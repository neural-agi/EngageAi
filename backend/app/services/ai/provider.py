"""Low-level AI provider wrapper."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.config import Settings, get_settings

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - optional dependency fallback
    AsyncOpenAI = None


T = TypeVar("T")


class AIProvider:
    """Async wrapper for low-level text, structured, and embedding calls."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        """Initialize the provider with configuration-driven settings."""

        self.settings = settings or get_settings()
        self.timeout_seconds = timeout_seconds or self.settings.ai_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else self.settings.ai_max_retries
        self._client = self._build_client()

    async def generate_text(self, prompt: str) -> str:
        """Generate plain text output for a prompt."""

        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            return ""
        if self._client is None:
            return cleaned_prompt

        async def operation() -> str:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": cleaned_prompt}],
            )
            content = response.choices[0].message.content or ""
            return content.strip()

        return await self._run_with_retry(
            operation=operation,
            fallback=lambda: cleaned_prompt,
        )

    async def generate_structured(self, prompt: str) -> dict[str, Any]:
        """Generate structured JSON output for a prompt."""

        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            return {}
        if self._client is None:
            return {"content": cleaned_prompt}

        async def operation() -> dict[str, Any]:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "Return a valid JSON object only.",
                    },
                    {"role": "user", "content": cleaned_prompt},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            return self._parse_json_object(content)

        return await self._run_with_retry(
            operation=operation,
            fallback=lambda: {"content": cleaned_prompt},
        )

    async def get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector for an input string."""

        cleaned_text = text.strip()
        if not cleaned_text or self._client is None:
            return []

        async def operation() -> list[float]:
            response = await self._client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=cleaned_text,
            )
            embedding = response.data[0].embedding
            return [float(value) for value in embedding]

        return await self._run_with_retry(
            operation=operation,
            fallback=list,
        )

    def _build_client(self) -> AsyncOpenAI | None:
        """Build the OpenAI client when the SDK and API key are available."""

        if AsyncOpenAI is None or not self.settings.openai_api_key:
            return None

        client_kwargs: dict[str, Any] = {"api_key": self.settings.openai_api_key}
        if self.settings.openai_base_url:
            client_kwargs["base_url"] = self.settings.openai_base_url
        return AsyncOpenAI(**client_kwargs)

    async def _run_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        fallback: Callable[[], T],
    ) -> T:
        """Run an async operation with basic retries and timeout handling."""

        last_error: Exception | None = None
        attempts = max(1, self.max_retries + 1)

        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
            except Exception as exc:  # pragma: no cover - depends on provider/runtime behavior
                last_error = exc
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(min(2**attempt, 3))

        # TODO: hook provider errors into structured logging/observability.
        _ = last_error
        return fallback()

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        """Parse a JSON object response into a clean dictionary."""

        if not content:
            return {}

        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
