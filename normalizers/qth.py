"""QTH 规范化：别名 + 行政区划库。

优先级：明确别名 > 拼音首字母 > 中文名。
重名（如 gl → 南京鼓楼/徐州鼓楼）必须返回候选，不得静默选择。
"""
from __future__ import annotations

from normalizers.dictionaries import AliasStore, norm_key
from normalizers.region_index import RegionEntry, RegionIndex

_HAN = "\u4e00-\u9fff"


class QthNormalizer:
    def __init__(self, store: AliasStore, region: RegionIndex) -> None:
        self.store = store
        self.region = region

    def resolve(self, token: str):
        """返回 (standard, source, candidates)。"""
        t = token.strip()
        if not t:
            return None, "", []
        if any("\u4e00" <= ch <= "\u9fff" for ch in t):
            return self._resolve_chinese(t)
        return self._resolve_abbr(t)

    def _resolve_abbr(self, token: str):
        key = norm_key(token)
        alias = self.store.qth.get(key)
        if alias:
            return alias.standard_value, "alias", []
        entries = self.region.resolve_initials(key)
        if entries:
            cands = list(dict.fromkeys(e.display for e in entries))
            std = cands[0] if len(cands) == 1 else ""
            return (std, "region", cands) if std else (None, "region", cands)
        return None, "", []

    def _resolve_chinese(self, token: str):
        # 全中文：先尝试整串行政区划匹配；无法干净匹配时保留原文（不静默折叠）
        entries = self.region.resolve_name(token)
        if entries:
            cands = list(dict.fromkeys(e.display for e in entries))
            std = cands[0] if len(cands) == 1 else ""
            return (std, "region", cands) if std else (None, "region", cands)
        return (token, "input", [])
