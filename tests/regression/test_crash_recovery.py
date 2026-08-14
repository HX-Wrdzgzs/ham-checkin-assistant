"""回归测试：首次启动崩溃恢复顺序（任务书第一阶段 #5）。

正确顺序：打开 DB → 读已有 active → 崩溃恢复 → 处理完成 → 仍无 current 才建新场次。
禁止先自动创建 active session 再恢复。
"""
from __future__ import annotations

import unittest

from tests.helpers import make_service


class TestCrashRecovery(unittest.TestCase):
    def test_fresh_start_does_not_trigger_crash_recovery(self):
        """全新库：启动时无 active sessions，无需恢复，且不自动建 ghost。"""
        svc = make_service()
        try:
            self.assertEqual(svc.startup_sessions(), [])
            self.assertIsNone(svc.current_session())
            # 恢复决策对空列表无副作用
            self.assertIsNone(svc.handle_crash_recovery("defer"))
        finally:
            svc.close()

    def test_real_stale_session_triggers_recovery(self):
        """存在未结束场次（崩溃残留）→ startup_sessions 必须报告。"""
        svc = make_service()
        try:
            a = svc.repo.create_session("旧场", "2026-08-07")
            stale = svc.startup_sessions()
            self.assertTrue(any(s.id == a.id for s in stale), "必须检测到残留 active 场次")
        finally:
            svc.close()

    def test_cancel_recovery_does_not_create_ghost_active_session(self):
        """取消/稍后处理 → 不创建幽灵 active session，也不把残留场次设为 current。"""
        svc = make_service()
        try:
            a = svc.repo.create_session("旧场", "2026-08-07")
            sid = svc.handle_crash_recovery("defer")
            self.assertIsNone(sid)
            self.assertIsNone(svc.current_session())
            self.assertEqual(len(svc.repo.active_sessions()), 1,
                             "残留场次保持 active（未误操作），但不作为 current")
            # 显式恢复指定场次
            sid2 = svc.handle_crash_recovery(str(a.id))
            self.assertEqual(sid2, a.id)
            self.assertEqual(svc.current_session().id, a.id)
        finally:
            svc.close()

    def test_end_all_ends_stale_sessions(self):
        svc = make_service()
        try:
            svc.repo.create_session("旧场A", "2026-08-07")
            svc.repo.create_session("旧场B", "2026-08-07")
            self.assertEqual(len(svc.repo.active_sessions()), 2)
            sid = svc.handle_crash_recovery("end_all")
            self.assertIsNone(sid)
            self.assertEqual(svc.repo.active_sessions(), [])
            self.assertIsNone(svc.current_session())
        finally:
            svc.close()

    def test_ensure_session_after_recovery(self):
        """恢复完成后仍无 current → ensure_session 才创建新场次。"""
        svc = make_service()
        try:
            self.assertIsNone(svc.current_session())
            s = svc.ensure_session()
            self.assertIsNotNone(s.id)
            self.assertEqual(svc.current_session().id, s.id)
            # 已有 current 时 ensure_session 不重复建
            s2 = svc.ensure_session()
            self.assertEqual(s2.id, s.id)
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
