"""配置中心：统一从环境变量（可选 .env 兜底）读取运行时参数。

契约见 minimax/DESIGN.md §7：
    SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD / SEEKDB_DATABASE
    MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_MODEL
    POWERCONTEXT_STATE_DIR

所有项都提供安全默认值；真实凭据只来自环境变量或本地 .env，代码内一律不写死。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# minimax/ 目录（speckit 包的上一级）。所有相对路径都以它为基准解析，
# 这样即使 CLI 在“另一个进程 / 另一个工作目录”里运行，也能定位到同一份数据与状态文件
# （这是 DESIGN §4 “resume 必须另起进程读取”的基础）。
MINIMAX_ROOT: Path = Path(__file__).resolve().parent.parent
REPO_ROOT: Path = MINIMAX_ROOT.parent

# save / resume 未显式指定 --state-file 时使用的默认状态文件名。
DEFAULT_STATE_FILE = "task_state.json"


def _as_int(value: object, default: int) -> int:
    """把环境变量安全地转成 int，非法值回退到 default。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 解析：仅作兜底，已存在的环境变量优先级更高。

    刻意不依赖 python-dotenv，保持依赖轻量。
    """
    env_path = Path(path) if path else (MINIMAX_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 真实环境变量优先，.env 只填补空缺
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_state_dir(value: str | None) -> Path:
    """把 POWERCONTEXT_STATE_DIR 解析为绝对路径（相对路径基于 minimax/）。"""
    candidate = Path(value) if value else Path(".powercontext")
    if not candidate.is_absolute():
        candidate = MINIMAX_ROOT / candidate
    return candidate


@dataclass(frozen=True)
class Config:
    """一次性读取的运行时配置快照。"""

    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    seekdb_database: str
    minimax_api_key: str
    minimax_base_url: str
    minimax_model: str
    powercontext_state_dir: Path
    powercontext_server: str

    @classmethod
    def from_env(cls, load_env_file: bool = True) -> "Config":
        if load_env_file:
            load_dotenv()
        return cls(
            seekdb_host=os.environ.get("SEEKDB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            seekdb_port=_as_int(os.environ.get("SEEKDB_PORT", "2881"), 2881),
            seekdb_user=os.environ.get("SEEKDB_USER", "root").strip() or "root",
            seekdb_password=os.environ.get("SEEKDB_PASSWORD", ""),
            seekdb_database=os.environ.get("SEEKDB_DATABASE", "speckit").strip() or "speckit",
            minimax_api_key=os.environ.get("MINIMAX_API_KEY", "").strip(),
            minimax_base_url=os.environ.get(
                "MINIMAX_BASE_URL", "https://api.minimax.chat/v1"
            ).strip().rstrip("/"),
            minimax_model=os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01").strip()
            or "MiniMax-Text-01",
            powercontext_state_dir=_resolve_state_dir(
                os.environ.get("POWERCONTEXT_STATE_DIR", ".powercontext")
            ),
            powercontext_server=os.environ.get("POWERCONTEXT_SERVER", "").strip(),
        )

    # ---- 派生路径（全部锚定 minimax/ 根目录）--------------------------------
    @property
    def data_dir(self) -> Path:
        return MINIMAX_ROOT / "data"

    @property
    def evidence_dir(self) -> Path:
        return MINIMAX_ROOT / "evidence"

    @property
    def demo_project_dir(self) -> Path:
        return MINIMAX_ROOT / "demo_project"

    @property
    def service_path(self) -> Path:
        return self.demo_project_dir / "orders" / "service.py"

    @property
    def specs_json(self) -> Path:
        return self.data_dir / "specs.json"

    @property
    def code_index_json(self) -> Path:
        return self.data_dir / "code_index.json"

    @property
    def tests_index_json(self) -> Path:
        return self.data_dir / "tests_index.json"

    @property
    def minimax_session_json(self) -> Path:
        return self.evidence_dir / "minimax_session.json"

    def state_file_path(self, state_file: str) -> Path:
        """把 --state-file 解析为绝对路径（相对路径基于 POWERCONTEXT_STATE_DIR）。"""
        p = Path(state_file)
        return p if p.is_absolute() else (self.powercontext_state_dir / p)

    # ---- 凭据处理 ----------------------------------------------------------
    def masked_key(self) -> str:
        """把 API Key 打码，供日志 / evidence 使用。"""
        key = self.minimax_api_key or ""
        if not key:
            return "<未配置>"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"

    def require_minimax_key(self) -> str:
        """返回可用的 API Key；未配置时抛出明确的中文错误。"""
        if not self.minimax_api_key:
            raise RuntimeError(
                "未配置 MINIMAX_API_KEY：请在环境变量或 minimax/.env 中填入 "
                "MiniMax API Key 后重试（参见 minimax/.env.example）。"
            )
        return self.minimax_api_key