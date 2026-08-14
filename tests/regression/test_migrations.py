"""回归测试：数据库迁移（任务书第三阶段 #23 / Test Stage 5）。

- v1 → latest、v2 → latest、latest → latest（no-op）
- 迁移后 schema 正确、数据保留、约束有效
- 既有重复 (session_id, sequence_no) 在迁移时去重（保留最小 id）
"""
from __future__ import annotations

import sqlite3
import unittest

from database import migrations


def _build_db_at(version: int) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for v in range(1, version + 1):
        for stmt in migrations.MIGRATIONS[v]:
            conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = {v}")
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


class TestMigrations(unittest.TestCase):
    def _assert_latest(self, conn):
        self.assertEqual(
            migrations.get_version(conn), max(migrations.MIGRATIONS),
            "必须迁移到最新版本")
        cols = _columns(conn, "checkins")
        for c in ("excel_sync_status", "excel_row", "excel_binding_id"):
            self.assertIn(c, cols)
        sess_cols = _columns(conn, "sessions")
        self.assertIn("excel_sheet_name", sess_cols)
        self.assertIn("external_key", sess_cols)
        tbls = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("source_station_state", tbls)
        self.assertIn("import_jobs", tbls)

    def test_v1_to_latest(self):
        conn = _build_db_at(1)
        try:
            cur = conn.execute(
                "INSERT INTO sessions(name, date, status) VALUES('旧场', '2026-08-01', 'active')")
            sid = cur.lastrowid
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign, checkin_time) "
                "VALUES(?,?,?,?)", (sid, 1, "BA4XXX", "2026-08-01T20:00:00"))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            row = conn.execute("SELECT * FROM checkins WHERE id=1").fetchone()
            self.assertEqual(row["callsign"], "BA4XXX", "迁移后数据必须保留")
            # 约束生效：唯一索引存在
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_checkins_session_seq'"
            ).fetchone()
            self.assertIsNotNone(idx)
        finally:
            conn.close()

    def test_v2_to_latest(self):
        conn = _build_db_at(2)
        try:
            cur = conn.execute(
                "INSERT INTO sessions(name, date, status) VALUES('旧场2', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign, excel_synced, excel_row) "
                "VALUES(?,?,?,1,5)", (sid, 1, "BA4XXX"))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            row = conn.execute("SELECT * FROM checkins WHERE id=1").fetchone()
            self.assertEqual(row["excel_synced"], 1)
            # 旧库回填：excel_synced=1 → verified
            self.assertEqual(row["excel_sync_status"], "verified")
        finally:
            conn.close()

    def test_latest_to_latest_noop(self):
        conn = _build_db_at(max(migrations.MIGRATIONS))
        try:
            migrations.migrate(conn)
            migrations.migrate(conn)
            self.assertEqual(migrations.get_version(conn), max(migrations.MIGRATIONS))
        finally:
            conn.close()

    def test_migration_dedupes_duplicate_sequences(self):
        """既有重复 (session_id, sequence_no) → 迁移去重（保留最小 id）。"""
        conn = _build_db_at(1)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('d', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'A')", (sid,))
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'B')", (sid,))
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'C')", (sid,))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            n = conn.execute(
                "SELECT COUNT(*) c FROM checkins WHERE session_id=? AND sequence_no=1", (sid,)
            ).fetchone()["c"]
            self.assertEqual(n, 1, "重复序列必须在迁移时去重")
            callsign = conn.execute(
                "SELECT callsign FROM checkins WHERE session_id=? AND sequence_no=1", (sid,)
            ).fetchone()["callsign"]
            self.assertEqual(callsign, "A", "保留最小 id 的记录")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
