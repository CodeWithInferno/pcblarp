"""Pipeline stages.

Each stage raises StageError on failure. When `llm_feedback` is set, the
pipeline feeds it back to Claude for a spec revision pass (the error feedback
loop), then re-runs downstream stages against the revised spec.
"""

from __future__ import annotations

import re


class StageError(Exception):
    def __init__(
        self,
        message: str,
        *,
        llm_feedback: str | None = None,
        metrics: dict[str, float] | None = None,
    ) -> None:
        super().__init__(message)
        self.llm_feedback = llm_feedback
        self.metrics = metrics or {}


def injected_failure(stage: str) -> StageError | None:
    """Demo/test hook: CHATPCB_FAIL_STAGE=layout makes that stage fail every
    attempt, exercising the revision loop and the partial-results path live
    (see `make demo-partial`)."""
    from .. import config

    failing = [s.strip() for s in (config.env("CHATPCB_FAIL_STAGE") or "").split(",")]
    if stage in failing:
        return StageError(
            f"injected failure in {stage} stage (CHATPCB_FAIL_STAGE)",
            llm_feedback=(
                f"The {stage} stage failed: simulated DRC/routing failure for "
                "demo purposes. Simplify the design if possible."
            ),
            metrics={"injected": 1.0},
        )
    return None


def slugify(name: str) -> str:
    """Safe filename fragment from an LLM-chosen project name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return cleaned or "board"
