"""时间规范化：数据库统一 YYYY-MM-DDTHH:MM:SS（任务书第三阶段 #6）。

Excel 里可能是：'2000' / '20:00' / '20:00:00' / Excel datetime 单元格
（openpyxl 读回为 datetime 对象，str 形如 '2026-08-08 20:00:00'）。
全部标准化为 'YYYY-MM-DDTHH:MM:SS'。
"""
from __future__ import annotations

import re
from datetime import datetime

_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?$")
_DATE_RE = re.compile(r"^(\d{4})[-_.]?(\d{1,2})[-_.]?(\d{1,2})")
_FULL_DT_RE = re.compile(
    r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?")


def normalize_time_token(tok: str) -> str | None:
    """'2000'/'20:00'/'20:00:00' → '20:00:00'；非法返回 None。"""
    tok = (tok or "").strip()
    if not tok:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", tok)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    else:
        m2 = re.match(r"^(\d{1,2})(\d{2})$", tok)  # 2000 → 20:00
        if not m2:
            return None
        h, mi, s = int(m2.group(1)), int(m2.group(2)), 0
    if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59:
        return f"{h:02d}:{mi:02d}:{s:02d}"
    return None


def normalize_checkin_time(date: str, time_tok: str) -> str:
    """组合日期+时间 → 'YYYY-MM-DDTHH:MM:SS'。

    - time_tok 若是完整 datetime 字符串（Excel 单元格），从中取日期和时间。
    - 缺日期用今天，缺时间用 00:00:00。
    """
    time_tok = (time_tok or "").strip()
    date = (date or "").strip()
    d = None
    t = None
    m = _FULL_DT_RE.match(time_tok)
    if m:
        d = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        t = f"{int(m.group(4)):02d}:{int(m.group(5)):02d}:{int(m.group(6) or 0):02d}"
    else:
        t = normalize_time_token(time_tok)
    if d is None and date:
        md = _DATE_RE.match(date)
        if md:
            d = f"{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}"
    if not t:
        t = "00:00:00"
    if not d:
        d = datetime.now().strftime("%Y-%m-%d")
    return f"{d}T{t}"
