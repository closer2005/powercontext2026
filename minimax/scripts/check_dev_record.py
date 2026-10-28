#!/usr/bin/env python3
"""Check that the recorded MiniMax development run corresponds to the shipped diff.

The development record stores the canonical ``git diff`` of the applied change.
This script recomputes the diff between the pre-change snapshot
(``sample_app/baseline/pricing.py``) and the shipped source file, then compares
the added/removed lines with the record. It also asserts the record shows a real
MiniMax call (token usage), a green test run and the expected context sources.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path


def hunk_body(diff_text: str) -> list[str]:
    lines = []
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "@@", "diff ", "index ")):
            continue
        if line[:1] in ("+", "-", " "):
            lines.append(line)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    args = parser.parse_args()

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    baseline = Path(args.baseline).read_text(encoding="utf-8")
    current = Path(args.current).read_text(encoding="utf-8")

    recomputed = "\n".join(
        difflib.unified_diff(
            baseline.splitlines(),
            current.splitlines(),
            fromfile="sample_app/baseline/pricing.py",
            tofile="sample_app/src/ordercore/pricing.py",
            lineterm="",
        )
    )
    recorded_body = hunk_body(record.get("applied_diff", ""))
    recomputed_body = hunk_body(recomputed)

    summary = record.get("context_summary") or {}
    usage = (record.get("attempts") or [{}])[0].get("usage") or {}
    checks = {
        "record_result_applied_and_tested": record.get("result") == "applied-and-tested",
        "tests_green": (record.get("tests") or {}).get("returncode") == 0,
        "minimax_usage_present": int(usage.get("prompt_tokens") or 0) > 0 and int(usage.get("completion_tokens") or 0) > 0,
        "recorded_context_has_two_specs": len(summary.get("specs") or []) == 2,
        "recorded_context_has_target_tests": len(summary.get("target_tests") or []) == 15,
        "recorded_context_has_regression_tests": len(summary.get("regression_tests") or []) == 15,
        "recorded_context_has_hint_code": len(summary.get("code") or []) >= 3,
        "diff_matches_recomputed": recorded_body == recomputed_body,
    }
    result = {
        "record": str(Path(args.record).resolve()),
        "model": record.get("model"),
        "api_style": record.get("api_style"),
        "base_url": record.get("base_url"),
        "recorded_added_removed_lines": len([line for line in recorded_body if line[:1] in ("+", "-")]),
        "recomputed_added_removed_lines": len([line for line in recomputed_body if line[:1] in ("+", "-")]),
        "checks": checks,
        "ok": all(checks.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())