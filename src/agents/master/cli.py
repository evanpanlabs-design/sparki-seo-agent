"""Simple CLI interface for Master Agent.

Usage:
    python -m src.agents.master.cli
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Run interactive Master Agent CLI."""
    from src.agents.master import (
        get_conversation_manager,
        get_intent_router,
        get_project_manager,
        get_pipeline_pool,
    )

    cm = get_conversation_manager()
    router = get_intent_router()
    pm = get_project_manager()
    pool = get_pipeline_pool()

    print("=" * 60)
    print("Sparki Master Agent - Video to Blog CLI")
    print("=" * 60)
    print("Commands:")
    print("  submit <url>          - Process a single video")
    print("  batch <url1> <url2>.. - Process multiple videos (max 10)")
    print("  status                - Show all task statuses")
    print("  projects              - List all projects")
    print("  help                  - Show this help")
    print("  exit                  - Exit")
    print("=" * 60)

    session_id = cm.create_session()
    print(f"Session created: {session_id[:8]}...")

    current_project = pm.get_or_create_project("default")

    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break

            if user_input.lower() == "help":
                print("\nCommands:")
                print("  submit <url>          - Process a single video")
                print("  batch <url1> <url2>.. - Process multiple videos")
                print("  status                - Show task statuses")
                print("  projects              - List projects")
                print("  exit                  - Exit")
                continue

            if user_input.lower() == "status":
                all_tasks = pool.get_all_status()
                if not all_tasks:
                    print("No running tasks.")
                for task in all_tasks:
                    print(f"  [{task.status}] {task.task_id[:8]} - {task.current_stage} ({task.progress*100:.0f}%)")
                continue

            if user_input.lower() == "projects":
                projects = pm.list_projects()
                for p in projects[:10]:
                    print(f"  {p['name']} - {p['current_status']} - {len(p.get('video_urls', []))} videos")
                continue

            intent = router.classify_intent(user_input)
            print(f"Detected intent: {intent['intent']}, URLs: {intent['video_urls']}")

            if intent["intent"] == "VIDEO_SUBMIT" and intent["video_urls"]:
                url = intent["video_urls"][0]
                print(f"Processing video: {url}")

                task_id = pool.submit(
                    video_url=url,
                    project_name=current_project["name"]
                )
                print(f"Task submitted: {task_id[:8]}...")

                pm.add_video_to_project(current_project["project_id"], url)

            elif intent["intent"] == "BATCH_SUBMIT" and intent["video_urls"]:
                urls = intent["video_urls"]
                valid, err, valid_urls = router.validate_batch(urls)
                if not valid:
                    print(f"Error: {err}")
                    continue

                print(f"Processing batch of {len(valid_urls)} videos...")

                for url in valid_urls:
                    task_id = pool.submit(
                        video_url=url,
                        project_name=current_project["name"]
                    )
                    pm.add_video_to_project(current_project["project_id"], url)
                    print(f"  Task submitted: {task_id[:8]}...")

            elif intent["intent"] == "STATUS_QUERY":
                all_tasks = pool.get_all_status()
                for task in all_tasks:
                    print(f"  [{task.status}] {task.task_id[:8]} - {task.video_url[:50]}")

            elif intent["intent"] == "unknown" and not intent["video_urls"]:
                # General conversation - use LLM
                from src.agents.master import get_llm_client
                llm = get_llm_client()

                if not llm.is_configured():
                    print("我还没有配置LLM。可以用 submit <url> 来提交视频任务。")
                else:
                    # Build conversation context
                    recent = cm.get_recent_messages(session_id)
                    history = "\n".join([f"{m['role']}: {m['content']}" for m in recent[-10:]])

                    system_prompt = """你是一个友好的AI助手，帮助用户处理视频内容分析任务。
用户可以提交Instagram或TikTok视频链接，你会生成博客文章。
常用命令：submit <url> 提交视频，status 查看进度，projects 查看项目列表。"""

                    response = llm.generate(
                        prompt=f"对话历史：\n{history}\n\n用户最新消息：{user_input}",
                        system=system_prompt
                    )

                    if response:
                        print(f"\n{response}")
                        cm.save_message(session_id, "assistant", response)
                    else:
                        print("抱歉，LLM响应失败。请稍后重试。")
                continue

        except KeyboardInterrupt:
            print("\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    main()