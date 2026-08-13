"""历史预测：基于 SQLite 统计的“最近一次”与“最常用”，供建议/预填。

默认优先最近一次（台友可能换 QTH/设备/天线/功率）。
只提供建议，绝不自动提交。
"""
from __future__ import annotations

from database.repository import Repository

FIELDS = ("qth", "device", "antenna", "power")
COL = {"qth": "qth_standard", "device": "device_standard",
       "antenna": "antenna_standard", "power": "power_standard"}


class Predictor:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def predict(self, callsign: str) -> dict:
        """返回 {field: {"recent": str, "frequent": str}}。"""
        if not callsign:
            return {}
        recent = self.repo.recent_history(callsign)
        out: dict = {}
        for ft in FIELDS:
            col = COL[ft]
            freq = self.repo.profiles_for(callsign, ft, 1)
            out[ft] = {
                "recent": getattr(recent, col, "") if recent else "",
                "frequent": freq[0].field_value if freq else "",
            }
        return out

    def fill_missing(self, callsign: str, current: dict) -> dict:
        """为缺失字段补充历史建议：优先 recent，其次 frequent。"""
        pred = self.predict(callsign)
        filled = dict(current)
        for ft, info in pred.items():
            if not filled.get(ft):
                filled[ft] = info["recent"] or info["frequent"]
        return filled
