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
from normalizers.antenna import normalize_antenna_measurement, resolve_antenna
from normalizers.callsign import normalize_callsign
from normalizers.device import resolve_device
from normalizers.device_aliases import device_model_key
from normalizers.dictionaries import AliasStore, norm_key
from normalizers.power import resolve_power
from normalizers.qth import QthNormalizer
from normalizers.region_index import RegionIndex

_SIGNAL = re.compile(r"^5[1-9]$")
_UNIT_POWER = re.compile(r"^\d+(?:\.\d+)?(w|瓦)$", re.I)
_UNKNOWN_ANTENNA_METERS = re.compile(
    r"^\d+(?:\.\d+)?(?:米|m)(?:玻璃钢|天线|gp)?$", re.I)
_UNKNOWN_DEVICE = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z0-9._-]{3,}$", re.I)
_CHINESE_DEVICE_PREFIXES = (
    "八重洲", "海能达", "好易通", "摩托罗拉", "威泰克斯", "泉盛", "宝锋",
    "全易通", "建伍", "艾可慕", "即时通", "特易通", "欧讯", "灵通", "科立讯",
    "建武", "森海克斯",
)
_DEVICE_BRANDS = {
    "摩托罗拉": "摩托罗拉", "motorola": "摩托罗拉", "moto": "摩托罗拉",
    "八重洲": "八重洲", "yaesu": "YAESU",
    "艾可慕": "ICOM", "icom": "ICOM",
    "建伍": "KENWOOD", "kenwood": "KENWOOD",
    "建武": "建武",
    "海能达": "海能达", "hytera": "海能达",
    "hyt": "海能达",
    "宝锋": "宝锋", "baofeng": "宝锋",
    "泉盛": "泉盛", "quansheng": "泉盛",
    "全易通": "全易通", "qyt": "全易通",
    "威泰克斯": "威诺", "vertex": "威诺",
    "即时通": "即时通", "zastone": "即时通",
    "特易通": "特易通", "tyt": "特易通",
    "欧讯": "欧讯", "wouxun": "欧讯",
    "灵通": "灵通", "linton": "灵通",
    "科立讯": "科立讯", "kirisun": "科立讯",
    "森海克斯": "森海克斯",
}

_POWER_WORDS = {
    "低功": "低",
    "中功": "中",
    "高功": "高",
    "满功": "满",
}

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


def _looks_like_antenna(token: str) -> bool:
    """判断未收录但明显像天线描述的原文，避免被 QTH 兜底吞掉。"""
    text = (token or "").strip()
    key = norm_key(text)
    if ("天线" in text or _UNKNOWN_ANTENNA_METERS.fullmatch(text)
            or normalize_antenna_measurement(text)):
        return True
    # 现场会把设备/地点拼在一起写成“HT湖北上台”这类天线描述；
    # 只对已知天线前缀 HT + 中文后缀启用，避免把普通中文 QTH 误判为天线。
    if key.startswith("ht") and len(key) > 2 and any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return True
    if text.endswith("上台") and len(text) > 2:
        return True
    if key.startswith(("az", "srh")) and any(ch.isdigit() for ch in key):
        return True
    if key in {"鹅颈", "鹅颈天线", "1.8米gp", "1.8米", "八木"}:
        return True
    # “老鹰507”这类现场天线简称没有统一品牌词典，但其前缀+型号
    # 组合足够明确；保留原文到天线列，避免最后被 QTH 兜底吞掉。
    if key.startswith("老鹰") and any(ch.isdigit() for ch in key):
        return True
    return False


def _looks_like_device(token: str) -> bool:
    """判断未收录的字母+数字机型，保留其原文而不是当成 QTH。"""
    text = (token or "").strip()
    if _UNKNOWN_DEVICE.fullmatch(text):
        return True
    key = norm_key(text)
    # 中文品牌+数字型号（例如 海能达pdc580、好易通800、八重洲150R）
    # 是设备描述，不应被当作未知地点。只对白名单品牌启用，避免把
    # 任意“地点+年份/楼号”误判为设备。
    return (any(key.startswith(prefix) for prefix in _CHINESE_DEVICE_PREFIXES)
            and any(ch.isdigit() for ch in key))


