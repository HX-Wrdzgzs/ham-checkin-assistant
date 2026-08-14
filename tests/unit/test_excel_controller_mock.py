"""ExcelController 控制器级 Mock COM 测试（任务书第一阶段 #5~#9）。

不依赖真实 Excel：使用 tests.helpers.mock_excel 的 Mock 工作簿。
"""
from __future__ import annotations

import unittest

from excel.controller import ExcelController
from tests.helpers.mock_excel import (
    MockApp,
    MockWorkbook,
    install_mock_app,
    make_sheet,
    make_workbook,
)


def connect_controller(controller: ExcelController, workbook: MockWorkbook,
                       sheet_name: str | None = None) -> tuple[bool, str]:
    install_mock_app(controller, MockApp([workbook], workbook))
    return controller.connect(str(workbook.FullName), sheet_name or "点名表")


class TestFindWorkbook(unittest.TestCase):
    def setUp(self):
        self.ctrl = ExcelController()

    def test_missing_bound_workbook_fails_closed(self):
        """指定 workbook 不存在 → fail-closed，不回退到 ActiveWorkbook/任意工作簿。"""
        wb_a = make_workbook("C:/tmp/A.xlsx")
        install_mock_app(self.ctrl, MockApp([wb_a], wb_a))
        ok, msg = self.ctrl.connect("C:/tmp/NOT_EXIST.xlsx", "点名表")
        self.assertFalse(ok)
        self.assertIn("未找到", msg)
        self.assertIsNone(self.ctrl.sheet, "不得回退到其它工作簿")

    def test_multiple_open_workbooks_never_choose_random_target(self):
        """多工作簿打开时：指定路径只精确匹配；未指定只用 ActiveWorkbook。"""
        wb_a = make_workbook("C:/tmp/A.xlsx")
        wb_b = make_workbook("C:/tmp/B.xlsx")
        install_mock_app(self.ctrl, MockApp([wb_a, wb_b], wb_a))
        # 指定 B → 必须连 B，不能随机
        ok, msg = connect_controller(self.ctrl, wb_b)
        self.assertTrue(ok)
        self.assertEqual(self.ctrl.workbook.FullName, "C:/tmp/B.xlsx")
        # 未指定 → 只用 ActiveWorkbook（A）
        c2 = ExcelController()
        install_mock_app(c2, MockApp([wb_a, wb_b], wb_a))
        ok2, _ = c2.connect("", "点名表")
        self.assertTrue(ok2)
        self.assertEqual(c2.workbook.FullName, "C:/tmp/A.xlsx")

    def test_schema_requires_core_columns(self):
        """只识别 2 个表头 → 必须失败（任务书第一阶段 #13）。"""
        from tests.helpers.mock_excel import MockSheet

        sheet = MockSheet("残缺", [["序号", "呼号"], [1, "BG4TKI"]])
        wb = make_workbook("C:/tmp/schema.xlsx", sheet=sheet)
        ok, msg = connect_controller(self.ctrl, wb, sheet_name="残缺")
        self.assertFalse(ok)
        self.assertIn("缺少必要列", msg)


