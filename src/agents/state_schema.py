"""State schema definitions for LangGraph pipeline.

All type definitions are based on InterfaceContracts.md.
Import these types in all nodes to ensure consistency.
"""

from typing import TypedDict, NotRequired, Callable


class VideoMetadata(TypedDict):
    video_id: str
    video_title: str
    video_description: str
    video_duration: float
    video_thumbnail_url: str
    video_url: str  # Original video URL (e.g., https://www.instagram.com/p/XXX/)
    published_at: str
    author_id: str
    author_name: str
    author_url: str  # Creator's profile URL
    author_avatar_url: str
    likes: int
    views: int
    saves: int
    shares: int
    comments: int
    followers: int
    following: int


class KeyMoment(TypedDict):
    timestamp: float
    description: str
    importance: str  # high | medium | low
    reason: str


class VideoAnalysisResult(TypedDict):
    narrative_structure: str
    key_moments: list[KeyMoment]
    subtitle_summary: str
    music_description: str
    visual_highlights: list[str]
    rhythm_analysis: str
    pacing_notes: str
    recommended_timestamps: list[float]
    extracted_keywords: list[str]
    raw_analysis: str


class Issue(TypedDict):
    location: str
    original: str
    problem: str
    suggestion: str
    revised: str | None


class DimensionResult(TypedDict):
    dimension: str
    score: float
    issues: list[Issue]
    suggestions: list[str]


class QCResult(TypedDict):
    passed: bool
    overall_score: float
    dimensions: list[DimensionResult]
    checked_at: str


class PipelineState(TypedDict):
    """Main state object passed through all LangGraph nodes."""

    # Task info
    task_id: str
    project_name: str
    status: str  # pending | running | done | failed | retry

    # Video
    video_url: str
    video_local_path: str
    video_gcs_path: str

    # Metadata
    video_metadata: VideoMetadata

    # Analysis
    analysis_result: VideoAnalysisResult
    frame_timestamps: list[float]

    # Frames
    frame_local_paths: list[str]
    frame_gcs_paths: list[str]

    # Article
    article_markdown: str
    article_word_count: int

    # QC & Revision
    qc_result: QCResult | None
    qc_attempts: int
    qc_passed: bool
    revision_needed: bool

    # Publish
    cms_draft_url: str

    # Logs
    logs: list[str]
    errors: list[str]

    # Progress callback: Callable[[float, str, str], None]
    # Signature: callback(progress: float, stage: str, message: str)
    progress_callback: NotRequired["Callable[[float, str, str], None]"] | None