#!/usr/bin/env bash
# ============================================================
# run_all.sh —— speckit 闭环一键复现
#
# 串联七个命令，覆盖 DESIGN.md §1 的六项必做项：
#   init -> build -> verify（before）-> 提示 draft/apply 需 Key
#        -> verify --after -> save -> resume
#
# 前提：
#   * 已安装依赖：pip install -r requirements.txt
#   * seekdb 已启动（init / build / draft 依赖它做索引与检索）
#   * 若要走通 draft / apply，需要 MINIMAX_API_KEY（否则 draft 会中文报错）
#
# 用法：
#   cd minimax
#   bash scripts/run_all.sh
#
# 可选环境变量：
#   PYTHON_BIN           指定 python 解释器（默认 python）
#   SPECKIT_AUTO_MINIMAX=1  若已配置 MINIMAX_API_KEY，自动执行 draft + apply
#
# 失败策略：set -e —— 除“预期失败”的 verify 外，任一步骤返回非零即中止；
#           verify 在存在失败用例时返回 1（修改前属预期），由脚本显式容忍。
# ============================================================
set -e

# 定位 minimax/ 目录（本脚本位于 minimax/scripts/），并切到该目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINIMAX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${MINIMAX_DIR}"

TASK="实现订单按状态筛选"
STATE_FILE="task_state.json"
PYTHON_BIN="${PYTHON_BIN:-python}"
CLI=("${PYTHON_BIN}" -m speckit.cli)

step() {
  printf '\n============================================================\n'
  printf '  %s\n' "$1"
  printf '============================================================\n'
}

# 容忍“预期失败”的 verify（存在失败用例时命令返回 1），其余错误仍由 set -e 中断
verify_tolerant() {
  local label="$1"
  shift
  step "${label}"
  set +e
  "${CLI[@]}" verify "$@"
  local rc=$?
  set -e
  echo "[退出码] ${rc}"
  if [ "${rc}" -ne 0 ]; then
    echo "[说明] verify 检测到失败用例（返回 1）。修改前目标测试尚未实现，属预期；本步不阻断脚本。"
  fi
}

echo "工作目录：${MINIMAX_DIR}"
echo "Python：$("${PYTHON_BIN}" --version 2>&1)"

# ---- 1/7 init --------------------------------------------------------------
step "1/7 初始化索引（init）"
"${CLI[@]}" init

# ---- 2/7 build -------------------------------------------------------------
step "2/7 组装上下文（build）"
"${CLI[@]}" build --task "${TASK}"

# ---- 3/7 verify（before）---------------------------------------------------
verify_tolerant "3/7 修改前测试（verify）"

# ---- 4/7 draft / apply（需 MiniMax Key）------------------------------------
step "4/7 MiniMax 生成补丁（draft）与应用（apply）—— 需要 MINIMAX_API_KEY"
cat <<'EOF'
[提示] 以下两步需要 MiniMax Key（且依赖 seekdb 提供的检索上下文）：

    python -m speckit.cli draft --task "实现订单按状态筛选"
    python -m speckit.cli apply --patch evidence/diff.patch

未配置 MINIMAX_API_KEY 时，draft 会以中文错误提示并返回非零码，绝不返回假内容。
若已配置 Key，可设置 SPECKIT_AUTO_MINIMAX=1 后重跑本脚本，自动执行以上两步。
EOF

if [ "${SPECKIT_AUTO_MINIMAX:-0}" = "1" ]; then
  step "4a 调用 MiniMax（draft）"
  "${CLI[@]}" draft --task "${TASK}"

  step "4b 应用补丁（apply）"
  "${CLI[@]}" apply --patch evidence/diff.patch
else
  echo "[跳过] 未设置 SPECKIT_AUTO_MINIMAX=1，draft / apply 留给人工执行（见上方命令）。"
fi

# ---- 5/7 verify --after ----------------------------------------------------
verify_tolerant "5/7 修改后测试（verify --after）" --after

# ---- 6/7 save --------------------------------------------------------------
step "6/7 保存任务状态（save）"
"${CLI[@]}" save --state-file "${STATE_FILE}"

# ---- 7/7 resume（另起进程）-------------------------------------------------
step "7/7 另起进程读取状态（resume）"
"${CLI[@]}" resume --state-file "${STATE_FILE}"

# ---- 完成 ------------------------------------------------------------------
step "完成"
echo "产出的证据文件："
ls -1 evidence/ 2>/dev/null || echo "  （evidence/ 为空或不存在）"
echo "状态文件：.powercontext/${STATE_FILE}"
echo "六项必做项对应关系见 minimax/DESIGN.md §1，验证样例见 minimax/VERIFY.md。"