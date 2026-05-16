"""Contentful publisher for Master Agent.

Implements the full Contentful CMA workflow:
1. Parse markdown (front matter + body)
2. Upload images as Assets
3. Convert Markdown to Slate JSON
4. Create Draft Entry
"""

import base64
import json
import logging
import os
import re
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

SPACE_ID = "gyre98gugxnb"
ENV = "master"
TOKEN = os.environ.get("CONTENTFUL_ACCESS_TOKEN", "") or "your-contentful-token-here"
CT_ID = "blogPost"
LOCALE = "en-US"
API_BASE = f"https://api.contentful.com/spaces/{SPACE_ID}/environments/{ENV}"
UPLOAD_BASE = f"https://upload.contentful.com/spaces/{SPACE_ID}"

CALL_INTERVAL = 0.15
_last_call = 0.0


def _api_request(url, method="GET", data=None, headers=None, timeout=30):
    """Make a Contentful API request with rate limiting."""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < CALL_INTERVAL:
        time.sleep(CALL_INTERVAL - elapsed)

    hdrs = {"Authorization": f"Bearer {TOKEN}"}
    if headers:
        hdrs.update(headers)

    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if isinstance(data, (dict, list)) else data
        if "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/vnd.contentful.management.v1+json"

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _last_call = time.time()
            if resp.status == 204:
                return {"_status": 204}
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _last_call = time.time()
        err_body = e.read().decode("utf-8")
        raise RuntimeError(f"HTTP {e.code} on {method} {url}: {err_body}") from e


