#!/usr/bin/env bash
# Demonstrate that a specification update is picked up after re-importing,
# instead of the module returning a fixed answer.
#
# The script appends a clearly marked demo clause to SPEC-ORD-001 v2, re-imports,
# asserts the new content appears in the context, then restores the file,
# re-imports, and asserts the demo marker is gone again.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIMAX="$(cd "$HERE/.." && pwd)"
APP="$MINIMAX/sample_app"
CTX="$MINIMAX/context_module"
EVID="$MINIMAX/evidence"
PY="${PYTHON:-python3}"
SPEC="$APP/specs/SPEC-ORD-001.v2.md"
DATA="${SDD_DATA_DIR:-$MINIMAX/runtime}"
BACKUP="$DATA/spec-v2.original.md"
MARKER="DEMO-SPEC-UPDATE-MARKER"

export PYTHONPATH="$CTX${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$EVID" "$DATA"
cp "$SPEC" "$BACKUP"
restore() {
  cp "$BACKUP" "$SPEC"
}
trap restore EXIT

echo "-- append a demo clause and re-import"
cat >> "$SPEC" <<MD

## 8. 规格更新演示（仅用于验证上下文刷新）

- 演示变更：gold 会员满 3 件额外减 600 分（$MARKER）。
MD
"$PY" -m sdd_context import > "$EVID/import-after-spec-update.json"
"$PY" -m sdd_context context \
  --out "$EVID/context-after-spec-update.json" --md "$EVID/context-after-spec-update.md" \
  > "$EVID/context-after-spec-update.summary.json"
"$PY" -m sdd_context verify-context \
  --context "$EVID/context-after-spec-update.json" \
  --expect "$MINIMAX/expectations-spec-update.json" \
  --md "$EVID/context-after-spec-update.md" | tee "$EVID/context-after-spec-update.check.json"

echo "-- restore the specification and re-import"
restore
"$PY" -m sdd_context import > "$EVID/import-restored.json"
"$PY" -m sdd_context context \
  --out "$EVID/context-restored.json" --md "$EVID/context-restored.md" \
  > "$EVID/context-restored.summary.json"
"$PY" -m sdd_context verify-context \
  --context "$EVID/context-restored.json" --expect "$MINIMAX/expectations.json" \
  --md "$EVID/context-restored.md" | tee "$EVID/context-restored.check.json"

"$PY" - "$EVID/context-restored.json" "$MARKER" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
marker = sys.argv[2]
texts = [spec.get("content", "") for spec in data.get("specs", [])]
assert not any(marker in text for text in texts), "demo marker survived the restore"
print("restored context no longer contains", marker)
PY

echo "-- spec update is reflected in the context, then disappears after rollback"