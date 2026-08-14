"""Mock Excel COM：不需要安装 Excel 即可测试 ExcelController 全部行为。

支持：
- Cells(r,c).Value 读写
- Range(cell1, cell2).ClearContents()
- UsedRange（Row / Rows.Count 自动按数据计算）
- workbook.Sheets(name) 取表 / 迭代
- workbook.Save()（可注入失败）
- app.Workbooks 迭代 / app.ActiveWorkbook
- 故障注入：save_fail、disconnected（访问抛异常）
"""
from __future__ import annotations


class MockError(RuntimeError):
    """模拟 COM 断开/异常。"""


class MockCellView:
    def __init__(self, sheet, row, col):
        self._sheet = sheet
        self.row = row
        self.col = col

    def _check(self):
        if self._sheet.disconnected:
            raise MockError("COM disconnected")

    @property
    def Value(self):
        self._check()
        return self._sheet._data.get((self.row, self.col))

    @Value.setter
    def Value(self, v):
        self._check()
        self._sheet._data[(self.row, self.col)] = v


class MockRange:
    def __init__(self, sheet, cell1, cell2):
        self._sheet = sheet
        self._top = min(cell1.row, cell2.row)
        self._bottom = max(cell1.row, cell2.row)
        self._left = min(cell1.col, cell2.col)
        self._right = max(cell1.col, cell2.col)

    def ClearContents(self):
        for (r, c) in list(self._sheet._data.keys()):
            if self._top <= r <= self._bottom and self._left <= c <= self._right:
                del self._sheet._data[(r, c)]


class MockSheet:
    def __init__(self, name: str, rows: list[list] | None = None):
        self.Name = name
        self._data: dict[tuple[int, int], object] = {}
        self.disconnected = False
        self._loaded_rows = 0
        if rows:
            for r, row in enumerate(rows, start=1):
                for c, v in enumerate(row, start=1):
                    if v is not None and v != "":
                        self._data[(r, c)] = v
            self._loaded_rows = len(rows)

    # 兼容既有测试的便捷方法
    def set_cell(self, r: int, c: int, v) -> None:
        self._data[(r, c)] = v

    def cell(self, r: int, c: int) -> MockCellView:
        return MockCellView(self, r, c)

    def Cells(self, r: int, c: int) -> MockCellView:
        return MockCellView(self, r, c)

    def Range(self, cell1, cell2) -> MockRange:
        return MockRange(self, cell1, cell2)

    @property
    def UsedRange(self):
        if not self._data:
            return _UsedRange(1, 1)
        max_r = max(r for (r, _c) in self._data)
        max_c = max(c for (_r, c) in self._data)
        return _UsedRange(1, max(max_r, 1), cols=max_c)

    def rows_dict(self) -> list[dict]:
        """调试用：返回 {(r, c): value} 的按行分组。"""
        out: dict[int, dict] = {}
        for (r, c), v in self._data.items():
            out.setdefault(r, {})[c] = v
        return out


class _UsedRange:
    def __init__(self, row: int, count: int, cols: int = 1):
        self.Row = row
        self.Rows = _Dim(count)
        self.Columns = _Dim(cols)


class _Dim:
    def __init__(self, count: int):
        self.Count = count


class MockSheets:
    def __init__(self, sheets: list[MockSheet]):
        self._sheets = sheets
        self._index = 0

    def __call__(self, name: str) -> MockSheet | None:
        for s in self._sheets:
            if s.Name == name:
                return s
        raise KeyError(name)

    def __getitem__(self, name: str) -> MockSheet:
        return self.__call__(name)

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self):
        if self._index >= len(self._sheets):
            raise StopIteration
        s = self._sheets[self._index]
        self._index += 1
        return s


class MockWorkbook:
    def __init__(self, full_name: str, sheets: list[MockSheet], active_sheet: MockSheet | None = None):
        self.FullName = full_name
        self.Sheets = MockSheets(sheets)
        self.ActiveSheet = active_sheet or sheets[0]
        self.save_fail = False
        self.save_count = 0
        self.save_exc: Exception | None = None

    def Save(self):
        self.save_count += 1
        if self.save_fail:
            if self.save_exc is not None:
                raise self.save_exc
            raise MockError("Save failed (read-only / disk full)")


class MockApp:
    def __init__(self, workbooks: list[MockWorkbook], active: MockWorkbook | None = None):
        self.Workbooks = workbooks
        self.ActiveWorkbook = active or (workbooks[0] if workbooks else None)


# ---------- 便捷构造 ----------
HEADERS = ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率", "信号"]


def make_sheet(name: str = "点名表", data_rows: list[list] | None = None) -> MockSheet:
    rows = [HEADERS]
    if data_rows:
        rows += data_rows
    return MockSheet(name, rows)


def make_workbook(full_name: str, sheet: MockSheet | None = None,
                  sheet_name: str = "点名表", data_rows: list[list] | None = None) -> MockWorkbook:
    s = sheet or make_sheet(sheet_name, data_rows)
    return MockWorkbook(full_name, [s], s)


def install_mock_app(controller, app: MockApp) -> None:
    """把 controller._get_excel_app 指向 mock app（无真实 Excel 的测试用）。"""
    controller._get_excel_app = lambda: app

