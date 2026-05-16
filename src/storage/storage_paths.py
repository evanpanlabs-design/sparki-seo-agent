"""Storage path construction utilities.

Ensures consistent paths across local and GCS storage.
GCS prefix: gs://{bucket}/Sparki_SEO_Blog_Agent_V2/{project_name}/
Local prefix: {data_root}/Sparki_SEO_Blog_Agent_V2/{project_name}/
"""

from pathlib import Path
from typing import ClassVar


class StoragePaths:
    """Path construction utility for consistent local/GCS paths."""

    BASE_PREFIX: ClassVar[str] = "Sparki_SEO_Blog_Agent_V2"

    @classmethod
    def local_base(cls, data_root: str, project_name: str) -> Path:
        return Path(data_root) / cls.BASE_PREFIX / project_name

    @classmethod
    def gcs_base(cls, bucket_name: str, project_name: str) -> str:
        return f"gs://{bucket_name}/{cls.BASE_PREFIX}/{project_name}"

    # === Video paths ===

    @classmethod
    def local_video_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "raw" / f"{task_id}.mp4"

    @classmethod
    def gcs_video_path(cls, bucket_name: str, project_name: str, task_id: str) -> str:
        return f"{cls.gcs_base(bucket_name, project_name)}/videos/{task_id}.mp4"

    # === Metadata paths ===

    @classmethod
    def local_metadata_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "metadata" / f"{task_id}_meta.json"

    # === Analysis paths ===

    @classmethod
    def local_analysis_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "analysis" / f"{task_id}_analysis.json"

    # === Frame paths ===

    @classmethod
    def local_frames_dir(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "frames" / task_id

    @classmethod
    def gcs_frames_dir(cls, bucket_name: str, project_name: str, task_id: str) -> str:
        return f"{cls.gcs_base(bucket_name, project_name)}/frames/{task_id}"

    @classmethod
    def local_frame_path(cls, data_root: str, project_name: str, task_id: str, timestamp: float) -> Path:
        """Generate frame path with HH-MM-SS timestamp format."""
        frame_name = f"frame_{cls._format_timestamp(timestamp)}.jpg"
        return cls.local_frames_dir(data_root, project_name, task_id) / frame_name

    @classmethod
    def gcs_frame_path(cls, bucket_name: str, project_name: str, task_id: str, timestamp: float) -> str:
        """Generate GCS frame path with HH-MM-SS timestamp format."""
        frame_name = f"frame_{cls._format_timestamp(timestamp)}.jpg"
        return f"{cls.gcs_frames_dir(bucket_name, project_name, task_id)}/{frame_name}"

    # === Article paths ===

    @classmethod
    def local_article_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "articles" / f"{task_id}_article.md"

    @classmethod
    def gcs_article_path(cls, bucket_name: str, project_name: str, task_id: str) -> str:
        return f"{cls.gcs_base(bucket_name, project_name)}/articles/{task_id}.md"

    # === QC paths ===

    @classmethod
    def local_qc_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "qc" / f"{task_id}_qc.json"

    # === Log paths ===

    @classmethod
    def local_log_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "logs" / f"{task_id}.log"

    @classmethod
    def local_error_log_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "logs" / f"{task_id}_error.log"

    # === Helpers ===

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Convert seconds to HH-MM-SS format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}-{minutes:02d}-{secs:02d}"

    @classmethod
    def ensure_dirs(cls, path: Path) -> None:
        """Ensure parent directory exists."""
        path.parent.mkdir(parents=True, exist_ok=True)