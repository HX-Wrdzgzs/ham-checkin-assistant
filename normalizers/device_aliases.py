"""从已经明确的设备文本中提取可解释的型号缩写。

工信部资料库只覆盖“无线电发射设备型号核准”中的记录；现场还会使用
未核准、旧型号或进口二手机型。因此这里提供一套不依赖工信部的轻量
型号切分规则，供“历史观察缩写”和“用户确认词典”复用。

本模块只提取字母+数字型号，不根据相似度猜品牌，也不把纯数字（例如
功率）自动当成设备型号。真正的标准值必须来自已有明确记录或用户确认。
"""
from __future__ import annotations

import re


# 这些词只用于阻止“品牌 + 型号”被拼成一个过宽的别名；品牌本身不会
# 作为型号缩写返回。中英文和现场常用简称均覆盖，但不会据此推断型号归属。
_BRAND_PARTS = {
    "motorola", "moto", "摩托罗拉",
    "yaesu", "八重洲",
    "icom", "艾可慕",
    "kenwood", "建伍", "建武",
    "anytone", "安拓",
    "hytera", "海能达",
    "baofeng", "宝锋",
    "quansheng", "泉盛",
    "wouxun", "欧讯",
    "linton", "灵通",
    "kirisun", "科立讯",
    "zastone", "即时通", "森海克斯",
    "bfdx", "北峰",
}

_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9()_.\-/]*")
_BASE_MODEL_RE = re.compile(r"^[A-Za-z]+\d+[A-Za-z]*", re.I)
_NON_MODEL_KEYS = {"w", "kw", "mw", "dbm", "mhz", "khz", "hz"}


def _compact(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").lower()


def device_model_key(value: str) -> str:
    """设备型号比较键：忽略大小写、空格和常见型号标点。"""
    return _compact(str(value or ""))


def _is_model_key(value: str) -> bool:
    key = _compact(value)
    if (len(key) < 2 or key in _NON_MODEL_KEYS
            or re.fullmatch(r"\d+(?:w|kw|mw|dbm)", key)):
        return False
    return bool(re.search(r"[a-z]", key) and re.search(r"\d", key))


def _add(values: list[str], value: str) -> None:
    key = _compact(value)
    if _is_model_key(key) and key not in values:
        values.append(key)


def device_model_abbreviations(*values: str) -> tuple[str, ...]:
    """提取现场可用的型号缩写，返回稳定且去重后的归一化键。

    示例：

    * ``摩托罗拉 GM 338`` -> ``("gm338",)``；
    * ``UV-K1(8)`` -> ``("uvk18", "k18", "k1")``；
    * ``KENWOOD TM-V71A`` -> ``("tmv71a", "v71a")``。

    函数允许同时传入原始值和标准值。调用方应把标准值作为最终映射
    目标，而不是把本函数的结果当成品牌识别结果。
    """
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        parts = _PART_RE.findall(text)
        if not parts:
            continue

        # 单片和相邻片段都尝试一次，覆盖 GM338、GM 338、ID-52 PLUS、
        # XTS 5000 等常见写法。窗口中若含品牌词则跳过，避免生成
        # motorolagm338 之类没有现场价值的宽键。
        for start in range(len(parts)):
            for end in range(start + 1, min(len(parts), start + 3) + 1):
                window = parts[start:end]
                if any(_compact(part) in _BRAND_PARTS for part in window):
                    continue
                _add(output, "".join(window))

        # 连字符、斜线和括号经常把基础型号切开；把带数字的片段本身
        # 以及“字母+数字”基础型号也放进去。纯数字永远不返回。
        for part in parts:
            for segment in re.split(r"[-_/]", part):
                _add(output, segment)
                base = _BASE_MODEL_RE.match(segment)
                if base:
                    _add(output, base.group(0))

    return tuple(output)


__all__ = ["device_model_abbreviations", "device_model_key"]
