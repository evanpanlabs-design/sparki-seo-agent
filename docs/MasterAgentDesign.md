# Master Agent Design Document

## 1. Overview

The Master Agent is a **local-first, single-user conversational interface** that orchestrates the Sparki SEO Blog pipeline sub-agents. It provides natural language interaction for video content analysis and blog article generation.

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Master Agent (Main Process)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Conversation│  │  Intent     │  │  Project & Memory       │  │
│  │  Manager    │  │  Router     │  │  Manager                │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         │                │                     │                  │
│         └────────────────┼─────────────────────┘                  │
│                          │                                          │
│         ┌────────────────▼────────────────┐                        │
│         │      LangGraph Orchestrator    │                        │
│         └────────────────┬────────────────┘                        │
└─────────────────────────┼──────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Pipeline   │  │  Contentful  │  │   Memory     │
│   Sub-Agent  │  │  Publisher   │  │   (RAG)      │
│   (Pool)     │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## 2. Core Components

### 2.1 Conversation Manager

**Responsibilities:**
- Maintain short-term conversation context (last N messages)
- Store conversation history per session/project
- Manage user API credentials securely

**Data Structure:**
```python
class ConversationContext(TypedDict):
    session_id: str                    # UUID for this conversation
    messages: list[ChatMessage]        # Recent messages (last 50)
    current_project: str | None        # Active project name
    user_api_config: UserAPIConfig     # Encrypted API key storage

class ChatMessage(TypedDict):
    role: str                         # "user" | "assistant" | "system"
    content: str
    timestamp: str
    attachments: list[str] | None      # Video URLs etc.
```

**Implementation:**
- Use LangChain `ChatMessageHistory` for context window management
- SQLite for session persistence (encrypted credentials)
- Auto-export conversation on project completion

### 2.2 Intent Router

**Responsibilities:**
- Detect video URLs in natural language
- Classify single vs batch requests
- Route to appropriate handler (pipeline, query, settings)

**Intent Types:**
| Intent | Patterns | Action |
|--------|----------|--------|
| `VIDEO_SUBMIT` | "分析这个视频", "处理这个链接" | Trigger pipeline |
| `BATCH_SUBMIT` | "批量处理", "分析这些视频" | Trigger batch pipeline |
| `STATUS_QUERY` | "进度", "状态如何" | Return task status |
| `PROJECT_LIST` | "查看项目", "案例库" | List projects |
| `SETTINGS` | "配置", "API设置" | Open settings |
| `CONTENTFUL_PUSH` | "推送到CMS", "发布" | Trigger Contentful |
| `MEMORY_QUERY` | "之前做过", "记忆" | Query RAG |

**Batch Detection:**
```python
def detect_batch_intent(message: str) -> tuple[bool, list[str]]:
    """Detect if message contains multiple video URLs."""
    urls = extract_urls(message)
    is_batch = len(urls) > 1 or any(kw in message.lower() for kw in ["批量", "多个", "batch", "multiple"])
    return is_batch, urls
```

**Limits:**
- Max batch size: 10 URLs
- Min interval between pipelines: 10 seconds

### 2.3 Pipeline Sub-Agent Pool

**Responsibilities:**
- Manage concurrent pipeline executions
- Track individual task progress
- Handle partial failures

**Design:**
```python
class PipelinePool:
    """Manages multiple pipeline sub-agent executions."""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.active_tasks: dict[str, TaskHandle] = {}
        self.completed_tasks: list[TaskResult] = []

    def submit(self, video_url: str, project_name: str, task_id: str = None) -> str:
        """Submit a pipeline task. Returns task_id."""

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""

    def get_status(self, task_id: str) -> TaskStatus:
        """Get current status of a task."""

    def get_all_status(self) -> list[TaskStatus]:
        """Get status of all tasks."""
```

**Task Tracking:**
- Each task has UUID as `task_id`
- Status stored in `data/{project_name}/pipeline_status/{task_id}_{stage}.json`
- Progress reported to user in real-time via callback

### 2.4 Project & Case Manager

**Project Structure:**
```
data/
└── projects/
    └── {project_uuid/}
        ├── meta.json              # Project metadata
        ├── conversation.json      # Conversation history
        ├── tasks/
        │   ├── {task_id}/
        │   │   ├── pipeline_status/
        │   │   ├── articles/
        │   │   ├── frames/
        │   │   └── qc/
        │   └── ...
        ├── memory_index.json       # RAG vector index reference
        └── contentful_status.json # Push status
```

