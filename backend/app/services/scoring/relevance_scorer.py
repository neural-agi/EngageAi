"""Relevance scoring service."""

from __future__ import annotations

import logging
import re
from math import sqrt

from app.services.ai.embedding_service import EmbeddingService


logger = logging.getLogger(__name__)


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

        post_embedding, niche_embedding = await self._embedding_pair(
            normalized_post=normalized_post,
            normalized_niche=normalized_niche,
        )
        if not post_embedding or not niche_embedding:
            lexical_score = self._lexical_similarity(normalized_post, normalized_niche)
            self._cache[cache_key] = lexical_score
            logger.info(
                "Using lexical relevance fallback",
                extra={"score": lexical_score},
            )
            return lexical_score

        cosine_similarity = self._cosine_similarity(post_embedding, niche_embedding)
        normalized_score = self._normalize_similarity(cosine_similarity)
        self._cache[cache_key] = normalized_score
        return normalized_score

    async def _embedding_pair(
        self,
        normalized_post: str,
        normalized_niche: str,
    ) -> tuple[list[float], list[float]]:
        """Fetch both embeddings and absorb provider failures into lexical fallback."""

        try:
            post_embedding = await self.embedding_service.get_embedding(normalized_post)
            niche_embedding = await self.embedding_service.get_embedding(normalized_niche)
        except Exception as exc:
            logger.warning(
                "Embedding relevance scoring failed; falling back to lexical similarity",
                extra={"error": str(exc)},
            )
            return [], []
        return post_embedding, niche_embedding

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

    def _lexical_similarity(self, post_text: str, niche_text: str) -> float:
        """Score textual overlap when embeddings are unavailable."""

        post_terms = self._tokenize(post_text)
        niche_terms = self._tokenize(niche_text)
        if not post_terms or not niche_terms:
            return 0.0

        shared_terms = post_terms.intersection(niche_terms)
        overlap_ratio = len(shared_terms) / len(niche_terms)
        phrase_bonus = 0.2 if niche_text.lower() in post_text.lower() else 0.0
        specificity_bonus = min(0.15, len(shared_terms) * 0.03)
        return round(max(0.0, min(1.0, overlap_ratio + phrase_bonus + specificity_bonus)), 4)

    def _tokenize(self, text: str) -> set[str]:
        """Split text into a lightweight token set for lexical matching."""

        return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower())}
