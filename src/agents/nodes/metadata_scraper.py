"""Metadata scraper node for Sparki SEO Blog Agent.

Extracts video and blogger metadata from TikTok and Instagram.
- TikTok: yt-dlp for video metadata + Playwright for profile (follower count)
- Instagram: yt-dlp for video metadata, profile URL derived from channel name

Input:
    MetadataScraperInput with video_url, task_id

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/metadata_result/{task_id}_meta.json
    {
        "success": bool,
        "metadata": {
            "platform": str,
            "video_id": str,
            "video_title": str,
            "video_description": str,
            "video_duration": float,
            "video_thumbnail_url": str,
            "published_at": str,
            "author_id": str,
            "author_name": str,
            "author_url": str,
            "author_avatar_url": str,
            "likes": int,
            "views": int,
            "saves": int,
            "shares": int,
            "comments": int,
            "followers": int,
            "following": int
        },
        "error": str | null,
        "task_id": str,
        "timestamp": str
    }
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import TypedDict

import yt_dlp

from src.storage.storage_paths import StoragePaths

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================


class MetadataScraperInput(TypedDict):
    """Input schema for metadata scraper node."""

    video_url: str
    task_id: str
    project_name: str = "default"
    output_base_dir: str = "data"


# =============================================================================
# Helper Functions
# =============================================================================


def _extract_video_metadata_ydl(info: dict, platform: str, original_url: str = "") -> dict:
    """Extract video metadata from yt-dlp info dict.

    Args:
        info: yt-dlp extract_info result
        platform: 'tiktok' or 'instagram'
        original_url: Original video URL provided by user

    Returns:
        Dict with video metadata fields
    """
    meta = {
        "video_id": info.get("id", ""),
        "video_title": info.get("title", ""),
        "video_description": info.get("description", ""),
        "video_duration": info.get("duration", 0.0) or 0.0,
        "video_thumbnail_url": info.get("thumbnail", ""),
        "video_url": original_url,  # Store original video URL
        "published_at": "",
        "author_id": "",
        "author_name": "",
        "author_url": "",
        "author_avatar_url": "",
        "likes": 0,
        "views": 0,
        "saves": 0,
        "shares": 0,
        "comments": 0,
        "followers": 0,
        "following": 0,
    }

    # Published date
    if info.get("upload_date"):
        meta["published_at"] = f"{info['upload_date'][:4]}-{info['upload_date'][4:6]}-{info['upload_date'][6:8]}"

    # Author info
    if platform == "tiktok":
        meta["author_id"] = info.get("uploader_id", "")
        meta["author_name"] = info.get("uploader", "")
        meta["author_url"] = info.get("uploader_url", "")
    elif platform == "instagram":
        channel = info.get("channel", "")
        meta["author_id"] = info.get("uploader_id", "")
        meta["author_name"] = channel
        if channel:
            meta["author_url"] = f"https://www.instagram.com/{channel}/"
        else:
            meta["author_url"] = ""

    # Engagement stats
    meta["likes"] = info.get("like_count", 0) or 0
    meta["views"] = info.get("view_count", 0) or 0
    meta["comments"] = info.get("comment_count", 0) or 0
    meta["saves"] = info.get("save_count", 0) or 0
    meta["shares"] = info.get("repost_count", 0) or 0

    return meta


def _detect_platform(url: str) -> str | None:
    """Detect platform from URL.

    Args:
        url: Video URL

    Returns:
        'tiktok', 'instagram', or None if unsupported
    """
    if "tiktok.com" in url:
        return "tiktok"
    elif "instagram.com" in url:
        return "instagram"
    return None


def _parse_tiktok_profile_url(video_url: str) -> str | None:
    """Extract profile URL from TikTok video URL.

    Args:
        video_url: e.g., https://www.tiktok.com/@urmom_sushi/video/123

    Returns:
        Profile URL e.g., https://www.tiktok.com/@urmom_sushi/
    """
    match = re.match(r"(https://www\.tiktok\.com/@[^/]+)/", video_url)
    if match:
        return match.group(1)
    return None


def _parse_follower_count(text: str) -> int:
    """Parse follower count string to integer.

    Args:
        text: e.g., "254.5K", "623K", "1,234"

    Returns:
        Integer count
    """
    import re
    text = text.strip().upper()
    # Remove non-numeric characters except k, m
    match = re.match(r'([\d,.]+)([KM])?', text)
    if not match:
        return 0
    num_str = match.group(1).replace(',', '')
    suffix = match.group(2)
    try:
        num = float(num_str)
        if suffix == 'K':
            num *= 1000
        elif suffix == 'M':
            num *= 1000000
        return int(num)
    except ValueError:
        return 0


def _scrape_tiktok_profile(profile_url: str) -> dict:
    """Scrape TikTok profile page for follower/following count.

    Args:
        profile_url: TikTok profile URL

    Returns:
        Dict with followers and following count
    """
    result = {
        "followers": 0,
        "following": 0,
        "author_avatar_url": "",
    }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                extra_http_headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            page = context.new_page()

            page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

            # TikTok follower count is in a <strong> element inside H3
            # XPath: /HTML[1]/BODY[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/H3[1]/DIV[2]/STRONG[1]
            try:
                follower_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/H3[1]/DIV[2]/STRONG[1]')
                if follower_el:
                    text = follower_el.inner_text()
                    result["followers"] = _parse_follower_count(text)
                    logger.info(f"TikTok follower count: {text} -> {result['followers']}")
            except Exception as e:
                logger.warning(f"Failed to get TikTok followers via xpath: {e}")

            # Following count is in H3 element (text is "105 Following")
            # XPath: /HTML[1]/BODY[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/H3[1]
            try:
                h3_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/H3[1]')
                if h3_el:
                    text = h3_el.inner_text()
                    # Parse "105 Following"
                    match = re.match(r'([\d,.]+)', text)
                    if match:
                        result["following"] = int(match.group(1).replace(',', ''))
                    logger.info(f"TikTok following count: {text} -> {result['following']}")
            except Exception as e:
                logger.warning(f"Failed to get TikTok following via xpath: {e}")

            # Avatar
            try:
                avatar_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[1]/DIV[2]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/DIV[1]/IMG[1]')
                if avatar_el:
                    result["author_avatar_url"] = avatar_el.get_attribute("src") or ""
            except Exception:
                pass

            browser.close()
            logger.info(f"Scraped TikTok profile: {profile_url}, followers={result['followers']}, following={result['following']}")

    except Exception as e:
        logger.warning(f"Failed to scrape TikTok profile {profile_url}: {e}")

    return result


def _scrape_instagram_profile(profile_url: str) -> dict:
    """Scrape Instagram profile page for follower/following count.

    Args:
        profile_url: Instagram profile URL

    Returns:
        Dict with followers and following count
    """
    result = {
        "followers": 0,
        "following": 0,
        "author_avatar_url": "",
    }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                extra_http_headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            page = context.new_page()

            page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Instagram has stats in header/ul/li
            # LI[2] has followers, LI[3] has following
            # Followers: /HTML[1]/BODY[1]/DIV[2]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[2]/SECTION[1]/MAIN[1]/DIV[1]/DIV[1]/HEADER[1]/SECTION[1]/DIV[3]/UL[1]/LI[2]
            try:
                followers_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[2]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[2]/SECTION[1]/MAIN[1]/DIV[1]/DIV[1]/HEADER[1]/SECTION[1]/DIV[3]/UL[1]/LI[2]')
                if followers_el:
                    text = followers_el.inner_text()
                    # Text is "623K followers"
                    result["followers"] = _parse_follower_count(text)
                    logger.info(f"Instagram follower count: {text} -> {result['followers']}")
            except Exception as e:
                logger.warning(f"Failed to get Instagram followers via xpath: {e}")

            # Following: /HTML[1]/BODY[1]/DIV[2]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[2]/SECTION[1]/MAIN[1]/DIV[1]/DIV[1]/HEADER[1]/SECTION[1]/DIV[3]/UL[1]/LI[3]
            try:
                following_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[2]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[2]/SECTION[1]/MAIN[1]/DIV[1]/DIV[1]/HEADER[1]/SECTION[1]/DIV[3]/UL[1]/LI[3]')
                if following_el:
                    text = following_el.inner_text()
                    # Text is "726 following"
                    result["following"] = _parse_follower_count(text)
                    logger.info(f"Instagram following count: {text} -> {result['following']}")
            except Exception as e:
                logger.warning(f"Failed to get Instagram following via xpath: {e}")

            # Avatar
            try:
                avatar_el = page.query_selector('xpath=/HTML[1]/BODY[1]/DIV[2]/DIV[1]/DIV[1]/DIV[2]/DIV[1]/DIV[1]/DIV[1]/DIV[2]/DIV[2]/SECTION[1]/MAIN[1]/DIV[1]/DIV[1]/HEADER[1]/SECTION[1]/DIV[1]/DIV[1]/DIV[1]/IMG[1]')
                if avatar_el:
                    result["author_avatar_url"] = avatar_el.get_attribute("src") or ""
            except Exception:
                pass

            browser.close()
            logger.info(f"Scraped Instagram profile: {profile_url}, followers={result['followers']}, following={result['following']}")

    except Exception as e:
        logger.warning(f"Failed to scrape Instagram profile {profile_url}: {e}")

    return result


def _save_result_json(result: dict, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save result as JSON file.

    Returns:
        Path to the JSON file
    """
    result_dir = StoragePaths.local_base(output_base_dir, project_name) / "metadata_result"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{task_id}_meta.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(result_path)


