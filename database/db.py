"""SQLite 连接管理 + 每日备份。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from database import migrations

DB_FILENAME = "ham_checkin.db"


class _LockedConnection(sqlite3.Connection):
    """线程安全连接：每个调用加锁，允许后台同步线程跨线程访问。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()

    def execute(self, *args, **kwargs):
        with self._lock:
            return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return super().executescript(*args, **kwargs)

    def commit(self):
        with self._lock:
            return super().commit()

    def rollback(self):
        with self._lock:
            return super().rollback()


def connect(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path), timeout=30, check_same_thread=False, factory=_LockedConnection
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrations.migrate(conn)
    return conn


def backup_daily(db_path: Path, backup_dir: Path, keep: int = 30) -> Path | None:
    """每天第一次启动备份一次，保留最近 keep 份。"""
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    dest = backup_dir / f"ham_checkin_{today}.db"
    if dest.exists():
        return dest  # 当天已备份
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except sqlite3.Error:
        return None
    # 清理旧备份
    backups = sorted(backup_dir.glob("ham_checkin_*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass
    return dest
