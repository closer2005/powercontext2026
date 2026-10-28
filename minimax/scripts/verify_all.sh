#!/usr/bin/env bash
# End-to-end verification of every "must pass" item for the MiniMax task (600077).
#
# Usage (from anywhere):
#   bash minimax/scripts/verify_all.sh
#
# Environment (all optional):
#   PYTHON              python interpreter with requirements.txt installed (default: python3)
#   SDD_DATA_DIR        runtime data dir (default: minimax/runtime; use a native Linux
#                       path when the repo lives on a Windows drive under WSL)
#   POWERCONTEXT_BACKEND seekdb (default) or sqlite
#   SDD_SEEKDB_MODE     embedded (default) or server
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIMAX="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$MINIMAX/.." && pwd)"
APP="$MINIMAX/sample_app"
CTX="$MINIMAX/context_module"
EVID="$MINIMAX/evidence"
PY="${PYTHON:-python3}"
TASK_ID="TASK-ORD-PRICING-V2"

export PYTHONPATH="$CTX${PYTHONPATH:+:$PYTHONPATH}"
export SDD_DATA_DIR="${SDD_DATA_DIR:-$MINIMAX/runtime}"
export SDD_SEEKDB_MODE="${SDD_SEEKDB_MODE:-embedded}"
export POWERCONTEXT_BACKEND="${POWERCONTEXT_BACKEND:-seekdb}"

step() { echo; echo "===== $* ====="; }
die() { echo "FAILED: $*" >&2; exit 1; }
mkdir -p "$EVID"

step "0. reset to an empty runtime state (no delivered local state is used)"
rm -rf "$SDD_DATA_DIR"
mkdir -p "$SDD_DATA_DIR"
[ ! -e "$SDD_DATA_DIR/seekdb" ] || die "seekdb directory still present after reset"

step "1. environment check (see evidence/doctor.json)"
"$PY" -m sdd_context doctor > "$EVID/doctor.json"
"$PY" - "$EVID/doctor.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print("pylibseekdb:", data["pylibseekdb"], "| powercontext:", data["powercontext"])
print("seekdb mode:", data["settings"]["seekdb_mode"], "| pc backend:", data["settings"]["pc_backend"])
assert data["pylibseekdb"] is True, "pylibseekdb is not importable"
assert data["powercontext"], "powercontext is not importable"
PY

step "2. import specifications, code and tests into seekdb"
"$PY" -m sdd_context import --reset > "$EVID/import.json"
"$PY" - "$EVID/import.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print("imported:", data["counts"], "| fulltext index:", data["fulltext"])
assert data["counts"]["spec"] == 3, data["counts"]
assert data["counts"]["code"] == 13, data["counts"]
assert data["counts"]["test"] == 30, data["counts"]
assert data["fulltext"] is True, "seekdb FULLTEXT index was not created"
PY

step "3. build the development context with an empty task state"
"$PY" -m sdd_context context \
  --out "$EVID/context-empty-state.json" --md "$EVID/context-empty-state.md" \
  > "$EVID/context-empty-state.summary.json"
"$PY" -m sdd_context verify-context \
  --context "$EVID/context-empty-state.json" --expect "$MINIMAX/expectations.json" \
  --md "$EVID/context-empty-state.md" | tee "$EVID/context-empty-state.check.json"
"$PY" - "$EVID/context-empty-state.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print("context counts:", data["counts"], "| validation:", data["validation"]["ok"])
assert data["validation"]["ok"]
assert data["counts"] == {"specs": 2, "code": 13, "target_tests": 15, "regression_tests": 15}, data["counts"]
assert not data["state"], "task state should be empty before it is saved"
PY

step "4. target tests fail on the pre-change snapshot (functional failure, not env error)"
cp "$APP/src/ordercore/pricing.py" "$SDD_DATA_DIR/pricing-after.py"
cp "$APP/baseline/pricing.py" "$APP/src/ordercore/pricing.py"
set +e
( cd "$APP" && "$PY" -m pytest tests/test_pricing_target.py -q ) > "$EVID/test-before.log" 2>&1
BEFORE_RC=$?
set -e
cp "$SDD_DATA_DIR/pricing-after.py" "$APP/src/ordercore/pricing.py"
tail -3 "$EVID/test-before.log"
[ "$BEFORE_RC" -ne 0 ] || die "target tests unexpectedly passed on the baseline snapshot"
grep -q "AssertionError" "$EVID/test-before.log" || die "baseline failure is not an assertion failure"
if grep -qE "ERROR collecting|ModuleNotFoundError|ImportError" "$EVID/test-before.log"; then
  die "baseline failure is an environment/import error, not a functional failure"
