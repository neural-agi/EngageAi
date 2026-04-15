"""Analyst agent implementation."""

from __future__ import annotations

from typing import Any

from app.services.scoring.relevance_scorer import RelevanceScorer


class AnalystAgent:
    """Analyze post relevance and engagement potential."""

    def __init__(self, relevance_scorer: RelevanceScorer | None = None) -> None:
        """Initialize the analyst agent dependencies."""

        self.relevance_scorer = relevance_scorer or RelevanceScorer()

    async def analyze(
        self,
        post_text: str,
        niche_text: str,
        engagement_metrics: dict[str, Any],
    ) -> dict[str, float | str]:
        """Analyze a post and return a simple engagement decision."""

        relevance_score = await self.relevance_scorer.score_relevance(
            post_text=post_text,
            niche_text=niche_text,
        )
        engagement_score = self._score_engagement(engagement_metrics)
        final_score = self._combine_scores(
            relevance_score=relevance_score,
            engagement_score=engagement_score,
        )

        return {
            "relevance_score": relevance_score,
            "engagement_score": engagement_score,
            "final_score": final_score,
            "decision": self._make_decision(final_score),
            "embedding_status": getattr(self.relevance_scorer, "last_embedding_status", "unknown"),
        }

    def _score_engagement(self, engagement_metrics: dict[str, Any]) -> float:
        """Score engagement using a small likes/comments heuristic."""

        likes = self._safe_int(engagement_metrics.get("likes"))
        comments = self._safe_int(engagement_metrics.get("comments"))
        time_value = self._safe_float(engagement_metrics.get("time"), default=1.0)

        weighted_engagement = likes + (comments * 2)
        normalized_time = max(time_value, 1.0)
        engagement_rate = weighted_engagement / normalized_time

        # TODO: incorporate tone analysis into engagement quality scoring.
        # TODO: replace this heuristic with richer time-decay and intent-aware scoring.
        return round(min(1.0, engagement_rate / 25.0), 4)

    def _combine_scores(self, relevance_score: float, engagement_score: float) -> float:
        """Combine relevance and engagement into a final score."""

        final_score = (relevance_score * 0.7) + (engagement_score * 0.3)
        return round(max(0.0, min(1.0, final_score)), 4)

    def _make_decision(self, final_score: float) -> str:
        """Convert the final score into a binary decision."""

        return "engage" if final_score >= 0.5 else "ignore"

    def _safe_int(self, value: Any) -> int:
        """Convert a metric value into a non-negative integer."""

        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """Convert a metric value into a non-negative float."""

        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return default
