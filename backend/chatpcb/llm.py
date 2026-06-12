"""Claude API access for the pipeline.

All calls route through the TrueFoundry gateway when TF_GATEWAY_URL is set:
the gateway exposes an Anthropic-compatible endpoint, so we just point the
official SDK's base_url at it and authenticate with the TrueFoundry virtual
key (TF_API_KEY). Falls back to the direct Anthropic API when unset.

CHATPCB_MOCK_LLM=1 short-circuits every call to the canned worked-example
spec in data/mock_spec.json so the full pipeline demos without any API key.
"""

from __future__ import annotations

from . import config

# Sampling parameters were removed on these model families; sending
# temperature to them returns a 400.
_NO_TEMPERATURE_PREFIXES = ("claude-fable", "claude-opus-4-7", "claude-opus-4-8")


class LLMError(RuntimeError):
    """The Claude API call itself failed (network, auth, rate limit)."""


def complete(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 16000,
    temperature: float = 0.0,
) -> str:
    """One non-streaming Messages API call; returns concatenated text blocks."""
    if config.flag("CHATPCB_MOCK_LLM"):
        return (config.DATA_DIR / "mock_spec.json").read_text()

    if config.llm_provider() == "openai":
        return _complete_openai(
            system, messages, max_tokens=max_tokens, temperature=temperature
        )

    import anthropic

    base_url = config.env("TF_GATEWAY_URL")
    if base_url and not config.env("TF_API_KEY"):
        raise LLMError(
            "TF_GATEWAY_URL is set but TF_API_KEY is not; refusing to send "
            "ANTHROPIC_API_KEY to the gateway. Set TF_API_KEY or unset "
            "TF_GATEWAY_URL."
        )
    api_key = (
        config.env("TF_API_KEY") if base_url else config.env("ANTHROPIC_API_KEY")
    )
    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    model = config.anthropic_model()
    request: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if not model.startswith(_NO_TEMPERATURE_PREFIXES):
        request["temperature"] = temperature

    try:
        client = anthropic.Anthropic(**kwargs)
        response = client.messages.create(**request)
    except anthropic.APIError as exc:
        raise LLMError(f"Claude API call failed: {exc}") from exc
    except (TypeError, ValueError) as exc:
        # e.g. "Could not resolve authentication method" when no key is set;
        # must become LLMError so the stage retry/failure path engages.
        raise LLMError(f"Claude client setup failed: {exc}") from exc

    if response.stop_reason == "max_tokens":
        raise LLMError(
            f"response truncated at max_tokens={max_tokens}; the spec JSON "
            "did not fit. Raise max_tokens in llm.complete()."
        )

    return "".join(
        block.text for block in response.content if block.type == "text"
    )


def _complete_openai(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float,
) -> str:
    """OpenAI Chat Completions path. The Anthropic-style (system, messages)
    shape maps directly: system becomes a system message, the rest pass
    through. JSON mode is requested since stage 1 must emit a JSON object."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMError(
            "openai package not installed; `pip install openai`"
        ) from exc

    api_key = config.env("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is not set")

    base_url = config.env("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(
        api_key=api_key
    )

    oai_messages = [{"role": "system", "content": system}]
    for m in messages:
        oai_messages.append({"role": m["role"], "content": m["content"]})

    try:
        response = client.chat.completions.create(
            model=config.openai_model(),
            messages=oai_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # openai raises a variety of API errors
        raise LLMError(f"OpenAI API call failed: {exc}") from exc

    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise LLMError(
            f"response truncated at max_tokens={max_tokens}; the spec JSON "
            "did not fit. Raise max_tokens in llm.complete()."
        )
    return choice.message.content or ""
