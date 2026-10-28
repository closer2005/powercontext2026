"""Runtime settings for the SDD context module.

Values are resolved from (in order): explicit arguments, process environment,
and an optional ``.env`` file placed next to the deliverable (never committed
with real credentials).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://api.minimaxi.com"
DEFAULT_MODEL = "MiniMax-M3.1-Flash"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` env file (BOM tolerant, ``#`` comments)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _deliverable_root() -> Path:
    """Return the ``minimax/`` deliverable root (parent of ``context_module``)."""
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    project_root: Path
    data_dir: Path
    db_path: Path
    evidence_dir: Path
    dev_record_dir: Path
    pc_backend: str = "seekdb"
    pc_db_path: Path | None = None
    seekdb_mode: str = "embedded"
    seekdb_host: str = "127.0.0.1"
    seekdb_port: int = 2881
    seekdb_user: str = "root"
    seekdb_password: str = ""
    seekdb_database: str = "sdd"
    minimax_api_key: str | None = None
    minimax_base_url: str = DEFAULT_BASE_URL
    minimax_model: str = DEFAULT_MODEL
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        project_root: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> "Settings":
        deliverable = _deliverable_root()
        # Process environment wins over the optional .env file (the file only
        # supplies defaults for a developer shell).
        env = read_env_file(deliverable / ".env")
        env.update(os.environ)

        root = Path(
            project_root
            or env.get("SDD_PROJECT_ROOT")
            or (deliverable / "sample_app")
        ).resolve()
        data = Path(
            data_dir or env.get("SDD_DATA_DIR") or (deliverable / "runtime")
        ).resolve()
        db_path = Path(env.get("SDD_DB_PATH") or (data / "seekdb" / "sdd.db"))
        pc_backend = env.get("POWERCONTEXT_BACKEND", "seekdb").strip().lower()
        pc_db = Path(env.get("POWERCONTEXT_DB") or (data / "powercontext" / "pc.db"))
        return cls(
            project_root=root,
            data_dir=data,
            db_path=db_path,
            evidence_dir=(deliverable / "evidence").resolve(),
            dev_record_dir=(deliverable / "dev-records").resolve(),
            pc_backend=pc_backend,
            pc_db_path=pc_db,
            seekdb_mode=env.get("SDD_SEEKDB_MODE", "embedded").strip().lower(),
            seekdb_host=env.get("SDD_SEEKDB_HOST", "127.0.0.1"),
            seekdb_port=int(env.get("SDD_SEEKDB_PORT", "2881")),
            seekdb_user=env.get("SDD_SEEKDB_USER", "root"),
            seekdb_password=env.get("SDD_SEEKDB_PASSWORD", ""),
            seekdb_database=env.get("SDD_SEEKDB_DATABASE", "sdd"),
            minimax_api_key=(env.get("MINIMAX_API_KEY") or "").strip() or None,
            minimax_base_url=(env.get("MINIMAX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            minimax_model=env.get("MINIMAX_MODEL", DEFAULT_MODEL),
            extra={k: v for k, v in env.items() if k.startswith(("MINIMAX_", "SDD_", "POWERCONTEXT_"))},
        )

    def seekdb_server(self) -> dict[str, object]:
        return {
            "host": self.seekdb_host,
            "port": self.seekdb_port,
            "user": self.seekdb_user,
            "password": self.seekdb_password,
        }

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.db_path.parent, self.evidence_dir, self.dev_record_dir):
            path.mkdir(parents=True, exist_ok=True)
        if self.pc_db_path is not None:
            self.pc_db_path.parent.mkdir(parents=True, exist_ok=True)

    def require_api_key(self) -> str:
        if not self.minimax_api_key:
            raise SystemExit(
                "MINIMAX_API_KEY is not configured. Copy minimax/.env.example to "
                "minimax/.env and fill in the subscription key, or export MINIMAX_API_KEY."
            )
        return self.minimax_api_key

    def describe(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "data_dir": str(self.data_dir),
            "db_path": str(self.db_path),
            "evidence_dir": str(self.evidence_dir),
            "dev_record_dir": str(self.dev_record_dir),
            "pc_backend": self.pc_backend,
            "pc_db_path": str(self.pc_db_path) if self.pc_db_path else None,
            "seekdb_mode": self.seekdb_mode,
            "seekdb_server": {
                "host": self.seekdb_host,
                "port": self.seekdb_port,
                "user": self.seekdb_user,
                "database": self.seekdb_database,
                "password_present": bool(self.seekdb_password),
            },
            "minimax_base_url": self.minimax_base_url,
            "minimax_model": self.minimax_model,
            "minimax_api_key_present": bool(self.minimax_api_key),
        }