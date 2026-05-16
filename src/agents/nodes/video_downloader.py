"""Video downloader node for Sparki SEO Blog Agent.

Downloads videos from TikTok and Instagram using yt-dlp, saves to local storage
and backs up to GCS.

Input:
    VideoDownloaderInput with video_url, project_name, output_base_dir, task_id

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/download_result/{task_id}_result.json
    {
        "success": bool,
        "local_video_path": str,
        "gcs_video_path": str,
        "error": str | null,
        "metadata": {
            "title": str,
            "duration": float,
            "uploader": str,
            "upload_date": str,
            "file_size": int
        },
        "task_id": str,
        "timestamp": str
    }
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import TypedDict

import yt_dlp

from src.storage.storage_paths import StoragePaths
from src.config import get_gcs_bucket_name

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================


class VideoDownloaderInput(TypedDict):
    """Input schema for video downloader node."""

    video_url: str
    project_name: str
    output_base_dir: str
    task_id: str


# =============================================================================
# Configuration
# =============================================================================

GCS_BUCKET_NAME = get_gcs_bucket_name()
if not GCS_BUCKET_NAME:
    GCS_BUCKET_NAME = "sparki-op-test"  # fallback


# =============================================================================
# Helper Functions
# =============================================================================


def _format_metadata(info: dict) -> dict:
    """Format yt-dlp info into our metadata schema.

    Args:
        info: Raw yt-dlp info dict

    Returns:
        Formatted metadata dict
    """
    return {
        "title": info.get("title", ""),
        "duration": info.get("duration", 0.0) or 0.0,
        "uploader": info.get("uploader", info.get("uploader_id", "")),
        "upload_date": info.get("upload_date", ""),
        "description": info.get("description", ""),
        "thumbnail": info.get("thumbnail", ""),
    }


def _upload_to_gcs(local_path: str, gcs_path: str) -> bool:
    """Upload file to Google Cloud Storage.

    Args:
        local_path: Local file path
        gcs_path: GCS destination path (gs://bucket/...)

    Returns:
        True if upload succeeded, False otherwise
    """
    try:
        from google.cloud import storage

        if not gcs_path.startswith("gs://"):
            logger.error(f"Invalid GCS path format: {gcs_path}")
            return False

        path_parts = gcs_path[5:].split("/", 1)
        bucket_name = path_parts[0]
        blob_path = path_parts[1] if len(path_parts) > 1 else ""

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(local_path)
        logger.info(f"Uploaded to GCS: {gcs_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        return False


def _parse_download_error(error: str) -> str:
    """Parse yt-dlp error and return user-friendly message in Chinese."""
    error_lower = error.lower()

    if any(pattern in error_lower for pattern in [
        "ip address is blocked", "blocked from accessing", "geo", "country", "region",
    ]):
        return "IP被封禁或地区受限，请检查代理设置"

    if any(pattern in error_lower for pattern in [
        "is not a valid url", "video id", "no video found", "cannot decode",
        "not found", "unable to extract",
    ]):
        return "请检查URL，该视频可能不存在、已删除或无法访问"

    if any(pattern in error_lower for pattern in [
        "connection", "timeout", "network", "ssl", "certificate",
    ]):
        return "网络连接失败，请检查网络或代理设置"

    if any(pattern in error_lower for pattern in [
        "login", "private", "age", "sign in", "authentication",
    ]):
        return "该视频需要登录或为私密内容，请检查URL"

    return "下载失败，请检查URL或网络连接"


def _save_result_json(result: dict, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save result as JSON file.

    Returns:
        Path to the JSON file
    """
    result_dir = StoragePaths.local_base(output_base_dir, project_name) / "download_result"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{task_id}_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(result_path)


# =============================================================================
# Main Download Function
# =============================================================================


def download_video(input: VideoDownloaderInput) -> str:
    """Download video from URL to local storage and GCS backup.

    Args:
        input: VideoDownloaderInput with video_url, project_name,
               output_base_dir, task_id

    Returns:
        Path to JSON result file
    """
    video_url = input["video_url"]
    project_name = input["project_name"]
    output_base_dir = input["output_base_dir"]
    task_id = input["task_id"]

    logger.info(f"Starting video download: {video_url}")
    logger.info(f"Project: {project_name}, Task: {task_id}")

    # Determine output paths
    local_video_path = str(StoragePaths.local_video_path(output_base_dir, project_name, task_id))
    gcs_video_path = StoragePaths.gcs_video_path(GCS_BUCKET_NAME, project_name, task_id)

    # Ensure output directory exists
    local_path_obj = StoragePaths.local_video_path(output_base_dir, project_name, task_id)
    StoragePaths.ensure_dirs(local_path_obj)

    # Configure yt-dlp options
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": local_video_path,
        "quiet": False,
        "no_warnings": False,
        "extract_flat": False,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 60,
    }

    # Result template
    result = {
        "success": False,
        "local_video_path": "",
        "gcs_video_path": "",
        "error": None,
        "metadata": {},
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

        if not os.path.exists(local_video_path):
            error_msg = f"Download completed but file not found: {local_video_path}"
            logger.error(error_msg)
            result["error"] = error_msg
            return _save_result_json(result, output_base_dir, project_name, task_id)

        file_size = os.path.getsize(local_video_path)
        logger.info(f"Download complete. File size: {file_size} bytes")

        # Format metadata
        if info:
            result["metadata"] = _format_metadata(info)
            result["metadata"]["file_size"] = file_size

        # Upload to GCS
        upload_success = _upload_to_gcs(local_video_path, gcs_video_path)
        if not upload_success:
            logger.warning("GCS upload failed, continuing with local file")

        result["success"] = True
        result["local_video_path"] = local_video_path
        result["gcs_video_path"] = gcs_video_path if upload_success else ""

        logger.info(f"Video download completed successfully")
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except yt_dlp.utils.DownloadError as e:
        error_msg = _parse_download_error(str(e))
        logger.error(f"Download failed: {error_msg}")
        result["error"] = error_msg
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except Exception as e:
        error_msg = f"Unexpected error during download: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        return _save_result_json(result, output_base_dir, project_name, task_id)


# =============================================================================
# Entry Point for LangGraph
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
        result_path = download_video(
            VideoDownloaderInput(
                video_url=test["url"],
                project_name=f"test_{test['name'].lower()}",
                output_base_dir="data",
                task_id=task_id,
            )
        )

        print(f"\nResult saved to: {result_path}")
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        print(f"  success: {result['success']}")
        print(f"  local_video_path: {result['local_video_path']}")
        print(f"  gcs_video_path: {result['gcs_video_path']}")
        print(f"  error: {result['error']}")
        if result["metadata"]:
            print(f"  metadata.title: {result['metadata'].get('title', '')[:50]}...")