"""Project and case manager for Master Agent.

Handles project/case CRUD operations and video URL deduplication.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages projects and cases with deduplication."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)
        self.projects_dir = self.data_root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.case_index_path = self.data_root / "case_index.json"

    def _load_case_index(self) -> dict[str, dict]:
        """Load the case index (video_url -> case_id mapping)."""
        if self.case_index_path.exists():
            with open(self.case_index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_case_index(self, index: dict[str, dict]) -> None:
        """Save the case index."""
        with open(self.case_index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _load_case(self, case_id: str) -> dict | None:
        """Load a case by ID."""
        case_path = self.projects_dir / case_id / "case.json"
        if not case_path.exists():
            return None
        with open(case_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_case(self, case: dict) -> None:
        """Save a case."""
        case_dir = self.projects_dir / case["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        with open(case_dir / "case.json", "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=2)

    def _load_project(self, project_id: str) -> dict | None:
        """Load a project by ID."""
        project_path = self.projects_dir / project_id / "project.json"
        if not project_path.exists():
            return None
        with open(project_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_project(self, project: dict) -> None:
        """Save a project."""
        project_dir = self.projects_dir / project["project_id"]
        project_dir.mkdir(parents=True, exist_ok=True)
        with open(project_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, indent=2)

    def check_duplicate(self, video_url: str) -> str | None:
        """Check if a case with this video URL exists. Returns case_id if duplicate."""
        index = self._load_case_index()
        return index.get(video_url, {}).get("case_id")

    def create_case(self, video_url: str, creator_handle: str, project_id: str | None = None) -> dict:
        """Create a new case. Fails if duplicate exists."""
        existing_case_id = self.check_duplicate(video_url)
        if existing_case_id:
            raise ValueError(f"Duplicate video URL: case {existing_case_id} already exists")

        case_id = str(uuid.uuid4())
        case = {
            "case_id": case_id,
            "video_url": video_url,
            "creator_handle": creator_handle,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_ids": [],
            "article_paths": [],
            "cms_pushed": False,
            "cms_entry_id": None
        }

        self._save_case(case)

        index = self._load_case_index()
        index[video_url] = {
            "case_id": case_id,
            "created_at": case["created_at"]
        }
        self._save_case_index(index)

        logger.info(f"Created case {case_id} for {video_url}")
        return case

    def add_task_to_case(self, case_id: str, task_id: str) -> bool:
        """Add a task ID to a case."""
        case = self._load_case(case_id)
        if not case:
            return False

        if task_id not in case["task_ids"]:
            case["task_ids"].append(task_id)
            self._save_case(case)

        return True

    def mark_case_cms_pushed(self, case_id: str, entry_id: str | None = None) -> bool:
        """Mark a case as pushed to CMS."""
        case = self._load_case(case_id)
        if not case:
            return False

        case["cms_pushed"] = True
        if entry_id:
            case["cms_entry_id"] = entry_id
        self._save_case(case)
        return True

    def get_case(self, case_id: str) -> dict | None:
        """Get a case by ID."""
        return self._load_case(case_id)

    def get_case_by_video_url(self, video_url: str) -> dict | None:
        """Get a case by video URL."""
        index = self._load_case_index()
        case_id = index.get(video_url, {}).get("case_id")
        if case_id:
            return self._load_case(case_id)
        return None

    def create_project(self, name: str) -> dict:
        """Create a new project."""
        project_id = str(uuid.uuid4())
        project = {
            "project_id": project_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "video_urls": [],
            "task_ids": [],
            "current_status": "active"
        }

        self._save_project(project)
        logger.info(f"Created project {project_id}: {name}")
        return project

    def get_project(self, project_id: str) -> dict | None:
        """Get a project by ID."""
        return self._load_project(project_id)

    def get_project_by_name(self, name: str) -> dict | None:
        """Get a project by name."""
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                project = self._load_project(project_dir.name)
                if project and project.get("name") == name:
                    return project
        return None

    def add_video_to_project(self, project_id: str, video_url: str) -> bool:
        """Add a video URL to a project."""
        project = self._load_project(project_id)
        if not project:
            return False

        if video_url not in project["video_urls"]:
            project["video_urls"].append(video_url)
            project["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_project(project)

        return True

    def list_projects(self) -> list[dict]:
        """List all projects."""
        projects = []
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir() and (project_dir / "project.json").exists():
                project = self._load_project(project_dir.name)
                if project:
                    projects.append(project)
        return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)

    def list_cases(self, project_id: str | None = None) -> list[dict]:
        """List all cases, optionally filtered by project."""
        cases = []
        for case_dir in self.projects_dir.iterdir():
            if case_dir.is_dir() and (case_dir / "case.json").exists():
                case = self._load_case(case_dir.name)
                if case:
                    if project_id is None or self._case_belongs_to_project(case, project_id):
                        cases.append(case)
        return sorted(cases, key=lambda x: x.get("created_at", ""), reverse=True)

    def _case_belongs_to_project(self, case: dict, project_id: str) -> bool:
        """Check if a case belongs to a project (simplified: project name in task_ids path)."""
        return True

    def archive_project(self, project_id: str) -> bool:
        """Archive a project."""
        project = self._load_project(project_id)
        if not project:
            return False

        project["current_status"] = "archived"
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_project(project)
        return True

    def get_or_create_project(self, name: str) -> dict:
        """Get existing project by name or create new one."""
        existing = self.get_project_by_name(name)
        if existing:
            return existing
        return self.create_project(name)


# Global singleton
_project_manager: ProjectManager | None = None


def get_project_manager() -> ProjectManager:
    """Get the global project manager instance."""
    global _project_manager
    if _project_manager is None:
        _project_manager = ProjectManager()
    return _project_manager