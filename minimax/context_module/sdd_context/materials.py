"""Engineering material extraction: specifications, code units and tests.

Everything indexed into seekdb is produced here so the store layer only deals
with rows. Extraction is deterministic: symbol names, line ranges and content
checksums can be re-derived from the repository at any time.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


# ---------------------------------------------------------------------------
# tokenisation (seekdb full-text friendly: whitespace separated terms)
# ---------------------------------------------------------------------------

def tokenize(text: str) -> str:
    """Split mixed Chinese/English text into whitespace separated terms.

    English identifiers are lower-cased as whole words; Chinese runs are split
    into character bigrams (plus single characters for one-character runs), the
    usual strategy for keyword matching without a Chinese segmenter.
    """
    terms: list[str] = [word.lower() for word in _WORD_RE.findall(text)]
    for segment in _CJK_RE.findall(text):
        if len(segment) == 1:
            terms.append(segment)
        else:
            terms.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return " ".join(terms)


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# material model
# ---------------------------------------------------------------------------

@dataclass
class Material:
    kind: str  # spec | code | test
    mat_id: str
    path: str
    anchor: str
    title: str
    content: str
    tokenized: str
    symbol: str | None = None
    spec_id: str | None = None
    revision: int | None = None
    status: str = "active"
    tags: str = ""
    line_start: int | None = None
    line_end: int | None = None
    digest: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.digest:
            self.digest = checksum(self.content)


def _front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    header = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, object] = {}
    for line in header.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key, raw = key.strip(), raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            items = [item.strip().strip('"').strip("'") for item in raw[1:-1].split(",")]
            meta[key] = [item for item in items if item]
        elif re.fullmatch(r"-?\d+", raw):
            meta[key] = int(raw)
        else:
            meta[key] = raw.strip('"').strip("'")
    return meta, body


# ---------------------------------------------------------------------------
# specification extraction
# ---------------------------------------------------------------------------

def extract_specs(project_root: Path) -> list[Material]:
    """Extract every ``specs/**/*.md`` file, honouring YAML front matter."""
    materials: list[Material] = []
    spec_dir = project_root / "specs"
    if not spec_dir.is_dir():
        return materials
    for path in sorted(spec_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _front_matter(text)
        spec_id = str(meta.get("spec_id") or path.stem.split(".")[0])
        revision = int(meta.get("revision") or 1)
        rel = path.relative_to(project_root).as_posix()
        title = ""
        for line in body.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        terms = " ".join(str(meta.get(key, "")) for key in ("tags", "title"))
        material = Material(
            kind="spec",
            mat_id=f"spec:{spec_id}:r{revision}",
            path=rel,
            anchor=f"{spec_id}#r{revision}",
            title=title or f"{spec_id} revision {revision}",
            content=text,
            tokenized=tokenize(f"{spec_id} {title} {terms} {body}"),
            spec_id=spec_id,
            revision=revision,
            status="active",
            tags=",".join(str(t) for t in (meta.get("tags") or [])),
            line_start=1,
            line_end=len(text.splitlines()),
            meta={"declared_status": meta.get("status", "active"), "effective_from": meta.get("effective_from")},
        )
        materials.append(material)
    return materials


def resolve_spec_versions(specs: list[Material]) -> list[Material]:
    """Mark the highest revision of each spec id active, the rest superseded."""
    by_spec: dict[str, list[Material]] = {}
    for material in specs:
        assert material.spec_id is not None
        by_spec.setdefault(material.spec_id, []).append(material)
    resolved: list[Material] = []
    for spec_id, versions in by_spec.items():
        versions.sort(key=lambda item: (item.revision or 0), reverse=True)
        for index, material in enumerate(versions):
            material.status = "active" if index == 0 else "superseded"
            resolved.append(material)
    return resolved


# ---------------------------------------------------------------------------
# source code extraction
# ---------------------------------------------------------------------------

def _module_name(project_root: Path, path: Path) -> str:
    rel = path.relative_to(project_root).with_suffix("")
    parts = [part for part in rel.parts if part not in ("src", "lib")]
    return ".".join(parts)


def extract_code_units(project_root: Path, include: list[str] | None = None) -> list[Material]:
    """Extract top-level functions and classes from Python sources via ``ast``."""
    materials: list[Material] = []
    candidates = project_root / "src"
    files: list[Path] = []
    if include:
        for item in include:
            target = (project_root / item).resolve()
            if target.is_file():
                files.append(target)
            elif target.is_dir():
                files.extend(sorted(target.rglob("*.py")))
    elif candidates.is_dir():
        files = sorted(candidates.rglob("*.py"))
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(project_root).as_posix()
        module = _module_name(project_root, path)
        body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        for node in body:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            segment = ast.get_source_segment(source, node) or ""
            symbol = f"{node.name}"
            docstring = ast.get_docstring(node) or ""
            material = Material(
                kind="code",
                mat_id=f"code:{rel}:{node.name}",
                path=rel,
                anchor=f"{rel}::{node.name}",
                title=node.name,
                content=segment,
                tokenized=tokenize(f"{module} {node.name} {docstring} {segment}"),
                symbol=symbol,
                tags=module,
                line_start=start,
                line_end=end,
                meta={"module": module, "node_type": type(node).__name__},
            )
            materials.append(material)
    return materials


# ---------------------------------------------------------------------------
# test extraction
# ---------------------------------------------------------------------------

def extract_tests(project_root: Path) -> list[Material]:
    """Extract every ``test_*`` function from ``tests/**/*.py``."""
    materials: list[Material] = []
    tests_dir = project_root / "tests"
    if not tests_dir.is_dir():
        return materials
    for path in sorted(tests_dir.rglob("test_*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(project_root).as_posix()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            segment = ast.get_source_segment(source, node) or ""
            docstring = ast.get_docstring(node) or ""
            material = Material(
                kind="test",
                mat_id=f"test:{rel}:{node.name}",
                path=rel,
                anchor=f"{rel}::{node.name}",
                title=node.name,
                content=segment,
                tokenized=tokenize(f"{node.name} {docstring} {segment}"),
                symbol=node.name,
                tags=rel,
                line_start=start,
                line_end=end,
                meta={"file": rel},
            )
            materials.append(material)
    return materials


def all_materials(project_root: Path, code_include: list[str] | None = None) -> dict[str, list[Material]]:
    specs = resolve_spec_versions(extract_specs(project_root))
    return {
        "spec": specs,
        "code": extract_code_units(project_root, code_include),
        "test": extract_tests(project_root),
    }