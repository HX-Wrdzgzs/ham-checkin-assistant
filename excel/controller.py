"""Excel COM 控制器：对单个目标工作表的写入控制。

数据安全原则（任务书第一阶段 #5~#9）：
- Excel 绑定是「Session 级」的：指定 workbook 后不得偷偷写其它 workbook。
- 指定 workbook 不存在时 fail-closed，绝不回退到 ActiveWorkbook/任意工作簿。
- 下一行算法基于「最后一条有效数据记录」，禁止找第一条全空行。
- rewrite_all 只清理受程序管理的列，保留用户列/公式列/备注列。
- 写 Excel 前按文本处理，防公式注入（=、+、-、@ 前缀加单引号）。

SQLite 数据永不因 Excel 失败丢失：本模块只负责 COM 操作，状态由 Service 管理。
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

# 连接时必须存在的列（任务书第一阶段 #13：禁止只识别 2 个表头就认为可安全写）
REQUIRED_FIELDS = ("sequence", "time", "callsign", "qth")
OPTIONAL_FIELDS = ("device", "antenna", "power", "signal", "unmatched")


def _cell_value(cell) -> str:
    try:
        v = cell.Value
    except Exception:
        return ""
    if v is None:
        return ""
    return str(v).strip()


def _clean(value) -> str:
    """批量 Range 单元格值清理（P2）。"""
    if value is None:
        return ""
    return str(value).strip()


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
        self.binding_id = ""  # workbook 指纹（FullName）

    # ---------- 连接 ----------
    def _get_excel_app(self):
        """获取 Excel Application（独立方法便于测试注入 Mock）。"""
        if not COM_AVAILABLE:
            raise RuntimeError("当前环境无 pywin32，无法操作 Excel COM")
        import win32com.client

        return win32com.client.GetActiveObject("Excel.Application")

    def connect(self, excel_path: str = "", sheet_name: str = "",
                auto_detect_sheet: bool = True) -> tuple[bool, str]:
        self.last_error = ""
        try:
            app = self._get_excel_app()
        except Exception as e:  # noqa: BLE001
            return False, f"未找到已打开的 Excel，请先打开工作簿（{e}）"
        try:
            workbook = self._find_workbook(app, excel_path)
            if workbook is None:
                return False, "未找到匹配的工作簿（fail-closed，不自动回退）"
            sheet = self._find_sheet(workbook, sheet_name, auto_detect_sheet)
            if sheet is None:
                return False, "未找到可用工作表"
            self.app, self.workbook, self.sheet = app, workbook, sheet
            try:
                self.excel_path = excel_path or str(workbook.FullName or "")
                self.binding_id = str(workbook.FullName or "")
            except Exception:
                self.excel_path = excel_path
                self.binding_id = excel_path
            if not self.refresh_header():
                return False, f"无法识别表头：{self.last_error}"
            return True, "已连接"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel connect failed")
            return False, f"Excel 连接失败：{e}"

    def _find_workbook(self, app, excel_path: str):
        """指定路径只精确匹配；未指定时只用 ActiveWorkbook。绝不随机挑一个。"""
        try:
            if excel_path:
                path = excel_path.lower()
                for wb in app.Workbooks:
                    try:
                        if (str(wb.FullName or "")).lower() == path:
                            return wb
                    except Exception:
                        continue
                return None  # 指定了却没找到 → fail-closed
            try:
                wb = app.ActiveWorkbook
                return wb if wb is not None else None
            except Exception:
                return None
        except Exception:
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

    # ---------- 表头 / 列映射 ----------
    def _read_rows(self, sheet, count: int = 12) -> list[list[str]]:
        """批量 Range 读取（P2：COM 单次调用取整个区域，避免逐格跨进程）。

        返回 [[str,...], ...]，行数 = min(UsedRange 行数, count)，列数固定 15。
        """
        rows = []
        try:
            used = sheet.UsedRange
            max_r = min(used.Row + used.Rows.Count - 1, count)
            if max_r < 1:
                return rows
            # 批量取 A1:O{max_r} 的二维数组（一次 COM 调用）
            try:
                block = sheet.Range(sheet.Cells(1, 1), sheet.Cells(max_r, 15)).Value
            except Exception:
                block = None
            if isinstance(block, (tuple, list)) and block and isinstance(block[0], (tuple, list)):
                for r in range(len(block)):
                    row = [_clean(v) for v in block[r]]
                    if len(row) < 15:
                        row += [""] * (15 - len(row))
                    rows.append(row[:15])
                return rows
            # 单行（1×15 或退化情况）或批量失败 → 逐格兜底
            for r in range(1, max_r + 1):
                row = []
                for c in range(1, 16):
                    try:
                        row.append(_cell_value(sheet.Cells(r, c)))
                    except Exception:
                        row.append("")
                rows.append(row)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
        return rows

    def _detect_mapping(self, sheet) -> dict[str, int]:
        rows = self._read_rows(sheet, 12)
        header_idx, mapping = template.find_header_row(rows)
        if header_idx is None:
            return {}
        self.header_row = header_idx + 1  # 1-based
        return {f: c + 1 for f, c in mapping.items()}

    def _validate_schema(self, mapping: dict) -> tuple[bool, str]:
        """任务书第一阶段 #13：连接时校验必要列。缺失关键列 → 失败。"""
        missing_required = [f for f in REQUIRED_FIELDS if f not in mapping]
        if missing_required:
            return False, f"缺少必要列：{'、'.join(missing_required)}"
        return True, ""

    def refresh_header(self) -> bool:
        """重新检测当前 sheet 的表头与列映射，并校验 schema。"""
        try:
            mapping = self._detect_mapping(self.sheet)
            if not mapping:
                self.last_error = "未识别到表头"
                return False
            ok, msg = self._validate_schema(mapping)
            if not ok:
                self.last_error = msg
                return False
            self.mapping = mapping
            # “未识别”是数据保全列，不应等到第一条异常输入时才临时创建。
            # 连接阶段就把旧模板补成可承载原文的结构；若前 15 列都被人工使用，
            # 保持连接成功但让具体写入返回明确错误，绝不覆盖人工列。
            if "unmatched" not in self.mapping:
                ensured, ensure_msg = self._ensure_unmatched_column()
                if not ensured:
                    logger.warning("Excel has no safe unmatched column: %s", ensure_msg)
            self.next_row = self._find_append_row()
            return True
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel refresh_header failed")
            return False

    def _find_append_row(self) -> int:
        """表头下「最后一条有效数据记录」之后的行（任务书第一阶段 #6）。

        header / data / data / blank / data / data → 新数据只能追加在最后一条之后。
        """
        start = (self.header_row or 1) + 1
        primary = self.mapping.get("sequence") or self.mapping.get("callsign")
        last = start - 1
        try:
            used = self.sheet.UsedRange
            bottom = used.Row + used.Rows.Count - 1
        except Exception:
            bottom = start + 100000
        for r in range(start, bottom + 1):
            if primary:
                if _cell_value(self.sheet.Cells(r, primary)):
                    last = r
            else:
                if any(_cell_value(self.sheet.Cells(r, c)) for c in self.mapping.values()):
                    last = r
        return last + 1

    def reset_next_row(self) -> None:
        """重新计算追加行（补同步/重排后使用，避免内部空行导致重复写）。"""
        if self.sheet is not None and self.mapping:
            self.next_row = self._find_append_row()

    # ---------- 写入 ----------
    def _set_cell(self, row: int, col: int, value) -> None:
        # 公式注入防护（P1-12：与 openpyxl 共用 excel_safe_text）
        self.sheet.Cells(row, col).Value = template.excel_safe_text(value)

    def _ensure_unmatched_column(self) -> tuple[bool, str]:
        """旧模板没有“未识别”列时，在首个空表头列补上显式列名。

        只使用当前表头区域内的空列，不覆盖已有的备注、公式或其它人工列；
        如果前 15 列都已有内容则 fail-closed，让调用方保留 Excel 错误状态。
        """
        if "unmatched" in self.mapping:
            return True, ""
        if self.sheet is None or self.header_row is None:
            return False, "尚未定位 Excel 表头，无法创建“未识别”列"
        start = max(self.mapping.values(), default=0) + 1
        try:
            for col in range(start, 16):
                if _cell_value(self.sheet.Cells(self.header_row, col)):
                    continue
                self._set_cell(self.header_row, col, "未识别")
                self.mapping["unmatched"] = col
                return True, ""
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return False, f"无法创建“未识别”列表头：{e}"
        return False, "Excel 前 15 列没有可用空列表头，未覆盖现有列"

    def write(self, values: dict[str, str], auto_save: bool = True) -> tuple[bool, str, int | None]:
        """values: {field: value}，按映射写入追加行。返回 (ok, msg, 写入行号)。

        auto_save=True 时若 Save 失败，返回 ok=False（写入了内存但未持久化）。
        """
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel", None
        try:
            if str(values.get("unmatched") or "").strip() and "unmatched" not in self.mapping:
                ok, msg = self._ensure_unmatched_column()
                if not ok:
                    return False, msg, None
            row = self.next_row or self._find_append_row()
            for field, value in values.items():
                col = self.mapping.get(field)
                if col is None or value is None:
                    continue
                self._set_cell(row, col, value)
            self.next_row = row + 1
            if auto_save:
                ok, msg = self.save()
                if not ok:
                    return False, msg, row
            return True, f"已写入第 {row} 行", row
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel write failed")
            return False, f"Excel 写入失败：{e}", None

    def read_data(self) -> list[dict]:
        """读回当前 sheet 表头之下的所有数据行（含内部空行，带 _row 行号）。

        用于 SQLite/Excel 一致性比对；内部空行不再截断扫描。
        """
        if not self.sheet or not self.mapping:
            return []
        start = (self.header_row or 1) + 1
        rows: list[dict] = []
        try:
            used = self.sheet.UsedRange
            bottom = used.Row + used.Rows.Count - 1
        except Exception:
            bottom = start + 200000
        for r in range(start, bottom + 1):
            row_vals: dict = {"_row": r}
            for field, col in self.mapping.items():
                row_vals[field] = _cell_value(self.sheet.Cells(r, col))
            rows.append(row_vals)
        return rows

    def update_row(self, row: int, values: dict[str, str],
                   auto_save: bool = True) -> tuple[bool, str]:
        """就地更新某行（只改已映射列）。调用方必须先做行身份校验（任务书第一阶段 #8）。"""
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel"
        try:
            for field, value in values.items():
                col = self.mapping.get(field)
                if col is None or value is None:
                    continue
                self._set_cell(row, col, value)
            if auto_save:
                ok, msg = self.save()
                if not ok:
                    return False, msg
            return True, f"已更新第 {row} 行"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel update_row failed")
            return False, f"Excel 更新失败：{e}"

    # ---------- 行身份（任务书第一阶段 #8/#9） ----------
    def verify_row_identity(self, row: int, sequence, callsign: str) -> bool:
        """校验某行 sequence+callsign 是否与数据库记录一致。"""
        if not self.sheet or not self.mapping:
            return False
        seq_col = self.mapping.get("sequence")
        cs_col = self.mapping.get("callsign")
        if seq_col is None or cs_col is None:
            return False
        try:
            r_seq = _cell_value(self.sheet.Cells(row, seq_col))
            r_cs = _cell_value(self.sheet.Cells(row, cs_col))
        except Exception:
            return False
        return (str(r_seq).strip() == str(sequence).strip()
                and str(r_cs).strip().upper() == str(callsign).strip().upper())

    def find_row(self, sequence, callsign: str) -> int | None:
        """按 sequence+callsign 搜索唯一匹配行；无/多条返回 None（不写）。"""
        if not self.sheet or not self.mapping:
            return None
        start = (self.header_row or 1) + 1
        seq_col = self.mapping.get("sequence")
        cs_col = self.mapping.get("callsign")
        if seq_col is None or cs_col is None:
            return None
        try:
            used = self.sheet.UsedRange
            bottom = used.Row + used.Rows.Count - 1
        except Exception:
            bottom = start + 200000
        matches: list[int] = []
        target_seq = str(sequence).strip()
        target_cs = str(callsign).strip().upper()
        for r in range(start, bottom + 1):
            try:
                r_seq = _cell_value(self.sheet.Cells(r, seq_col))
                r_cs = _cell_value(self.sheet.Cells(r, cs_col))
            except Exception:
                continue
            if (r_seq.strip() == target_seq
                    and r_cs.strip().upper() == target_cs):
                matches.append(r)
        return matches[0] if len(matches) == 1 else None

    def save(self) -> tuple[bool, str]:
        try:
            self.workbook.Save()
            return True, ""
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel save failed")
            return False, f"Excel 保存失败：{e}"

    def snapshot_managed_rows(self) -> dict | None:
        """快照受管数据列，供整场重写失败时恢复内存内容。

        ``rewrite_all`` 会先清空受管列再重写；如果 Excel.Save 因只读、磁盘
        或 COM 故障失败，不能把“已清空但未落盘”的状态留在用户工作簿内存中。
        这里只读取程序管理的列，不触碰备注/公式等人工列。
        """
        if not self.sheet or not self.mapping:
            return None
        start = (self.header_row or 1) + 1
        try:
            used = self.sheet.UsedRange
            bottom = max(start - 1, used.Row + used.Rows.Count - 1)
        except Exception:
            bottom = start - 1
        values: dict[tuple[int, int], object] = {}
        for row in range(start, bottom + 1):
            for col in sorted(set(self.mapping.values())):
                try:
                    value = self.sheet.Cells(row, col).Value
                except Exception:
                    value = None
                if value is not None and value != "":
                    values[(row, col)] = value
        return {"start": start, "bottom": bottom, "values": values,
                "next_row": self.next_row}

    def restore_managed_rows(self, snapshot: dict | None) -> bool:
        """恢复 ``snapshot_managed_rows`` 的数据列；人工列保持不变。"""
        if not snapshot or not self.sheet or not self.mapping:
            return False
        start = int(snapshot.get("start") or ((self.header_row or 1) + 1))
        try:
            used = self.sheet.UsedRange
            current_bottom = used.Row + used.Rows.Count - 1
        except Exception:
            current_bottom = start - 1
        bottom = max(current_bottom, int(snapshot.get("bottom") or start - 1))
        try:
            if bottom >= start:
                for col in sorted(set(self.mapping.values())):
                    self.sheet.Range(
                        self.sheet.Cells(start, col),
                        self.sheet.Cells(bottom, col),
                    ).ClearContents()
            for (row, col), value in (snapshot.get("values") or {}).items():
                self.sheet.Cells(int(row), int(col)).Value = value
            self.next_row = snapshot.get("next_row")
            return True
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel managed row restore failed")
            return False

    def rewrite_all(self, checkins, values_fn, auto_save: bool = True) -> tuple[bool, str]:
        """只清理受管列并重写（任务书第一阶段 #7：保留用户列/公式列/备注列）。"""
        if not self.sheet or not self.mapping:
            return False, "尚未连接 Excel"
        start = (self.header_row or 1) + 1
        try:
            used = self.sheet.UsedRange
            last_row = used.Row + used.Rows.Count - 1
            if last_row >= start:
                for col in sorted(set(self.mapping.values())):
                    self.sheet.Range(
                        self.sheet.Cells(start, col),
                        self.sheet.Cells(max(last_row, start), col),
                    ).ClearContents()
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
                ok, msg = self.save()
                if not ok:
                    return False, msg
            return True, f"已重写 {len(checkins)} 行"
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            logger.exception("Excel rewrite failed")
            return False, f"Excel 重写失败：{e}"

    def status_text(self) -> str:
        if not self.sheet:
            return "未连接"
        name = ""
        wb = ""
        try:
            name = self.sheet.Name
            wb = str(self.workbook.FullName or "")
        except Exception:
            pass
        return f"已连接：{wb} / {name}"

    def disconnect(self) -> None:
        """断开当前绑定（不关闭用户 Excel，仅释放引用）。"""
        self.app = self.workbook = self.sheet = None
        self.mapping = {}
        self.header_row = None
        self.next_row = None
        self.excel_path = ""
        self.binding_id = ""

    close = disconnect


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
