"""Conversation manager for Master Agent.

Handles chat history, context window, and session persistence.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation history and context for a Master Agent session."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)
        self.sessions_dir = self.data_root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        """Create a new conversation session. Returns session_id."""
        session_id = str(uuid.uuid4())
        session_path = self.sessions_dir / f"{session_id}.json"

        session_data = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "messages": [],
            "current_project": None,
            "api_configured": False
        }

        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Created new session: {session_id}")
        return session_id

    def load_session(self, session_id: str) -> dict | None:
        """Load a session by ID. Returns None if not found."""
        session_path = self.sessions_dir / f"{session_id}.json"
        if not session_path.exists():
            return None

        with open(session_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_message(self, session_id: str, role: str, content: str, attachments: list[str] | None = None) -> bool:
        """Add a message to the session. Returns True if successful."""
        session = self.load_session(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            return False

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attachments": attachments
        }

        session["messages"].append(message)

        session_path = self.sessions_dir / f"{session_id}.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        return True

    def get_recent_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get the most recent N messages for context."""
        session = self.load_session(session_id)
        if not session:
            return []

        messages = session.get("messages", [])
        return messages[-limit:] if len(messages) > limit else messages

    def set_current_project(self, session_id: str, project_name: str | None) -> bool:
        """Set the active project for this session."""
        session = self.load_session(session_id)
        if not session:
            return False

        session["current_project"] = project_name

        session_path = self.sessions_dir / f"{session_id}.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        return True

    def get_current_project(self, session_id: str) -> str | None:
        """Get the active project name for this session."""
        session = self.load_session(session_id)
        return session.get("current_project") if session else None

    def set_api_configured(self, session_id: str, configured: bool) -> bool:
        """Mark whether API has been configured."""
        session = self.load_session(session_id)
        if not session:
            return False

        session["api_configured"] = configured

        session_path = self.sessions_dir / f"{session_id}.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        return True

    def is_api_configured(self, session_id: str) -> bool:
        """Check if API is configured for this session."""
        session = self.load_session(session_id)
        return session.get("api_configured", False) if session else False

    def export_conversation(self, session_id: str, output_path: str | None = None) -> str:
        """Export full conversation to JSON file. Returns the path."""
        session = self.load_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(self.data_root / f"conversation_export_{timestamp}.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"Exported conversation to {output_path}")
        return output_path

    def import_conversation(self, input_path: str) -> str:
        """Import a conversation from JSON file. Returns new session_id."""
        with open(input_path, "r", encoding="utf-8") as f:
            imported_session = json.load(f)

        new_session_id = str(uuid.uuid4())
        imported_session["session_id"] = new_session_id
        imported_session["created_at"] = datetime.now(timezone.utc).isoformat()

        session_path = self.sessions_dir / f"{new_session_id}.json"
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(imported_session, f, ensure_ascii=False, indent=2)

        logger.info(f"Imported conversation as new session: {new_session_id}")
        return new_session_id

    def list_sessions(self) -> list[dict]:
        """List all sessions with summary info."""
        sessions = []
        for session_file in self.sessions_dir.glob("*.json"):
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "message_count": len(data.get("messages", [])),
                    "current_project": data.get("current_project")
                })
        return sorted(sessions, key=lambda x: x["created_at"], reverse=True)


# Global singleton instance
_conversation_manager: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    """Get the global conversation manager instance."""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager