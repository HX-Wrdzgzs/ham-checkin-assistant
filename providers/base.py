"""数据源 Provider 抽象：新增公开点名数据源只需实现该接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def check_updates(self) -> dict:
        """检查是否有更新，返回 {'has_new': bool, ...}。"""

    @abstractmethod
    def fetch_records(self) -> list[dict]:
        """拉取全部（或增量）原始记录，返回 dict 列表。"""

    @abstractmethod
    def normalize_record(self, raw: dict) -> dict:
        """把原始记录标准化为 checkins 可用的字段。"""
