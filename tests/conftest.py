import json

import pytest

from chatpcb import config


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """Mocked Claude + isolated artifacts dir + local-only backends."""
    monkeypatch.setenv("CHATPCB_MOCK_LLM", "1")
    monkeypatch.setenv("CHATPCB_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    for var in ("CLICKHOUSE_URL", "S3_BUCKET", "REDIS_URL",
                "CHATPCB_REMOTE_LAYOUT", "CHATPCB_FAIL_STAGE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def mock_spec_data():
    return json.loads((config.DATA_DIR / "mock_spec.json").read_text())
