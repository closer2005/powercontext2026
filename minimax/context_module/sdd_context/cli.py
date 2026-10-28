"""Command line entry point for the SDD context module.

Every command prints a JSON summary so the verification scripts (and graders)
can assert on the result without parsing prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import Settings
from .importer import import_project
from .pc_state import describe_backend, load_state, new_state, record_verification, save_state
from .selector import build_context, load_task, render_markdown, validate_context
from .store import open_store


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.resolve(args.project, args.data_dir)
    if getattr(args, "db", None):
        settings.db_path = Path(args.db).resolve()
    settings.ensure_dirs()
    return settings


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _task(settings: Settings, args: argparse.Namespace) -> dict[str, Any]:
    task_path = Path(args.task).resolve() if getattr(args, "task", None) else settings.project_root / "task.yaml"
    if task_path.is_file() and task_path.name != "task.yaml":
        import yaml

        return yaml.safe_load(task_path.read_text(encoding="utf-8"))
    return load_task(settings.project_root)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    info: dict[str, Any] = {
        "module": "sdd_context",
        "version": __version__,
        "settings": settings.describe(),
    }
    try:
        import pylibseekdb  # noqa: F401

        info["pylibseekdb"] = True
    except ModuleNotFoundError:
        info["pylibseekdb"] = False
    try:
        import powercontext

        info["powercontext"] = getattr(powercontext, "__version__", "?")
    except ModuleNotFoundError:
        info["powercontext"] = None
    info["powercontext_backend"] = describe_backend(settings)
    _print(info)
    return 0


def _open(settings: Settings, *, reset: bool = False, log_name: str = "db.log", echo: bool = False):
    return open_store(
        settings.db_path,
        reset=reset,
        log_path=settings.evidence_dir / log_name,
        echo=echo,
        mode=settings.seekdb_mode,
        server=settings.seekdb_server(),
        database=settings.seekdb_database,
    )


def cmd_import(args: argparse.Namespace) -> int:
    settings = _settings(args)
    log_path = settings.evidence_dir / (args.log or "db-import.log")
    store = _open(settings, reset=args.reset, log_name=args.log or "db-import.log", echo=args.echo)
    try:
        result = import_project(store, settings.project_root, note=args.note or "cli import")
        store.query_log.flush()
        result["db"] = str(settings.db_path)
        result["query_log"] = str(log_path)
        result["spec_versions"] = store.spec_versions()
        _print(result)
    finally:
        store.close()
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    settings = _settings(args)
    log_path = settings.evidence_dir / (args.log or "db-queries.log")
    store = _open(settings, log_name=args.log or "db-queries.log", echo=args.echo)
    try:
        task = _task(settings, args)
        state: dict[str, Any] = {}
        state_meta: dict[str, Any] = {}
        if args.with_state:
            loaded, state_meta = load_state(settings, task["task_id"])
            if loaded:
                state = loaded
        context = build_context(store, settings.project_root, task, state=state)
        context["state_meta"] = state_meta
        problems = validate_context(context, settings.project_root)
        context["validation"] = {"problems": problems, "ok": not problems}
        out_json = Path(args.out) if args.out else settings.evidence_dir / "context.json"
        out_md = Path(args.md) if args.md else settings.evidence_dir / "context.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
        out_md.write_text(render_markdown(context), encoding="utf-8")
        store.query_log.flush()
        _print(
            {
                "context_json": str(out_json),
                "context_md": str(out_md),
                "context_digest": context["context_digest"],
                "counts": context["counts"],
                "state_loaded": bool(state),
                "validation": context["validation"],
                "specs": [f"{spec['spec_id']}#r{spec['revision']}" for spec in context["specs"]],
                "code": [f"{unit['path']}::{unit['symbol']}" for unit in context["code"]],
                "query_log": str(log_path),
            }
        )
        return 0 if not problems or args.allow_problems else 2
    finally:
        store.close()


def cmd_state_save(args: argparse.Namespace) -> int:
    settings = _settings(args)
    task = _task(settings, args)
    task_id = args.task_id or task["task_id"]
    if args.state_file:
        state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    else:
        state = new_state(task_id)
    state["task_id"] = task_id
    if args.status:
        state["status"] = args.status
    if args.verification:
        verification = json.loads(args.verification)
        record_verification(
            state,
            name=verification.get("name", "verification"),
            command=verification.get("command", ""),
            returncode=int(verification.get("returncode", 0)),
            detail=verification.get("detail", ""),
            git_revision=verification.get("git_revision"),
        )
    detail = save_state(settings, task_id, state)
    detail["state"] = state
    _print(detail)
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    settings = _settings(args)
    state, meta = load_state(settings, args.task_id)
    out = {"task_id": args.task_id, "found": state is not None, "state": state, "meta": meta}
    if args.out:
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(out)
    return 0 if state is not None else 1


def cmd_dev_run(args: argparse.Namespace) -> int:
    from .devrun import run_development

    settings = _settings(args)
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    repo_root = Path(args.repo).resolve() if args.repo else Path.cwd()
    targets = args.test_target or [
        "tests/test_pricing_target.py",
        "tests/test_pricing_regression.py",
    ]
    record = run_development(
        settings,
        context,
        repo_root=repo_root,
        patch_prefix=args.patch_prefix,
        model=args.model,
        apply=not args.no_apply,
        test_targets=targets,
        max_rounds=args.max_rounds,
    )
    summary = {
        "record": record.get("record_path"),
        "result": record.get("result"),
        "applied": record.get("applied"),
        "rounds": len(record.get("attempts") or []),
        "patch_sha256": (record.get("attempts") or [{}])[-1].get("patch_sha256"),
        "tests": record.get("tests"),
        "git_revision_after": record.get("git_revision_after"),
    }
    _print(summary)
    return 0 if record.get("result") == "applied-and-tested" else 1


def cmd_verify_context(args: argparse.Namespace) -> int:
    settings = _settings(args)
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    expect = json.loads(Path(args.expect).read_text(encoding="utf-8"))
    problems: list[str] = []

    spec_anchors = {spec["anchor"] for spec in context.get("specs", [])}
    for anchor in expect.get("spec_anchors", []):
        if anchor not in spec_anchors:
            problems.append(f"missing spec anchor {anchor}")
    for anchor, phrases in (expect.get("spec_text_must_contain") or {}).items():
        entry = next((spec for spec in context.get("specs", []) if spec["anchor"] == anchor), None)
        if entry is None:
            problems.append(f"missing spec {anchor}")
            continue
        for phrase in phrases:
            if phrase not in entry.get("content", ""):
                problems.append(f"spec {anchor} does not contain {phrase!r}")
    for anchor, phrases in (expect.get("spec_text_must_not_contain") or {}).items():
        entry = next((spec for spec in context.get("specs", []) if spec["anchor"] == anchor), None)
        if entry is None:
            continue
        for phrase in phrases:
            if phrase in entry.get("content", ""):
                problems.append(f"spec {anchor} still contains removed phrase {phrase!r}")
    for anchor in expect.get("forbidden_spec_anchors", []):
        if anchor in spec_anchors:
            problems.append(f"context includes superseded spec {anchor}")
    code_anchors = {unit["anchor"] for unit in context.get("code", [])}
    for anchor in expect.get("code_anchors", []):
        if anchor not in code_anchors:
            problems.append(f"missing code anchor {anchor}")
    target_symbols = {test["symbol"] for test in context.get("tests", {}).get("target", [])}
    for symbol in expect.get("target_tests", []):
        if symbol not in target_symbols:
            problems.append(f"missing target test {symbol}")
    regression_symbols = {test["symbol"] for test in context.get("tests", {}).get("regression", [])}
    for symbol in expect.get("regression_tests", []):
        if symbol not in regression_symbols:
            problems.append(f"missing regression test {symbol}")
    for symbol in expect.get("forbidden_target_tests", []):
        if symbol in target_symbols:
            problems.append(f"unexpected target test {symbol}")
    if "state_present" in expect:
        present = bool(context.get("state"))
        if present != bool(expect["state_present"]):
            problems.append(f"state_present expected {expect['state_present']} got {present}")
    for phrase in expect.get("markdown_must_contain", []):
        md_path = Path(args.md) if args.md else settings.evidence_dir / "context.md"
        if md_path.exists() and phrase not in md_path.read_text(encoding="utf-8"):
            problems.append(f"context markdown does not contain {phrase!r}")

    _print({"context": str(args.context), "ok": not problems, "problems": problems})
    return 0 if not problems else 2


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd_context", description="SDD context module (seekdb + PowerContext + MiniMax)")
    parser.add_argument("--project", help="business project root (default: minimax/sample_app)")
    parser.add_argument("--data-dir", help="runtime data directory (default: minimax/runtime)")
    parser.add_argument("--db", help="explicit seekdb database path")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="print environment and configuration")
    doctor.set_defaults(func=cmd_doctor)

    imp = sub.add_parser("import", help="import specs/code/tests into seekdb")
    imp.add_argument("--reset", action="store_true", help="drop and recreate the material tables")
    imp.add_argument("--log", default="db-import.log")
    imp.add_argument("--note", default="")
    imp.add_argument("--echo", action="store_true")
    imp.set_defaults(func=cmd_import)

    ctx = sub.add_parser("context", help="select context for the task and write JSON + Markdown")
    ctx.add_argument("--task", help="task YAML path (default: <project>/task.yaml)")
    ctx.add_argument("--out", help="context JSON output path")
    ctx.add_argument("--md", help="context Markdown output path")
    ctx.add_argument("--log", default="db-queries.log")
    ctx.add_argument("--with-state", action="store_true", help="load task state from PowerContext")
    ctx.add_argument("--allow-problems", action="store_true")
    ctx.add_argument("--echo", action="store_true")
    ctx.set_defaults(func=cmd_context)

    save = sub.add_parser("state-save", help="persist task state through PowerContext")
    save.add_argument("--task", help="task YAML path")
    save.add_argument("--task-id")
    save.add_argument("--state-file", help="JSON file with the full state")
    save.add_argument("--status")
    save.add_argument("--verification", help="JSON object describing one verification result")
    save.set_defaults(func=cmd_state_save)

    show = sub.add_parser("state-show", help="read task state through PowerContext")
    show.add_argument("--task-id", required=True)
    show.add_argument("--out")
    show.set_defaults(func=cmd_state_show)

    dev = sub.add_parser("dev-run", help="ask MiniMax for a patch, apply it and run tests")
    dev.add_argument("--context", required=True)
    dev.add_argument("--repo", help="repository root used for git apply (default: cwd)")
    dev.add_argument("--patch-prefix", default="minimax/sample_app")
    dev.add_argument("--model", help="MiniMax model id (default from env)")
    dev.add_argument("--test-target", action="append", help="pytest target (repeatable)")
    dev.add_argument("--no-apply", action="store_true", help="generate the patch only")
    dev.add_argument("--max-rounds", type=int, default=2)
    dev.set_defaults(func=cmd_dev_run)

    verify = sub.add_parser("verify-context", help="assert that a context pack contains the required sources")
    verify.add_argument("--context", required=True)
    verify.add_argument("--expect", required=True)
    verify.add_argument("--md")
    verify.set_defaults(func=cmd_verify_context)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())