"""回归测试：P0-3 —— 历史 Excel 跨日期不得误去重。

- 先确定有效日期/时间 → 规范化 canonical datetime → 再生成指纹。
- 指纹含 canonical datetime；不同日期（文件名/日期列）的同名记录不误判重复。
- 完全相同的同一事件跨文件仍是重复。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from database.db import connect
from database.repository import Repository
from database.seed import seed_default_aliases
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from providers.excel_import import ExcelImportProvider
from services.standardizer import Standardizer

HEADERS = ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率"]
HEADERS_DATE = ["序号", "日期", "时间", "呼号", "QTH", "设备", "天线", "功率"]


def _env():
    tmp = Path(tempfile.mkdtemp(prefix="ham_xdate_"))
    conn = connect(tmp / "imp.db")
    repo = Repository(conn)
    seed_default_aliases(repo)
    std = Standardizer(AliasStore(repo), RegionIndex("江苏"))
    return tmp, conn, repo, std


def make_xlsx(path: Path, rows: list[list], headers=None):
    wb = Workbook()
    ws = wb.active
    ws.append(headers or HEADERS)
    for r in rows:
        ws.append(r)
    wb.save(path)
    wb.close()


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]


class TestImportCrossDate(unittest.TestCase):
    def test_same_station_same_time_different_date_not_duplicate(self):
        """文件名日期不同 → 同一时间/呼号的记录不误判重复。"""
        tmp, conn, repo, std = _env()
        try:
            a = tmp / "2026-08-08.xlsx"
            b = tmp / "2026-08-15.xlsx"
            rec = [1, "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"]
            make_xlsx(a, [rec])
            make_xlsx(b, [rec])
            prov = ExcelImportProvider(repo)
            prov.import_file(a, std)
            imp, skip, _ = prov.import_file(b, std)
            self.assertEqual(imp, 1, "不同日期的同一记录必须导入")
            self.assertEqual(skip, 0)
            self.assertEqual(_count(conn), 2)
            dates = [r["checkin_time"][:10] for r in conn.execute(
                "SELECT checkin_time FROM checkins ORDER BY id")]
            self.assertNotEqual(dates[0], dates[1], "两条记录的日期必须不同")
        finally:
            conn.close()

    def test_filename_date_participates_in_hash(self):
        """文件名中的日期必须进入指纹（无日期列时）。"""
        tmp, conn, repo, std = _env()
        try:
            a = tmp / "2026-08-08.xlsx"
            b = tmp / "2026-08-15.xlsx"
            rec = [1, "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"]
            make_xlsx(a, [rec])
            make_xlsx(b, [rec])
            prov = ExcelImportProvider(repo)
            prov.import_file(a, std)
            prov.import_file(b, std)
            hashes = {r["source_record_id"] for r in conn.execute(
                "SELECT source_record_id FROM checkins WHERE source_record_id!=''")}
            self.assertEqual(len(hashes), 2, "两个文件的指纹必须不同（日期参与 hash）")
        finally:
            conn.close()

    def test_sheet_date_participates_in_hash(self):
        """表内日期列参与指纹：同一文件内不同日期的记录都导入。"""
        tmp, conn, repo, std = _env()
        try:
            f = tmp / "sheet_date.xlsx"
            make_xlsx(f, [
                [1, "2026-08-08", "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"],
                [2, "2026-08-15", "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"],
            ], headers=HEADERS_DATE)
            prov = ExcelImportProvider(repo)
            imp, skip, _ = prov.import_file(f, std)
            self.assertEqual(imp, 2, "表内不同日期的两条记录都必须导入")
            self.assertEqual(skip, 0)
            self.assertEqual(_count(conn), 2)
        finally:
            conn.close()

    def test_exact_same_event_across_files_is_duplicate(self):
        """日期+内容完全相同 → 跨文件仍是重复（去重）。"""
        tmp, conn, repo, std = _env()
        try:
            a = tmp / "2026-08-08_A.xlsx"
            b = tmp / "2026-08-08_B.xlsx"
            rec = [1, "2000", "BA4XXX", "南京栖霞", "K6", "771", "5W"]
            make_xlsx(a, [rec])
            make_xlsx(b, [rec])
            prov = ExcelImportProvider(repo)
            prov.import_file(a, std)
            imp, skip, _ = prov.import_file(b, std)
            self.assertEqual(imp, 0)
            self.assertEqual(skip, 1, "完全相同的同一事件必须去重")
            self.assertEqual(_count(conn), 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
