"""Article writer node for Sparki SEO Blog Agent.

Extracts frames from video and generates blog article using Gemini.

Input:
    ArticleWriterInput with metadata_json_path, analysis_json_path, frame_timestamps,
    seo_keywords, project_name, output_base_dir, task_id

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/articles/{task_id}_article.json
    {
        "success": bool,
        "article_markdown": str,
        "word_count": int,
        "frame_paths": [...],
        "error": str | null,
        "task_id": str,
        "timestamp": str
    }
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.storage.storage_paths import StoragePaths
from src.config import get_gcp_config

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================


class ArticleWriterInput(TypedDict):
    """Input schema for article writer node."""

    metadata_json_path: str          # Path to metadata JSON from metadata_scraper
    analysis_json_path: str         # Path to analysis JSON from video_analyzer
    frame_timestamps: list[float]   # List of timestamps to extract frames
    cover_image_timestamps: list[float]  # List of timestamps for cover image frames
    seo_keywords: list[str]          # SEO keywords for article
    project_name: str = "default"
    output_base_dir: str = "data"
    task_id: str


# =============================================================================
# Helper Functions
# =============================================================================


def _load_prompt_template(filename: str) -> str:
    """Load prompt template from configs/prompts/."""
    prompt_path = Path(__file__).parent.parent.parent.parent / "configs" / "prompts" / filename
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_triplet_frames(video_local_path: str, timestamps: list[float],
                            output_dir: Path) -> list[str]:
    """Extract 3 frames per timestamp (anchor-0.5s, anchor, anchor+0.5s) and stitch into images.

    For each anchor timestamp, extracts a horizontal triplet image showing the moment
    before, at, and after the key moment.

    Args:
        video_local_path: Local path to video file
        timestamps: List of anchor timestamps (seconds)
        output_dir: Directory to save stitched frames

    Returns:
        List of paths to stitched triplet images (one per anchor)
    """
    triplet_paths = []
    output_dir.mkdir(parents=True, exist_ok=True)

    offsets = [-0.5, 0, 0.5]  # Before, anchor, after

    for idx, anchor in enumerate(timestamps):
        triplet_frames = []

        for offset in offsets:
            ts_actual = anchor + offset
            if ts_actual < 0:
                ts_actual = 0

            hours = int(ts_actual // 3600)
            minutes = int((ts_actual % 3600) // 60)
            seconds = int(ts_actual % 60)
            millis = int((ts_actual % 1) * 1000)

            frame_name = f"triplet_{idx}_{hours:02d}-{minutes:02d}-{seconds:02d}-{millis:03d}.jpg"
            frame_path = output_dir / frame_name

            # Check if already exists
            if frame_path.exists():
                triplet_frames.append(str(frame_path))
                continue

            cmd = [
                "ffmpeg", "-y", "-ss", str(ts_actual), "-i", video_local_path,
                "-vframes", "1", "-q:v", "2", str(frame_path)
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0 and frame_path.exists():
                    triplet_frames.append(str(frame_path))
                else:
                    logger.warning(f"Failed to extract triplet frame at {ts_actual:.3f}s")
            except Exception as e:
                logger.warning(f"Triplet frame error at {ts_actual:.3f}s: {e}")

        # Stitch the 3 frames horizontally (no scaling, no crop)
        if len(triplet_frames) >= 2:
            triplet_path = output_dir / f"triplet_{idx}_{anchor:.1f}s.jpg"
            num = len(triplet_frames)
            filter_parts = [f"[{i}:v]null[img{i}]" for i in range(num)]
            if num == 2:
                filter_parts.append("[img0][img1]hstack=inputs=2[out]")
            elif num == 3:
                filter_parts.append("[img0][img1]hstack=inputs=2[left];[left][img2]hstack=inputs=2[out]")

            filter_str = ";".join(filter_parts)
            cmd = ["ffmpeg", "-y"]
            for path in triplet_frames:
                cmd.extend(["-i", path])
            cmd.extend(["-filter_complex", filter_str, "-map", "[out]", "-vframes", "1", "-q:v", "2", str(triplet_path)])

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0 and triplet_path.exists():
                    triplet_paths.append(str(triplet_path))
                    logger.info(f"Created triplet image: {triplet_path.name}")
                else:
                    logger.warning(f"Triplet stitch failed: {result.stderr[:100]}")
            except Exception as e:
                logger.warning(f"Triplet stitch error: {e}")

    logger.info(f"Created {len(triplet_paths)} triplet images from {len(timestamps)} anchors")
    return triplet_paths


def _extract_frames_ffmpeg(video_local_path: str, timestamps: list[float],
                           output_dir: Path) -> tuple[list[str], list[str]]:
    """Extract frames from video using ffmpeg.

    For each requested timestamp, extracts frames at:
    - ts (primary)
    - ts - 1500ms, ts - 1000ms, ts - 500ms (backup before)
    - ts + 500ms, ts + 1000ms, ts + 1500ms (backup after)

    Args:
        video_local_path: Local path to video file
        timestamps: List of timestamps (seconds) to extract
        output_dir: Directory to save frames

    Returns:
        Tuple of (primary_frame_paths, backup_frame_paths)
    """
    primary_paths = []
    backup_paths = []
    output_dir.mkdir(parents=True, exist_ok=True)

    # Offset multipliers: backup before (negative) and after (positive)
    offsets = [-1.5, -1.0, -0.5, 0, 0.5, 1.0, 1.5]

    for ts in timestamps:
        for offset in offsets:
            ts_actual = ts + offset
            if ts_actual < 0:
                continue  # Skip negative timestamps

            hours = int(ts_actual // 3600)
            minutes = int((ts_actual % 3600) // 60)
            seconds = int(ts_actual % 60)
            millis = int((ts_actual % 1) * 1000)

            # Naming: frame_HH-MM-SS-mmm.jpg
            frame_name = f"frame_{hours:02d}-{minutes:02d}-{seconds:02d}-{millis:03d}.jpg"
            frame_path = output_dir / frame_name

            # Skip if already exists
            if frame_path.exists():
                if offset == 0:
                    primary_paths.append(str(frame_path))
                else:
                    backup_paths.append(str(frame_path))
                logger.info(f"Frame already exists: {frame_path}")
                continue

            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(ts_actual),
                "-i", video_local_path,
                "-vframes", "1",
                "-q:v", "2",
                str(frame_path)
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and frame_path.exists():
                    if offset == 0:
                        primary_paths.append(str(frame_path))
                    else:
                        backup_paths.append(str(frame_path))
                    logger.info(f"Extracted frame at {ts_actual:.3f}s -> {frame_name}")
                else:
                    logger.warning(f"Failed at {ts_actual:.3f}s: {result.stderr[:100]}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout at {ts_actual:.3f}s")
            except Exception as e:
                logger.warning(f"Error at {ts_actual:.3f}s: {e}")

    logger.info(f"Extracted {len(primary_paths)} primary + {len(backup_paths)} backup frames")
    return primary_paths, backup_paths


def _build_frame_info(frame_paths: list[str], backup_paths: list[str] = None,
                      triplet_paths: list[str] = None) -> str:
    """Build frame metadata string for prompt.

    Args:
        frame_paths: List of primary frame file paths
        backup_paths: Optional list of backup frame file paths
        triplet_paths: Optional list of triplet image paths (anchor ±0.5s stitched)

    Returns:
        String describing available frames
    """
    if not frame_paths and not triplet_paths:
        return "No frames available."

    lines = ["Available Frames:"]

    # Describe triplet images (main content images)
    if triplet_paths:
        lines.append("\nTriplet Images (for article body - shows anchor-0.5s, anchor, anchor+0.5s):")
        for path in triplet_paths:
            filename = Path(path).name
            lines.append(f"- {filename}")

    # Describe primary frames
    if frame_paths:
        lines.append("\nPrimary Frames:")
        for path in frame_paths:
            filename = Path(path).name
            # Extract timestamp from filename
            # Format: frame_HH-MM-SS-mmm.jpg (with milliseconds)
            try:
                parts = filename.replace("frame_", "").replace(".jpg", "").split("-")
                if len(parts) == 4:
                    h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    ts = h * 3600 + m * 60 + s + ms / 1000
                    lines.append(f"- {filename} (timestamp: {ts:.3f}s)")
                elif len(parts) == 3:
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                    ts = h * 3600 + m * 60 + s
                    lines.append(f"- {filename} (timestamp: {ts}s)")
                else:
                    lines.append(f"- {filename}")
            except Exception:
                lines.append(f"- {filename}")

    if backup_paths:
        lines.append("\nBackup Frames (for motion blur avoidance):")
        for path in backup_paths:
            filename = Path(path).name
            try:
                parts = filename.replace("frame_", "").replace(".jpg", "").split("-")
                if len(parts) == 4:
                    h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    ts = h * 3600 + m * 60 + s + ms / 1000
                    lines.append(f"- {filename} (timestamp: {ts:.3f}s)")
            except Exception:
                lines.append(f"- {filename}")

    return "\n".join(lines)


def _generate_cover_image(frame_paths: list[str], frames_dir: Path, task_id: str) -> str:
    """Generate a cover image by stitching multiple 9:16 frames horizontally.

    Simply concatenates frames side-by-side without any scaling/cropping.
    For 9:16 source (0.5625 aspect), 3 frames give ~1.69 aspect (closest to 4:3).

    Args:
        frame_paths: List of primary frame file paths
        frames_dir: Directory containing frames
        task_id: Task ID for naming

    Returns:
        Path to generated cover image, or empty string if failed
    """
    if not frame_paths:
        return ""

    # Take exactly 3 frames for 9:16 (gives ~1.69 aspect, closest to 4:3)
    # 4 frames would be 2.25, 2 frames would be 1.125
    num_frames = 3
    if len(frame_paths) < 3:
        logger.warning(f"Need at least 3 frames for cover, got {len(frame_paths)}")
        return ""

    # Evenly space across available frames
    selected = frame_paths[::max(1, len(frame_paths) // num_frames)][:num_frames]

    if len(selected) < 2:
        logger.warning("Need at least 2 frames for cover image")
        return ""

    cover_path = frames_dir / f"cover_{task_id}.jpg"

    # Simply hstack frames without any scaling/cropping
    num = len(selected)

    # Build filter: each frame passed through, then hstack
    filter_parts = []
    for i in range(num):
        filter_parts.append(f"[{i}:v]null[img{i}]")

    if num == 2:
        filter_parts.append("[img0][img1]hstack=inputs=2[out]")
    elif num == 3:
        filter_parts.append("[img0][img1]hstack=inputs=2[left];[left][img2]hstack=inputs=2[out]")
    elif num == 4:
        filter_parts.append("[img0][img1]hstack=inputs=2[left];[left][img2]hstack=inputs=2[mid];[mid][img3]hstack=inputs=2[out]")
    else:
        filter_parts.append("[img0][img1]hstack=inputs=2[out]")

    filter_str = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
    ]
    for path in selected:
        cmd.extend(["-i", path])
    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-vframes", "1",
        "-q:v", "2",
        str(cover_path)
    ])

    logger.info(f"Running ffmpeg with filter: {filter_str}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and cover_path.exists():
            from PIL import Image
            with Image.open(cover_path) as img:
                logger.info(f"Cover image stitched from {len(selected)} frames -> {cover_path} ({img.size})")
            return str(cover_path)
        else:
            logger.warning(f"Cover image failed: {result.stderr[:500]}")
    except Exception as e:
        logger.warning(f"Cover image error: {e}")

    return ""


def _format_blog_prompt(metadata: dict, analysis: dict, frame_info: str,
                        seo_keywords: list[str], cover_image_path: str = "") -> str:
    """Format blog writing prompt with input data."""
    template = _load_prompt_template("blog_write.txt")

    # Build video stats string
    video_stats = []
    if metadata.get("views"):
        video_stats.append(f"Views: {metadata['views']:,}")
    if metadata.get("likes"):
        video_stats.append(f"Likes: {metadata['likes']:,}")
    if metadata.get("comments"):
        video_stats.append(f"Comments: {metadata['comments']:,}")
    if metadata.get("saves"):
        video_stats.append(f"Saves: {metadata['saves']:,}")
    video_stats_str = ", ".join(video_stats) if video_stats else "N/A"

    # Build analysis result string (JSON as text)
    analysis_str = json.dumps(analysis, ensure_ascii=False, indent=2)

    # Cover image info for prompt
    cover_info = ""
    if cover_image_path:
        cover_filename = Path(cover_image_path).name
        cover_info = f"\n\nCover Image: {cover_filename} (4:3 stitched image to be placed at top of article)"

    # Format prompt
    return template.format(
        Creator=metadata.get("author_name", "@unknown"),
        Followers=_format_follower_count(metadata.get("followers", 0)),
        video_url=metadata.get("video_url", metadata.get("author_url", "")),
        video_stats_str=video_stats_str,
        seo_keywords=", ".join(seo_keywords) if seo_keywords else "viral video, content creation",
        analysis_result=analysis_str,
        frame_info=frame_info,
        cover_image=cover_info,
    )


def _format_follower_count(count: int) -> str:
    """Format follower count for display."""
    if count >= 1000000:
        return f"{count / 1000000:.1f}M"
    elif count >= 1000:
        return f"{count / 1000:.1f}K"
    else:
        return str(count)


def _save_result_json(result: dict, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save result as JSON file."""
    result_dir = StoragePaths.local_base(output_base_dir, project_name) / "articles"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{task_id}_article.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(result_path)


