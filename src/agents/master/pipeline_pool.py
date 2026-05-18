"""Pipeline pool for managing concurrent pipeline executions."""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class TaskHandle:
    """Handle to a submitted pipeline task."""
    task_id: str
    video_url: str
    project_name: str
    status: str = "pending"
    progress: float = 0.0
    current_stage: str = ""
    started_at: str = ""
    completed_at: str | None = None
    error: str | None = None
    result: dict | None = None
    future: Future | None = None


class PipelinePool:
    """Manages multiple pipeline sub-agent executions with concurrency control."""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._tasks: dict[str, TaskHandle] = {}
        self._lock = threading.Lock()
        self._interval_seconds = 10
        self._last_submit_time = 0.0

    def submit(
        self,
        video_url: str,
        project_name: str,
        task_id: str | None = None,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> str:
        """Submit a pipeline task. Returns task_id."""
        task_id = task_id or str(uuid.uuid4())

        with self._lock:
            self._enforce_interval()
            self._last_submit_time = time.time()

            handle = TaskHandle(
                task_id=task_id,
                video_url=video_url,
                project_name=project_name,
                status="pending",
                started_at=datetime.now(timezone.utc).isoformat()
            )
            self._tasks[task_id] = handle

        logger.info(f"Submitted task {task_id} for {video_url}")

        def run_pipeline():
            try:
                from src.agents.pipeline import run_pipeline
                from src.storage.storage_paths import StoragePaths
                import logging

                # Set up file handler so logs are written to disk
                log_path = StoragePaths.local_log_path("data", project_name, task_id)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(log_path, encoding="utf-8")
                fh.setLevel(logging.INFO)
                formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                fh.setFormatter(formatter)
                root_logger = logging.getLogger()
                root_logger.addHandler(fh)

                try:
                    def progress_callback(progress: float, stage: str, message: str):
                        self._update_status(task_id, "running", progress, stage)

                    self._update_status(task_id, "running", 0.0, "download")
                    result = run_pipeline(
                        video_url=video_url,
                        project_name=project_name,
                        task_id=task_id,
                        progress_callback=progress_callback
                    )
                    self._update_status(
                        task_id,
                        "done" if result.get("status") == "done" else "failed",
                        1.0,
                        "done",
                        result=result,
                        error=result.get("errors", [None])[0] if result.get("errors") else None
                    )
                finally:
                    root_logger.removeHandler(fh)
                    fh.close()
            except Exception as e:
                logger.error(f"Pipeline task {task_id} failed: {e}")
                self._update_status(task_id, "failed", 0.0, "error", error=str(e))

        handle.future = self._executor.submit(run_pipeline)
        return task_id

    def submit_batch(
        self,
        video_urls: list[str],
        project_name: str,
        progress_callback: Callable[[str, float, str], None] | None = None
    ) -> list[str]:
        """Submit multiple pipeline tasks with interval delays. Returns list of task_ids."""
        task_ids = []
        for i, video_url in enumerate(video_urls):
            task_id = str(uuid.uuid4())
            task_ids.append(task_id)

            with self._lock:
                self._enforce_interval()
                self._last_submit_time = time.time()

                handle = TaskHandle(
                    task_id=task_id,
                    video_url=video_url,
                    project_name=project_name,
                    status="pending",
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                self._tasks[task_id] = handle

            def run_pipeline(url=video_url, tid=task_id):
                try:
                    from src.agents.pipeline import run_pipeline
                    self._update_status(tid, "running", 0.0, "download")
                    result = run_pipeline(
                        video_url=url,
                        project_name=project_name,
                        task_id=tid,
                        progress_callback=progress_callback
                    )
                    self._update_status(
                        tid,
                        "done" if result.get("status") == "done" else "failed",
                        1.0,
                        "done",
                        result=result,
                        error=result.get("errors", [None])[0] if result.get("errors") else None
                    )
                except Exception as e:
                    logger.error(f"Pipeline task {tid} failed: {e}")
                    self._update_status(tid, "failed", 0.0, "error", error=str(e))

            self._executor.submit(run_pipeline)

            if i < len(video_urls) - 1:
                time.sleep(self._interval_seconds)

        logger.info(f"Submitted batch of {len(video_urls)} tasks")
        return task_ids

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        with self._lock:
            handle = self._tasks.get(task_id)
            if not handle:
                return False

            if handle.future and not handle.future.done():
                handle.future.cancel()
                handle.status = "cancelled"
                handle.completed_at = datetime.now(timezone.utc).isoformat()
                logger.info(f"Cancelled task {task_id}")
                return True

            return False

    def cancel_all(self) -> int:
        """Cancel all running tasks. Returns count of cancelled tasks."""
        count = 0
        with self._lock:
            for task_id, handle in self._tasks.items():
                if handle.future and not handle.future.done():
                    handle.future.cancel()
                    handle.status = "cancelled"
                    handle.completed_at = datetime.now(timezone.utc).isoformat()
                    count += 1
        logger.info(f"Cancelled {count} tasks")
        return count

    def get_status(self, task_id: str) -> TaskHandle | None:
        """Get current status of a task."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_status(self) -> list[TaskHandle]:
        """Get status of all tasks."""
        with self._lock:
            return list(self._tasks.values())

    def _update_status(
        self,
        task_id: str,
        status: str,
        progress: float,
        current_stage: str,
        result: dict | None = None,
        error: str | None = None
    ) -> None:
        """Update task status (thread-safe)."""
        with self._lock:
            handle = self._tasks.get(task_id)
            if handle:
                handle.status = status
                handle.progress = progress
                handle.current_stage = current_stage
                if result:
                    handle.result = result
                if error:
                    handle.error = error
                if status in ("done", "failed", "cancelled"):
                    handle.completed_at = datetime.now(timezone.utc).isoformat()

    def _enforce_interval(self) -> None:
        """Enforce minimum interval between task submissions."""
        elapsed = time.time() - self._last_submit_time
        if elapsed < self._interval_seconds:
            sleep_time = self._interval_seconds - elapsed
            logger.debug(f"Enforcing {sleep_time:.1f}s interval")
            time.sleep(sleep_time)


# Global singleton
_pipeline_pool: PipelinePool | None = None


def get_pipeline_pool() -> PipelinePool:
    """Get the global pipeline pool instance."""
    global _pipeline_pool
    if _pipeline_pool is None:
        _pipeline_pool = PipelinePool()
    return _pipeline_pool