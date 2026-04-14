"""Relevance scoring service."""

from __future__ import annotations

from math import sqrt

from app.services.ai.embedding_service import EmbeddingService


class RelevanceScorer:
    """Score topical relevance using embedding similarity."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        """Initialize the scorer with an embedding service dependency."""

        self.embedding_service = embedding_service or EmbeddingService()
        self._cache: dict[tuple[str, str], float] = {}

    async def score_relevance(self, post_text: str, niche_text: str) -> float:
        """Return a normalized relevance score in the range ``0..1``."""

        normalized_post = post_text.strip()
        normalized_niche = niche_text.strip()
        if not normalized_post or not normalized_niche:
            return 0.0

        cache_key = (normalized_post, normalized_niche)
        cached_score = self._cache.get(cache_key)
        if cached_score is not None:
            return cached_score

        post_embedding = await self.embedding_service.get_embedding(normalized_post)
        niche_embedding = await self.embedding_service.get_embedding(normalized_niche)
        if not post_embedding or not niche_embedding:
            return 0.0

        cosine_similarity = self._cosine_similarity(post_embedding, niche_embedding)
        normalized_score = self._normalize_similarity(cosine_similarity)
        self._cache[cache_key] = normalized_score
        return normalized_score

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""

        if len(left) != len(right) or not left:
            return 0.0

        left_magnitude = sqrt(sum(value * value for value in left))
        right_magnitude = sqrt(sum(value * value for value in right))
        if left_magnitude == 0.0 or right_magnitude == 0.0:
            return 0.0

        dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
        return dot_product / (left_magnitude * right_magnitude)

    def _normalize_similarity(self, similarity: float) -> float:
        """Normalize cosine similarity from ``-1..1`` into ``0..1``."""

        normalized = (similarity + 1.0) / 2.0
        return round(max(0.0, min(1.0, normalized)), 4)
