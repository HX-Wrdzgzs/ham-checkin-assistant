"""回归测试：备份 / 恢复（任务书第三阶段 #19~#21 / Test Stage 15）。

流程：建库 → 插入 N 条 → backup → 再插 → restore → 精确恢复 + quick_check PASS。
损坏备份必须拒绝恢复。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.db import backup_daily, list_backups, restore_backup
from database.models import Checkin
from database.repository import Repository


def _make_db(path: Path, n: int) -> None:
    from database.db import connect
    from database.seed import seed_default_aliases

    conn = connect(path)
    repo = Repository(conn)
    seed_default_aliases(repo)
    s = repo.create_session("测试", "2026-08-08")
    for i in range(n):
        repo.add_checkin(Checkin(
            session_id=s.id, sequence_no=i + 1, callsign=f"BG{i:04d}",
            qth_standard="南京栖霞", checkin_time="2026-08-08T20:00:00", source="local"))
    conn.close()


def _count(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        n = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()[0]
        return n
    finally:
        conn.close()


class TestBackupRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_backup_"))

    def test_backup_and_restore(self):
        """插入 100 → backup → 再插 20 → restore → 精确回到 100 + quick_check PASS。"""
        db = self.tmp / "data" / "ham.db"
        _make_db(db, 100)
        bak_dir = self.tmp / "backup"
        b = backup_daily(db, bak_dir, keep=5)
        self.assertIsNotNone(b)
        # 再插 20
        from database.db import connect

        conn = connect(db)
        repo = Repository(conn)
        s = repo.list_sessions()[0]
        for i in range(100, 120):
            repo.add_checkin(Checkin(
                session_id=s.id, sequence_no=i + 1, callsign=f"BG{i:04d}",
                qth_standard="南京栖霞", checkin_time="2026-08-08T20:00:00", source="local"))
        conn.close()
        self.assertEqual(_count(db), 120)
        # 恢复
        ok, msg = restore_backup(b, db)
        self.assertTrue(ok, msg)
        self.assertEqual(_count(db), 100, "恢复后必须精确回到 100 条")
        conn = sqlite3.connect(str(db))
        try:
            qc = conn.execute("PRAGMA quick_check").fetchone()[0]
            self.assertEqual(qc, "ok")
        finally:
            conn.close()

    def test_restore_rejects_corrupted_backup(self):
        """损坏备份必须拒绝恢复。"""
        db = self.tmp / "data" / "ham.db"
        _make_db(db, 10)
        bak_dir = self.tmp / "backup"
        b = backup_daily(db, bak_dir, keep=5)
        self.assertIsNotNone(b)
        # 破坏备份文件（截断为一半，必然损坏且 quick_check 必失败）
        b.write_bytes(b.read_bytes()[: len(b.read_bytes()) // 2])
        dest = self.tmp / "restored.db"
        ok, msg = restore_backup(b, dest)
        self.assertFalse(ok, "损坏备份必须拒绝")
        self.assertFalse(dest.exists(), "恢复失败不得产生目标文件")

    def test_backup_writes_metadata(self):
        """备份附带 metadata.json（版本 / schema / checksum）。"""
        db = self.tmp / "data" / "ham.db"
        _make_db(db, 5)
        bak_dir = self.tmp / "backup"
        backup_daily(db, bak_dir, keep=5, config_path=self.tmp / "config.json")
        metas = list(bak_dir.glob("*.metadata.json"))
        self.assertEqual(len(metas), 1)
        meta = json.loads(metas[0].read_text(encoding="utf-8"))
        self.assertIn("app_version", meta)
        self.assertIn("db_schema_version", meta)
        self.assertIn("db_checksum", meta)
        self.assertIn("created_at", meta)

    def test_list_backups(self):
        db = self.tmp / "data" / "ham.db"
        _make_db(db, 3)
        bak_dir = self.tmp / "backup"
        backup_daily(db, bak_dir, keep=5)
        backups = list_backups(bak_dir)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].suffix, ".db")

    def test_same_day_corrupt_backup_is_redone(self):
        """P2：当天已有备份损坏 → backup_daily 检测到并重建，不沿用坏文件。"""
        db = self.tmp / "data" / "ham.db"
        _make_db(db, 5)
        bak_dir = self.tmp / "backup"
        b = backup_daily(db, bak_dir, keep=5)
        self.assertIsNotNone(b)
        # 破坏当天备份
        b.write_bytes(b.read_bytes()[: len(b.read_bytes()) // 2])
        b2 = backup_daily(db, bak_dir, keep=5)
        self.assertIsNotNone(b2)
        conn = sqlite3.connect(str(b2))
        try:
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()[0], 5)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
