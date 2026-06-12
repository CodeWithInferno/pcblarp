import pytest

import chatpcb.llm as llm


def _clear_llm_env(monkeypatch):
    for var in ("CHATPCB_MOCK_LLM", "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN", "TF_GATEWAY_URL", "TF_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_missing_key_raises_llmerror_not_typeerror(monkeypatch):
    # SDK raises TypeError when no auth is resolvable; must surface as
    # LLMError so the stage retry/failure path engages instead of crashing.
    _clear_llm_env(monkeypatch)
    with pytest.raises(llm.LLMError):
        llm.complete("system", [{"role": "user", "content": "hi"}])


def test_gateway_without_virtual_key_fails_fast(monkeypatch):
    # Half-configured gateway must not silently send ANTHROPIC_API_KEY to it.
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key")
    monkeypatch.setenv("TF_GATEWAY_URL", "https://gateway.example.com")
    with pytest.raises(llm.LLMError, match="TF_API_KEY"):
        llm.complete("system", [{"role": "user", "content": "hi"}])