class ContentfulPublisher:
    """Manages Contentful publishing with credentials."""

    def __init__(self):
        self.space_id = SPACE_ID
        self.env = ENV
        self.ct_id = CT_ID
        self.locale = LOCALE
        self.api_base = API_BASE
        self.upload_base = UPLOAD_BASE

    def _parse_markdown(self, md_text: str) -> tuple[dict, str]:
        """Parse markdown file into metadata dict and body text."""
        meta = {}
        text = md_text

        if md_text.startswith("---"):
            parts = md_text.split("---", 2)
            if len(parts) >= 3:
                fm_text = parts[1].strip()
                text = parts[2].strip()
                for line in fm_text.splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        val = val.strip().strip('"').strip("'")
                        if val.startswith("[") and val.endswith("]"):
                            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
                        meta[key.strip()] = val

        if "title" not in meta:
            if "seoTitle" in meta:
                meta["title"] = meta["seoTitle"]
            else:
                m = re.match(r"^#\s+(.+)", text, re.MULTILINE)
                if m:
                    meta["title"] = m.group(1).strip()

        if "slug" not in meta:
            slug = meta.get("title", "untitled").lower()
            slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
            slug = slug[:80]
            meta["slug"] = slug

        meta.setdefault("author", "Sparki Team")
        meta.setdefault("publishDate", time.strftime("%Y-%m-%dT00:00+08:00"))
        meta.setdefault("category", "Video Editing")
        meta.setdefault("tags", [])
        meta.setdefault("seoTitle", meta.get("title", ""))
        meta.setdefault("seoDescription", "")
        meta.setdefault("seoKeywords", [])
        meta.setdefault("excerpt", "")

        if not meta["excerpt"]:
            paragraphs = re.split(r"\n{2,}", text)
            for p in paragraphs:
                p_clean = re.sub(r"^[#>\-|].*", "", p.strip(), flags=re.MULTILINE).strip()
                p_clean = re.sub(r"!\[.*?\]\(.*?\)", "", p_clean).strip()
                p_clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", p_clean).strip()
                p_clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", p_clean).strip()
                if len(p_clean) > 30:
                    meta["excerpt"] = p_clean[:300]
                    break

        return meta, text

    def _upload_image(self, image_path: str) -> str | None:
        """Upload a local image file to Contentful and return the Asset ID."""
        path = Path(image_path)
        if not path.exists():
            logger.error(f"Image not found: {image_path}")
            return None

        file_name = path.name
        content_type_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp", ".svg": "image/svg+xml",
        }
        content_type = content_type_map.get(path.suffix.lower(), "image/jpeg")
        asset_id = f"img_{uuid.uuid4().hex[:12]}"

        print(f"  Uploading {file_name} ...", end=" ", flush=True)
        with open(path, "rb") as f:
            file_data = f.read()

        upload_url = f"{self.upload_base}/uploads"
        req = urllib.request.Request(upload_url, data=file_data, method="POST", headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/octet-stream",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                upload_result = json.loads(resp.read().decode("utf-8"))
                upload_id = upload_result["sys"]["id"]
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            logger.error(f"Upload failed for {file_name}: HTTP {e.code}: {err}")
            return None

        asset_body = {
            "fields": {
                "title": {self.locale: file_name},
                "file": {self.locale: {
                    "uploadFrom": {"sys": {"type": "Link", "linkType": "Upload", "id": upload_id}},
                    "fileName": file_name,
                    "contentType": content_type,
                }},
            }
        }
        try:
            result = _api_request(
                f"{self.api_base}/assets/{asset_id}", method="PUT", data=asset_body,
            )
            version = result["sys"]["version"]
        except Exception as e:
            logger.error(f"Asset creation failed: {e}")
            return None

        try:
            _api_request(
                f"{self.api_base}/assets/{asset_id}/files/{self.locale}/process",
                method="PUT", data={},
            )
        except Exception as e:
            logger.warning(f"Asset processing trigger failed: {e}")

        for attempt in range(10):
            time.sleep(2)
            try:
                asset = _api_request(f"{self.api_base}/assets/{asset_id}")
                if asset.get("fields", {}).get("file", {}).get(self.locale, {}).get("url"):
                    version = asset["sys"]["version"]
                    _api_request(
                        f"{self.api_base}/assets/{asset_id}/published",
                        method="PUT",
                        headers={"X-Contentful-Version": str(version)},
                    )
                    print(f"done (asset: {asset_id})")
                    return asset_id
            except Exception:
                pass

        print(f"WARNING: Asset {asset_id} processing timed out")
        return asset_id

    def _upload_all_images(self, md_text: str, md_dir: str) -> dict:
        """Find all image references in markdown, upload them, return {path: asset_id}."""
        image_map = {}
        pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        matches = re.findall(pattern, md_text)

        if not matches:
            print("No images found in markdown.")
            return image_map

        print(f"Found {len(matches)} image(s) in markdown, uploading...")
        for alt_text, img_path in matches:
            full_path = os.path.normpath(os.path.join(md_dir, img_path))
            if img_path in image_map:
                continue
            asset_id = self._upload_image(full_path)
            if asset_id:
                image_map[img_path] = asset_id

        return image_map

    def _text_node(self, value: str, marks=None) -> dict:
        return {"data": {}, "marks": marks or [], "value": value, "nodeType": "text"}

    def _parse_inline(self, text: str) -> list:
        """Parse inline markdown into Slate text/hyperlink nodes."""
        nodes = []
        pattern = r"(\[([^\]]+)\]\(([^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`"

        last = 0
        for m in re.finditer(pattern, text):
            if m.start() > last:
                plain = text[last:m.start()]
                if plain:
                    nodes.append(self._text_node(plain))

            if m.group(2) is not None:
                nodes.append({
                    "data": {"uri": m.group(3)},
                    "content": [self._text_node(m.group(2))],
                    "nodeType": "hyperlink",
                })
            elif m.group(4) is not None:
                nodes.append(self._text_node(m.group(4), [{"type": "bold"}]))
            elif m.group(5) is not None:
                nodes.append(self._text_node(m.group(5), [{"type": "italic"}]))
            elif m.group(6) is not None:
                nodes.append(self._text_node(m.group(6), [{"type": "code"}]))

            last = m.end()

        if last < len(text):
            remaining = text[last:]
            if remaining:
                nodes.append(self._text_node(remaining))

        if not nodes:
            nodes.append(self._text_node(""))

        return nodes

    def _md_to_slate(self, md_text: str, image_map: dict) -> dict:
        """Convert Markdown text to Contentful Slate JSON structure."""
        content_nodes = []
        lines = md_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            if stripped.startswith("|") and "|" in stripped[1:]:
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                for tl in table_lines:
                    if re.match(r"^\|[\s\-:|]+\|$", tl):
                        continue
                    cells = [c.strip() for c in tl.split("|")[1:-1]]
                    if len(cells) >= 3:
                        row_text = f"**{cells[0]}**: {cells[1]}"
                        if len(cells) > 2:
                            row_text += f" — {cells[2]}"
                        content_nodes.append({
                            "data": {},
                            "content": self._parse_inline(row_text),
                            "nodeType": "paragraph",
                        })
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                try:
                    content_nodes.append({
                        "data": {},
                        "content": self._parse_inline(heading_text),
                        "nodeType": f"heading-{level}",
                    })
                except re.error as e:
                    print(f"ERROR at heading line {i}: {e}")
                    print(f"  Heading text: {repr(heading_text)}")
                    raise
                i += 1
                continue

            img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
            if img_match:
                img_path = img_match.group(2)
                asset_id = image_map.get(img_path, "")
                if asset_id:
                    content_nodes.append({
                        "data": {"target": {"sys": {"id": asset_id, "type": "Link", "linkType": "Asset"}}},
                        "content": [],
                        "nodeType": "embedded-asset-block",
                    })
                else:
                    content_nodes.append({
                        "data": {},
                        "content": [self._text_node(f"[Image: {img_match.group(1) or img_path}]")],
                        "nodeType": "paragraph",
                    })
                i += 1
                continue

            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
                content_nodes.append({"data": {}, "content": [], "nodeType": "hr"})
                i += 1
                continue

            if stripped.startswith(">"):
                quote_lines = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                    i += 1
                quote_text = " ".join(quote_lines)
                content_nodes.append({
                    "data": {},
                    "content": [{"data": {}, "content": self._parse_inline(quote_text), "nodeType": "paragraph"}],
                    "nodeType": "blockquote",
                })
                continue

            if re.match(r"^[-*+]\s+", stripped):
                list_lines = []
                while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i].strip()):
                    list_lines.append(lines[i].strip())
                    i += 1
                items = []
                for ll in list_lines:
                    content_text = re.sub(r"^[-*+]\s+", "", ll)
                    items.append({
                        "data": {},
                        "content": [{"data": {}, "content": self._parse_inline(content_text), "nodeType": "paragraph"}],
                        "nodeType": "list-item",
                    })
                content_nodes.append({"data": {}, "content": items, "nodeType": "unordered-list"})
                continue

            if re.match(r"^\d+\.\s+", stripped):
                list_lines = []
                while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i].strip()):
                    list_lines.append(lines[i].strip())
                    i += 1
                items = []
                for ll in list_lines:
                    content_text = re.sub(r"^\d+\.\s+", "", ll)
                    items.append({
                        "data": {},
                        "content": [{"data": {}, "content": self._parse_inline(content_text), "nodeType": "paragraph"}],
                        "nodeType": "list-item",
                    })
                content_nodes.append({"data": {}, "content": items, "nodeType": "ordered-list"})
                continue

            para_lines = []
            while i < len(lines):
                ln = lines[i].strip()
                if not ln:
                    break
                if re.match(r"^(#{1,6}\s|!\[|>|\d+\.\s|[-*+]\s|\|)", ln):
                    break
                if re.match(r"^(-{3,}|\*{3,}|_{3,})$", ln):
                    break
                para_lines.append(ln)
                i += 1

            if para_lines:
                para_text = " ".join(para_lines)
                content_nodes.append({
                    "data": {},
                    "content": self._parse_inline(para_text),
                    "nodeType": "paragraph",
                })
                continue

            i += 1

        return {"data": {}, "content": content_nodes, "nodeType": "document"}

    def _create_draft_entry(self, meta: dict, slate_content: dict) -> dict:
        """Create a Blog Post draft entry in Contentful."""
        entry_body = {
            "fields": {
                "title": {self.locale: meta["title"]},
                "slug": {self.locale: meta["slug"]},
                "excerpt": {self.locale: meta["excerpt"]},
                "content": {self.locale: slate_content},
                "author": {self.locale: meta["author"]},
                "publishDate": {self.locale: meta["publishDate"]},
                "seoTitle": {self.locale: meta["seoTitle"]},
                "seoDescription": {self.locale: meta["seoDescription"]},
                "seoKeywords": {self.locale: meta["seoKeywords"]},
                "category": {self.locale: meta["category"]},
                "tags": {self.locale: meta["tags"]},
            }
        }

        result = _api_request(
            f"{self.api_base}/entries",
            method="POST",
            data=entry_body,
            headers={"X-Contentful-Content-Type": self.ct_id},
        )
        return result

    def publish_article(
        self,
        article_markdown: str,
        metadata: dict,
        project_name: str = "default",
        task_id: str = ""
    ) -> dict:
        """Publish article to Contentful. Returns result dict."""
        try:
            import subprocess

            # Convert relative image paths to absolute paths before publishing
            # The temp markdown file is written to articles/, so ../frames/ paths won't resolve
            data_base = Path("data/Sparki_SEO_Blog_Agent_V2").resolve()
            project_data_dir = data_base / project_name

            def _make_path_absolute(match):
                alt_text, img_path = match.group(1), match.group(2)
                if img_path.startswith("http"):
                    return f"![{alt_text}]({img_path})"
                if img_path.startswith("../"):
                    # Path like ../frames/{task_id}/... needs to be resolved from data_base
                    rel_from_data = img_path.lstrip("../")  # frames/{task_id}/...
                    abs_path = (project_data_dir / rel_from_data).resolve()
                    return f"![{alt_text}]({abs_path})"
                elif not os.path.isabs(img_path):
                    # Bare filename like triplet_0_0.5s.jpg - these are in the frames directory, not articles
                    abs_path = (project_data_dir / "frames" / task_id / img_path).resolve()
                    return f"![{alt_text}]({abs_path})"
                return f"![{alt_text}]({img_path})"

            article_markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _make_path_absolute, article_markdown)

            # Ensure frontmatter has 'title' field (reference script expects it)
            if article_markdown.startswith("---"):
                parts = article_markdown.split("---", 2)
                if len(parts) >= 3:
                    fm_text = parts[1]
                    body_text = parts[2]

                    # Fix title field
                    if not any(line.strip().startswith("title:") for line in fm_text.splitlines()):
                        for line in fm_text.splitlines():
                            if line.strip().startswith("seoTitle:"):
                                title = line.split("seoTitle:", 1)[1].strip().strip('"').strip("'")
                                fm_text = fm_text.rstrip() + f'\ntitle: "{title}"\n'
                                break

                    # Fix seoKeywords: convert comma-separated string to YAML array
                    new_fm_lines = []
                    for line in fm_text.splitlines():
                        if line.strip().startswith("seoKeywords:"):
                            val = line.split("seoKeywords:", 1)[1].strip()
                            # If it's a quoted string, convert to YAML array
                            if val.startswith('"') or val.startswith("'"):
                                keywords = val.strip().strip('"').strip("'")
                                keyword_list = [k.strip() for k in keywords.split(",")]
                                yaml_array = "[" + ", ".join(f'"{k}"' for k in keyword_list) + "]"
                                line = f"seoKeywords: {yaml_array}"
                        new_fm_lines.append(line)
                    fm_text = "\n".join(new_fm_lines)

                    article_markdown = f"---{fm_text}---{body_text}"

            # Save article to temp markdown file (unique per task to avoid race condition)
            article_dir = f"data/Sparki_SEO_Blog_Agent_V2/{project_name}/articles"
            os.makedirs(article_dir, exist_ok=True)

            # Use task_id in filename so each pipeline has its own temp file
            temp_md_path = os.path.abspath(os.path.join(article_dir, f"_temp_{task_id}_publish.md"))
            with open(temp_md_path, "w", encoding="utf-8") as f:
                f.write(article_markdown)

            # Call the reference implementation
            reference_script = "E:/2027_GET_A_JOB/Get_An_AI_Job/视界Sparki/09_ContentfulAuto/contentful_publish.py"
            result = subprocess.run(
                ["python", reference_script, temp_md_path],
                capture_output=True,
                text=True,
                timeout=300,
                cwd="E:/2027_GET_A_JOB/Get_An_AI_Job/视界Sparki/09_ContentfulAuto"
            )

            # Clean up temp file
            if task_id and os.path.exists(temp_md_path):
                os.remove(temp_md_path)

            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)

            # Parse output for entry ID and image map
            entry_id = None
            draft_url = None
            image_map = {}
            for line in result.stdout.split("\n"):
                if "Entry ID:" in line:
                    entry_id = line.split("Entry ID:")[1].strip()
                    draft_url = f"https://app.contentful.com/spaces/{self.space_id}/environments/{self.env}/entries/{entry_id}"
                # Parse "Uploading filename ... done (asset: asset_id)"
                match = re.search(r"Uploading\s+(.+?)\s+\.\.\.\s+done\s+\(asset:\s+([a-zA-Z0-9_]+)\)", line)
                if match:
                    image_map[match.group(1)] = match.group(2)

            if entry_id:
                # Get the uploaded asset IDs from parsed output
                cover_asset_id = None
                body_asset_ids = []
                for img_path, asset_id in image_map.items():
                    if "cover" in img_path.lower():
                        cover_asset_id = asset_id
                    else:
                        body_asset_ids.append(asset_id)

                if cover_asset_id:
                    print(f"  Setting coverImage: {cover_asset_id}")
                    try:
                        # Get current entry to get version
                        get_resp = _api_request(f"{self.api_base}/entries/{entry_id}")
                        version = get_resp["sys"]["version"]

                        # Update entry with coverImage (need ALL fields because PUT replaces entire entry)
                        entry_fields = get_resp.get("fields", {})
                        entry_fields["coverImage"] = {
                            self.locale: {
                                "sys": {"type": "Link", "linkType": "Asset", "id": cover_asset_id}
                            }
                        }

                        update_resp = _api_request(
                            f"{self.api_base}/entries/{entry_id}",
                            method="PUT",
                            data={"fields": entry_fields},
                            headers={"X-Contentful-Version": str(version)}
                        )
                        print(f"  coverImage set successfully")
                    except Exception as e:
                        print(f"  WARNING: Could not set coverImage: {e}")

                return {
                    "success": True,
                    "article_id": entry_id,
                    "cms_draft_url": draft_url,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "article_id": None,
                    "cms_draft_url": None,
                    "error": result.stdout + result.stderr
                }

        except Exception as e:
            logger.error(f"Contentful publish failed: {e}")
            return {
                "success": False,
                "article_id": None,
                "cms_draft_url": None,
                "error": str(e)
            }


_contentful_publisher: ContentfulPublisher | None = None


def get_contentful_publisher() -> ContentfulPublisher:
    """Get the global Contentful publisher instance."""
    global _contentful_publisher
    if _contentful_publisher is None:
        _contentful_publisher = ContentfulPublisher()
    return _contentful_publisher