# DevGuide - Sparki SEO Blog Agent

## 1. Development Setup

### 1.1 Environment Requirements

- **Python:** 3.11+
- **FFmpeg:** Latest (for frame extraction)
- **Git:** For version control

### 1.2 Installation

```bash
# Clone repository
git clone <your-github-repo>
cd 14_NewAgent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install langgraph langchain-core langchain-community \
    google-genai ffmpeg-python yt-dlp playwright \
    chromadb sentence-transformers cryptography keyring

# Install Playwright browsers (if needed)
playwright install chromium
```

### 1.3 Configuration

Create `configs/config.local.yaml`:

```yaml
gcp:
  project_id: "your-gcp-project"
  gcs_bucket_name: "your-bucket"

storage:
  data_root: "data"
  base_prefix: "Sparki_SEO_Blog_Agent_V2"

contentful:
  space_id: "your-space-id"
  access_token: "your-api-token"  # User provides this
  environment: "master"

llm:
  api_url: "https://your-llm-endpoint.com/v1"
  api_key: "your-api-key"

proxy:
  http_proxy: "http://127.0.0.1:7897"
  https_proxy: "http://127.0.0.1:7897"
```

---

## 2. Project Structure

```
14_NewAgent/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── state_schema.py       # Shared TypedDict definitions
│   │   ├── pipeline.py            # LangGraph pipeline (sub-agent)
│   │   ├── nodes/                 # Pipeline nodes (standalone)
│   │   │   ├── video_downloader.py
│   │   │   ├── metadata_scraper.py
│   │   │   ├── video_analyzer.py
│   │   │   ├── article_writer.py
│   │   │   ├── qc_checker.py
│   │   │   ├── article_rewriter.py
│   │   │   └── cms_publisher.py   # To be implemented
│   │   └── master/                # Master agent components
│   │       ├── __init__.py
│   │       ├── conversation.py
│   │       ├── intent_router.py
│   │       ├── pipeline_pool.py
│   │       ├── project_manager.py
│   │       ├── memory.py
│   │       ├── contentful_publisher.py
│   │       └── credentials.py
│   ├── config.py
│   └── storage/
│       └── storage_paths.py
├── configs/
│   ├── config.local.yaml         # User configuration (gitignored)
│   ├── config.example.yaml       # Template
│   └── prompts/
│       ├── blog_write.txt
│       ├── video_analysis.txt
│       └── qc_check_unified.txt
├── data/                          # Task outputs (gitignored)
│   └── projects/
├── docs/
│   ├── MasterAgentDesign.md       # Master agent architecture
│   ├── InterfaceContracts.md      # Sub-agent interfaces
│   └── DevGuide.md               # This file
└── tests/
```

---

## 3. Sub-Agent Pipeline (Completed)

The pipeline is a **LangGraph StateGraph** that orchestrates video-to-blog generation.

### 3.1 Pipeline Stages

| Stage | Node | Description |
|-------|------|-------------|
| 1 | `download_video` | Download video from TikTok/Instagram |
| 2 | `scrape_metadata` | Extract video and creator metadata |
| 3 | `analyze_video` | Gemini analysis for content insights |
| 4 | `write_article` | Generate blog article |
| 5 | `qc_check` | Quality control check |
| 6 | `rewrite_article` | Fix QC issues (if needed, max 2 rounds) |
| 7 | `publish_cms` | Push to Contentful (placeholder) |

### 3.2 Running the Pipeline

```python
from src.agents.pipeline import run_pipeline, get_task_progress

# Run pipeline
result = run_pipeline(
    video_url="https://www.instagram.com/reels/xxx/",
    project_name="my_project",
    task_id="abc123"  # Optional, auto-generated if not provided
)

# Check progress
progress = get_task_progress("abc123", "my_project")
print(f"Progress: {progress['progress']*100:.0f}%")
```

### 3.3 Node Output Files

Each node saves results to JSON:

```
data/Sparki_SEO_Blog_Agent_V2/{project_name}/
├── download_result/{task_id}_result.json
├── metadata_result/{task_id}_meta.json
├── analysis_result/{task_id}_analysis.json
├── frames/{task_id}/                    # Extracted frames
├── articles/{task_id}_article.md
├── qc/{task_id}_qc.json
└── pipeline_status/                      # Master agent monitoring
    ├── {task_id}_download.json
    ├── {task_id}_analyze.json
    └── ...
```

---

## 4. Master Agent (To Be Implemented)

### 4.1 Architecture Overview

The Master Agent is a **conversational interface** that:

1. Accepts natural language commands from users
2. Detects video URLs and orchestrates pipeline execution
3. Manages projects and conversation history
4. Provides semantic memory of past cases
5. Handles Contentful publishing

### 4.2 Components

| Component | File | Responsibility |
|-----------|------|-----------------|
| Conversation Manager | `master/conversation.py` | Chat history, context window |
| Intent Router | `master/intent_router.py` | URL detection, batch classification |
| Pipeline Pool | `master/pipeline_pool.py` | Concurrent pipeline management |
| Project Manager | `master/project_manager.py` | Case/project CRUD, deduplication |
| Memory (RAG) | `master/memory.py` | ChromaDB vector index |
| Contentful Publisher | `master/contentful_publisher.py` | CMS push workflow |
| Credentials | `master/credentials.py` | Encrypted API key storage |

### 4.3 Implementation Priority

```
Phase 1: Core Messaging (MVP)
├── Simple conversation loop
├── Intent detection (video URL extraction)
├── Single pipeline execution
└── Basic status reporting

Phase 2: Batch & Progress
├── Batch pipeline with 10s delays
├── Real-time progress tracking
├── Task cancellation
└── Project/case structure

Phase 3: Memory & RAG
├── ChromaDB integration
├── Case embedding
└── Semantic search

Phase 4: Contentful & Polish
├── Credential management
├── Push confirmation flow
├── Retry logic
└── Export/import
```

### 4.4 Intent Types

```python
class Intent(str):
    VIDEO_SUBMIT = "video_submit"        # Single video
    BATCH_SUBMIT = "batch_submit"        # Multiple videos
    STATUS_QUERY = "status_query"         # Check progress
    PROJECT_LIST = "project_list"         # List cases
    SETTINGS = "settings"                 # Configure API
    CONTENTFUL_PUSH = "contentful_push"   # Publish to CMS
    MEMORY_QUERY = "memory_query"         # Search past cases
```

### 4.5 Key Constraints

- **Batch limit:** Max 10 URLs per request
- **Task interval:** 10 seconds between pipeline starts
- **Partial failure:** Batch continues even if some tasks fail
- **Deduplication:** Same video URL cannot create duplicate cases

---

## 5. Adding New Nodes

### 5.1 Node Template

```python
"""New node for Sparki pipeline."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.storage.storage_paths import StoragePaths

logger = logging.getLogger(__name__)


class NewNodeInput(TypedDict):
    required_field: str
    optional_field: str = "default"


def _save_result_json(result: dict, output_base_dir: str, project_name: str, task_id: str) -> str:
    """Save result as JSON file."""
    result_dir = StoragePaths.local_base(output_base_dir, project_name) / "new_result"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{task_id}_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(result_path)


def new_node(input: NewNodeInput) -> str:
    """Process something.

    Args:
        input: NewNodeInput with required_field

    Returns:
        Path to JSON result file
    """
    required_field = input["required_field"]
    task_id = input.get("task_id", "")
    project_name = input.get("project_name", "default")
    output_base_dir = input.get("output_base_dir", "data")

    logger.info(f"Processing {required_field}")

    result = {
        "success": False,
        "data": None,
        "error": None,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Processing logic here
        result["success"] = True
        result["data"] = {"key": "value"}
        return _save_result_json(result, output_base_dir, project_name, task_id)

    except Exception as e:
        logger.error(f"Error: {e}")
        result["error"] = str(e)
        return _save_result_json(result, output_base_dir, project_name, task_id)
```

### 5.2 Adding to Pipeline

```python
# In pipeline.py

def node_new(state: PipelineState) -> PipelineState:
    """New node wrapper for pipeline."""
    # Extract inputs from state
    # Call new_node()
    # Update state with outputs
    pass

# In _build_pipeline_graph():
graph.add_node("new_stage", node_new)
graph.add_edge("previous_stage", "new_stage")
```

---

## 6. Contentful Integration

### 6.1 Reference Implementation

See `E:\2027_GET_A_JOB\Get_An_AI_Job\视界Sparki\09_ContentfulAuto\contentful_publish.py`

Key steps:
1. Parse Markdown (extract frontmatter + body)
2. Upload images as Contentful Assets
3. Convert Markdown to Slate JSON
4. Create Draft Entry

### 6.2 Push Flow

```
User confirms "推送到Contentful"
    │
    ▼
Check if already pushed (case.cms_pushed)
    │
    ├── Already pushed → Ask "重新推送?"
    │
    └── Not pushed
            │
            ▼
        Validate credentials
            │
            ▼
        Call contentful_publish.py logic
            │
            ├── Success → Update case.cms_pushed = True, save entry_id
            │
            ├── Retry once on failure
            │
            └── Fail after retry → Log error, keep "未推送" status
```

