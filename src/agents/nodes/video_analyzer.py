"""Video analyzer node for Sparki SEO Blog Agent.

Analyzes video using Gemini via Vertex AI with GCS URI.
Supports TikTok and Instagram Reels.

Input:
    VideoAnalyzerInput with video_gcs_path, video_local_path, platform,
    creator_handle, duration, project_name, output_base_dir, task_id

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/analysis_result/{task_id}_analysis.json
    {
        "success": bool,
        "analysis": { ... full Gemini output ... },
        "frame_timestamps": [ ... timestamps from recommended_frames ... ],
        "error": str | null,
        "task_id": str,
        "timestamp": str
    }
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.storage.storage_paths import StoragePaths
from src.config import get_gcp_config

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================


class VideoAnalyzerInput(TypedDict):
    """Input schema for video analyzer node."""

    video_gcs_path: str           # GCS path for Gemini (e.g., gs://bucket/videos/task_id.mp4)
    video_local_path: str         # Local path for ffmpeg (not sent to Gemini)
    platform: str                # 'tiktok' or 'instagram'
    creator_handle: str          # e.g., '@urmom_sushi'
    duration: float               # Video duration in seconds
    project_name: str = "default"
    output_base_dir: str = "data"
    task_id: str


# =============================================================================
# Configuration
# =============================================================================


def _get_gcp_settings() -> dict:
    """Get GCP settings from config."""
    return get_gcp_config()


# =============================================================================
# Helper Functions
# =============================================================================


def _load_prompt_template() -> str:
    """Load video analysis prompt template."""
    prompt_path = Path(__file__).parent.parent.parent.parent / "configs" / "prompts" / "video_analysis.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _format_prompt(template: str, video_uri: str, platform: str, creator: str, duration: float) -> str:
    """Fill in prompt template with video info."""
    return template.format(
        video_uri=video_uri,
        platform=platform,
        creator_handle=creator,
        duration=int(duration)
    )


def _extract_frame_timestamps(analysis: dict, max_duration: float = float('inf')) -> tuple[list[float], list[float]]:
    """Extract recommended frame timestamps and cover image timestamps from Gemini analysis.

    Args:
        analysis: Parsed JSON from Gemini response
        max_duration: Maximum valid timestamp (video duration in seconds)

    Returns:
        Tuple of (recommended_timestamps, cover_image_timestamps)
    """
    timestamps = []
    cover_timestamps = []
    try:
        frames = analysis.get("recommended_frames", {}).get("frames", [])
        for frame in frames:
            ts = frame.get("timestamp")
            if ts is not None:
                try:
                    ts_float = float(ts)
                    if ts_float < 0:
                        ts_float = 0.0
                    if ts_float > max_duration:
                        ts_float = max_duration
                    timestamps.append(ts_float)
                except (ValueError, TypeError):
                    pass

        # Extract cover image timestamps
        cover_data = analysis.get("cover_image_timestamps", {})
        if cover_data:
            cover_list = cover_data.get("timestamps", [])
            for item in cover_list:
                ts = item.get("timestamp")
                if ts is not None:
                    try:
                        ts_float = float(ts)
                        if ts_float < 0:
                            ts_float = 0.0
                        if ts_float > max_duration:
                            ts_float = max_duration
                        cover_timestamps.append(ts_float)
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        logger.warning(f"Failed to extract frame timestamps: {e}")

    # Deduplicate and sort
    timestamps = sorted(set(timestamps))
    cover_timestamps = sorted(set(cover_timestamps))
    logger.info(f"Extracted {len(timestamps)} frame timestamps, {len(cover_timestamps)} cover timestamps (clipped to {max_duration}s)")
    return timestamps, cover_timestamps


def _save_result_json(result: dict, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save result as JSON file."""
    result_dir = StoragePaths.local_base(output_base_dir, project_name) / "analysis_result"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{task_id}_analysis.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(result_path)


# =============================================================================
# Main Function
# =============================================================================