# =============================================================================
# Main Function
# =============================================================================


def scrape_metadata(input: MetadataScraperInput) -> str:
    """Scrape video and blogger metadata.

    Args:
        input: MetadataScraperInput with video_url, task_id, project_name, output_base_dir

    Returns:
        Path to JSON result file
    """
    video_url = input["video_url"]
    task_id = input["task_id"]
    project_name = input.get("project_name", "default")
    output_base_dir = input.get("output_base_dir", "data")

    logger.info(f"Starting metadata extraction: {video_url}")

    # Result template
    result = {
        "success": False,
        "metadata": None,
        "error": None,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Detect platform
    platform = _detect_platform(video_url)
    if not platform:
        result["error"] = "不支持的平台，仅支持 TikTok 和 Instagram"
        return _save_result_json(result, output_base_dir, project_name, task_id)

    try:
        # Extract video metadata via yt-dlp
        logger.info(f"Extracting video metadata via yt-dlp ({platform})")
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": False}) as ydl:
            info = ydl.extract_info(video_url, download=False)

        if not info:
            result["error"] = "无法获取视频信息，请检查URL是否有效"
            return _save_result_json(result, output_base_dir, project_name, task_id)

        # Build base metadata from yt-dlp
        metadata = _extract_video_metadata_ydl(info, platform, video_url)
        metadata["platform"] = platform

        # Scrape profile for additional data (followers, following, avatar)
        profile_url = metadata.get("author_url", "")
        if platform == "tiktok" and profile_url:
            logger.info(f"Scraping TikTok profile: {profile_url}")
            profile_data = _scrape_tiktok_profile(profile_url)
            metadata.update(profile_data)
        elif platform == "instagram" and profile_url:
            logger.info(f"Scraping Instagram profile: {profile_url}")
            profile_data = _scrape_instagram_profile(profile_url)
            metadata.update(profile_data)

        logger.info(f"Metadata extraction completed: video_id={metadata['video_id']}, author={metadata['author_name']}")

        result["success"] = True
        result["metadata"] = metadata
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except yt_dlp.utils.DownloadError as e:
        error_msg = f"获取元数据失败: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except Exception as e:
        error_msg = f"获取元数据时发生错误: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        return _save_result_json(result, output_base_dir, project_name, task_id)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uuid

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    test_cases = [
        {"name": "TikTok", "url": "https://www.tiktok.com/@urmom_sushi/video/7619575805584117014"},
        {"name": "Instagram", "url": "https://www.instagram.com/reels/DWwVuBJiukt/"},
    ]

    for test in test_cases:
        print(f"\n{'=' * 60}")
        print(f"Testing {test['name']}: {test['url']}")
        print("=" * 60)

        task_id = str(uuid.uuid4())[:8]
        result_path = scrape_metadata(MetadataScraperInput(
            video_url=test["url"],
            task_id=task_id,
            project_name=f"test_{test['name'].lower()}",
        ))

        print(f"\nResult saved to: {result_path}")
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        print(f"  success: {result['success']}")
        if result["metadata"]:
            m = result["metadata"]
            print(f"  platform: {m.get('platform')}")
            print(f"  video_id: {m.get('video_id')}")
            print(f"  author_name: {m.get('author_name')}")
            print(f"  likes: {m.get('likes')}, views: {m.get('views')}, comments: {m.get('comments')}")
            print(f"  followers: {m.get('followers')}, following: {m.get('following')}")
        if result["error"]:
            print(f"  error: {result['error']}")