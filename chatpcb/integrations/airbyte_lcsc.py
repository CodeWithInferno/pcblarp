"""Airbyte-backed parts table (LCSC catalog sync).

The real sync runs inside Airbyte (configs in airbyte/): a File source
pointing at an LCSC parts CSV export syncs into a Postgres `parts` table,
full-refresh overwrite. parts.load_parts_table() reads that table when
PARTS_DB_URL is set and falls back to data/parts.csv otherwise.

This module is the `make sync-parts` entrypoint:
  1. If AIRBYTE_API_URL + AIRBYTE_CONNECTION_ID are set, trigger a sync job
     through the Airbyte API.
  2. Otherwise (local dev) seed an equivalent SQLite table from
     data/parts.csv so the DB code path is exercised without Airbyte.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .. import config

PARTS_COLUMNS = (
    "catalog_block", "role", "mpn", "lcsc", "description", "package",
    "unit_price_usd", "stock",
)
DEFAULT_SQLITE_PATH = "data/parts.db"


def trigger_airbyte_sync() -> bool:
    """Kick off the Airbyte connection sync. Returns False when unconfigured."""
    api_url = config.env("AIRBYTE_API_URL")
    connection_id = config.env("AIRBYTE_CONNECTION_ID")
    if not api_url or not connection_id:
        return False
    import httpx

    headers = {}
    if config.env("AIRBYTE_API_TOKEN"):
        headers["Authorization"] = f"Bearer {config.env('AIRBYTE_API_TOKEN')}"
    resp = httpx.post(
        f"{api_url.rstrip('/')}/v1/jobs",
        headers=headers,
        json={"jobType": "sync", "connectionId": connection_id},
        timeout=30,
    )
    resp.raise_for_status()
    return True


def seed_sqlite(db_path: Path, csv_path: Path | None = None) -> int:
    """Local stand-in for the Airbyte destination: load the CSV into a
    `parts` table shaped like the synced one. Returns the row count."""
    csv_path = csv_path or (config.DATA_DIR / "parts.csv")
    with open(csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS parts")
        conn.execute(
            """CREATE TABLE parts (
                catalog_block TEXT, role TEXT, mpn TEXT, lcsc TEXT,
                description TEXT, package TEXT,
                unit_price_usd REAL, stock INTEGER
            )"""
        )
        conn.executemany(
            f"INSERT INTO parts ({', '.join(PARTS_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(PARTS_COLUMNS))})",
            [
                (
                    r["catalog_block"], r.get("role") or "main", r["mpn"],
                    r.get("lcsc") or None, r["description"],
                    r.get("package") or None,
                    float(r["unit_price_usd"]) if r.get("unit_price_usd") else None,
                    int(r["stock"]) if r.get("stock") else 0,
                )
                for r in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def load_from_db(db_url: str) -> list[dict]:
    """Read the `parts` table from sqlite:/// or postgresql:// URLs,
    returning rows shaped like csv.DictReader rows."""
    query = f"SELECT {', '.join(PARTS_COLUMNS)} FROM parts"
    if db_url.startswith("sqlite:///"):
        path = Path(db_url[len("sqlite:///"):])
        if not path.is_absolute():
            # cwd-independent: the documented sqlite:///data/parts.db URL must
            # work no matter where the server was launched from.
            path = config.REPO_ROOT / path
        if not path.exists():
            # sqlite3.connect would silently create an empty stray DB here.
            raise FileNotFoundError(f"sqlite parts DB not found: {path}")
        conn = sqlite3.connect(path)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query)]
        finally:
            conn.close()
    if db_url.startswith(("postgres://", "postgresql://")):
        import psycopg  # sponsors extra

        # Bounded connect: a down Postgres must degrade to the CSV fallback
        # quickly, not stall every parts attempt for the OS TCP timeout.
        with psycopg.connect(db_url, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(query)
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
    raise ValueError(f"unsupported PARTS_DB_URL scheme: {db_url}")


def main() -> None:
    if trigger_airbyte_sync():
        print("Airbyte sync triggered; set PARTS_DB_URL to the Postgres "
              "destination to use the synced table.")
        return
    db_path = config.REPO_ROOT / DEFAULT_SQLITE_PATH
    count = seed_sqlite(db_path)
    print(f"Airbyte not configured (AIRBYTE_API_URL/AIRBYTE_CONNECTION_ID); "
          f"seeded {count} parts into {db_path} from data/parts.csv instead.")
    print(f"Use it with: PARTS_DB_URL=sqlite:///{db_path}")


if __name__ == "__main__":
    main()
