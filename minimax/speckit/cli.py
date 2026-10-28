"""命令行入口：``python -m speckit.cli <cmd> [options]``

命令（契约见 minimax/DESIGN.md §4）：

    init                            建库建表并导入 data/ 三份索引
    build   --task "..."            检索并组装上下文（JSON，每项带 source）
    draft   --task "..."            把上下文交给 MiniMax，生成候选补丁
    apply   --patch <file>          把补丁应用到 demo_project/orders/service.py
    verify  [--after]               跑目标 + 回归测试，写 evidence/test_before.log|test_after.log
    save    --state-file <f>        保存任务状态（PowerContext，失败自动降级本地 JSON）
    resume  --state-file <f>        另起进程读取任务状态

每个命令都支持 ``--help``。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_STATE_FILE, MINIMAX_ROOT, Config
from .minimax import MiniMaxError, chat
from .patch import PatchError, apply_patch_file, extract_patch, make_diff
from .selector import build_context
from .state import ProgressStore, StateError
from .store import SeekDBStore, StoreError


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    store = SeekDBStore(cfg)
    print(f"正在初始化 seekdb schema：{cfg.seekdb_host}:{cfg.seekdb_port}/{cfg.seekdb_database}")
    store.init_schema()
    counts = store.import_from_json()
    print("已建表：spec_items / code_items / test_items")
    print(
        f"导入条目数：specs={counts['specs']} code={counts['code']} tests={counts['tests']}"
    )
    for warning in counts.get("warnings", []):
        print(f"[提示] {warning}")
    stats = store.stats()
    print(f"当前表计数：{json.dumps(stats, ensure_ascii=False)}")
    return 0


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _load_progress_or_empty(cfg: Config) -> dict:
    """尝试读取默认状态文件；不存在则返回空进展结构。"""
    try:
        ps = ProgressStore(cfg.powercontext_state_dir)
        return ps.load_progress(ps.default_state_file)
    except Exception:
        return {"done": [], "todo": [], "evidence": {}, "backend": "none"}


def cmd_build(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    store = SeekDBStore(cfg)
    progress = _load_progress_or_empty(cfg)
    ctx = build_context(
        args.task, store=store, top_k=args.top_k, scope=args.scope, progress=progress
    )
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    if not (ctx["specs"] or ctx["code"] or ctx["tests"]):
        print(
            "[提示] 未检索到任何条目：请确认已执行 init 导入索引，或调整 --task 关键词。",
            file=sys.stderr,
        )
    return 0


# --------------------------------------------------------------------------- #
# draft
# --------------------------------------------------------------------------- #
def build_draft_prompt(ctx: dict, source_code: str) -> str:
    """把上下文组装成给 MiniMax 的提示词（含来源标注，便于核对）。"""
    lines: list[str] = [
        "你是资深 Python 工程师。请基于下列规格、现有代码与测试，完成给定任务。",
        "",
        f"# 任务\n{ctx.get('task', '')}",
        "",
        "# 相关规格",
    ]
    for s in ctx.get("specs", []):
        lines.append(f"- [{s['id']}] {s['title']}  (source: {s['source']})")
    if not ctx.get("specs"):
        lines.append("- （无）")

    lines += ["", "# 相关代码符号"]
    for c in ctx.get("code", []):
        lines.append(f"- [{c['id']}] {c['file']}::{c['symbol']}  (source: {c['source']})")
    if not ctx.get("code"):
        lines.append("- （无）")

    lines += ["", "# 相关测试"]
    for t in ctx.get("tests", []):
        lines.append(f"- [{t['id']}] {t['file']}::{t['name']}  (source: {t['source']})")
    if not ctx.get("tests"):
        lines.append("- （无）")

    if source_code:
        lines += [
            "",
            "# 现有 demo_project/orders/service.py 源码",
            "```python",
            source_code.rstrip("\n"),
            "```",
        ]

    lines += [
        "",
        "要求：",
        "1) 仅实现 list_orders 的 status 过滤（status 为 None 时不过滤）；",
        "2) 不得改变 min_amount 过滤与按 id 升序排序的既有行为；",
        "3) 不得修改任何测试或断言；",
        "4) 只输出修改后的 service.py 完整源码，放在一个 ```python 代码块中，不要任何额外解释。",
    ]
    return "\n".join(lines)


def cmd_draft(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    store = SeekDBStore(cfg)
    ctx = build_context(args.task, store=store)
    source_code = (
        cfg.service_path.read_text(encoding="utf-8") if cfg.service_path.is_file() else ""
    )
    prompt = build_draft_prompt(ctx, source_code)

    print("正在调用 MiniMax（上下文来自 seekdb 检索）...")
    text = chat(prompt, config=cfg)
    code = extract_patch(text)

    out_path = Path(args.out) if args.out else (cfg.evidence_dir / "candidate_service.py")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(code, encoding="utf-8")

    # 生成相对当前 service.py 的候选 diff
    diff = make_diff(source_code, code)
    diff_path = cfg.evidence_dir / "diff.patch"
    diff_path.write_text(diff, encoding="utf-8")

    print("MiniMax 调用成功，请求 / 响应已写入 evidence/minimax_session.json")
    print(f"候选补丁：{out_path}")
    print(f"候选 diff：{diff_path}")
    return 0


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def cmd_apply(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    result = apply_patch_file(args.patch, args.service, config=cfg)
    print(f"已应用补丁到 {result['service_path']}（changed={result['changed']}）")
    print(f"修改前快照：{result['before_snapshot']}")
    print(f"修改后快照：{result['after_snapshot']}")
    print(f"unified diff：{result['diff_path']}")
    if not result["changed"]:
        print("[提示] 目标文件内容与补丁一致，未产生实际改动。")
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def _format_section(label: str, cmd: list[str], returncode: int, stdout: str, stderr: str) -> str:
    lines = [
        f"## {label}",
        f"$ {' '.join(cmd)}",
        f"exit_code={returncode}",
        "",
        (stdout or "").rstrip(),
        "",
    ]
    if stderr and stderr.strip():
        lines += ["--- stderr ---", stderr.rstrip(), ""]
    lines.append(f"结果：{'PASS' if returncode == 0 else 'FAIL'}")
    return "\n".join(lines)


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    groups = [
        ("回归（baseline）", cfg.demo_project_dir / "tests" / "test_orders_baseline.py"),
        ("目标（target）", cfg.demo_project_dir / "tests" / "test_orders_target.py"),
    ]

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    sections: list[str] = []
    all_passed = True
    for label, path in groups:
        if not path.is_file():
            sections.append(f"## {label}\n[错误] 测试文件不存在：{path}\n结果：FAIL")
            all_passed = False
            continue
        cmd = [sys.executable, "-m", "pytest", str(path), "-q", "--no-header", "-p", "no:cacheprovider"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(MINIMAX_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except FileNotFoundError as exc:
            sections.append(f"## {label}\n[错误] 无法运行 pytest：{exc}\n结果：FAIL")
            all_passed = False
            continue
        returncode = proc.returncode
        all_passed = all_passed and (returncode == 0)
        sections.append(_format_section(label, cmd, returncode, proc.stdout, proc.stderr))

    phase = "修改后（after）" if args.after else "修改前（before）"
    log_name = "test_after.log" if args.after else "test_before.log"
    log_path = cfg.evidence_dir / log_name
    cfg.evidence_dir.mkdir(parents=True, exist_ok=True)

    header = f"# verify 阶段：{phase}   时间：{_now_iso()}\n"
    content = header + "\n\n".join(sections) + "\n"
    log_path.write_text(content, encoding="utf-8")

    print(header.rstrip())
    print()
    for section in sections:
        print(section)
        print()
    print(f"日志已写入：{log_path}")
    verdict = "全部通过" if all_passed else "存在失败用例"
    print(f"总体结果：{verdict}（{'PASS' if all_passed else 'FAIL'}）")
    return 0 if all_passed else 1


# --------------------------------------------------------------------------- #
# save / resume
# --------------------------------------------------------------------------- #
def _evidence_map(cfg: Config) -> dict[str, str]:
    out: dict[str, str] = {}
    if not cfg.evidence_dir.is_dir():
        return out
    for f in sorted(cfg.evidence_dir.rglob("*")):
        if f.is_file():
            try:
                rel = f.relative_to(MINIMAX_ROOT).as_posix()
            except ValueError:
                rel = f.as_posix()
            out[rel] = rel
    return out


def _collect_progress(cfg: Config) -> dict:
    """根据当前工作区状态自动汇总 done / todo / evidence。"""
    done: list[str] = []
    todo: list[str] = []

    service_src = ""
    if cfg.service_path.is_file():
        service_src = cfg.service_path.read_text(encoding="utf-8")

    if not service_src:
        todo.append("创建 demo_project/orders/service.py")
    elif "TODO: status filter not implemented yet" in service_src:
        todo.append("在 demo_project/orders/service.py 中实现 list_orders 的 status 过滤")
    else:
        done.append("list_orders 的 status 过滤已实现")

    if (cfg.evidence_dir / "before" / "service.py").is_file():
        done.append("已生成修改前快照 evidence/before/service.py")
    if (cfg.evidence_dir / "minimax_session.json").is_file():
        done.append("MiniMax 请求/响应已留痕 evidence/minimax_session.json")
    if (cfg.evidence_dir / "after" / "service.py").is_file():
        done.append("已生成修改后快照 evidence/after/service.py")
    if (cfg.evidence_dir / "test_before.log").is_file():
        done.append("已记录修改前测试日志 evidence/test_before.log")
    else:
        todo.append("运行 verify 记录修改前测试日志")
    if (cfg.evidence_dir / "test_after.log").is_file():
        done.append("已记录修改后测试日志 evidence/test_after.log")
    else:
        todo.append("运行 verify --after 记录修改后测试日志")

    return {"done": done, "todo": todo, "evidence": _evidence_map(cfg)}


def cmd_save(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    ps = ProgressStore(cfg.powercontext_state_dir)
    progress = _collect_progress(cfg)
    state_id = ps.save_progress(progress, args.state_file)
    print(f"状态已保存：{state_id}")
    print(ps.describe_backend())
    print(f"文件位置：{cfg.state_file_path(args.state_file or DEFAULT_STATE_FILE)}")
    print(f"进展概览：done={len(progress['done'])} todo={len(progress['todo'])}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    ps = ProgressStore(cfg.powercontext_state_dir)
    data = ps.load_progress(args.state_file)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[backend] {data.get('backend')}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m speckit.cli",
        description="speckit —— 面向软件持续演进的 SDD 上下文管理 CLI（契约见 minimax/DESIGN.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            '  python -m speckit.cli init\n'
            '  python -m speckit.cli build --task "实现订单按状态筛选"\n'
            '  python -m speckit.cli draft --task "实现订单按状态筛选"\n'
            "  python -m speckit.cli apply --patch evidence/diff.patch\n"
            "  python -m speckit.cli verify\n"
            "  python -m speckit.cli verify --after\n"
            "  python -m speckit.cli save --state-file task_state.json\n"
            "  python -m speckit.cli resume --state-file task_state.json\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_init = sub.add_parser("init", help="建库建表并导入 data/ 三份索引")
    p_init.set_defaults(func=cmd_init)

    p_build = sub.add_parser("build", help="检索并组装上下文（JSON，每项带 source）")
    p_build.add_argument("--task", required=True, help="任务描述，例如：实现订单按状态筛选")
    p_build.add_argument("--top-k", type=int, default=5, help="每类返回条数上限（默认 5）")
    p_build.add_argument("--scope", default=None, help="可选：显式指定 scope 过滤")
    p_build.set_defaults(func=cmd_build)

    p_draft = sub.add_parser("draft", help="把上下文交给 MiniMax，生成候选补丁")
    p_draft.add_argument("--task", required=True, help="任务描述")
    p_draft.add_argument("--out", default=None, help="候选补丁输出路径（默认 evidence/candidate_service.py）")
    p_draft.set_defaults(func=cmd_draft)

    p_apply = sub.add_parser("apply", help="把补丁应用到 demo_project/orders/service.py")
    p_apply.add_argument("--patch", required=True, help="补丁文件路径（模型输出或纯代码）")
    p_apply.add_argument("--service", default=None, help="目标 service.py 路径（默认 demo_project/orders/service.py）")
    p_apply.set_defaults(func=cmd_apply)

    p_verify = sub.add_parser("verify", help="跑目标 + 回归测试，写 evidence 日志")
    p_verify.add_argument("--after", action="store_true", help="标记为修改后阶段，日志写入 evidence/test_after.log")
    p_verify.set_defaults(func=cmd_verify)

    p_save = sub.add_parser("save", help="保存任务状态（PowerContext / 本地 JSON）")
    p_save.add_argument("--state-file", default=None, help=f"状态文件名（默认 {DEFAULT_STATE_FILE}）")
    p_save.set_defaults(func=cmd_save)

    p_resume = sub.add_parser("resume", help="另起进程读取任务状态")
    p_resume.add_argument("--state-file", required=True, help="要读取的状态文件名")
    p_resume.set_defaults(func=cmd_resume)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return int(args.func(args) or 0)
    except (StoreError, MiniMaxError, PatchError, StateError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[中断] 已取消", file=sys.stderr)
        return 130
    except Exception as exc:  # 兜底：不隐藏堆栈，方便排查
        print(f"[未预期错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())