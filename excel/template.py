"""Excel 表头识别：不写死列，通过表头别名动态映射列（规格第 48 节）。"""
from __future__ import annotations

FIELDS = ("sequence", "date", "time", "callsign", "qth", "device", "antenna", "power", "signal")

# 别名表：统一转大写去空格后匹配
HEADER_ALIASES: dict[str, list[str]] = {
    "sequence": ["序号", "序", "NO", "NO.", "#", "编号", "SEQUENCE"],
    "date": ["日期", "点名日期", "DATE", "上报日期"],
    "time": ["时间", "TIME", "点名时间", "上报时间", "TIME(HHMM)"],
    "callsign": ["呼号", "CALLSIGN", "CALL", "电台呼号", "CALL SIGN"],
    "qth": ["QTH", "地点", "位置", "QTH地点"],
    "device": ["设备", "机器", "DEVICE", "电台设备", "设备型号"],
    "antenna": ["天线", "ANTENNA", "天线型号"],
    "power": ["功率", "POWER", "发射功率", "功率(W)"],
    "signal": ["信号", "SIGNAL", "信号报告", "信号强度"],
}

# 导出模板表头（SQLite 重建 Excel 用）
EXPORT_HEADERS = ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率", "信号", "来源"]


def _norm(value) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def detect_header(header_row: list) -> dict[str, int]:
    """返回 {field: col_index}，识别失败/缺失的字段不包含在内。"""
    mapping: dict[str, int] = {}
    for idx, value in enumerate(header_row):
        nv = _norm(value)
        if not nv:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field in mapping:
                continue
            if nv in (_norm(a) for a in aliases):
                mapping[field] = idx
                break
    return mapping


def has_header(header_row: list) -> bool:
    """判断一行是否像表头（含至少一个已识别字段）。"""
    return len(detect_header(header_row)) >= 2


def find_header_row(rows: list[list]) -> tuple[int | None, dict[str, int]]:
    """在前若干行中寻找表头行，返回 (行号, 列映射)。"""
    for i, row in enumerate(rows[:10]):
        mapping = detect_header(row)
        if len(mapping) >= 2 and ("callsign" in mapping or "sequence" in mapping):
            return i, mapping
    return None, {}
