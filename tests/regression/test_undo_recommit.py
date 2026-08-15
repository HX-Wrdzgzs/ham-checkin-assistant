"""回归测试：P0-1 —— 撤销后重新录入不得撞序号唯一约束。

- 序号唯一索引仅约束有效记录（is_deleted=0），软删除后序号可复用。
- Ctrl+Z 后马上重新录入正常，不出现 SQLite IntegrityError。
- 多次撤销后重录正常。
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.helpers import make_service
from tests.helpers.mock_excel import MockApp, install_mock_app, make_workbook


class TestUndoRecommit(unittest.TestCase):
    def test_undo_last_then_commit(self):
        """撤销最后一条后立即重新录入，序号复用不报错。"""
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            r1 = svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            self.assertEqual(r1["checkin"].sequence_no, 1)
            svc.undo_last()
            # 撤销后 next_sequence 回到 1（软删除不占位）
            self.assertEqual(svc.repo.next_sequence(svc.current_session().id), 1)
            r2 = svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            self.assertTrue(r2["ok"], "撤销后重录不得报错")
            self.assertEqual(r2["checkin"].sequence_no, 1, "序号可复用")
            c = svc.repo.get_checkin(r2["checkin"].id)
            self.assertEqual(c.callsign, "BA4XXX")
            # 有效记录数 1，软删除记录仍在（历史保留）
            self.assertEqual(len(svc.repo.list_checkins(svc.current_session().id)), 1)
            self.assertEqual(
                svc.repo.as_dict_rows(
                    "SELECT COUNT(*) c FROM checkins WHERE is_deleted=1")[0]["c"], 1)
        finally:
            svc.close()

    def test_multiple_undo_then_commit(self):
        """连续多次撤销后重录不报错。"""
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            svc.undo_last()
            svc.undo_last()
            self.assertEqual(svc.repo.next_sequence(svc.current_session().id), 1)
            for i in range(3):
                res = svc.commit(svc.parse(f"bg{i:04d} njqx k6 y 5"))
                self.assertTrue(res["ok"])
            self.assertEqual(len(svc.repo.list_checkins(svc.current_session().id)), 3)
        finally:
            svc.close()

    def test_deleted_sequence_can_be_reused(self):
        """同一序号在软删除后可被复用（partial UNIQUE 只约束有效记录）。"""
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))   # seq 1
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))   # seq 2
            svc.undo_last()                                # 撤销 seq 2
            svc.commit(svc.parse("bd4abc njqx k6 y 5"))    # 复用 seq 2
            seqs = [c.sequence_no for c in svc.repo.list_checkins(svc.current_session().id)]
            self.assertEqual(seqs, [1, 2])
            # 唯一约束允许：软删除的旧 seq 2 与新的有效 seq 2 并存
            conn = svc.conn
            n_active = conn.execute(
                "SELECT COUNT(*) c FROM checkins WHERE sequence_no=2 AND is_deleted=0").fetchone()["c"]
            self.assertEqual(n_active, 1)
        finally:
            svc.close()

    def test_undo_commit_excel_resync(self):
        """撤销触发 Excel resync 后再提交，流程完整不报错。"""
        wb = make_workbook("C:/tmp/undo.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            svc.commit(svc.parse("ba4xxx njqx k6 y 5"))
            u = svc.undo_last()
            self.assertTrue(u["ok"])
            # 撤销后 Excel 已 resync（只剩 1 条有效）
            sheet = wb.Sheets("点名表")
            from tests.regression.test_excel_sync import sheet_records
            records = sheet_records(sheet)
            self.assertEqual(len(records), 1)
            res = svc.commit(svc.parse("bd4abc njqx k6 y 5"))
            self.assertTrue(res["ok"], "撤销+resync 后重录不得报错")
        finally:
            svc.close()

    def test_ui_style_undo_does_not_block_on_excel_resync(self):
        """UI 撤销路径只软删除 SQLite，不在主线程执行整场 COM 重排。"""
        wb = make_workbook("C:/tmp/undo-no-resync.xlsx")
        svc = make_service()
        try:
            svc.create_session("场A", "2026-08-08")
            install_mock_app(svc.excel, MockApp([wb], wb))
            ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
            self.assertTrue(ok, msg)
            svc.commit(svc.parse("bg4tki njqx k6 y 5"))
            with mock.patch.object(svc, "excel_resync") as resync:
                out = svc.undo_last(sync_excel=False)
            self.assertTrue(out["ok"])
            resync.assert_not_called()
            # 原表仍在，避免卡顿/失败时自动清空用户数据；SQLite 撤销已完成。
            from tests.regression.test_excel_sync import sheet_records
            self.assertEqual(len(sheet_records(wb.Sheets("点名表"))), 1)
            self.assertEqual(len(svc.repo.list_checkins(svc.current_session().id)), 0)
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
