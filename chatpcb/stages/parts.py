"""Stage 2: match spec blocks to real parts.

The parts table is data/parts.csv, a hand-seeded stand-in for the LCSC
catalog. Production plan: Airbyte syncs LCSC into the warehouse and this
table is regenerated from it, so keep the column set boring.

Some catalog blocks need several physical parts (a LiPo block is charger +
protection + FET + connector), so rows carry a `role`. Per (catalog_block,
role) we prefer a part hinted in the spec's candidate_parts, else the
cheapest in-stock row. Unmatched blocks do not fail the stage; they are
reported so the demo always shows partial results.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .. import config
from ..models import BomLine, PartsResult, Spec
from . import injected_failure

# These use the MCU module's radio; no BOM line needed.
INTEGRATED_BLOCKS = {"comm_ble_builtin", "comm_wifi_builtin"}


def load_parts_table(path: Path | None = None) -> list[dict]:
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

    total = sum((line.unit_price_usd or 0.0) * line.qty for line in bom)
    return PartsResult(
        bom=bom, unmatched_blocks=unmatched, total_cost_usd=round(total, 2)
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
