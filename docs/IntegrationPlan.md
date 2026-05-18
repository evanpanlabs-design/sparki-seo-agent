# Sparki GUI 与后端集成方案

## 概述

本文档定义前端（HTML GUI）如何与后端（Python pipeline）通信，实现可验证的完整流程。

**核心原则**：前端可微调，后端不改。后端已跑通，前端通过标准化接口接入。

---

## 一、架构设计

```
┌─────────────────┐      HTTP/REST       ┌──────────────────┐
│   sparki_gui.html   │ ◄───────────────► │   Flask API Server │
│   (Frontend)        │                   │   (Backend)        │
│                     │  SSE/polling      │                  │
│   - AI Chat        │ ◄───────────────► │  - PipelinePool  │
│   - Video Preview  │                   │  - TaskHandle    │
│   - Blog Preview   │                   │  - run_pipeline  │
│   - Log Viewer    │                   │                  │
│   - Settings      │                   │                  │
└─────────────────┘                   └──────────────────┘
```

### 通信方式
- **前端主动请求**：fetch API 调用 REST API
- **后端推送状态**：Server-Sent Events (SSE) 实现实时更新
- **轮询备选**：如果 SSE 复杂，可用简单轮询（每 2 秒）

---

## 二、后端 API 设计

### 2.1 启动 API Server

在 `src/agents/master/api_server.py` 中实现：

```python
"""Sparki REST API Server for GUI integration."""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from src.agents.pipeline_pool import get_pipeline_pool, TaskHandle
from src.config import get_settings

app = Flask(__name__)
CORS(app)
logger = logging.getLogger(__name__)

# SSE clients for real-time updates
_sse_clients: dict[str, list] = {}

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
            {
                "task_id": t.task_id,
                "video_url": t.video_url,
                "project_name": t.project_name,
                "status": t.status,
                "progress": t.progress,
                "current_stage": t.current_stage,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
                "error": t.error,
            }
            for t in tasks
        ]
    })


@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    """Get single task details."""
    pool = get_pipeline_pool()
    task = pool.get_status(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "task_id": task.task_id,
        "video_url": task.video_url,
        "project_name": task.project_name,
        "status": task.status,
        "progress": task.progress,
        "current_stage": task.current_stage,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error": task.error,
        "result": task.result,
    })


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

    # Logs stored in data/{project}/logs/{task_id}.log
    logs = _read_task_logs(task.project_name, task_id)
    return jsonify({"logs": logs})


@app.route("/api/settings", methods=["GET"])
def get_settings_api():
    """Get current settings (mask sensitive values)."""
    settings = get_settings()
    return jsonify({
        "gcp_project_id": settings.GCP_PROJECT_ID,
        "gcs_bucket": settings.GCS_BUCKET_NAME,
        "gemini_model": settings.GEMINI_MODEL,
        "api_key": "***" if settings.API_KEY else "",
        "api_url": settings.API_URL,
        "model_name": settings.MODEL_NAME,
        "contentful_space_id": settings.CONTENTFUL_SPACE_ID,
        "contentful_env": settings.CONTENTFUL_ENV,
        "contentful_access_token": "***" if settings.CONTENTFUL_ACCESS_TOKEN else "",
    })


@app.route("/api/settings", methods=["POST"])
def save_settings_api():
    """Save settings (writes to .env file)."""
    data = request.get_json()

    # Update environment variables
    updates = {}
    for key in ["GCP_PROJECT_ID", "GCS_BUCKET_NAME", "GEMINI_MODEL",
                "API_KEY", "API_URL", "MODEL_NAME",
                "CONTENTFUL_SPACE_ID", "CONTENTFUL_ENV", "CONTENTFUL_ACCESS_TOKEN"]:
        if key.lower() in data or key in data:
            val = data.get(key) or data.get(key.lower()) or ""
            updates[key] = val

    if updates:
        _save_env_updates(updates)

    return jsonify({"success": True})


@app.route("/api/tasks/<task_id>/stream")
def task_stream(task_id: str):
    """SSE endpoint for real-time task updates."""
    def generate():
        client_id = str(uuid.uuid4())
        if task_id not in _sse_clients:
            _sse_clients[task_id] = []
        _sse_clients[task_id].append(client_id)

        try:
            pool = get_pipeline_pool()
            last_status = ""

            while True:
                task = pool.get_status(task_id)
                if not task:
                    yield f"event: error\ndata: Task not found\n\n"
                    break

                status_json = json.dumps({
                    "task_id": task.task_id,
                    "status": task.status,
                    "progress": task.progress,
                    "current_stage": task.current_stage,
                    "error": task.error,
                })
                yield f"event: status\ndata: {status_json}\n\n"

                if task.status in ("done", "failed", "cancelled"):
                    break

                import time
                time.sleep(1)
        finally:
            if task_id in _sse_clients:
                _sse_clients[task_id].remove(client_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"}
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _read_task_logs(project_name: str, task_id: str) -> list[str]:
    """Read logs from log file."""
    from src.storage.storage_paths import StoragePaths
    log_path = StoragePaths.local_logs_path(project_name, task_id)
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []


def _save_env_updates(updates: dict):
    """Update .env file with new values."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if not env_path.exists():
        env_path.touch()

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped:
            key = stripped.split("=")[0]
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in [l.split("=")[0] for l in new_lines if "=" in l]:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=True, threaded=True)
```

### 2.2 运行方式

```bash
cd e:/2027_GET_A_JOB/Get_An_AI_Job/视界Sparki/14_NewAgent
python -m src.agents.master.api_server
```

---

