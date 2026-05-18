"""Sparki REST API Server for GUI integration."""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from src.agents.master.pipeline_pool import get_pipeline_pool, TaskHandle
try:
    from src.config import get_config
    _settings = get_config()
except Exception:
    _settings = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# SSE clients for real-time updates
_sse_clients: dict[str, list] = {}
_sse_lock = threading.Lock()

# =============================================================================
# API Endpoints
# =============================================================================

@app.route("/api/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    """List all tasks."""
    pool = get_pipeline_pool()
    tasks = pool.get_all_status()
    return jsonify({
        "tasks": [
            _task_to_dict(t) for t in tasks
        ]
    })


@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    """Get single task details."""
    pool = get_pipeline_pool()
    task = pool.get_status(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(_task_to_dict(task))


@app.route("/api/tasks", methods=["POST"])
def create_task():
    """Submit a new pipeline task."""
    data = request.get_json()
    video_url = data.get("video_url")
    project_name = data.get("project_name", "default")

    if not video_url:
        return jsonify({"error": "video_url required"}), 400

    pool = get_pipeline_pool()
    task_id = pool.submit(
        video_url=video_url,
        project_name=project_name
    )

    return jsonify({"task_id": task_id, "status": "pending"})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def cancel_task(task_id: str):
    """Cancel a running task."""
    pool = get_pipeline_pool()
    success = pool.cancel(task_id)
    return jsonify({"success": success})


@app.route("/api/tasks/<task_id>/logs", methods=["GET"])
def get_task_logs(task_id: str):
    """Get logs for a specific task."""
    pool = get_pipeline_pool()
    task = pool.get_status(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    logs = _read_task_logs(task.project_name, task_id)
    return jsonify({"logs": logs})


@app.route("/api/settings", methods=["GET"])
def get_settings_api():
    """Get current settings (mask sensitive values)."""
    return jsonify({
        "gcp_project_id": _settings.get("GCP_PROJECT_ID", "") or "",
        "gcs_bucket": _settings.get("GCS_BUCKET_NAME", "") or "",
        "gemini_model": _settings.get("GEMINI_MODEL", "") or "",
        "api_key": "***" if _settings.get("API_KEY") else "",
        "api_url": _settings.get("API_URL", "") or "",
        "model_name": _settings.get("MODEL_NAME", "") or "",
        "contentful_space_id": _settings.get("CONTENTFUL_SPACE_ID", "") or "",
        "contentful_env": _settings.get("CONTENTFUL_ENV", "") or "",
        "contentful_access_token": "***" if _settings.get("CONTENTFUL_ACCESS_TOKEN") else "",
    })


@app.route("/api/settings", methods=["POST"])
def save_settings_api():
    """Save settings (writes to .env file)."""
    data = request.get_json()
    updates = {}

    for key in ["GCP_PROJECT_ID", "GCS_BUCKET_NAME", "GEMINI_MODEL",
                "API_KEY", "API_URL", "MODEL_NAME",
                "CONTENTFUL_SPACE_ID", "CONTENTFUL_ENV", "CONTENTFUL_ACCESS_TOKEN"]:
        camel_key = _snake_to_camel(key.lower())
        if key.lower() in data or key in data:
            val = data.get(key) or data.get(key.lower()) or ""
            updates[key] = val

    if updates:
        _save_env_updates(updates)

    return jsonify({"success": True})


@app.route("/api/tasks/<task_id>/stream")
def task_stream(task_id: str):
    """SSE endpoint for real-time task updates.

    Uses TaskHandle for current progress (written by progress_callback in subthread).
    Falls back to pipeline_status JSON files only when task is done.
    """
    def generate():
        client_id = str(uuid.uuid4())
        with _sse_lock:
            if task_id not in _sse_clients:
                _sse_clients[task_id] = []
            _sse_clients[task_id].append(client_id)

        last_emitted_progress = -1.0
        last_emitted_stage = None

        try:
            pool = get_pipeline_pool()

            while True:
                task = pool.get_status(task_id)
                if not task:
                    yield f"event: error\ndata: Task not found\n\n"
                    break

                # If task is done/failed/cancelled, read final state from JSON files for accuracy
                if task.status in ("done", "failed", "cancelled"):
                    stage_order = ["download", "scrape_metadata", "analyze",
                                   "write_article", "qc_check", "rewrite", "publish", "done"]
                    for stage in stage_order:
                        fp = _get_stage_result_path(task.project_name, task_id, stage)
                        if fp and fp.exists():
                            try:
                                with open(fp, "r", encoding="utf-8") as f:
                                    d = json.load(f)
                                if d.get("status") in ("completed", "failed"):
                                    status_json = json.dumps({
                                        "task_id": task_id,
                                        "status": "failed" if d.get("status") == "failed" else "done",
                                        "progress": d.get("progress", 1.0),
                                        "current_stage": stage,
                                        "error": d.get("error"),
                                    })
                                    yield f"event: status\ndata: {status_json}\n\n"
                                    break
                            except Exception:
                                pass
                    break

                # While running: emit if progress/stage changed
                current_progress = task.progress
                current_stage = task.current_stage or "pending"

                if (abs(current_progress - last_emitted_progress) > 0.04 or
                    current_stage != last_emitted_stage):
                    status_json = json.dumps({
                        "task_id": task_id,
                        "status": task.status,
                        "progress": float(current_progress),
                        "current_stage": current_stage,
                        "error": task.error,
                    })
                    yield f"event: status\ndata: {status_json}\n\n"
                    last_emitted_progress = current_progress
                    last_emitted_stage = current_stage

                import time
                time.sleep(0.5)
        finally:
            with _sse_lock:
                if task_id in _sse_clients:
                    try:
                        _sse_clients[task_id].remove(client_id)
                    except ValueError:
                        pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
        direct_passthrough=False
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _task_to_dict(task: TaskHandle) -> dict:
    """Convert TaskHandle to dict for JSON serialization."""
    d = {
        "task_id": task.task_id,
        "video_url": task.video_url,
        "project_name": task.project_name,
        "status": task.status,
        "progress": task.progress,
        "current_stage": task.current_stage,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error": task.error,
        "result": str(task.result) if task.result is not None else None,
    }
    # Ensure all values are JSON-serializable
    for key in list(d.keys()):
        try:
            import json
            json.dumps(d[key])
        except (TypeError, ValueError):
            d[key] = repr(d[key])
    return d


def _read_task_logs(project_name: str, task_id: str) -> list[str]:
    """Read logs from log file."""
    try:
        from src.storage.storage_paths import StoragePaths
        log_path = StoragePaths.local_log_path("data", project_name, task_id)
        if log_path and log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.warning(f"Could not read logs for {task_id}: {e}")
    return []


def _get_stage_result_path(project_name: str, task_id: str, stage: str) -> "Path | None":
    """Get path to pipeline_status stage result file."""
    try:
        from src.storage.storage_paths import StoragePaths
        base = StoragePaths.local_base("data", project_name)
        return base / "pipeline_status" / f"{task_id}_{stage}.json"
    except Exception:
        return None


def _save_env_updates(updates: dict):
    """Update .env file with new values."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if not env_path.exists():
        env_path.touch()

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    existing_keys = set()

    for line in lines:
        stripped = line.strip()
        if "=" in stripped:
            key = stripped.split("=", 1)[0]
            existing_keys.add(key)
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    logger.info(f"Updated .env with: {list(updates.keys())}")


def _snake_to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


if __name__ == "__main__":
    import os
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        os.environ.pop(key, None)

    logger.info("Starting Sparki API Server on port 5555 (waitress)...")
    from waitress import serve
    serve(app, host="0.0.0.0", port=5555)