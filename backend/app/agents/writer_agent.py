"""Writer agent implementation."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.memory_store import MemoryStore
from app.services.ai.provider import AIProvider


logger = logging.getLogger(__name__)


class WriterAgent:
    """Generate simple engagement comment variants."""

    def __init__(
        self,
        provider: AIProvider | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        """Initialize the writer agent dependencies."""

        self.provider = provider or AIProvider()
        self.memory_store = memory_store or MemoryStore()
        self._generated_comment_texts: set[str] = set()
        self._historical_comment_texts = self.memory_store.get_generated_comments()
        self._stopwords = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "for",
            "from",
            "how",
            "in",
            "into",
            "is",
            "it",
            "of",
            "on",
            "or",
            "that",
            "the",
            "this",
            "to",
            "with",
            "why",
        }

    async def draft(
        self,
        post_text: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate comment variants for a post."""

        normalized_post = post_text.strip()
        if not normalized_post:
            return []

        context = context or {}
        prompt = self._build_prompt(normalized_post, context)
        variants: list[dict[str, Any]] = []
        try:
            response = await self.provider.generate_structured(prompt)
            variants = self._tag_variants(self._normalize_variants(response), source="llm")
        except Exception as exc:
            logger.warning(
                "Writer provider call failed; using fallback variants",
                extra={
                    "error": str(exc),
                    "llm_status": "failed",
                    "fallback_used": True,
                },
            )
        if variants:
            variants = self._deduplicate_variants(variants)
            variants = self._apply_style_rotation(variants, context)
        if len(variants) >= 5:
            self._remember_variants(variants)
            return variants

        fallback_variants = self._fallback_variants(normalized_post, context)
        fallback_variants = self._apply_style_rotation(fallback_variants, context)
        combined_variants = [*variants, *fallback_variants]
        if combined_variants:
            self._remember_variants(combined_variants)
            return combined_variants

        return []

    async def draft_batch(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Generate variants for multiple posts in one provider call."""

        normalized_items = self._normalize_batch_items(items)
        if not normalized_items:
            return {}

        response_items: dict[str, list[dict[str, Any]]] = {}
        try:
            response = await self.provider.generate_structured(self._build_batch_prompt(normalized_items))
            response_items = self._normalize_batch_response(response)
        except Exception as exc:
            logger.warning(
                "Writer provider call failed; using fallback variants",
                extra={
                    "error": str(exc),
                    "llm_status": "failed",
                    "fallback_used": True,
                },
            )

        batched_variants: dict[str, list[dict[str, Any]]] = {}
        for item in normalized_items:
            post_id = item["post_id"]
            context = item["context"]
            variants = self._tag_variants(response_items.get(post_id, []), source="llm")
            if variants:
                variants = self._deduplicate_variants(variants)
                variants = self._apply_style_rotation(variants, context)

            if len(variants) < 5:
                fallback_variants = self._fallback_variants(item["post_text"], context)
                fallback_variants = self._apply_style_rotation(fallback_variants, context)
                variants = [*variants, *fallback_variants]

            if variants:
                self._remember_variants(variants)
                batched_variants[post_id] = variants

        return batched_variants

    def _build_prompt(self, post_text: str, context: dict[str, Any]) -> str:
        """Build a simple structured-generation prompt for comment variants."""

        signals = self._extract_post_signals(post_text, context)
        persona_prompt = self._build_persona_prompt(context)
        style_rotation_prompt = self._build_style_rotation_prompt(context)
        return (
            "Generate 5 concise LinkedIn comment variants as JSON with a top-level "
            "'variants' array. Each item must contain 'text', 'style', and 'confidence'. "
            "Use these styles exactly once: question, insight, contrarian, bold statement, storytelling. "
            "Each comment must directly reference the post content, feel human, avoid generic praise, "
            "and include a concrete detail or phrase from the source post.\n\n"
            f"{persona_prompt}\n"
            f"{style_rotation_prompt}\n\n"
            f"Post:\n{post_text}\n\n"
            f"Context:\n{context}\n\n"
            f"Reference signals:\n{signals}"
        )

    def _build_batch_prompt(self, items: list[dict[str, Any]]) -> str:
        """Build one prompt that requests variants for multiple posts."""

        prompt_items: list[str] = []
        for item in items:
            prompt_items.append(
                "\n".join(
                    [
                        f"post_id: {item['post_id']}",
                        f"post_text: {item['post_text']}",
                        f"context: {item['context']}",
                        f"signals: {self._extract_post_signals(item['post_text'], item['context'])}",
                    ]
                )
            )

        return (
            "Generate LinkedIn comment variants as JSON with a top-level 'items' array. "
            "Each item must contain 'post_id' and 'variants'. Each 'variants' array must contain 5 objects with "
            "'text', 'style', and 'confidence'. Use these styles exactly once per post: question, insight, contrarian, bold statement, storytelling. "
            "Each comment must directly reference its source post, stay concise, and avoid generic praise.\n\n"
            + "\n\n".join(prompt_items)
        )

    def _normalize_batch_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize one batched input payload."""

        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            post_text = str(item.get("post_text", "")).strip()
            if not post_text:
                continue
            normalized_items.append(
                {
                    "post_id": str(item.get("post_id", "")).strip() or f"post-{index}",
                    "post_text": post_text,
                    "context": item.get("context", {}) if isinstance(item.get("context"), dict) else {},
                }
            )
        return normalized_items

    def _normalize_batch_response(self, response: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Normalize a batched provider response into a per-post mapping."""

        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            return {}

        normalized_items: dict[str, list[dict[str, Any]]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            post_id = str(item.get("post_id", "")).strip()
            variants = item.get("variants")
            if not post_id or not isinstance(variants, list):
                continue
            normalized_items[post_id] = self._normalize_variants({"variants": variants})
        return normalized_items

    def _normalize_variants(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize structured provider output into clean variant dictionaries."""

        raw_variants = response.get("variants")
        if not isinstance(raw_variants, list):
            return []

        normalized_variants: list[dict[str, Any]] = []
        for item in raw_variants:
            if not isinstance(item, dict):
                continue

            text = str(item.get("text", "")).strip()
            style = str(item.get("style", "")).strip()
            confidence = self._safe_confidence(item.get("confidence"))
            if not text or not style:
                continue

            reference_terms = item.get("reference_terms")
            if not isinstance(reference_terms, list):
                reference_terms = self._extract_reference_terms(text)

            normalized_variants.append(
                {
                    "text": text,
                    "style": style,
                    "confidence": confidence,
                    "reference_terms": [str(term).strip() for term in reference_terms if str(term).strip()],
                    "generation_source": str(item.get("generation_source", "")).strip() or "llm",
                    "llm_status": str(item.get("llm_status", "")).strip() or "success",
                    "fallback_used": bool(item.get("fallback_used", False)),
                    "warning": str(item.get("warning", "")).strip() or None,
                }
            )

        return normalized_variants

    def _fallback_variants(
        self,
        post_text: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return deterministic variants when AI output is unavailable."""

        signals = self._extract_post_signals(post_text, context)
        primary_reference = signals["primary_reference"]
        supporting_reference = signals["supporting_reference"]
        numeric_reference = signals["numeric_reference"]
        topic = signals["topic"]
        persona = self._persona_context(context)

        raw_variants: list[dict[str, Any]] = [
            {
                "text": self._build_persona_text(
                    style="question",
                    persona=persona,
                    primary_reference=primary_reference,
                    supporting_reference=supporting_reference,
                    topic=topic,
                    numeric_reference=numeric_reference,
                ),
                "style": "question",
                "confidence": 0.79,
                "reference_terms": [primary_reference, topic],
            },
            {
                "text": self._build_persona_text(
                    style="insight",
                    persona=persona,
                    primary_reference=primary_reference,
                    supporting_reference=supporting_reference,
                    topic=topic,
                    numeric_reference=numeric_reference,
                ),
                "style": "insight",
                "confidence": 0.82,
                "reference_terms": [primary_reference, topic],
            },
            {
                "text": self._build_persona_text(
                    style="contrarian",
                    persona=persona,
                    primary_reference=primary_reference,
                    supporting_reference=supporting_reference,
                    topic=topic,
                    numeric_reference=numeric_reference,
                ),
                "style": "contrarian",
                "confidence": 0.74,
                "reference_terms": [primary_reference, supporting_reference],
            },
            {
                "text": self._build_persona_text(
                    style="bold statement",
                    persona=persona,
                    primary_reference=primary_reference,
                    supporting_reference=supporting_reference,
                    topic=topic,
                    numeric_reference=numeric_reference,
                ),
                "style": "bold statement",
                "confidence": 0.76,
                "reference_terms": [primary_reference, topic],
            },
            {
                "text": self._build_persona_text(
                    style="storytelling",
                    persona=persona,
                    primary_reference=primary_reference,
                    supporting_reference=supporting_reference,
                    topic=topic,
                    numeric_reference=numeric_reference,
                ),
                "style": "storytelling",
                "confidence": 0.71,
                "reference_terms": [primary_reference, supporting_reference],
            },
        ]

        variants = self._deduplicate_variants(
            self._tag_variants(
                raw_variants,
                source="fallback",
                warning="LLM generation failed, using fallback content",
            )
        )

        # TODO: add quality scoring and ranking across generated variants.
        return variants

    def _deduplicate_variants(
        self,
        variants: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop repeated comment text across the current pipeline run."""

        unique_variants: list[dict[str, Any]] = []
        for variant in variants:
            text = str(variant.get("text", "")).strip()
            if not text:
                continue

            normalized_text = self._normalize_text(text)
            if normalized_text in self._generated_comment_texts:
                continue
            if normalized_text in self._historical_comment_texts:
                continue

            self._generated_comment_texts.add(normalized_text)
            unique_variants.append(
                {
                    "text": text,
                    "style": str(variant.get("style", "")).strip() or "unknown",
                    "confidence": self._safe_confidence(variant.get("confidence")),
                    "reference_terms": [
                        str(term).strip()
                        for term in variant.get("reference_terms", [])
                        if str(term).strip()
                    ],
                    "generation_source": str(variant.get("generation_source", "")).strip() or "llm",
                    "llm_status": str(variant.get("llm_status", "")).strip() or "success",
                    "fallback_used": bool(variant.get("fallback_used", False)),
                    "warning": str(variant.get("warning", "")).strip() or None,
                }
            )

        return unique_variants

    def _apply_style_rotation(
        self,
        variants: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Adjust confidence scores to rotate styles over time."""

        style_usage = context.get("style_usage", {})
        persona = self._persona_context(context)
        preferred_styles = set(persona.get("preferred_styles", []))

        adjusted_variants: list[dict[str, Any]] = []
        for variant in variants:
            style = str(variant.get("style", "")).strip()
            base_confidence = self._safe_confidence(variant.get("confidence"))

            usage_count = 0
            if isinstance(style_usage, dict):
                raw_count = style_usage.get(style, 0)
                try:
                    usage_count = max(0, int(raw_count))
                except (TypeError, ValueError):
                    usage_count = 0

            rotation_adjustment = 0.08 if usage_count == 0 else 0.03 if usage_count == 1 else -0.04 * min(usage_count - 1, 3)
            persona_adjustment = 0.04 if style in preferred_styles else 0.0
            adjusted_confidence = self._safe_confidence(
                base_confidence + rotation_adjustment + persona_adjustment
            )

            adjusted_variants.append(
                {
                    **variant,
                    "confidence": adjusted_confidence,
                }
            )

        return adjusted_variants

    def _tag_variants(
        self,
        variants: list[dict[str, Any]],
        *,
        source: str,
        warning: str | None = None,
    ) -> list[dict[str, Any]]:
        """Apply consistent generation metadata to one variant list."""

        tagged_variants: list[dict[str, Any]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            tagged_variants.append(
                {
                    **variant,
                    "generation_source": source,
                    "llm_status": "success" if source == "llm" else "failed",
                    "fallback_used": source != "llm",
                    "warning": warning if source != "llm" else str(variant.get("warning", "")).strip() or None,
                }
            )
        return tagged_variants

    def _remember_variants(self, variants: list[dict[str, Any]]) -> None:
        """Persist generated comments so future runs can avoid reuse."""

        comment_texts = [
            str(variant.get("text", "")).strip()
            for variant in variants
            if str(variant.get("text", "")).strip()
        ]
        if not comment_texts:
            return

        self.memory_store.remember_generated_comments(comment_texts)
        self._historical_comment_texts.update(
            {self._normalize_text(comment_text) for comment_text in comment_texts}
        )

    def _build_persona_prompt(self, context: dict[str, Any]) -> str:
        """Build persona instructions for the structured generation prompt."""

        persona_prompt = str(context.get("persona_prompt", "")).strip()
        if persona_prompt:
            return persona_prompt

        persona = self._persona_context(context)
        if not persona:
            return "Persona: keep the tone professional, clear, and human."

        vocabulary = ", ".join(persona.get("vocabulary", []))
        preferred_styles = ", ".join(persona.get("preferred_styles", []))
        return (
            f"Persona: {persona.get('name', 'Default persona')} ({persona.get('archetype', 'generalist')}). "
            f"Tone: {persona.get('tone', 'professional')}. "
            f"Phrasing: {persona.get('phrasing', 'clear and conversational')}. "
            f"Signature: {persona.get('signature', 'sounds like a thoughtful operator')}. "
            f"Preferred styles: {preferred_styles}. "
            f"Use vocabulary such as {vocabulary}."
        )

    def _build_style_rotation_prompt(self, context: dict[str, Any]) -> str:
        """Build prompt guidance to rotate styles over time."""

        style_usage = context.get("style_usage", {})
        if not isinstance(style_usage, dict) or not style_usage:
            return "Style rotation: give each style a distinct voice and avoid repeating the same cadence."

        ordered_usage = ", ".join(
            f"{style}={count}"
            for style, count in sorted(style_usage.items(), key=lambda item: (item[1], item[0]))
        )
        return (
            "Style rotation: use less-frequent styles more aggressively in this batch. "
            f"Current usage counts: {ordered_usage}."
        )

    def _persona_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return the normalized persona payload from writer context."""

        persona = context.get("persona")
        if isinstance(persona, dict):
            return persona
        return {}

    def _build_persona_text(
        self,
        style: str,
        persona: dict[str, Any],
        primary_reference: str,
        supporting_reference: str,
        topic: str,
        numeric_reference: str,
    ) -> str:
        """Generate a fallback comment variant aligned to persona voice and style."""

        archetype = str(persona.get("archetype", "")).strip().lower()
        signature = str(persona.get("signature", "")).strip()
        vocabulary = persona.get("vocabulary", [])
        lexicon = str(vocabulary[0]).strip() if isinstance(vocabulary, list) and vocabulary else "execution"

        if style == "question":
            templates = {
                "analytical expert": f"From a {signature} angle, what metric would you watch first around {primary_reference} as teams scale {topic}?",
                "bold contrarian": f"{signature} makes me ask whether {primary_reference} is the real advantage here, or just the visible symptom of a deeper {lexicon} problem?",
                "friendly storyteller": f"{signature} makes me wonder how teams hold onto {primary_reference} once the day-to-day reality of {topic} gets messy?",
                "industry insider": f"From the operator side, how do you keep {primary_reference} intact once {topic} moves from pilot to rollout?",
            }
        elif style == "insight":
            templates = {
                "analytical expert": f"The strongest signal here is {primary_reference}. That is usually where {topic} turns into a repeatable {lexicon} instead of a loose idea.",
                "bold contrarian": f"The overlooked part is {supporting_reference}. {primary_reference} gets the attention, but {supporting_reference} is where the real leverage usually hides.",
                "friendly storyteller": f"What lands for me is how {primary_reference} changes the day-to-day rhythm. That is often the point where {topic} starts feeling real to a team.",
                "industry insider": f"What stands out from an operator lens is {primary_reference}. That is usually the point where adoption either compounds or stalls in {topic}.",
            }
        elif style == "contrarian":
            templates = {
                "analytical expert": f"I think the harder read is that {primary_reference} matters less than {supporting_reference}, because that is where the operating friction actually shows up.",
                "bold contrarian": f"Small contrarian take: {primary_reference} sounds compelling, but {supporting_reference} is probably the detail that decides whether this survives contact with reality.",
                "friendly storyteller": f"I have seen teams get excited about {primary_reference} and still miss the mark because {supporting_reference} never got solved in practice.",
                "industry insider": f"Contrarian operator view: {primary_reference} is not the bottleneck most teams think it is. {supporting_reference} usually creates the real drag.",
            }
        elif style == "bold statement":
            templates = {
                "analytical expert": f"{primary_reference} is becoming a real strategic edge in {topic}, not just a nice idea teams mention in planning decks.",
                "bold contrarian": f"The market is still underrating {primary_reference}. Teams that ignore it in {topic} will keep mistaking motion for progress.",
                "friendly storyteller": f"{primary_reference} is the kind of shift that quietly changes how a team works long before people have the language to describe it.",
                "industry insider": f"{primary_reference} is no longer optional in serious {topic} rollouts. It is part of the baseline operating expectation now.",
            }
        else:
            templates = {
                "analytical expert": f"{signature} reminds me that teams often start with {supporting_reference} and only later realize the real unlock comes from sharpening {primary_reference}{numeric_reference}.",
                "bold contrarian": f"I have watched teams celebrate {primary_reference} early and still lose momentum because {supporting_reference} never held up once the pressure increased{numeric_reference}.",
                "friendly storyteller": f"This reminds me of teams that thought {supporting_reference} was enough, then saw how much changed once {primary_reference} finally clicked{numeric_reference}.",
                "industry insider": f"This sounds a lot like real rollouts where {supporting_reference} gets the meeting-time attention, but {primary_reference} ends up driving the result once execution starts{numeric_reference}.",
            }

        return templates.get(archetype, templates["analytical expert"])

    def _extract_post_signals(self, post_text: str, context: dict[str, Any]) -> dict[str, str]:
        """Extract lightweight content signals used to anchor comment variants."""

        sentences = [
            sentence.strip()
            for sentence in re.split(r"[.!?]+", post_text)
            if sentence.strip()
        ]
        primary_sentence = sentences[0] if sentences else post_text.strip()
        secondary_sentence = sentences[1] if len(sentences) > 1 else primary_sentence

        keywords = self._extract_reference_terms(post_text)
        primary_reference = self._reference_phrase(primary_sentence, fallback=keywords[:2])
        supporting_reference = self._reference_phrase(secondary_sentence, fallback=keywords[2:4])
        topic = str(context.get("topic", "")).strip() or self._excerpt(post_text, max_length=45)
        numeric_reference = self._extract_numeric_reference(post_text)

        return {
            "primary_reference": primary_reference,
            "supporting_reference": supporting_reference,
            "topic": topic,
            "numeric_reference": numeric_reference,
        }

    def _reference_phrase(self, text: str, fallback: list[str] | None = None) -> str:
        """Build a short post-grounded reference phrase."""

        compact_text = " ".join(text.split())
        if compact_text:
            words = compact_text.split()
            if len(words) >= 3:
                return " ".join(words[: min(6, len(words))]).strip(",.:;")
            return compact_text.strip(",.:;")

        if fallback:
            return " ".join(fallback).strip() or "the execution detail"
        return "the execution detail"

    def _extract_reference_terms(self, text: str) -> list[str]:
        """Extract a short list of meaningful reference terms from post text."""

        terms: list[str] = []
        seen_terms: set[str] = set()
        for match in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{3,}", text):
            normalized_term = match.lower()
            if normalized_term in self._stopwords or normalized_term in seen_terms:
                continue
            seen_terms.add(normalized_term)
            terms.append(match)
            if len(terms) == 5:
                break
        return terms

    def _extract_numeric_reference(self, text: str) -> str:
        """Return a short numeric detail when the source post includes one."""

        match = re.search(r"\b\d+(?:%|\+|x)?\b", text)
        if match is None:
            return ""
        return f", especially around the {match.group(0)} signal"

    def _normalize_text(self, text: str) -> str:
        """Normalize comment text for deduplication checks."""

        return " ".join(text.lower().split())

    def _excerpt(self, post_text: str, max_length: int = 60) -> str:
        """Build a short excerpt from the source post."""

        compact_text = " ".join(post_text.split())
        if len(compact_text) <= max_length:
            return compact_text
        return f"{compact_text[: max_length - 3].rstrip()}..."

    def _safe_confidence(self, value: Any) -> float:
        """Normalize confidence values into the range ``0..1``."""

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5

        return round(max(0.0, min(1.0, confidence)), 4)
