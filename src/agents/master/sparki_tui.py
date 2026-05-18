"""Sparki SEO Blog Agent - TUI Interface

Rich-based rendering with proper Windows console support.
Layout: LEFT (Task Logs + Output Files) | RIGHT (AI Chat + Input).
Smart refresh: fast (0.25s) when tasks running, slow (2s) when idle.
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    # Enable Windows Virtual Terminal processing for ANSI support
    import colorama
    colorama.init()

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Rich setup
# =============================================================================

from rich.console import Console
from rich.layout import Layout
from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich import box

console = Console(force_terminal=True, color_system="standard")

# =============================================================================
# Task Manager (thread-safe)
# =============================================================================

class TaskManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._version = 0
        self._running_count = 0

    def add_task(self, task_id: str, url: str):
        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id, "url": url, "status": "pending",
                "stage": "init", "progress": 0.0, "logs": [],
                "cms_url": None, "article_path": None,
                "frame_paths": [], "video_path": None,
                "created_at": datetime.now().strftime("%H:%M:%S"),
            }
            self._version += 1
            self._running_count += 1

    def get_all(self):
        with self._lock:
            return list(self._tasks.values())

    def get(self, task_id: str):
        with self._lock:
            return self._tasks.get(task_id)

    @property
    def running_count(self) -> int:
        with self._lock:
            return self._running_count

    def update_status(self, task_id: str, status: str = None, stage: str = None,
                      progress: float = None, log: str = None, cms_url: str = None,
                      article_path: str = None, frame_paths: list = None,
                      video_path: str = None):
        with self._lock:
            if task_id not in self._tasks:
                return
            t = self._tasks[task_id]
            old_status = t.get("status")
            if status:
                if status == "done" and old_status == "running":
                    self._running_count = max(0, self._running_count - 1)
                t["status"] = status
            if stage: t["stage"] = stage
            if progress is not None: t["progress"] = progress
            if log:
                ts = datetime.now().strftime("%H:%M:%S")
                t["logs"].append(f"[{ts}] {log}")
            if cms_url: t["cms_url"] = cms_url
            if article_path: t["article_path"] = article_path
            if frame_paths: t["frame_paths"] = frame_paths
            if video_path: t["video_path"] = video_path
            self._version += 1

    def get_version(self) -> int:
        with self._lock:
            return self._version

    def get_all_files(self):
        with self._lock:
            result = {}
            for task_id, t in self._tasks.items():
                files = []
                if t.get("video_path"):
                    files.append(("video", t["video_path"]))
                if t.get("frame_paths"):
                    for fp in t["frame_paths"]:
                        files.append(("frame", fp))
                if t.get("article_path"):
                    files.append(("article", t["article_path"]))
                if files:
                    result[task_id] = {
                        "status": t["status"], "stage": t["stage"],
                        "url": t["url"], "files": files,
                        "cms_url": t.get("cms_url"),
                    }
            return result

    def scan_output_files(self):
        base = Path(__file__).parent.parent.parent / "data" / "Sparki_SEO_Blog_Agent_V2" / "default"
        if not base.exists():
            return
        ps_dir = base / "pipeline_status"
        if not ps_dir.exists():
            return

        import json
        for json_file in ps_dir.glob("*_publish.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                parts = json_file.stem.rsplit("_", 2)
                if len(parts) >= 2:
                    tid = parts[0] + "_" + parts[1]
                    if d.get("success") and d.get("data", {}).get("cms_draft_url"):
                        self.update_status(tid, status="done", stage="PUBLISHED",
                                         log="Published to Contentful",
                                         cms_url=d["data"]["cms_draft_url"])
            except:
                pass

        for json_file in ps_dir.glob("*_write_article.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                parts = json_file.stem.rsplit("_", 2)
                if len(parts) >= 2:
                    tid = parts[0] + "_" + parts[1]
                    if d.get("success") and d.get("data", {}).get("article_path"):
                        self.update_status(tid, article_path=d["data"]["article_path"])
            except:
                pass

        for json_file in ps_dir.glob("*_extract_frames.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                parts = json_file.stem.rsplit("_", 2)
                if len(parts) >= 2:
                    tid = parts[0] + "_" + parts[1]
                    if d.get("success") and d.get("data", {}).get("frame_paths"):
                        self.update_status(tid, frame_paths=d["data"]["frame_paths"])
            except:
                pass

_task_manager = TaskManager()

# =============================================================================
# Pipeline Runner
# =============================================================================

def _run_pipeline(task_id: str, video_url: str, project_name: str):
    try:
        _task_manager.update_status(task_id, "running", stage="SUBMIT", progress=0.01,
                                    log=f"Task submitted: {video_url[:60]}...")

        def progress_callback(progress: float, stage: str, message: str):
            _task_manager.update_status(task_id, "running", stage=stage,
                                        progress=progress, log=message)
            _detect_output_files(task_id, message)

        from src.agents.pipeline import run_pipeline

        result = run_pipeline(
            video_url=video_url, project_name=project_name, task_id=task_id,
            progress_callback=progress_callback,
        )

        if result and result.get("status") == "completed":
            _task_manager.update_status(task_id, "done", stage="COMPLETE", progress=1.0,
                                        log="Pipeline completed successfully!",
                                        cms_url=result.get("cms_url", ""),
                                        article_path=result.get("article_path", ""),
                                        frame_paths=result.get("frame_paths", []))
        elif result and result.get("status") == "failed":
            _task_manager.update_status(task_id, "failed", stage="FAILED",
                                        progress=result.get("progress", 0),
                                        log=f"Pipeline failed: {result.get('error', 'Unknown error')}")
        else:
            _task_manager.update_status(task_id, "done", stage="COMPLETE", progress=1.0,
                                        log="Pipeline completed")

    except Exception as e:
        logger.error(f"Pipeline error for {task_id}: {e}", exc_info=True)
        _task_manager.update_status(task_id, "failed", stage="ERROR",
                                    log=f"Error: {str(e)[:100]}")


def _detect_output_files(task_id: str, message: str):
    import re
    patterns = [
        r'([A-Za-z]:\\[^"\s]+\.(mp4|jpg|jpeg|png|md|json))',
        r'(data\\[^"\s]+\.(mp4|jpg|jpeg|png|md|json))',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, message, re.IGNORECASE)
        for match in matches:
            path = match if isinstance(match, str) else match[0]
            if path.endswith(".mp4"):
                _task_manager.update_status(task_id, video_path=path)
            elif path.endswith((".jpg", ".jpeg", ".png")):
                task = _task_manager.get(task_id)
                if task and path not in task.get("frame_paths", []):
                    frames = list(task.get("frame_paths", []))
                    frames.append(path)
                    _task_manager.update_status(task_id, frame_paths=frames)
            elif path.endswith(".md"):
                _task_manager.update_status(task_id, article_path=path)


# =============================================================================
# Key input (non-blocking)
# =============================================================================

def get_key():
    if sys.platform == "win32":
        import msvcrt
        if msvcrt.kbhit():
            c1 = msvcrt.getwche()
            if c1 == '\r':
                c1 = '\n'
            if c1 in ('\x00', '\xe0'):
                c2 = msvcrt.getwche()
                if c2 == 'H': return ('↑', True)
                if c2 == 'P': return ('↓', True)
                if c2 == 'K': return ('←', True)
                if c2 == 'M': return ('→', True)
                return (c2, False)
            return (c1, False)
        return ('', False)
    else:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            c1 = sys.stdin.read(1)
            if c1 == '\x1b':
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    c2 = sys.stdin.read(1)
                    if c2 == '[':
                        if select.select([sys.stdin], [], [], 0.1)[0]:
                            c3 = sys.stdin.read(1)
                            if c3 == 'A': return ('↑', True)
                            if c3 == 'B': return ('↓', True)
            return (c1, False)
        return ('', False)


# =============================================================================
# Rich Layout Builder
# =============================================================================

PANELS = ["logs", "files", "ai"]
PANEL_LABELS = {"logs": "TASK LOGS", "files": "OUTPUT FILES", "ai": "AI INPUT"}


def make_layout(tui, active_panel: str) -> Layout:
    layout = Layout()

    # Header: 9 lines for ASCII banner
    layout.split(
        Layout(name="header", size=9),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )

    # Body: LEFT 55% | RIGHT 45%
    layout["body"].split(
        Layout(name="left", ratio=55),
        Layout(name="right", ratio=45),
    )

    # Left: logs + files
    layout["left"].split(
        Layout(name="logs"),
        Layout(name="sep", size=1),
        Layout(name="files"),
    )

    # Right: chat + input
    layout["right"].split(
        Layout(name="chat"),
        Layout(name="input_sec"),
    )

    # ---- Header: SPARKI ASCII art ----
    banner = Text()
    banner.append("  ██████╗ ██╗██╗     ██╗     ██╗███████╗██╗ ██████╗ ███╗   ██╗\n", style="bold #4A83F9")
    banner.append("  ██╔══██╗██║██║     ██║     ██║██╔════╝██║██╔═══██╗████╗  ██║\n", style="bold #4A83F9")
    banner.append("  ██████╔╝██║██║     ██║     ██║███████╗██║██║   ██║██╔██╗ ██║\n", style="bold #4A83F9")
    banner.append("  ██╔══██╗██║██║     ██║     ██║╚════██║██║██║   ██║██║╚██╗██║\n", style="bold #4A83F9")
    banner.append("  ██████╔╝██║███████╗███████╗██║███████║██║╚██████╔╝██║ ╚████║\n", style="#4A83F9")
    banner.append("  ╚═════╝ ╚═╝╚══════╝╚══════╝╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝\n", style="#4A83F9")
    banner.append("  SEO Blogger V2", style="bold #4A83F9")
    banner.append("  —  Agentic Video-to-Blog Pipeline", style="#6B7280")

    layout["header"].update(Panel(banner, box=box.SIMPLE, border_style="#4A83F9", padding=0))

    # ---- Logs panel ----
    m = "►" if active_panel == "logs" else " "
    tid = tui.selected_task_id[:12] if tui.selected_task_id else "none"
    title_logs = f"{m} [bold #4A83F9]TASK LOGS[/]  ([#6B7280]{tid}[/#6B7280])"

    task = _task_manager.get(tui.selected_task_id) if tui.selected_task_id else None
    if not task:
        content_logs = Text("[#6B7280][No task selected — use ↑↓ to select][/#6B7280]")
    else:
        content_logs = Text()
        for log in task.get("logs", [])[max(0, len(task["logs"]) - 16):]:
            if "ERROR" in log or "✗" in log:
                content_logs.append(f"  {log}\n", style="bold #EF4444")
            elif "✓" in log:
                content_logs.append(f"  {log}\n", style="bold #10B981")
            elif "●" in log or "running" in log.lower():
                content_logs.append(f"  {log}\n", style="#4A83F9")
            elif "downloading" in log.lower():
                content_logs.append(f"  {log}\n", style="#F59E0B")
            else:
                content_logs.append(f"  {log}\n", style="#6B7280")
        if task.get("cms_url"):
            content_logs.append(f"  [#10B981]✓ CMS: {task['cms_url'][:60]}[/#10B981]\n")
        if task.get("article_path"):
            content_logs.append(f"  [#10B981]✓ Article: {Path(task['article_path']).name}[/#10B981]\n")

    layout["logs"].update(Panel(content_logs, title=title_logs, box=box.SIMPLE,
                                border_style="#4A83F9", padding=0))

    layout["sep"].update(Text(""))

    # ---- Files panel ----
    m = "►" if active_panel == "files" else " "
    title_files = f"{m} [bold #4A83F9]OUTPUT FILES[/]  ([#6B7280]auto-detect[/#6B7280])"

    all_files = _task_manager.get_all_files()
    if not all_files:
        content_files = Text("[#6B7280][No output files yet][/#6B7280]")
    else:
        content_files = Text()
        for f_task_id, info in all_files.items():
            s = info["status"]
            icon = {"running": "●", "done": "✓", "failed": "✗", "pending": "○"}.get(s, "?")
            sty = {"running": "#4A83F9", "done": "#10B981", "failed": "#EF4444", "pending": "#6B7280"}.get(s, "#6B7280")
            fname = Path(info["url"]).name[:18]
            m2 = "►" if f_task_id == tui.selected_task_id else " "
            content_files.append(f"  {m2}[{sty}]{icon}[/{sty}] [#6B7280]{f_task_id[:12]}[/#6B7280] [bold #4A83F9]{fname}[/bold #4A83F9]\n")
            for ftype, fpath in info["files"]:
                icon2 = {"video": "🎬", "frame": "🖼", "article": "📄"}.get(ftype, "📁")
                disp = f"      {icon2} {Path(fpath).name}"
                if len(disp) > 45:
                    disp = disp[:42] + "..."
                content_files.append(f"{disp}\n", style="#6B7280")

    layout["files"].update(Panel(content_files, title=title_files, box=box.SIMPLE,
                                  border_style="#4A83F9", padding=0))

    # ---- AI Chat ----
    m = "►" if active_panel == "ai" else " "
    title_chat = f"{m} [bold #4A83F9]AI ASSISTANT[/]"

    content_chat = Text()
    chat = tui.chat_history
    for role, msg in chat[max(0, len(chat) - 14):]:
        if role == "user":
            for lm in msg.split("\n")[:2]:
                content_chat.append(f"  [bold #4A83F9]You:[/#4A83F9] {lm[:55]}\n")
        else:
            for lm in msg.split("\n")[:2]:
                content_chat.append(f"  [#6B7280]AI:[/#6B7280] {lm[:55]}\n")

    layout["chat"].update(Panel(content_chat, title=title_chat, box=box.SIMPLE,
                                border_style="#4A83F9", padding=0))

    # ---- Input ----
    m = "►" if active_panel == "ai" else " "
    title_input = f"{m} [bold #4A83F9]INPUT[/]"

    buf = tui.input_buffer
    if buf:
        disp = buf[:50] + "█" if len(buf) < 50 else buf[:47] + "..."
        content_input = Text(f"  {disp}", style="white")
    else:
        content_input = Text("  [#6B7280][Type message and press Enter][/#6B7280]")

    layout["input_sec"].update(Panel(content_input, title=title_input, box=box.SIMPLE,
                                     border_style="#4A83F9", padding=0))

    # ---- Footer ----
    pl = PANEL_LABELS[active_panel]
    footer = Text()
    footer.append(f"  ► [bold #4A83F9]{pl}[/bold #4A83F9] panel active   ", style="#6B7280")
    footer.append("[#4A83F9][Tab][/] Switch   ", style="#6B7280")
    footer.append("[#4A83F9][Enter][/] Submit AI   ", style="#6B7280")
    footer.append("[#4A83F9][↑↓][/] Navigate   ", style="#6B7280")
    footer.append("[#4A83F9][o][/] Open folder   ", style="#6B7280")
    footer.append("[#EF4444][Ctrl+C][/] Quit", style="#6B7280")

    layout["footer"].update(Panel(footer, box=box.SIMPLE, border_style="#4A83F9", padding=0))

    return layout


# =============================================================================
# SparkiTUI
# =============================================================================

class SparkiTUI:
    def __init__(self):
        self.task_manager = _task_manager
        self.selected_task_id: Optional[str] = None
        self.active_panel = "logs"
        self.input_buffer = ""
        self.chat_history = []
        self._init_chat()

    def _init_chat(self):
        self.chat_history = [
            ("assistant", "Welcome to SEO Blogger V2!\n\n"
                         "Paste a TikTok/Instagram URL to start.\n"
                         "Commands: /status /open /help\n\n"
                         "Tab=switch panels, ↑↓=navigate tasks.")
        ]

    def submit_url(self, url: str):
        if not url:
            return
        platform = "TikTok" if "tiktok.com" in url else "Instagram" if "instagram.com" in url else "Unknown"
        import uuid
        task_id = str(uuid.uuid4())
        self.task_manager.add_task(task_id, url)
        self.selected_task_id = task_id
        self.chat_history.append(("user", url))
        self.chat_history.append(("assistant", f"✓ {platform} task submitted. Use /status to track."))
        t = threading.Thread(target=_run_pipeline, args=(task_id, url, "default"), daemon=True)
        t.start()

    def handle_command(self, text: str):
        if not text:
            return
        if text.startswith("/"):
            self._handle_cmd(text)
        elif text.startswith("http"):
            self.submit_url(text)
        else:
            self._handle_chat(text)

    def _handle_cmd(self, text: str):
        cmd = text.lower()
        if cmd == "/status":
            tasks = self.task_manager.get_all()
            if not tasks:
                self.chat_history.append(("assistant", "No tasks."))
            else:
                self.chat_history.append(("assistant", "\n".join(
                    f"[{t['status'].upper()}] {t['stage']} - {t['progress']:.0%}" for t in tasks)))
        elif cmd == "/help":
            self.chat_history.append(("assistant", "Commands:\n/status /open /help\nTab=switch panels, ↑↓=navigate"))
        elif cmd == "/open":
            self._open_output_folder()
        else:
            self.chat_history.append(("assistant", f"Unknown: {text}"))

    def _handle_chat(self, text: str):
        from src.agents.master import get_llm_client
        llm = get_llm_client()
        if not llm.is_configured():
            self.chat_history.append(("assistant", "LLM not configured. Paste a URL to start."))
            return
        tasks = self.task_manager.get_all()
        task_info = "\n".join([f"- {t['task_id'][:8]}: {t['status']}" for t in tasks]) or "No tasks."
        try:
            response = llm.generate(prompt=text, system=f"Tasks:\n{task_info}\n\nUser: {text}")
            if response:
                self.chat_history.append(("assistant", response))
        except Exception as e:
            self.chat_history.append(("assistant", f"Error: {str(e)[:80]}"))

    def _open_output_folder(self):
        from src.storage.storage_paths import StoragePaths
        try:
            base = StoragePaths.local_base("data", "default")
            if base.exists():
                os.startfile(base)
                self.chat_history.append(("assistant", f"Opened: {base}"))
        except Exception as e:
            self.chat_history.append(("assistant", f"Error: {e}"))


# =============================================================================
# Main Loop
# =============================================================================

def run_tui():
    tui = SparkiTUI()
    last_render_version = -1

    def make_layout_fn():
        return make_layout(tui, tui.active_panel)

    try:
        with Live(make_layout_fn(), console=console,
                  refresh_per_second=4, transient=False, screen=False) as live:

            while True:
                current_version = _task_manager.get_version()

                # Re-render only when state changed
                if current_version != last_render_version:
                    live.update(make_layout_fn())
                    last_render_version = current_version

                # Process input (non-blocking)
                key, is_arrow = get_key()
                if not key:
                    time.sleep(0.05)
                    continue

                if key == '\x03':
                    console.print("\n[#10B981]Goodbye![/#10B981]")
                    break

                elif key == '\t':
                    idx = PANELS.index(tui.active_panel)
                    tui.active_panel = PANELS[(idx + 1) % len(PANELS)]
                    live.update(make_layout_fn())
                    last_render_version = current_version

                elif key == '\n' or key == '\r':
                    if tui.active_panel == "ai" and tui.input_buffer.strip():
                        tui.handle_command(tui.input_buffer)
                        tui.input_buffer = ""
                        live.update(make_layout_fn())
                        last_render_version = _task_manager.get_version()
                    else:
                        idx = PANELS.index(tui.active_panel)
                        tui.active_panel = PANELS[(idx + 1) % len(PANELS)]
                        live.update(make_layout_fn())
                        last_render_version = current_version

                elif key in ('\x7f', '\x08'):
                    if tui.active_panel == "ai" and tui.input_buffer:
                        tui.input_buffer = tui.input_buffer[:-1]
                        live.update(make_layout_fn())
                        last_render_version = current_version

                elif is_arrow:
                    tasks = _task_manager.get_all()
                    if tasks:
                        if not tui.selected_task_id:
                            tui.selected_task_id = tasks[0]["task_id"]
                            live.update(make_layout_fn())
                            last_render_version = current_version
                        else:
                            idx = next((i for i, t in enumerate(tasks)
                                      if t["task_id"] == tui.selected_task_id), -1)
                            changed = False
                            if key == '↑' and idx > 0:
                                tui.selected_task_id = tasks[idx - 1]["task_id"]
                                changed = True
                            elif key == '↓' and idx < len(tasks) - 1:
                                tui.selected_task_id = tasks[idx + 1]["task_id"]
                                changed = True
                            if changed:
                                live.update(make_layout_fn())
                                last_render_version = current_version

                elif key in ('o', 'O'):
                    tui._open_output_folder()

                elif key.isprintable():
                    tui.active_panel = "ai"
                    tui.input_buffer += key
                    live.update(make_layout_fn())
                    last_render_version = current_version

                time.sleep(0.05)

    except KeyboardInterrupt:
        console.print("\n[#10B981]Goodbye![/#10B981]")
    except Exception as e:
        logger.error(f"TUI error: {e}", exc_info=True)


if __name__ == "__main__":
    run_tui()