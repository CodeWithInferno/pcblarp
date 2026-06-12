"""Pipeline orchestrator.

Stage order: spec -> parts -> schematic -> layout -> export.

Error feedback loop: any downstream stage failure that carries llm_feedback
triggers one spec revision pass through Claude (bounded by
CHATPCB_MAX_SPEC_REVISIONS and per-stage CHATPCB_MAX_STAGE_ATTEMPTS), then
the pipeline re-runs from `parts` against the revised spec. Stage 1 handles
its own JSON-parse retry conversation internally.

Export always runs when a spec exists, packaging whatever earlier stages
produced, so a failed run still yields demo-able partial results. Every
attempt of every stage is logged to telemetry.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import config, telemetry
from .integrations import guild_tracking, jua
from .models import STAGE_ORDER, PartsResult, RunState, Spec, StageRecord
from .stages import StageError
from .stages import export as export_stage
from .stages import layout as layout_stage
from .stages import parts as parts_stage
from .stages import schematic as schematic_stage
from .stages import spec as spec_stage


@dataclass
class _Context:
    run_id: str
    out_dir: Path
    spec: Optional[Spec] = None
    parts: Optional[PartsResult] = None
    schematic: Optional[schematic_stage.SchematicResult] = None
    layout: Optional[layout_stage.LayoutResult] = None


def new_run_state(run_id: str, idea: str) -> RunState:
    return RunState(
        run_id=run_id,
        idea=idea,
        created_at=datetime.now(timezone.utc).isoformat(),
        stages=[StageRecord(name=name) for name in STAGE_ORDER],
    )


def run_pipeline(
    idea: str,
    run_id: str | None = None,
    on_update: Callable[[RunState], None] | None = None,
) -> RunState:
    run_id = run_id or uuid.uuid4().hex[:12]
    run = new_run_state(run_id, idea)
    run.status = "running"
    ctx = _Context(run_id=run_id, out_dir=config.artifacts_dir() / run_id)

    def push(message: str | None = None) -> None:
        if message:
            run.events.append(message)
        if on_update:
            on_update(run)

    push(f"run {run_id} started")

    if not _run_spec_stage(run, ctx, push):
        _track_experiment(run, push)
        return run

    if ctx.spec.status == "ok":
        _run_downstream_stages(run, ctx, push)
    else:
        # Claude flagged the spec itself; do not build, but still export the
        # spec so the user sees why.
        for name in ("parts", "schematic", "layout"):
            _record(run, name).status = "skipped"
        if ctx.spec.status == "needs_clarification":
            push("spec needs clarification before building:")
            for question in ctx.spec.clarification_questions:
                push(f"clarify: {question}")
        else:
            push(
                "design is infeasible with the current block catalog: "
                + _short(ctx.spec.feasibility.notes)
            )
    _run_export_stage(run, ctx, push)

    run.status = "done" if all(r.status == "ok" for r in run.stages) else "partial"
    _track_experiment(run, push)
    push(f"pipeline finished: {run.status}")
    return run


def _track_experiment(run: RunState, push) -> None:
    """Guild.ai experiment tracking; isolated so it can never block a run."""
    try:
        guild_tracking.track_run(run)
    except Exception as exc:
        push(f"experiment tracking skipped: {_short(str(exc))}")


# ---------------------------------------------------------------------------
# Stage 1: spec (internal conversational retry)
# ---------------------------------------------------------------------------

def _run_spec_stage(run: RunState, ctx: _Context, push) -> bool:
    record = _record(run, "spec")
    record.status = "running"
    push()

    def log_attempt(attempt, status, duration_ms, error=None):
        record.attempts = attempt
        telemetry.log_stage_attempt(
            ctx.run_id, "spec", attempt, status, duration_ms, error=error
        )
        if error:
            push(f"spec attempt {attempt} failed: {_short(error)}")

    started = time.monotonic()
    try:
        ctx.spec, _ = spec_stage.generate_spec(run.idea, log_attempt=log_attempt)
        record.status = "ok"
        run.spec = ctx.spec
        # Jua integration: outdoor designs get climate notes appended.
        if ctx.spec.constraints.environment == "outdoor":
            ctx.spec.assumptions.extend(jua.climate_notes())
            push("outdoor environment: appended Jua climate notes to spec")
    except StageError as exc:
        record.status = "failed"
        record.error = str(exc)
    record.duration_ms = (time.monotonic() - started) * 1000
    push(f"spec stage {record.status}")

    if record.status == "failed":
        for other in run.stages:
            if other.status == "pending":
                other.status = "skipped"
        run.status = "failed"
        push("pipeline failed: no valid spec produced")
        return False
    return True


# ---------------------------------------------------------------------------
# Stages 2-4 with the spec revision loop
# ---------------------------------------------------------------------------

def _run_downstream_stages(run: RunState, ctx: _Context, push) -> None:
    downstream = [
        ("parts", _do_parts),
        ("schematic", _do_schematic),
        ("layout", _do_layout),
    ]
    index = 0
    while index < len(downstream):
        name, fn = downstream[index]
        record = _record(run, name)
        record.status = "running"
        record.attempts += 1
        push()
        started = time.monotonic()
        try:
            fn(ctx, record)
        except Exception as exc:
            duration = (time.monotonic() - started) * 1000
            record.duration_ms += duration
            record.error = str(exc)
            feedback = exc.llm_feedback if isinstance(exc, StageError) else None
            metrics = exc.metrics if isinstance(exc, StageError) else {}
            telemetry.log_stage_attempt(
                ctx.run_id, name, record.attempts, "failed", duration,
                error=str(exc), metrics=metrics,
            )
            push(f"{name} attempt {record.attempts} failed: {_short(str(exc))}")

            if (
                feedback
                and record.attempts < config.max_stage_attempts()
                and run.revision_count < config.max_spec_revisions()
            ):
                # Senso kb_notes gathered during parts matching give the
                # revision concrete part-selection context.
                if ctx.parts and ctx.parts.kb_notes:
                    feedback += ("\n\nParts knowledge-layer notes:\n"
                                 + "\n".join(ctx.parts.kb_notes))

                revision_no = run.revision_count + 1

                def log_revision(attempt, status, duration_ms, error=None,
                                 _n=revision_no):
                    telemetry.log_stage_attempt(
                        ctx.run_id, "spec_revision", attempt, status,
                        duration_ms, error=error,
                        metrics={"revision": float(_n)},
                    )

                try:
                    ctx.spec = spec_stage.revise_spec_with_error(
                        ctx.spec, name, feedback, log_attempt=log_revision
                    )
                    run.spec = ctx.spec
                    run.revision_count += 1
                    ctx.parts = ctx.schematic = ctx.layout = None
                    run.bom = None
                    for other_name, _ in downstream:
                        other = _record(run, other_name)
                        other.status = "pending"
                        other.error = None
                        other.metrics = {}
                    push(
                        f"spec revised by Claude (revision {run.revision_count}); "
                        "re-running from parts"
                    )
                    index = 0
                    continue
                except Exception as revision_exc:
                    push(f"spec revision failed: {_short(str(revision_exc))}")

            record.status = "failed"
            for later_name, _ in downstream[index + 1:]:
                later = _record(run, later_name)
                if later.status == "pending":
                    later.status = "skipped"
            push(f"{name} stage failed; continuing to export with partial results")
            return

        duration = (time.monotonic() - started) * 1000
        record.duration_ms += duration
        record.status = "ok"
        record.error = None
        if name == "parts":
            run.bom = ctx.parts
        telemetry.log_stage_attempt(
            ctx.run_id, name, record.attempts, "ok", duration,
            metrics=record.metrics,
        )
        push(f"{name} stage ok")
        index += 1


def _do_parts(ctx: _Context, record: StageRecord) -> None:
    ctx.parts = parts_stage.match_parts(ctx.spec)
    record.metrics = {
        "bom_lines": float(len(ctx.parts.bom)),
        "unmatched_blocks": float(len(ctx.parts.unmatched_blocks)),
        "total_cost_usd": ctx.parts.total_cost_usd,
    }


def _do_schematic(ctx: _Context, record: StageRecord) -> None:
    ctx.schematic = schematic_stage.build_schematic(ctx.spec, ctx.parts, ctx.out_dir)
    record.metrics = {"erc_errors": float(ctx.schematic.erc_errors)}


def _do_layout(ctx: _Context, record: StageRecord) -> None:
    ctx.layout = layout_stage.build_layout(ctx.spec, ctx.schematic, ctx.out_dir)
    record.metrics = {
        "drc_violations": float(ctx.layout.drc_violations),
        "routing_completion_pct": ctx.layout.routing_completion_pct,
    }


# ---------------------------------------------------------------------------
# Stage 5: export (always runs when a spec exists)
# ---------------------------------------------------------------------------

def _run_export_stage(run: RunState, ctx: _Context, push) -> None:
    record = _record(run, "export")
    record.status = "running"
    record.attempts += 1
    push()
    started = time.monotonic()
    try:
        result = export_stage.export_artifacts(
            ctx.run_id, ctx.spec, ctx.parts, ctx.schematic, ctx.layout,
            ctx.out_dir,
        )
        record.artifacts = result.urls
        record.status = "ok"
        duration = (time.monotonic() - started) * 1000
        telemetry.log_stage_attempt(
            ctx.run_id, "export", record.attempts, "ok", duration,
            metrics={"artifact_count": float(len(result.files))},
        )
    except Exception as exc:
        duration = (time.monotonic() - started) * 1000
        record.status = "failed"
        record.error = str(exc)
        telemetry.log_stage_attempt(
            ctx.run_id, "export", record.attempts, "failed", duration,
            error=str(exc),
        )
    record.duration_ms = duration
    push(f"export stage {record.status}")


def _record(run: RunState, name: str) -> StageRecord:
    return next(r for r in run.stages if r.name == name)


def _short(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
