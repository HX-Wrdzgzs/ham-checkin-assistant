"""置信度常量：规则系统自身的可信等级（非 AI 输出）。"""
from __future__ import annotations

# 来源对应的默认置信度
SOURCE_CONFIDENCE = {
    "input": 1.0,
    "alias": 1.0,
    "region": 0.95,
    "rule": 0.95,
    "history_recent": 0.8,
    "history_frequent": 0.7,
    "fuzzy": 0.9,
    "manual": 1.0,
}


def confidence_for(source: str, base: float = None) -> float:
    if base is not None:
        return base
    return SOURCE_CONFIDENCE.get(source, 0.5)
