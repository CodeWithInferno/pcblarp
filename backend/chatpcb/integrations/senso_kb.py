"""Senso knowledge layer: design rules and parts context for prompts.

Ingests docs/pcbway_capabilities.md plus per-part "datasheet" snippets
(generated from the parts table) into Senso, then serves search queries that
spec.py injects into the Claude prompt as a <design_rules> block.

Isolation guarantee: every public function degrades gracefully. With no
SENSO_API_KEY (or on any Senso error) queries fall back to ranking sections
of the local markdown, so the core pipeline never blocks on Senso.

Ingest once per content change:  python -m chatpcb.integrations.senso_kb
"""

from __future__ import annotations

import logging

from .. import config

log = logging.getLogger(__name__)

# TODO: verify endpoint paths against the current Senso API reference.
DEFAULT_BASE_URL = "https://sdk.senso.ai/api/v1"
TIMEOUT_S = 10


def _enabled() -> bool:
    return bool(config.env("SENSO_API_KEY"))


def design_rules_context(query: str, top_k: int = 3, max_chars: int = 1800) -> str:
    """Top design-rule snippets for `query`, joined for prompt injection.
    Senso when configured, local markdown ranking otherwise. Never raises."""
    if _enabled():
        try:
            return _search_remote(query, top_k, max_chars)
        except Exception as exc:
            log.warning("senso search failed, using local fallback: %s", exc)
    try:
        return _search_local(query, max_chars)
    except Exception as exc:
        log.warning("local design-rules fallback failed: %s", exc)
        return ""


def _search_remote(query: str, top_k: int, max_chars: int) -> str:
    import httpx

    base = config.env("SENSO_BASE_URL", DEFAULT_BASE_URL)
    resp = httpx.post(
        f"{base}/search",
        headers={"X-API-Key": config.env("SENSO_API_KEY")},
        json={"query": query, "max_results": top_k},
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    chunks = [
        (r.get("content") or "").strip()
        for r in resp.json().get("results", [])
    ]
    return "\n---\n".join(c for c in chunks if c)[:max_chars]


def _search_local(query: str, max_chars: int) -> str:
    """Rank the ## sections of the local capabilities doc by keyword overlap."""
    doc = (config.DOCS_DIR / "pcbway_capabilities.md").read_text()
    sections = []
    for raw in doc.split("\n## ")[1:]:  # skip the title/preamble
        title, _, body = raw.partition("\n")
        sections.append((title.strip(), body.strip()))

    words = {w for w in query.lower().split() if len(w) > 3}
    scored = sorted(
        sections,
        key=lambda s: -len(words & set((s[0] + " " + s[1]).lower().split())),
    )
    picked: list[str] = []
    used = 0
    for title, body in scored:
        chunk = f"{title}: {body}"
        if used + len(chunk) > max_chars:
            break
        picked.append(chunk)
        used += len(chunk)
        if len(picked) >= 3:
            break
    return "\n---\n".join(picked)


# ---------------------------------------------------------------------------
# Ingestion (one-off CLI)
# ---------------------------------------------------------------------------

def ingest() -> int:
    """Push the capabilities doc + per-part datasheet snippets into Senso.
    Returns the number of documents ingested."""
    if not _enabled():
        raise SystemExit("SENSO_API_KEY is not set; nothing to ingest into")
    import httpx

    from ..stages.parts import load_parts_table

    base = config.env("SENSO_BASE_URL", DEFAULT_BASE_URL)
    headers = {"X-API-Key": config.env("SENSO_API_KEY")}

    documents = [{
        "title": "PCBWay manufacturing capabilities",
        "text": (config.DOCS_DIR / "pcbway_capabilities.md").read_text(),
    }]
    # Until real datasheet PDFs land, each parts-table row becomes a snippet.
    for row in load_parts_table():
        documents.append({
            "title": f"datasheet: {row['mpn']}",
            "text": (
                f"{row['mpn']} ({row['catalog_block']}/{row.get('role', 'main')}): "
                f"{row['description']}. Package {row.get('package') or 'n/a'}, "
                f"unit price ${row.get('unit_price_usd') or '?'}, "
                f"LCSC {row.get('lcsc') or 'n/a'}."
            ),
        })

    for doc in documents:
        resp = httpx.post(
            f"{base}/content/raw", headers=headers, json=doc, timeout=TIMEOUT_S
        )
        resp.raise_for_status()
    return len(documents)


if __name__ == "__main__":
    count = ingest()
    print(f"ingested {count} documents into Senso")
