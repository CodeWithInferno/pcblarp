"""Guild.ai experiment tracking for pipeline runs.

Records per run: prompt version (hash of prompts/stage1_spec.md), model,
placement optimizer / autorouter settings, routing completion %, DRC
violation count, retries, revisions, and durations, so runs are comparable
as prompts and router settings evolve.

Isolation guarantee: if guildai is not installed (it lives in the
"sponsors" extra) or anything in it fails, the same record appends to
<artifacts>/experiments.jsonl instead. The pipeline never blocks on this.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from .. import config
from ..models import RunState
from ..stages.layout import ROUTER_SETTINGS

log = logging.getLogger(__name__)


def prompt_version() -> str:
    """Stable label for the current stage 1 prompt: env override + content hash."""
    digest = hashlib.sha256(
        (config.PROMPTS_DIR / "stage1_spec.md").read_bytes()
    ).hexdigest()[:8]
    label = config.env("CHATPCB_PROMPT_VERSION", "dev")
    return f"{label}-{digest}"


def _flags(run: RunState) -> dict:
    return {
        "prompt_version": prompt_version(),
        "model": config.anthropic_model(),
        "mock_llm": config.flag("CHATPCB_MOCK_LLM"),
        **ROUTER_SETTINGS,
    }


def _scalars(run: RunState) -> dict:
    by_name = {r.name: r for r in run.stages}
    layout = by_name.get("layout")
    return {
        "routing_completion_pct": (layout.metrics.get("routing_completion_pct", -1.0)
                                   if layout else -1.0),
        "drc_violations": (layout.metrics.get("drc_violations", -1.0)
                           if layout else -1.0),
        "spec_revisions": float(run.revision_count),
        "retries": float(sum(max(0, r.attempts - 1) for r in run.stages)),
        "stages_ok": float(sum(1 for r in run.stages if r.status == "ok")),
        "duration_ms_total": round(sum(r.duration_ms for r in run.stages), 1),
        "run_ok": 1.0 if run.status == "done" else 0.0,
    }


def track_run(run: RunState) -> None:
    """Record one experiment data point. Never raises."""
    flags, scalars = _flags(run), _scalars(run)
    try:
        from guild import ipy as guild_ipy  # type: ignore

        def _record(**_fl):
            # Guild captures "key: value" output lines as run scalars.
            for key, value in scalars.items():
                print(f"{key}: {value}")
            return scalars

        # TODO: confirm ipy.run signature against the pinned guildai version.
        guild_ipy.run(_record, **flags)
    except Exception as exc:
        if not isinstance(exc, ImportError):
            log.warning("guild tracking failed, writing jsonl: %s", exc)
        _append_jsonl(run, flags, scalars)


def _append_jsonl(run: RunState, flags: dict, scalars: dict) -> None:
    try:
        path = config.artifacts_dir() / "experiments.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "run_id": run.run_id,
                "status": run.status,
                "flags": flags,
                "scalars": scalars,
            }, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning("experiment jsonl fallback failed: %s", exc)
