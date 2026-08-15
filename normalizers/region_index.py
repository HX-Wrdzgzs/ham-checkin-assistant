"""行政区划索引：基于 pypinyin 预计算拼音首字母，支持缩写与中文名匹配。"""
from __future__ import annotations

from dataclasses import dataclass, field

from pypinyin import lazy_pinyin

from normalizers.regions import REGIONS

_ADMIN_SUFFIXES = (
    "特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区",
    "自治州", "自治县", "自治旗", "新区", "林区", "地区", "盟", "旗",
    "省", "市", "区", "县",
)


def strip_admin(name: str) -> str:
    for s in _ADMIN_SUFFIXES:
        if name.endswith(s) and len(name) > len(s):
            return name[: -len(s)]
    return name


def initials(name: str) -> str:
    return "".join(p[0] for p in lazy_pinyin(strip_admin(name))).lower()


# 可视为“地址细节”的尾随字符：只有这些才允许在行政区划名后折叠，避免“南京南”被静默折叠成“南京”
_DETAIL_TAIL = set(
    "0123456789站路街村镇巷桥园山湖洞号室栋单元楼层口坊弄广场大道宿舍花园小区市场"
)

# 单字行政后缀字符（用于渐进剥离“真正的行政后缀”，绝不删名称本身字符）
_ADMIN_CHARS = "省市辖区县盟旗"

# 残余允许字符 = 地址细节 + 行政后缀字符（如「青岛市南区」→ 键「青岛市南」+ 残余「区」）
_ALLOWED_TAIL = _DETAIL_TAIL | set(_ADMIN_CHARS)


@dataclass
class RegionEntry:
    province: str = ""
    city: str = ""
    district: str = ""
    display: str = ""
    initials: str = ""
    pinyin: str = ""  # 全拼音（供拼音模糊匹配，如 nanjingqixia）
    name_keys: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.display


class RegionIndex:
    """预计算全量索引，dict 查找，O(1) 查询。"""

    def __init__(self, default_province: str = "江苏") -> None:
        self.default_province = default_province
        self.by_initials: dict[str, list[RegionEntry]] = {}
        self.by_name: dict[str, list[RegionEntry]] = {}
        self._build()

    def _add_entry(self, parts: list[str], init_parts: list[str]) -> None:
        is_default = parts[0] == self.default_province
        disp_parts = parts[1:] if is_default else parts
        display = "".join(disp_parts)
        entry = RegionEntry(
            province=parts[0],
            city=parts[1] if len(parts) > 1 else "",
            district=parts[2] if len(parts) > 2 else "",
            display=display,
            initials="".join(init_parts),
            pinyin="".join("".join(lazy_pinyin(p)) for p in disp_parts).lower(),
        )
        # 拼音首字母键
        full = "".join(init_parts)
        init_keys = {full}
        # 省+市 键（直辖市除外：城市名==省名时省略城市层）
        if len(parts) >= 2 and parts[0] != parts[1]:
            init_keys.add("".join(init_parts[:-1]))
        if is_default:
            init_keys.add("".join(init_parts[1:]))  # 省略省份
            if len(parts) >= 3:
                init_keys.add(init_parts[-1])  # 区县单独（用于重名检测如 gl）
        for k in init_keys:
            self.by_initials.setdefault(k, []).append(entry)
        # 中文名键
        name_full = "".join(strip_admin(p) for p in parts)
        name_keys = {name_full}
        # 省省略键：所有省份都加（青岛市南 / 济南市中），支持省略省份的区县解析（P1-10）
        name_short = "".join(strip_admin(p) for p in parts[1:])
        if name_short and name_short != name_full:
            name_keys.add(name_short)
        # 默认省份的区县名在现场经常单独输入（如“江宁”“栖霞”）。
        # 只加入默认省份，避免跨省同名区县被静默归到当前省；同名条目仍由
        # resolve_name 返回候选，不在这里强行选择。
        if is_default and len(parts) >= 3:
            district_key = strip_admin(parts[-1])
            if district_key:
                name_keys.add(district_key)
        entry.name_keys = list(name_keys)
        for k in name_keys:
            self.by_name.setdefault(k, []).append(entry)

    def _build(self) -> None:
        for prov, cities in REGIONS.items():
            p_init = initials(prov)
            for city, districts in cities.items():
                c_init = initials(city)
                if city == prov:  # 直辖市
                    self._add_entry([prov], [p_init])
                    for d in districts:
                        self._add_entry([prov, d], [p_init, initials(d)])
                else:
                    self._add_entry([prov, city], [p_init, c_init])
                    for d in districts:
                        self._add_entry([prov, city, d], [p_init, c_init, initials(d)])

    def resolve_initials(self, alias: str) -> list[RegionEntry]:
        entries = list(self.by_initials.get(alias.lower().replace(" ", ""), []))
        if len(entries) <= 1:
            return entries
        # 同级歧义才要候选：优先层级最少的（城市级 > 区县级），避免“yz”→扬州/仪征 强制选择
        levels = [len([p for p in (e.province, e.city, e.district) if p]) for e in entries]
        min_level = min(levels)
        return [e for e, lv in zip(entries, levels) if lv == min_level]

    def resolve_name(self, name: str) -> list[RegionEntry]:
        n = name.strip().replace(" ", "")
        if not n:
            return []
        if n in self.by_name:
            return list(self.by_name[n])
        # 1) 完整行政链：去掉间隔的行政后缀字符再匹配（江苏省南京市栖霞区 → 江苏南京栖霞）
        f = "".join(ch for ch in n if ch not in _ADMIN_CHARS)
        if f and f != n:
            if f in self.by_name:
                return list(self.by_name[f])
            hits = self._containment_clean(f)
            if hits:
                return hits
        # 2) 渐进去掉「末尾真正行政后缀」再匹配（青岛市南区 → 青岛市南；不删名称本身字符）
        s = n
        while len(s) > 1 and s[-1] in _ADMIN_CHARS:
            s = s[:-1]
            if s in self.by_name:
                return list(self.by_name[s])
        # 3) 含区划名 + 残余细节/行政后缀（如 南京市栖霞区6楼）
        hits = self._containment_clean(n)
        if hits:
            return hits
        return []

    def _containment_clean(self, n: str) -> list[RegionEntry]:
        """取包含在查询串中的最长名称键；残余部分必须是可辨识的地址细节
        （或「真正的行政后缀」如 区），否则不折叠（防「南京南」被折叠成「南京」）。"""
        best_key, best_entries, best_len = "", [], 0
        for k, entries in self.by_name.items():
            if len(k) < 2:
                continue
            if k in n and len(k) > best_len:
                best_len = len(k)
                best_key = k
                best_entries = list(entries)
        if not best_key:
            return []
        leftover = n.replace(best_key, "", 1)
        if leftover and not all(ch in _ALLOWED_TAIL for ch in leftover):
            return []  # 残余含非细节字符（如“南京南”的“南”）→ 不静默折叠
        return best_entries

    def all_initials_entries(self) -> list[tuple[str, RegionEntry]]:
        out = []
        for k, entries in self.by_initials.items():
            for e in entries:
                out.append((k, e))
        return out