### 6.3 Contentful Client Configuration

```python
SPACE_ID = "gyre98gugxnb"
ENV = "master"
TOKEN = "CFPAT-xxx"  # User provides this
CT_ID = "blogPost"
LOCALE = "en-US"
API_BASE = f"https://api.contentful.com/spaces/{SPACE_ID}/environments/{ENV}"
```

---

## 7. Memory System (RAG)

### 7.1 ChromaDB Setup

```python
from chromadb import Client as ChromaClient

client = ChromaClient(persist_directory="data/memory_index")
collection = client.get_or_create_collection("sparki_cases")
```

### 7.2 Embedding Model

Use `sentence-transformers/all-MiniLM-L6-v2` for lightweight local embeddings:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

def get_embedding(text: str) -> list[float]:
    return model.encode(text).tolist()
```

### 7.3 Adding Cases to Memory

```python
def add_case_to_memory(case_id: str, creator_handle: str, article_content: str):
    embedding = get_embedding(f"{creator_handle}: {article_content[:1000]}")
    collection.add(
        ids=[case_id],
        embeddings=[embedding],
        metadatas=[{"creator": creator_handle}],
        documents=[article_content]
    )
```

---

## 8. API Credentials Security

### 8.1 Encryption

Use `cryptography.Fernet` for symmetric encryption:

```python
from cryptography.fernet import Fernet
import keyring

def store_credential(key: str, value: str):
    # Get or create encryption key from keyring
    encryption_key = keyring.get_password("sparki", "encryption_key")
    if not encryption_key:
        encryption_key = Fernet.generate_key().decode()
        keyring.set_password("sparki", "encryption_key", encryption_key)

    # Encrypt and store
    f = Fernet(encryption_key.encode())
    encrypted = f.encrypt(value.encode())
    Path(f"~/.sparki/{key}.enc").write_bytes(encrypted)

def load_credential(key: str) -> str:
    encryption_key = keyring.get_password("sparki", "encryption_key")
    f = Fernet(encryption_key.encode())
    encrypted = Path(f"~/.sparki/{key}.enc").read_bytes()
    return f.decrypt(encrypted).decode()
```

---

## 9. Git Workflow

### 9.1 Branch Strategy

```
main                           # Stable
├── develop                    # Integration
│   ├── feature/pipeline       # Completed
│   ├── feature/master-conversation
│   ├── feature/master-intent
│   ├── feature/master-memory
│   └── feature/master-contentful
└── release
```

### 9.2 Commit Convention

```
feat: add new node for X
fix: resolve video URL detection bug
docs: update InterfaceContracts
refactor: simplify QC result structure
test: add pipeline integration test
```

### 9.3 State Schema Updates

When updating `state_schema.py` or `InterfaceContracts.md`:

1. Make the change
2. Update all nodes that use the changed fields
3. Update the docstrings
4. Run tests
5. Update `InterfaceContracts.md` if schema changed

---

## 10. Testing

### 10.1 Sub-Agent Testing

```bash
# Test individual node
python -m src.agents.nodes.video_downloader --help

# Test pipeline
python -m src.agents.pipeline --video-url "https://www.instagram.com/reels/xxx/" --project test
```

### 10.2 Integration Testing

```python
from src.agents.pipeline import run_pipeline, get_task_progress

result = run_pipeline(
    video_url="https://www.instagram.com/reels/DWwVuBJiukt/",
    project_name="integration_test",
    task_id="test001"
)

assert result["status"] == "done"
assert result.get("article_markdown")
assert result.get("qc_passed")
```

---

## 11. Troubleshooting

| Issue | Solution |
|-------|----------|
| Pipeline hangs | Check GCS credentials, Vertex AI access |
| QC fails all rounds | Review qc_check_unified.txt prompt |
| Contentful push fails | Verify API token, retry once |
| Memory search returns nothing | Check ChromaDB persistence |
| Batch tasks fail silently | Check logs in data/projects/{id}/logs/ |

### 11.1 Debug Commands

```bash
# Check pipeline status files
ls -la data/Sparki_SEO_Blog_Agent_V2/*/pipeline_status/

# View task logs
cat data/projects/{project_id}/logs/{task_id}.log

# Test ChromaDB
python -c "from chromadb import Client; c = Client(); print(c.list_collections())"
```

---

## 12. References

- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Contentful CMA API](https://www.contentful.com/developers/docs/references/content-management-api/)
- [yt-dlp Documentation](https://github.com/yt-dlp/yt-dlp)
- [sentence-transformers](https://www.sbert.net/)