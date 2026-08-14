"""回归测试：DB 唯一约束 + 并发序列安全 + 单实例（任务书第一阶段 #3）。"""
from __future__ import annotations

import sqlite3
import threading
import unittest
import uuid

from database.models import Checkin
from tests.helpers import make_service


class TestSequenceUniqueConstraint(unittest.TestCase):
    def test_sequence_unique_constraint(self):
        """UNIQUE(session_id, sequence_no) 由数据库强制，重复插入必须抛 IntegrityError。"""
        svc = make_service()
        try:
            s = svc.create_session("约束", "2026-08-08")
            c1 = Checkin(session_id=s.id, sequence_no=1, callsign="BG4TKI", source="local")
            svc.repo.add_checkin(c1)
            c2 = Checkin(session_id=s.id, sequence_no=1, callsign="BA4XXX", source="local")
            with self.assertRaises(sqlite3.IntegrityError):
                svc.repo.add_checkin(c2)
            # 不同场次同序号允许
            s2 = svc.create_session("约束2", "2026-08-08")
            c3 = Checkin(session_id=s2.id, sequence_no=1, callsign="BA4XXX", source="local")
            svc.repo.add_checkin(c3)
        finally:
            svc.close()

    def test_concurrent_next_sequence_cannot_duplicate(self):
        """多线程并发提交：不产生重复序号、无异常。"""
        import tempfile
        from pathlib import Path

        from database.db import connect
        from database.repository import Repository
        from database.seed import seed_default_aliases

        tmp = Path(tempfile.mkdtemp())
        conn = connect(tmp / "conc.db")
        repo = Repository(conn)
        seed_default_aliases(repo)
        try:
            s = repo.create_session("并发", "2026-08-08")
            errors: list[Exception] = []

            def worker(n):
                try:
                    for _ in range(20):
                        c = Checkin(session_id=s.id, callsign=f"BG{n:02d}", source="local")
                        repo.add_checkin_with_seq(s.id, c)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [], f"并发插入异常：{errors}")
            rows = conn.execute(
                "SELECT session_id, sequence_no, COUNT(*) c FROM checkins "
                "GROUP BY session_id, sequence_no HAVING c > 1").fetchall()
            self.assertEqual(rows, [], "存在重复序号！")
            total = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
            self.assertEqual(total, 160)
        finally:
            conn.close()


class TestSingleInstance(unittest.TestCase):
    def test_second_instance_is_rejected(self):
        """同一进程内再次 acquire 同一锁名必须被拒绝。"""
        from ui.single_instance import acquire, release

        name = f"ham_test_{uuid.uuid4().hex}"
        self.assertTrue(acquire(name))
        try:
            self.assertFalse(acquire(name), "第二个实例必须被拒绝")
        finally:
            release()


if __name__ == "__main__":
    unittest.main()
