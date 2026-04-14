"""Opportunity scoring skeleton."""

from dataclasses import dataclass

from app.services.analytics.engagement_analyzer import EngagementVelocity
from app.services.behavior.tone_analyzer import ToneAnalysis


@dataclass(slots=True)
class DecisionScore:
    """Container for decision scoring output."""

    score: float
    recommendation: str
    components: dict[str, float]
    reasons: list[str]


class OpportunityScoringService:
    """Combine analysis signals into a decision score."""

    def __init__(
        self,
        relevance_weight: float = 0.5,
        tone_weight: float = 0.2,
        velocity_weight: float = 0.3,
    ) -> None:
        """Initialize decision scoring weights."""

        # TODO: store scoring weights.
        pass

    def score(
        self,
        relevance_score: float,
        tone_analysis: ToneAnalysis,
        velocity: EngagementVelocity,
    ) -> DecisionScore:
        """Produce a final decision score."""

        # TODO: implement scoring logic.
        pass

    def _recommendation_for_score(self, score: float) -> str:
        """Map a numeric score to a recommendation."""

        # TODO: implement recommendation mapping.
        pass