fi
grep -q "15 failed" "$EVID/test-before.log" || die "expected 15 failing target tests on the baseline"

step "5. save task state through PowerContext (process 1, from empty state)"
cat > "$SDD_DATA_DIR/state-initial.json" <<JSON
{
  "task_id": "$TASK_ID",
  "status": "in_progress",
  "done": ["导入规格/代码/测试资料", "生成开发上下文（空状态）"],
  "todo": ["由 MiniMax 按上下文修改 pricing.py", "运行目标与回归测试"],
  "verifications": []
}
JSON
"$PY" -m sdd_context state-save \
  --task-id "$TASK_ID" --state-file "$SDD_DATA_DIR/state-initial.json" \
  > "$EVID/powercontext-save.json"
cat "$EVID/powercontext-save.json"

step "6. restart the module and read the saved state back (process 2)"
"$PY" -m sdd_context state-show --task-id "$TASK_ID" \
  > "$EVID/powercontext-reload.json"
"$PY" - "$EVID/powercontext-reload.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print("found:", data["found"], "| scope:", data["meta"].get("scope_id"), "| entries:", data["meta"].get("entries"))
assert data["found"] is True
assert data["state"]["task_id"] == "TASK-ORD-PRICING-V2"
assert data["state"]["status"] == "in_progress"
PY

step "7. the reloaded state is used by the next context build (process 3)"
"$PY" -m sdd_context context --with-state \
  --out "$EVID/context-with-state.json" --md "$EVID/context-with-state.md" \
  > "$EVID/context-with-state.summary.json"
"$PY" - "$EVID/context-with-state.summary.json" "$EVID/context-with-state.json" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
context = json.load(open(sys.argv[2], encoding="utf-8"))
print("state_loaded:", summary["state_loaded"], "| state status:", context["state"].get("status"))
assert summary["state_loaded"] is True
assert context["state"]["task_id"] == "TASK-ORD-PRICING-V2"
assert context["state"]["status"] == "in_progress"
assert context["state_meta"].get("scope_id"), "context does not record the PowerContext scope"
assert context["validation"]["ok"]
PY

step "8. target and regression tests pass on the MiniMax-modified code"
( cd "$APP" && "$PY" -m pytest tests -q ) > "$EVID/test-after.log" 2>&1
tail -3 "$EVID/test-after.log"
grep -q "30 passed" "$EVID/test-after.log" || die "expected 30 passing tests after the change"

step "9. the recorded MiniMax development run matches the committed code diff"
LATEST_RECORD="$(ls -t "$MINIMAX"/dev-records/*minimax-dev-run.json | head -1)"
"$PY" "$HERE/check_dev_record.py" \
  --record "$LATEST_RECORD" \
  --baseline "$APP/baseline/pricing.py" \
  --current "$APP/src/ordercore/pricing.py" \
  | tee "$EVID/dev-record-check.json"

step "10. update a specification, re-import, and confirm the context refreshes"
bash "$HERE/demo_spec_update.sh"

step "11. reset runtime state again and summarise"
"$PY" - "$EVID" <<'PY'
import json, pathlib, sys
evid = pathlib.Path(sys.argv[1])
summary = {
    "runnable": True,
    "minimax_dev_record": json.load(open(evid / "dev-record-check.json", encoding="utf-8")),
    "context_before_change": json.load(open(evid / "context-empty-state.summary.json", encoding="utf-8")),
    "context_after_spec_update": json.load(open(evid / "context-after-spec-update.summary.json", encoding="utf-8")),
    "powercontext_save": json.load(open(evid / "powercontext-save.json", encoding="utf-8")),
    "powercontext_reload": json.load(open(evid / "powercontext-reload.json", encoding="utf-8"))["meta"],
}
path = evid / "verification-summary.json"
path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
print("written:", path)
PY

echo
echo "ALL CHECKS PASSED"