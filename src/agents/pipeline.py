"""LangGraph pipeline for Sparki SEO Blog Agent.

This pipeline orchestrates the video-to-blog workflow:
1. download_video - Download video from TikTok/Instagram
2. scrape_metadata - Extract video and creator metadata
3. analyze_video - Gemini analysis for content insights
4. extract_frames - Extract key frames from video
5. write_article - Generate blog article
6. qc_check - Quality control check
7. rewrite_article (if needed) - Fix QC issues
8. publish_cms - Publish to Contentful

Usage:
    from src.agents.pipeline import run_pipeline

    result = run_pipeline({
        "video_url": "https://www.instagram.com/reels/DWwVuBJiukt/",
        "project_name": "my_project",
        "task_id": "abc123"
    })
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END

from src.agents.state_schema import (
    PipelineState,
)
from src.agents.nodes.video_downloader import download_video, VideoDownloaderInput
from src.agents.nodes.metadata_scraper import scrape_metadata, MetadataScraperInput
from src.agents.nodes.video_analyzer import analyze_video, VideoAnalyzerInput
from src.agents.nodes.article_writer import write_article, ArticleWriterInput
from src.agents.nodes.qc_checker import qc_check, QCCheckerInput
from src.agents.nodes.article_rewriter import rewrite_article, ArticleRewriterInput
from src.storage.storage_paths import StoragePaths
from src.config import get_gcs_bucket_name

logger = logging.getLogger(__name__)

# =============================================================================
# Pipeline State - Extended for LangGraph
# =============================================================================

class PipelineStage(str):
    """Pipeline stages enum."""
    INIT = "init"
    DOWNLOAD = "download"
    SCRAPE_METADATA = "scrape_metadata"
    ANALYZE = "analyze"
    EXTRACT_FRAMES = "extract_frames"
    WRITE_ARTICLE = "write_article"
    QC_CHECK = "qc_check"
    REWRITE = "rewrite"
    PUBLISH = "publish"
    DONE = "done"
    FAILED = "failed"


class PipelineNodeResult(TypedDict):
    """Standardized result from any pipeline node."""
    success: bool
    task_id: str
    stage: str
    status: str  # "completed" | "failed" | "in_progress"
    progress: float  # 0.0-1.0
    message: str
    data: dict | None
    error: str | None
    timestamp: str
    can_retry: bool


# =============================================================================
# Helper Functions
# =============================================================================

def _save_stage_result(
    task_id: str,
    stage: str,
    success: bool,
    progress: float,
    message: str,
    data: dict = None,
    error: str = None,
    can_retry: bool = True
) -> str:
    """Save standardized stage result to JSON file.

    Returns:
        Path to the result file
    """
    base_dir = StoragePaths.local_base("data", "default")  # Will be overridden by task's project
    result = PipelineNodeResult(
        success=success,
        task_id=task_id,
        stage=stage,
        status="completed" if success else "failed",
        progress=progress,
        message=message,
        data=data or {},
        error=error,
        timestamp=datetime.now(timezone.utc).isoformat(),
        can_retry=can_retry
    )

    # Save to task-specific directory
    result_path = base_dir / "pipeline_status" / f"{task_id}_{stage}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return str(result_path)


def _load_stage_result(task_id: str, stage: str) -> dict | None:
    """Load a stage result if it exists."""
    base_dir = StoragePaths.local_base("data", "default")
    result_path = base_dir / "pipeline_status" / f"{task_id}_{stage}.json"
    if result_path.exists():
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# =============================================================================
# Pipeline Nodes
# =============================================================================

def node_download_video(state: PipelineState) -> PipelineState:
    """Download video from URL."""
    task_id = state["task_id"]
    video_url = state["video_url"]
    project_name = state["project_name"]

    logger.info(f"[{task_id}] Starting download: {video_url}")

    try:
        result_path = download_video(VideoDownloaderInput(
            video_url=video_url,
            project_name=project_name,
            output_base_dir="data",
            task_id=task_id
        ))

        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        if result.get("success"):
            state["video_local_path"] = result.get("local_video_path", "")
            state["video_gcs_path"] = result.get("gcs_video_path", "")
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Download completed")

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.DOWNLOAD,
                success=True,
                progress=0.15,
                message="Video downloaded successfully",
                data={"local_path": state["video_local_path"], "gcs_path": state["video_gcs_path"]}
            )
        else:
            state["errors"].append(f"Download failed: {result.get('error')}")
            state["status"] = PipelineStage.FAILED

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.DOWNLOAD,
                success=False,
                progress=0.0,
                message=f"Download failed: {result.get('error')}",
                error=result.get("error"),
                can_retry=True
            )

    except Exception as e:
        logger.error(f"[{task_id}] Download error: {e}")
        state["errors"].append(str(e))
        state["status"] = PipelineStage.FAILED

        _save_stage_result(
            task_id=task_id,
            stage=PipelineStage.DOWNLOAD,
            success=False,
            progress=0.0,
            message=f"Download error: {str(e)}",
            error=str(e),
            can_retry=True
        )

    return state


def node_scrape_metadata(state: PipelineState) -> PipelineState:
    """Scrape video and creator metadata."""
    task_id = state["task_id"]
    video_url = state["video_url"]
    project_name = state["project_name"]

    logger.info(f"[{task_id}] Starting metadata scraping")

    try:
        result_path = scrape_metadata(MetadataScraperInput(
            video_url=video_url,
            task_id=task_id,
            project_name=project_name
        ))

        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        if result.get("success"):
            state["video_metadata"] = result.get("metadata", {})
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Metadata scraped")

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.SCRAPE_METADATA,
                success=True,
                progress=0.25,
                message="Metadata extracted successfully",
                data={"metadata": state["video_metadata"]}
            )
        else:
            state["errors"].append(f"Metadata scrape failed: {result.get('error')}")
            state["status"] = PipelineStage.FAILED

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.SCRAPE_METADATA,
                success=False,
                progress=0.15,
                message=f"Metadata scrape failed: {result.get('error')}",
                error=result.get("error"),
                can_retry=True
            )

    except Exception as e:
        logger.error(f"[{task_id}] Metadata scrape error: {e}")
        state["errors"].append(str(e))
        state["status"] = PipelineStage.FAILED

        _save_stage_result(
            task_id=task_id,
            stage=PipelineStage.SCRAPE_METADATA,
            success=False,
            progress=0.15,
            message=f"Metadata scrape error: {str(e)}",
            error=str(e),
            can_retry=True
        )

    return state


def node_analyze_video(state: PipelineState) -> PipelineState:
    """Analyze video with Gemini."""
    task_id = state["task_id"]
    project_name = state["project_name"]
    video_gcs_path = state.get("video_gcs_path", "")
    video_local_path = state.get("video_local_path", "")
    video_metadata = state.get("video_metadata", {})

    logger.info(f"[{task_id}] Starting video analysis")

    # Determine platform and creator handle
    platform = video_metadata.get("platform", "instagram")
    creator_handle = f"@{video_metadata.get('author_name', 'unknown')}"
    duration = video_metadata.get("video_duration", 60.0)

    try:
        result_path = analyze_video(VideoAnalyzerInput(
            video_gcs_path=video_gcs_path,
            video_local_path=video_local_path,
            platform=platform,
            creator_handle=creator_handle,
            duration=duration,
            project_name=project_name,
            task_id=task_id
        ))

        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        if result.get("success"):
            state["analysis_result"] = result.get("analysis", {})
            state["frame_timestamps"] = result.get("frame_timestamps", [])
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Video analyzed")

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.ANALYZE,
                success=True,
                progress=0.45,
                message="Video analyzed successfully",
                data={
                    "analysis": state["analysis_result"],
                    "frame_timestamps": state["frame_timestamps"],
                    "cover_timestamps": result.get("cover_image_timestamps", [])
                }
            )
        else:
            state["errors"].append(f"Video analysis failed: {result.get('error')}")
            state["status"] = PipelineStage.FAILED

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.ANALYZE,
                success=False,
                progress=0.25,
                message=f"Video analysis failed: {result.get('error')}",
                error=result.get("error"),
                can_retry=True
            )

    except Exception as e:
        logger.error(f"[{task_id}] Video analysis error: {e}")
        state["errors"].append(str(e))
        state["status"] = PipelineStage.FAILED

        _save_stage_result(
            task_id=task_id,
            stage=PipelineStage.ANALYZE,
            success=False,
            progress=0.25,
            message=f"Video analysis error: {str(e)}",
            error=str(e),
            can_retry=True
        )

    return state


def node_write_article(state: PipelineState) -> PipelineState:
    """Write blog article from analysis."""
    task_id = state["task_id"]
    project_name = state["project_name"]
    video_metadata = state.get("video_metadata", {})
    analysis_result = state.get("analysis_result", {})
    frame_timestamps = state.get("frame_timestamps", [])

    logger.info(f"[{task_id}] Starting article writing")

    # Build paths to metadata and analysis JSONs
    metadata_path = str(StoragePaths.local_base("data", project_name) / "metadata_result" / f"{task_id}_meta.json")
    analysis_path = str(StoragePaths.local_base("data", project_name) / "analysis_result" / f"{task_id}_analysis.json")

    # Extract cover timestamps from analysis if available
    cover_timestamps = []
    if analysis_result and isinstance(analysis_result, dict):
        cover_timestamps = analysis_result.get("cover_image_timestamps", [])
        if isinstance(cover_timestamps, dict):
            cover_timestamps = cover_timestamps.get("timestamps", [])

    # SEO keywords from analysis
    seo_keywords = []
    if analysis_result and isinstance(analysis_result, dict):
        seo_keywords = analysis_result.get("extracted_keywords", [])

    try:
        result_path = write_article(ArticleWriterInput(
            metadata_json_path=metadata_path,
            analysis_json_path=analysis_path,
            frame_timestamps=frame_timestamps,
            cover_image_timestamps=cover_timestamps,
            seo_keywords=seo_keywords,
            project_name=project_name,
            output_base_dir="data",
            task_id=task_id
        ))

        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        if result.get("success"):
            state["article_markdown"] = result.get("article_markdown", "")
            state["article_word_count"] = result.get("word_count", 0)
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Article written ({state['article_word_count']} words)")

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.WRITE_ARTICLE,
                success=True,
                progress=0.75,
                message=f"Article written successfully ({state['article_word_count']} words)",
                data={
                    "article_markdown": state["article_markdown"],
                    "word_count": state["article_word_count"]
                }
            )
        else:
            state["errors"].append(f"Article writing failed: {result.get('error')}")
            state["status"] = PipelineStage.FAILED

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.WRITE_ARTICLE,
                success=False,
                progress=0.55,
                message=f"Article writing failed: {result.get('error')}",
                error=result.get("error"),
                can_retry=True
            )

    except Exception as e:
        logger.error(f"[{task_id}] Article writing error: {e}")
        state["errors"].append(str(e))
        state["status"] = PipelineStage.FAILED

        _save_stage_result(
            task_id=task_id,
            stage=PipelineStage.WRITE_ARTICLE,
            success=False,
            progress=0.55,
            message=f"Article writing error: {str(e)}",
            error=str(e),
            can_retry=True
        )

    return state


def node_qc_check(state: PipelineState) -> PipelineState:
    """Quality control check."""
    task_id = state["task_id"]
    project_name = state["project_name"]
    article_markdown = state.get("article_markdown", "")

    logger.info(f"[{task_id}] Starting QC check")

    # Build paths to metadata and analysis JSONs
    metadata_path = str(StoragePaths.local_base("data", project_name) / "metadata_result" / f"{task_id}_meta.json")
    analysis_path = str(StoragePaths.local_base("data", project_name) / "analysis_result" / f"{task_id}_analysis.json")

    try:
        result = qc_check(QCCheckerInput(
            article_markdown=article_markdown,
            metadata_json_path=metadata_path,
            analysis_json_path=analysis_path,
            project_name=project_name,
            task_id=task_id
        ))

        if result.get("success") and result.get("qc_result"):
            qc_result = result["qc_result"]
            state["qc_result"] = qc_result
            state["qc_attempts"] += 1
            state["qc_passed"] = qc_result.get("passed", False)

            if state["qc_passed"]:
                state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] QC passed (score: {qc_result.get('overall_score', 0):.1f})")
                state["status"] = PipelineStage.PUBLISH
            else:
                state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] QC failed (score: {qc_result.get('overall_score', 0):.1f}), needs rewrite")
                state["status"] = PipelineStage.REWRITE

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.QC_CHECK,
                success=True,
                progress=0.85,
                message=f"QC check completed: {'passed' if state['qc_passed'] else 'needs rewrite'}",
                data={
                    "qc_result": qc_result,
                    "qc_attempts": state["qc_attempts"],
                    "qc_passed": state["qc_passed"]
                }
            )
        else:
            state["errors"].append(f"QC check failed: {result.get('error')}")
            state["status"] = PipelineStage.FAILED

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.QC_CHECK,
                success=False,
                progress=0.75,
                message=f"QC check failed: {result.get('error')}",
                error=result.get("error"),
                can_retry=True
            )

    except Exception as e:
        logger.error(f"[{task_id}] QC check error: {e}")
        state["errors"].append(str(e))
        state["status"] = PipelineStage.FAILED

        _save_stage_result(
            task_id=task_id,
            stage=PipelineStage.QC_CHECK,
            success=False,
            progress=0.75,
            message=f"QC check error: {str(e)}",
            error=str(e),
            can_retry=True
        )

    return state


def node_rewrite_article(state: PipelineState) -> PipelineState:
    """Rewrite article based on QC feedback."""
    task_id = state["task_id"]
    project_name = state["project_name"]
    article_markdown = state.get("article_markdown", "")
    qc_result = state.get("qc_result")

    logger.info(f"[{task_id}] Starting article rewrite (attempt {state['qc_attempts']})")

    try:
        result = rewrite_article(ArticleRewriterInput(
            article_markdown=article_markdown,
            qc_result=qc_result,
            project_name=project_name,
            task_id=task_id
        ))

        if result.get("success"):
            state["article_markdown"] = result.get("revised_article", article_markdown)
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Article rewritten")

            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.REWRITE,
                success=True,
                progress=0.80,
                message="Article rewritten successfully",
                data={"revisions_applied": result.get("revisions_applied", [])}
            )
        else:
            state["errors"].append(f"Article rewrite failed: {result.get('error')}")
            # Continue anyway - rewrite failure doesn't stop the pipeline
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Article rewrite failed but continuing")

    except Exception as e:
        logger.error(f"[{task_id}] Article rewrite error: {e}")
        state["errors"].append(str(e))
        # Continue anyway

    return state


def node_publish_cms(state: PipelineState) -> PipelineState:
    """Publish article to Contentful CMS."""
    task_id = state["task_id"]
    project_name = state["project_name"]

    logger.info(f"[{task_id}] Starting CMS publish")

    try:
        from src.agents.master.contentful_publisher import get_contentful_publisher

        publisher = get_contentful_publisher()

        result = publisher.publish_article(
            article_markdown=state["article_markdown"],
            metadata=state.get("video_metadata", {}),
            project_name=project_name,
            task_id=task_id
        )

        if result["success"]:
            state["cms_draft_url"] = result["cms_draft_url"]
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] CMS publish successful: {result['cms_draft_url']}")
            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.PUBLISH,
                success=True,
                progress=0.95,
                message=f"Published to Contentful: {result['article_id']}",
                data={"cms_draft_url": result["cms_draft_url"], "article_id": result["article_id"]}
            )
        else:
            state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] CMS publish failed: {result['error']}")
            _save_stage_result(
                task_id=task_id,
                stage=PipelineStage.PUBLISH,
                success=False,
                progress=0.95,
                message=f"CMS publish failed: {result['error']}",
                data={"error": result["error"]}
            )

    except Exception as e:
        logger.error(f"[{task_id}] CMS publish error: {e}")
        state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] CMS publish error: {str(e)}")

    state["status"] = PipelineStage.DONE
    state["logs"].append(f"[{datetime.now(timezone.utc).isoformat()}] Pipeline completed")

    _save_stage_result(
        task_id=task_id,
        stage=PipelineStage.DONE,
        success=True,
        progress=1.0,
        message="Pipeline completed successfully",
        data={"final_status": "done"}
    )

    return state


# =============================================================================
# Conditional Routing Functions
# =============================================================================

def should_rewrite(state: PipelineState) -> str:
    """Determine if we should rewrite or publish.

    Returns:
        "rewrite" if QC failed and attempts < 2, "publish" if QC passed
    """
    if state.get("qc_passed"):
        return "publish"

    if state.get("qc_attempts", 0) >= 2:
        # Max retries reached, just publish
        logger.info(f"[{state['task_id']}] Max QC retries reached, proceeding to publish")
        return "publish"

    return "rewrite"


def is_failed(state: PipelineState) -> bool:
    """Check if pipeline has failed."""
    return state.get("status") == PipelineStage.FAILED


# =============================================================================
# Build LangGraph
# =============================================================================

def _build_pipeline_graph() -> StateGraph:
    """Build the LangGraph state machine."""
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node(PipelineStage.DOWNLOAD, node_download_video)
    graph.add_node(PipelineStage.SCRAPE_METADATA, node_scrape_metadata)
    graph.add_node(PipelineStage.ANALYZE, node_analyze_video)
    graph.add_node(PipelineStage.WRITE_ARTICLE, node_write_article)
    graph.add_node(PipelineStage.QC_CHECK, node_qc_check)
    graph.add_node(PipelineStage.REWRITE, node_rewrite_article)
    graph.add_node(PipelineStage.PUBLISH, node_publish_cms)

    # Set entry point
    graph.set_entry_point(PipelineStage.DOWNLOAD)

    # Define edges
    graph.add_edge(PipelineStage.DOWNLOAD, PipelineStage.SCRAPE_METADATA)
    graph.add_edge(PipelineStage.SCRAPE_METADATA, PipelineStage.ANALYZE)
    graph.add_edge(PipelineStage.ANALYZE, PipelineStage.WRITE_ARTICLE)
    graph.add_edge(PipelineStage.WRITE_ARTICLE, PipelineStage.QC_CHECK)

    # Conditional edge from QC_CHECK
    graph.add_conditional_edges(
        PipelineStage.QC_CHECK,
        should_rewrite,
        {
            "rewrite": PipelineStage.REWRITE,
            "publish": PipelineStage.PUBLISH
        }
    )

    # From REWRITE, go back to QC_CHECK for another round
    graph.add_edge(PipelineStage.REWRITE, PipelineStage.QC_CHECK)

    # PUBLISH leads to DONE
    graph.add_edge(PipelineStage.PUBLISH, END)

    return graph.compile()


# Create the compiled graph
_pipeline_graph = _build_pipeline_graph()


# =============================================================================
# Pipeline Runner
# =============================================================================

def run_pipeline(
    video_url: str,
    project_name: str = "default",
    task_id: str = None,
    seo_keywords: list[str] = None
) -> dict:
    """Run the complete video-to-blog pipeline.

    Args:
        video_url: URL of the video (TikTok or Instagram)
        project_name: Project name for path organization
        task_id: Optional task ID (auto-generated if not provided)
        seo_keywords: Optional list of SEO keywords

    Returns:
        Final pipeline state
    """
    import uuid

    if not task_id:
        task_id = str(uuid.uuid4())[:8]

    logger.info(f"[{task_id}] Starting pipeline for {video_url}")

    # Initialize state
    initial_state: PipelineState = {
        "task_id": task_id,
        "project_name": project_name,
        "status": PipelineStage.INIT,
        "video_url": video_url,
        "video_local_path": "",
        "video_gcs_path": "",
        "video_metadata": {},
        "analysis_result": {},
        "frame_timestamps": [],
        "frame_local_paths": [],
        "frame_gcs_paths": [],
        "article_markdown": "",
        "article_word_count": 0,
        "qc_result": None,
        "qc_attempts": 0,
        "qc_passed": False,
        "revision_needed": False,
        "cms_draft_url": "",
        "logs": [f"[{datetime.now(timezone.utc).isoformat()}] Pipeline started"],
        "errors": []
    }

    # Run the graph in a separate thread to avoid Playwright sync API conflicts in asyncio loop
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_pipeline_graph.invoke, initial_state)
        final_state = future.result()

    return final_state


def get_task_progress(task_id: str, project_name: str = "default") -> dict:
    """Get the progress of a pipeline task.

    Returns:
        Dict with progress percentage and stage status
    """
    stages = [
        PipelineStage.DOWNLOAD,
        PipelineStage.SCRAPE_METADATA,
        PipelineStage.ANALYZE,
        PipelineStage.WRITE_ARTICLE,
        PipelineStage.QC_CHECK,
        PipelineStage.REWRITE,
        PipelineStage.PUBLISH,
        PipelineStage.DONE
    ]

    completed = 0
    stage_status = {}

    for stage in stages:
        result = _load_stage_result(task_id, stage)
        if result:
            if result.get("status") == "completed":
                completed += 1
            stage_status[stage] = result.get("status", "unknown")
        else:
            stage_status[stage] = "pending"

    return {
        "task_id": task_id,
        "progress": completed / len(stages),
        "stage_status": stage_status
    }


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="Run Sparki SEO Blog Pipeline")
    parser.add_argument("--video-url", required=True, help="Video URL (TikTok or Instagram)")
    parser.add_argument("--project", default="test_pipeline", help="Project name")
    parser.add_argument("--task-id", help="Task ID (auto-generated if not provided)")

    args = parser.parse_args()

    result = run_pipeline(
        video_url=args.video_url,
        project_name=args.project,
        task_id=args.task_id
    )

    print("\n" + "=" * 60)
    print("PIPELINE RESULT")
    print("=" * 60)
    print(f"Task ID: {result['task_id']}")
    print(f"Status: {result['status']}")
    print(f"QC Passed: {result.get('qc_passed', False)}")
    print(f"QC Attempts: {result.get('qc_attempts', 0)}")
    print(f"Article Words: {result.get('article_word_count', 0)}")
    print(f"Errors: {len(result.get('errors', []))}")

    if result.get("errors"):
        print("\nErrors:")
        for err in result["errors"]:
            print(f"  - {err}")

    print("\nLogs:")
    for log in result.get("logs", []):
        print(f"  {log}")