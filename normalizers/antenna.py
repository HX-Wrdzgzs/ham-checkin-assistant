"""天线规范化：别名匹配。"""
from __future__ import annotations

from normalizers.dictionaries import AliasStore


def resolve_antenna(store: AliasStore, token: str):
    alias = store.lookup("antenna", token)
    if alias:
        return alias.standard_value, []
    return None, []