## 三、前端集成

### 3.1 API Client 模块

在 `sparki_gui.html` 底部添加：

```javascript
// ========== API Client ==========
const API_BASE = "http://localhost:5555/api";

const api = {
    async health() {
        const r = await fetch(`${API_BASE}/health`);
        return r.json();
    },

    async listTasks() {
        const r = await fetch(`${API_BASE}/tasks`);
        return r.json();
    },

    async getTask(taskId) {
        const r = await fetch(`${API_BASE}/tasks/${taskId}`);
        return r.json();
    },

    async createTask(videoUrl, projectName = "default") {
        const r = await fetch(`${API_BASE}/tasks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_url: videoUrl, project_name: projectName })
        });
        return r.json();
    },

    async cancelTask(taskId) {
        const r = await fetch(`${API_BASE}/tasks/${taskId}`, { method: "DELETE" });
        return r.json();
    },

    async getLogs(taskId) {
        const r = await fetch(`${API_BASE}/tasks/${taskId}/logs`);
        return r.json();
    },

    async getSettings() {
        const r = await fetch(`${API_BASE}/settings`);
        return r.json();
    },

    async saveSettings(settings) {
        const r = await fetch(`${API_BASE}/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(settings)
        });
        return r.json();
    },

    subscribeTask(taskId, callback) {
        const es = new EventSource(`${API_BASE}/tasks/${taskId}/stream`);
        es.addEventListener("status", (e) => {
            callback(JSON.parse(e.data));
        });
        es.addEventListener("error", (e) => {
            console.error("SSE error", e);
            es.close();
        });
        return es;
    }
};
```

### 3.2 任务提交流程

```javascript
// 发送按钮点击
async function sendMessage() {
    const input = document.getElementById("chatInput");
    const msg = input.value.trim();
    if (!msg) return;

    // 如果是URL，提交任务
    if (msg.includes("tiktok.com") || msg.includes("instagram.com")) {
        const result = await api.createTask(msg);
        if (result.task_id) {
            addChatEntry(`> 已提交任务: ${result.task_id}`, "assistant");
            // 启动SSE监听
            subscribeToTask(result.task_id);
        }
    } else {
        addChatEntry(`> 命令 ${msg} 已收到`, "assistant");
    }

    input.value = "";
}

// 订阅任务更新
function subscribeToTask(taskId) {
    const es = api.subscribeTask(taskId, (data) => {
        updateTaskProgress(data.task_id, data.progress, data.current_stage, data.status);
        if (data.status === "done" || data.status === "failed") {
            es.close();
        }
    });
}
```

### 3.3 视频预览（从本地文件读取）

```javascript
async function loadVideoPreview(taskId) {
    const task = await api.getTask(taskId);
    if (!task || !task.result) return;

    const videoPath = task.result.video_local_path;
    // 转换为 file:// URL
    const fileUrl = "file:///" + videoPath.replace(/\\/g, "/");

    document.querySelector(".video-placeholder").innerHTML = `
        <video controls src="${fileUrl}"></video>
    `;
}
```

### 3.4 Blog 预览

```javascript
async function loadBlogPreview(taskId) {
    const task = await api.getTask(taskId);
    if (!task || !task.result) return;

    const articleMarkdown = task.result.article_markdown;
    document.querySelector(".blog-excerpt").innerHTML = marked.parse(articleMarkdown);
}
```

---

## 四、验证清单

### Step 1: 启动后端
```bash
python -m src.agents.master.api_server
# 验证: curl http://localhost:5555/api/health
```

### Step 2: 提交任务
```bash
curl -X POST http://localhost:5555/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"video_url":"https://www.tiktok.com/@user/video/123","project_name":"default"}'
```

### Step 3: 检查任务状态
```bash
curl http://localhost:5555/api/tasks
```

### Step 4: 打开前端
在浏览器中打开 `sparki_gui.html`，确认能连接到 API（跨域需 CORS 支持）。

---

## 五、文件清单

| 文件 | 作用 | 状态 |
|------|------|------|
| `src/agents/master/api_server.py` | 新增 REST API | 待创建 |
| `src/agents/master/sparki_gui.html` | 前端 GUI | 已创建 |
| `src/agents/pipeline.py` | 后端 pipeline | 已跑通 |
| `src/agents/master/pipeline_pool.py` | 任务池管理 | 已跑通 |
| `src/config.py` | 配置管理 | 已跑通 |

---

## 六、Settings 配置项对照

| 前端字段 | 后端 Env 变量 | 说明 |
|----------|---------------|------|
| GCP Project ID | `GCP_PROJECT_ID` | Google Cloud 项目 |
| GCS Bucket | `GCS_BUCKET_NAME` | 存储桶名 |
| Gemini 模型 | `GEMINI_MODEL` | Gemini 模型名 |
| API Key | `API_KEY` | 自定义 API Key |
| API URL | `API_URL` | API 端点 |
| 模型名称 | `MODEL_NAME` | LLM 模型名 |
| Contentful Space ID | `CONTENTFUL_SPACE_ID` | CMS Space |
| Contentful Environment | `CONTENTFUL_ENV` | 环境 |
| Access Token | `CONTENTFUL_ACCESS_TOKEN` | 访问令牌 |

---

## 七、注意事项

1. **跨域 CORS**：Flask 应用已启用 CORS，前端可直接访问
2. **视频路径**：Windows 文件路径需转换 `\` → `/` 前缀加 `file:///`
3. **SSE 兼容**：IE 不支持 SSE，需降级为轮询
4. **状态持久化**：任务状态在内存中，API Server 重启后丢失