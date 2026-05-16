"""Data models for Master Agent."""

from typing import TypedDict


class ChatMessage(TypedDict):
    """A single chat message."""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str
    attachments: list[str] | None


class ConversationContext(TypedDict):
    """Conversation context for a session."""
    session_id: str
    messages: list[ChatMessage]
    current_project: str | None
    api_configured: bool


class TaskStatus(TypedDict):
    """Status of a single pipeline task."""
    task_id: str
    project_id: str
    video_url: str
    creator_handle: str
    status: str  # "pending" | "downloading" | "analyzing" | "writing" | "qc" | "publishing" | "done" | "failed"
    progress: float  # 0.0 - 1.0
    current_stage: str
    qc_passed: bool | None
    cms_pushed: bool
    error: str | None
    started_at: str
    completed_at: str | None


class Case(TypedDict):
    """A case (video article generation task)."""
    case_id: str
    video_url: str
    creator_handle: str
    created_at: str
    task_ids: list[str]
    article_paths: list[str]
    cms_pushed: bool
    cms_entry_id: str | None


class Project(TypedDict):
    """A project containing multiple cases."""
    project_id: str
    name: str
    created_at: str
    updated_at: str
    video_urls: list[str]
    task_ids: list[str]
    current_status: str  # "active" | "completed" | "archived"


class IntentResult(TypedDict):
    """Result of intent classification."""
    intent: str
    video_urls: list[str]
    is_batch: bool
    raw_query: str