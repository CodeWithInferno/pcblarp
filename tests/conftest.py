import json

import pytest

from chatpcb import config

# Backend/sponsor env that must never leak into the suite: a developer's
# filled-in .env (auto-loaded by config.py) would otherwise flip tests onto
# live services (Senso HTTP calls, Composio, a real parts DB, ClickHouse).
EXTERNAL_ENV_VARS = (
    "CLICKHOUSE_URL", "S3_BUCKET", "REDIS_URL", "CHATPCB_REMOTE_LAYOUT",
    "CHATPCB_FAIL_STAGE", "CHATPCB_MAX_STAGE_ATTEMPTS",
    "CHATPCB_MAX_SPEC_REVISIONS",
    "COMPOSIO_API_KEY", "COMPOSIO_USER_ID", "COMPOSIO_GITHUB_OWNER",
    "COMPOSIO_GMAIL_TO",
    "SENSO_API_KEY", "SENSO_BASE_URL",
    "PARTS_DB_URL", "AIRBYTE_API_URL", "AIRBYTE_CONNECTION_ID",
    "AIRBYTE_API_TOKEN",
)


@pytest.fixture(autouse=True)
def _isolate_external_env(monkeypatch):
    for var in EXTERNAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """Mocked Claude + isolated artifacts dir (external env cleared autouse)."""
    monkeypatch.setenv("CHATPCB_MOCK_LLM", "1")
    monkeypatch.setenv("CHATPCB_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    return tmp_path


@pytest.fixture
def mock_spec_data():
    return json.loads((config.DATA_DIR / "mock_spec.json").read_text())
