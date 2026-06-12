import pytest

import chatpcb.llm as llm
from chatpcb import config
from chatpcb.stages import StageError
from chatpcb.stages import spec as spec_stage


def test_parse_retry_feeds_error_back(monkeypatch):
    good = (config.DATA_DIR / "mock_spec.json").read_text()
    responses = iter(["this is not json at all", f"```json\n{good}\n```"])
    calls = []

    def fake_complete(system, messages, **kwargs):
        calls.append([dict(m) for m in messages])
        return next(responses)

    monkeypatch.setattr(llm, "complete", fake_complete)

    attempts = []

    def log_attempt(attempt, status, duration_ms, error=None):
        attempts.append((attempt, status))

    spec, used = spec_stage.generate_spec("idea", log_attempt=log_attempt)
    assert used == 2
    assert attempts == [(1, "failed"), (2, "ok")]
    # second call carries the bad output plus the validation error feedback
    assert calls[1][1]["role"] == "assistant"
    assert "failed validation" in calls[1][2]["content"]
    assert spec.project.name == "ble-voice-streamer"


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "still not json")
    monkeypatch.setenv("CHATPCB_MAX_STAGE_ATTEMPTS", "2")

    logged = []
    with pytest.raises(StageError, match="after 2 attempts"):
        spec_stage.generate_spec(
            "idea", log_attempt=lambda a, s, d, error=None: logged.append(s)
        )
    assert logged == ["failed", "failed"]


def test_revision_retries_parse_errors(monkeypatch):
    good = (config.DATA_DIR / "mock_spec.json").read_text()
    base = spec_stage.parse_spec(good)
    responses = iter(["definitely not json", good])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: next(responses))

    revised = spec_stage.revise_spec_with_error(base, "layout", "DRC failed")
    assert revised.project.name == "ble-voice-streamer"


def test_fence_stripping():
    assert spec_stage._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert spec_stage._strip_fences('{"a": 1}') == '{"a": 1}'