def _looks_like_branded_model(token: str) -> bool:
    """品牌上下文中的短型号（例如 Motorola R6）允许两字符。"""
    key = device_model_key(token)
    return bool(re.fullmatch(r"[a-z]+\d+[a-z0-9]*", key, re.I))


def _looks_like_power_word(token: str) -> bool:
    return norm_key(token) in _POWER_WORDS


class Parser:
    def __init__(self, store: AliasStore, region: RegionIndex, predictor: Predictor,
                 fuzzy_high: float = 92.0, fuzzy_mid: float = 75.0,
                 fuzzy_margin: float = 5.0, radio_catalog=None, qth_places=None) -> None:
        self.store = store
        self.region = region
        self.qth_norm = QthNormalizer(store, region, qth_places)
        self.predictor = predictor
        self.fuzzy_high = fuzzy_high
        self.fuzzy_mid = fuzzy_mid
        self.fuzzy_margin = fuzzy_margin
        self.radio_catalog = radio_catalog
        # 来自本地已明确记录的“观察缩写”。它与用户词典和工信部快照
        # 分开，只有型号键唯一映射到一个标准值时才会被注入。
        self.observed_device_aliases: dict[str, str] = {}
        self._qth_fuzzy_opts = None
        self._qth_ambiguous_displays: set[str] | None = None

    def set_observed_device_aliases(self, aliases: dict[str, str] | None) -> None:
        """更新历史观察到的设备缩写，不写入用户词典。"""
        self.observed_device_aliases = dict(aliases or {})

    def resolve_device_token(self, token: str) -> tuple[str, str]:
        """按“用户词典 → 历史观察缩写 → 工信部精确型号”解析设备。

        返回 ``(标准值, 来源)``。来源单独保留，便于预览区区分“用户已
        确认的缩写”和“根据历史记录观察到的缩写”。
        """
        value, _ = resolve_device(self.store, token)
        if value:
            return value, "alias"
        observed = self.observed_device_aliases.get(device_model_key(token))
        if observed:
            return observed, "observed_alias"
        if self.radio_catalog is not None:
            try:
                matches = self.radio_catalog.exact_model(token)
            except Exception:  # noqa: BLE001 - 型号库不可用不影响现场解析
                matches = []
            if matches:
                first = matches[0]
                value = (first.get("standard_name") or first.get("model") or "").strip()
                if value:
                    return value, "miit_catalog"
            # 只有短的字母+数字缩写才走这一层；合法呼号形状优先留给
            # 呼号阶段，避免把 BA4XXX 之类误当作型号后缀。若多个官方
            # 记录对应不同标准值，则不擅自选择，仍交给候选/人工确认。
            key = device_model_key(token)
            _, valid_call, _ = normalize_callsign(token)
            if (not valid_call and len(key) >= 2 and re.search(r"[a-z]", key)
                    and re.search(r"\d", key)
                    and hasattr(self.radio_catalog, "abbreviation_matches")):
                try:
                    abbreviation_rows = self.radio_catalog.abbreviation_matches(
                        token, limit=50,
                    )
                except Exception:  # noqa: BLE001 - 型号库不可用不影响现场解析
                    abbreviation_rows = []
                values = {
                    (row.get("standard_name") or row.get("model") or "").strip()
                    for row in abbreviation_rows
                    if (row.get("standard_name") or row.get("model") or "").strip()
                }
                if len(values) == 1:
                    return next(iter(values)), "miit_catalog"
        return "", ""

    def invalidate_caches(self) -> None:
        """别名/省份变化后使模糊缓存失效（由 AppService 在词典/区划变更时调用）。"""
        self._qth_fuzzy_opts = None
        self._qth_ambiguous_displays = None

    def _is_alias_token(self, t: str) -> bool:
        """token 是否已收录为设备/天线/功率/QTH 缩写（优先于呼号判定）。"""
        if self.resolve_device_token(t)[0]:
            return True
        if any(self.store.lookup(k, t) for k in ("antenna", "power", "qth")):
            return True
        return False

    def _consume_compound_device(self, result: ParseResult,
                                 tokens: list[str], used: list[bool]) -> None:
        """先消费“品牌 + 型号”组合，避免 BF 被单独占成设备后型号丢失。"""
        if result.device.value:
            return
        # 先尝试三词，再尝试两词；只接受词典中的完整组合，不做模糊猜测。
        for width in (3, 2):
            for i in range(0, len(tokens) - width + 1):
                indexes = range(i, i + width)
                if any(used[j] for j in indexes):
                    continue
                phrase = " ".join(tokens[j] for j in indexes)
                v, source = self.resolve_device_token(phrase)
                if not v:
                    continue
                result.device = ParseField(v, source, 1.0, raw=phrase)
                for j in indexes:
                    used[j] = True
                return

    def _consume_brand_device_pair(self, result: ParseResult,
                                   tokens: list[str], used: list[bool]) -> None:
        """保留“品牌 + 未核准型号”的明确输入。

        工信部没有收录的进口旧机、二手机型仍然是合法的现场资料。只要
        品牌是白名单中的电台品牌，旁边是字母+数字型号，就把两者作为
        一个设备值保存；若型号本身已有词典/工信部标准，则优先使用该
        标准，不擅自重新命名。
        """
        if result.device.value:
            return
        for i, token in enumerate(tokens):
            if used[i] or norm_key(token) not in _DEVICE_BRANDS:
                continue
            # 品牌通常写在型号前；优先向后看，避免把前面的 BA4XXX
            # 呼号误当成“字母+数字型号”。
            for j in (i + 1, i - 1):
                if j < 0 or j >= len(tokens) or used[j]:
                    continue
                model = tokens[j].strip()
                if not (_looks_like_device(model) or _looks_like_branded_model(model)):
                    continue
                # 词典中也有“品牌本身”的缩写（如 tyt/qyt）。品牌后面
                # 若没有型号，前一个通常就是呼号；不能把 ``BG4TKI TYT``
                # 拼成“特易通 BG4TKI”。向后找仍可正常处理
                # ``摩托罗拉 M8268``，这里只限制反向消费。
                if j < i and _looks_like_callsign(model):
                    continue
                resolved, source = self.resolve_device_token(model)
                value = resolved or f"{_DEVICE_BRANDS[norm_key(token)]} {model.upper()}"
                result.device = ParseField(value, source or "input", 1.0,
                                           raw=f"{token} {model}")
                used[i] = True
                used[j] = True
                return

        # 现场也会省略品牌与型号之间的空格，例如“摩托罗拉R6”。先跳过
        # 已有完整词典/工信部命中的写法，再只对白名单品牌拆解，避免把
        # 任意中文+数字地点改造成设备。
        for i, token in enumerate(tokens):
            if used[i] or self.resolve_device_token(token)[0]:
                continue
            # 这里不能用 device_model_key：它专门去掉中文，只适合比较型号。
            # 无空格中文品牌（“摩托罗拉R6”）需要保留品牌前缀再拆分。
            compact = norm_key(token)
            for brand_key, brand in sorted(
                    _DEVICE_BRANDS.items(), key=lambda item: len(norm_key(item[0])),
                    reverse=True):
                brand_compact = norm_key(brand_key)
                if not brand_compact or not compact.startswith(brand_compact):
                    continue
                model = device_model_key(compact[len(brand_compact):])
                if not _looks_like_branded_model(model):
                    continue
                value = f"{brand} {model.upper()}"
                result.device = ParseField(value, "input", 1.0, raw=token)
                used[i] = True
                return

    def _qth_fuzzy_options(self) -> list:
        if self._qth_fuzzy_opts is None:
            prov = self.region.default_province
            seen: set = set()
            opts = []
            bykey: dict[str, list] = {}
            for k, e in self.region.all_initials_entries():
                seen.add(k)
                bykey.setdefault(k, []).append(e)
            # P2：同一缩写 key 映射多个不同城市区县（gl → 南京鼓楼/徐州鼓楼）
            # 必须全部保留，不得按 key 丢弃歧义地点。
            # 按 display 去重（一个地点保留最短缩写 key + 最高权重），避免父级
            # 作用域 key（jsnj）把同一地点重复 N 次挤占候选名额。
            best: dict[str, tuple] = {}
            for k, entries in bykey.items():
                for e in entries:
                    weight = 3.0 if e.province == prov else 0.0
                    cur = best.get(e.display)
                    if cur is None or (weight, -len(k)) > (cur[2], -len(cur[1])):
                        best[e.display] = (e, k, weight)
            for e, k, weight in best.values():
                opts.append((k, e.display, e.pinyin, weight))
            opts += [(k, a.standard_value, "", 0.0)
                     for k, a in self.store.qth.items() if k not in seen]
            self._qth_fuzzy_opts = opts
            # 真歧义 display：区县级条目与**其他城市**的同缩写条目并存（南京鼓楼 vs 徐州鼓楼）。
            # 排除父级作用域 key 与同城市重名，避免误伤正常自动接受。
            amb_displays: set[str] = set()
            for k, entries in bykey.items():
                cities = {e.city for e in entries if e.district}
                if len(cities) > 1:
                    amb_displays.update(e.display for e in entries if e.district)
            self._qth_ambiguous_displays = amb_displays
        return self._qth_fuzzy_opts

    def _qth_display_is_ambiguous(self, display: str) -> bool:
        self._qth_fuzzy_options()  # 确保缓存已构建
        return display in (self._qth_ambiguous_displays or set())

    def parse(self, text: str, session_id: int | None = None) -> ParseResult:
        result = ParseResult(raw_text=text or "")
        result.tokens = text.split() if text else []
        tokens = result.tokens
        used = [False] * len(tokens)

        # 有些现场缩写跨字段复用（例如 yz = 扬州，也可表示原装天线）。
        # 先按出现顺序消费一次 QTH、一次天线，避免后面的字段阶段把单个 yz
        # 抢成天线，从而破坏既有的“单个 yz → 扬州”规则。
        self._consume_overlapping_aliases(result, tokens, used)
        # 现场名单后半段常见“BF 5rh / BF UV-32 / RYT 6900 / wpks 2108”。
        # 组合命中必须早于单 token 设备阶段，否则 BF 会先占位、型号会落入未识别。
        self._consume_brand_device_pair(result, tokens, used)
        self._consume_compound_device(result, tokens, used)

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
            v, source = self.resolve_device_token(t)
            if v and not result.device.value:
                result.device = ParseField(v, source, 1.0, raw=t)
                used[i] = True

        # 4. 天线
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            v, _ = resolve_antenna(self.store, t)
            if v and not result.antenna.value:
                result.antenna = ParseField(v, "alias", 1.0, raw=t)
                used[i] = True

        # 5. 已明确识别的 QTH：别名/行政区划优先于任何中文原文。
        #    QthNormalizer 对未知中文会返回 source=input 以便保留现场地址，
        #    这里不能先把它当 QTH，否则“504天线”“高功”“1.8米”等会抢字段。
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            v, source, cands = self.qth_norm.resolve(t)
            if v and source in ("alias", "region", "place") and not result.qth.value:
                result.qth = ParseField(v, source, confidence_for(source), raw=t)
                if len(cands) > 1:
                    result.qth.candidates = cands
                used[i] = True
            elif cands and not result.qth.value:
                result.qth.candidates = cands

        # 6. 明显的现场字段原文：即使词典没有，也必须进入对应列，
        #    不能因为“未识别”而从 Excel/数据库消失。
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            if _looks_like_power_word(t) and not result.power.value:
                result.power = ParseField(_POWER_WORDS[norm_key(t)], "input", 1.0, raw=t)
                used[i] = True
            elif _looks_like_antenna(t) and not result.antenna.value:
                result.antenna = ParseField(
                    normalize_antenna_measurement(t) or t.strip(),
                    "input", 1.0, raw=t,
                )
                used[i] = True
            elif _looks_like_device(t) and not result.device.value:
                result.device = ParseField(t.strip(), "input", 1.0, raw=t)
                used[i] = True

        # 7. 剩余纯数字 → 功率（≤3 位或功率别名；4 位如 1907 不当作功率，避免误判）
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            if t.isdigit() and (len(t) <= 3 or self.store.lookup("power", t)):
                v = resolve_power(self.store, t)
                if v and not result.power.value:
                    result.power = ParseField(v, "rule", 0.95, raw=t)
                    used[i] = True

        # 8. 历史建议（呼号已知）。只放入 result.history，绝不直接写入字段——
        #    只有用户 Tab 接受（accept_history）后才进入提交 payload（任务书第二阶段 #1/#2）。
        if result.callsign.value:
            result.history = self.predictor.predict(result.callsign.value)

        # 9. 模糊匹配未匹配 token
        for i, t in enumerate(tokens):
            if used[i]:
                continue
            self._try_fuzzy(result, t, used, i)

        # 10. 最后才把剩余中文原文作为 QTH。此时已知 QTH、机型、天线、功率
        #     和模糊高置信结果都已经占位，未知地址仍会原样保留。
        if not result.qth.value:
            for i, t in enumerate(tokens):
                if used[i] or _looks_like_antenna(t) or _looks_like_power_word(t):
                    continue
                v, source, cands = self.qth_norm.resolve(t)
                if v and source == "input":
                    result.qth = ParseField(v, source, confidence_for(source), raw=t)
                    used[i] = True
                    break

        # P2：fuzzy 成功后重新计算 unmatched（fuzzy 可能消化了部分 token）
        result.unmatched = [t for i, t in enumerate(tokens) if not used[i]]

        return result

    def _consume_overlapping_aliases(self, result: ParseResult,
                                     tokens: list[str], used: list[bool]) -> None:
        """处理同时存在于 QTH/天线词典的重复缩写。

        现场常见三种写法：``yz``、``yz yz``、``yz 湖北``。第一种按
        既有规则是扬州，第二种拆成扬州+原装，第三种应把湖北保留为 QTH、
        把 yz 作为天线。仅按第一个命中消费会导致后续字段被错位吞掉。
        """
        if result.qth.value or result.antenna.value:
            return
        overlaps = []
        qth_only = []
        qth_inputs = []
        for i, token in enumerate(tokens):
            if used[i]:
                continue
            qth, source, candidates = self.qth_norm.resolve(token)
            antenna, _ = resolve_antenna(self.store, token)
            if qth and source in ("alias", "region", "place"):
                if antenna:
                    overlaps.append((i, token, qth, source, candidates, antenna))
                else:
                    qth_only.append((i, token, qth, source, candidates))
            elif (qth and source == "input" and not _looks_like_antenna(token)
                  and not _looks_like_power_word(token)):
                qth_inputs.append((i, token, qth))

        if not overlaps:
            return

        # 有明确 QTH 原文（例如“湖北”）时，重复缩写优先作为天线。
        if qth_inputs and not qth_only:
            qidx, qtoken, qvalue = qth_inputs[0]
            oidx, otoken, _qth, _source, _cands, antenna = overlaps[0]
            result.qth = ParseField(qvalue, "input", 1.0, raw=qtoken)
            result.antenna = ParseField(antenna, "alias", 1.0, raw=otoken)
            used[qidx] = True
            used[oidx] = True
            return

        # 出现独立的已知 QTH（例如 njgl）时，它优先作为 QTH。
        # 若重叠的 yz 在这个缩写 QTH **之前**，而且后者是 yz 的更具体
        # 行政区写法（例如“yz yzjd”），前面的 yz 是地点前缀，不应凭空
        # 生成“原”天线；若 yz 在 QTH 之后（例如“njqh ... yz”），才按
        # 天线消费。这样既保留“重复 yz → 扬州 + 原装”，又不污染名单中
        # “扬州 + 扬州江都”的地点输入。
        if qth_only:
            oidx, otoken, _qth, _source, _cands, antenna = overlaps[0]
            scoped_qths = [item for item in qth_only
                           if item[0] > oidx
                           and item[3] in ("alias", "region")
                           and norm_key(otoken) == "yz"
                           and not any("\u4e00" <= ch <= "\u9fff" for ch in item[1])
                           and norm_key(item[1]).startswith("yz")
                           and norm_key(item[1]) != "yz"]
            if scoped_qths:
                # 更长的缩写通常是更具体的行政区；同长度保留后出现者。
                qidx, qtoken, qth, source, candidates = max(
                    scoped_qths,
                    key=lambda item: (len(norm_key(item[1])), item[0]),
                )
                result.qth = ParseField(qth, source, confidence_for(source), raw=qtoken)
                if len(candidates) > 1:
                    result.qth.candidates = candidates
                used[qidx] = True
                # 这个 yz 已经作为地点前缀被消费，不再填天线，也不显示为未识别。
                used[oidx] = True
                return

            qidx, qtoken, qth, source, candidates = qth_only[0]
            result.qth = ParseField(qth, source, confidence_for(source), raw=qtoken)
            if len(candidates) > 1:
                result.qth.candidates = candidates
            used[qidx] = True
            result.antenna = ParseField(antenna, "alias", 1.0, raw=otoken)
            used[oidx] = True
            return

        # 没有第二个地点时保持“单个 yz → 扬州”；只有重复 token 才拆出天线。
        oidx, otoken, qth, source, candidates, antenna = overlaps[0]
        result.qth = ParseField(qth, source, confidence_for(source), raw=otoken)
        if len(candidates) > 1:
            result.qth.candidates = candidates
        used[oidx] = True
        same = [j for j, other in enumerate(tokens)
                if not used[j] and norm_key(other) == norm_key(otoken)]
        if same:
            result.antenna = ParseField(antenna, "alias", 1.0, raw=tokens[same[0]])
            used[same[0]] = True

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
        device_options = self.store.options("device")
        device_options += [
            (key, value) for key, value in self.observed_device_aliases.items()
            if key not in {item[0] for item in device_options}
        ]
        for opts, kind in [
            (device_options, "device"),
            (self.store.options("antenna"), "antenna"),
            (self.store.options("power"), "power"),
        ]:
            level, hits = fuzzy_resolve(token, opts, self.fuzzy_high, self.fuzzy_mid,
                                        min_margin=self.fuzzy_margin)
            if level == "low":
                continue
            if best_level == "low" or (hits and hits[0][0] > (best_hits[0][0] if best_hits else 0)):
                best_level, best_hits, best_kind = level, hits, kind
        # 本地工信部快照只用于设备候选，不联网。只在 token 足够长时查询，
        # 避免用户每敲一个字符都扫描几十万条型号记录。
        if (best_kind is None or best_kind == "device") and self.radio_catalog is not None:
            key = norm_key(token)
            if len(key) >= 3 and not result.device.value:
                try:
                    catalog_hits = self.radio_catalog.search(
                        token, limit=3, allow_fuzzy=False,
                    )
                except TypeError:
                    # 兼容旧版/测试替身 catalog；正式资料库支持快速检索开关。
                    try:
                        catalog_hits = self.radio_catalog.search(token, limit=3)
                    except Exception:  # noqa: BLE001
                        catalog_hits = []
                except Exception:  # noqa: BLE001
                    catalog_hits = []
                if catalog_hits:
                    labels = [h.get("standard_name") or h.get("model") for h in catalog_hits]
                    labels = [v for v in labels if v]
                    if labels:
                        exact = next(
                            (h for h in catalog_hits
                             if norm_key(h.get("model")) == key), None,
                        )
                        if exact:
                            result.device = ParseField(
                                exact.get("standard_name") or exact.get("model"),
                                "miit_catalog", 0.98, raw=token,
                            )
                            used[i] = True
                            return
                        if not best_hits:
                            result.device.candidates = list(dict.fromkeys(labels))
        if not best_hits:
            return
        field = getattr(result, best_kind)
        # P2：QTH 命中跨城市歧义地点（南京鼓楼 vs 徐州鼓楼）时，即使 fuzzy 判 high
        # 也强制降级为候选，绝不按 key 丢弃歧义地点而自信猜错。
        if best_kind == "qth" and best_level == "high" and best_hits:
            if self._qth_display_is_ambiguous(best_hits[0][2]):
                best_level = "mid"
        if best_level == "high" and not field.value:
            field.value = best_hits[0][2]
            field.source = "fuzzy"
            field.confidence = confidence_for("fuzzy")
            field.raw = token
            used[i] = True
        elif best_level == "mid" and not field.value:
            field.candidates = list(dict.fromkeys(h[2] for h in best_hits))
