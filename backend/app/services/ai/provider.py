"""Low-level AI provider wrapper."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.config import Settings, get_settings
from app.services.ai.gemini_client import GeminiClient

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - optional dependency fallback
    AsyncOpenAI = None


T = TypeVar("T")
logger = logging.getLogger(__name__)


class AIProvider:
    """Async wrapper for low-level text, structured, and embedding calls."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        llm_provider: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the provider with configuration-driven settings."""

        self.settings = settings or get_settings()
        self.timeout_seconds = timeout_seconds or self.settings.ai_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else self.settings.ai_max_retries
        self.disabled = disabled
        configured_provider = llm_provider or self.settings.llm_provider
        self.llm_provider = configured_provider.strip().lower() or "openai"
        self._client = self._build_client()

    async def generate_text(self, prompt: str) -> str:
        """Generate plain text output for a prompt."""

        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            return ""
        if self.disabled:
            return cleaned_prompt
        self._require_client()

        logger.info("Generating text with configured LLM provider", extra={"provider": self.llm_provider})

        if self.llm_provider == "gemini":
            operation = self._build_gemini_text_operation(cleaned_prompt)
            max_attempts = 2
        else:
            operation = self._build_openai_text_operation(cleaned_prompt)
            max_attempts = None

        return await self._run_with_retry(
            operation=operation,
            operation_name="generate_text",
            max_attempts=max_attempts,
        )

    async def generate_structured(self, prompt: str) -> dict[str, Any]:
        """Generate structured JSON output for a prompt."""

        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            return {}
        if self.disabled:
            return {"content": cleaned_prompt}
        self._require_client()

        structured_prompt = (
            "Return a valid JSON object only. Do not wrap the response in markdown fences.\n\n"
            f"{cleaned_prompt}"
        )
        content = await self.generate_text(structured_prompt)
        return self._parse_json_object(content)

    async def get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector for an input string."""

        cleaned_text = text.strip()
        if not cleaned_text or self.disabled:
            return []
        self._require_client()

        logger.info("Generating embeddings with configured LLM provider", extra={"provider": self.llm_provider})

        if self.llm_provider == "gemini":
            operation = self._build_gemini_embedding_operation(cleaned_text)
            max_attempts = 2
        else:
            operation = self._build_openai_embedding_operation(cleaned_text)
            max_attempts = None

        return await self._run_with_retry(
            operation=operation,
            operation_name="get_embedding",
            max_attempts=max_attempts,
        )

    def _build_client(self) -> AsyncOpenAI | GeminiClient | None:
        """Build the configured LLM client when dependencies and keys are available."""

        if self.disabled:
            return None

        if self.llm_provider == "gemini":
            if not self.settings.gemini_api_key:
                logger.warning("Gemini provider selected without GEMINI_API_KEY")
                return None
            client = GeminiClient(
                self.settings.gemini_api_key,
                model=self.settings.gemini_model,
                embedding_model=self.settings.gemini_embedding_model,
            )
            if not client.is_available:
                logger.warning("Gemini SDK is unavailable", extra={"provider": self.llm_provider})
            return client if client.is_available else None

        if AsyncOpenAI is None or not self.settings.openai_api_key:
            logger.warning("OpenAI provider unavailable", extra={"provider": self.llm_provider})
            return None
        client_kwargs: dict[str, Any] = {"api_key": self.settings.openai_api_key}
        if self.settings.openai_base_url:
            client_kwargs["base_url"] = self.settings.openai_base_url
        return AsyncOpenAI(**client_kwargs)

    def _require_client(self) -> None:
        """Ensure a concrete provider client exists before making external calls."""

        if self._client is not None:
            return
        raise RuntimeError(
            f"LLM provider '{self.llm_provider}' is not configured or its SDK is unavailable."
        )

    def _build_openai_text_operation(self, prompt: str) -> Callable[[], Awaitable[str]]:
        """Build the async OpenAI text operation."""

        async def operation() -> str:
            response = await self._client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content or ""
            return content.strip()

        return operation

    def _build_gemini_text_operation(self, prompt: str) -> Callable[[], Awaitable[str]]:
        """Build the async Gemini text operation."""

        async def operation() -> str:
            return await asyncio.to_thread(self._client.generate_text, prompt)

        return operation

    def _build_openai_embedding_operation(self, text: str) -> Callable[[], Awaitable[list[float]]]:
        """Build the async OpenAI embedding operation."""

        async def operation() -> list[float]:
            response = await self._client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=text,
            )
            embedding = response.data[0].embedding
            return [float(value) for value in embedding]

        return operation

    def _build_gemini_embedding_operation(self, text: str) -> Callable[[], Awaitable[list[float]]]:
        """Build the async Gemini embedding operation."""

        async def operation() -> list[float]:
            return await asyncio.to_thread(self._client.get_embedding, text)

        return operation

    async def _run_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        operation_name: str,
        max_attempts: int | None = None,
    ) -> T:
        """Run an async operation with basic retries and timeout handling."""

        last_error: Exception | None = None
        attempts = max(1, max_attempts if max_attempts is not None else self.max_retries + 1)

        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
                logger.info(
                    "LLM provider call succeeded",
                    extra={
                        "provider": self.llm_provider,
                        "operation": operation_name,
                        "attempt": attempt + 1,
                    },
                )
                return result
            except Exception as exc:  # pragma: no cover - depends on provider/runtime behavior
                last_error = exc
                logger.warning(
                    "LLM provider call failed",
                    extra={
                        "provider": self.llm_provider,
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "max_attempts": attempts,
                        "error": str(exc),
                    },
                )
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(min(2**attempt, 3))

        logger.error(
            "LLM provider call exhausted retries",
            extra={
                "provider": self.llm_provider,
                "operation": operation_name,
                "retry_count": attempts,
                "error": str(last_error) if last_error is not None else "unknown",
            },
        )
        raise RuntimeError(
            f"{self.llm_provider} {operation_name} failed after {attempts} attempts: "
            f"{str(last_error) if last_error is not None else 'unknown error'}"
        ) from last_error

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        """Parse a JSON object response into a clean dictionary."""

        if not content:
            return {}

        sanitized_content = content.strip()
        if sanitized_content.startswith("```"):
            sanitized_content = sanitized_content.strip("`")
            if sanitized_content.lower().startswith("json"):
                sanitized_content = sanitized_content[4:].strip()

        try:
            parsed = json.loads(sanitized_content)
        except json.JSONDecodeError:
            return {"content": content}
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
