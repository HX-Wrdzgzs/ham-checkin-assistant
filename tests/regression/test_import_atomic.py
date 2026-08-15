"""回归测试：Excel 导入原子化、job 状态、跨文件去重、.xlsx only（任务书第三阶段 #1~#4）。

Test Stage 9：fail → 0 half-import；overlap → dedupe；completed 才能整文件跳过。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from database.db import connect
from database.repository import Repository
from database.seed import seed_default_aliases
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from providers.excel_import import ExcelImportProvider
from services.standardizer import Standardizer

HEADERS = ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率"]


def make_xlsx(path: Path, rows: list[list], headers=None):
    wb = Workbook()
    ws = wb.active
    ws.append(headers or HEADERS)
    for r in rows:
        ws.append(r)
    wb.save(path)
    wb.close()


def _env():
    tmp = Path(tempfile.mkdtemp(prefix="ham_import_"))
    conn = connect(tmp / "imp.db")
    repo = Repository(conn)
    seed_default_aliases(repo)
    std = Standardizer(AliasStore(repo), RegionIndex("江苏"))
    return tmp, conn, repo, std


class TestImportAtomic(unittest.TestCase):
    def test_import_atomic_rolls_back_on_failure(self):
        """导入中途失败 → session/raw_imports/checkins 全部回滚，job 标记 failed。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "半导入.xlsx"
            make_xlsx(f, [[1, "2000", "BA4XXX", "南京", "K6", "771", "5W"],
                          [2, "2010", "BG4TKI", "扬州", "705", "原", "10W"]])
            prov = ExcelImportProvider(repo)
            with mock.patch.object(
                    repo, "import_file_atomic",
                    side_effect=RuntimeError("mid-import failure")):
                imp, skip, msg = prov.import_file(f, std)
            self.assertEqual(imp, 0)
            self.assertIn("已回滚", msg)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"], 0,
                             "失败后不得留下任何 checkin")
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM raw_imports").fetchone()["c"], 0,
                             "失败后不得留下 raw_imports（0 half-import）")
            # P1-8：失败后不得留下 ghost active session
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"], 0,
                             "失败后不得留下任何 session（含 active ghost）")
            # 未标记 completed → 允许重新导入
            self.assertFalse(repo.import_job_completed("excel_import", repo.file_hash(str(f))))
            imp2, _, msg2 = prov.import_file(f, std)
            self.assertEqual(imp2, 2, "重试应成功")
            self.assertTrue(repo.import_job_completed("excel_import", repo.file_hash(str(f))))
        finally:
            conn.close()

    def test_import_success_session_ended(self):
        """成功导入后 session 已结束（非 active ghost）。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "成功.xlsx"
            make_xlsx(f, [[1, "2000", "BA4XXX", "南京", "K6", "771", "5W"]])
            prov = ExcelImportProvider(repo)
            imp, _, _ = prov.import_file(f, std)
            self.assertEqual(imp, 1)
            sessions = [dict(r) for r in conn.execute("SELECT * FROM sessions")]
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["status"], "ended")
        finally:
            conn.close()

    def test_import_job_completed_skips_file(self):
        """completed 的文件整文件跳过（不再用 raw_imports 有行判定）。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "完成.xlsx"
            make_xlsx(f, [[1, "2000", "BA4XXX", "南京", "K6", "771", "5W"]])
            prov = ExcelImportProvider(repo)
            imp, _, _ = prov.import_file(f, std)
            self.assertEqual(imp, 1)
            # 已 completed → 第二次整文件跳过
            imp2, _, msg2 = prov.import_file(f, std)
            self.assertEqual(imp2, 0)
            self.assertIn("已导入过", msg2)
            total = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
            self.assertEqual(total, 1)
        finally:
            conn.close()

    def test_overlap_between_two_files_is_deduped(self):
        """两个文件含同一签到 → 只能导入一次（业务指纹跨文件去重）。"""
        tmp, conn, repo, std = _env()
        try:
            a = tmp / "A.xlsx"
            b = tmp / "B.xlsx"
            rec = [1, "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"]
            make_xlsx(a, [rec, [2, "2010", "BG4TKI", "扬州", "705", "原", "10W"]])
            make_xlsx(b, [[1, "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"],
                          [3, "2020", "BD4ABC", "徐州", "9000", "771", "5W"]])
            prov = ExcelImportProvider(repo)
            prov.import_file(a, std)
            imp, skip, _ = prov.import_file(b, std)
            self.assertEqual(skip, 1, "重叠记录必须被去重")
            self.assertEqual(imp, 1)
            total = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
            self.assertEqual(total, 3, "BA4XXX 只应存在一次")
        finally:
            conn.close()

    def test_xls_rejected(self):
        """.xls 明确拒绝（不假装支持）。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "old.xls"
            f.write_bytes(b"not-real-xls")
            prov = ExcelImportProvider(repo)
            imp, _, msg = prov.import_file(f, std)
            self.assertEqual(imp, 0)
            self.assertIn(".xls", msg)
        finally:
            conn.close()

    def test_import_rebuilds_projection(self):
        """导入后 station 投影与 checkins 一致。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "投影.xlsx"
            make_xlsx(f, [[1, "2000", "BA4XXX", "南京", "K6", "771", "5W"],
                          [2, "2010", "BA4XXX", "扬州", "K6", "771", "5W"],
                          [3, "2020", "BG4TKI", "南京", "705", "原", "10W"]])
            ExcelImportProvider(repo).import_file(f, std)
            st = repo.get_station("BA4XXX")
            self.assertEqual(st["checkin_count"], 2)
            self.assertEqual(st["last_qth"], "扬州", "last_qth 按时间取最新")
            self.assertEqual(repo.get_station("BG4TKI")["checkin_count"], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
