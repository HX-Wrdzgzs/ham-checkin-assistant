"""回归测试：Excel-Session 绑定、同步状态机、Save 错误传播、一致性（任务书第一阶段 #5~#14）。

全部使用 Mock COM，不依赖真实 Excel。
"""
from __future__ import annotations

import unittest

from database.models import Checkin
from tests.helpers import make_service
from tests.helpers.mock_excel import MockApp, install_mock_app, make_workbook


def sheet_records(sheet) -> list[dict]:
    """从 Mock sheet 提取数据行 [{sequence, callsign, qth}]。"""
    out = []
    max_r = max((r for (r, _c) in sheet._data), default=0)
    for r in range(2, max_r + 1):
        rec = {"_row": r,
               "sequence": sheet._data.get((r, 1)),
               "callsign": sheet._data.get((r, 3)),
               "qth": sheet._data.get((r, 4))}
        if rec["sequence"] is not None or rec["callsign"] is not None:
            out.append(rec)
    return out


def make_svc_with_excel(workbook=None):
    """构建 AppService + 连接 Mock Excel。"""

    svc = make_service()
    svc.create_session("场A", "2026-08-08")
    wb = workbook or make_workbook("C:/tmp/A.xlsx")
    install_mock_app(svc.excel, MockApp([wb], wb))
    ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
    assert ok, msg
    return svc, wb


class TestExcelSessionBinding(unittest.TestCase):
    """任务书第一阶段 #5：Excel 绑定是 Session 级的。"""

    def test_excel_binding_is_session_scoped(self):
        svc, wb = make_svc_with_excel(make_workbook("C:/tmp/A.xlsx"))
        try:
            self.assertIsNotNone(svc.excel.sheet, "场 A 应已连接")
            svc.create_session("场B", "2026-08-09")
            self.assertIsNone(svc.excel.sheet, "B 场无绑定 → 必须显示未连接")
        finally:
            svc.close()

    def test_switch_session_disconnects_previous_excel(self):
        svc, wb = make_svc_with_excel(make_workbook("C:/tmp/A.xlsx"))
        try:
            a = svc.current_session()
            svc.create_session("场B", "2026-08-09")
            self.assertIsNone(svc.excel.sheet)
            # 切回 A → 恢复 A 的绑定
            self.assertTrue(svc.set_current_session(a.id))
            self.assertIsNotNone(svc.excel.sheet)
            self.assertEqual(svc.excel.workbook.FullName, "C:/tmp/A.xlsx")
        finally:
            svc.close()

    def test_session_b_does_not_write_session_a_workbook(self):
        wb_a = make_workbook("C:/tmp/A.xlsx")
        svc, wb = make_svc_with_excel(wb_a)
        try:
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            svc.create_session("场B", "2026-08-09")
            svc.commit(svc.parse("bd4abc njqx k6 y 5"))
            records = sheet_records(wb_a.Sheets("点名表"))
            self.assertEqual(len(records), 2, "A 场 Excel 只能有 A 场记录")
            self.assertEqual(records[0]["callsign"], "BG4TKI")
            self.assertEqual(records[1]["callsign"], "BA4XXX")
        finally:
            svc.close()

    def test_missing_bound_workbook_fails_closed(self):
        svc, wb = make_svc_with_excel(make_workbook("C:/tmp/A.xlsx"))
        try:
            a = svc.current_session()
            svc.repo.update_session(a.id, excel_path="C:/tmp/MISSING.xlsx")
            svc.create_session("场B", "2026-08-09")
            self.assertTrue(svc.set_current_session(a.id))
            self.assertIsNone(svc.excel.sheet, "绑定缺失 → fail-closed 未连接，不得回退")
        finally:
            svc.close()


