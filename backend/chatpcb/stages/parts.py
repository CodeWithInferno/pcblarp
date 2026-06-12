"""Stage 2: match spec blocks to real parts.

The parts table comes from the Airbyte-synced LCSC catalog when PARTS_DB_URL
is set (see airbyte/ and `make sync-parts`); data/parts.csv is the seed/
fallback so the stage never blocks on the database. Keep the column set
identical in both.

Some catalog blocks need several physical parts (a LiPo block is charger +
protection + FET + connector), so rows carry a `role`. Per (catalog_block,
role) we prefer a part hinted in the spec's candidate_parts, else the
cheapest in-stock row. Unmatched blocks do not fail the stage; they are
reported (with Senso knowledge-layer notes when available) so the demo
always shows partial results and the revision loop has context.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .. import config
from ..models import BomLine, PartsResult, Spec
from . import injected_failure

log = logging.getLogger(__name__)

# These use the MCU module's radio; no BOM line needed.
INTEGRATED_BLOCKS = {"comm_ble_builtin", "comm_wifi_builtin"}


def load_parts_table(path: Path | None = None) -> list[dict]:
    if path is None and config.env("PARTS_DB_URL"):
        try:
            from ..integrations.airbyte_lcsc import load_from_db

            rows = load_from_db(config.env("PARTS_DB_URL"))
            if rows:
                return rows
            log.warning("parts DB is empty (sync not run yet?); "
                        "falling back to CSV")
        except Exception as exc:
            log.warning("parts DB unavailable (%s); falling back to CSV", exc)
    path = path or (config.DATA_DIR / "parts.csv")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def match_parts(spec: Spec, table: list[dict] | None = None) -> PartsResult:
    failure = injected_failure("parts")
    if failure:
        raise failure
    table = table if table is not None else load_parts_table()

    by_block: dict[str, list[dict]] = {}
    for row in table:
        by_block.setdefault(row["catalog_block"], []).append(row)

    bom: list[BomLine] = []
    unmatched: list[str] = []
    for block in spec.blocks:
        if block.catalog_block in INTEGRATED_BLOCKS:
            bom.append(BomLine(
                block_id=block.id, catalog_block=block.catalog_block,
                role="main", mpn=None, lcsc=None,
                description="Integrated in MCU module radio", package=None,
                qty=0, unit_price_usd=None, status="integrated",
            ))
            continue

        rows = by_block.get(block.catalog_block, [])
        if not rows:
            unmatched.append(block.id)
            bom.append(BomLine(
                block_id=block.id, catalog_block=block.catalog_block,
                role="main", mpn=None, lcsc=None,
                description="No part in local parts table", package=None,
                qty=1, unit_price_usd=None, status="no_match",
            ))
            continue

        hinted = {p.mpn for p in block.candidate_parts}
        roles: dict[str, list[dict]] = {}
        for row in rows:
            roles.setdefault(row.get("role") or "main", []).append(row)
        for role, candidates in sorted(roles.items()):
            pick = _pick(candidates, hinted)
            price = pick.get("unit_price_usd")
            bom.append(BomLine(
                block_id=block.id, catalog_block=block.catalog_block,
                role=role, mpn=pick["mpn"], lcsc=pick.get("lcsc") or None,
                description=pick["description"],
                package=pick.get("package") or None, qty=1,
                unit_price_usd=float(price) if price else None,
                status="matched",
            ))

    # Senso knowledge layer: pull part-selection context for unmatched blocks
    # so the spec revision prompt has something concrete to work with.
    kb_notes: list[str] = []
    if unmatched:
        try:
            from ..integrations import senso_kb

            blocks = ", ".join(
                b.catalog_block for b in spec.blocks if b.id in set(unmatched)
            )
            context = senso_kb.design_rules_context(
                f"part selection and alternatives for: {blocks}", top_k=2
            )
            if context:
                kb_notes.append(context)
        except Exception as exc:
            log.warning("senso kb notes skipped: %s", exc)

    total = sum((line.unit_price_usd or 0.0) * line.qty for line in bom)
    return PartsResult(
        bom=bom, unmatched_blocks=unmatched, total_cost_usd=round(total, 2),
        kb_notes=kb_notes,
    )


def _pick(candidates: list[dict], hinted: set[str]) -> dict:
    # Prefer the spec's candidate_parts hints; tolerate suffix differences
    # ("ESP32-C3-MINI-1" should match "ESP32-C3-MINI-1-N4").
    for row in candidates:
        for hint in hinted:
            if row["mpn"] == hint or row["mpn"].startswith(hint) or hint.startswith(row["mpn"]):
                return row
    in_stock = [r for r in candidates if int(r.get("stock") or 0) > 0]
    pool = in_stock or candidates
    return min(pool, key=lambda r: float(r.get("unit_price_usd") or 1e9))
