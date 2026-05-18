# Frontend Development Plan - Node by Node Connection

## Overview

The frontend development follows a **"verify one node, then add next"** approach, mirroring the pipeline development methodology used to build the backend. Each frontend feature is validated end-to-end before adding complexity.

**Core Principle**: Each phase produces a working, testable deliverable. We never stack unverified features on top of each other.

---

## Phase 0: Environment Setup

### Goal: Verify the API server and a simple static page can communicate

**Backend**:
```bash
python -m src.agents.master.api_server
# Runs on http://localhost:5555
# Endpoints: /api/health, /api/tasks, /api/tasks/<id>
```

**Frontend**:
- Simple HTML file opened directly in browser
- No build step, no framework
- Vanilla JS calling REST API

**Verification**:
1. `curl http://localhost:5555/api/health` → `{"status": "ok"}`
2. Open HTML file in browser, see "Connected" status

---

## Phase 1: Task Submission + Status Polling

### Goal: URL input → submit task → see progress update

**What to build**:
- Single URL input field
- Submit button
- Status card showing: task_id, stage, progress (%), status badge
- Poll `/api/tasks/<task_id>` every 2 seconds

**User Flow**:
1. User pastes TikTok/Instagram URL
2. Clicks "Submit"
3. Task ID appears immediately
4. Progress bar updates every 2s
5. When status = "done" or "failed", polling stops

**API endpoints used**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tasks` | POST | Submit new task with `{"video_url": "...", "project_name": "default"}` |
| `/api/tasks/<task_id>` | GET | Poll for status, progress, current_stage |

**Verification**:
- Submit `https://www.tiktok.com/@annntastic/video/7625836931292630303`
- See `current_stage` change from "DOWNLOAD" → "SCRAPE_METADATA" → "ANALYZE" → ...
- See `progress` go from 0.0 → 1.0
- See `status` go from "running" → "done"

**Deliverable**:
`frontend/v1_task_submit.html` — single working HTML file with one URL input and status display.

---

## Phase 2: Log Output Display

### Goal: Show real-time text log of what the pipeline is doing

**What to add**:
- Log panel below the status card
- GET `/api/tasks/<task_id>/logs` every 2s
- Display logs as a scrolling list, newest at bottom
- Auto-scroll to latest entry

**User Flow**:
1. Submit task
2. Log panel fills with entries like:
   ```
   [12:42:30] Task submitted: https://...
   [12:42:35] Download started: 12MB video
   [12:42:40] Download complete
   [12:42:45] Scraping metadata...
   ```

**API endpoints used**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tasks/<task_id>/logs` | GET | Returns `{"logs": ["line1", "line2", ...]}` |

**Verification**:
- Same test URL
- Log entries appear in real-time as pipeline progresses
- No "stale" logs — they update every poll cycle

**Deliverable**:
`frontend/v2_with_logs.html` — extends Phase 1, adds scrolling log panel.

---

## Phase 3: SSE Real-Time Updates

### Goal: Replace polling with Server-Sent Events for instant updates

**What to change**:
- Replace 2-second polling with SSE connection to `/api/tasks/<task_id>/stream`
- SSE pushes `event: status` with JSON payload on every progress change
- No polling, instant visual feedback

**Why upgrade**:
- Polling misses rapid progress changes (a node can complete in <1s)
- SSE pushes immediately when `progress_callback` fires in the backend

**User Flow** (unchanged visual, instant updates):
1. Submit task
2. SSE connection established
3. Every progress_callback from backend → instant UI update
4. No more "stale" 2-second gaps

**API endpoint**:
| Endpoint | Purpose |
|----------|---------|
| `/api/tasks/<task_id>/stream` | SSE stream, emits `event: status` with JSON `{task_id, status, progress, current_stage, error}` |

**Verification**:
- Submit video and watch progress update within milliseconds of backend changes
- Should feel "instant" compared to Phase 1-2

**Deliverable**:
`frontend/v3_with_sse.html` — extends Phase 2, replaces polling with SSE.

---

## Phase 4: AI Chat Panel

### Goal: Add conversational AI assistant alongside task display

**What to add**:
- AI Chat panel (right side or below)
- Text input for conversational commands
- POST messages to backend (no LLM integration yet — simulate response)
- Display chat history (user message + AI response)

**User Flow**:
1. User types "show status" in AI panel
2. AI responds with current task summary
3. Or types "help" → AI responds with command list

**Note**: This phase does NOT require a working LLM. We simulate AI responses to verify the UI pattern works. The real LLM integration comes later.

**API endpoints used**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Send `{"message": "...", "task_id": "..."}`, receive `{"response": "..."}` |

**Verification**:
- Chat history scrolls properly
- Input field clears on submit
- AI response appears below user message

**Deliverable**:
`frontend/v4_with_chat.html` — extends Phase 3, adds AI chat panel.

---

## Phase 5: File Browser (Output Files)

### Goal: Auto-detect and display pipeline output files grouped by task

**What to add**:
- File Browser panel (left side, below logs)
- Automatically scan `data/Sparki_SEO_Blog_Agent_V2/default/pipeline_status/` for output files
- Group by task_id
- Show: video file (.mp4), frames (.jpg), article (.md)
- Click to open in file explorer / default app

**Detection approach**:
- Read `*_publish.json` for CMS URL
- Read `*_write_article.json` for article_path
- Read `*_extract_frames.json` for frame_paths

**User Flow**:
1. Task completes
2. File Browser populates with Video + Frames + Article icons
3. User clicks "📄 Article.md" → opens in default editor
4. User clicks "🎬 video.mp4" → opens in default player

**API endpoint**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/files` | GET | Returns all detected output files grouped by task_id |

