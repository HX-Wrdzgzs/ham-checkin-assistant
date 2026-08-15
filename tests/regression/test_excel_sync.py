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
            before = list(sheet_records(wb.Sheets("点名表")))
            wb.save_fail = True
            ok, msg = svc.excel_resync()
            self.assertFalse(ok)
            self.assertEqual(sheet_records(wb.Sheets("点名表")), before,
                             "整场重写 Save 失败时必须恢复工作簿内存数据")
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


class TestDeferredExcelSave(unittest.TestCase):
    """快速点名：先写内存、空闲时一次 Save，且不重复追加已有 written 行。"""

    def test_edit_can_defer_excel_save_without_blocking_service_call(self):
        """修改入口只更新 SQLite 并生成 worker 快照，不同步调用 Excel.Save。"""
        svc, wb = make_svc_with_excel()
        try:
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            cid = res["checkin"].id
            before = wb.save_count
            out = svc.update_checkin(cid, "qth", "南京鼓楼", defer_excel=True)
            self.assertTrue(out["ok"])
            self.assertEqual(wb.save_count, before,
                             "defer_excel=True 不应在 UI 调用路径同步 Save")
            self.assertIsNotNone(out["excel_task"])
            self.assertEqual(out["excel_task"]["excel_field"], "qth")
            c = svc.repo.get_checkin(cid)
            self.assertEqual(c.qth_standard, "南京鼓楼")
            self.assertEqual(c.excel_sync_status, "pending")

            ok, msg = svc.finish_deferred_excel_update({
                "ok": True,
                "checkin_id": cid,
                "row": 2,
                "binding_id": out["excel_task"]["binding_id"],
                "message": "已更新第 2 行",
            })
            self.assertTrue(ok, msg)
            self.assertEqual(svc.repo.get_checkin(cid).excel_sync_status, "persisted")
        finally:
            svc.close()

    def test_deferred_commit_flushes_once(self):
        svc, wb = make_svc_with_excel()
        try:
            before = wb.save_count
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5"), save_excel=False)
            self.assertTrue(res["ok"])
            self.assertEqual(res["excel_state"], "written")
            self.assertFalse(res["excel_persisted"])
            self.assertEqual(wb.save_count, before, "延迟提交不应立即 Save")
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.excel_sync_status, "written")

            ok, msg = svc.flush_excel_pending()
            self.assertTrue(ok, msg)
            self.assertEqual(wb.save_count, before + 1)
            c = svc.repo.get_checkin(c.id)
            self.assertEqual(c.excel_sync_status, "persisted")
            self.assertEqual(c.excel_row, 2)

            # 已经 persisted 的记录不再进入补同步，也不产生第二次 Save。
            ok2, msg2 = svc.flush_excel_pending()
            self.assertTrue(ok2, msg2)
            self.assertEqual(wb.save_count, before + 1)
        finally:
            svc.close()

    def test_written_row_is_not_duplicated_when_flushed_with_another_record(self):
        svc, wb = make_svc_with_excel()
        try:
            r1 = svc.commit(svc.parse("bg4tki njqx k6 y 5"), save_excel=False)
            r2 = svc.commit(svc.parse("ba4xxx njqx k6 y 5"), save_excel=False)
            self.assertEqual(wb.save_count, 0)
            ok, msg = svc.flush_excel_pending()
            self.assertTrue(ok, msg)
            self.assertEqual(wb.save_count, 1)
            records = sheet_records(wb.Sheets("点名表"))
            self.assertEqual([r["callsign"] for r in records], ["BG4TKI", "BA4XXX"])
            self.assertEqual(svc.repo.get_checkin(r1["checkin"].id).excel_row, 2)
            self.assertEqual(svc.repo.get_checkin(r2["checkin"].id).excel_row, 3)
        finally:
            svc.close()

    def test_unmatched_input_is_persisted_to_excel_unmatched_column(self):
        """无法归类的 token 不能随标准字段丢失，应写入显式“未识别”列。"""
        from tests.helpers.mock_excel import make_sheet

        # 普通旧表没有该可选列时，首次出现未识别内容应自动补列，不能丢失输入。
        sheet = make_sheet("点名表")
        wb = make_workbook("C:/tmp/unmatched.xlsx", sheet=sheet)
        svc, _ = make_svc_with_excel(wb)
        try:
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5 mysterytoken"))
            self.assertTrue(res["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.unmatched, "mysterytoken")
            self.assertEqual(wb.Sheets("点名表")._data.get((1, 9)), "未识别")
            self.assertEqual(wb.Sheets("点名表")._data.get((2, 9)), "mysterytoken")
        finally:
            svc.close()

    def test_unmatched_column_does_not_overwrite_manual_column(self):
        """旧模板已有备注列时，补列必须向后寻找空列表头。"""
        from tests.helpers.mock_excel import make_sheet

        sheet = make_sheet("点名表")
        sheet.set_cell(1, 9, "备注")
        sheet.set_cell(2, 9, "人工备注")
        wb = make_workbook("C:/tmp/unmatched-manual-column.xlsx", sheet=sheet)
        svc, _ = make_svc_with_excel(wb)
        try:
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5 mysterytoken"))
            self.assertTrue(res["ok"])
            self.assertEqual(sheet._data.get((1, 9)), "备注")
            self.assertEqual(sheet._data.get((2, 9)), "人工备注")
            self.assertEqual(sheet._data.get((1, 10)), "未识别")
            self.assertEqual(sheet._data.get((2, 10)), "mysterytoken")
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


class TestSignalSync(unittest.TestCase):
    """P1-4：signal 修改必须同步 Excel signal 列。"""

    def test_update_signal_syncs_excel(self):
        wb = make_workbook("C:/tmp/sig.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5 59"))
            out = svc.update_checkin(res["checkin"].id, "signal", "55")
            self.assertTrue(out["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.signal, "55")
            # Excel signal 列（第 8 列）已更新
            self.assertEqual(wb.Sheets("点名表")._data.get((2, 8)), "55")
            self.assertEqual(c.excel_sync_status, "persisted")
        finally:
            svc.close()

    def test_update_signal_save_failure_marks_error(self):
        wb = make_workbook("C:/tmp/sig2.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5 59"))
            wb.save_fail = True
            out = svc.update_checkin(res["checkin"].id, "signal", "55")
            self.assertTrue(out["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.signal, "55")
            self.assertEqual(c.excel_sync_status, "error", "Save 失败必须标 error")
        finally:
            svc.close()

    def test_update_signal_not_connected_stays_pending(self):
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            res = svc.commit(svc.parse("bg4tki njqx k6 y 5 59"))
            # 未连接 Excel 时改 signal → 状态保持 pending，不假装同步
            svc.excel.disconnect()
            out = svc.update_checkin(res["checkin"].id, "signal", "55")
            self.assertTrue(out["ok"])
            c = svc.repo.get_checkin(res["checkin"].id)
            self.assertEqual(c.signal, "55")
            self.assertEqual(c.excel_sync_status, "pending")
        finally:
            svc.close()


class TestAtomicBatchState(unittest.TestCase):
    """P1-7：excel_sync_missing 单事务批量更新状态。"""

    def test_sync_missing_marks_persisted_in_one_batch(self):
        wb = make_workbook("C:/tmp/batch.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            # 先断开 Excel 提交两条 → pending
            res1 = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            res2 = svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            self.assertEqual(svc.repo.get_checkin(res1["checkin"].id).excel_sync_status, "pending")
            # 连接后补同步
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            ok2, msg2 = svc.excel_sync_missing()
            self.assertTrue(ok2, msg2)
            c1 = svc.repo.get_checkin(res1["checkin"].id)
            c2 = svc.repo.get_checkin(res2["checkin"].id)
            self.assertEqual(c1.excel_sync_status, "persisted")
            self.assertEqual(c2.excel_sync_status, "persisted")
            self.assertIsNotNone(c1.excel_row)
            self.assertIsNotNone(c2.excel_row)
        finally:
            svc.close()


class TestResyncVerify(unittest.TestCase):
    """P1-6：resync readback + 逐行 verify + 记录每条 excel_row。"""

    def test_resync_marks_verified_with_rows(self):
        wb = make_workbook("C:/tmp/resync.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            r1 = svc.commit(svc.parse("bg4tki njqx k6 y 5"))  # seq1 → row2
            r2 = svc.commit(svc.parse("ba4xxx njqx k6 y 5"))  # seq2 → row3
            # 手动改坏 Excel 一行（模拟用户编辑）
            sheet = wb.Sheets("点名表")
            sheet.set_cell(3, 3, "WRONG")
            ok2, msg2 = svc.excel_resync()
            self.assertTrue(ok2, msg2)
            c1 = svc.repo.get_checkin(r1["checkin"].id)
            c2 = svc.repo.get_checkin(r2["checkin"].id)
            self.assertEqual(c1.excel_sync_status, "verified")
            self.assertEqual(c1.excel_row, 2)
            self.assertEqual(c2.excel_sync_status, "verified")
            self.assertEqual(c2.excel_row, 3)
            # readback 确认每行 sequence+callsign 正确
            self.assertTrue(svc.excel.verify_row_identity(2, 1, "BG4TKI"))
            self.assertTrue(svc.excel.verify_row_identity(3, 2, "BA4XXX"))
        finally:
            svc.close()

    def test_resync_save_failure_marks_error_not_all_synced(self):
        wb = make_workbook("C:/tmp/resync2.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            r1 = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            wb.save_fail = True
            ok2, msg2 = svc.excel_resync()
            self.assertFalse(ok2)
            c1 = svc.repo.get_checkin(r1["checkin"].id)
            self.assertEqual(c1.excel_sync_status, "error", "Save 失败不得标记 verified")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
