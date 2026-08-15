"""回归测试：数据库迁移（任务书第三阶段 #23 / 第二轮 P0-2）。

- v1 → latest、v2 → latest、latest → latest（no-op）
- 迁移后 schema 正确、数据保留、约束有效
- 重复序列**稳定重新编号**，绝不 DELETE 签到
- source_record 冲突按完整字段确认（真重复软删 / 假冲突保留两条）
- 迁移前后有效/总记录数不变（写入 migration_log）
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
            if callable(stmt):
                stmt(conn)
            else:
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

    def _counts(self, conn) -> tuple[int, int]:
        active = conn.execute("SELECT COUNT(*) c FROM checkins WHERE is_deleted=0").fetchone()["c"]
        total = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
        return active, total

    def test_migration_renumbers_duplicate_sequence(self):
        """重复序列 → 稳定重新编号（保留最早原序号），不删除任何记录。"""
        conn = _build_db_at(1)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('d', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'A')", (sid,))
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'B')", (sid,))
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'C')", (sid,))
            conn.commit()
            active_before, total_before = self._counts(conn)
            migrations.migrate(conn)
            self._assert_latest(conn)
            # 不删除：总记录数与有效记录数不变
            active_after, total_after = self._counts(conn)
            self.assertEqual(total_before, total_after, "迁移不得减少总记录数")
            self.assertEqual(active_before, active_after, "迁移不得减少有效记录数")
            # 三个记录都有不同序列
            seqs = [r["sequence_no"] for r in conn.execute(
                "SELECT sequence_no FROM checkins WHERE session_id=? ORDER BY id", (sid,))]
            self.assertEqual(len(seqs), len(set(seqs)), "序列必须唯一")
            self.assertEqual(seqs[0], 1, "最早记录保留原序号")
            # partial 唯一索引存在且仅约束有效记录
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign, is_deleted) "
                         "VALUES(?,1,'Z',1)", (sid,))
            conn.commit()  # 软删除行可与有效行同序号共存
        finally:
            conn.close()

    def test_migration_never_drops_distinct_checkins(self):
        """迁移不得让不同签到消失（无任何冲突数据也必须保留）。"""
        conn = _build_db_at(1)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            for i in range(1, 6):
                conn.execute(
                    "INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,?,?)",
                    (sid, i, f"BG{i:04d}"))
            conn.commit()
            _, total_before = self._counts(conn)
            migrations.migrate(conn)
            self._assert_latest(conn)
            _, total_after = self._counts(conn)
            self.assertEqual(total_before, total_after)
            self.assertEqual(total_after, 5)
        finally:
            conn.close()

    def test_migration_preserves_soft_deleted_rows(self):
        """软删除行迁移后保留（不得被清掉）。"""
        conn = _build_db_at(1)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign, is_deleted) "
                         "VALUES(?,5,'BG4DEL',1)", (sid,))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            row = conn.execute("SELECT * FROM checkins WHERE callsign='BG4DEL'").fetchone()
            self.assertIsNotNone(row, "软删除行必须保留")
            self.assertEqual(row["is_deleted"], 1)
        finally:
            conn.close()

    def test_migration_preserves_active_rows(self):
        conn = _build_db_at(1)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'active')")
            sid = cur.lastrowid
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign, is_deleted) "
                         "VALUES(?,3,'BG4ACT',0)", (sid,))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            row = conn.execute("SELECT * FROM checkins WHERE callsign='BG4ACT'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["is_deleted"], 0)
        finally:
            conn.close()

    def test_migration_writes_report(self):
        """迁移把前后记录数写入 migration_log（P0-2 留痕）。"""
        conn = _build_db_at(2)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'A')", (sid,))
            conn.execute("INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'B')", (sid,))
            conn.commit()
            migrations.migrate(conn)
            logs = conn.execute(
                "SELECT * FROM migration_log WHERE action='sequence_partial_unique'").fetchall()
            self.assertTrue(len(logs) >= 1, "必须写入迁移报告")
            self.assertIn("total_before=2", logs[0]["detail"])
            self.assertIn("total_after=2", logs[0]["detail"])
        finally:
            conn.close()

    def test_source_id_collision_does_not_delete_different_record(self):
        """source_record_id 相同但内容不同的记录 → 保留两条（不得删除不同签到）。"""
        conn = _build_db_at(5)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            srcid = "COLLIDE_HASH"
            # 两条内容不同但同 source_record_id（模拟历史坏数据/假冲突）
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign, checkin_time, source, source_record_id) "
                "VALUES(?,1,'BA4XXX','2026-08-01T20:00:00','365dt',?)", (sid, srcid))
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign, checkin_time, source, source_record_id) "
                "VALUES(?,2,'BA4YYY','2026-08-02T20:00:00','365dt',?)", (sid, srcid))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            n = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
            self.assertEqual(n, 2, "假冲突必须保留两条记录")
            # 后一条 source_record_id 被清空以允许唯一索引
            cleared = conn.execute(
                "SELECT COUNT(*) c FROM checkins WHERE source_record_id=''").fetchone()["c"]
            self.assertEqual(cleared, 1)
        finally:
            conn.close()

    def test_source_id_true_duplicate_soft_merged(self):
        """真重复（内容全等）→ 迁移软删除非最早记录，保留历史行。"""
        conn = _build_db_at(5)
        try:
            cur = conn.execute("INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'ended')")
            sid = cur.lastrowid
            srcid = "TRUE_DUP_HASH"
            for i in (1, 2):
                conn.execute(
                    "INSERT INTO checkins(session_id, sequence_no, callsign, checkin_time, "
                    "source, source_record_id, qth_standard) "
                    "VALUES(?,?, 'BA4XXX','2026-08-01T20:00:00','365dt',?,'南京')",
                    (sid, i, srcid))
            conn.commit()
            migrations.migrate(conn)
            self._assert_latest(conn)
            active = conn.execute(
                "SELECT COUNT(*) c FROM checkins WHERE source_record_id=? AND is_deleted=0",
                (srcid,)).fetchone()["c"]
            self.assertEqual(active, 1, "真重复只保留一条有效")
            total = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
            self.assertEqual(total, 2, "历史行仍保留（软删除）")
        finally:
            conn.close()


class TestV10Constraints(unittest.TestCase):
    """v10：checkins.session_id 外键 + is_deleted/status CHECK 约束。"""

    def test_v10_to_latest(self):
        conn = _build_db_at(9)
        try:
            cur = conn.execute(
                "INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'active')")
            sid = cur.lastrowid
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'BA4XXX')",
                (sid,))
            conn.commit()
            migrations.migrate(conn)
            self.assertEqual(migrations.get_version(conn), max(migrations.MIGRATIONS))
            row = conn.execute("SELECT * FROM checkins WHERE callsign='BA4XXX'").fetchone()
            self.assertIsNotNone(row, "数据必须保留")
            self.assertEqual(row["session_id"], sid)
        finally:
            conn.close()

    def test_orphan_checkins_removed_on_migrate(self):
        """父场次已不存在的孤儿签到 → 迁移时清理（计数留痕）。"""
        conn = _build_db_at(9)
        try:
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(999,1,'ORPHAN')")
            conn.commit()
            migrations.migrate(conn)
            n = conn.execute(
                "SELECT COUNT(*) c FROM checkins WHERE callsign='ORPHAN'").fetchone()["c"]
            self.assertEqual(n, 0, "孤儿记录必须清理")
            log = conn.execute(
                "SELECT * FROM migration_log WHERE action='fk_check_constraints'").fetchone()
            self.assertIsNotNone(log)
            self.assertIn("orphan_deleted=1", log["detail"])
        finally:
            conn.close()

    def test_fk_blocks_orphan_insert(self):
        conn = _build_db_at(max(migrations.MIGRATIONS))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO checkins(session_id, sequence_no, callsign) "
                    "VALUES(999,1,'BAD')")
            conn.commit()
        finally:
            conn.close()

    def test_fk_allows_valid_insert(self):
        conn = _build_db_at(max(migrations.MIGRATIONS))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            cur = conn.execute(
                "INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'active')")
            sid = cur.lastrowid
            conn.execute(
                "INSERT INTO checkins(session_id, sequence_no, callsign) VALUES(?,1,'OK')",
                (sid,))
            conn.commit()
        finally:
            conn.close()

    def test_check_blocks_bad_is_deleted(self):
        conn = _build_db_at(max(migrations.MIGRATIONS))
        try:
            cur = conn.execute(
                "INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'active')")
            sid = cur.lastrowid
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO checkins(session_id, sequence_no, callsign, is_deleted) "
                    "VALUES(?,1,'BAD',2)", (sid,))
            conn.commit()
        finally:
            conn.close()

    def test_check_blocks_bad_session_status(self):
        conn = _build_db_at(max(migrations.MIGRATIONS))
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO sessions(name, date, status) VALUES('s', '2026-08-01', 'bogus')")
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
