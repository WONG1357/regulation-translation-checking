from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests


class AIClientError(RuntimeError):
    pass


def extract_json_payload(text: str) -> Any:
    if not text or not text.strip():
        raise AIClientError("The AI returned an empty response.")
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        starts = [pos for pos in (clean.find("{"), clean.find("[")) if pos >= 0]
        if not starts:
            raise AIClientError("The AI response did not contain valid JSON.")
        start = min(starts)
        for end_char in ("}", "]"):
            end = clean.rfind(end_char)
            if end > start:
                try:
                    return json.loads(clean[start:end + 1])
                except json.JSONDecodeError:
                    pass
        raise AIClientError("The AI returned invalid JSON. Please retry.")


def normalize_base_url(base_url: str) -> str:
    root = (base_url.strip() or "https://api.openai.com/v1").rstrip("/")
    if root.endswith("/chat/completions"):
        root = root[: -len("/chat/completions")]
    parsed = urlparse(root)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIClientError("The API base URL is invalid.")
    return root


def is_deepseek_url(base_url: str) -> bool:
    return urlparse(normalize_base_url(base_url)).netloc.lower() in {
        "api.deepseek.com", "api.deepseek.com.cn"
    }


def call_openai_compatible(
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    base_url: str = "",
    temperature: float = 0,
    timeout: int = 180,
    retries: int = 3,
) -> Any:
    if not api_key.strip():
        raise AIClientError("Enter an API key in Upload & Settings.")
    if not model.strip():
        raise AIClientError("Enter an AI model name.")

    root = normalize_base_url(base_url)
    if is_deepseek_url(root):
        return _call_with_openai_sdk(
            api_key, model, messages, root, temperature, timeout, retries
        )
    return _call_with_requests(
        api_key, model, messages, root, temperature, timeout, retries
    )


def _call_with_openai_sdk(
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    base_url: str,
    temperature: float,
    timeout: int,
    retries: int,
) -> Any:
    """Use DeepSeek's documented OpenAI-compatible SDK transport."""
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            AuthenticationError,
            OpenAI,
            RateLimitError,
        )
    except ImportError as exc:
        raise AIClientError(
            "The OpenAI SDK is required for DeepSeek. Run: pip install openai"
        ) from exc

    client = OpenAI(
        api_key=api_key.strip(),
        base_url=base_url,
        timeout=timeout,
        max_retries=retries,
    )
    try:
        response = client.chat.completions.create(
            model=model.strip(),
            messages=messages,
            temperature=temperature,
            stream=False,
            max_tokens=16384,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        if not response.choices:
            raise AIClientError("DeepSeek returned no completion choices.")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise AIClientError(
                "DeepSeek reached the output limit. Reduce the chunk size and retry."
            )
        if choice.finish_reason == "insufficient_system_resource":
            raise AIClientError(
                "DeepSeek interrupted the request because inference resources were unavailable. "
                "Please retry in a moment."
            )
        return extract_json_payload(choice.message.content or "")
    except AuthenticationError as exc:
        raise AIClientError("The DeepSeek API key was rejected.") from exc
    except RateLimitError as exc:
        raise AIClientError("DeepSeek rate limit reached. Please wait and retry.") from exc
    except APITimeoutError as exc:
        raise AIClientError(
            "DeepSeek timed out after retries. Try again or reduce the AI chunk size."
        ) from exc
    except APIConnectionError as exc:
        raise AIClientError(
            "The DeepSeek connection closed before a complete response was received. "
            "The app retried automatically; please retry once more or reduce the chunk size."
        ) from exc
    except APIStatusError as exc:
        detail = str(exc)
        raise AIClientError(f"DeepSeek API error {exc.status_code}: {detail[:300]}") from exc


def _call_with_requests(
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    base_url: str,
    temperature: float,
    timeout: int,
    retries: int,
) -> Any:
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model.strip(),
        "messages": messages,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 401:
                raise AIClientError("The API key was rejected. Check the key and provider.")
            if response.status_code == 429:
                raise AIClientError("The API rate limit was reached. Please wait and retry.")
            if response.status_code >= 400:
                raise AIClientError(f"AI API error {response.status_code}: {response.text[:300]}")
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return extract_json_payload(content)
        except requests.Timeout:
            last_error = AIClientError("The AI request timed out.")
        except requests.RequestException as exc:
            last_error = AIClientError(f"Could not reach the AI API: {exc}")
        except (ValueError, KeyError, IndexError) as exc:
            last_error = AIClientError(f"Unexpected AI API response: {exc}")
        except AIClientError as exc:
            last_error = exc
            if "rejected" in str(exc) or "invalid JSON" in str(exc):
                break
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise last_error or AIClientError("The AI request failed.")


def test_api_connection(api_key: str, model: str, base_url: str = "") -> dict[str, Any]:
    result = call_openai_compatible(
        api_key,
        model,
        [
            {
                "role": "system",
                "content": "Return valid JSON only.",
            },
            {
                "role": "user",
                "content": 'Return exactly this JSON object: {"status":"ok"}',
            },
        ],
        base_url,
        timeout=45,
        retries=1,
    )
    if not isinstance(result, dict):
        raise AIClientError("The API connection worked but did not return a JSON object.")
    return result
