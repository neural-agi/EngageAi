"""Google Gemini client wrapper."""

from __future__ import annotations

from typing import Any

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional dependency fallback
    genai = None


class GeminiClient:
    """Minimal sync wrapper around the Google Generative AI SDK."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-1.5-flash",
        embedding_model: str = "models/text-embedding-004",
    ) -> None:
        """Store Gemini configuration for generation and embeddings."""

        self.api_key = api_key.strip()
        self.model = model
        self.embedding_model = embedding_model

    @property
    def is_available(self) -> bool:
        """Return whether the SDK and API key are available."""

        return genai is not None and bool(self.api_key)

    def generate_text(self, prompt: str) -> str:
        """Generate plain text from Gemini."""

        self._configure()
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(prompt)
        return self._extract_text(response).strip()

    def get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector using Gemini-compatible embedding APIs."""

        self._configure()
        response = genai.embed_content(
            model=self.embedding_model,
            content=text,
            task_type="retrieval_document",
        )
        embedding = response.get("embedding", []) if isinstance(response, dict) else []
        return [float(value) for value in embedding]

    def _configure(self) -> None:
        """Configure the Gemini SDK and verify availability."""

        if genai is None or not self.api_key:
            raise RuntimeError("Google Generative AI SDK is unavailable or GEMINI_API_KEY is missing.")
        genai.configure(api_key=self.api_key)

    def _extract_text(self, response: Any) -> str:
        """Extract plain text from a Gemini response payload."""

        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            return response_text

        candidates = getattr(response, "candidates", None)
        if not isinstance(candidates, list):
            return ""

        text_parts: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None)
            if not isinstance(parts, list):
                continue
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    text_parts.append(part_text.strip())
        return "\n".join(text_parts)
