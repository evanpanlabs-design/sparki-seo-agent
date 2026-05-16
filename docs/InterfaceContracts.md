# Interface Contracts - AI Video Blog Article Generator Agent

## 目录

1. [State Schema](#1-state-schema)
2. [Tool Interface Contracts](#2-tool-interface-contracts)
3. [Node Boundary Table](#3-node-boundary-table)
4. [Storage Structure](#4-storage-structure)
5. [Git Flow](#5-git-flow)

---

## 1. State Schema

贯穿整个 Pipeline 的状态对象，所有节点共享同一个状态字典。

### 1.1 PipelineState（核心状态）

```python
from typing import TypedDict, NotRequired

class PipelineState(TypedDict):
    # ========== 任务基础信息 ==========
    task_id: str                           # 唯一任务ID，格式: uuid4
    project_name: str                      # 项目名，用于路径隔离
    status: str                            # pending | running | done | failed | retry

    # ========== 视频信息 ==========
    video_url: str                         # 原始视频URL
    video_local_path: str                  # 本地视频路径
    video_gcs_path: str                    # GCS 视频路径

    # ========== 元数据 ==========
    video_metadata: "VideoMetadata"        # 视频+博主元数据

    # ========== 分析结果 ==========
    analysis_result: "VideoAnalysisResult" # Gemini 多模态分析结果
    frame_timestamps: list[float]         # 抽帧时间点（秒）

    # ========== 抽帧 ==========
    frame_local_paths: list[str]           # 本地抽帧图片路径列表
    frame_gcs_paths: list[str]             # GCS 抽帧图片路径列表

    # ========== 文章 ==========
    article_markdown: str                  # 生成的 Markdown 文章
    article_word_count: int                # 文章字数

    # ========== 质检 ==========
    qc_result: "QCResult"                  # 质检结果
    qc_attempts: int                       # 质检尝试次数

    # ========== 发布 ==========
    cms_draft_url: str                     # Contentful Draft URL

    # ========== 日志 ==========
    logs: list[str]                        # 任务日志
    errors: list[str]                      # 错误记录
```

### 1.2 VideoMetadata

```python
class VideoMetadata(TypedDict):
    # 视频信息
    video_id: str                          # 平台视频ID
    video_url: str                          # 原始视频URL (e.g., https://www.instagram.com/p/XXX/)
    video_title: str                       # 视频标题
    video_description: str                # 视频描述
    video_duration: float                  # 视频时长（秒）
    video_thumbnail_url: str               # 封面图URL
    published_at: str                      # 发布时间 ISO8601

    # 博主信息
    author_id: str                         # 博主ID
    author_name: str                       # 博主昵称
    author_url: str                       # 博主主页URL
    author_avatar_url: str                 # 博主头像URL

    # 互动数据
    likes: int                             # 点赞数
    views: int                             # 播放量
    saves: int                             # 收藏数
    shares: int                            # 转发数
    comments: int                          # 评论数

    # 粉丝数据
    followers: int                         # 粉丝数
    following: int                          # 关注数
```

### 1.3 VideoAnalysisResult

```python
class VideoAnalysisResult(TypedDict):
    # 叙事结构
    narrative_structure: str                # 叙事结构描述
    key_moments: list["KeyMoment"]         # 关键情节点

    # 内容分析
    subtitle_summary: str                   # 字幕/文案摘要
    music_description: str                 # 配乐描述
    visual_highlights: list[str]            # 视觉亮点

    # 节奏分析
    rhythm_analysis: str                    # 节奏分析
    pacing_notes: str                      # 节拍备注

    # 推荐抽帧时间点（LLM 根据内容判断）
    recommended_timestamps: list[float]     # 推荐抽帧时间（秒）

    # SEO 关键词
    extracted_keywords: list[str]           # 从视频中提取的关键词

    # 原始分析文本（供溯源）
    raw_analysis: str                      # Gemini 原始输出
```

### 1.4 KeyMoment

```python
class KeyMoment(TypedDict):
    timestamp: float                       # 时间点（秒）
    description: str                      # 场景描述
    importance: str                       # high | medium | low
    reason: str                           # 为什么要在这个时间点抽帧
```

### 1.5 QCResult

```python
class QCResult(TypedDict):
    passed: bool                           # 是否通过（所有维度≥7.0）
    overall_score: float                    # 加权总分 0-10
    dimensions: list["DimensionResult"]    # 各维度结果
    checked_at: str                        # 质检时间 ISO8601
```

### 1.6 DimensionResult

```python
class DimensionResult(TypedDict):
    dimension: str                          # 维度名称
    score: float                           # 得分 0-10
    issues: list["Issue"]                   # 问题列表
    suggestions: list[str]                  # 修改建议
```

### 1.7 Issue

```python
class Issue(TypedDict):
    location: str                          # 问题位置（如"第3段第2句"）
    original: str                          # 原文片段
    problem: str                          # 具体问题描述
    suggestion: str                       # 修改方向
    revised: str | None                    # 建议修改文本（可选）
```

### 1.8 ArticleRewriterResult

```python
class ArticleRewriterResult(TypedDict):
    success: bool                          # 是否成功
    revised_article: str                   # 修改后的文章
    revisions_applied: list[str]           # 实际应用的修改说明
    error: str | None
```

---

## 2. Tool Interface Contracts

每个工具都是独立模块，有明确的输入输出 schema。

### 2.1 VideoDownloader

```python
# ========== 输入 ==========
class VideoDownloaderInput(TypedDict):
    video_url: str                        # 视频 URL
    project_name: str                     # 项目名（用于路径组织）
    output_base_dir: str                   # 本地存储根目录
    task_id: str                          # 任务ID（用于文件名）

# ========== 输出 ==========
class VideoDownloaderOutput(TypedDict):
    success: bool
    local_video_path: str                  # e.g., data/Sparki_SEO_Blog_Agent_V2/{project}/raw/{task_id}.mp4
    gcs_video_path: str                    # e.g., gs://{bucket}/Sparki_SEO_Blog_Agent_V2/{project}/videos/{task_id}.mp4
    error: str | None
```

**实现要点：**
- 使用 `yt-dlp` 下载视频
- 下载完成后自动上传到 GCS 备份
- 本地保留一份用于后续处理
- 异常时返回 `success: False` 和 `error` 信息

---

### 2.2 MetadataScraper

```python
# ========== 输入 ==========
class MetadataScraperInput(TypedDict):
    video_url: str                        # 视频 URL

# ========== 输出 ==========
class MetadataScraperOutput(TypedDict):
    success: bool
    metadata: VideoMetadata | None        # 完整元数据结构
    error: str | None
```

**实现要点：**
- 优先从 yt-dlp 提取的 metadata 获取（同步返回）
- 使用 Playwright 补充动态加载的数据（如粉丝数、评论数）
- 返回完整的 `VideoMetadata` 对象

---

### 2.3 VideoAnalyzer

```python
# ========== 输入 ==========
class VideoAnalyzerInput(TypedDict):
    video_local_path: str                 # 本地视频路径
    video_gcs_path: str                   # GCS 视频路径
    metadata: VideoMetadata               # 视频元数据

# ========== 输出 ==========
class VideoAnalyzerOutput(TypedDict):
    success: bool
    analysis_result: VideoAnalysisResult | None
    error: str | None
```

**实现要点：**
- 使用 Gemini 多模态分析（通过 GCS URL）
- 提取叙事结构、节奏、字幕、配乐等维度
- 输出推荐抽帧时间点

---

### 2.4 FrameExtractor

```python
# ========== 输入 ==========
class FrameExtractorInput(TypedDict):
    video_local_path: str                 # 本地视频路径
    timestamps: list[float]               # 抽帧时间点列表（秒）
    project_name: str                    # 项目名
    task_id: str                         # 任务ID

# ========== 输出 ==========
class FrameExtractorOutput(TypedDict):
    success: bool
    frame_paths: list[str]                # 本地路径列表 e.g., data/Sparki_SEO_Blog_Agent_V2/{project}/frames/{task_id}/frame_00-01-23.jpg
    gcs_paths: list[str]                  # GCS 路径列表
    error: str | None
```

**实现要点：**
- 使用 ffmpeg 抽帧
- 时间戳格式：`frame_{HH-MM-SS}.jpg`
- 同时上传到 GCS
- 异常帧（如视频太短）跳过并记录

---

### 2.5 ArticleWriter

```python
# ========== 输入 ==========
class ArticleWriterInput(TypedDict):
    metadata: VideoMetadata               # 视频+博主元数据
    analysis_result: VideoAnalysisResult   # 分析结果
    frame_gcs_paths: list[str]             # 抽帧图片 GCS 路径（用于 Markdown 插入）
    seo_keywords: list[str]               # SEO 长尾词
    template_name: str                    # 模板名称

# ========== 输出 ==========
class ArticleWriterOutput(TypedDict):
    success: bool
    article_markdown: str | None          # 生成的 Markdown
    word_count: int                       # 字数
    error: str | None
```

**实现要点：**
- 使用 Gemini 基于模板写作
- 图片插入位置：`![alt text](GCS_URL)`
- 包含博主信息、视频元数据

---

### 2.6 QCChecker

```python
# ========== 输入 ==========
class QCCheckerInput(TypedDict):
    article_markdown: str                 # 待质检文章
    metadata: VideoMetadata               # 视频元数据（用于核对事实）
    analysis_result: VideoAnalysisResult   # 分析结果（用于核对事实）

# ========== 输出 ==========
class QCCheckerOutput(TypedDict):
    success: bool
    qc_result: QCResult                   # 质检结果（包含结构化返修报告）
    error: str | None
```

**QC 检查维度（6个维度，每个维度≥7.0通过）：**
1. `metadata` - 元数据准确性（creator handle、粉丝数、stats）
2. `seo_keywords` - 关键词自然融入，1-2次
3. `fluency` - 人类写作风格，无AI典型用语
4. `factuality` - 与视频内容一致，无捏造
5. `non_generic` - 具体洞察，非泛化建议
6. `replication_table` - "How to Replicate"表格存在且格式正确

**质检通过标准：** 所有6个维度得分≥7.0

**质检流程：**
1. 逐维度评分（0-10分）
2. 问题定位（location + original）
3. 生成结构化返修建议（problem + suggestion + revised）
4. 计算加权总分，判断是否通过

---

### 2.7 ArticleRewriter

```python
# ========== 输入 ==========
class ArticleRewriterInput(TypedDict):
    article_markdown: str                 # 当前文章
    qc_result: QCResult                   # 质检结果（包含问题列表）

# ========== 输出 ==========
class ArticleRewriterOutput(TypedDict):
    success: bool
    revised_article: str                   # 修改后的文章
    revisions_applied: list[str]           # 实际应用的修改说明
    error: str | None
```

**实现要点：**
- 定向修改：只修改 QC 指出的问题点，不改变文章整体结构
- 保留原意：确保修改后文章核心内容不变
- 逐条处理：按照 QCResult.issues 逐一修改
- 输出修订记录：记录每条修改的具体内容

---

### 2.8 CMSPublisher

```python
# ========== 输入 ==========
class CMSPublisherInput(TypedDict):
    article_markdown: str                 # 文章 Markdown
    metadata: VideoMetadata               # 视频元数据
    frame_gcs_paths: list[str]             # 抽帧图片 GCS 路径
    project_name: str                     # 项目名

# ========== 输出 ==========
class CMSPublisherOutput(TypedDict):
    success: bool
    cms_draft_url: str | None             # Contentful Draft URL
    article_id: str | None                # Contentful 文章 ID
    error: str | None
```

**实现要点：**
- 使用 Contentful Management API
- 将文章发布为 Draft 状态
- 上传图片到 Contentful Assets

---

## 3. Node Boundary Table

LangGraph 节点定义，每个节点有明确的输入输出。

| 节点名 | 职责 | 输入 State 字段 | 输出 State 字段 | 并行性 |
|--------|------|-----------------|-----------------|--------|
| `download_video` | 下载视频到本地和 GCS | `video_url, project_name, task_id` | `video_local_path, video_gcs_path` | 独立 |
| `scrape_metadata` | 爬取视频+博主元数据 | `video_url` | `video_metadata` | 独立 |
| `analyze_video` | Gemini 多模态分析 | `video_gcs_path, video_metadata` | `analysis_result, frame_timestamps` | 依赖 download+metadata |
| `write_article` | 生成 Markdown 文章（含抽帧） | `video_metadata, analysis_result` | `article_markdown, article_word_count, frame_local_paths` | 依赖 analyze |
| `qc_check` | 质量检查 | `article_markdown` | `qc_result, qc_attempts` | 依赖 write |
| `rewrite_article` | 定向修改文章 | `article_markdown, qc_result` | `article_markdown` (修改后) | 依赖 qc |
| `publish_cms` | 推送到 Contentful | `article_markdown, video_metadata` | `cms_draft_url` | 依赖 qc/rewrite |

**Pipeline Stage Enum:**
```python
class PipelineStage(str):
    INIT = "init"
    DOWNLOAD = "download"
    SCRAPE_METADATA = "scrape_metadata"
    ANALYZE = "analyze"
    WRITE_ARTICLE = "write_article"
    QC_CHECK = "qc_check"
    REWRITE = "rewrite"
    PUBLISH = "publish"
    DONE = "done"
    FAILED = "failed"
```

**节点依赖关系图：**

```
[download_video] ──┐
                   │
[srape_metadata] ─┼──> [analyze_video] ──> [write_article] ──> [qc_check] ──┬──> [publish_cms]
                   │                                                        │         │
                   │                                                        ↓         │
                   │                                            (qc_passed?)          │
                   │                                                ↓              │
                   │                                    [rewrite] ──→ [qc_check 2]  │
                   │                                                             │
                   └─────────────────────────────────────────────────────────────────┘
```

**QC 决策逻辑：**
- QC 通过（所有维度≥7.0）→ 直接推送 CMS
- QC 不通过 + qc_attempts < 2 → 打回 rewrite_article → 再次 QC
- QC 不通过 + qc_attempts ≥ 2 → 直接推送 CMS（不再QC，防止死循环）

**状态文件输出：**
每个阶段完成后保存到 `data/{project_name}/pipeline_status/{task_id}_{stage}.json`：
```json
{
  "success": true,
  "task_id": "abc123",
  "stage": "write_article",
  "status": "completed",
  "progress": 0.75,
  "message": "Article written successfully (1222 words)",
  "data": {},
  "error": null,
  "timestamp": "2026-05-16T10:00:00Z",
  "can_retry": true
}
```

---

## 4. Storage Structure

### 4.1 本地存储（`data/`）

所有本地文件都在 `data/Sparki_SEO_Blog_Agent_V2/{project_name}/` 下：

```
data/
└── Sparki_SEO_Blog_Agent_V2/
    └── {project_name}/                 # 项目名隔离
        ├── raw/                        # 原始视频
        │   └── {task_id}.mp4
        ├── metadata/                   # 元数据 JSON
        │   └── {task_id}_meta.json
        ├── analysis/                   # Gemini 分析结果
        │   └── {task_id}_analysis.json
        ├── frames/                     # 抽帧图片
        │   └── {task_id}/
        │       ├── frame_00-01-23.jpg
        │       ├── frame_00-02-45.jpg
        │       └── frame_00-05-12.jpg
        ├── articles/                   # 生成的博文
        │   └── {task_id}_article.md
        ├── qc/                         # 质检结果
        │   └── {task_id}_qc.json
        └── logs/                       # 任务日志
            ├── {task_id}.log
            └── {task_id}_error.log
```

### 4.2 GCS 存储

```
gs://{GCS_BUCKET_NAME}/
└── Sparki_SEO_Blog_Agent_V2/          # 总项目文件夹
    └── {project_name}/                  # 子项目隔离
        ├── videos/                      # 原始视频备份
        │   └── {task_id}.mp4
        ├── frames/                      # 抽帧图片
        │   └── {task_id}/
        │       ├── frame_00-01-23.jpg
        │       ├── frame_00-02-45.jpg
        │       └── frame_00-05-12.jpg
        └── articles/                    # 文章备份
            └── {task_id}.md
```

### 4.3 路径构造工具函数

```python
from pathlib import Path

class StoragePaths:
    """路径构造工具，确保本地和 GCS 路径一致"""

    BASE_PREFIX = "Sparki_SEO_Blog_Agent_V2"

    @classmethod
    def local_base(cls, data_root: str, project_name: str) -> Path:
        return Path(data_root) / cls.BASE_PREFIX / project_name

    @classmethod
    def gcs_base(cls, bucket_name: str, project_name: str) -> str:
        return f"gs://{bucket_name}/{cls.BASE_PREFIX}/{project_name}"

    @classmethod
    def local_video_path(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "raw" / f"{task_id}.mp4"

    @classmethod
    def local_frames_dir(cls, data_root: str, project_name: str, task_id: str) -> Path:
        return cls.local_base(data_root, project_name) / "frames" / task_id

    @classmethod
    def gcs_video_path(cls, bucket_name: str, project_name: str, task_id: str) -> str:
        return f"{cls.gcs_base(bucket_name, project_name)}/videos/{task_id}.mp4"

    @classmethod
    def gcs_frames_dir(cls, bucket_name: str, project_name: str, task_id: str) -> str:
        return f"{cls.gcs_base(bucket_name, project_name)}/frames/{task_id}"
```

---

## 5. Git Flow

### 5.1 分支策略

```
main (稳定版本)
│
├── develop (开发分支)
│   ├── feature/video-downloader      # Claude Code 1
│   ├── feature/metadata-scraper     # Claude Code 2
│   ├── feature/video-analysis
│   ├── feature/article-writer
│   ├── feature/qc-check
│   ├── feature/cms-publisher
│   └── feature/ui-dashboard
│
└── release (发布准备)
```

### 5.2 工作流程

1. **创建功能分支**
   ```bash
   git checkout develop
   git checkout -b feature/video-downloader
   ```

2. **开发并提交**
   ```bash
   git add src/agents/nodes/video_downloader.py
   git commit -m "feat: implement video downloader tool with GCS backup"
   git push origin feature/video-downloader
   ```

3. **创建 PR 到 develop**
   - 使用 PR 模板
   - 关联 InterfaceContracts.md 中的接口定义
   - 包含测试结果

4. **Code Review 后合并到 develop**
   ```bash
   git checkout develop
   git merge feature/video-downloader
   git push origin develop
   ```

### 5.3 代码规范

- **类型标注**：所有函数必须使用 TypedDict 进行输入输出标注
- **Docstring**：每个工具类和方法需要文档字符串
- **异常处理**：工具返回 `success: False` 和 `error` 而非抛出异常
- **日志记录**：使用 `logging` 模块，关键步骤记录 INFO 级别

### 5.4 并行开发约定

1. **接口不变原则**：InterfaceContracts.md 中定义的接口为契约，任何修改需要通知所有开发者
2. **状态键一致**：所有节点使用相同的状态键（如 `video_metadata` 而非 `meta` 或 `info`）
3. **路径构造器**：使用 `StoragePaths` 工具函数构造路径，避免硬编码
4. **提交前自测**：每个工具独立测试通过后再提交 PR

---

## 附录：Type Aliases

```python
from typing import TypedDict

# 状态中使用的类型别名
VideoMetadata = dict  # 见 1.2 定义
VideoAnalysisResult = dict  # 见 1.3 定义
KeyMoment = dict  # 见 1.4 定义
QCResult = dict  # 见 1.5 定义
DimensionResult = dict  # 见 1.6 定义
Issue = dict  # 见 1.7 定义
ArticleRewriterResult = dict  # 见 1.8 定义
```

---

*本文档为并行开发的接口契约，任何修改需要与所有开发者同步。*