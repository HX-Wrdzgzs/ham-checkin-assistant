"""呼号规范化：自动大写、去空格、基础格式检查（不因格式禁止录入）。"""
from __future__ import annotations

import re

CALLSIGN_RE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]{1,4}$")
LOOSE_RE = re.compile(r"^[A-Z0-9/]{3,10}$")


def normalize_callsign(raw: str) -> tuple[str, bool, list[str]]:
    """返回 (标准呼号, 是否符合规范, 问题列表)。"""
    s = (raw or "").strip().upper().replace(" ", "")
    issues: list[str] = []
    if not s:
        return s, False, ["空"]
    if "/" in s:
        issues.append("特殊活动呼号，保留原样")
        return s, True, issues  # 允许人工保留
    if not LOOSE_RE.match(s):
        issues.append("格式可疑")
    valid = bool(CALLSIGN_RE.match(s))
    if not valid:
        issues.append("不符合常规呼号格式")
    return s, valid, issues