def analyze_video(input: VideoAnalyzerInput) -> str:
    """Analyze video using Gemini via Vertex AI.

    Args:
        input: VideoAnalyzerInput with video_gcs_path, video_local_path, platform,
               creator_handle, duration, project_name, output_base_dir, task_id

    Returns:
        Path to JSON result file
    """
    video_gcs_path = input["video_gcs_path"]
    video_local_path = input["video_local_path"]
    platform = input["platform"]
    creator_handle = input["creator_handle"]
    duration = input["duration"]
    project_name = input.get("project_name", "default")
    output_base_dir = input.get("output_base_dir", "data")
    task_id = input["task_id"]

    logger.info(f"Starting video analysis: {video_gcs_path}")

    # Result template
    result = {
        "success": False,
        "analysis": None,
        "frame_timestamps": [],
        "cover_image_timestamps": [],
        "error": None,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Load prompt and fill in video info
        prompt_template = _load_prompt_template()
        prompt = _format_prompt(prompt_template, video_gcs_path, platform, creator_handle, duration)

        logger.info(f"Calling Gemini with video URI: {video_gcs_path}")

        # Call Gemini via Vertex AI
        gcp_config = _get_gcp_settings()
        project_id = gcp_config.get("project_id", "sparki-op")

        from google import genai

        client = genai.Client(
            vertexai=True,
            project=project_id,
            location="global",
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                genai.types.Part.from_uri(file_uri=video_gcs_path, mime_type="video/mp4"),
                prompt,
            ],
        )

        # Parse Gemini response as JSON
        response_text = response.text.strip()
        # Remove markdown code blocks if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        analysis = json.loads(response_text)
        logger.info(f"Gemini analysis successful")

        # Extract frame timestamps (clip to video duration)
        frame_timestamps, cover_timestamps = _extract_frame_timestamps(analysis, max_duration=duration)

        result["success"] = True
        result["analysis"] = analysis
        result["frame_timestamps"] = frame_timestamps
        result["cover_image_timestamps"] = cover_timestamps

        logger.info(f"Video analysis completed. Extracted {len(frame_timestamps)} frame timestamps, {len(cover_timestamps)} cover timestamps")
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse Gemini response as JSON: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except Exception as e:
        error_msg = f"Video analysis failed: {str(e)}"
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
            "video_gcs_path": "gs://sparki-op-test/Sparki_SEO_Blog_Agent_V2/test_tiktok/videos/973009b7.mp4",
            "video_local_path": "data/Sparki_SEO_Blog_Agent_V2/test_tiktok/raw/973009b7.mp4",
            "platform": "tiktok",
            "creator_handle": "@urmom_sushi",
            "duration": 48.0,
            "project_name": "test_tiktok",
        },
        {
            "name": "Instagram",
            "video_gcs_path": "gs://sparki-op-test/Sparki_SEO_Blog_Agent_V2/test_instagram/videos/d0dd1d15.mp4",
            "video_local_path": "data/Sparki_SEO_Blog_Agent_V2/test_instagram/raw/d0dd1d15.mp4",
            "platform": "instagram",
            "creator_handle": "@mialaurengreen",
            "duration": 70.666,
            "project_name": "test_instagram",
        },
    ]

    for test in test_cases:
        print(f"\n{'=' * 60}")
        print(f"Testing {test['name']}: {test['video_gcs_path']}")
        print("=" * 60)

        task_id = str(uuid.uuid4())[:8]
        result_path = analyze_video(VideoAnalyzerInput(
            video_gcs_path=test["video_gcs_path"],
            video_local_path=test["video_local_path"],
            platform=test["platform"],
            creator_handle=test["creator_handle"],
            duration=test["duration"],
            project_name=test["project_name"],
            task_id=task_id,
        ))

        print(f"\nResult saved to: {result_path}")
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        print(f"  success: {result['success']}")
        if result["analysis"]:
            analysis = result["analysis"]
            print(f"  hook_opening.first_frame_description: {analysis.get('hook_opening', {}).get('first_frame_description', '')[:80]}...")
            print(f"  recommended_frames.count: {len(analysis.get('recommended_frames', {}).get('frames', []))}")
        print(f"  frame_timestamps: {result['frame_timestamps'][:5]}...")
        if result["error"]:
            print(f"  error: {result['error']}")