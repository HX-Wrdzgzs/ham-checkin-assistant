"""呼号规范化：自动大写、去空格、格式检查（含 / 后缀合法性，任务书第二阶段 #8）。"""
from __future__ import annotations

import re

CALLSIGN_RE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]{1,4}$")
LOOSE_RE = re.compile(r"^[A-Z0-9/]{3,10}$")
# 主体：标准呼号；后缀：1~3 位字母/数字（P/M/MM/区域号等）
_SUFFIX_RE = re.compile(r"^[A-Z0-9]{1,3}$")


def normalize_callsign(raw: str) -> tuple[str, bool, list[str]]:
    """返回 (标准呼号, 是否符合规范, 问题列表)。

    含 / 的便携/移动呼号：主体必须合法 + 后缀合法（///、A/// 等拒绝）。
    """
    s = (raw or "").strip().upper().replace(" ", "")
    issues: list[str] = []
    if not s:
        return s, False, ["空"]
    if "/" in s:
        parts = s.split("/")
        base, suffix = parts[0], "/".join(parts[1:])
        if base.startswith("/") or base.endswith("/"):
            issues.append("主体呼号为空")
        valid_base = bool(CALLSIGN_RE.match(base))
        if not valid_base:
            issues.append("主体呼号不合法")
        valid_suffix = bool(suffix and _SUFFIX_RE.match(suffix))
        if not valid_suffix:
            issues.append("后缀不合法")
        if not (3 <= len(s) <= 12):
            issues.append("长度可疑")
        return s, valid_base and valid_suffix, issues
    if not LOOSE_RE.match(s):
        issues.append("格式可疑")
    valid = bool(CALLSIGN_RE.match(s))
    if not valid:
        issues.append("不符合常规呼号格式")
    return s, valid, issues