def _save_markdown(markdown: str, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save article as Markdown file."""
    md_dir = StoragePaths.local_base(output_base_dir, project_name) / "articles"
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{task_id}_article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return str(md_path)


# =============================================================================
# Main Function
# =============================================================================


def write_article(input: ArticleWriterInput) -> str:
    """Generate blog article from video metadata, analysis, and frames.

    Args:
        input: ArticleWriterInput with metadata_json_path, analysis_json_path,
               frame_timestamps, seo_keywords, project_name, output_base_dir, task_id

    Returns:
        Path to JSON result file
    """
    metadata_json_path = input["metadata_json_path"]
    analysis_json_path = input["analysis_json_path"]
    frame_timestamps = input["frame_timestamps"]
    cover_image_timestamps = input.get("cover_image_timestamps", [])
    seo_keywords = input.get("seo_keywords", [])
    project_name = input.get("project_name", "default")
    output_base_dir = input.get("output_base_dir", "data")
    task_id = input["task_id"]

    logger.info(f"Starting article writing: task_id={task_id}, cover_frames={len(cover_image_timestamps)}")

    # Result template
    result = {
        "success": False,
        "article_markdown": "",
        "word_count": 0,
        "frame_paths": [],
        "error": None,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Load metadata and analysis JSONs
        with open(metadata_json_path, "r", encoding="utf-8") as f:
            metadata_result = json.load(f)
        metadata = metadata_result.get("metadata", {})

        with open(analysis_json_path, "r", encoding="utf-8") as f:
            analysis_result = json.load(f)
        analysis = analysis_result.get("analysis", {})

        if not metadata or not analysis:
            raise ValueError("Metadata or analysis JSON is empty")

        # Get video local path for this specific task_id
        video_local_path = str(StoragePaths.local_video_path(output_base_dir, project_name, task_id))
        if not os.path.exists(video_local_path):
            raise ValueError(f"Video file not found for task_id {task_id}: {video_local_path}")

        # Extract frames (returns tuple of primary and backup paths)
        frames_dir = StoragePaths.local_frames_dir(output_base_dir, project_name, task_id)
        frame_paths, backup_paths = _extract_frames_ffmpeg(video_local_path, frame_timestamps, frames_dir)

        if not frame_paths:
            logger.warning("No frames extracted, proceeding with article generation")

        result["frame_paths"] = frame_paths

        # Generate triplet images for body content (anchor-0.5s, anchor, anchor+0.5s)
        triplet_paths = []
        if frame_timestamps:
            triplet_paths = _extract_triplet_frames(video_local_path, frame_timestamps, frames_dir)
            logger.info(f"Generated {len(triplet_paths)} triplet images for article body")

        # Build frame info for prompt (include backup frames info)
        frame_info = _build_frame_info(frame_paths, backup_paths, triplet_paths)

        # Generate cover image using dedicated cover timestamps
        cover_image_path = ""
        cover_frame_paths = []
        if cover_image_timestamps:
            cover_frames_dir = frames_dir  # Same directory
            cover_frame_paths, _ = _extract_frames_ffmpeg(video_local_path, cover_image_timestamps, cover_frames_dir)
            if cover_frame_paths:
                cover_image_path = _generate_cover_image(cover_frame_paths, cover_frames_dir, task_id)
                if cover_image_path:
                    logger.info(f"Cover image generated from {len(cover_frame_paths)} cover frames: {cover_image_path}")
        elif frame_paths:
            # Fallback: use regular frames if no cover timestamps
            cover_image_path = _generate_cover_image(frame_paths[:4], frames_dir, task_id)
            if cover_image_path:
                logger.info(f"Cover image generated (fallback): {cover_image_path}")

        # Format prompt (include cover image path)
        prompt = _format_blog_prompt(metadata, analysis, frame_info, seo_keywords, cover_image_path)

        logger.info(f"Calling Gemini for article generation")

        # Call Gemini via Vertex AI
        gcp_config = get_gcp_config()
        project_id = gcp_config.get("project_id", "sparki-op")

        from google import genai

        client = genai.Client(
            vertexai=True,
            project=project_id,
            location="global",
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
            ],
        )

        # Clean markdown code block wrappers if present
        article_markdown = response.text.strip()
        if article_markdown.startswith("```yaml"):
            article_markdown = article_markdown[7:]  # Remove ```yaml
        elif article_markdown.startswith("```"):
            article_markdown = article_markdown[3:]  # Remove opening ```
        if article_markdown.endswith("```"):
            article_markdown = article_markdown[:-3]  # Remove closing ```
        article_markdown = article_markdown.strip()

        # Find the YAML block start (---) and end (---) and extract just the YAML + content
        # Handle cases where stray characters might appear before ---
        yaml_start = article_markdown.find("---")
        if yaml_start > 0:
            article_markdown = article_markdown[yaml_start:]
            logger.info(f"Stripped {yaml_start} stray characters before YAML block")

        # Fix image paths: replace generic "frames/" with proper relative path
        # Handle both regular frames and triplet images
        if task_id:
            if frame_paths:
                article_markdown = article_markdown.replace("frames/frame_", f"../frames/{task_id}/frame_")
                logger.info(f"Fixed frame image paths to use ../frames/{task_id}/")
            if triplet_paths:
                article_markdown = article_markdown.replace("frames/triplet_", f"../frames/{task_id}/triplet_")
                logger.info(f"Fixed triplet image paths to use ../frames/{task_id}/")

        # Remove duplicate cover image that Gemini might add (often with wrong path format)
        # Gemini sometimes adds its own cover image description - remove it if present
        import re
        article_markdown = re.sub(r'!\[Cover Image\]\([^)]+\)\n?', '', article_markdown, count=1)
        article_markdown = re.sub(r'!\[[^\]]*stitched[^\]]*\]\([^)]+\)\n?', '', article_markdown, count=1)
        logger.info("Removed duplicate cover image if present")

        # Insert cover image at top (after YAML block, before H1 title)
        if cover_image_path:
            cover_filename = Path(cover_image_path).name
            cover_markdown = f"![Cover Image](../frames/{task_id}/{cover_filename})\n\n"
            yaml_end = article_markdown.find("---", 4)  # Find closing ---
            if yaml_end > 0:
                yaml_end = article_markdown.find("\n", yaml_end + 3)
                if yaml_end > 0:
                    article_markdown = article_markdown[:yaml_end + 1] + cover_markdown + article_markdown[yaml_end + 1:]
                    logger.info(f"Inserted cover image at top of article")

        # Remove any image that appears after the last "---" in How to Replicate section
        # Find the last occurrence of "---" (end of table) and remove images after it
        last_dash = article_markdown.rfind("---")
        if last_dash > 0:
            # Check if there are images after the last ---
            after_table = article_markdown[last_dash:]
            if "](.." in after_table:
                # Remove all image links after the table
                import re
                article_markdown = article_markdown[:last_dash] + re.sub(r'!\[[^\]]*\]\([^)]+\)', '', after_table)
                logger.info("Removed images after How to Replicate table")

        word_count = len(article_markdown.split())

        logger.info(f"Article generated: {word_count} words, {len(frame_paths)} frames")

        result["success"] = True
        result["article_markdown"] = article_markdown
        result["word_count"] = word_count

        # Also save as .md file
        md_path = _save_markdown(article_markdown, output_base_dir, project_name, task_id)
        logger.info(f"Article saved to: {md_path}")

        return _save_result_json(result, output_base_dir, project_name, task_id)

    except Exception as e:
        error_msg = f"Article writing failed: {str(e)}"
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
        {
            "name": "TikTok",
            "metadata_json_path": "data/Sparki_SEO_Blog_Agent_V2/test_tiktok/metadata_result/4751a8dd_meta.json",
            "analysis_json_path": "data/Sparki_SEO_Blog_Agent_V2/test_tiktok/analysis_result/4199b40d_analysis.json",
            "frame_timestamps": [0.5, 3.5, 6.5, 12.5, 18.5],
            "cover_image_timestamps": [],
            "seo_keywords": ["morning routine", "productivity", "clean girl aesthetic"],
            "project_name": "test_tiktok",
        },
        {
            "name": "Instagram",
            "metadata_json_path": "data/Sparki_SEO_Blog_Agent_V2/test_instagram/metadata_result/4c82d2b1_meta.json",
            "analysis_json_path": "data/Sparki_SEO_Blog_Agent_V2/test_instagram/analysis_result/69e89d18_analysis.json",
            "frame_timestamps": [3.0, 6.0, 8.0, 12.0, 19.0],
            "cover_image_timestamps": [],
            "seo_keywords": ["gym workout", "fitness routine", "home exercise"],
            "project_name": "test_instagram",
        },
    ]

    for test in test_cases:
        print(f"\n{'=' * 60}")
        print(f"Testing {test['name']}: {test['metadata_json_path']}")
        print("=" * 60)

        task_id = str(uuid.uuid4())[:8]
        result_path = write_article(ArticleWriterInput(
            metadata_json_path=test["metadata_json_path"],
            analysis_json_path=test["analysis_json_path"],
            frame_timestamps=test["frame_timestamps"],
            cover_image_timestamps=test.get("cover_image_timestamps", []),
            seo_keywords=test["seo_keywords"],
            project_name=test["project_name"],
            task_id=task_id,
        ))

        print(f"\nResult saved to: {result_path}")
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        print(f"  success: {result['success']}")
        print(f"  word_count: {result['word_count']}")
        print(f"  frames_extracted: {len(result['frame_paths'])}")
        if result['error']:
            print(f"  error: {result['error']}")
        elif result['article_markdown']:
            print(f"  article_preview: {result['article_markdown'][:200]}...")