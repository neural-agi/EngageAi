"""Execution strategy objects for real and mock pipeline runs."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.agents.analyst_agent import AnalystAgent
from app.agents.critic_agent import CriticAgent
from app.agents.executor_agent import ExecutorAgent
from app.agents.writer_agent import WriterAgent
from app.core.memory_store import MemoryStore
from app.core.persona_engine import PersonaEngine
from app.orchestrator.pipeline import EngagementPipeline
from app.services.analytics.analytics_service import AnalyticsService
from app.services.ai.provider import AIProvider
from app.services.scraping.linkedin_scraper import LinkedInScraper
from app.services.security.session_manager import SessionManager


logger = logging.getLogger(__name__)


class RealPipelineRunner:
    """Build and execute the production dependency graph."""

    mode = "real"

    async def run(
        self,
        account_id: str,
        niche_text: str,
        persona_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute the real pipeline with isolated per-request objects."""

        logger.info(
            "Executing pipeline runner",
            extra={"mode": self.mode, "account_id": account_id},
        )
        pipeline = self._build_pipeline(account_id)

        try:
            results = await pipeline.run(
                account_id=account_id,
                niche_text=niche_text,
                persona_name=persona_name,
            )
        except Exception:
            logger.exception(
                "Real pipeline execution failed",
                extra={"mode": self.mode, "account_id": account_id},
            )
            raise

        logger.info(
            "Pipeline runner completed",
            extra={
                "mode": self.mode,
                "account_id": account_id,
                "result_count": len(results),
            },
        )
        return results

    def _build_pipeline(self, account_id: str) -> EngagementPipeline:
        """Construct a fresh real-mode dependency graph."""

        memory_store = MemoryStore(account_id=account_id)
        return EngagementPipeline(
            session_manager=SessionManager(),
            analytics=AnalyticsService(),
            memory_store=memory_store,
            persona_engine=PersonaEngine(memory_store=memory_store),
            analyst=AnalystAgent(),
            writer=WriterAgent(memory_store=memory_store),
            critic=CriticAgent(),
            executor=ExecutorAgent(memory_store=memory_store),
            scraper_factory=LinkedInScraper,
        )


