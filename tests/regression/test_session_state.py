"""回归测试：Session 状态机（任务书第一阶段 #4）。"""
from __future__ import annotations

import unittest

from tests.helpers import make_service


class TestSessionState(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()

    def tearDown(self):
        self.svc.close()

    def test_end_session_clears_current_session(self):
        """end_current_session() 后必须清空 _current_session_id。"""
        self.svc.create_session("场A", "2026-08-08")
        self.assertIsNotNone(self.svc.current_session())
        self.svc.end_current_session()
        self.assertIsNone(self.svc.current_session())

    def test_cannot_commit_to_ended_session(self):
        """ended 场次不允许 commit；set_current_session 拒绝 ended。"""
        a = self.svc.create_session("场A", "2026-08-08")
        r = self.svc.parse("bg4tki njqx k6 y 5")
        self.svc.commit(r)
        self.svc.end_current_session()
        # 直接 set 回 ended 场次必须被拒绝
        self.assertFalse(self.svc.set_current_session(a.id))
        self.assertIsNone(self.svc.current_session())
        # ended 场次记录数不变
        self.assertEqual(len(self.svc.repo.list_checkins(a.id)), 1)

    def test_commit_after_end_creates_new_session(self):
        """结束场次后下一次提交自动创建新场次，绝不续写 ended。"""
        a = self.svc.create_session("场A", "2026-08-08")
        self.svc.commit(self.svc.parse("bg4tki njqx k6 y 5"))
        self.svc.end_current_session()
        self.svc.commit(self.svc.parse("ba4xxx njqx k6 y 5"))
        b = self.svc.current_session()
        self.assertIsNotNone(b)
        self.assertNotEqual(b.id, a.id, "不得继续写入 ended 场次")
        # 新记录进了新场次，场A 保持 1 条
        self.assertEqual(len(self.svc.repo.list_checkins(a.id)), 1)
        self.assertEqual(len(self.svc.repo.list_checkins(b.id)), 1)

    def test_select_ended_session_is_readonly(self):
        """ended 场次默认只读：直接 set 拒绝；必须显式 reopen 才可写。"""
        a = self.svc.create_session("场A", "2026-08-08")
        self.svc.end_current_session()
        self.assertFalse(self.svc.set_current_session(a.id))
        # 显式 reopen 后才可写
        self.assertTrue(self.svc.reopen_session(a.id))
        self.assertEqual(self.svc.current_session().id, a.id)
        self.assertEqual(self.svc.repo.get_session(a.id).status, "active")
        self.svc.commit(self.svc.parse("bg4tki njqx k6 y 5"))
        self.assertEqual(len(self.svc.repo.list_checkins(a.id)), 1)


if __name__ == "__main__":
    unittest.main()
