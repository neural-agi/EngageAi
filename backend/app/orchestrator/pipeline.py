"""Pipeline orchestration for engagement generation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List

from app.agents.analyst_agent import AnalystAgent
from app.agents.critic_agent import CriticAgent
from app.agents.executor_agent import ExecutorAgent
from app.agents.writer_agent import WriterAgent
from app.core.memory_store import MemoryStore
from app.core.persona_engine import PersonaEngine
from app.services.analytics.analytics_service import AnalyticsService
from app.services.scraping.linkedin_scraper import LinkedInScraper
from app.services.security.session_manager import SessionManager


logger = logging.getLogger(__name__)


class EngagementPipeline:
    """Coordinate scraping, analysis, writing, and critique steps."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        analytics: AnalyticsService | None = None,
        memory_store: MemoryStore | None = None,
        persona_engine: PersonaEngine | None = None,
        analyst: AnalystAgent | None = None,
        writer: WriterAgent | None = None,
        critic: CriticAgent | None = None,
        executor: ExecutorAgent | None = None,
        scraper_factory: Callable[..., Any] | None = None,
    ) -> None:
        """Initialize pipeline dependencies with optional per-run overrides."""

        self.memory_store = memory_store or MemoryStore()
        self.session_manager = session_manager or SessionManager()
        self.analytics = analytics or AnalyticsService()
        self.persona_engine = persona_engine or PersonaEngine(memory_store=self.memory_store)
        self.analyst = analyst or AnalystAgent()
        self.writer = writer or WriterAgent(memory_store=self.memory_store)
        self.critic = critic or CriticAgent()
        self.executor = executor or ExecutorAgent(memory_store=self.memory_store)
        self.scraper_factory = scraper_factory or LinkedInScraper

    async def run(
        self,
        account_id: str,
        niche_text: str,
        persona_name: str | None = None,
    ) -> List[Dict]:
        """
        Full pipeline execution:
        1. Load session
        2. Fetch posts
        3. Analyze relevance
        4. Generate comments
        5. Filter + rank comments
        """

        logger.info(
            "Starting engagement pipeline",
            extra={"account_id": account_id, "niche_text": niche_text},
        )
        if hasattr(self.memory_store, "account_id") and not getattr(self.memory_store, "account_id", None):
            self.memory_store.set_account_id(account_id)
            if (
                hasattr(self.writer, "memory_store")
                and getattr(self.writer, "memory_store", None) is self.memory_store
                and hasattr(self.writer, "_historical_comment_texts")
            ):
                self.writer._historical_comment_texts = self.memory_store.get_generated_comments()
        if hasattr(self.executor, "start_run"):
            self.executor.start_run()

        selected_persona = self.persona_engine.select_persona(persona_name)
        run_style_usage: dict[str, int] = {}
        logger.info(
            "Selected pipeline persona",
            extra={
                "account_id": account_id,
                "persona_id": selected_persona["id"],
                "persona_name": selected_persona["name"],
                "persona_archetype": selected_persona["archetype"],
            },
        )

        try:
            logger.info("Loading session cookies", extra={"account_id": account_id})
            cookies = await self.session_manager.get_session(account_id)
        except Exception:
            logger.exception("Failed to load account session", extra={"account_id": account_id})
            return []

        if not cookies:
            logger.warning("No session cookies found for account", extra={"account_id": account_id})

        scraper = self.scraper_factory(session_cookies=cookies)

        try:
            logger.info("Fetching feed posts", extra={"account_id": account_id})
            posts = await scraper.fetch_feed()
        except Exception:
            logger.exception("Failed to fetch feed posts", extra={"account_id": account_id})
            return []

        if not isinstance(posts, list) or not posts:
            logger.info("No posts available for pipeline processing", extra={"account_id": account_id})
            return []

        logger.info("Posts fetched: %s", len(posts), extra={"account_id": account_id, "count": len(posts)})
        results: list[dict[str, Any]] = []
        posts_after_filtering = 0

        for index, post in enumerate(posts, start=1):
            if not isinstance(post, dict):
                logger.warning("Skipping invalid post payload", extra={"post_index": index})
                continue

            post_text = self._extract_post_text(post)
            if not post_text:
                logger.info("Skipping post with empty content", extra={"post_index": index})
                continue

            try:
                logger.info("Computing analytics for post", extra={"post_index": index})
                viral_score = self.analytics.compute_viral_score(post)

                logger.info("Analyzing post relevance", extra={"post_index": index})
                analysis = await self.analyst.analyze(
                    post_text=post_text,
                    niche_text=niche_text,
                    engagement_metrics=self._build_engagement_metrics(post),
                )

                if analysis.get("decision") != "engage":
                    logger.info(
                        "Post ignored by analyst",
                        extra={"post_index": index, "analysis": analysis},
                    )
                    continue
                posts_after_filtering += 1

                logger.info("Generating comment variants", extra={"post_index": index})
                variants = await self.writer.draft(
                    post_text=post_text,
                    context=self._build_writer_context(
                        post,
                        niche_text,
                        viral_score,
                        persona=selected_persona,
                        style_usage=self._combine_style_usage(run_style_usage),
                    ),
                )
                if not variants:
                    logger.info("No comment variants generated", extra={"post_index": index})
                    continue

                logger.info("Reviewing generated variants", extra={"post_index": index})
                review = await self.critic.review(variants)
                best_variant = review.get("best_variant")
                ranked_variants = review.get("ranked_variants", [])

                if not best_variant:
                    logger.info("No approved variants after review", extra={"post_index": index})
                    continue

                self._record_style_selection(best_variant, run_style_usage)
                logger.info("Executing best variant", extra={"post_index": index})
                execution_result = await self.executor.execute(
                    post_id=str(post.get("platform_post_id", "")),
                    comment={
                        **best_variant,
                        "persona": selected_persona,
                    },
                )
                logger.info(
                    "Execution step completed",
                    extra={
                        "post_index": index,
                        "execution_status": execution_result.get("status"),
                    },
                )

                results.append(
                    {
                        "post": post,
                        "analysis": analysis,
                        "analytics": {
                            "viral_score": viral_score,
                        },
                        "best_comment": best_variant,
                        "ranked_comments": ranked_variants,
                        "execution": execution_result,
                    }
                )
                logger.info("Post processed successfully", extra={"post_index": index})
            except Exception:
                logger.exception("Failed to process post", extra={"post_index": index})
                continue

        logger.info(
            "Posts after filtering: %s",
            posts_after_filtering,
            extra={"account_id": account_id, "count": posts_after_filtering},
        )
        logger.info(
            "Engagement pipeline completed",
            extra={"account_id": account_id, "processed_results": len(results)},
        )
        return results

    def _extract_post_text(self, post: dict[str, Any]) -> str:
        """Extract normalized text content from a scraped post payload."""

        return str(post.get("content", "")).strip()

    def _build_engagement_metrics(self, post: dict[str, Any]) -> dict[str, Any]:
        """Build the engagement metrics payload expected by the analyst."""

        return {
            "likes": post.get("likes", 0),
            "comments": post.get("comments", 0),
            "time": post.get("hours_since_post", 1),
        }

    def _build_writer_context(
        self,
        post: dict[str, Any],
        niche_text: str,
        viral_score: float,
        persona: dict[str, Any],
        style_usage: dict[str, int],
    ) -> dict[str, Any]:
        """Build lightweight writer context from pipeline metadata."""

        return {
            "topic": niche_text,
            "author": post.get("author"),
            "url": post.get("url"),
            "viral_score": viral_score,
            "persona": persona,
            "persona_prompt": self.persona_engine.build_prompt(persona["id"], niche_text),
            "style_usage": style_usage,
        }

    def _combine_style_usage(self, run_style_usage: dict[str, int]) -> dict[str, int]:
        """Merge historical style usage with the current run counters."""

        combined_usage = dict(self.memory_store.get_style_usage())
        for style, count in run_style_usage.items():
            combined_usage[style] = combined_usage.get(style, 0) + count
        return combined_usage

    def _record_style_selection(
        self,
        best_variant: dict[str, Any],
        run_style_usage: dict[str, int],
    ) -> None:
        """Track the selected style in memory for rotation across posts and runs."""

        style = str(best_variant.get("style", "")).strip()
        if not style:
            return

        run_style_usage[style] = run_style_usage.get(style, 0) + 1
        self.memory_store.increment_style_usage(style)
