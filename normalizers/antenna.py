"""天线规范化：别名匹配和常见长度写法。"""
from __future__ import annotations

import re

from normalizers.dictionaries import AliasStore

_MEASUREMENT_RE = re.compile(
    r"^(?P<length>\d+(?:\.\d+)?)(?:米|m)(?P<kind>玻璃钢|天线|gp)?$",
    re.IGNORECASE,
)


def normalize_antenna_measurement(value: str) -> str:
    """把现场的 ``4.2m`` 等长度写法规范成可读的天线值。

    现场只写长度时，按点名表既有约定解释为玻璃钢天线；只有明确写出
    ``天线`` 或 ``GP`` 才保留对应后缀。其他无法确认的描述仍返回空，
    不会把普通数字或地址误塞进天线列。
    """
    text = str(value or "").strip()
    match = _MEASUREMENT_RE.fullmatch(text)
    if not match:
        return ""
    length = match.group("length")
    kind = (match.group("kind") or "玻璃钢").casefold()
    if kind == "gp":
        suffix = "GP"
    elif kind == "天线":
        suffix = "天线"
    else:
        suffix = "玻璃钢"
    return f"{length}米{suffix}"


def resolve_antenna(store: AliasStore, token: str):
    alias = store.lookup("antenna", token)
    if alias:
        return alias.standard_value, []
    normalized = normalize_antenna_measurement(token)
    if normalized:
        return normalized, []
    return None, []
