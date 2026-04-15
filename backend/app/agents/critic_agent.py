"""Critic agent implementation."""

from __future__ import annotations

import random
from typing import Any


class CriticAgent:
    """Review, filter, and rank generated comment variants."""

    def __init__(self, minimum_score: float = 0.45) -> None:
        """Initialize the critic agent configuration."""

        self.minimum_score = minimum_score
        self._unsafe_markers = {
            "buy now",
            "click here",
            "guaranteed",
            "dm me",
            "follow me",
            "subscribe",
            "act now",
        }
        self._generic_markers = {
            "great post",
            "great point",
            "interesting perspective",
            "well said",
            "thanks for sharing",
            "love this",
            "so true",
            "this is great",
        }
        self._selected_comment_texts: set[str] = set()
        self._rng = random.Random()

    async def review(
        self,
        comment_variants: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any] | list[dict[str, Any]] | None]:
        """Filter low-quality variants and return ranked results."""

        normalized_variants = self._normalize_variants(comment_variants)
        ranked_variants: list[dict[str, Any]] = []

        for variant in normalized_variants:
            if not self._is_safe_variant(variant["text"]):
                continue
            if self._was_already_selected(variant["text"]):
                continue

            score = self._score_variant(variant)
            if score < self.minimum_score:
                continue

            ranked_variants.append(
                {
                    **variant,
                    "score": score,
                }
            )

        ranked_variants.sort(key=lambda item: float(item["score"]), reverse=True)
        best_variant = self._select_best_variant(ranked_variants)
        if best_variant is not None:
            self._selected_comment_texts.add(self._normalize_text(str(best_variant["text"])))

        # TODO: add toxicity detection beyond simple unsafe phrase filtering.
        # TODO: incorporate brand and persona alignment checks into ranking.
        return {
            "best_variant": best_variant,
            "ranked_variants": ranked_variants,
        }

    def _normalize_variants(self, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize raw variant payloads into a clean internal structure."""

        normalized_variants: list[dict[str, Any]] = []
        for item in variants:
            if not isinstance(item, dict):
                continue

            text = str(item.get("text", "")).strip()
            style = str(item.get("style", "")).strip() or "unknown"
            confidence = self._safe_confidence(item.get("confidence"))
            reference_terms = item.get("reference_terms", [])
            if not text:
                continue

            normalized_variants.append(
                {
                    "text": text,
                    "style": style,
                    "confidence": confidence,
                    "reference_terms": reference_terms if isinstance(reference_terms, list) else [],
                    "generation_source": str(item.get("generation_source", "")).strip() or "llm",
                    "llm_status": str(item.get("llm_status", "")).strip() or "success",
                    "fallback_used": bool(item.get("fallback_used", False)),
                    "warning": str(item.get("warning", "")).strip() or None,
                }
            )

        return normalized_variants

    def _is_safe_variant(self, text: str) -> bool:
        """Reject obvious spammy or unsafe variants."""

        normalized_text = " ".join(text.lower().split())
        if len(normalized_text) < 12:
            return False
        if any(marker in normalized_text for marker in self._unsafe_markers):
            return False
        if normalized_text.count("!") > 1:
            return False
        return True

    def _score_variant(self, variant: dict[str, Any]) -> float:
        """Score a variant using lightweight quality heuristics."""

        text = str(variant["text"])
        confidence = float(variant["confidence"])

        length_quality = self._score_length_quality(text)
        clarity = self._score_clarity(text)
        originality = self._score_originality(text)
        specificity = self._score_specificity(variant)

        score = (
            (length_quality * 0.2)
            + (clarity * 0.2)
            + (confidence * 0.2)
            + (originality * 0.2)
            + (specificity * 0.2)
        )
        return round(max(0.0, min(1.0, score)), 4)

    def _score_length_quality(self, text: str) -> float:
        """Score comment length against a simple preferred range."""

        text_length = len(text.strip())
        if 45 <= text_length <= 180:
            return 1.0
        if 25 <= text_length < 45 or 180 < text_length <= 240:
            return 0.7
        if 15 <= text_length < 25:
            return 0.45
        return 0.2

    def _score_clarity(self, text: str) -> float:
        """Score clarity using basic readability heuristics."""

        word_count = len(text.split())
        if word_count == 0:
            return 0.0

        uppercase_ratio = sum(1 for character in text if character.isupper()) / max(len(text), 1)
        repeated_punctuation = "!!" in text or "??" in text or "..." in text
        question_bonus = 0.1 if text.strip().endswith("?") else 0.0

        clarity = 0.75
        if 6 <= word_count <= 28:
            clarity += 0.15
        if uppercase_ratio > 0.25:
            clarity -= 0.25
        if repeated_punctuation:
            clarity -= 0.15

        return round(max(0.0, min(1.0, clarity + question_bonus)), 4)

    def _score_originality(self, text: str) -> float:
        """Boost comments that feel specific and non-generic."""

        normalized_text = self._normalize_text(text)
        originality = 0.72

        if any(marker in normalized_text for marker in self._generic_markers):
            originality -= 0.38
        if self._contains_specific_detail(text):
            originality += 0.18
        if self._style_opening_bonus(text):
            originality += 0.08

        return round(max(0.0, min(1.0, originality)), 4)

    def _score_specificity(self, variant: dict[str, Any]) -> float:
        """Boost variants that tie back to concrete post details."""

        text = str(variant["text"])
        specificity = 0.58

        reference_terms = variant.get("reference_terms", [])
        if isinstance(reference_terms, list):
            matched_terms = [
                str(term).lower()
                for term in reference_terms
                if str(term).strip() and str(term).lower() in text.lower()
            ]
            specificity += min(0.24, len(matched_terms) * 0.12)

        if self._contains_specific_detail(text):
            specificity += 0.14

        return round(max(0.0, min(1.0, specificity)), 4)

    def _select_best_variant(
        self,
        ranked_variants: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Choose a final variant from the top ranked options with light randomness."""

        if not ranked_variants:
            return None

        top_candidates = ranked_variants[:3]
        weights = [max(float(candidate["score"]), 0.01) for candidate in top_candidates]
        return self._rng.choices(top_candidates, weights=weights, k=1)[0]

    def _was_already_selected(self, text: str) -> bool:
        """Check whether a variant text has already been used earlier in the run."""

        return self._normalize_text(text) in self._selected_comment_texts

    def _normalize_text(self, text: str) -> str:
        """Normalize text for repeat detection."""

        return " ".join(text.lower().split())

    def _contains_specific_detail(self, text: str) -> bool:
        """Detect simple specificity signals such as numbers or long domain terms."""

        words = text.split()
        has_number = any(character.isdigit() for character in text)
        long_terms = sum(1 for word in words if len(word.strip(".,!?")) >= 8)
        return has_number or long_terms >= 2

    def _style_opening_bonus(self, text: str) -> bool:
        """Check whether the comment starts with a more distinctive framing."""

        normalized_text = self._normalize_text(text)
        return normalized_text.startswith(
            (
                "small contrarian take",
                "this reminds me",
                "how are you thinking",
                "the sharpest insight",
            )
        )

    def _safe_confidence(self, value: Any) -> float:
        """Normalize confidence values to the ``0..1`` range."""

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5

        return max(0.0, min(1.0, confidence))
