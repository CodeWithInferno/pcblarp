import json

import pytest

from chatpcb import config
from chatpcb.worker import handle_job


def test_handle_job_returns_artifact_contents(mock_env, mock_spec_data):
    key, payload = handle_job(json.dumps({"job_id": "abc123",
                                          "spec": mock_spec_data}))
    assert key.endswith("abc123")
    assert payload["status"] == "ok"
    assert payload["result"]["routing_completion_pct"] == 0.0  # placed, unrouted
    # artifacts travel by content, not by path (no shared volume)
    names = set(payload["files"])
    assert any(n.endswith(".kicad_pcb") for n in names)
    assert "drc_report.json" in names


def test_handle_job_invalid_spec_becomes_error_payload(mock_env):
    key, payload = handle_job(json.dumps({"job_id": "abc", "spec": {}}))
    assert payload["status"] == "error"


def test_malformed_envelope_raises(mock_env):
    with pytest.raises(Exception):
        handle_job("not json")