class TestAppendRow(unittest.TestCase):
    """下一行算法：按最后一条有效数据记录追加（任务书第一阶段 #6）。"""

    def _ctrl(self, rows):
        c = ExcelController()
        sheet = make_sheet("点名表", rows)
        wb = make_workbook("C:/tmp/append.xlsx", sheet=sheet)
        ok, msg = connect_controller(c, wb)
        self.assertTrue(ok, msg)
        return c

    def test_append_after_last_real_record(self):
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "K6", "771", "5W", "59"],
                        [2, "2010", "BG4TKI", "扬州", "K6", "771", "5W", "59"]])
        ok, msg, row = c.write({"sequence": 3, "time": "2020", "callsign": "BD4ABC",
                                "qth": "徐州", "device": "", "antenna": "",
                                "power": "", "signal": ""}, auto_save=False)
        self.assertTrue(ok, msg)
        self.assertEqual(row, 4, "应追加在最后一条有效记录之后")

    def test_append_after_internal_blank_row(self):
        """header / data / data / blank / data → 新数据追加在最后一条 data 之后（第 6 行）。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""],
                        [2, "2010", "BG4TKI", "扬州", "", "", "", ""],
                        [],
                        [3, "2020", "BD4ABC", "徐州", "", "", "", ""]])
        ok, msg, row = c.write({"sequence": 4, "time": "2030", "callsign": "BH4DEF",
                                "qth": "苏州", "device": "", "antenna": "",
                                "power": "", "signal": ""}, auto_save=False)
        self.assertTrue(ok, msg)
        self.assertEqual(row, 6, "不得写入内部空行（第 4 行），必须追加到最后数据之后")

    def test_never_overwrite_existing_row_after_blank(self):
        """内部空行后的已有数据绝不能因追加而覆盖。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""],
                        [],
                        [2, "2010", "BG4TKI", "扬州", "", "", "", ""]])
        ok, msg, row = c.write({"sequence": 3, "time": "2020", "callsign": "BD4ABC",
                                "qth": "徐州", "device": "", "antenna": "",
                                "power": "", "signal": ""}, auto_save=False)
        self.assertTrue(ok, msg)
        self.assertEqual(row, 5, "必须追加到第 4 行（BG4TKI）之后")
        # 读回确认第 4 行数据没被覆盖
        data = c.read_data()
        self.assertEqual(data[0]["callsign"], "BA4XXX")
        self.assertEqual(data[2]["_row"], 4)
        self.assertEqual(data[2]["callsign"], "BG4TKI")
        self.assertEqual(data[3]["_row"], 5)
        self.assertEqual(data[3]["callsign"], "BD4ABC")

    def test_empty_sheet_starts_after_header(self):
        c = self._ctrl([])
        ok, msg, row = c.write({"sequence": 1, "time": "2000", "callsign": "BA4XXX",
                                "qth": "南京", "device": "", "antenna": "",
                                "power": "", "signal": ""}, auto_save=False)
        self.assertTrue(ok, msg)
        self.assertEqual(row, 2, "空表应从表头下一行开始")


class TestRewriteScoped(unittest.TestCase):
    """rewrite_all 只清理受管列（任务书第一阶段 #7）。"""

    def _setup(self):
        # A sequence, B 用户备注, C 呼号, D 自定义公式, E QTH, F 时间
        from tests.helpers.mock_excel import MockSheet

        return MockSheet(
            "点名表",
            [["序号", "用户备注", "呼号", "自定义公式", "QTH", "时间"],
             [1, "用户备注X", "BA4XXX", "=SUM(1,2)", "南京", "2000"],
             [2, "用户备注Y", "BG4TKI", "=SUM(3,4)", "扬州", "2010"]])

    def _checkins(self):
        from database.models import Checkin
        return [
            Checkin(sequence_no=1, callsign="BA4XXX", checkin_time="2026-08-08T20:00:00",
                    qth_standard="南京", device_standard="", antenna_standard="",
                    power_standard="", signal=""),
            Checkin(sequence_no=2, callsign="BG4TKI", checkin_time="2026-08-08T20:10:00",
                    qth_standard="扬州", device_standard="", antenna_standard="",
                    power_standard="", signal=""),
        ]

    def test_rewrite_preserves_unmanaged_and_formula_columns(self):
        c = ExcelController()
        sheet = self._setup()
        wb = make_workbook("C:/tmp/rewrite.xlsx", sheet=sheet)
        ok, msg = connect_controller(c, wb)
        self.assertTrue(ok, msg)
        ok2, msg2 = c.rewrite_all(self._checkins(), _vals, auto_save=False)
        self.assertTrue(ok2, msg2)
        # 受管列已重写
        self.assertEqual(sheet._data.get((2, 1)), 1)
        self.assertEqual(sheet._data.get((2, 3)), "BA4XXX")
        self.assertEqual(sheet._data.get((3, 1)), 2)
        self.assertEqual(sheet._data.get((3, 3)), "BG4TKI")
        # B（用户备注）与 D（自定义公式）完全不变
        self.assertEqual(sheet._data.get((2, 2)), "用户备注X")
        self.assertEqual(sheet._data.get((3, 2)), "用户备注Y")
        self.assertEqual(sheet._data.get((2, 4)), "=SUM(1,2)")
        self.assertEqual(sheet._data.get((3, 4)), "=SUM(3,4)")

    def test_rewrite_only_clears_managed_cells(self):
        """rewrite 后受管列清空，非受管列保留。"""
        c = ExcelController()
        sheet = self._setup()
        # 在表头下有 3 行数据，其中第 3 行只有用户备注（非受管）
        sheet.set_cell(4, 1, 999)
        sheet.set_cell(4, 2, "孤岛备注")
        wb = make_workbook("C:/tmp/rewrite2.xlsx", sheet=sheet)
        ok, msg = connect_controller(c, wb)
        self.assertTrue(ok, msg)
        ok2, msg2 = c.rewrite_all(self._checkins(), _vals, auto_save=False)
        self.assertTrue(ok2, msg2)
        self.assertNotIn((4, 1), sheet._data, "受管列 999 应被清掉")
        self.assertEqual(sheet._data.get((4, 2)), "孤岛备注", "用户备注列必须保留")


