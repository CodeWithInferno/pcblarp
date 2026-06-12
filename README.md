# ChatPCB

Natural-language hardware idea in, fabrication-ready PCB files out (Gerbers,
BOM, pick-and-place for PCBWay).

```
idea ──> [1 spec] ──> [2 parts] ──> [3 schematic] ──> [4 layout] ──> [5 export]
          Claude       parts.csv     kicad-tools       kicad-tools     S3 / local
            │                        (mocked)          + pcbway DRC    presigned
            │                                          (mocked)        URLs
            └──── error feedback loop: any stage failure (JSON parse, ERC,
                  DRC, routing) goes back to Claude for a spec revision pass,
                  max 3 retries, every attempt logged to telemetry
```

## Quickstart

```sh
make install     # uv venv (python 3.12) + editable install
make test
make demo        # full pipeline, mocked Claude + mocked stages, no API key
make demo-ui     # same, behind the web UI at http://localhost:8000
make demo-partial# layout fails on purpose: shows retries + partial results
make demo-live   # real Claude stage 1 (set ANTHROPIC_API_KEY or TF_* vars)
```

Every run stays demo-able: export packages whatever exists (spec.json after
stage 1, bom.csv after stage 2, and so on), so a failed layout still gives
you download links and a BOM on screen.

## Stage status

| Stage | Module | Status |
|---|---|---|
| 1 spec | `chatpcb/stages/spec.py` | Real. Claude via `prompts/stage1_spec.md`, validated by pydantic, parse errors fed back for retry. |
| 2 parts | `chatpcb/stages/parts.py` | Real against `data/parts.csv` (~45 seeded parts, stand-in for an Airbyte LCSC sync; LCSC ids are seed data, verify before ordering). |
| 3 schematic | `chatpcb/stages/schematic.py` | Mocked. Emits netlist.json + .kicad_sch skeleton. Replace with kicad-tools circuit blocks (`pip install -e ".[eda]"`). |
| 4 layout | `chatpcb/stages/layout.py` | Mocked. Emits board + clean pcbway DRC report. Replace with kicad-tools placement + autoroute. Offloads to the Redis worker when configured. |
| 5 export | `chatpcb/stages/export.py` | Real packaging, mocked Gerber/PnP content. S3 presigned URLs when `S3_BUCKET` is set. |

Replace mocks one stage at a time; each stage has a stable result dataclass
the pipeline and tests already exercise.

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
