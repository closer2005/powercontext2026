"""导入 data/samples/ 下的示例 Markdown 笔记（幂等：按 title 判重）。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app import db, services

logger = logging.getLogger(__name__)

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str] | None:
    """解析 YAML-like front matter，返回 (meta, body)。无合法 front-matter 返回 None。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    meta: Dict[str, str] = {}
    body = m.group(2).strip()
    try:
        for line in m.group(1).split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
    except Exception as e:
        logger.warning("Front-matter parse error: %s", e)
        return None
    return meta, body


def _load_sample_files() -> List[Dict[str, Any]]:
    """扫描 data/samples/*.md，返回解析后的笔记列表。"""
    if not SAMPLES_DIR.exists():
        logger.warning("Samples directory not found: %s", SAMPLES_DIR)
        return []

    notes: List[Dict[str, Any]] = []
    for md_file in sorted(SAMPLES_DIR.glob("*.md")):
        if md_file.name == "README.md":
            logger.debug("Skipping README.md")
            continue
        text = md_file.read_text(encoding="utf-8")
        parsed = _parse_frontmatter(text)
        if parsed is None:
            logger.warning("Skipping %s: no valid YAML front-matter", md_file.name)
            continue
        meta, body = parsed
        if not meta.get("title"):
            logger.warning("Skipping %s: front-matter missing 'title'", md_file.name)
            continue
        notes.append({
            "title": meta["title"],
            "course": meta.get("course", ""),
            "topic": meta.get("topic", ""),
            "tags": meta.get("tags", ""),
            "source": meta.get("source", md_file.name),
            "content": body,
        })
    return notes


def import_samples() -> Dict[str, int]:
    """幂等导入示例数据。返回 {imported, skipped}。"""
    samples = _load_sample_files()
    imported = 0
    skipped = 0

    for note in samples:
        existing = db.get_note_by_title(note["title"])
        if existing:
            skipped += 1
            logger.debug("Skipping duplicate note: %s", note["title"])
            continue
        try:
            services.import_note(**note)
            imported += 1
        except Exception as e:
            logger.error("Failed to import '%s': %s", note["title"], e)
            skipped += 1

    logger.info("Sample import done: %d imported, %d skipped", imported, skipped)
    return {"imported": imported, "skipped": skipped}
