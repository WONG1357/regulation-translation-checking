from __future__ import annotations

import json
import re
import time
from typing import Any

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


def call_openai_compatible(
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    base_url: str = "",
    temperature: float = 0,
    timeout: int = 90,
    retries: int = 2,
) -> Any:
    if not api_key.strip():
        raise AIClientError("Enter an API key in Upload & Settings.")
    if not model.strip():
        raise AIClientError("Enter an AI model name.")
    root = (base_url.strip() or "https://api.openai.com/v1").rstrip("/")
    url = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
    payload = {"model": model.strip(), "messages": messages, "temperature": temperature}
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 401:
                raise AIClientError("The API key was rejected. Check the key and provider.")
            if response.status_code == 429:
                raise AIClientError("The API rate limit was reached. Please wait and retry.")
            if response.status_code >= 400:
                detail = response.text[:300]
                raise AIClientError(f"AI API error {response.status_code}: {detail}")
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return extract_json_payload(content)
        except requests.Timeout as exc:
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
            time.sleep(1.5 * (attempt + 1))
    raise last_error or AIClientError("The AI request failed.")
