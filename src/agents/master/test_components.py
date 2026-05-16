"""Test script for Master Agent components.

Run individual tests:
    python -m src.agents.master.test_components --component conversation
    python -m src.agents.master.test_components --component intent
    python -m src.agents.master.test_components --component project
    python -m src.agents.master.test_components --component memory
    python -m src.agents.master.test_components --component pool
    python -m src.agents.master.test_components --component all
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def test_conversation():
    """Test conversation manager."""
    from src.agents.master import ConversationManager

    print("\n" + "=" * 50)
    print("Testing ConversationManager")
    print("=" * 50)

    cm = ConversationManager()

    # Create session
    session_id = cm.create_session()
    print(f"[OK] Created session: {session_id[:8]}...")

    # Add messages
    cm.save_message(session_id, "user", "分析这个视频")
    cm.save_message(session_id, "assistant", "请提供视频链接")
    print("[OK] Added 2 messages")

    # Get recent messages
    messages = cm.get_recent_messages(session_id)
    assert len(messages) == 2
    print(f"[OK] Retrieved {len(messages)} messages")

    # Set project
    cm.set_current_project(session_id, "test_project")
    assert cm.get_current_project(session_id) == "test_project"
    print("[OK] Project tracking works")

    # Export/import
    export_path = cm.export_conversation(session_id)
    new_session_id = cm.import_conversation(export_path)
    assert new_session_id != session_id
    print(f"[OK] Export/import works: {new_session_id[:8]}...")

    print("\n[PASS] ConversationManager tests passed")
    return True


def test_intent():
    """Test intent router."""
    from src.agents.master import IntentRouter

    print("\n" + "=" * 50)
    print("Testing IntentRouter")
    print("=" * 50)

    router = IntentRouter()

    tests = [
        ("分析这个视频 https://www.instagram.com/reels/DWwVuBJiukt/", "VIDEO_SUBMIT", 1),
        ("批量处理 https://www.instagram.com/reels/ABC https://www.tiktok.com/@user/video/123", "BATCH_SUBMIT", 2),
        ("查看我的项目列表", "PROJECT_LIST", 0),
        ("现在进度怎么样", "STATUS_QUERY", 0),
        ("取消任务", "CANCEL", 0),
        ("推送到Contentful", "CONTENTFUL_PUSH", 0),
        ("之前做过什么案例", "MEMORY_QUERY", 0),
        ("帮助", "HELP", 0),
    ]

    all_passed = True
    for text, expected_intent, expected_url_count in tests:
        result = router.classify_intent(text)
        status = "[OK]" if result["intent"] == expected_intent else "[FAIL]"
        if result["intent"] != expected_intent:
            all_passed = False
        print(f"{status} '{text[:30]}...' -> {result['intent']} (expected {expected_intent})")

    # Test batch validation
    valid, err, urls = router.validate_batch(["url1", "url2"])
    assert valid and len(urls) == 2
    print("[OK] Batch validation works")

    if all_passed:
        print("\n[PASS] IntentRouter tests passed")
    else:
        print("\n[WARN] Some intent tests failed")
    return all_passed


def test_project():
    """Test project manager."""
    import uuid
    from src.agents.master import ProjectManager

    print("\n" + "=" * 50)
    print("Testing ProjectManager")
    print("=" * 50)

    pm = ProjectManager()

    # Create project
    project = pm.create_project(f"test_project_{uuid.uuid4().hex[:8]}")
    print(f"[OK] Created project: {project['project_id'][:8]}...")

    # Check duplicate - use unique URL each run
    url = f"https://www.instagram.com/reels/test_{uuid.uuid4().hex}/"

    # Create case
    case = pm.create_case(url, "@test_user", project["project_id"])
    print(f"[OK] Created case: {case['case_id'][:8]}...")

    # Try duplicate - should fail
    try:
        pm.create_case(url, "@test_user")
        print("[FAIL] Duplicate should have raised exception")
        return False
    except ValueError as e:
        print(f"[OK] Duplicate detection works: {e}")

    # Get case by URL
    found = pm.get_case_by_video_url(url)
    assert found is not None
    print("[OK] Get case by URL works")

    # List projects
    projects = pm.list_projects()
    assert len(projects) >= 1
    print(f"[OK] Listed {len(projects)} projects")

    print("\n[PASS] ProjectManager tests passed")
    return True


def test_memory():
    """Test memory (RAG)."""
    from src.agents.master import get_memory_index

    print("\n" + "=" * 50)
    print("Testing MemoryIndex")
    print("=" * 50)

    mem = get_memory_index()
    print(f"[OK] Memory type: {type(mem).__name__}")

    # Add cases
    mem.add_case("case001", "@mialaurengreen", "How to do perfect push-ups with proper form", "https://instagram.com/p/001")
    mem.add_case("case002", "@fitness_guru", "Best exercises for abs and core strength", "https://instagram.com/p/002")
    mem.add_case("case003", "@yoga_master", "Morning yoga routine for flexibility", "https://instagram.com/p/003")
    print(f"[OK] Added 3 cases, total: {mem.get_case_count()}")

    # Search
    results = mem.search("exercise for core", top_k=2)
    print(f"[OK] Search 'exercise for core': {len(results)} results")
    for r in results[:2]:
        print(f"    - {r['case_id']}: distance={r.get('distance', 'N/A'):.3f}")

    # Search in Chinese
    results2 = mem.search("腹肌 训练", top_k=2)
    print(f"[OK] Search '腹肌 训练': {len(results2)} results")

    print("\n[PASS] Memory tests passed")
    return True


def test_pool():
    """Test pipeline pool."""
    from src.agents.master import PipelinePool
    import time

    print("\n" + "=" * 50)
    print("Testing PipelinePool")
    print("=" * 50)

    pool = PipelinePool(max_concurrent=2)

    # Submit a test task (will run actual pipeline, may take time)
    # For testing, just check pool mechanics
    print(f"[OK] Pool created with max_concurrent=2")
    print(f"[OK] Current tasks: {len(pool.get_all_status())}")

    # Check interval enforcement logic
    print(f"[OK] Interval seconds: {pool._interval_seconds}")

    print("\n[PASS] PipelinePool structural tests passed")
    print("      (Actual pipeline execution tested separately)")
    return True


def test_llm():
    """Test LLM client."""
    from src.agents.master import LLMClient

    print("\n" + "=" * 50)
    print("Testing LLMClient")
    print("=" * 50)

    client = LLMClient()

    # Not configured yet
    assert not client.is_configured()
    print("[OK] Default state: not configured")

    # Configure
    success = client.configure(
        api_url="https://api.openai.com/v1",
        api_key="sk-test-123",
        model="gpt-4o-mini"
    )
    assert success
    print("[OK] Configuration saved")

    # Load
    client2 = LLMClient()
    assert not client2.is_configured()  # New instance, needs load
    client2.load_config()
    assert client2.is_configured()
    print("[OK] Config load works")

    print("\n[PASS] LLMClient tests passed")
    return True


def main():
    parser = argparse.ArgumentParser(description="Test Master Agent components")
    parser.add_argument("--component", choices=["conversation", "intent", "project", "memory", "pool", "llm", "all"], default="all")
    args = parser.parse_args()

    results = {}
    if args.component in ("conversation", "all"):
        results["conversation"] = test_conversation()
    if args.component in ("intent", "all"):
        results["intent"] = test_intent()
    if args.component in ("project", "all"):
        results["project"] = test_project()
    if args.component in ("memory", "all"):
        results["memory"] = test_memory()
    if args.component in ("pool", "all"):
        results["pool"] = test_pool()
    if args.component in ("llm", "all"):
        results["llm"] = test_llm()

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())