def _vals(c):
    return {
        "sequence": c.sequence_no, "time": "20:00", "callsign": c.callsign,
        "qth": c.qth_standard, "device": c.device_standard, "antenna": c.antenna_standard,
        "power": c.power_standard, "signal": c.signal,
    }


class TestRowIdentity(unittest.TestCase):
    """Excel 行身份：更新前必须验证 sequence+callsign（任务书第一阶段 #8/#9）。"""

    def _ctrl(self, rows):
        c = ExcelController()
        sheet = make_sheet("点名表", rows)
        wb = make_workbook("C:/tmp/ident.xlsx", sheet=sheet)
        ok, msg = connect_controller(c, wb)
        self.assertTrue(ok, msg)
        return c

    def test_excel_row_insert_does_not_modify_wrong_record(self):
        """行号失效（被插入/删除导致漂移）时，verify 必须失败，find 必须找到唯一目标。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""],
                        [2, "2010", "BG4TKI", "扬州", "", "", "", ""]])
        # 模拟在第 2 行前插入一行，原 BG4TKI 从第 3 行变到第 4 行？这里模拟行漂移：
        # 直接把第 3 行内容变成 BG4TKI（原第 2 行被改成别的）→ excel_row=2 身份失效
        c.sheet.set_cell(2, 1, 999)
        c.sheet.set_cell(2, 3, "XXXXXXXX")
        self.assertFalse(c.verify_row_identity(2, 2, "BG4TKI"))
        found = c.find_row(2, "BG4TKI")
        self.assertEqual(found, 3, "应搜索到唯一匹配行")
        ok, msg = c.update_row(found, {"qth": "徐州"}, auto_save=False)
        self.assertTrue(ok, msg)
        self.assertEqual(c.sheet._data.get((3, 4)), "徐州")

    def test_excel_sort_does_not_modify_wrong_record(self):
        """排序后行号全乱，update 必须先校验身份，绝不按旧行号写错记录。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""],
                        [2, "2010", "BG4TKI", "扬州", "", "", "", ""]])
        # 完整交换两行内容模拟排序（含所有字段）
        def swap_row(r1, r2):
            for col in range(1, 9):
                v1 = c.sheet._data.get((r1, col))
                v2 = c.sheet._data.get((r2, col))
                if v1 is not None:
                    c.sheet.set_cell(r2, col, v1)
                if v2 is not None:
                    c.sheet.set_cell(r1, col, v2)
        swap_row(2, 3)
        # 现在 row2=BG4TKI(#2)、row3=BA4XXX(#1)。对 BA4XXX(#1) 的旧行号 2 身份失效。
        self.assertFalse(c.verify_row_identity(2, 1, "BA4XXX"))
        found = c.find_row(1, "BA4XXX")
        self.assertEqual(found, 3)
        ok, msg = c.update_row(found, {"qth": "徐州"}, auto_save=False)
        self.assertTrue(ok, msg)
        # 不能改错 BG4TKI 的行（row2 的 qth 仍是扬州）
        self.assertEqual(c.sheet._data.get((2, 4)), "扬州")
        self.assertEqual(c.sheet._data.get((3, 4)), "徐州")

    def test_excel_deleted_row_detected_as_conflict(self):
        """目标行被删除 → find 无唯一匹配 → 不写，返回 None。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""],
                        [2, "2010", "BG4TKI", "扬州", "", "", "", ""]])
        # BG4TKI 在第 3 行；删除其 sequence+callsign（模拟整行删除）
        c.sheet.set_cell(3, 1, None)
        c.sheet.set_cell(3, 3, None)
        self.assertFalse(c.verify_row_identity(3, 2, "BG4TKI"))
        self.assertIsNone(c.find_row(2, "BG4TKI"))

    def test_excel_identity_mismatch_fails_closed(self):
        """身份不匹配时 update_row 仍可被调用，但调用方必须先用 verify/find 决策。"""
        c = self._ctrl([[1, "2000", "BA4XXX", "南京", "", "", "", ""]])
        # 目标行不是该记录 → 调用方应拒写（这里直接验证 verify 返回 False）
        self.assertFalse(c.verify_row_identity(2, 99, "NOPE"))
        self.assertIsNone(c.find_row(99, "NOPE"))


if __name__ == "__main__":
    unittest.main()
