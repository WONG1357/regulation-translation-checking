from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMConfig:
    provider: str
    api_key: str | None
    model: str
    base_url: str | None = None


class LLMAuthenticationError(RuntimeError):
    """Raised when the selected provider rejects the API key."""


def get_llm_config(model: str | None = None) -> LLMConfig:
    session_provider = None
    session_key = None
    session_base_url = None
    session_model = None
    secrets_key = None
    secrets_base_url = None
    try:
        import streamlit as st

        session_provider = st.session_state.get("api_provider")
        session_key = st.session_state.get("api_key") or st.session_state.get("openai_api_key")
        session_base_url = st.session_state.get("api_base_url")
        session_model = st.session_state.get("model_name")
    except Exception:
        pass

    try:
        import streamlit as st

        secrets_key = (
            st.secrets.get("LLM_API_KEY")
            or st.secrets.get("DEEPSEEK_API_KEY")
            or st.secrets.get("OPENAI_API_KEY")
            or st.secrets.get("ANTHROPIC_API_KEY")
        )
        secrets_base_url = st.secrets.get("LLM_API_BASE_URL")
    except Exception:
        pass

    provider = session_provider or os.getenv("LLM_API_PROVIDER") or "DeepSeek"
    resolved_model = model or session_model or os.getenv("LLM_MODEL") or _default_model(provider)
    api_key = _clean_api_key(
        session_key
        or secrets_key
        or os.getenv("LLM_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    base_url = session_base_url or secrets_base_url or os.getenv("LLM_API_BASE_URL") or _default_base_url(provider)
    return LLMConfig(provider=provider, api_key=api_key, model=resolved_model, base_url=base_url)


def call_llm_json(config: LLMConfig, messages: list[dict[str, str]], expected: str = "array") -> Any:
    if not config.api_key:
        raise ValueError(f"{config.provider} API key not found")

    provider = config.provider.lower()
    if provider in {"openai", "openai-compatible", "deepseek"}:
        content = _call_openai_compatible(config, messages)
    elif provider == "anthropic":
        content = _call_anthropic(config, messages)
    else:
        raise ValueError(f"Unsupported API provider: {config.provider}")

    parsed = json.loads(_extract_json(content))
    if expected == "array" and not isinstance(parsed, list):
        raise ValueError("API returned JSON, but not a JSON array")
    if expected == "object" and not isinstance(parsed, dict):
        raise ValueError("API returned JSON, but not a JSON object")
    return parsed


def format_api_error(provider: str, exc: Exception) -> str:
    if is_authentication_error(exc):
        return f"{provider} authentication failed. Check that the API key is correct, active, and belongs to the selected provider."
    return _sanitize_error(str(exc))


def is_authentication_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, LLMAuthenticationError) or "401" in text or "authentication" in text or "invalid api key" in text


def provider_key_label(provider: str) -> str:
    if provider == "DeepSeek":
        return "DeepSeek API key"
    if provider == "Anthropic":
        return "Anthropic API key"
    if provider == "OpenAI-compatible":
        return "API key"
    return "OpenAI API key"


def _default_model(provider: str) -> str:
    if provider == "DeepSeek":
        return "deepseek-v4-flash"
    if provider == "Anthropic":
        return "claude-sonnet-4-5"
    return "gpt-4o-mini"


def _default_base_url(provider: str) -> str | None:
    if provider == "DeepSeek":
        return "https://api.deepseek.com"
    return None


def _call_openai_compatible(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": _clean_api_key(config.api_key)}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    client = OpenAI(**kwargs)
    try:
        response = client.chat.completions.create(
            model=config.model,
            temperature=0.1,
            messages=messages,
        )
    except Exception as exc:
        if is_authentication_error(exc):
            raise LLMAuthenticationError(format_api_error(config.provider, exc)) from exc
        raise RuntimeError(format_api_error(config.provider, exc)) from exc
    return response.choices[0].message.content or "[]"


def _call_anthropic(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    import httpx

    system_parts = [message["content"] for message in messages if message["role"] == "system"]
    user_messages = [
        {"role": "user" if message["role"] != "assistant" else "assistant", "content": message["content"]}
        for message in messages
        if message["role"] != "system"
    ]
    response = httpx.post(
        config.base_url or "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": _clean_api_key(config.api_key) or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.model,
            "max_tokens": 4000,
            "temperature": 0.1,
            "system": "\n\n".join(system_parts),
            "messages": user_messages,
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    return "\n".join(part.get("text", "") for part in payload.get("content", []) if part.get("type") == "text")


def _extract_json(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    return match.group(1).strip() if match else content.strip()


def _clean_api_key(api_key: str | None) -> str | None:
    return api_key.strip() if isinstance(api_key, str) and api_key.strip() else None


def _sanitize_error(message: str) -> str:
    sanitized = re.sub(r"(api key[: ]+)[^,'}\s]+", r"\1[hidden]", message, flags=re.I)
    sanitized = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[hidden]", sanitized)
    return sanitized
