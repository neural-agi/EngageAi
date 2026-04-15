"""LinkedIn scraping helpers built on Playwright."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from contextlib import asynccontextmanager
from typing import Any

try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Error as PlaywrightError,
        Locator,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        async_playwright,
    )
except ImportError:  # pragma: no cover - runtime dependency
    Browser = BrowserContext = Locator = Page = Playwright = Any
    PlaywrightError = Exception
    PlaywrightTimeoutError = TimeoutError
    async_playwright = None


logger = logging.getLogger(__name__)


class LinkedInScraper:
    """Scrape LinkedIn feed content and interact with posts."""

    def __init__(
        self,
        session_cookies: list[dict[str, Any]],
        proxy: str | None = None,
        selectors: dict[str, str] | None = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        """Initialize scraper settings and browser context options."""

        self.session_cookies = session_cookies
        self.proxy = proxy
        self.selectors = {**self._default_selectors(), **(selectors or {})}
        self.headless = headless
        self.timeout_ms = timeout_ms

        # TODO: load selectors from application configuration instead of passing them inline.

    async def fetch_feed(self, max_posts: int = 20) -> list[dict[str, Any]]:
        """
        Fetch posts from LinkedIn feed.

        Returns:
            List of posts:
            {
                author,
                content,
                likes,
                comments,
                url,
                platform_post_id
            }
        """

        required_selectors = (
            "feed_post",
            "post_author",
            "post_content",
            "post_likes",
            "post_comments",
            "post_link",
        )
        if async_playwright is None:
            logger.warning(
                "Playwright unavailable for real scraping. Install it with 'pip install playwright' and 'playwright install'."
            )
            raise RuntimeError("Playwright is not installed for real scraping.")

        if not self._has_required_selectors(required_selectors):
            logger.warning("LinkedIn selectors are missing for real scraping")
            raise RuntimeError("LinkedIn scraper selectors are not configured.")

        logger.info("Fetching LinkedIn feed posts", extra={"max_posts": max_posts})
        try:
            async with self._browser_session() as page:
                await self._open_page(page, "https://www.linkedin.com/feed/")
                posts = await self._collect_posts(
                    page=page,
                    post_selector=self.selectors["feed_post"],
                    max_posts=max_posts,
                )
                logger.info(
                    "Posts fetched: %s",
                    len(posts),
                    extra={"count": len(posts), "source": "real"},
                )
                return posts
        except Exception as exc:
            logger.exception(
                "Failed to fetch LinkedIn feed",
                extra={"error": str(exc), "source": "real"},
            )
            raise

    async def fetch_placeholder_real_data(self, max_posts: int = 20) -> list[dict[str, Any]]:
        """Return structured placeholder posts until real selectors are fully configured."""

        logger.info("Using placeholder real feed data", extra={"max_posts": max_posts, "source": "placeholder"})

        placeholder_posts = [
            {
                "platform_post_id": "real-placeholder-1",
                "author": "Avery Patel",
                "content": "How AI automation is changing pipeline operations for revenue teams.",
                "likes": 84,
                "comments": 19,
                "hours_since_post": 2,
                "url": "https://www.linkedin.com/posts/real-placeholder-1",
            },
            {
                "platform_post_id": "real-placeholder-2",
                "author": "Morgan Lee",
                "content": "A field note on scaling outbound systems without adding manual busywork.",
                "likes": 42,
                "comments": 8,
                "hours_since_post": 3,
                "url": "https://www.linkedin.com/posts/real-placeholder-2",
            },
            {
                "platform_post_id": "real-placeholder-3",
                "author": "Jordan Kim",
                "content": "Why workflow design matters more than tool count in modern GTM teams.",
                "likes": 36,
                "comments": 6,
                "hours_since_post": 4,
                "url": "https://www.linkedin.com/posts/real-placeholder-3",
            },
            {
                "platform_post_id": "real-placeholder-4",
                "author": "Sam Rivera",
                "content": "Leadership lesson: clear operating cadences reduce execution drag.",
                "likes": 18,
                "comments": 3,
                "hours_since_post": 5,
                "url": "https://www.linkedin.com/posts/real-placeholder-4",
            },
            {
                "platform_post_id": "real-placeholder-5",
                "author": "Taylor Brooks",
                "content": "Case study: replacing repetitive CRM tasks with AI automation cut admin time by 60%.",
                "likes": 91,
                "comments": 22,
                "hours_since_post": 1,
                "url": "https://www.linkedin.com/posts/real-placeholder-5",
            },
            {
                "platform_post_id": "real-placeholder-6",
                "author": "Riley Chen",
                "content": "Simple productivity habits that help managers protect deep work blocks.",
                "likes": 14,
                "comments": 2,
                "hours_since_post": 6,
                "url": "https://www.linkedin.com/posts/real-placeholder-6",
            },
        ]

        selected_posts = placeholder_posts[:max_posts]
        logger.info(
            "Posts fetched: %s",
            len(selected_posts),
            extra={"count": len(selected_posts), "source": "placeholder"},
        )
        return selected_posts

    async def fetch_creator_posts(
        self,
        profile_url: str,
        max_posts: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch posts from a specific creator profile."""

        required_selectors = (
            "creator_post",
            "post_author",
            "post_content",
            "post_likes",
            "post_comments",
            "post_link",
        )
        if not profile_url.strip() or not self._has_required_selectors(required_selectors):
            return []

        logger.info("Fetching creator posts", extra={"profile_url": profile_url, "max_posts": max_posts})
        try:
            async with self._browser_session() as page:
                await self._open_page(page, profile_url.strip())

                creator_posts_tab = self.selectors.get("creator_posts_tab")
                if creator_posts_tab:
                    await self._safe_click(page.locator(creator_posts_tab).first)
                    await self._human_delay()

                posts = await self._collect_posts(
                    page=page,
                    post_selector=self.selectors["creator_post"],
                    max_posts=max_posts,
                )
                logger.info("Fetched creator posts", extra={"count": len(posts)})
                return posts
        except Exception:
            logger.exception("Failed to fetch creator posts", extra={"profile_url": profile_url})
            return []

    async def post_comment(self, post_url: str, comment_text: str) -> bool:
        """Post a comment on a LinkedIn post."""

        required_selectors = ("comment_button", "comment_input", "comment_submit")
        normalized_post_url = post_url.strip()
        normalized_comment_text = comment_text.strip()
        if (
            not normalized_post_url
            or not normalized_comment_text
            or not self._has_required_selectors(required_selectors)
        ):
            return False

        logger.info("Posting LinkedIn comment", extra={"post_url": normalized_post_url})
        try:
            async with self._browser_session() as page:
                await self._open_page(page, normalized_post_url)
                await self._safe_click(page.locator(self.selectors["comment_button"]).first)
                await self._human_delay(0.8, 1.5)

                comment_input = page.locator(self.selectors["comment_input"]).first
                await comment_input.click()
                await self._type_like_human(comment_input, normalized_comment_text)
                await self._human_delay(0.7, 1.4)

                await self._safe_click(page.locator(self.selectors["comment_submit"]).first)
                await self._human_delay(1.0, 1.8)

                logger.info("LinkedIn comment posted")
                return True
        except Exception:
            logger.exception("Failed to post LinkedIn comment", extra={"post_url": normalized_post_url})
            return False

    @asynccontextmanager
    async def _browser_session(self):
        """Create and clean up a Playwright browser session."""

        if async_playwright is None:
            raise RuntimeError("Playwright is not installed")

        playwright_context = async_playwright()
        browser: Browser | None = None
        context: BrowserContext | None = None

        try:
            async with playwright_context as playwright:
                browser = await self._launch_browser(playwright)
                context = await self._create_context(browser)
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                yield page
        finally:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()

    async def _launch_browser(self, playwright: Playwright) -> Browser:
        """Launch a Chromium browser instance."""

        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}

        return await playwright.chromium.launch(**launch_kwargs)

    async def _create_context(self, browser: Browser) -> BrowserContext:
        """Create a browser context and apply session cookies."""

        context = await browser.new_context()
        if self.session_cookies:
            try:
                await context.add_cookies(self.session_cookies)
            except PlaywrightError:
                logger.exception("Failed to apply LinkedIn session cookies")
                raise
        return context

    async def _open_page(self, page: Page, url: str) -> None:
        """Open a page and wait for it to settle."""

        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            await self._human_delay()
        except PlaywrightTimeoutError:
            logger.warning("Timeout while opening page", extra={"url": url})
            raise
        except PlaywrightError:
            logger.exception("Playwright error while opening page", extra={"url": url})
            raise

    async def _collect_posts(
        self,
        page: Page,
        post_selector: str,
        max_posts: int,
    ) -> list[dict[str, Any]]:
        """Collect post data from the active page."""

        collected_posts: list[dict[str, Any]] = []
        seen_post_ids: set[str] = set()
        stagnant_rounds = 0

        while len(collected_posts) < max_posts and stagnant_rounds < 3:
            post_locator = page.locator(post_selector)
            post_count = await post_locator.count()
            before_count = len(collected_posts)

            for index in range(post_count):
                post = await self._extract_post(post_locator.nth(index))
                if not post:
                    continue

                post_id = str(post.get("platform_post_id") or post.get("url") or index)
                if post_id in seen_post_ids:
                    continue

                seen_post_ids.add(post_id)
                collected_posts.append(post)
                if len(collected_posts) >= max_posts:
                    break

            if len(collected_posts) == before_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            if len(collected_posts) < max_posts:
                await page.mouse.wheel(0, random.randint(900, 1600))
                await self._human_delay(1.2, 2.1)

        return collected_posts[:max_posts]

    async def _extract_post(self, post_locator: Locator) -> dict[str, Any] | None:
        """Extract a structured post payload from a post container."""

        try:
            author = await self._safe_text(post_locator, self.selectors["post_author"])
            content = await self._safe_text(post_locator, self.selectors["post_content"])
            likes_text = await self._safe_text(post_locator, self.selectors["post_likes"])
            comments_text = await self._safe_text(post_locator, self.selectors["post_comments"])
            url = await self._safe_attribute(post_locator, self.selectors["post_link"], "href")

            if not author and not content:
                return None

            return {
                "author": author,
                "content": content,
                "likes": self._parse_metric(likes_text),
                "comments": self._parse_metric(comments_text),
                "hours_since_post": 1,
                "url": url,
                "platform_post_id": self._extract_post_id(url),
            }
        except Exception:
            logger.exception("Failed to extract LinkedIn post")
            return None

    async def _safe_text(self, locator: Locator, selector: str) -> str:
        """Return text content for a nested locator safely."""

        try:
            child = locator.locator(selector).first
            text = await child.text_content(timeout=self.timeout_ms)
            return (text or "").strip()
        except PlaywrightTimeoutError:
            logger.debug("Timeout reading text for selector", extra={"selector": selector})
            return ""
        except PlaywrightError:
            logger.debug("Playwright error reading text for selector", extra={"selector": selector})
            return ""

    async def _safe_attribute(self, locator: Locator, selector: str, attribute: str) -> str:
        """Return an attribute value for a nested locator safely."""

        try:
            child = locator.locator(selector).first
            value = await child.get_attribute(attribute, timeout=self.timeout_ms)
            return (value or "").strip()
        except PlaywrightTimeoutError:
            logger.debug(
                "Timeout reading attribute for selector",
                extra={"selector": selector, "attribute": attribute},
            )
            return ""
        except PlaywrightError:
            logger.debug(
                "Playwright error reading attribute for selector",
                extra={"selector": selector, "attribute": attribute},
            )
            return ""

    async def _safe_click(self, locator: Locator) -> None:
        """Click a locator with basic safety logging."""

        try:
            await locator.click(timeout=self.timeout_ms)
        except PlaywrightTimeoutError:
            logger.warning("Timeout while clicking LinkedIn element")
            raise
        except PlaywrightError:
            logger.exception("Playwright error while clicking LinkedIn element")
            raise

    async def _type_like_human(self, locator: Locator, text: str) -> None:
        """Type text with a small random delay to mimic human input."""

        await locator.fill("")
        await locator.type(text, delay=random.randint(45, 110))

    async def _human_delay(self, minimum: float = 0.6, maximum: float = 1.4) -> None:
        """Sleep for a randomized interval to avoid robotic interaction timing."""

        await asyncio.sleep(random.uniform(minimum, maximum))

    def _default_selectors(self) -> dict[str, str]:
        """Return a best-effort selector map for current LinkedIn layouts."""

        return {
            "feed_post": "div.feed-shared-update-v2, article[data-id]",
            "creator_post": "div.feed-shared-update-v2, article[data-id]",
            "post_author": (
                ".update-components-actor__title span[dir='ltr'], "
                ".update-components-actor__name span[dir='ltr'], "
                "span.update-components-actor__name"
            ),
            "post_content": (
                ".update-components-text span[dir='ltr'], "
                ".feed-shared-inline-show-more-text span[dir='ltr'], "
                ".break-words span[dir='ltr']"
            ),
            "post_likes": (
                "button[aria-label*='reaction'], "
                "button[aria-label*='like'], "
                ".social-details-social-counts__reactions-count"
            ),
            "post_comments": (
                "button[aria-label*='comment'], "
                ".social-details-social-counts__comments"
            ),
            "post_link": "a.app-aware-link[href*='/posts/'], a[href*='/feed/update/']",
            "creator_posts_tab": "a[href*='recent-activity/shares'], a[href*='recent-activity/all/']",
            "comment_button": "button[aria-label*='Comment'], button[aria-label*='comment']",
            "comment_input": "div[role='textbox'][contenteditable='true']",
            "comment_submit": "button.comments-comment-box__submit-button--cr, button[aria-label='Post comment']",
        }

    def _has_required_selectors(self, keys: tuple[str, ...]) -> bool:
        """Check that all required selector keys are configured."""

        missing_keys = [key for key in keys if not self.selectors.get(key)]
        if missing_keys:
            logger.error(
                "Missing LinkedIn scraper selectors",
                extra={"missing_keys": missing_keys},
            )
            return False
        return True

    def _parse_metric(self, value: str) -> int:
        """Convert a metric string into an integer count."""

        normalized_value = value.strip().upper().replace(",", "")
        if not normalized_value:
            return 0

        match = re.search(r"(\d+(?:\.\d+)?)\s*([KM]?)", normalized_value)
        if match is None:
            return 0

        amount = float(match.group(1))
        suffix = match.group(2)
        multiplier = {"K": 1_000, "M": 1_000_000}.get(suffix, 1)
        return int(amount * multiplier)

    def _extract_post_id(self, url: str) -> str:
        """Derive a lightweight platform post identifier from a post URL."""

        normalized_url = url.strip()
        if not normalized_url:
            return ""

        match = re.search(r"/posts/([^/?#]+)", normalized_url)
        if match is not None:
            return match.group(1)
        return normalized_url