**Case Identification:**
```python
class Case(TypedDict):
    case_id: str              # UUID
    video_url: str            # Primary key for deduplication
    creator_handle: str        # e.g., @mialaurengreen
    created_at: str           # ISO timestamp
    task_ids: list[str]       # All pipeline task IDs for this case
    article_paths: list[str] # Generated article files
    cms_pushed: bool          # Contentful push status
    cms_entry_id: str | None  # Contentful Entry ID if pushed
```

**Deduplication Logic:**
```python
def check_duplicate(video_url: str) -> Case | None:
    """Check if case with this video URL exists. Returns existing case or None."""
    # Check in case index by video_url
    pass

def create_case(video_url: str, creator_handle: str) -> Case:
    """Create new case. Fails if duplicate exists."""
    pass
```

### 2.5 Memory System (RAG)

**Approach:** Vector database for semantic search of past cases and learnings.

**Model Options:**
| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **ChromaDB** (local) | Zero-config, embedded | Limited scalability | ✅ First choice |
| **Qdrant** | Full-featured | Requires Docker | For production |
| **Pinecone** | Managed, powerful | External dependency | Cloud option |

**ChromaDB Implementation:**
```python
from chromadb import Client as ChromaClient

class MemoryIndex:
    def __init__(self, persist_dir: str):
        self.client = ChromaClient(persist_directory=persist_dir)
        self.collection = self.client.get_or_create_collection("sparki_cases")

    def add_case(self, case: Case, article_content: str):
        """Add case to vector index with embeddings."""
        embedding = get_embedding(f"{case['creator_handle']}: {article_content[:1000]}")
        self.collection.add(
            ids=[case["case_id"]],
            embeddings=[embedding],
            metadatas=[{
                "video_url": case["video_url"],
                "creator": case["creator_handle"],
                "created": case["created_at"]
            }],
            documents=[article_content]
        )

    def query(self, query: str, top_k: int = 5) -> list[Case]:
        """Semantic search for similar cases."""
        embedding = get_embedding(query)
        results = self.collection.query(query_embeddings=[embedding], n_results=top_k)
        return results
```

**Embedding Model:**
```python
# Use local embeddings model for privacy
from src.llm.embeddings import get_local_embedding

def get_embedding(text: str) -> list[float]:
    """Get embedding using local model (e.g., sentence-transformers)."""
    # Default: all-MiniLM-L6-v2 (lightweight, fast)
    # Alternative: bge-small for Chinese support
    pass
```

### 2.6 Contentful Integration

**Configuration Flow:**
1. User provides Contentful credentials (Space ID, Environment, API Token)
2. Master Agent encrypts and stores in `~/.sparki/credentials.enc`
3. User confirms before any publish operation

**Encryption:**
```python
from cryptography.fernet import Fernet
import keyring

def store_credentials(space_id: str, env: str, token: str):
    """Encrypt and store Contentful credentials."""
    key = keyring.get_password("sparki", "encryption_key") or Fernet.generate_key()
    keyring.set_password("sparki", "encryption_key", key.decode())

    f = Fernet(key)
    creds_json = json.dumps({"space_id": space_id, "env": env, "token": token})
    encrypted = f.encrypt(creds_json.encode())

    # Store encrypted blob in local file
    Path("~/.sparki/contentful.enc").write_bytes(encrypted)

def load_credentials() -> dict:
    """Decrypt and load Contentful credentials."""
    # Reverse of above
    pass
```

**Push Flow:**
```
User confirms "推送到Contentful"
    │
    ▼
Check if case already pushed
    │
    ├── Already pushed → Ask "重新推送?"
    │
    └── Not pushed
            │
            ▼
        Show preview (title, slug, excerpt)
            │
            ▼
        User confirms
            │
            ▼
        Call contentful_publish.py
            │
            ├── Success → Update case.cms_pushed = True
            │
            ├── Retry once on failure
            │
            └── Fail after retry → Report error, keep as "未推送"
```

---

## 3. Conversation Interface

### 3.1 Supported Interactions

