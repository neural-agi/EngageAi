"""Analytics and performance evaluation helpers."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Handles analytics and performance evaluation.
    """

    def compute_viral_score(self, post: Dict) -> float:
        """
        Compute how "viral" a post is.

        The score balances:
        - overall engagement volume
        - engagement velocity over time
        """

        if not isinstance(post, dict):
            logger.warning("Invalid post payload for viral score computation")
            return 0.0

        likes = self._get_non_negative_number(post, "likes")
        comments = self._get_non_negative_number(post, "comments")
        shares = self._get_non_negative_number(post, "shares")
        hours_since_post = self._get_positive_number(post, "hours_since_post", default=1.0)

        # Comments and shares usually indicate stronger intent than passive likes.
        weighted_engagement = (likes * 1.0) + (comments * 3.0) + (shares * 5.0)
        engagement_velocity = weighted_engagement / hours_since_post

        # Blend raw engagement and time-adjusted velocity to avoid brittle spikes.
        volume_score = self._normalize_log(weighted_engagement, reference=250.0)
        velocity_score = self._normalize_log(engagement_velocity, reference=60.0)
        score = self._clamp_score((volume_score * 0.4) + (velocity_score * 0.6))

        logger.info(
            "Computed viral score",
            extra={
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "hours_since_post": hours_since_post,
                "weighted_engagement": round(weighted_engagement, 4),
                "engagement_velocity": round(engagement_velocity, 4),
                "viral_score": score,
            },
        )
        return score

    def get_dashboard_stats(self, posts: List[Dict]) -> Dict:
        """
        Aggregate analytics for dashboard.
        """

        if not isinstance(posts, list):
            logger.warning("Invalid posts payload for dashboard stats")
            return {
                "total_posts": 0,
                "total_likes": 0.0,
                "total_comments": 0.0,
                "avg_engagement": 0.0,
            }

        valid_posts = [post for post in posts if isinstance(post, dict)]
        total_posts = len(valid_posts)
        total_likes = sum(self._get_non_negative_number(post, "likes") for post in valid_posts)
        total_comments = sum(self._get_non_negative_number(post, "comments") for post in valid_posts)

        avg_engagement = (total_likes + total_comments) / max(total_posts, 1)
        stats = {
            "total_posts": total_posts,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "avg_engagement": round(avg_engagement, 4),
        }

        logger.info("Computed dashboard analytics", extra=stats)
        return stats

    def _get_non_negative_number(self, payload: Dict[str, Any], field_name: str) -> float:
        """Return a numeric field value, defaulting invalid values to zero."""

        raw_value = payload.get(field_name, 0)
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid analytics field value",
                extra={"field_name": field_name, "raw_value": raw_value},
            )
            return 0.0

        return max(0.0, numeric_value)

    def _get_positive_number(
        self,
        payload: Dict[str, Any],
        field_name: str,
        default: float = 1.0,
    ) -> float:
        """Return a strictly positive number for time-based calculations."""

        value = self._get_non_negative_number(payload, field_name)
        if value <= 0.0:
            logger.warning(
                "Missing or non-positive analytics field; using default",
                extra={"field_name": field_name, "default": default},
            )
            return default
        return value

    def _normalize_log(self, value: float, reference: float) -> float:
        """Normalize a value into the 0..1 range using logarithmic scaling."""

        safe_value = max(0.0, value)
        safe_reference = max(1.0, reference)
        normalized = math.log1p(safe_value) / math.log1p(safe_reference)
        return self._clamp_score(normalized)

    def _clamp_score(self, value: float) -> float:
        """Clamp a numeric score into the 0..1 range."""

        return round(max(0.0, min(1.0, value)), 4)
