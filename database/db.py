"""SQLite 连接管理 + 每日备份 + 恢复。"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from database import migrations

DB_FILENAME = "ham_checkin.db"

logger = logging.getLogger("ham.db")


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


def _quick_check_ok(conn: sqlite3.Connection) -> bool:
    """PRAGMA quick_check 必须 PASS（任务书第三阶段 #19）。"""
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False


def _file_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _write_backup_metadata(backup_dir: Path, today: str, db_path: Path,
                           config_path: Path | None) -> None:
    """记录 app version / db schema version / created_at / db checksum（任务书第三阶段 #20）。"""
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            schema = migrations.get_version(conn)
        finally:
            conn.close()
        from version import __version__

        meta = {
            "app_version": __version__,
            "db_schema_version": schema,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "db_checksum": _file_sha256(db_path),
        }
        if config_path is not None and Path(config_path).exists():
            meta["config_checksum"] = _file_sha256(Path(config_path))
        meta_path = backup_dir / f"ham_checkin_{today}.metadata.json"
        import json

        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    except Exception:  # noqa: BLE001 - 元数据失败不影响主备份
        logger.warning("backup metadata write failed", exc_info=True)


def backup_daily(db_path: Path, backup_dir: Path, keep: int = 30,
                 config_path: Path | None = None) -> Path | None:
    """每天第一次启动备份一次，保留最近 keep 份。

    流程（任务书第三阶段 #19）：临时文件 → SQLite backup API → quick_check
    → 原子改名。失败记录日志并返回 None（调用方提示，不静默）。
    """
    if not db_path.exists():
        return None
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("backup dir create failed: %s", e)
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    dest = backup_dir / f"ham_checkin_{today}.db"
    if dest.exists():
        return dest  # 当天已备份
    tmp = backup_dir / f"ham_checkin_{today}.db.tmp"
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp))
        try:
            with dst:
                src.backup(dst)
            if not _quick_check_ok(dst):
                logger.warning("backup quick_check FAILED, discard %s", tmp)
                return None
        finally:
            dst.close()
        src.close()
        os.replace(tmp, dest)
        _write_backup_metadata(backup_dir, today, db_path, config_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("backup failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    # 清理旧备份
    backups = sorted(backup_dir.glob("ham_checkin_*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def list_backups(backup_dir: Path) -> list[Path]:
    """检测可用备份（任务书第三阶段 #21）。"""
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("ham_checkin_*.db"))


def restore_backup(backup_db: Path, dest_db: Path) -> tuple[bool, str]:
    """验证并恢复备份（任务书第三阶段 #21）。

    - 备份文件本身 quick_check
    - 恢复副本先写临时文件并 quick_check，通过后原子替换目标。
    """
    if not backup_db.exists():
        return False, "备份文件不存在"
    try:
        conn = sqlite3.connect(str(backup_db))
        try:
            if not _quick_check_ok(conn):
                return False, "备份文件损坏（quick_check 失败），拒绝恢复"
        finally:
            conn.close()
    except sqlite3.Error as e:
        return False, f"备份无法打开：{e}"
    dest = Path(dest_db)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".restore.tmp")
    try:
        src = sqlite3.connect(str(backup_db))
        dst = sqlite3.connect(str(tmp))
        try:
            with dst:
                src.backup(dst)
            if not _quick_check_ok(dst):
                return False, "恢复副本 quick_check 失败"
        finally:
            dst.close()
        src.close()
        os.replace(tmp, dest)
        return True, "恢复成功"
    except Exception as e:  # noqa: BLE001
        logger.warning("restore failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"恢复失败：{e}"