class MockPipelineRunner:
    """Build and execute an isolated mock dependency graph."""

    mode = "mock"

    async def run(
        self,
        account_id: str,
        niche_text: str,
        persona_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute the mock pipeline without mutating shared runtime classes."""

        logger.info(
            "Executing pipeline runner",
            extra={"mode": self.mode, "account_id": account_id},
        )
        mock_scope_account_id = self._build_mock_scope_account_id(account_id)
        memory_store = MemoryStore(account_id=mock_scope_account_id)
        pipeline = self._build_pipeline(
            memory_store=memory_store,
            niche_text=niche_text,
        )

        try:
            results = await pipeline.run(
                account_id=account_id,
                niche_text=niche_text,
                persona_name=persona_name,
            )
        except Exception:
            logger.exception(
                "Mock pipeline execution failed",
                extra={"mode": self.mode, "account_id": account_id},
            )
            raise
        finally:
            try:
                memory_store.delete_account_state()
            except Exception:
                logger.warning(
                    "Failed to clean up mock pipeline state",
                    extra={"mode": self.mode, "account_id": account_id},
                )

        logger.info(
            "Pipeline runner completed",
            extra={
                "mode": self.mode,
                "account_id": account_id,
                "result_count": len(results),
            },
        )
        return results

    def _build_pipeline(
        self,
        memory_store: MemoryStore,
        niche_text: str,
    ) -> EngagementPipeline:
        """Construct a fresh mock-mode dependency graph."""

        mock_posts = self._build_mock_posts(niche_text)

        def scraper_factory(*, session_cookies: list[dict[str, Any]]) -> MockLinkedInScraper:
            return MockLinkedInScraper(
                session_cookies=session_cookies,
                mock_posts=mock_posts,
            )

        return EngagementPipeline(
            session_manager=MockSessionManager(),
            analytics=AnalyticsService(),
            memory_store=memory_store,
            persona_engine=PersonaEngine(memory_store=memory_store),
            analyst=MockAnalystAgent(),
            writer=WriterAgent(
                provider=AIProvider(disabled=True),
                memory_store=memory_store,
            ),
            critic=CriticAgent(),
            executor=ExecutorAgent(memory_store=memory_store),
            scraper_factory=scraper_factory,
        )

    def _build_mock_scope_account_id(self, account_id: str) -> str:
        """Return a unique account scope for one mock run."""

        return f"mock::{account_id}::{uuid.uuid4().hex}"

    def _build_mock_posts(self, niche_text: str) -> list[dict[str, Any]]:
        """Build a fixed set of sample posts for isolated mock runs."""

        topic = niche_text.strip() or "AI automation"

        strong_posts = [
            f"Deep dive into {topic} workflows for scaling SaaS businesses.",
            f"How {topic} is transforming modern sales pipelines.",
            f"Real-world {topic} strategies that actually increase revenue.",
            f"Why {topic} is the future of business operations.",
            f"Case study: implementing {topic} to reduce manual work by 80%.",
        ]
        mildly_relevant_posts = [
            f"Three practical lessons from piloting {topic} inside a growing operations team.",
            f"What early-stage founders get wrong about adopting {topic}.",
            f"A simple framework for evaluating {topic} tools before rollout.",
            f"How teams can introduce {topic} without disrupting existing processes.",
            f"When {topic} creates value and when it just adds noise.",
            f"Balancing human judgment with {topic} in customer-facing workflows.",
            f"Why implementation discipline matters more than hype in {topic} initiatives.",
            f"Metrics to watch after your first quarter using {topic}.",
        ]
        irrelevant_posts = [
            "Morning routine habits that improve long-term productivity.",
            "What strong leadership looks like during uncertain markets.",
            "How managers can give better feedback in one-on-ones.",
            "Five lessons from building resilient remote teams.",
            "Why clear communication beats endless meetings.",
            "Hiring principles that help teams move faster.",
            "The role of focus time in executive performance.",
            "Simple delegation habits for first-time team leads.",
            "How to structure a weekly planning ritual that sticks.",
            "What I learned from coaching founders through burnout.",
        ]

        posts: list[dict[str, Any]] = []
        post_index = 1

        for content in strong_posts:
            posts.append(
                {
                    "platform_post_id": f"mock-post-{post_index}",
                    "author": f"Mock Author {post_index}",
                    "content": content,
                    "likes": 90 + (post_index * 7),
                    "comments": 18 + (post_index % 5),
                    "hours_since_post": 1,
                    "url": f"https://example.com/mock-post-{post_index}",
                }
            )
            post_index += 1

        for content in mildly_relevant_posts:
            posts.append(
                {
                    "platform_post_id": f"mock-post-{post_index}",
                    "author": f"Mock Author {post_index}",
                    "content": content,
                    "likes": 25 + (post_index * 2),
                    "comments": 6 + (post_index % 4),
                    "hours_since_post": 2 + (post_index % 3),
                    "url": f"https://example.com/mock-post-{post_index}",
                }
            )
            post_index += 1

        for content in irrelevant_posts:
            posts.append(
                {
                    "platform_post_id": f"mock-post-{post_index}",
                    "author": f"Mock Author {post_index}",
                    "content": content,
                    "likes": 8 + post_index,
                    "comments": post_index % 3,
                    "hours_since_post": 4 + (post_index % 4),
                    "url": f"https://example.com/mock-post-{post_index}",
                }
            )
            post_index += 1

        return posts


class MockSessionManager:
    """Return fixed mock cookies for isolated pipeline runs."""

    async def get_session(self, account_id: str) -> list[dict[str, str]]:
        """Return a deterministic mock cookie payload."""

        _ = account_id
        return [{"name": "session", "value": "mock"}]


class MockLinkedInScraper:
    """Return predefined posts instead of calling the real scraper."""

    def __init__(
        self,
        session_cookies: list[dict[str, Any]],
        mock_posts: list[dict[str, Any]],
    ) -> None:
        """Store mock cookies and post fixtures for one run."""

        self.session_cookies = session_cookies
        self.mock_posts = list(mock_posts)

    async def fetch_feed(self) -> list[dict[str, Any]]:
        """Return the configured mock post set."""

        return list(self.mock_posts)


class MockAnalystAgent:
    """Always return an engage decision for local end-to-end testing."""

    async def analyze(
        self,
        post_text: str,
        niche_text: str,
        engagement_metrics: dict[str, Any],
    ) -> dict[str, float | str]:
        """Return a deterministic engage decision."""

        _ = post_text
        _ = niche_text
        _ = engagement_metrics
        return {
            "relevance_score": 0.9,
            "engagement_score": 0.8,
            "final_score": 0.85,
            "decision": "engage",
        }
