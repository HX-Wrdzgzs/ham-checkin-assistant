"""功率规范化：规则 + 别名。

规则：
- 带单位 5w / 10瓦 → 5W / 10W
- 两位前导零 01 → 0.1W
- 纯数字 5 → 5W
- l/m/h/f → 低/中/高/满
注意：纯数字是否解释为功率由 Parser 依据上下文决定，本函数只负责“给定判定为功率的 token 时的标准化”。
"""
from __future__ import annotations

import re

from normalizers.dictionaries import AliasStore

_NUM_UNIT = re.compile(r"^(\d+(?:\.\d+)?)\s*(w|瓦)?$")
_LEADING_ZERO = re.compile(r"^0\d$")


def resolve_power(store: AliasStore, token: str):
    """返回标准化功率或 None。"""
    t = (token or "").strip()
    if not t:
        return None
    alias = store.lookup("power", t)
    if alias:
        return alias.standard_value
    m = _NUM_UNIT.fullmatch(t.lower())
    if m:
        num, unit = m.group(1), m.group(2)
        if unit in ("w", "瓦") or num.replace(".", "").isdigit():
            if _LEADING_ZERO.match(num):
                return f"0.{num[1]}W"
            try:
                return f"{float(num):g}W"
            except ValueError:
                return f"{num}W"
    return None
