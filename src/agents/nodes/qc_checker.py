"""QC checker node for Sparki SEO Blog Agent.

Performs quality control on generated blog articles.

Input:
    QCCheckerInput with article_markdown, metadata, analysis_result

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/qc/{task_id}_qc.json
    {
        "success": bool,
        "qc_result": {
            "passed": bool,
            "overall_score": float,
            "dimensions": [...],
            "checked_at": str
        },
        "error": str | null
    }
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.storage.storage_paths import StoragePaths

logger = logging.getLogger(__name__)


class QCCheckerInput(TypedDict):
    article_markdown: str
    metadata_json_path: str
    analysis_json_path: str
    project_name: str = "default"
    task_id: str


class QCCheckerOutput(TypedDict):
    success: bool
    qc_result: dict | None
    error: str | None


def _load_prompt_template(filename: str) -> str:
    prompt_path = Path(__file__).parent.parent.parent.parent / "configs" / "prompts" / filename
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_json_response(response_text: str) -> dict:
    # Try to extract JSON from the response
    try:
        # Handle potential markdown code blocks
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        parsed = json.loads(text.strip())
        logger.info(f"QC JSON parsed successfully, keys: {list(parsed.keys())}")

        # Validate and normalize the structure
        validated = _validate_qc_result(parsed)
        return validated
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response text was: {response_text[:500]}")
        # Return a minimal valid structure
        return {
            "passed": False,
            "overall_score": 0.0,
            "dimensions": []
        }


def _validate_qc_result(result: dict) -> dict:
    """Validate and normalize QC result to match expected schema."""
    required_dims = ["metadata", "seo_keywords", "fluency", "factuality", "non_generic", "replication_table"]

    validated = {
        "passed": result.get("passed", False),
        "overall_score": result.get("overall_score", 0.0),
        "dimensions": []
    }

    for dim_name in required_dims:
        dim_found = None
        for dim in result.get("dimensions", []):
            if dim.get("dimension") == dim_name:
                dim_found = dim
                break

        if dim_found:
            validated["dimensions"].append({
                "dimension": dim_name,
                "score": dim_found.get("score", 0.0),
                "issues": dim_found.get("issues", []),
                "suggestions": dim_found.get("suggestions", [])
            })
        else:
            # Dimension not found in response, add empty entry
            validated["dimensions"].append({
                "dimension": dim_name,
                "score": 0.0,
                "issues": [],
                "suggestions": [f"Dimension {dim_name} was not evaluated"]
            })

    # Recalculate passed based on all dimensions >= 7.0
    all_passed = all(d["score"] >= 7.0 for d in validated["dimensions"])
    validated["passed"] = all_passed

    # Recalculate overall score as average
    if validated["dimensions"]:
        validated["overall_score"] = sum(d["score"] for d in validated["dimensions"]) / len(validated["dimensions"])

    return validated


def qc_check(input_data: QCCheckerInput) -> QCCheckerOutput:
    """Perform quality control on a blog article.

    Args:
        input_data: Dictionary containing article_markdown, metadata_json_path,
                   analysis_json_path, project_name, task_id

    Returns:
        QCCheckerOutput with success flag and qc_result
    """
    article_markdown = input_data.get("article_markdown", "")
    metadata_json_path = input_data.get("metadata_json_path", "")
    analysis_json_path = input_data.get("analysis_json_path", "")
    project_name = input_data.get("project_name", "default")
    task_id = input_data.get("task_id", "")

    logger.info(f"Starting QC check for task {task_id}")

    # Load metadata and analysis
    try:
        with open(metadata_json_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load metadata: {e}")
        metadata = {}

    try:
        with open(analysis_json_path, "r", encoding="utf-8") as f:
            analysis_result = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load analysis result: {e}")
        analysis_result = {}

    # Load QC prompt template
    try:
        qc_prompt = _load_prompt_template("qc_check_unified.txt")
    except Exception as e:
        logger.error(f"Failed to load QC prompt: {e}")
        return QCCheckerOutput(
            success=False,
            qc_result=None,
            error=f"Failed to load QC prompt: {e}"
        )

    # Format the prompt with actual content
    # Prepare metadata string for prompt
    metadata_str = json.dumps(metadata, indent=2, ensure_ascii=False)
    analysis_str = json.dumps(analysis_result, indent=2, ensure_ascii=False)

    # Use string replacement instead of str.format() to avoid curly brace conflicts
    # Curly braces in YAML frontmatter and JSON content conflict with format placeholders
    formatted_prompt = qc_prompt.replace("{blog_content}", article_markdown)
    formatted_prompt = formatted_prompt.replace("{metadata}", metadata_str)
    formatted_prompt = formatted_prompt.replace("{analysis_result}", analysis_str)

    # Call LLM for QC check
    # Using Gemini via Vertex AI
    try:
        from google import genai
        from src.config import get_gcp_config

        gcp_config = get_gcp_config()
        project_id = gcp_config.get("project_id", "sparki-op")

        client = genai.Client(
            vertexai=True,
            project=project_id,
            location="global",
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[formatted_prompt],
            config={
                "response_mime_type": "application/json",
            }
        )

        qc_result = _parse_json_response(response.text)

    except Exception as e:
        logger.error(f"QC check failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return QCCheckerOutput(
            success=False,
            qc_result=None,
            error=f"QC check failed: {e}"
        )

    # Enrich the QC result with timestamp
    qc_result["checked_at"] = datetime.now(timezone.utc).isoformat()

    # Determine if revision is needed
    revision_needed = not qc_result.get("passed", False)

    logger.info(
        f"QC check completed for task {task_id}: "
        f"passed={qc_result.get('passed')}, "
        f"overall_score={qc_result.get('overall_score'):.1f}, "
        f"revision_needed={revision_needed}"
    )

    # Save QC result to file
    try:
        qc_output_dir = StoragePaths.local_base(
            "data", project_name
        ) / "qc"
        qc_output_dir.mkdir(parents=True, exist_ok=True)

        output_path = qc_output_dir / f"{task_id}_qc.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "success": True,
                "qc_result": qc_result,
                "revision_needed": revision_needed
            }, f, indent=2, ensure_ascii=False)

        logger.info(f"QC result saved to {output_path}")

    except Exception as e:
        logger.error(f"Failed to save QC result: {e}")

    return QCCheckerOutput(
        success=True,
        qc_result=qc_result,
        error=None
    )


# Standalone test
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-name", default="test_instagram")
    args = parser.parse_args()

    task_id = args.task_id
    project_name = args.project_name

    # Load the article
    article_path = StoragePaths.local_base("data", project_name) / "articles" / f"{task_id}_article.md"
    metadata_path = StoragePaths.local_base("data", project_name) / "metadata" / f"{task_id}_meta.json"
    analysis_path = StoragePaths.local_base("data", project_name) / "analysis" / f"{task_id}_analysis.json"

    with open(article_path, "r", encoding="utf-8") as f:
        article_markdown = f.read()

    result = qc_check({
        "article_markdown": article_markdown,
        "metadata_json_path": str(metadata_path),
        "analysis_json_path": str(analysis_path),
        "project_name": project_name,
        "task_id": task_id
    })

    print(json.dumps(result, indent=2, ensure_ascii=False))