class TestExcelSaveErrorPropagation(unittest.TestCase):
    """任务书第一阶段 #11/#12：Save 失败必须传播，DB 不得标记已同步。"""

    def test_excel_write_success_save_failure_remains_unsynced(self):
        svc, wb = make_svc_with_excel()
        try:
            wb.save_fail = True
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertTrue(res["ok"])
            self.assertFalse(res["excel_ok"], "Save 失败 → excel_ok 必须为 False")
            self.assertEqual(res["excel_state"], "error")
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.excel_sync_status, "error")
            self.assertEqual(c.excel_synced, 0, "Save 失败不得标记已同步")
            self.assertTrue(c.excel_last_error)
        finally:
            svc.close()

    def test_excel_update_save_failure_marks_error(self):
        svc, wb = make_svc_with_excel()
        try:
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            wb.save_fail = True
            out = svc.update_checkin(res["checkin"].id, "qth", "南京鼓楼")
            self.assertTrue(out["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.qth_standard, "南京鼓楼", "DB 应已更新")
            self.assertEqual(c.excel_sync_status, "error", "Save 失败 → error")
        finally:
            svc.close()

    def test_excel_resync_save_failure_does_not_mark_all_synced(self):
        svc, wb = make_svc_with_excel()
        try:
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            wb.save_fail = True
            ok, msg = svc.excel_resync()
            self.assertFalse(ok)
            for c in svc.repo.list_checkins(svc.current_session().id):
                self.assertNotEqual(c.excel_sync_status, "verified",
                                    "resync Save 失败不得标记全部已同步")
        finally:
            svc.close()

    def test_excel_sync_missing_save_failure_rolls_back_sync_state(self):
        svc, wb = make_svc_with_excel()
        try:
            # 断开 Excel 提交 → pending
            svc.excel.disconnect()
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            c1 = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c1.excel_sync_status, "pending")
            # 重连，Save 失败 → 补同步必须失败且不标记成功
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            wb.save_fail = True
            ok2, msg2 = svc.excel_sync_missing()
            self.assertFalse(ok2)
            c1b = svc.repo.get_checkin(c1.id)
            self.assertNotEqual(c1b.excel_sync_status, "verified")
            self.assertIn("保存失败", msg2)
        finally:
            svc.close()


def _mk(seq, cs, qth="南京", signal="59", device="K6", antenna="771", power="5W",
        time="2026-08-08T22:13:00"):
    return Checkin(sequence_no=seq, callsign=cs, qth_standard=qth,
                   device_standard=device, antenna_standard=antenna,
                   power_standard=power, signal=signal, checkin_time=time)


class TestConsistency(unittest.TestCase):
    """任务书第一阶段 #14：一致性检查重写。"""

    def _report(self, sqlite, excel):
        from services.app_service import build_consistency_report

        return build_consistency_report(sqlite, excel)

    def test_consistency_detects_signal_diff(self):
        excel = [{"_row": 2, "sequence": "1", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "device": "K6", "antenna": "771", "power": "5W", "signal": "55"},
                 {"_row": 3, "sequence": "2", "time": "22:13", "callsign": "BA4XXX",
                  "qth": "南京", "device": "K6", "antenna": "771", "power": "5W", "signal": "59"}]
        ok, report = self._report([_mk(1, "BG4TKI"), _mk(2, "BA4XXX")], excel)
        self.assertFalse(ok)
        self.assertIn("SIGNAL", report)

    def test_consistency_detects_duplicate_sequence(self):
        excel = [{"_row": 2, "sequence": "1", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "signal": "59"},
                 {"_row": 3, "sequence": "1", "time": "22:13", "callsign": "BA4XXX",
                  "qth": "南京", "signal": "59"}]
        ok, report = self._report([_mk(1, "BG4TKI")], excel)
        self.assertFalse(ok)
        self.assertIn("DUPLICATE_SEQUENCE", report)

    def test_consistency_detects_invalid_sequence(self):
        excel = [{"_row": 2, "sequence": "abc", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "signal": "59"}]
        ok, report = self._report([_mk(1, "BG4TKI")], excel)
        self.assertFalse(ok)
        self.assertIn("INVALID_SEQUENCE", report)

    def test_consistency_reads_rows_after_internal_blank(self):
        """内部空行后的数据必须继续被检查（含差异也要报出）。"""
        excel = [{"_row": 2, "sequence": "1", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "signal": "59"},
                 {"_row": 3, "sequence": "", "time": "", "callsign": "", "qth": "", "signal": ""},
                 {"_row": 4, "sequence": "2", "time": "22:13", "callsign": "BA4XXX",
                  "qth": "南京", "signal": "55"}]
        ok, report = self._report([_mk(1, "BG4TKI"), _mk(2, "BA4XXX")], excel)
        self.assertFalse(ok)
        self.assertIn("SIGNAL", report, "空行后的数据差异必须被检测")

    def test_consistency_detects_extra_row(self):
        excel = [{"_row": 2, "sequence": "1", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "signal": "59"},
                 {"_row": 3, "sequence": "99", "time": "22:13", "callsign": "XXXX",
                  "qth": "南京", "signal": "59"}]
        ok, report = self._report([_mk(1, "BG4TKI")], excel)
        self.assertFalse(ok)
        self.assertIn("EXTRA_IN_EXCEL", report)

    def test_consistency_detects_missing_row(self):
        excel = [{"_row": 2, "sequence": "1", "time": "22:13", "callsign": "BG4TKI",
                  "qth": "南京", "signal": "59"}]
        ok, report = self._report([_mk(1, "BG4TKI"), _mk(2, "BA4XXX")], excel)
        self.assertFalse(ok)
        self.assertIn("MISSING_IN_EXCEL", report)


if __name__ == "__main__":
    unittest.main()
