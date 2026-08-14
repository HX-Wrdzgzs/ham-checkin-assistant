"""回归测试：Parser 建议模型（任务书第二阶段 #1~#4）。

规则：
- 历史只进 result.history，绝不写入实际字段。
- Enter = 只提交 explicit/manual accepted；Tab = 接受历史建议。
- 本次输入永远高于历史；模糊/歧义候选不被历史吞掉。
"""
from __future__ import annotations

import unittest

from database.models import Checkin
from tests.helpers import make_service


def _seed_history(svc, callsign="BA4XXX", qth="南京栖霞", device="K6",
                  antenna="771", power="5W"):
    s = svc.create_session("历史", "2026-08-08")
    c = Checkin(session_id=s.id, sequence_no=1, checkin_time="2026-08-08T10:00:00",
                callsign=callsign, qth_standard=qth, device_standard=device,
                antenna_standard=antenna, power_standard=power, source="local")
    svc.repo.add_checkin(c)
    svc.repo.rebuild_profiles_for(callsign)
    svc.repo.rebuild_station(callsign)
    return s


class TestHistoryModel(unittest.TestCase):
    def test_history_is_not_committed_without_accept(self):
        """只输呼号 → Enter 提交：历史字段不得进入提交 payload。"""
        svc = make_service()
        try:
            _seed_history(svc)
            svc.create_session("提交", "2026-08-09")
            r = svc.parse("ba4xxx")
            self.assertEqual(r.qth.value, "", "parse 不得把历史写进字段")
            res = svc.commit(r)
            self.assertTrue(res["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.qth_standard, "", "未接受历史 → 不得提交历史 QTH")
            self.assertEqual(c.device_standard, "")
            self.assertEqual(c.callsign, "BA4XXX")
        finally:
            svc.close()

    def test_tab_accepts_history(self):
        """Tab 接受历史后，Enter 提交才带历史字段。"""
        svc = make_service()
        try:
            _seed_history(svc)
            svc.create_session("提交", "2026-08-09")
            r = svc.parse("ba4xxx")
            r2 = svc.accept_history(r)
            self.assertEqual(r2.qth.value, "南京栖霞")
            self.assertEqual(r2.qth.source, "manual")
            res = svc.commit(r2)
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.qth_standard, "南京栖霞")
            self.assertEqual(c.device_standard, "K6")
        finally:
            svc.close()

    def test_explicit_input_overrides_history(self):
        """本次显式输入 → 历史绝不覆盖。"""
        svc = make_service()
        try:
            _seed_history(svc, qth="南京栖霞")
            r = svc.parse("ba4xxx 南京鼓楼")
            self.assertEqual(r.qth.value, "南京鼓楼")
            self.assertNotIn("history", r.qth.source, "显式输入来源不是历史")
            r2 = svc.accept_history(r)
            self.assertEqual(r2.qth.value, "南京鼓楼", "显式输入优先于历史")
        finally:
            svc.close()

    def test_fuzzy_input_not_hidden_by_history(self):
        """模糊候选（njqix→南京栖霞 88.9%）不被历史直接填掉。"""
        svc = make_service()
        try:
            _seed_history(svc, qth="南京栖霞")
            r = svc.parse("ba4xxx njqix")
            self.assertEqual(r.qth.value, "", "模糊未确认 → 不得用历史/模糊直接填字段")
            self.assertIn("南京栖霞", r.qth.candidates)
            # 提交也不会写入历史 QTH
            svc.create_session("提交", "2026-08-09")
            res = svc.commit(r)
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.qth_standard, "")
        finally:
            svc.close()

    def test_explicit_ambiguous_qth_not_hidden_by_history(self):
        """歧义输入（gl → 南京鼓楼/徐州鼓楼）即使历史存在南京鼓楼也不自动消歧。"""
        svc = make_service()
        try:
            _seed_history(svc, qth="南京鼓楼")
            r = svc.parse("ba4xxx gl")
            self.assertEqual(r.qth.value, "", "歧义必须保持待选")
            self.assertGreaterEqual(len(r.qth.candidates), 2)
        finally:
            svc.close()

    def test_history_never_overrides_current_token(self):
        """已输入 token（即使未匹配）也保留，历史不覆盖当前输入。"""
        svc = make_service()
        try:
            _seed_history(svc, qth="南京栖霞")
            r = svc.parse("ba4xxx njqz")  # njqz 未匹配 → unmatched，历史也不补
            self.assertEqual(r.qth.value, "")
            self.assertIn("njqz", r.unmatched, "未匹配 token 必须保留在 unmatched")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
