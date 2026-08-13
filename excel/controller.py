"""Excel COM 控制器：优先操作用户当前打开的 Excel，全程容错，SQLite 数据永不因 Excel 失败丢失。

流程（规格第 47 节）：
寻找 Excel → 找 Workbook → 找 Worksheet → 识别表头 → 找下一空行 → 写入 → 保存。
"""
from __future__ import annotations

import logging
import time

from excel import template

logger = logging.getLogger("ham.excel")

try:  # pywin32 仅 Windows
    import win32com.client  # noqa: F401
    import pywintypes  # noqa: F401

    COM_AVAILABLE = True
except Exception:  # pragma: no cover - 非 Windows 环境
    COM_AVAILABLE = False


def _cell_value(cell) -> str:
    try:
        v = cell.Value
    except Exception:
        return ""
    if v is None:
        return ""
    return str(v).strip()


class ExcelController:
    """对单个目标工作表的写入控制。connect 成功后才能 write。"""

    def __init__(self) -> None:
        self.app = None
        self.workbook = None
        self.sheet = None
        self.header_row: int | None = None  # 1-based
        self.mapping: dict[str, int] = {}   # field -> col (1-based)
        self.next_row: int | None = None
        self.excel_path = ""
        self.last_error = ""

    # ---------- 连接 ----------
    def connect(self, excel_path: str = "", sheet_name: str = "",
                auto_detect_sheet: bool = True) -> tuple[bool, str]:
        self.last_error = ""
        if not COM_AVAILABLE:
            return False, "当前环境无 pywin32，无法操作 Excel COM"
        try:
            import win32com.client
            app = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            return False, "未找到已打开的 Excel，请先打开工作簿"
        try:
            workbook = self._find_workbook(app, excel_path)
            if workbook is None:
                return False, "未找到匹配的工作簿（含指定路径或活动工作簿）"
            sheet = self._find_sheet(workbook, sheet_name, auto_detect_sheet)
            if sheet is None:
                return False, "未找到可用工作表（未识别到表头）"
            self.app, self.workbook, self.sheet = app, workbook, sheet
            self.excel_path = excel_path or workbook.FullName or ""
            if not self.refresh_header():
                return False, f"无法识别表头：{self.last_error}"
            return True, "已连接"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel connect failed")
            return False, f"Excel 连接失败：{e}"

    def _find_workbook(self, app, excel_path: str):
        if excel_path:
            path = excel_path.lower()
            try:
                for wb in app.Workbooks:
                    try:
                        if (wb.FullName or "").lower() == path:
                            return wb
                    except Exception:
                        continue
            except Exception:
                pass
            return None
        try:
            wb = app.ActiveWorkbook
            if wb is not None:
                return wb
        except Exception:
            pass
        # 兜底：任意打开的工作簿
        try:
            for wb in app.Workbooks:
                return wb
        except Exception:
            return None
        return None

    def _find_sheet(self, workbook, sheet_name: str, auto_detect: bool):
        try:
            if sheet_name:
                try:
                    return workbook.Sheets(sheet_name)
                except Exception:
                    return None
            if not auto_detect:
                try:
                    return workbook.ActiveSheet
                except Exception:
                    pass
            # 在第一个有表头的 sheet 中找
            for s in workbook.Sheets:
                mapping = self._detect_mapping(s)
                if len(mapping) >= 2:
                    return s
            try:
                return workbook.ActiveSheet
            except Exception:
                return None
        except Exception:
            return None

    # ---------- 表头 ----------
    def _read_rows(self, sheet, count: int = 12) -> list[list[str]]:
        rows = []
        try:
            used = sheet.UsedRange
            max_r = min(used.Row + used.Rows.Count - 1, 12)
            for r in range(1, max_r + 1):
                row = []
                for c in range(1, 16):
                    try:
                        row.append(_cell_value(sheet.Cells(r, c)))
                    except Exception:
                        row.append("")
                rows.append(row)
        except Exception as e:
            self.last_error = str(e)
        return rows

    def _detect_mapping(self, sheet) -> dict[str, int]:
        rows = self._read_rows(sheet, 12)
        header_idx, mapping = template.find_header_row(rows)
        if header_idx is None:
            return {}
        self.header_row = header_idx + 1  # 1-based
        return {f: c + 1 for f, c in mapping.items()}

    def refresh_header(self) -> bool:
        """重新检测当前 sheet 的表头与列映射。"""
        try:
            mapping = self._detect_mapping(self.sheet)
            if not mapping:
                self.last_error = "未识别到表头"
                return False
            self.mapping = mapping
            self.next_row = self._find_next_empty()
            return True
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel refresh_header failed")
            return False

    def _find_next_empty(self) -> int:
        """表头之下第一个（已映射列）全空的行。"""
        start = (self.header_row or 1) + 1
        cols = sorted(set(self.mapping.values()))
        for r in range(start, start + 100000):
            empty = True
            for c in cols:
                try:
                    if _cell_value(self.sheet.Cells(r, c)):
                        empty = False
                        break
                except Exception:
                    empty = False
                    break
            if empty:
                return r
        return start

    # ---------- 写入 ----------
    def write(self, values: dict[str, str], auto_save: bool = True) -> tuple[bool, str, int | None]:
        """values: {field: value}，按映射写入 next_row。返回 (ok, msg, 写入行号)。"""
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel", None
        row = self.next_row or self._find_next_empty()
        try:
            for field, value in values.items():
                col = self.mapping.get(field)
                if col is None:
                    continue
                if value is None:
                    continue
                self.sheet.Cells(row, col).Value = value
            self.next_row = row + 1
            if auto_save:
                self.save()
            return True, f"已写入第 {row} 行", row
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel write failed")
            return False, f"Excel 写入失败：{e}", None

    def read_data(self) -> list[dict]:
        """读回当前 sheet 表头之下的数据行（用于 SQLite/Excel 一致性比对）。"""
        if not self.sheet or not self.mapping:
            return []
        start = (self.header_row or 1) + 1
        rows: list[dict] = []
        cols = self.mapping
        for r in range(start, start + 200000):
            row_vals: dict = {}
            empty = True
            for field, col in cols.items():
                v = _cell_value(self.sheet.Cells(r, col))
                if v:
                    empty = False
                row_vals[field] = v
            if empty:
                break
            rows.append(row_vals)
        return rows

    def update_row(self, row: int, values: dict[str, str], auto_save: bool = True) -> tuple[bool, str]:
        """就地更新某行（修改记录时用，只改已映射列）。"""
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel"
        try:
            for field, value in values.items():
                col = self.mapping.get(field)
                if col is None or value is None:
                    continue
                self.sheet.Cells(row, col).Value = value
            if auto_save:
                self.save()
            return True, f"已更新第 {row} 行"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel update_row failed")
            return False, f"Excel 更新失败：{e}"

    def save(self) -> tuple[bool, str]:
        try:
            self.workbook.Save()
            return True, ""
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel save failed")
            return False, f"Excel 保存失败：{e}"

    def rewrite_all(self, checkins, values_fn, auto_save: bool = True) -> tuple[bool, str]:
        """清空表头以下数据区，按 checkins 重写（用于撤销/重新同步本场）。"""
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel"
        start = (self.header_row or 1) + 1
        try:
            used = self.sheet.UsedRange
            last_row = used.Row + used.Rows.Count - 1
            if last_row >= start:
                max_col = max(self.mapping.values())
                rng = self.sheet.Range(self.sheet.Cells(start, 1),
                                       self.sheet.Cells(max(last_row, start), max_col))
                rng.ClearContents()
        except Exception as e:  # noqa: BLE001
            logger.exception("Excel rewrite clear failed")
            return False, f"Excel 清空失败：{e}"
        self.next_row = start
        try:
            for c in checkins:
                ok, msg, _ = self.write(values_fn(c), auto_save=False)
                if not ok:
                    return False, msg
            if auto_save:
                self.save()
            return True, f"已重写 {len(checkins)} 行"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel rewrite failed")
            return False, f"Excel 重写失败：{e}"

    def status_text(self) -> str:
        if not self.sheet:
            return "未连接"
        name = ""
        try:
            name = self.sheet.Name
        except Exception:
            pass
        return f"已连接：{name}"

    def close(self) -> None:
        """不关闭用户 Excel，仅释放引用。"""
        self.app = self.workbook = self.sheet = None


def wait_for_excel(retries: int = 5, delay: float = 1.0) -> bool:
    """等待用户打开 Excel（用于启动时的重试连接）。"""
    if not COM_AVAILABLE:
        return False
    import win32com.client
    for _ in range(retries):
        try:
            win32com.client.GetActiveObject("Excel.Application")
            return True
        except Exception:
            time.sleep(delay)
    return False
