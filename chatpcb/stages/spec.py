"""Stage 1: plain-language idea -> validated Spec via Claude.

JSON parse / schema validation failures are appended to the conversation and
retried (per the prompt's own integration notes), up to
CHATPCB_MAX_STAGE_ATTEMPTS. Every attempt is reported through the
`log_attempt` callback so telemetry records the whole feedback loop.
"""

from __future__ import annotations

import json
import time
from typing import Callable

from pydantic import ValidationError

from .. import config, llm
from ..models import Spec
from . import StageError

# log_attempt(attempt, status, duration_ms, error=None)
AttemptLogger = Callable[..., None]


class SpecParseError(ValueError):
    """The model's output failed JSON parsing or schema validation."""


def load_system_prompt() -> str:
    return (config.PROMPTS_DIR / "stage1_spec.md").read_text()


def _system_prompt_with_rules(query: str) -> str:
    """System prompt plus a <design_rules> block from the Senso knowledge
    layer (local markdown fallback). Senso must never block stage 1."""
    system = load_system_prompt()
    try:
        from ..integrations import senso_kb

        rules = senso_kb.design_rules_context(query)
    except Exception:
        rules = ""
    if rules:
        system += (
            "\n\n<design_rules>\n"
            "Manufacturer design rules and parts context relevant to this "
            "request; respect them when choosing blocks and constraints.\n"
            f"{rules}\n</design_rules>"
        )
    return system


def _strip_fences(text: str) -> str:
    """The prompt forbids markdown fences, but be lenient when parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_spec(raw: str) -> Spec:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise SpecParseError(f"JSON.parse failed: {exc}") from exc
    try:
        return Spec.model_validate(data)
    except ValidationError as exc:
        raise SpecParseError(f"schema validation failed: {exc}") from exc


def generate_spec(idea: str, *, log_attempt: AttemptLogger) -> tuple[Spec, int]:
    """Returns (spec, attempts_used). Raises StageError after max attempts."""
    system = _system_prompt_with_rules(idea)
    messages: list[dict] = [{"role": "user", "content": idea}]
    last_error = "no attempts made"

    for attempt in range(1, config.max_stage_attempts() + 1):
        started = time.monotonic()
        try:
            raw = llm.complete(system, messages)
        except llm.LLMError as exc:
            last_error = str(exc)
            log_attempt(attempt, "failed", (time.monotonic() - started) * 1000,
                        error=last_error)
            continue
        try:
            spec = parse_spec(raw)
        except SpecParseError as exc:
            last_error = str(exc)
            log_attempt(attempt, "failed", (time.monotonic() - started) * 1000,
                        error=last_error)
            # Feed the exact error back, per the prompt's integration notes.
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"Your output failed validation with: {exc}\n"
                    "Output only the corrected JSON object, nothing else."
                ),
            })
            continue
        log_attempt(attempt, "ok", (time.monotonic() - started) * 1000)
        return spec, attempt

    raise StageError(
        f"spec generation failed after {config.max_stage_attempts()} attempts: "
        f"{last_error}"
    )


def revise_spec_with_error(
    spec: Spec,
    stage: str,
    error: str,
    *,
    log_attempt: AttemptLogger | None = None,
) -> Spec:
    """Revision pass: hand Claude the downstream failure plus the current
    spec, get a corrected spec back. Parse/validation failures get the same
    bounded feedback-retry conversation as generate_spec, so one malformed
    response does not abort the whole revision loop. Raises SpecParseError
    after max attempts."""
    log = log_attempt or (lambda *a, **k: None)
    system = _system_prompt_with_rules(f"{stage} stage failure: {error}")
    messages: list[dict] = [{
        "role": "user",
        "content": (
            "A downstream pipeline stage failed while building this spec.\n"
            f"Failed stage: {stage}\n"
            f"Error: {error}\n\n"
            "Here is the current spec JSON:\n"
            f"{spec.model_dump_json()}\n\n"
            "Revise the spec to address the failure (for example: simplify the "
            "design, relax constraints, or swap blocks) and output the complete "
            "corrected JSON object only."
        ),
    }]
    last_error = "no attempts made"
    for attempt in range(1, config.max_stage_attempts() + 1):
        started = time.monotonic()
        try:
            raw = llm.complete(system, messages)
        except llm.LLMError as exc:
            last_error = str(exc)
            log(attempt, "failed", (time.monotonic() - started) * 1000,
                error=last_error)
            continue
        try:
            revised = parse_spec(raw)
        except SpecParseError as exc:
            last_error = str(exc)
            log(attempt, "failed", (time.monotonic() - started) * 1000,
                error=last_error)
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"Your output failed validation with: {exc}\n"
                    "Output only the corrected JSON object, nothing else."
                ),
            })
            continue
        log(attempt, "ok", (time.monotonic() - started) * 1000)
        return revised
    raise SpecParseError(
        f"spec revision failed after {config.max_stage_attempts()} attempts: "
        f"{last_error}"
    )
