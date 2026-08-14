"""设备规范化：别名匹配（忽略大小写、连字符、空格）。"""
from __future__ import annotations

from normalizers.dictionaries import AliasStore


def resolve_device(store: AliasStore, token: str):
    """返回 (标准值, 候选列表) 或 (None, [])。"""
    alias = store.lookup("device", token)
    if alias:
        return alias.standard_value, []
    return None, []
