"""Intent router for Master Agent.

Detects video URLs and classifies user intent.
"""

import logging
import re
from typing import TypedDict

from src.agents.master.models import IntentResult

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:instagram\.com/(?:p|reel|reels|tv)/|tiktok\.com/@.*?/video/|youtube\.com/shorts/)([^\s\)]+)',
    re.IGNORECASE
)

BATCH_KEYWORDS = ["批量", "多个", "batch", "multiple", "一系列", "一群"]
CANCEL_KEYWORDS = ["取消", "cancel", "stop", "终止", "中止"]
STATUS_KEYWORDS = ["进度", "状态", "status", "情况", "怎样", "如何"]
LIST_KEYWORDS = ["项目", "案例", "列表", "list", "projects", "cases"]
SETTINGS_KEYWORDS = ["配置", "设置", "settings", "api", "key"]
PUSH_KEYWORDS = ["推送", "发布", "contentful", "cms", "push", "publish"]
MEMORY_KEYWORDS = ["记忆", "之前", "做过", "memory", "remember", "search", "查找"]


class IntentRouter:
    """Routes user input to appropriate intent handlers."""

    def __init__(self):
        self.max_batch_size = 10

    def extract_urls(self, text: str) -> list[str]:
        """Extract video URLs from text using regex."""
        matches = URL_PATTERN.findall(text)
        full_urls = []
        text_lower = text.lower()

        for match in matches:
            video_id = match.rstrip('/')
            if not video_id:
                continue

            if "instagram.com" in text_lower:
                if "/reels/" in text_lower or "/reel/" in text_lower:
                    full_urls.append(f"https://www.instagram.com/reels/{video_id}")
                elif "/p/" in text_lower:
                    full_urls.append(f"https://www.instagram.com/p/{video_id}")
                elif "/tv/" in text_lower:
                    full_urls.append(f"https://www.instagram.com/tv/{video_id}")
            elif "tiktok.com" in text_lower:
                full_urls.append(f"https://www.tiktok.com/{match}" if not match.startswith("http") else match)
            elif "youtube.com" in text_lower or "youtu.be" in text_lower:
                full_urls.append(match if match.startswith("http") else f"https://youtu.be/{video_id}")

        return list(dict.fromkeys(full_urls))

    def extract_urls_with_llm(self, text: str) -> list[str]:
        """Use LLM to extract and validate video URLs from complex text."""
        from src.agents.master import get_llm_client

        llm = get_llm_client()
        if not llm.is_configured():
            return self.extract_urls(text)

        prompt = f"""Extract all video URLs from the following text. Return ONLY a JSON array of URLs, nothing else.

Supported platforms:
- Instagram: https://www.instagram.com/reels/XXX, https://www.instagram.com/p/XXX, https://www.instagram.com/reel/XXX
- TikTok: https://www.tiktok.com/@user/video/XXX
- YouTube: https://www.youtube.com/shorts/XXX, https://youtu.be/XXX

Text: {text}

Return format: ["url1", "url2", ...]
If no URLs found, return: []"""

        try:
            response = llm.generate(prompt)
            if response:
                import json
                # Try to parse as JSON
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                urls = json.loads(cleaned)
                if isinstance(urls, list):
                    return urls
        except Exception as e:
            logger.warning(f"LLM URL extraction failed: {e}")

        return self.extract_urls(text)

    def classify_intent(self, text: str) -> IntentResult:
        """Classify user intent from input text.

        Uses LLM to extract URLs for complex cases (batch with Chinese separators, etc).
        """
        text_lower = text.lower()

        # Quick keyword checks first (no LLM needed)
        if any(kw in text_lower for kw in PUSH_KEYWORDS):
            return IntentResult(intent="CONTENTFUL_PUSH", video_urls=[], is_batch=False, raw_query=text)
        if any(kw in text_lower for kw in MEMORY_KEYWORDS):
            return IntentResult(intent="MEMORY_QUERY", video_urls=[], is_batch=False, raw_query=text)
        if any(kw in text_lower for kw in SETTINGS_KEYWORDS):
            return IntentResult(intent="SETTINGS", video_urls=[], is_batch=False, raw_query=text)
        if any(kw in text_lower for kw in LIST_KEYWORDS):
            return IntentResult(intent="PROJECT_LIST", video_urls=[], is_batch=False, raw_query=text)
        if any(kw in text_lower for kw in STATUS_KEYWORDS):
            return IntentResult(intent="STATUS_QUERY", video_urls=[], is_batch=False, raw_query=text)
        if any(kw in text_lower for kw in CANCEL_KEYWORDS):
            return IntentResult(intent="CANCEL", video_urls=[], is_batch=False, raw_query=text)
        if "help" in text_lower or "帮助" in text_lower:
            return IntentResult(intent="HELP", video_urls=[], is_batch=False, raw_query=text)

        # Try LLM-based URL extraction first (handles complex cases)
        urls = self.extract_urls_with_llm(text)

        # Determine batch vs single
        is_batch = len(urls) > 1 or any(kw in text_lower for kw in BATCH_KEYWORDS)
        intent = "BATCH_SUBMIT" if is_batch else ("VIDEO_SUBMIT" if len(urls) == 1 else "unknown")

        return IntentResult(
            intent=intent,
            video_urls=urls,
            is_batch=is_batch,
            raw_query=text
        )

    def validate_batch(self, urls: list[str]) -> tuple[bool, str, list[str]]:
        """Validate batch request. Returns (valid, error_message, valid_urls)."""
        if not urls:
            return False, "未检测到视频URL", []

        if len(urls) > self.max_batch_size:
            return False, f"批量数量超过限制（最多{self.max_batch_size}个）", urls[:self.max_batch_size]

        return True, "", urls


# Global singleton
_intent_router: IntentRouter | None = None


def get_intent_router() -> IntentRouter:
    """Get the global intent router instance."""
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router