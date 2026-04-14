"""Tests for the engagement pipeline orchestration."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _ensure_pydantic_settings_stub() -> None:
    """Provide a minimal runtime stub when pydantic-settings is unavailable."""

    try:
        import pydantic_settings  # noqa: F401
        return
    except ImportError:
        pass

    stub_module = types.ModuleType("pydantic_settings")

    class BaseSettings:
        """Minimal BaseSettings stub for tests."""

        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def SettingsConfigDict(**kwargs: Any) -> dict[str, Any]:
        """Return a plain dictionary for config declarations."""

        return kwargs

    stub_module.BaseSettings = BaseSettings
    stub_module.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = stub_module


def _load_pipeline_module():
    """Import the pipeline module after preparing runtime stubs."""

    _ensure_pydantic_settings_stub()
    return importlib.import_module("app.orchestrator.pipeline")


class FakeSessionManager:
    """Return a fixed cookie payload for tests."""

    async def get_session(self, account_id: str) -> list[dict[str, str]]:
        return [{"name": "session", "value": account_id}]


class FakeScraper:
    """Return preconfigured mock posts."""

    def __init__(self, session_cookies: list[dict[str, str]]) -> None:
        self.session_cookies = session_cookies

    async def fetch_feed(self) -> list[dict[str, Any]]:
        return [
            {
                "platform_post_id": "post-empty",
                "content": "   ",
                "likes": 2,
                "comments": 0,
            },
            {
                "platform_post_id": "post-ignore",
                "content": "General productivity advice.",
                "likes": 4,
                "comments": 1,
            },
            {
                "platform_post_id": "post-engage",
                "content": "Strong post about AI sales workflows and automation.",
                "likes": 20,
                "comments": 8,
                "author": "Alex",
                "url": "https://example.com/post-engage",
                "hours_since_post": 2,
            },
        ]


class FakeAnalyticsService:
    """Provide deterministic analytics output."""

    def compute_viral_score(self, post: dict[str, Any]) -> float:
        return 0.81 if post.get("platform_post_id") == "post-engage" else 0.1


class FakeAnalystAgent:
    """Filter posts by a simple engage/ignore decision."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze(
        self,
        post_text: str,
        niche_text: str,
        engagement_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "post_text": post_text,
                "niche_text": niche_text,
                "engagement_metrics": engagement_metrics,
            }
        )
        if "AI sales" in post_text:
            return {
                "relevance_score": 0.9,
                "engagement_score": 0.7,
                "final_score": 0.84,
                "decision": "engage",
            }

        return {
            "relevance_score": 0.2,
            "engagement_score": 0.1,
            "final_score": 0.17,
            "decision": "ignore",
        }


class FakeWriterAgent:
    """Return deterministic comment variants."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def draft(
        self,
        post_text: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append({"post_text": post_text, "context": context or {}})
        return [
            {"text": "Analytical take.", "style": "analytical", "confidence": 0.72},
            {"text": "Could this work at scale?", "style": "question-based", "confidence": 0.8},
        ]


class FakeCriticAgent:
    """Return ranked variants with a single best option."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def review(self, comment_variants: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(comment_variants)
        ranked = [
            {
                "text": "Could this work at scale?",
                "style": "question-based",
                "confidence": 0.8,
                "score": 0.91,
            },
            {
                "text": "Analytical take.",
                "style": "analytical",
                "confidence": 0.72,
                "score": 0.76,
            },
        ]
        return {
            "best_variant": ranked[0],
            "ranked_variants": ranked,
        }


class FakeExecutorAgent:
    """Capture execution requests and return a simulation result."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, post_id: str, comment: dict[str, Any]) -> dict[str, str]:
        self.calls.append({"post_id": post_id, "comment": comment})
        return {
            "status": "success",
            "message": "Comment simulated successfully",
        }


def test_pipeline_run_filters_and_executes(monkeypatch) -> None:
    """Pipeline should filter posts, generate comments, rank them, and execute the best one."""

    pipeline_module = _load_pipeline_module()
    monkeypatch.setattr(pipeline_module, "LinkedInScraper", FakeScraper)

    pipeline = pipeline_module.EngagementPipeline()
    pipeline.session_manager = FakeSessionManager()
    pipeline.analytics = FakeAnalyticsService()
    pipeline.analyst = FakeAnalystAgent()
    pipeline.writer = FakeWriterAgent()
    pipeline.critic = FakeCriticAgent()
    pipeline.executor = FakeExecutorAgent()

    results = asyncio.run(pipeline.run(account_id="acct-1", niche_text="AI sales"))

    assert len(results) == 1
    result = results[0]

    assert result["post"]["platform_post_id"] == "post-engage"
    assert result["analysis"]["decision"] == "engage"
    assert result["best_comment"]["style"] == "question-based"
    assert result["ranked_comments"][0]["score"] >= result["ranked_comments"][1]["score"]
    assert result["execution"] == {
        "status": "success",
        "message": "Comment simulated successfully",
    }

    assert len(pipeline.analyst.calls) == 2
    assert len(pipeline.writer.calls) == 1
    assert len(pipeline.critic.calls) == 1
    assert len(pipeline.executor.calls) == 1
    assert pipeline.executor.calls[0]["post_id"] == "post-engage"


def test_pipeline_run_continues_when_one_post_fails(monkeypatch) -> None:
    """Pipeline should continue processing later posts when one post raises an error."""

    pipeline_module = _load_pipeline_module()
    monkeypatch.setattr(pipeline_module, "LinkedInScraper", FakeScraper)

    class FlakyWriterAgent(FakeWriterAgent):
        async def draft(
            self,
            post_text: str,
            context: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            if "General productivity" in post_text:
                raise RuntimeError("writer failure")
            return await super().draft(post_text=post_text, context=context)

    class EngageEverythingAnalyst(FakeAnalystAgent):
        async def analyze(
            self,
            post_text: str,
            niche_text: str,
            engagement_metrics: dict[str, Any],
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "post_text": post_text,
                    "niche_text": niche_text,
                    "engagement_metrics": engagement_metrics,
                }
            )
            return {
                "relevance_score": 0.8,
                "engagement_score": 0.6,
                "final_score": 0.74,
                "decision": "engage",
            }

    pipeline = pipeline_module.EngagementPipeline()
    pipeline.session_manager = FakeSessionManager()
    pipeline.analytics = FakeAnalyticsService()
    pipeline.analyst = EngageEverythingAnalyst()
    pipeline.writer = FlakyWriterAgent()
    pipeline.critic = FakeCriticAgent()
    pipeline.executor = FakeExecutorAgent()

    results = asyncio.run(pipeline.run(account_id="acct-2", niche_text="AI sales"))

    assert len(results) == 1
    assert results[0]["post"]["platform_post_id"] == "post-engage"
    assert results[0]["execution"]["status"] == "success"
