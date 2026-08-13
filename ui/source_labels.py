"""字段来源中文标签（规格第 69 节）。"""
from __future__ import annotations

SOURCE_LABELS = {
    "input": "本次",
    "alias": "缩写",
    "region": "区划",
    "rule": "规则",
    "history_recent": "历史最近",
    "history_frequent": "历史高频",
    "fuzzy": "模糊",
    "manual": "已接受",
}


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source or "")


_FIELD_NAMES = {"callsign": "呼号", "qth": "QTH", "device": "设备",
                "antenna": "天线", "power": "功率", "signal": "信号"}


def field_name(field: str) -> str:
    return _FIELD_NAMES.get(field, field)
