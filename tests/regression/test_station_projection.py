"""回归测试：station/profile 可重建投影 + 修改呼号 + 撤销语义（任务书第一阶段 #15~#17）。

核心不变量：
- checkins 是唯一事实源，stations/station_profiles 只是投影。
- 编辑/撤销绝不手工 count+1；last_seen 按时间（MAX），不按导入顺序。
"""
from __future__ import annotations

import unittest

from database.models import Checkin
from tests.helpers import make_service
from tests.helpers.mock_excel import MockApp, install_mock_app, make_workbook


def _add(svc, s, seq, cs, time, qth="南京栖霞", device="K6"):
    c = Checkin(session_id=s.id, sequence_no=seq, checkin_time=time, callsign=cs,
                qth_standard=qth, device_standard=device, source="local")
    svc.repo.add_checkin(c)
    return c


class TestStationProjection(unittest.TestCase):
    def test_edit_does_not_increment_station_count(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertEqual(svc.repo.get_station("BG4TKI")["checkin_count"], 1)
            svc.update_checkin(res["checkin"].id, "qth", "南京鼓楼")
            self.assertEqual(svc.repo.get_station("BG4TKI")["checkin_count"], 1,
                             "编辑不得使 count+1")
        finally:
            svc.close()

    def test_old_record_edit_does_not_move_last_seen_backwards(self):
        svc = make_service()
        try:
            s = svc.create_session("t", "2026-08-08")
            c1 = _add(svc, s, 1, "BG4TKI", "2026-08-01T10:00:00")
            _add(svc, s, 2, "BG4TKI", "2026-08-02T10:00:00")
            svc.repo.rebuild_station("BG4TKI")
            self.assertEqual(svc.repo.get_station("BG4TKI")["last_seen"],
                             "2026-08-02T10:00:00")
            # 编辑旧记录 → last_seen 不得回退，count 不变
            svc.update_checkin(c1.id, "qth", "徐州")
            st = svc.repo.get_station("BG4TKI")
            self.assertEqual(st["last_seen"], "2026-08-02T10:00:00")
            self.assertEqual(st["checkin_count"], 2)
        finally:
            svc.close()

    def test_import_order_does_not_affect_station_summary(self):
        """先导入新记录再导入旧记录，投影仍按时间聚合。"""
        svc = make_service()
        try:
            s = svc.create_session("t", "2026-08-08")
            # 导入顺序：先新后旧
            _add(svc, s, 1, "BG4TKI", "2026-08-02T10:00:00", qth="扬州")
            _add(svc, s, 2, "BG4TKI", "2026-08-01T10:00:00", qth="南京")
            svc.repo.rebuild_station("BG4TKI")
            st = svc.repo.get_station("BG4TKI")
            self.assertEqual(st["first_seen"], "2026-08-01T10:00:00")
            self.assertEqual(st["last_seen"], "2026-08-02T10:00:00")
            self.assertEqual(st["last_qth"], "扬州", "last_qth 按时间取最新")
            self.assertEqual(st["checkin_count"], 2)
        finally:
            svc.close()

    def test_station_rebuild_is_idempotent(self):
        svc = make_service()
        try:
            s = svc.create_session("t", "2026-08-08")
            _add(svc, s, 1, "BG4TKI", "2026-08-01T10:00:00")
            _add(svc, s, 2, "BG4TKI", "2026-08-02T10:00:00")
            svc.repo.rebuild_all_stations()
            svc.repo.rebuild_all_profiles()
            before = svc.repo.get_station("BG4TKI")
            svc.repo.rebuild_all_stations()
            svc.repo.rebuild_all_profiles()
            after = svc.repo.get_station("BG4TKI")
            self.assertEqual(before, after)
            self.assertEqual(after["checkin_count"], 2)
        finally:
            svc.close()


class TestChangeCallsign(unittest.TestCase):
    """任务书第一阶段 #16：修改呼号必须重建旧/新站、同步 Excel、审计。"""

    def test_change_callsign_rebuilds_old_station(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertIsNotNone(svc.repo.get_station("BG4TKI"))
            out = svc.update_checkin(res["checkin"].id, "callsign", "BA4XXX")
            self.assertTrue(out["ok"])
            self.assertIsNone(svc.repo.get_station("BG4TKI"),
                              "旧呼号无记录 → 投影应删除")
            st = svc.repo.get_station("BA4XXX")
            self.assertIsNotNone(st)
            self.assertEqual(st["checkin_count"], 1)
            # 审计
            audit = svc.repo.list_audit(res["checkin"].id)
            self.assertTrue(any(a.field_name == "callsign"
                                and a.old_value == "BG4TKI" and a.new_value == "BA4XXX"
                                for a in audit), "修改呼号必须被审计")
        finally:
            svc.close()

    def test_change_callsign_updates_excel(self):
        wb = make_workbook("C:/tmp/cc.xlsx")
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.update_checkin(res["checkin"].id, "callsign", "BA4XXX")
            sheet = wb.Sheets("点名表")
            self.assertEqual(sheet._data.get((2, 3)), "BA4XXX",
                             "Excel 呼号列必须同步更新")
        finally:
            svc.close()


class TestUndo(unittest.TestCase):
    """任务书第一阶段 #17：撤销后投影/画像/历史必须一致。"""

    def test_undo_updates_station_count(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertEqual(svc.repo.get_station("BG4TKI")["checkin_count"], 1)
            svc.undo_last()
            self.assertIsNone(svc.repo.get_station("BG4TKI"),
                              "撤销后无有效记录 → 投影应删除")
            self.assertEqual(svc.repo.profiles_for("BG4TKI", "qth"), [])
        finally:
            svc.close()

    def test_undo_updates_profile(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertEqual(svc.repo.get_station("BG4TKI")["checkin_count"], 2)
            svc.undo_last()
            st = svc.repo.get_station("BG4TKI")
            self.assertEqual(st["checkin_count"], 1)
            total = sum(p.use_count for p in svc.repo.profiles_for("BG4TKI", "qth"))
            self.assertEqual(total, 1, "撤销后画像使用次数应回退")
        finally:
            svc.close()

    def test_undo_changes_recent_history(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            svc.undo_last()  # 撤销 ba4xxx
            hist = svc.repo.station_history("BA4XXX")
            self.assertEqual(hist, [], "撤销后该呼号不应出现在 recent history")
            self.assertIsNone(svc.repo.recent_history("BA4XXX"))
        finally:
            svc.close()

    def test_rebuild_before_after_undo_same_result(self):
        svc = make_service()
        try:
            svc.create_session("t", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.undo_last()
            incremental = svc.repo.get_station("BG4TKI")
            svc.repo.rebuild_all_stations()
            rebuilt = svc.repo.get_station("BG4TKI")
            self.assertEqual(incremental, rebuilt,
                             "增量维护与全量重建结果必须一致")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
