"""Embedding service wrapper."""

from __future__ import annotations

from app.services.ai.provider import AIProvider


class EmbeddingService:
    """Lightweight embedding service with in-memory caching."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        """Initialize the service with an AI provider dependency."""

        self.provider = provider or AIProvider()
        self._cache: dict[str, list[float]] = {}

    async def get_embedding(self, text: str) -> list[float]:
        """Return an embedding for the given text input."""

        normalized_text = text.strip()
        if not normalized_text:
            return []

        cached_embedding = self._cache.get(normalized_text)
        if cached_embedding is not None:
            return list(cached_embedding)

        embedding = await self.provider.get_embedding(normalized_text)
        clean_embedding = [float(value) for value in embedding]
        self._cache[normalized_text] = clean_embedding
        return list(clean_embedding)