**Text Input:**
```
用户: "帮我分析这个视频 https://www.instagram.com/reels/xxx/"
助手: "收到！我来为这个视频创建任务..."

用户: "批量处理这几个视频 [url1] [url2] [url3]"
助手: "好的，检测到3个视频。开始创建任务（间隔10秒启动）..."

用户: "现在进度怎么样了"
助手: "当前任务进度：\n- video1: ✅ 完成\n- video2: 🔄 QC中\n- video3: ⏳ 等待中"

用户: "查看我的案例库"
助手: "你的案例：\n1. @mialaurengreen (2个任务)\n2. @urmom_sushi (1个任务)..."

用户: "推送最新的文章到Contentful"
助手: "即将推送：《How to Elevate Your Gym Workout...》\n确认执行？"
```

### 3.2 API Configuration

**Onboarding Flow:**
```
首次启动 → 检测无API配置 → 引导配置
    │
    ▼
助手: "请提供您的 LLM API Base URL"
用户: "https://api.openai.com/v1"
助手: "请提供 API Key（将加密存储）"
用户: "sk-xxx..."
    │
    ▼
验证连接 → 成功 → 开始使用
```

---

## 4. Data Models

### 4.1 Project

```python
class Project(TypedDict):
    project_id: str               # UUID
    name: str                     # Display name
    created_at: str               # ISO timestamp
    updated_at: str               # ISO timestamp
    video_urls: list[str]         # All submitted URLs
    task_ids: list[str]           # All pipeline task IDs
    current_status: str           # "active" | "completed" | "archived"
```

### 4.2 Task Status

```python
class TaskStatus(TypedDict):
    task_id: str
    project_id: str
    video_url: str
    creator_handle: str
    status: str                    # "pending" | "downloading" | "analyzing" | "writing" | "qc" | "publishing" | "done" | "failed"
    progress: float               # 0.0 - 1.0
    current_stage: str
    qc_passed: bool | None
    cms_pushed: bool
    error: str | None
    started_at: str
    completed_at: str | None
```

### 4.3 Conversation Message

```python
class Message(TypedDict):
    message_id: str
    role: str                     # "user" | "assistant" | "system"
    content: str
    attachments: list[str] | None
    timestamp: str
    task_ids: list[str] | None    # Related task IDs
```

---

## 5. File Structure

```
14_NewAgent/
├── src/
│   └── agents/
│       ├── __init__.py
│       ├── state_schema.py           # Shared types
│       ├── pipeline.py               # Sub-agent pipeline
│       ├── master/                    # Master agent components
│       │   ├── __init__.py
│       │   ├── conversation.py       # Chat manager
│       │   ├── intent_router.py      # Intent detection
│       │   ├── pipeline_pool.py      # Task pool
│       │   ├── project_manager.py     # Project/case mgmt
│       │   ├── memory.py             # RAG system
│       │   ├── contentful_publisher.py # CMS integration
│       │   ├── credentials.py       # API key encryption
│       │   └── models.py              # Data models
│       └── nodes/                     # Sub-agent nodes
├── configs/
│   ├── prompts/
│   │   ├── blog_write.txt
│   │   ├── video_analysis.txt
│   │   └── qc_check_unified.txt
│   └── settings.yaml
├── data/
│   └── projects/                      # Project data
│       └── {project_id}/
├── docs/
│   ├── MasterAgentDesign.md          # This document
│   └── DevGuide.md                   # Developer guide
└── tests/
```

---

## 6. Implementation Priorities

### Phase 1: Core Messaging (MVP)
1. Simple conversation loop (no LangChain yet)
2. Intent detection for video URLs
3. Single pipeline execution
4. Basic status reporting

### Phase 2: Batch & Progress
1. Batch pipeline with 10s delays
2. Real-time progress tracking
3. Task cancellation
4. Project/case structure

### Phase 3: Memory & RAG
1. ChromaDB integration
2. Case embedding and search
3. Memory-informed responses

### Phase 4: Contentful & Polish
1. Credential management
2. Push confirmation flow
3. Retry logic
4. Export/import

---

## 7. Dependencies

```yaml
# requirements.txt
langgraph>=0.0.20
langchain>=0.1.0
chromadb>=0.4.0
sentence-transformers>=2.2.0
cryptography>=41.0.0
keyring>=23.0.0
typer>=0.9.0
rich>=13.0.0  # For terminal UI
```

---

## 8. Open Questions

1. **Embedding Model**: Confirm local model supports both English and Chinese adequately
2. **Rate Limits**: How should we handle LLM API rate limits during batch processing?
3. **Storage Limits**: Is there a max storage size for the projects directory?