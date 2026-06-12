"""FastAPI app: minimal single-page UI, run API, telemetry dashboard.

The frontend polls GET /api/runs/{id} for live stage progress (we will
restyle with OpenUI later). Runs are kept in memory; artifacts are served
from the artifacts dir (or via S3 presigned URLs when configured, in which
case export URLs point at S3 directly).
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, telemetry
from .models import RunState
from .pipeline import new_run_state, run_pipeline

log = logging.getLogger(__name__)

app = FastAPI(title="ChatPCB", version="0.1.0")

RUNS: dict[str, RunState] = {}

_RUN_ID_RE = re.compile(r"[0-9a-f]{8,32}")


class RunRequest(BaseModel):
    idea: str


@app.post("/api/runs")
def create_run(body: RunRequest, background: BackgroundTasks) -> dict:
    idea = body.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="idea is empty")
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = new_run_state(run_id, idea)
    background.add_task(_execute, run_id, idea)
    return {"run_id": run_id}


def _execute(run_id: str, idea: str) -> None:
    def on_update(state: RunState) -> None:
        RUNS[run_id] = state.model_copy(deep=True)

    try:
        RUNS[run_id] = run_pipeline(idea, run_id=run_id, on_update=on_update)
    except Exception as exc:  # never lose the run record
        log.exception("pipeline crashed for run %s", run_id)
        state = RUNS[run_id]
        state.status = "failed"
        for record in state.stages:
            if record.status == "running":
                record.status = "failed"
                record.error = str(exc)
            elif record.status == "pending":
                record.status = "skipped"
        state.events.append(f"pipeline crashed: {exc}")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> RunState:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="unknown run id")
    return RUNS[run_id]


@app.get("/api/dashboard")
def dashboard() -> dict:
    return telemetry.dashboard_summary()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mock_llm": config.flag("CHATPCB_MOCK_LLM")}


@app.get("/artifacts/{run_id}/{filename}")
def get_artifact(run_id: str, filename: str) -> FileResponse:
    # run_id must look like a run id (rejects "." / ".." / anything that
    # would resolve outside a run directory, e.g. the telemetry log at the
    # artifacts root) and the file must live directly inside that run dir.
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    base = config.artifacts_dir().resolve()
    path = (base / run_id / filename).resolve()
    if path.parent != base / run_id or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "index.html")
