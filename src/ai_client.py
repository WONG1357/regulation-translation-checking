from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from src.schemas import AIConfig
from src.utils import json_hash, validate_json_response

T = TypeVar("T", bound=BaseModel)


class AIClient:
    def __init__(self, config: AIConfig):
        self.config = config
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token_usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}

    def _cache_path(self, system_prompt: str, payload: Any, schema: type[T]) -> Path:
        digest = json_hash(
            {
                "model": self.config.model,
                "system_prompt": system_prompt,
                "payload": payload,
                "schema": schema.model_json_schema(),
            }
        )
        return self.config.cache_dir / f"{digest}.json"

    def request_json(self, system_prompt: str, payload: Any, schema: type[T]) -> T:
        cache_path = self._cache_path(system_prompt, payload, schema)
        if cache_path.exists():
            return schema.model_validate_json(cache_path.read_text(encoding="utf-8"))

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The openai package is required for AI review.") from exc

        client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        user_content = json.dumps(payload, ensure_ascii=False, default=str)
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            repair = (
                "\nYour previous output was invalid. Return one JSON object only, matching the schema."
                if attempt
                else ""
            )
            try:
                response = client.chat.completions.create(
                    model=self.config.model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": f"{system_prompt}\n\nRequired JSON schema:\n"
                            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}{repair}",
                        },
                        {"role": "user", "content": user_content},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                result = validate_json_response(content, schema)
                cache_path.write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
                usage = getattr(response, "usage", None)
                if usage:
                    self.token_usage["input_tokens"] += int(
                        getattr(usage, "prompt_tokens", 0) or 0
                    )
                    self.token_usage["output_tokens"] += int(
                        getattr(usage, "completion_tokens", 0) or 0
                    )
                self.token_usage["requests"] += 1
                return result
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"AI response failed validation: {last_error}")

