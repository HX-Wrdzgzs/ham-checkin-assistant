"""核心 Parser：自由顺序字段识别，纯规则 + 词典 + 历史 + 模糊，无 AI。

处理顺序（规格第 25 节）：
Tokenize → 呼号 → 明确信号/功率 → 设备 → 天线 → QTH → 历史补全 → 模糊匹配
"""
from __future__ import annotations

import re

from core.confidence import confidence_for
from core.fuzzy_resolver import fuzzy_resolve, fuzzy_resolve_pinyin
from core.predictor import Predictor
from database.models import ParseField, ParseResult
from normalizers.antenna import resolve_antenna
from normalizers.callsign import normalize_callsign
from normalizers.device import resolve_device
from normalizers.dictionaries import AliasStore
from normalizers.power import resolve_power
from normalizers.qth import QthNormalizer
from normalizers.region_index import RegionIndex

_SIGNAL = re.compile(r"^5[1-9]$")
_UNIT_POWER = re.compile(r"^\d+(?:\.\d+)?(w|瓦)$", re.I)

_FUZZY_FIELDS = (
    ("qth", "qth"), ("device", "device"), ("antenna", "antenna"), ("power", "power"),
)


def _looks_like_callsign(t: str) -> bool:
    s = (t or "").upper().replace(" ", "")
    if not s or not s[0].isalpha():
        return False
    if "/" in s:
        return len(s) >= 3
    return 3 <= len(s) <= 10 and any(c.isdigit() for c in s) and s.isalnum()


def _is_explicit_power(store: AliasStore, t: str) -> bool:
    if _UNIT_POWER.fullmatch(t):
        return True
    if t.lower() in ("l", "m", "h", "f"):
        return True
    return store.lookup("power", t) is not None


