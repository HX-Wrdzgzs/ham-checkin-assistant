"""QTH 规范化：别名 + 行政区划库。

优先级：明确别名 > 拼音首字母 > 中文名。
重名（如 gl → 南京鼓楼/徐州鼓楼）必须返回候选，不得静默选择。
"""
from __future__ import annotations

import re

from normalizers.dictionaries import AliasStore, norm_key
from normalizers.region_index import RegionIndex

_HAN = "\u4e00-\u9fff"


class QthNormalizer:
    def __init__(self, store: AliasStore, region: RegionIndex, places=None) -> None:
        self.store = store
        self.region = region
        self.places = places

    def set_places(self, places=None) -> None:
        self.places = places

    def resolve(self, token: str):
        """返回 (standard, source, candidates)。"""
        t = token.strip()
        if not t:
            return None, "", []
        # 现场常把行政区缩写和道路/地标直接连写，例如
        # ``njgl中山路169号``。不能因为后半段含中文就跳过前半段的
        # 确定性缩写，否则完整 QTH 只能落入“未识别”。
        mixed = self._resolve_mixed(t)
        if mixed is not None:
            return mixed
        if any("\u4e00" <= ch <= "\u9fff" for ch in t):
            return self._resolve_chinese(t)
        return self._resolve_abbr(t)

    def _resolve_mixed(self, token: str):
        """解析“拼音首字母 + 中文地点细节”的混合写法。

        只接受前缀能唯一命中现有行政区/别名的情况；道路、门牌和地标
        原文全部保留，不根据相似度猜地点。返回值仍使用 ``region`` 或
        ``alias`` 来源，兼容现场解析的确定性路径。
        """
        match = re.fullmatch(r"([A-Za-z]+)([\u4e00-\u9fff].*)", token)
        if not match:
            return None
        prefix, suffix = match.groups()
        # 最长前缀优先，避免把 njgl... 错拆成 nj + gl...。
        for end in range(len(prefix), 1, -1):
            standard, source, candidates = self._resolve_abbr(prefix[:end])
            if standard and not candidates and source:
                return standard + suffix, source, []
        return None

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
        # 地点包中的道路/学校/车站只在唯一精确命中时自动采用；模糊命中
        # 仍由补全窗口展示候选，不在现场静默猜测。
        if self.places is not None:
            try:
                place = self.places.resolve(token)
            except Exception:  # noqa: BLE001 - 地点库损坏不影响行政区解析
                place = None
            if place:
                canonical = str(place.get("canonical_qth") or "").strip()
                if canonical:
                    return canonical, "place", []
        # 全中文：先尝试整串行政区划匹配；无法干净匹配时保留原文（不静默折叠）
        entries = self.region.resolve_name(token)
        if entries:
            cands = list(dict.fromkeys(e.display for e in entries))
            std = cands[0] if len(cands) == 1 else ""
            return (std, "region", cands) if std else (None, "region", cands)
        return (token, "input", [])
