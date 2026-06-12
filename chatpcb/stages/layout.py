"""Stage 4: design -> placed board + DRC report.

Real placement: the netlist design is rebuilt from the spec (deterministic),
footprints are packed onto the board outline (MaxRects), and a real
.kicad_pcb is generated with every pad bound to its net. Checks are honest:
courtyard overlap and outline overflow raise StageError with llm_feedback
(e.g. "board too small") so the revision loop can fix the spec.

Routing is NOT implemented yet and is not faked: the DRC report says
routed=false and lists the unrouted net count; KiCad shows the ratsnest.

Heavy routing offload: when CHATPCB_REMOTE_LAYOUT=1 and REDIS_URL are set,
the job is pushed to the Redis queue and a worker (chatpcb/worker.py, run
dockerized on Render or a Nebius box) executes it. The worker has no shared
filesystem with the API: artifact contents come back through the Redis
result payload and are written into out_dir here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..eda.board_gen import build_board, generate_board
from ..eda.netlist import DesignError, build_design
from ..models import Spec
from . import StageError, injected_failure, slugify
from .schematic import SchematicResult

MANUFACTURER = "pcbway"
QUEUE_KEY = "chatpcb:layout:jobs"
RESULT_PREFIX = "chatpcb:layout:result:"

# Recorded per run by Guild.ai experiment tracking.
ROUTER_SETTINGS = {
    "manufacturer": MANUFACTURER,
    "placement_optimizer": "maxrects-bssf",
    "autorouter": "none (placement only)",
}


@dataclass
class LayoutResult:
    board_path: str
    drc_report_path: str
    drc_violations: int
    routing_completion_pct: float
    mocked: bool = False
    remote: bool = False
    component_count: int = 0
    board_size_mm: tuple[float, float] = (0.0, 0.0)


def build_layout(spec: Spec, schematic: SchematicResult, out_dir: Path) -> LayoutResult:
    failure = injected_failure("layout")
    if failure:
        raise failure
    del schematic  # design is rebuilt deterministically from the spec
    if config.flag("CHATPCB_REMOTE_LAYOUT") and config.env("REDIS_URL"):
        return _run_remote(spec, out_dir)
    return run_local(spec, out_dir)


def run_local(spec: Spec, out_dir: Path) -> LayoutResult:
    """Placement + checks. Also called directly by the worker process."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        design = build_design(spec)
    except DesignError as exc:
        raise StageError(str(exc), llm_feedback=exc.llm_feedback) from exc

    board = build_board(design, spec.constraints.max_board_size_mm)

    title = slugify(spec.project.name)
    board_path = out_dir / f"{title}.kicad_pcb"
    board_path.write_text(generate_board(design, board, title))

    report = {
        "manufacturer": MANUFACTURER,
        "board_size_mm": [board.width, board.height],
        "components_placed": len(board.placements),
        "violations": board.violations,
        "routed": False,
        "unrouted_nets": board.unrouted_nets,
        "routing_completion_pct": 0.0,
        "checks": ["courtyard_overlap", "board_outline_fit"],
        "notes": [
            "placement is real (MaxRects over courtyards from the official "
            "KiCad footprints); routing is not implemented yet, open the "
            "board in KiCad to see the ratsnest",
        ],
        "mocked": False,
    }
    drc_path = out_dir / "drc_report.json"
    drc_path.write_text(json.dumps(report, indent=2))

    if board.violations:
        size = spec.constraints.max_board_size_mm
        raise StageError(
            f"placement failed: {'; '.join(board.violations)}",
            llm_feedback=(
                f"Board placement failed {MANUFACTURER} checks: "
                f"{'; '.join(board.violations)}. "
                + (
                    f"Increase max_board_size_mm (currently {size[0]}x{size[1]}mm) "
                    "or remove blocks. Note ESP32 module courtyards include the "
                    "antenna keep-out and are larger than the module body."
                    if size else "Reduce the number of blocks."
                )
            ),
            metrics={
                "drc_violations": float(len(board.violations)),
                "routing_completion_pct": 0.0,
            },
        )

    return LayoutResult(
        board_path=str(board_path),
        drc_report_path=str(drc_path),
        drc_violations=0,
        routing_completion_pct=0.0,
        mocked=False,
        component_count=len(board.placements),
        board_size_mm=(board.width, board.height),
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
                "The layout worker timed out. Consider a simpler design "
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
        mocked=body.get("mocked", False),
        remote=True,
        component_count=body.get("component_count", 0),
        board_size_mm=tuple(body.get("board_size_mm", (0.0, 0.0))),
    )