class Parser:
    def __init__(self, store: AliasStore, region: RegionIndex, predictor: Predictor,
                 fuzzy_high: float = 92.0, fuzzy_mid: float = 75.0,
                 fuzzy_margin: float = 5.0) -> None:
        self.store = store
        self.region = region
        self.qth_norm = QthNormalizer(store, region)
        self.predictor = predictor
        self.fuzzy_high = fuzzy_high
        self.fuzzy_mid = fuzzy_mid
        self.fuzzy_margin = fuzzy_margin
        self._qth_fuzzy_opts = None

    def invalidate_caches(self) -> None:
        """别名/省份变化后使模糊缓存失效（由 AppService 在词典/区划变更时调用）。"""
        self._qth_fuzzy_opts = None

    def _is_alias_token(self, t: str) -> bool:
        """token 是否已收录为设备/天线/功率/QTH 缩写（优先于呼号判定）。"""
        return any(self.store.lookup(k, t) for k in ("device", "antenna", "power", "qth"))

    def _qth_fuzzy_options(self) -> list:
        if self._qth_fuzzy_opts is None:
            prov = self.region.default_province
            seen: set = set()
            opts = []
            for k, e in self.region.all_initials_entries():
                if k in seen:
                    continue
                seen.add(k)
                opts.append((k, e.display, e.pinyin, 3.0 if e.province == prov else 0.0))
            opts += [(k, a.standard_value, "", 0.0)
                     for k, a in self.store.qth.items() if k not in seen]
            self._qth_fuzzy_opts = opts
        return self._qth_fuzzy_opts

    def parse(self, text: str, session_id: int | None = None) -> ParseResult:
        result = ParseResult(raw_text=text or "")
        result.tokens = text.split() if text else []
        tokens = result.tokens
        used = [False] * len(tokens)

        # 1. 呼号（已收录缩写优先，避免 id52/ft1900/1907 这类被误当呼号）
        for i, t in enumerate(tokens):
            if self._is_alias_token(t):
                continue
            std, valid, issues = normalize_callsign(t)
            has_slash = "/" in (t or "")
            # 含 / 的呼号必须整体合法（///、A/// 等拒绝，任务书第二阶段 #8）
            if std and (valid or (not has_slash and _looks_like_callsign(t))):
                result.callsign = ParseField(std, "input", 1.0,
                                             candidates=issues if issues else [], raw=t)
                used[i] = True
                break

        # 2. 明确信号 / 明确功率
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            if _SIGNAL.fullmatch(t) and not self.store.lookup("antenna", t):
                result.signal = ParseField(t, "input", 1.0, raw=t)
                used[i] = True
                continue
            if _is_explicit_power(self.store, t):
                v = resolve_power(self.store, t)
                if v and not result.power.value:
                    result.power = ParseField(v, "input", 1.0, raw=t)
                    used[i] = True

        # 3. 设备
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            v, _ = resolve_device(self.store, t)
            if v and not result.device.value:
                result.device = ParseField(v, "alias", 1.0, raw=t)
                used[i] = True

        # 4. 天线
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            v, _ = resolve_antenna(self.store, t)
            if v and not result.antenna.value:
                result.antenna = ParseField(v, "alias", 1.0, raw=t)
                used[i] = True

        # 5. QTH
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            v, source, cands = self.qth_norm.resolve(t)
            if v and not result.qth.value:
                result.qth = ParseField(v, source, confidence_for(source), raw=t)
                if len(cands) > 1:
                    result.qth.candidates = cands
                used[i] = True
            elif cands and not result.qth.value:
                result.qth.candidates = cands

        # 6. 剩余纯数字 → 功率（≤3 位或功率别名；4 位如 1907 不当作功率，避免误判）
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            if t.isdigit() and (len(t) <= 3 or self.store.lookup("power", t)):
                v = resolve_power(self.store, t)
                if v and not result.power.value:
                    result.power = ParseField(v, "rule", 0.95, raw=t)
                    used[i] = True

        result.unmatched = [t for i, t in enumerate(tokens) if not used[i]]

        # 7. 历史建议（呼号已知）。只放入 result.history，绝不直接写入字段——
        #    只有用户 Tab 接受（accept_history）后才进入提交 payload（任务书第二阶段 #1/#2）。
        if result.callsign.value:
            result.history = self.predictor.predict(result.callsign.value)

        # 8. 模糊匹配未匹配 token
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            self._try_fuzzy(result, t, used, i)

        return result

    def accept_history(self, result: ParseResult) -> ParseResult:
        """Tab 接受历史建议：把 history 中的 recent/frequent 合入缺失字段，标记为 manual。

        只在用户显式接受后，历史值才进入提交 payload（任务书第二阶段 #1/#2）。
        """
        for ft, info in result.history.items():
            field = getattr(result, ft)
            if field.value:
                continue  # 本次显式输入优先，历史绝不覆盖
            val = (info or {}).get("recent") or (info or {}).get("frequent")
            if val:
                field.value = val
                field.source = "manual"
                field.confidence = confidence_for("manual")
        return result

    def _try_fuzzy(self, result: ParseResult, token: str, used: list, i: int) -> None:
        best_level, best_hits, best_kind = "low", [], None
        # QTH：字符 + 拼音 + 省份权重（选项缓存，避免每次解析重建全量列表）
        level, hits = fuzzy_resolve_pinyin(
            token, self._qth_fuzzy_options(), self.fuzzy_high, self.fuzzy_mid,
            min_margin=self.fuzzy_margin)
        if level != "low":
            best_level, best_hits, best_kind = level, hits, "qth"
        # 设备 / 天线 / 功率：字符相似度
        for opts, kind in [
            (self.store.options("device"), "device"),
            (self.store.options("antenna"), "antenna"),
            (self.store.options("power"), "power"),
        ]:
            level, hits = fuzzy_resolve(token, opts, self.fuzzy_high, self.fuzzy_mid,
                                        min_margin=self.fuzzy_margin)
            if level == "low":
                continue
            if best_level == "low" or (hits and hits[0][0] > (best_hits[0][0] if best_hits else 0)):
                best_level, best_hits, best_kind = level, hits, kind
        if not best_hits:
            return
        field = getattr(result, best_kind)
        if best_level == "high" and not field.value:
            field.value = best_hits[0][2]
            field.source = "fuzzy"
            field.confidence = confidence_for("fuzzy")
            field.raw = token
            used[i] = True
        elif best_level == "mid" and not field.value:
            field.candidates = list(dict.fromkeys(h[2] for h in best_hits))
