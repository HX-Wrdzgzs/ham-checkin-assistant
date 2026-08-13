"""历史/外部数据的标准值计算：别名精确匹配 + 包含匹配 + QTH 行政区划。"""
from __future__ import annotations

from normalizers.antenna import resolve_antenna
from normalizers.device import resolve_device
from normalizers.dictionaries import AliasStore, norm_key
from normalizers.power import resolve_power
from normalizers.qth import QthNormalizer
from normalizers.region_index import RegionIndex

_KIND_DICT = {"device": "device", "antenna": "antenna", "power": "power"}


class Standardizer:
    def __init__(self, store: AliasStore, region: RegionIndex) -> None:
        self.store = store
        self.qth_norm = QthNormalizer(store, region)

    def standardize(self, field: str, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        if field == "qth":
            v, _, cands = self.qth_norm.resolve(raw)
            if v:
                return v
            return cands[0] if len(cands) == 1 else ""
        if field in _KIND_DICT:
            if field == "device":
                v, _ = resolve_device(self.store, raw)
            elif field == "antenna":
                v, _ = resolve_antenna(self.store, raw)
            else:
                v = resolve_power(self.store, raw)
            if v:
                return v
            return self._substring_match(_KIND_DICT[field], raw)
        return ""

    def _substring_match(self, kind: str, raw: str) -> str:
        """设备/天线含中文前缀时，从原文中找最长别名子串。"""
        key = norm_key(raw)
        d = {"device": self.store.device, "antenna": self.store.antenna, "power": self.store.power}[kind]
        best_key, best_alias = "", None
        for k, alias in d.items():
            if len(k) >= 3 and k in key and len(k) > len(best_key):
                best_key, best_alias = k, alias
        return best_alias.standard_value if best_alias else ""
