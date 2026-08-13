"""RapidFuzz 模糊匹配：缩写错拼、多/少一位、写法不统一。

阈值：>=high 自动接受；mid~high 给候选；<mid 不处理（阈值可配置）。
"""
from __future__ import annotations

from rapidfuzz import fuzz


def fuzzy_resolve(
    token: str,
    options: list[tuple[str, str]],
    high: float = 92.0,
    mid: float = 75.0,
    limit: int = 5,
):
    """options: [(key, label)]。返回 (level, [(score, key, label)])，level∈{high,mid,low}。"""
    token = (token or "").strip().lower()
    if not token:
        return "low", []
    scored = []
    for key, label in options:
        if key == token:
            continue
        score = fuzz.ratio(token, key)
        if score >= mid:
            scored.append((score, key, label))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= high:
        return "high", scored[:limit]
    if scored:
        return "mid", scored[:limit]
    return "low", []


def fuzzy_resolve_pinyin(
    token: str,
    options: list[tuple[str, str, str, float]],
    high: float = 92.0,
    mid: float = 75.0,
    limit: int = 5,
):
    """拼音加权模糊：options: [(key, label, pinyin, weight)]。

    得分 = max(字符相似度, 拼音相似度[含部分匹配])；weight 只参与排序，不改变阈值，
    避免“自信地填错”。
    """
    token = (token or "").strip().lower()
    if not token:
        return "low", []
    scored = []
    for key, label, py, weight in options:
        if key == token:
            continue
        r_char = fuzz.ratio(token, key)
        r_py = 0
        if py:
            r_py = fuzz.ratio(token, py)
            # 短词（<3 字符）不做部分匹配，避免过度纠错
            if len(token) >= 3:
                r_py = max(r_py, fuzz.partial_ratio(token, py))
        score = max(r_char, r_py)
        if score >= mid:
            scored.append((score, key, label, weight))
    scored.sort(key=lambda x: -(x[0] + x[3]))
    hits = [(s, k, l) for s, k, l, _ in scored[:limit]]
    if hits and hits[0][0] >= high:
        return "high", hits
    if hits:
        return "mid", hits
    return "low", []
