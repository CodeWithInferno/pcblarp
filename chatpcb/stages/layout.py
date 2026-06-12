"""Stage 4: schematic -> placed + routed board + DRC (MOCKED).

Real implementation: kicad-tools placement optimizer + autorouter, then DRC
with manufacturer="pcbway" rules; DRC violations / unrouted nets raise
StageError with llm_feedback so the pipeline can ask Claude for a spec
revision. The mock emits a board skeleton and a clean DRC report.

Heavy routing offload: when CHATPCB_REMOTE_LAYOUT=1 and REDIS_URL are set,
the job is pushed to the Redis queue and a worker (chatpcb/worker.py, run
dockerized on Render or a Nebius box) executes it. The worker has no shared
filesystem with the API: artifact contents come back through the Redis
result payload and are written into out_dir here (fine for mock-sized text
files; TODO hand off via S3 once real Gerber-scale outputs exist).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..models import Spec
from . import StageError, injected_failure, slugify
from .schematic import SchematicResult

MANUFACTURER = "pcbway"
QUEUE_KEY = "chatpcb:layout:jobs"
RESULT_PREFIX = "chatpcb:layout:result:"


@dataclass
class LayoutResult:
    board_path: str
    drc_report_path: str
    drc_violations: int
    routing_completion_pct: float
    mocked: bool = True
    remote: bool = False


def build_layout(spec: Spec, schematic: SchematicResult, out_dir: Path) -> LayoutResult:
    failure = injected_failure("layout")
    if failure:
        raise failure
    del schematic  # mock derives everything from the spec
    if config.flag("CHATPCB_REMOTE_LAYOUT") and config.env("REDIS_URL"):
        return _run_remote(spec, out_dir)
    return run_local(spec, out_dir)


def run_local(spec: Spec, out_dir: Path) -> LayoutResult:
    """Placement + routing + DRC. Mock until kicad-tools is wired in.
    Also called directly by the worker process."""
    out_dir.mkdir(parents=True, exist_ok=True)
    board_path = out_dir / f"{slugify(spec.project.name)}.kicad_pcb"
    board_path.write_text(_mock_board(spec))

    report = {
        "manufacturer": MANUFACTURER,
        "violations": [],
        "unrouted_nets": 0,
        "routing_completion_pct": 100.0,
        "mocked": True,
    }
    drc_path = out_dir / "drc_report.json"
    drc_path.write_text(json.dumps(report, indent=2))

    violations = len(report["violations"])
    completion = float(report["routing_completion_pct"])
    if violations or completion < 100.0:
        raise StageError(
            f"DRC/routing failed: {violations} violations, "
            f"{completion:.1f}% routed",
            llm_feedback=(
                f"Board layout failed {MANUFACTURER} DRC with {violations} "
                f"violations and {completion:.1f}% routing completion. "
                "Consider a larger board outline or fewer blocks."
            ),
            metrics={
                "drc_violations": float(violations),
                "routing_completion_pct": completion,
            },
        )
    return LayoutResult(
        board_path=str(board_path),
        drc_report_path=str(drc_path),
        drc_violations=violations,
        routing_completion_pct=completion,
    )


def _run_remote(spec: Spec, out_dir: Path) -> LayoutResult:
    import redis

    client = redis.Redis.from_url(config.env("REDIS_URL"))
    job_id = uuid.uuid4().hex
    client.lpush(QUEUE_KEY, json.dumps({
        "job_id": job_id,
        "spec": spec.model_dump(),
    }))
    timeout = int(config.env("CHATPCB_LAYOUT_TIMEOUT_S", "300"))
    popped = client.blpop(f"{RESULT_PREFIX}{job_id}", timeout=timeout)
    if popped is None:
        raise StageError(
            f"remote layout job timed out after {timeout}s",
            llm_feedback=(
                "The autorouter worker timed out. Consider a simpler design "
                "with fewer blocks or a larger board."
            ),
        )
    data = json.loads(popped[1])
    if data.get("status") != "ok":
        raise StageError(
            data.get("error", "remote layout failed"),
            llm_feedback=data.get("llm_feedback"),
            metrics=data.get("metrics") or {},
        )
    # Materialize the worker's artifacts locally; no shared volume needed.
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (data.get("files") or {}).items():
        (out_dir / Path(name).name).write_text(content)
    body = data["result"]
    return LayoutResult(
        board_path=str(out_dir / Path(body["board_path"]).name),
        drc_report_path=str(out_dir / Path(body["drc_report_path"]).name),
        drc_violations=body["drc_violations"],
        routing_completion_pct=body["routing_completion_pct"],
        mocked=body.get("mocked", True),
        remote=True,
    )


def _mock_board(spec: Spec) -> str:
    size = spec.constraints.max_board_size_mm or (50.0, 40.0)
    lines = [
        "(kicad_pcb",
        "  (version 20240108)",
        '  (generator "chatpcb-mock")',
        f'  (gr_text "MOCK board {size[0]}x{size[1]}mm, '
        f'{len(spec.blocks)} blocks, mfr={MANUFACTURER}" (at 5 5))',
    ]
    lines.append(")")
    return "\n".join(lines) + "\n"
