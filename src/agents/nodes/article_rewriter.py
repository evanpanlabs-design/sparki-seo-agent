"""Article rewriter node for Sparki SEO Blog Agent.

Performs targeted revisions on blog articles based on QC feedback.

Input:
    ArticleRewriterInput with article_markdown, qc_result

Output:
    JSON file at data/Sparki_SEO_Blog_Agent_V2/{project_name}/articles/{task_id}_revised.json
    {
        "success": bool,
        "revised_article": str,
        "revisions_applied": [...],
        "error": str | null
    }
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from src.storage.storage_paths import StoragePaths

logger = logging.getLogger(__name__)


class ArticleRewriterInput(TypedDict):
    article_markdown: str
    qc_result: dict
    project_name: str = "default"
    task_id: str


class ArticleRewriterOutput(TypedDict):
    success: bool
    revised_article: str | None
    revisions_applied: list[str]
    error: str | None


def _load_prompt_template(filename: str) -> str:
    prompt_path = Path(__file__).parent.parent.parent.parent / "configs" / "prompts" / filename
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _rewrite_with_llm(article_markdown: str, qc_result: dict) -> tuple[str, list[str]]:
    """Use LLM to rewrite the article based on QC feedback.

    Returns:
        tuple of (revised_article, list of applied revisions)
    """
    # Collect all issues from QC result - flatten to simple structure
    all_issues = []
    for dim in qc_result.get("dimensions", []):
        for issue in dim.get("issues", []):
            # Flatten: extract only what the rewriter needs
            flattened_issue = {
                "location": issue.get("location", "unknown"),
                "original": issue.get("original", ""),
                "problem": issue.get("problem", ""),
                "suggestion": issue.get("suggestion", ""),
                "revised": issue.get("revised"),  # May be None
                "dimension": dim["dimension"]
            }
            all_issues.append(flattened_issue)

    if not all_issues:
        return article_markdown, ["No issues to fix"]

    # Build flat issues list for the prompt
    issues_for_prompt = [
        {
            "location": i["location"],
            "original": i["original"],
            "problem": i["problem"],
            "suggestion": i["suggestion"],
            "revised": i["revised"] if i["revised"] else "[LLM to determine]"
        }
        for i in all_issues
    ]

    # Build optimized revision prompt
    # Group issues by type to handle YAML frontmatter specially
    yaml_issues = [i for i in all_issues if "seoKeywords" in i.get("location", "") or "seoTitle" in i.get("location", "") or "slug" in i.get("location", "")]
    body_issues = [i for i in all_issues if i not in yaml_issues]

    # Build flat issues list for the prompt
    issues_for_prompt = [
        {
            "location": i["location"],
            "original": i["original"],
            "problem": i["problem"],
            "suggestion": i["suggestion"],
            "revised": i["revised"] if i["revised"] else "[LLM to determine]"
        }
        for i in all_issues
    ]

    revision_prompt = f"""You are an expert content editor. Fix ONLY the specific issues listed below.

## CRITICAL OUTPUT FORMAT - MUST FOLLOW EXACTLY
Your output must be ONLY the revised markdown article, with:
1. The YAML frontmatter block (--- at top, --- after) kept INTACT with ALL fields preserved
2. NO text before the opening --- or after the closing ---
3. NO explanations, comments, or prefix/suffix text before or after the article
4. The article body must remain well-formed markdown

## YAML FRONTMATTER RULES
- If an issue mentions "seoKeywords", "seoTitle", "slug", or "excerpt", update ONLY those specific YAML fields
- NEVER remove or rename the title field (keep it as is, or copy seoTitle value to title if needed)
- Preserve ALL existing frontmatter fields - do not delete or rename any
- If you need to add title and it doesn't exist, use the seoTitle value
- Keep frontmatter formatting clean: "field: value" on each line
- NEVER modify the seoTitle if the issue is about seoKeywords or other fields

## CONTENT RULES
- Keep the article length nearly identical (max ±50 words difference)
- Preserve all headers, image references, and table formatting EXACTLY
- CRITICAL: Do NOT modify image paths like `../frames/...` or `triplet_...jpg` - leave them exactly as is
- If "revised" shows a replacement text, use it exactly
- If "revised" shows "[LLM to determine]", propose a fix based on "suggestion"
- For tables: preserve exact column count and row count as specified in issues
- For table "How Sparki Replicate" column: content MUST start with "Replicate by..." or "Replicate with..."
- NEVER touch image paths in the body - treat them as invariants

