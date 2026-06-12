# ChatPCB

Natural-language hardware idea in, fabrication-ready PCB files out (Gerbers,
BOM, pick-and-place for PCBWay).

```
idea ──> [1 spec] ──> [2 parts] ──> [3 schematic] ──> [4 layout] ──> [5 export]
          Claude       parts.csv     real circuits     real placement  real Gerbers
            │                        + .kicad_sch      + DRC checks    PnP, BOMs
            │                        (KiCad library)   (unrouted)      S3 / local
            └──── error feedback loop: any stage failure (JSON parse, ERC,
                  unsupported block, board too small) goes back to Claude for
                  a spec revision pass, max 3 retries, logged to telemetry
```

## Quickstart

```sh
make install     # uv venv (python 3.12) + editable install
make test
make demo        # full pipeline, mocked Claude + mocked stages, no API key
make demo-ui     # same, behind the web UI at http://localhost:8000
make demo-partial# layout fails on purpose: shows retries + partial results
make demo-live   # real Claude stage 1 (set ANTHROPIC_API_KEY or TF_* vars)
make sync-parts  # Airbyte LCSC sync, or local SQLite seed when unconfigured
make ingest-kb   # push design rules + datasheet snippets into Senso
```

Every run stays demo-able: export packages whatever exists (spec.json after
stage 1, bom.csv after stage 2, and so on), so a failed layout still gives
you download links and a BOM on screen.

## Sponsor tech

| Sponsor | Used for | Where |
|---|---|---|
| Anthropic Claude | Stage 1 spec compiler + error-feedback revision loop | `chatpcb/stages/spec.py` |
| TrueFoundry | Gateway for all Claude calls (`TF_GATEWAY_URL`) | `chatpcb/llm.py` |
| Composio | Share button: GitHub repo push + Gmail order summary | `chatpcb/integrations/composio_actions.py` |
| Senso | Design-rules knowledge layer injected into prompts | `chatpcb/integrations/senso_kb.py` |
| Guild.ai | Experiment tracking per pipeline run | `chatpcb/integrations/guild_tracking.py` |
| Airbyte | LCSC catalog sync into the parts table | `airbyte/`, `chatpcb/integrations/airbyte_lcsc.py` |
| ClickHouse | Per-attempt pipeline telemetry + dashboard | `chatpcb/telemetry.py` |
| Jua | Climate notes appended to outdoor specs | `chatpcb/integrations/jua.py` |
| Render | API + worker deployment blueprint | `render.yaml` |
| Nebius | Heavy autorouting worker host | `chatpcb/worker.py`, `docker/worker.Dockerfile` |
| OpenUI | Frontend restyle (planned; UI kept minimal for it) | `frontend/index.html` |
| PCBWay | Manufacturing DRC profile + capabilities doc | `chatpcb/stages/layout.py`, `docs/pcbway_capabilities.md` |

Each integration is an isolated module that degrades gracefully (env vars
unset = skip or local fallback), so the core pipeline never blocks on a
sponsor service. Install the optional SDKs with `pip install -e ".[sponsors]"`.

## Stage status

| Stage | Module | Status |
|---|---|---|
| 1 spec | `chatpcb/stages/spec.py` | Real. Claude via `prompts/stage1_spec.md`, validated by pydantic, parse errors fed back for retry. |
| 2 parts | `chatpcb/stages/parts.py` | Real against `data/parts.csv` (~45 seeded parts, stand-in for an Airbyte LCSC sync; LCSC ids are seed data, verify before ordering). |
| 3 schematic | `chatpcb/stages/schematic.py` | Real. Block circuits (`chatpcb/eda/blocks.py`, 24 of 40 catalog blocks) instantiate symbols vendored from the official KiCad libraries, the netlist engine resolves every pin (GPIO allocation, I2C/SPI/UART/USB buses, power topology), and a self-contained `.kicad_sch` is generated. Unsupported blocks feed the supported list back to Claude for a spec revision. |
| 4 layout | `chatpcb/stages/layout.py` | Real placement (MaxRects over courtyards), real `.kicad_pcb` with netted pads, honest checks (courtyard overlap, outline fit -> revision loop). **Routing not implemented yet**: boards ship placed-but-unrouted with the ratsnest visible in KiCad. Offloads to the Redis worker when configured. |
| 5 export | `chatpcb/stages/export.py` | Real Gerbers (RS-274X pads/mask/outline + Excellon drill, generated directly from pad geometry), real pick-and-place from placement, assembly BOM, packaging. S3 presigned URLs when `S3_BUCKET` is set. |

The remaining gap to production fab outputs is routing (tracks + zones) and
silkscreen; everything else in the export is real geometry. Vendored library
components live in `data/kicad_library/` (CC-BY-SA 4.0 w/ KiCad exception);
refresh with `make fetch-libs`.

## Key pieces

- `chatpcb/models.py` is the spec contract. It mirrors the JSON schema inside
  `prompts/stage1_spec.md`; change them together. `BLOCK_CATALOG` must also
  stay in sync with the prompt's catalog section (longer term, generate both
  from the real block library).
- `chatpcb/pipeline.py` owns the error feedback loop: a downstream failure
  with `llm_feedback` triggers a Claude spec revision, then re-runs from
  stage 2. Bounded by `CHATPCB_MAX_STAGE_ATTEMPTS` and
  `CHATPCB_MAX_SPEC_REVISIONS`.
- `chatpcb/telemetry.py` logs every attempt (durations, DRC violations,
  routing %, retries) to ClickHouse when `CLICKHOUSE_URL` is set, else to
  `artifacts/telemetry.jsonl`. The UI dashboard reads `/api/dashboard`.
- `chatpcb/llm.py` routes all Claude calls through the TrueFoundry gateway
  when `TF_GATEWAY_URL` is set, direct API otherwise.
- `chatpcb/integrations/jua.py` appends climate notes to outdoor specs
  (stubbed Jua client).
- `frontend/index.html` is deliberately minimal; restyle with OpenUI later.

## Deploy

- **Render**: `render.yaml` defines the web service plus a dockerized layout
  worker. Set secrets in the dashboard.
- **Nebius (heavy routing)**: `make docker-worker`, run the image on a Nebius
  box with the shared `REDIS_URL`, and set `CHATPCB_REMOTE_LAYOUT=1` on the
  API. No shared filesystem needed: artifact contents return through the
  Redis result payload (TODO: hand off via S3 once real Gerber-scale outputs
  exist).

## Environment

See `.env.example` for the full list. Nothing is required for `make demo`.