**Verification**:
- After Phase 1 task completes, file list appears
- Each file type has correct icon
- "Open" action launches correct application

**Deliverable**:
`frontend/v5_with_files.html` — extends Phase 4, adds file browser panel.

---

## Phase 6: Visual Polish + Multi-Task

### Goal: Full UI with visual design and multiple concurrent tasks

**What to add**:
- Three-column layout (left: logs + files, right: AI chat)
- Proper color scheme (#4A83F9 brand blue)
- Draggable splitters
- Multiple task tabs
- AUTO/MANUAL publish mode toggle (future)
- Settings modal (GCP/GCS/Gemini/Contentful config)

**Visual Layout** (from VisualizationDesign.md):
```
┌─────────────────────────────────────────────────────────────────┐
│ Header: "SPARKI SEO BLOG AGENT V2" + mode toggle               │
├───────────────────────────┬─────────────────────────────────────┤
│ LEFT (40%)                │ RIGHT (60%)                        │
│ ┌─────────────────────┐   │ ┌─────────────────────────────────┐ │
│ │ AI Chat              │   │ │ Blog Preview                    │ │
│ │ (conversation)       │   │ │ (markdown render)                │ │
│ └─────────────────────┘   │ └─────────────────────────────────┘ │
│ ┌─────────────────────┐   │ ┌─────────────────────────────────┐ │
│ │ Progress + Log        │   │ │ Video Preview                    │ │
│ │ (live updates)       │   │ │ (thumbnail + metadata)           │ │
│ └─────────────────────┘   │ └─────────────────────────────────┘ │
└───────────────────────────┴─────────────────────────────────────┘
```

**Deliverable**:
`frontend/sparki_gui_final.html` — full-featured single-file HTML GUI.

---

## Phase 7: Settings Panel + Config Persistence

### Goal: Allow user to configure API keys and settings from UI

**What to add**:
- Settings modal (Gear icon → opens modal)
- Fields for: LLM API URL/Key, GCP Project, GCS Bucket, Contentful credentials
- POST to `/api/settings` to save
- Settings stored in `.env` file on backend

**User Flow**:
1. Click gear icon
2. Settings modal opens
3. Edit config fields
4. Click "Save"
5. Backend writes to `.env`

**API endpoints**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/settings` | GET | Returns current config (API keys masked) |
| `/api/settings` | POST | Save new config values |

**Verification**:
- Get settings → see masked API keys (`***`)
- Change one value → POST → verify `.env` updated
- New pipeline uses updated credentials

---

## Node-to-Phase Mapping

| Phase | Frontend Feature | Status | Notes |
|-------|------------------|--------|-------|
| 0 | API server + health check | Required before start | Verify backend reachable |
| 1 | URL Submit + Status Polling | **Start here** | Simplest complete user flow |
| 2 | Log Output Display | After Phase 1 | Adds visibility |
| 3 | SSE Real-Time Updates | After Phase 2 | Replaces polling |
| 4 | AI Chat Panel | After Phase 3 | Chat UI pattern |
| 5 | File Browser | After Phase 4 | Auto-detect outputs |
| 6 | Visual Polish | After Phase 5 | Layout + styling |
| 7 | Settings Panel | After Phase 6 | Config from UI |

---

## Development Workflow

### Each Phase:
1. **Write the HTML** for the phase feature
2. **Run the backend** (`python -m src.agents.master.api_server`)
3. **Open HTML file** in browser
4. **Test with real URL**: `https://www.tiktok.com/@annntastic/video/7625836931292630303`
5. **Verify** all interactions work
6. **Commit** working version before moving to next phase

### No Stacking
- Phase 1 must work independently (no reliance on Phase 2+ features)
- Phase 2 extends Phase 1 but doesn't break it
- If Phase 3 breaks Phase 1-2, fix Phase 3 before continuing

### Testing Protocol
Each phase must pass the same verification test:
```bash
# Start API server
python -m src.agents.master.api_server

# In browser console, test:
fetch('http://localhost:5555/api/health')
# → {status: "ok"}

# Submit task
fetch('http://localhost:5555/api/tasks', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    video_url: 'https://www.tiktok.com/@annntastic/video/7625836931292630303',
    project_name: 'default'
  })
})
# → {task_id: "..."}

# Poll status
setInterval(() => {
  fetch('http://localhost:5555/api/tasks/<task_id>')
    .then(r => r.json())
    .then(d => console.log(d.status, d.current_stage, d.progress))
}, 1000)
```

---

## Frontend File Structure

```
frontend/
├── v0_api_health.html        # Phase 0: API health check
├── v1_task_submit.html        # Phase 1: URL submit + status polling
├── v2_with_logs.html          # Phase 2: + log output display
├── v3_with_sse.html            # Phase 3: + SSE real-time updates
├── v4_with_chat.html           # Phase 4: + AI chat panel
├── v5_with_files.html         # Phase 5: + file browser
├── v6_full_layout.html        # Phase 6: visual polish, full layout
├── v7_settings.html           # Phase 7: settings panel + config
└── sparki_gui.html            # Final: full-featured (all phases merged)
```

---

## Backend API Reference

| Method | Endpoint | Request Body | Response |
|--------|----------|--------------|----------|
| GET | `/api/health` | - | `{status: "ok", timestamp: "..."}` |
| POST | `/api/tasks` | `{video_url, project_name}` | `{task_id: "...", status: "pending"}` |
| GET | `/api/tasks` | - | `{tasks: [TaskHandle, ...]}` |
| GET | `/api/tasks/<task_id>` | - | `{task_id, video_url, project_name, status, progress, current_stage, started_at, completed_at, error, result}` |
| DELETE | `/api/tasks/<task_id>` | - | `{success: bool}` |
| GET | `/api/tasks/<task_id>/logs` | - | `{logs: [string, ...]}` |
| GET | `/api/tasks/<task_id>/stream` | - | SSE `event: status` with JSON payload |
| GET | `/api/settings` | - | Config with masked API keys |
| POST | `/api/settings` | Config object | `{success: true}` |

---

## Prerequisites Before Starting Frontend Development

1. [ ] `python -m src.agents.master.api_server` starts on port 5555
2. [ ] `curl http://localhost:5555/api/health` returns `{"status": "ok"}`
3. [ ] `python -m src.agents.master.cli` runs pipeline end-to-end without errors
4. [ ] `configs/config.local.yaml` has valid credentials for at least one video platform

**Verification command**:
```bash
# Terminal 1: Start API server
python -m src.agents.master.api_server

# Terminal 2: Test from new terminal
curl http://localhost:5555/api/health
# Expected: {"status":"ok","timestamp":"..."}

# Then submit a task from browser or curl:
curl -X POST http://localhost:5555/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"video_url":"https://www.tiktok.com/@annntastic/video/7625836931292630303","project_name":"default"}'
# Expected: {"task_id":"...","status":"pending"}
```