## ORIGINAL ARTICLE
{article_markdown}

## ISSUES TO FIX
{json.dumps(issues_for_prompt, indent=2, ensure_ascii=False)}

## OUTPUT
Return the complete revised article in Markdown format now:"""

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
            contents=[revision_prompt],
            config={
                "temperature": 0.3,
                "max_output_tokens": 8192
            }
        )

        revised_article = response.text.strip()

        # Post-process: strip markdown code fences if LLM wrapped the output
        if revised_article.startswith("```yaml"):
            revised_article = revised_article[7:]
            if revised_article.startswith("\n"):
                revised_article = revised_article[1:]
            if revised_article.endswith("```"):
                revised_article = revised_article[:-3]
            revised_article = revised_article.strip()
        elif revised_article.startswith("```"):
            fence_end = revised_article.find("\n", 3)
            if fence_end > 0:
                revised_article = revised_article[fence_end+1:]
            if revised_article.endswith("```"):
                revised_article = revised_article[:-3]
            revised_article = revised_article.strip()

        # Strip any stray characters before the YAML block (same logic as article_writer)
        yaml_start = revised_article.find("---")
        if yaml_start > 0:
            revised_article = revised_article[yaml_start:]
            logger.info(f"Rewriter: stripped {yaml_start} stray characters before YAML block")
        elif yaml_start < 0:
            # No frontmatter at all - this is a serious format violation
            logger.warning("LLM output has no frontmatter delimiter, prepending from original")
            if article_markdown.startswith("---"):
                orig_parts = article_markdown.split("---", 2)
                if len(orig_parts) >= 3:
                    revised_article = f"---{orig_parts[1]}---\n{revised_article}"
            else:
                seo_title_match = re.search(r'seoTitle:\s*["\']?(.+?)["\']?\s*$', article_markdown, re.MULTILINE)
                if seo_title_match:
                    revised_article = f'---\ntitle: "{seo_title_match.group(1).strip()}"\n---\n{revised_article}'

        # Ensure frontmatter is properly closed - find the ENDING ---
        # The format must be: --- \n frontmatter \n --- \n body
        fm_end = revised_article.find("---", 3)  # Find closing --- after opening ---
        if fm_end < 0:
            # Frontmatter not closed - this is a format violation
            logger.warning("Frontmatter not properly closed with ---, fixing")
            if "\n" in revised_article:
                lines = revised_article.split("\n", 1)
                revised_article = lines[0] + "\n---\n" + (lines[1] if len(lines) > 1 else "")

        # Now extract frontmatter and body safely
        parts = revised_article.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body_text = parts[2]

            # Ensure frontmatter has title field
            if not any(line.strip().startswith("title:") for line in fm_text.splitlines()):
                for line in fm_text.splitlines():
                    if line.strip().startswith("seoTitle:"):
                        title = line.split("seoTitle:", 1)[1].strip().strip('"').strip("'")
                        fm_text = fm_text.rstrip() + f'\ntitle: "{title}"\n'
                        break
                revised_article = f"---{fm_text}---{body_text}"
        else:
            # Split failed - article body probably consumed the closing ---
            # This happens when LLM puts content after frontmatter on same line
            logger.warning(f"Frontmatter split failed (got {len(parts)} parts), attempting repair")
            # Try to find where body starts (first line that's not frontmatter key:value)
            if len(parts) == 2 and parts[1]:
                # Try to extract frontmatter lines and find body start
                fm_and_body = parts[1]
                fm_lines = []
                body_lines = []
                in_body = False
                for line in fm_and_body.split("\n"):
                    if not in_body and ": " in line and not line.strip().startswith("#"):
                        fm_lines.append(line)
                    else:
                        in_body = True
                        body_lines.append(line)
                if fm_lines and body_lines:
                    fm_text = "\n".join(fm_lines)
                    body_text = "\n".join(body_lines)
                    # Ensure title
                    if not any(l.strip().startswith("title:") for l in fm_lines):
                        for line in fm_lines:
                            if line.strip().startswith("seoTitle:"):
                                title = line.split("seoTitle:", 1)[1].strip().strip('"').strip("'")
                                fm_text += f'\ntitle: "{title}"\n'
                                break
                    revised_article = f"---\n{fm_text}\n---\n{body_text}"

        # Build revision log
        revisions_applied = []
        for issue in all_issues:
            loc = issue.get("location", "unknown")
            dim = issue.get("dimension", "unknown")
            revised = issue.get("revised")
            status = f"[{dim}] {loc}"
            if revised:
                status += f" -> {revised[:30]}..."
            revisions_applied.append(status)

        return revised_article, revisions_applied

    except Exception as e:
        logger.error(f"LLM rewrite failed: {e}")
        raise


def _simple_rewrite(article_markdown: str, qc_result: dict) -> tuple[str, list[str]]:
    """Simple rule-based rewrite for common issues.

    This is a fallback when LLM is unavailable.
    """
    revisions_applied = []
    revised = article_markdown

    # Collect all issues
    all_issues = []
    for dim in qc_result.get("dimensions", []):
        for issue in dim.get("issues", []):
            all_issues.append(issue)

    for issue in all_issues:
        original = issue.get("original", "")
        revised_text = issue.get("revised")

        if original and revised_text and original in revised:
            revised = revised.replace(original, revised_text)
            revisions_applied.append(f"Replaced: {original[:50]}...")

    if not revisions_applied:
        revisions_applied.append("No direct replacements possible - LLM rewrite needed")

    return revised, revisions_applied


def rewrite_article(input_data: ArticleRewriterInput) -> ArticleRewriterOutput:
    """Rewrite a blog article based on QC feedback.

    Args:
        input_data: Dictionary containing article_markdown, qc_result, project_name, task_id

    Returns:
        ArticleRewriterOutput with success flag, revised article, and applied revisions
    """
    article_markdown = input_data.get("article_markdown", "")
    qc_result = input_data.get("qc_result", {})
    project_name = input_data.get("project_name", "default")
    task_id = input_data.get("task_id", "")

    logger.info(f"Starting article rewrite for task {task_id}")

    if not qc_result:
        return ArticleRewriterOutput(
            success=False,
            revised_article=None,
            revisions_applied=[],
            error="No QC result provided"
        )

    # Check if any issues exist
    has_issues = False
    for dim in qc_result.get("dimensions", []):
        if dim.get("issues"):
            has_issues = True
            break

    if not has_issues:
        logger.info(f"No issues to fix for task {task_id}")
        return ArticleRewriterOutput(
            success=True,
            revised_article=article_markdown,
            revisions_applied=["No issues to fix"],
            error=None
        )

    # Attempt LLM rewrite
    try:
        revised_article, revisions_applied = _rewrite_with_llm(article_markdown, qc_result)
    except Exception as e:
        logger.warning(f"LLM rewrite failed, falling back to simple rewrite: {e}")
        try:
            revised_article, revisions_applied = _simple_rewrite(article_markdown, qc_result)
        except Exception as e2:
            return ArticleRewriterOutput(
                success=False,
                revised_article=None,
                revisions_applied=[],
                error=f"Both LLM and simple rewrite failed: {e2}"
            )

    logger.info(
        f"Article rewrite completed for task {task_id}: "
        f"{len(revisions_applied)} revisions applied"
    )

    # Save revised article
    try:
        output_dir = StoragePaths.local_base("data", project_name) / "articles"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save as the main article file (overwrite)
        article_path = output_dir / f"{task_id}_article.md"
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(revised_article)

        # Save revision report
        report_path = output_dir / f"{task_id}_revision_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "revisions_applied": revisions_applied,
                "qc_result_summary": {
                    "passed": qc_result.get("passed"),
                    "overall_score": qc_result.get("overall_score"),
                    "dimension_count": len(qc_result.get("dimensions", []))
                }
            }, f, indent=2, ensure_ascii=False)

        logger.info(f"Revised article saved to {article_path}")

    except Exception as e:
        logger.error(f"Failed to save revised article: {e}")

    return ArticleRewriterOutput(
        success=True,
        revised_article=revised_article,
        revisions_applied=revisions_applied,
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
    qc_path = StoragePaths.local_base("data", project_name) / "qc" / f"{task_id}_qc.json"

    with open(article_path, "r", encoding="utf-8") as f:
        article_markdown = f.read()

    with open(qc_path, "r", encoding="utf-8") as f:
        qc_data = json.load(f)
        qc_result = qc_data.get("qc_result", {})

    result = rewrite_article({
        "article_markdown": article_markdown,
        "qc_result": qc_result,
        "project_name": project_name,
        "task_id": task_id
    })

    print(json.dumps({
        "success": result["success"],
        "revisions_count": len(result["revisions_applied"]),
        "revisions": result["revisions_applied"],
        "error": result["error"]
    }, indent=2, ensure_ascii=False))