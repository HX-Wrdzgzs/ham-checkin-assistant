"""本场资料补全建议。

补全与现场解析分开：本模块只生成可审阅建议，不改变 Parser 的“历史建议必须按
Tab 接受”规则。建议按证据分级，任何实质性覆盖都默认不勾选。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from database.models import Checkin
from database.repository import Repository
from normalizers.device_aliases import device_model_key
from normalizers.dictionaries import norm_key
from normalizers.region_index import RegionEntry, RegionIndex, strip_admin
from providers.miit import model_abbreviations
from services.standardizer import Standardizer

FIELDS = ("qth", "device", "antenna", "power")
FIELD_LABELS = {"qth": "QTH", "device": "设备", "antenna": "天线", "power": "功率"}
FIELD_ATTRS = {field: f"{field}_standard" for field in FIELDS}

_PLACEHOLDERS = {"", "-", "—", "无", "未知", "不详", "none", "null"}
_ADMIN_CHARS = "省市辖区县盟旗"
_DIRECT_CITIES = {"北京", "上海", "天津", "重庆"}
_AUTONOMOUS_PROVINCES = {
    "内蒙古": "内蒙古自治区",
    "广西": "广西壮族自治区",
    "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区",
    "新疆": "新疆维吾尔自治区",
    "香港": "香港特别行政区",
    "澳门": "澳门特别行政区",
}

# 江苏内置区划中的县级市名称没有统一携带“市”后缀，整理输出时需要补回。
_JIANGSU_COUNTY_CITIES = {
    "新沂", "邳州", "东台", "仪征", "高邮", "靖江", "泰兴", "兴化",
    "启东", "如皋", "海安", "丹阳", "扬中", "句容", "溧阳", "江阴",
    "宜兴", "常熟", "张家港", "昆山", "太仓",
}

_MODEL_PART_RE = re.compile(r"[a-z]+|\d+", re.I)


def _catalog_search(catalog, query: str, limit: int = 3) -> list[dict]:
    """快速补全专用型号查询；兼容旧版 catalog 替身。"""
    try:
        return catalog.search(query, limit=limit, allow_fuzzy=False)
    except TypeError:
        try:
            return catalog.search(query, limit=limit)
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001
        return []


def _text(value) -> str:
    return str(value or "").strip()


def _is_placeholder(value: str) -> bool:
    return _text(value).lower() in _PLACEHOLDERS


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(_text(value))
    except (TypeError, ValueError):
        return None


def _compact_qth(value: str) -> str:
    return "".join(ch for ch in _text(value).replace(" ", "") if ch not in _ADMIN_CHARS)


def _device_parts(value: str) -> list[str]:
    return _MODEL_PART_RE.findall(norm_key(value))


def _same_device_model(left: str, right: str) -> bool:
    a, b = norm_key(left), norm_key(right)
    if not a or not b:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) >= 3
    pa, pb = _device_parts(a), _device_parts(b)
    long_numbers_a = {part for part in pa if part.isdigit() and len(part) >= 3}
    long_numbers_b = {part for part in pb if part.isdigit() and len(part) >= 3}
    return bool(long_numbers_a & long_numbers_b)


def _equivalent(field: str, old: str, new: str) -> bool:
    if not old:
        return True
    if norm_key(old) == norm_key(new):
        return True
    if field == "qth":
        a, b = _compact_qth(old), _compact_qth(new)
        # 省份前缀只是在规范化时补上的行政层级，例如“南京江宁”与
        # “江苏南京江宁牛首山”属于同一地点链；地点细节仍必须是包含关系。
        return bool(a and b and (a.startswith(b) or b.startswith(a) or a in b or b in a))
    if field == "device":
        # “HT”→“HT链路”增加了实际含义，不作为纯格式变化自动覆盖。
        if norm_key(old) == "ht" and "链路" in new:
            return False
        return _same_device_model(old, new)
    if field == "antenna":
        def slim(value: str) -> str:
            out = norm_key(value)
            for word in ("天线", "原装"):
                out = out.replace(word, "")
            return out

        a, b = slim(old), slim(new)
        return bool(a and b and (a == b or a in b or b in a))
    return False


def _province_full(name: str) -> str:
    if not name:
        return ""
    if name in _DIRECT_CITIES:
        return f"{name}市"
    if name in _AUTONOMOUS_PROVINCES:
        return _AUTONOMOUS_PROVINCES[name]
    if name.endswith(("省", "自治区", "特别行政区")):
        return name
    return f"{name}省"


def _city_full(name: str) -> str:
    if not name:
        return ""
    if name.endswith(("市", "地区", "盟", "自治州")):
        return name
    # 徐州、扬州、苏州等名称以“州”结尾，但行政层级仍是地级市。
    if name.endswith("州"):
        return f"{name}市"
    return f"{name}市"


def _district_full(name: str, province: str) -> str:
    if not name:
        return ""
    if name.endswith(("区", "县", "市", "旗", "林区")):
        return name
    if province == "江苏" and name in _JIANGSU_COUNTY_CITIES:
        return f"{name}市"
    return f"{name}区"


def _entry_parts(entry: RegionEntry) -> tuple[str, str, str]:
    """兼容 RegionIndex 对直辖市区县使用 (province, city, '') 的结构。"""
    if entry.province in _DIRECT_CITIES:
        district = entry.district or (entry.city if entry.city != entry.province else "")
        return entry.province, "", district
    return entry.province, entry.city, entry.district


def _entry_full(entry: RegionEntry) -> str:
    province, city, district = _entry_parts(entry)
    return _province_full(province) + _city_full(city) + _district_full(district, province)


def _entry_forms(entry: RegionEntry) -> set[str]:
    province, city, district = _entry_parts(entry)
    p_full, c_full = _province_full(province), _city_full(city)
    d_full = _district_full(district, province)
    forms = {
        entry.display,
        province + city + district,
        city + district,
        p_full + c_full + d_full,
        c_full + d_full,
    }
    if district:
        forms.add(district)
        forms.add(d_full)
    if city:
        forms.add(city)
        forms.add(c_full)
    if province in _DIRECT_CITIES:
        forms.add(province + district)
        forms.add(p_full + d_full)
    return {form.replace(" ", "") for form in forms if form}


def _qth_admin_match(value: str, region: RegionIndex) -> tuple[str, RegionEntry, str] | None:
    """返回 QTH 最长且唯一的行政区划前缀及其余地点原文。"""
    raw = _text(value).replace(" ", "")
    if not raw:
        return None
    mixed = re.fullmatch(r"([A-Za-z]+)([\u4e00-\u9fff].*)", raw)
    if mixed:
        prefix, tail = mixed.groups()
        for end in range(len(prefix), 1, -1):
            candidates = region.resolve_initials(prefix[:end])
            if len(candidates) == 1:
                return raw, candidates[0], tail
    entries: list[RegionEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for group in region.by_name.values():
        for entry in group:
            parts = _entry_parts(entry)
            if parts not in seen:
                seen.add(parts)
                entries.append(entry)

    # 城市级值（如“扬州”“南京”）同时是该城市所有区县的前缀；如果直接
    # 进入下面的前缀匹配，会被多个更深层条目判成歧义。先处理官方/索引
    # 中的精确显示值，并兼容直辖市的“浦东”省略“新区”写法。
    exact = [
        entry for entry in entries
        if entry.display == raw or strip_admin(entry.display) == raw
    ]
    if len(exact) == 1:
        return raw, exact[0], ""

    matches: list[tuple[int, RegionEntry, str]] = []
    for entry in entries:
        for form in _entry_forms(entry):
            if not raw.startswith(form):
                continue
            tail = raw[len(form):]
            # 城市级命中“南京大学”时，不能把校名后缀误当成地点细节。
            _province, _city, district = _entry_parts(entry)
            if not district and tail.startswith(("大学", "学院", "航空", "理工")):
                continue
            # 裸城市名后接“路/街/大道”等时，可能是道路名称而不是该城市
            # 的行政前缀；没有地点库精确证据时不能把“中山路”猜成中山市。
            if not district and tail.startswith(("路", "街", "大道", "大街", "巷")):
                continue
            matches.append((len(form), entry, tail))
    if not matches:
        return None
    longest = max(length for length, _entry, _tail in matches)
    top = [(entry, tail) for length, entry, tail in matches if length == longest]
    unique = {(_entry_parts(entry), tail) for entry, tail in top}
    if len(unique) != 1:
        return None
    entry, tail = top[0]
    return raw, entry, tail


def full_qth_candidate(value: str, region: RegionIndex) -> str:
    """补齐可确认的省/市/区县，并原样保留其后的地点细节。

    只接受唯一最长行政区划匹配；“鼓楼”等重名且没有城市上下文时返回空，
    不会默认归到南京。街道、学校和地标只保留原文，绝不凭历史猜造。
    """
    match = _qth_admin_match(value, region)
    if match is None:
        return ""
    raw, entry, tail = match
    candidate = _entry_full(entry) + tail
    return candidate if candidate != raw else ""


class CompletionEngine:
    """从未识别原文、确定性词典、同次报到和呼号历史生成建议。"""

    def __init__(self, repo: Repository, standardizer: Standardizer,
                 region: RegionIndex, catalog=None, place_resolver=None) -> None:
        self.repo = repo
        self.standardizer = standardizer
        self.region = region
        self.catalog = catalog
        self.place_resolver = place_resolver
        # 由 AppService 从历史/导入记录构建的临时缩写；它不改变正式
        # device_aliases，且只包含无冲突的一对一映射。
        self.observed_device_aliases: dict[str, str] = {}

    def set_observed_device_aliases(self, aliases: dict[str, str] | None) -> None:
        """更新历史观察缩写索引。"""
        self.observed_device_aliases = dict(aliases or {})

    def suggest_session(self, session_id: int) -> list[dict]:
        suggestions: list[dict] = []
        history_cache: dict[str, list[Checkin]] = {}
        for checkin in self.repo.list_checkins(session_id):
            history = history_cache.setdefault(
                checkin.callsign,
                self.repo.station_history(checkin.callsign, 100),
            )
            suggestions.extend(self._suggest_checkin(checkin, history))
        return sorted(
            suggestions,
            key=lambda item: (item["sequence_no"], FIELDS.index(item["field"])),
        )

    def _suggest_checkin(self, checkin: Checkin, history: list[Checkin]) -> list[dict]:
        candidates: dict[str, list[dict]] = {field: [] for field in FIELDS}
        old_values = {field: _text(getattr(checkin, FIELD_ATTRS[field], "")) for field in FIELDS}

        for item in self._unmatched_candidates(checkin, old_values):
            candidates[item["field"]].append(item)

        for field, old in old_values.items():
            if field == "qth":
                proposed = full_qth_candidate(old, self.region)
                place = None
                if not proposed and self.place_resolver is not None:
                    try:
                        place = self.place_resolver.resolve(old)
                    except Exception:  # noqa: BLE001
                        place = None
                    proposed = _text(place.get("canonical_qth")) if place else ""
                if proposed:
                    source_type = "place_exact" if place else "admin_exact"
                    source_label = "本地点库精确匹配" if place else "行政区划确定性补齐"
                    detail = (
                        f"地点“{_text(place.get('name'))}”唯一映射到省/市/区"
                        if place else "只补省/市/区县后缀，街道和地标保留原文"
                    )
                    candidates[field].append(self._candidate(
                        field, proposed, source_type, source_label, detail,
                        97 if place else 96, True, 114 if place else 112,
                    ))
            elif old:
                proposed = self.standardizer.standardize(field, old)
                if field == "antenna" and proposed == "原":
                    proposed = "原装天线"
                if proposed and proposed != old:
                    candidates[field].append(self._candidate(
                        field, proposed, "alias_exact", "本地精确词典",
                        f"“{old}”精确映射到规范值", 97, True, 124,
                    ))

        for field in FIELDS:
            history_item = self._history_candidate(checkin, field, old_values[field], history)
            if history_item:
                candidates[field].append(history_item)

        # 独立工信部电台快照只作为设备候选，不自动覆盖；候选详情带官方记录
        # ID/核准代码，便于现场后整理时复核来源。
        old_device = old_values["device"]
        if old_device:
            catalog = []
            if self.catalog is not None:
                catalog = _catalog_search(self.catalog, old_device, limit=3)
            first = catalog[0] if catalog else None
            source_type = "miit_catalog"
            if first is None:
                cached = self.repo.find_miit_device_cache(old_device, limit=3)
                first = cached[0] if cached else None
                source_type = "miit_cache"
            if first is not None:
                proposed = _text(first.get("standard_name") or first.get("model"))
                if proposed and proposed != old_device:
                    # 旧表中的原始设备可能已经有内置别名（例如 UV-K6）。
                    # 若工信部缓存/快照给出同一规范值，使用官方候选保留
                    # article_id 和同步批次，避免本地别名遮掉来源留痕。
                    candidates["device"] = [
                        item for item in candidates["device"]
                        if not (
                            item.get("source_type") == "alias_exact"
                            and norm_key(item.get("proposed_value")) == norm_key(proposed)
                        )
                    ]
                    candidates["device"].append(self._candidate(
                        "device", proposed, source_type,
                        "工信部电台型号库" if source_type == "miit_catalog" else "工信部本地缓存",
                        self._miit_detail(first), 88, False, 82,
                        candidate_id=_text(first.get("article_id")),
                        miit_article_id=_text(first.get("article_id")),
                        miit_sync_run_id=_text(first.get("miit_sync_run_id")),
                    ))

        out: list[dict] = []
        for field in FIELDS:
            viable = [item for item in candidates[field]
                      if _text(item["proposed_value"]) != old_values[field]]
            if not viable:
                continue
            # 安全项适当加权：若高置信同次记录与低风险行政补齐冲突，
            # 实质性覆盖不会挤掉可直接应用的安全建议。
            best = max(
                viable,
                key=lambda item: (item["priority"] + (20 if item["default_selected"] else 0),
                                  item["confidence"]),
            )
            best = dict(best)
            best.update(
                record_id=checkin.id,
                session_id=checkin.session_id,
                sequence_no=checkin.sequence_no,
                callsign=checkin.callsign,
                field_label=FIELD_LABELS[field],
                old_value=old_values[field],
                old_unmatched=_text(checkin.unmatched),
            )
            best.pop("priority", None)
            out.append(best)
        return out

    @staticmethod
    def _candidate(field: str, value: str, source_type: str, source_label: str,
                   detail: str, confidence: int, selected: bool, priority: int,
                    *, evidence: str = "", candidate_id: str = "",
                    choice_group: str = "", evidence_token_start: int | None = None,
                    evidence_token_end: int | None = None,
                    requires_confirmation: bool | None = None,
                    miit_article_id: str = "", miit_sync_run_id: str = "") -> dict:
        return {
            "field": field,
            "proposed_value": _text(value),
            "source_type": source_type,
            "source_label": source_label,
            "source_detail": detail,
            "confidence": max(0, min(int(confidence), 100)),
            "default_selected": bool(selected),
            "risk": "安全补齐" if selected else "需要确认",
            "priority": int(priority),
            "evidence": evidence,
            "candidate_id": candidate_id,
            "choice_group": choice_group,
            "evidence_token_start": evidence_token_start,
            "evidence_token_end": evidence_token_end,
            "requires_confirmation": (
                bool(not selected) if requires_confirmation is None else bool(requires_confirmation)
            ),
            "miit_article_id": miit_article_id,
            "miit_sync_run_id": miit_sync_run_id,
        }

    def _unmatched_candidates(self, checkin: Checkin, old_values: dict[str, str]) -> list[dict]:
        parts = _text(checkin.unmatched).split()
        if not parts:
            return []
        # 先保留“字段 - token 区间”的全部命中，再做一个确定性的轻量
        # 一对一分配。单个 yz 同时可解释为 QTH/天线时共用一个 choice_group；
        # 两个 yz 则优先分给两个不同区间，避免应用时总是消费第一个。
        hits: list[dict] = []
        for width in range(min(3, len(parts)), 0, -1):
            for start in range(len(parts) - width + 1):
                if width > 1 and len({norm_key(part) for part in parts[start:start + width]}) == 1:
                    # 两个相同缩写分别可能代表两个字段；不要先把
                    # “yz yz”拼成一个虚假的复合 QTH。
                    continue
                phrase = " ".join(parts[start:start + width])
                phrase_hits: list[tuple[str, str, bool, str, str]] = []
                for field in FIELDS:
                    if old_values[field]:
                        continue
                    exact = False
                    value = ""
                    if field == "qth":
                        resolved, source, choices = self.standardizer.qth_norm.resolve(phrase)
                        if resolved and source in ("alias", "region", "place") and len(choices) <= 1:
                            value = resolved
                            exact = True
                            value = full_qth_candidate(value, self.region) or value
                    else:
                        alias = self.standardizer.store.lookup(field, phrase)
                        if alias:
                            value = alias.standard_value
                            exact = True
                        elif field == "device":
                            value = self.observed_device_aliases.get(
                                device_model_key(phrase), "")
                            exact = bool(value)
                            if not value:
                                value = self.standardizer.standardize(field, phrase)
                        else:
                            value = self.standardizer.standardize(field, phrase)
                    if field == "antenna" and value == "原":
                        value = "原装天线"
                    if value:
                        phrase_hits.append((field, value, exact, "", ""))
                    if field == "device" and self.catalog is not None:
                        catalog_hits = _catalog_search(self.catalog, phrase, limit=3)
                        for item in catalog_hits:
                            model = _text(item.get("model"))
                            proposed = _text(item.get("standard_name") or model)
                            if not model or not proposed:
                                continue
                            phrase_key = norm_key(phrase)
                            model_key = norm_key(model)
                            # 宽泛的“包含匹配”不能直接消费未识别原文；
                            # 官方完整型号或官方型号生成的后缀缩写可以作为
                            # 候选，但缩写仍需确认，不能默认覆盖。
                            is_full_model = model_key == phrase_key
                            is_official_abbreviation = phrase_key in model_abbreviations(model)
                            if not (is_full_model or is_official_abbreviation):
                                continue
                            phrase_hits.append((
                                field,
                                proposed,
                                False,
                                _text(item.get("article_id")),
                                _text(item.get("miit_sync_run_id")),
                            ))
                            break
                if not phrase_hits:
                    continue
                # 相同字段/值的重复词典来源只保留一个，避免重复候选。
                unique: list[tuple[str, str, bool, str, str]] = []
                for item in phrase_hits:
                    key = (item[0], norm_key(item[1]))
                    existing_index = next(
                        (index for index, existing in enumerate(unique)
                         if (existing[0], norm_key(existing[1])) == key),
                        None,
                    )
                    if existing_index is None:
                        unique.append(item)
                        continue
                    # 本地别名和工信部结果可能给出同一个规范值。保留
                    # 工信部记录 ID/同步批次，导入整理时才能追溯官方依据；
                    # 现场解析仍然优先使用本地别名，不受这里影响。
                    if item[3] and not unique[existing_index][3]:
                        unique[existing_index] = item
                hits.append({
                    "start": start,
                    "end": start + width,
                    "phrase": phrase,
                    "items": unique,
                })

        by_field: dict[str, list[tuple[int, int, str, bool, str, str]]] = {
            field: [] for field in FIELDS
        }
        for hit in hits:
            for field, value, exact, candidate_id, sync_run_id in hit["items"]:
                by_field[field].append((
                    hit["start"], hit["end"], value, exact, candidate_id, sync_run_id,
                ))

        selected_hits: list[tuple[str, int, int, str, bool, str, str]] = []
        assigned_groups: set[tuple[int, int]] = set()
        for field in FIELDS:
            options = by_field[field]
            if not options:
                continue
            options.sort(key=lambda item: (
                not item[3], -(item[1] - item[0]), item[0], norm_key(item[2]),
            ))
            available = [item for item in options if (item[0], item[1]) not in assigned_groups]
            chosen = (available or options)[0]
            start, end, value, exact, candidate_id, sync_run_id = chosen
            selected_hits.append((
                field, start, end, value, exact, candidate_id, sync_run_id,
            ))
            assigned_groups.add((start, end))

        group_counts = Counter(
            (start, end)
            for _field, start, end, _value, _exact, _id, _sync_id in selected_hits
        )
        best: dict[str, dict] = {}
        for field, start, end, value, exact, candidate_id, sync_run_id in selected_hits:
            phrase = " ".join(parts[start:end])
            ambiguous = group_counts[(start, end)] > 1
            item = self._candidate(
                field,
                value,
                "unmatched_exact" if exact else "unmatched_contains",
                "未识别原文",
                f"从未识别内容“{phrase}”恢复；原文仍保留到应用成功为止",
                98 if exact and not ambiguous else 87,
                exact and not ambiguous,
                132 if exact else 118,
                evidence=phrase,
                candidate_id=candidate_id,
                choice_group=f"record:{checkin.id}:unmatched:{start}:{end}",
                evidence_token_start=start,
                evidence_token_end=end,
                requires_confirmation=ambiguous,
                miit_article_id=candidate_id,
                miit_sync_run_id=sync_run_id,
            )
            # 同一字段只保留最长证据、精确匹配优先；其余 token 不丢数据，
            # 但不让一个字段在预览里重复出现。
            rank = (item["priority"], len(item["evidence"]))
            old = best.get(field)
            old_rank = (old["priority"], len(old["evidence"])) if old else (-1, -1)
            if rank > old_rank:
                best[field] = item
        return list(best.values())

    def _history_candidate(self, checkin: Checkin, field: str, old: str,
                           history: list[Checkin]) -> dict | None:
        attr = FIELD_ATTRS[field]
        current_time = _parse_time(checkin.checkin_time)
        usable = [item for item in history
                  if item.id != checkin.id
                  and item.session_id != checkin.session_id
                  and not _is_placeholder(getattr(item, attr, ""))]
        if not usable:
            return None

        same_event: list[tuple[float, Checkin]] = []
        if current_time:
            for item in usable:
                hist_time = _parse_time(item.checkin_time)
                if hist_time is None:
                    continue
                seconds = abs((hist_time - current_time).total_seconds())
                if seconds <= 120:
                    same_event.append((seconds, item))
        if same_event:
            seconds, item = min(
                same_event,
                key=lambda pair: (pair[0], 0 if pair[1].source == "365dt" else 1, -pair[1].id),
            )
            value = _text(getattr(item, attr, ""))
            selected = not old or _equivalent(field, old, value)
            detail = (
                f"{item.source or '历史'} 在同一分钟记录，时间差 {int(seconds)} 秒；"
                "仍请在应用前核对当前上报"
            )
            return self._candidate(
                field, value, "same_event", "同次报到记录", detail,
                99 if seconds <= 60 else 97, selected, 180,
            )

        values = [_text(getattr(item, attr, "")) for item in usable]
        counts = Counter(values)
        latest_by_value: dict[str, Checkin] = {}
        for item in usable:  # station_history 已按时间倒序
            value = _text(getattr(item, attr, ""))
            latest_by_value.setdefault(value, item)
        value = max(
            counts,
            key=lambda candidate: (
                counts[candidate],
                _text(latest_by_value[candidate].checkin_time),
                candidate,
            ),
        )
        latest = latest_by_value[value]
        conflicts = len(counts)
        qth_history_safe = field != "qth" or self._qth_history_is_safe(value)

        if old:
            if not _equivalent(field, old, value):
                return None
            selected = qth_history_safe
            confidence = 91 if counts[value] >= 2 else 84
        else:
            # 只有至少两次且无冲突的画像才默认补空；单次或冲突历史仅建议。
            selected = (
                counts[value] >= 2
                and conflicts == 1
                and qth_history_safe
            )
            confidence = 91 if selected else (78 if conflicts == 1 else 64)
        detail = (
            f"本呼号历史出现 {counts[value]} 次，最近 {_text(latest.checkin_time)[:10] or '时间未知'}"
        )
        if conflicts > 1:
            detail += f"；该字段共有 {conflicts} 个不同历史值，默认不勾选"
        if field == "qth" and not qth_history_safe:
            detail += "；为避免跨场次引入街道和地标，默认不勾选"
        return self._candidate(
            field, value, "history_profile", "呼号历史画像", detail,
            confidence, selected, 91 if selected else 70,
        )

    def _qth_history_is_safe(self, value: str) -> bool:
        """历史画像只自动补行政区划，不跨场次带入街道/学校/地标。"""
        match = _qth_admin_match(value, self.region)
        return match is not None and not match[2]

    @staticmethod
    def _miit_detail(item: dict) -> str:
        parts = [
            _text(item.get("device_name")),
            _text(item.get("applicant")),
            f"记录 ID {_text(item.get('article_id'))}" if item.get("article_id") else "",
            f"核准代码 {_text(item.get('approval_code'))}" if item.get("approval_code") else "",
            f"CMIIT ID {_text(item.get('cmiit_id'))}" if item.get("cmiit_id") else "",
            f"查询于 {_text(item.get('fetched_at'))[:10]}" if item.get("fetched_at") else "",
        ]
        return "；".join(part for part in parts if part)
