"""Environment-driven configuration.

Values are read at call time (not import time) so tests and the demo targets
can override them with monkeypatch / inline env vars.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    # Load .env from the cwd (the documented copy-of-.env.example workflow);
    # real environment variables always win over .env values.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
FRONTEND_DIR = REPO_ROOT / "frontend"


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def artifacts_dir() -> Path:
    return Path(env("CHATPCB_ARTIFACTS_DIR", str(REPO_ROOT / "artifacts")))


def anthropic_model() -> str:
    # The stage 1 prompt is tuned for Sonnet; bump via env to an Opus/Fable
    # tier for hard designs.
    return env("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def llm_provider() -> str:
    """Which LLM backs stage 1. Explicit via CHATPCB_LLM_PROVIDER, else auto:
    use OpenAI when only an OpenAI key is present, otherwise Anthropic."""
    explicit = (env("CHATPCB_LLM_PROVIDER") or "").strip().lower()
    if explicit in {"openai", "anthropic"}:
        return explicit
    if env("OPENAI_API_KEY") and not (env("ANTHROPIC_API_KEY") or env("TF_GATEWAY_URL")):
        return "openai"
    return "anthropic"


def openai_model() -> str:
    return env("OPENAI_MODEL", "gpt-4o-mini")


def max_stage_attempts() -> int:
    return int(env("CHATPCB_MAX_STAGE_ATTEMPTS", "3"))


def max_spec_revisions() -> int:
    return int(env("CHATPCB_MAX_SPEC_REVISIONS", "3"))
