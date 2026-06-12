# Airbyte: LCSC catalog -> parts table

Connection spec for syncing an LCSC parts CSV export into the `parts` table
that `chatpcb/stages/parts.py` reads (via `PARTS_DB_URL`). data/parts.csv
stays as the seed/fallback, so nothing here blocks the core pipeline.

## Files

- `source_lcsc_csv.json`: File (CSV over HTTPS) source pointing at the LCSC
  parts export. Swap `url` for your real export location.
- `destination_postgres.json`: Postgres destination (host/db/user from env
  or the Airbyte UI secrets).
- `connection_parts.json`: the connection: stream `parts`, full refresh +
  overwrite, manual schedule (we trigger it from `make sync-parts`).

## Setup (local Airbyte via abctl)

```sh
abctl local install
# create source, destination, connection from the JSON configs via the UI
# or the Airbyte API, then note the connection id
export AIRBYTE_API_URL=http://localhost:8000/api/public
export AIRBYTE_CONNECTION_ID=<uuid>
export AIRBYTE_API_TOKEN=<token>          # if auth is enabled
export PARTS_DB_URL=postgresql://airbyte:***@localhost:5432/chatpcb
make sync-parts
```

Without `AIRBYTE_*` configured, `make sync-parts` seeds an equivalent local
SQLite table from data/parts.csv (then `PARTS_DB_URL=sqlite:///data/parts.db`)
so the DB code path is exercised end to end.
