# Sparki SEO Blog Agent - CLI Tool

An agentic pipeline that converts TikTok/Instagram videos into SEO-optimized blog articles, automatically published to Contentful CMS.

## Features

- Download videos from TikTok and Instagram
- Scrape video/metadata using yt-dlp
- Multi-modal analysis via Gemini (Google AI)
- SEO article generation with frame extraction
- Automatic quality control with rewrite loop
- Direct publish to Contentful CMS

## Prerequisites

### 1. Python Environment

- Python 3.10 or higher
- Create and activate virtual environment (recommended):

```bash
# Create venv
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configuration

Copy and edit the configuration file:

```bash
# Copy example config
cp configs/config.example.yaml configs/config.local.yaml

# Edit with your credentials
# Linux/macOS:
nano configs/config.local.yaml
# Windows:
notepad configs/config.local.yaml
```

#### Required Configuration Fields

| Field | Description | Where to Get |
|-------|-------------|--------------|
| `llm.api_url` | LLM API endpoint | Your LLM provider |
| `llm.api_key` | API key for LLM | Your LLM provider |
| `gcp.project_id` | GCP project ID | Google Cloud Console |
| `gcs_bucket_name` | GCS bucket for video storage | Google Cloud Storage |
| `contentful.space_id` | Contentful space ID | Contentful dashboard |
| `contentful.access_token` | Contentful API token | Contentful settings |

#### Optional Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `video.format` | best mp4 | yt-dlp format preference |
| `video.retries` | 3 | Download retry count |
| `video.timeout` | 60 | Download timeout (seconds) |

### 4. Google Cloud Setup (for Gemini Video Analysis)

```bash
# Set GCP credentials (if using Gemini)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

Or set in `config.local.yaml`:
```yaml
gcp:
  service_account_key_path: "/path/to/key.json"
```

### 5. Contentful Space Setup

Create a Contentful space with:
- A content model for blog posts (title, body, featured_image, seo_metadata)
- An API key with read/write access

## Quick Start

### 1. Run the CLI

```bash
# Activate venv first (if using)
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Run CLI
python -m src.agents.master.cli
```

### 2. CLI Commands

```
Commands:
  submit <url>          - Process a single video
  batch <url1> <url2>.. - Process multiple videos (max 10)
  status                - Show all task statuses
  projects              - List all projects
  help                  - Show this help
  exit                  - Exit
```

### 3. Example Session

```
==================================================
Sparki Master Agent - Video to Blog CLI
==================================================
Commands:
  submit <url>          - Process a single video
  batch <url1> <url2>.. - Process multiple videos (max 10)
  status                - Show all task statuses
  projects              - List projects
  help                  - Show this help
  exit                  - Exit
==================================================
Session created: a1b2c3d4...

> submit https://www.tiktok.com/@user/video/1234567890
Processing video: https://www.tiktok.com/@user/video/1234567890
Task submitted: a1b2c3d4...
```

## Verification Checklist

Run this checklist before first use:

- [ ] Python 3.10+ installed (`python --version`)
- [ ] Virtual environment activated (`.venv` shown in prompt)
- [ ] Dependencies installed (`pip list` shows all packages)
- [ ] `configs/config.local.yaml` created with all required fields
- [ ] GCP credentials configured (if using Gemini video analysis)
- [ ] Contentful space created and API key generated
- [ ] GCS bucket exists and is accessible

### Verify Each Pipeline Node

Test each node independently:

```bash
# Test video downloader
python -c "
from src.agents.nodes.video_downloader import download_video
result = download_video('https://www.tiktok.com/@user/video/123', 'test_project', 'test-task-id')
print('Download:', 'OK' if result.get('local_video_path') else 'FAIL')
"

# Test metadata scraper
python -c "
from src.agents.nodes.metadata_scraper import scrape_metadata
result = scrape_metadata('https://www.tiktok.com/@user/video/123')
print('Scraper:', 'OK' if result.get('metadata') else 'FAIL')
"

# Test video analyzer
python -c "
from src.agents.nodes.video_analyzer import analyze_video
result = analyze_video('/path/to/video.mp4', {}, 'test-task-id')
print('Analyzer:', 'OK' if result.get('analysis_result') else 'FAIL')
"

# Run full pipeline test
python -c "
from src.agents.pipeline import run_pipeline
result = run_pipeline('https://www.tiktok.com/@user/video/123', 'default', 'test-001')
print('Pipeline:', result.get('status'), result.get('error', ''))
"
```

## Project Structure

```
14_NewAgent/
├── src/
│   ├── agents/
│   │   ├── master/          # Master Agent (CLI, API server, TUI)
│   │   │   ├── cli.py       # CLI entry point
│   │   │   ├── api_server.py # REST API server (port 5555)
│   │   │   ├── pipeline_pool.py # Task pool management
│   │   │   └── ...
│   │   ├── nodes/           # Pipeline nodes
│   │   │   ├── video_downloader.py
│   │   │   ├── metadata_scraper.py
│   │   │   ├── video_analyzer.py
│   │   │   ├── article_writer.py
│   │   │   ├── qc_checker.py
│   │   │   └── article_rewriter.py
│   │   ├── pipeline.py      # Main pipeline orchestration
│   │   └── state_schema.py  # Shared state schema
│   └── storage/
│       └── storage_paths.py # Storage path utilities
├── configs/
│   ├── config.example.yaml  # Template configuration
│   └── config.local.yaml    # Local configuration (gitignored)
├── data/                    # Task outputs (gitignored)
├── docs/                    # Documentation
├── tests/                   # Test files
└── requirements.txt         # Python dependencies
```

## Architecture

```
User Input (CLI)
    ↓
PipelinePool.submit() → Background thread
    ↓
run_pipeline(video_url, project_name, task_id, progress_callback)
    ↓
Node 1: video_downloader (yt-dlp)
    ↓ progress_callback(progress, stage, message)
    ↓
Node 2: metadata_scraper (requests + parsing)
    ↓
Node 3: video_analyzer (Gemini multi-modal)
    ↓
Node 4: frame_extractor (ffmpeg)
    ↓
Node 5: article_writer (LLM + frames)
    ↓
Node 6: qc_checker (LLM)
    ↓ (if failed → rewrite loop)
    ↓
Node 7: contentful_publisher
    ↓
Result: CMS URL + local files
```

## Data Storage

### Local
- `data/Sparki_SEO_Blog_Agent_V2/{project_name}/raw/` - Downloaded videos
- `data/Sparki_SEO_Blog_Agent_V2/{project_name}/frames/` - Extracted frames
- `data/Sparki_SEO_Blog_Agent_V2/{project_name}/articles/` - Generated articles
- `data/Sparki_SEO_Blog_Agent_V2/{project_name}/pipeline_status/` - Node status JSON

### GCS (Google Cloud Storage)
- `gs://{bucket}/Sparki_SEO_Blog_Agent_V2/{project_name}/videos/`
- `gs://{bucket}/Sparki_SEO_Blog_Agent_V2/{project_name}/frames/`

## Troubleshooting

### "Download failed: Unexpected error"
Usually proxy or network issue. In CLI, proxy is auto-cleared. For other contexts:
```python
import os
for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(key, None)
```

### "API key not configured"
Check `configs/config.local.yaml` has valid `llm.api_key` and `llm.api_url`.

### "Contentful publish failed"
Verify space ID, access token, and content model exist in Contentful.

### "Gemini analysis failed"
Verify GCP credentials and `gcp.project_id` are correct.

## License

MIT - See LICENSE file (not included in this package).