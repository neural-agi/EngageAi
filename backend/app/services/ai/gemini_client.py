"""Google Gemini client wrapper."""

from __future__ import annotations

from typing import Any

try:
    from google import genai
except ImportError:  # pragma: no cover - optional dependency fallback
    genai = None


class GeminiClient:
    """Minimal sync wrapper around the Google GenAI SDK."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.0-flash",
        embedding_model: str = "text-embedding-004",
    ) -> None:
        """Store Gemini configuration for generation and embeddings."""

        self.api_key = api_key.strip()
        self.model = model
        self.embedding_model = embedding_model
        self._client: Any | None = None

    @property
    def is_available(self) -> bool:
        """Return whether the SDK and API key are available."""

        return genai is not None and bool(self.api_key)

    def generate_text(self, prompt: str) -> str:
        """Generate plain text from Gemini."""

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()
        raise RuntimeError("Gemini response did not include text output.")

    def get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector when the SDK provides one cleanly."""

        client = self._get_client()
        response = client.models.embed_content(
            model=self.embedding_model,
            contents=text,
        )
        embedding = self._extract_embedding(response)
        if not embedding:
            raise RuntimeError("Gemini embedding response did not include usable values.")
        return embedding

    def _get_client(self) -> Any:
        """Return an initialized Gemini client."""

        if genai is None or not self.api_key:
            raise RuntimeError("Google GenAI SDK is unavailable or GEMINI_API_KEY is missing.")
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _extract_embedding(self, response: Any) -> list[float]:
        """Extract embedding values from multiple SDK response shapes."""

        direct_embedding = getattr(response, "embedding", None)
        direct_values = getattr(direct_embedding, "values", None)
        if isinstance(direct_values, list):
            return [float(value) for value in direct_values]

        embeddings = getattr(response, "embeddings", None)
        if isinstance(embeddings, list) and embeddings:
            first_embedding = embeddings[0]
            first_values = getattr(first_embedding, "values", None)
            if isinstance(first_values, list):
                return [float(value) for value in first_values]

        if isinstance(response, dict):
            embedding_payload = response.get("embedding")
            if isinstance(embedding_payload, dict):
                values = embedding_payload.get("values")
                if isinstance(values, list):
                    return [float(value) for value in values]

        return []
