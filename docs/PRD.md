# PRD - AI Video Blog Article Generator Agent

## 1. Overview

**Project Name:** Sparki Blog Agent

**Project Type:** Agentic Workflow / LangGraph-based Pipeline

**Core Functionality:** An automated system that analyzes viral videos, extracts key moments for illustrations, writes SEO-optimized blog articles according to templates, performs quality checks, and publishes to CMS.

**Target Users:** Growth team members who need to produce high-quality SEO articles from video content.

---

## 2. Background

Our company operates an AI video editing & generation product that clones viral video styles for user footage editing. The growth team needs to write articles in the product blog for SEO purposes. This tool automates the entire pipeline from video analysis to article publication.

---

## 3. Goals

### Primary Goals
- Automate video analysis (narrative, rhythm, subtitles, music, etc.)
- Extract optimal illustration timepoints using multimodal LLM
- Generate SEO-optimized articles based on templates
- Quality check articles before publishing
- Publish to Contentful CMS as Draft

### Extended Goals
- Batch processing support (multiple videos in parallel)
- Project management with task tracking
- Visual operation interface
- High extensibility and maintainability

---

## 4. Functional Specification

### 4.1 Core Features

#### F1: Video Download & Metadata Extraction
- Download video from URL using yt-dlp
- Extract metadata: title, author, URL, likes, views, saves, shares, comments, follower count
- Store metadata for article insertion

#### F2: Video Analysis
- Multi-modal analysis using Gemini models
- Analyze dimensions: narrative structure, rhythm, subtitles, music, key moments
- Output: structured analysis report with recommended illustration timestamps

#### F3: Frame Extraction
- Extract frames at LLM-specified timestamps using ffmpeg
- Store extracted images with proper naming convention

#### F4: Article Writing
- Use template-based writing with SEO long-tail keywords
- Insert extracted images at marked positions
- Include video and blogger metadata in article
- Support Markdown output format

#### F5: Quality Check
- Automated QC against defined rules
- Generate modification suggestions if failed
- Loop until QC passes or max iterations reached

#### F6: CMS Publishing
- Push completed article to Contentful as Draft
- Include all metadata and images

### 4.2 Batch Processing
- Parse input intent to extract multiple video URLs
- Spawn parallel sub-agents for each video
- Main agent coordinates and monitors progress
- Project-level management and tracking

### 4.3 User Interface
- Web-based visual interface
- Task dashboard showing pipeline status
- Results and feedback viewer
- Manual intervention points for QC

---

## 5. System Architecture

### 5.1 Agent Types

| Agent | Role | Technology |
|-------|------|------------|
| Main Agent | Coordinator, Intent Parsing, Task Distribution | Self-hosted LLM |
| Video Analysis Agent | Video analysis, timestamp extraction | Gemini (GCP) |
| Article Writer Agent | Template-based writing, SEO optimization | Gemini (GCP) |
| QC Agent | Quality checking, feedback generation | Self-hosted LLM |

### 5.2 Pipeline Flow

```
Input (Video URLs + Intent)
       ↓
Main Agent (Intent Parsing & Task Distribution)
       ↓
┌─────────────────────────────────────┐
│  Parallel Sub-Agents (per video)    │
│       ↓                             │
│  Video Download → Metadata Extract  │
│       ↓                             │
│  Video Analysis (Gemini)            │
│       ↓                             │
│  Frame Extraction (ffmpeg)         │
│       ↓                             │
│  Article Writing (Gemini)          │
│       ↓                             │
│  Quality Check (Self-hosted LLM)    │
│       ↓                             │
│  Push to Contentful CMS             │
└─────────────────────────────────────┘
       ↓
Main Agent (Aggregation & Reporting)
```

---

## 6. Input/Output Specification

### 6.1 Inputs
- Video URL(s) (YouTube or other platforms)
- SEO keywords / long-tail phrases
- Writing template selection
- (Optional) Custom QC rules

### 6.2 Outputs
- Markdown article with embedded images
- Structured metadata (blogger info, video stats)
- QC report (pass/fail + suggestions)
- Contentful Draft URL

---

## 7. External Dependencies

| Resource | Purpose | Access |
|----------|---------|--------|
| yt-dlp | Video download | Local |
| ffmpeg | Frame extraction | Local |
| Playwright | Dynamic content scraping | Local |
| Gemini (GCP) | Multi-modal analysis, writing | GCS Bucket |
| Self-hosted LLM | Intent parsing, QC | API Key + URL |
| GitHub | Version control | Personal repo |
| Contentful API | CMS publishing | API credentials |
| Proxy (Clash Verge) | Network access | Port 7897 |

---

## 8. Data Flow

### 8.1 Artifacts Storage
- **GCS Bucket:** Videos, extracted frames
- **Local:** Task results, logs, intermediate outputs
- **GitHub:** Code and configuration

### 8.2 Task Persistence
- Each task maintains:
  - Input parameters
  - Intermediate outputs (metadata, analysis, drafts)
  - Modification suggestions (if QC failed)
  - Final output and status

---

## 9. Acceptance Criteria

### AC1: Single Video Pipeline
- [ ] Given a video URL and SEO keywords, system produces a complete Markdown article
- [ ] Article contains video metadata, blogger info, extracted images
- [ ] QC check runs and provides feedback or passes

### AC2: Batch Processing
- [ ] System accepts multiple URLs and processes them in parallel
- [ ] Main agent tracks and reports individual task status
- [ ] Failed tasks do not block others

### AC3: CMS Publishing
- [ ] Successfully published article appears as Draft in Contentful
- [ ] All images and metadata are correctly associated

### AC4: Observability
- [ ] User can view pipeline status in web UI
- [ ] Task results and logs are accessible
- [ ] QC feedback is visible to users

### AC5: Extensibility
- [ ] New template types can be added without major refactoring
- [ ] Additional analysis dimensions can be plugged in

---

## 10. Non-Functional Requirements

- **Performance:** Single video pipeline completes within 10 minutes
- **Reliability:** Failed tasks can be retried without full restart
- **Maintainability:** Modular design, clear interfaces between components
- **Security:** API keys stored securely, not hardcoded

---

## 11. Project Structure

```
14_NewAgent/
├── docs/                    # Documentation
│   ├── 00_RawIdea.md
│   ├── PRD.md              # This document
│   ├── DevGuide.md
│   └── InterfaceContracts.md  # State Schema, Tool Interfaces, Node Boundaries
├── src/                     # Source code
│   ├── agents/             # LangGraph agents (nodes)
│   ├── tools/              # Tool implementations
│   ├── utils/              # Utilities
│   └── ui/                 # Web interface
├── configs/                 # Configuration files
├── data/                    # Task outputs, logs (see Storage Structure)
└── tests/                   # Unit and integration tests
```

---

## 12. Storage Structure

All local data follows `data/Sparki_SEO_Blog_Agent_V2/{project_name}/` structure.

GCS data follows `gs://{GCS_BUCKET_NAME}/Sparki_SEO_Blog_Agent_V2/{project_name}/` structure.

See [InterfaceContracts.md](InterfaceContracts.md#4-storage-structure) for full details.

---

## 13. Interface Contracts

All tool interfaces, state schemas, and node boundaries are defined in [InterfaceContracts.md](InterfaceContracts.md).

Key contracts:
- **PipelineState**: Shared state object passed through all nodes
- **Tool Input/Output Schema**: TypedDict-based contracts for each tool
- **Node Boundary Table**: Defines which state fields each node reads/writes

Refer to InterfaceContracts.md before implementing any tool or node to ensure compatibility with the parallel development workflow.