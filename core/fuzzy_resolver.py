"""RapidFuzz 模糊匹配：缩写错拼、多/少一位、写法不统一。

阈值：>=high 且 top1-top2>=min_margin 才自动接受；否则给候选（任务书第二阶段 #5）。
"""
from __future__ import annotations

from rapidfuzz import fuzz


def fuzzy_resolve(
    token: str,
    options: list[tuple[str, str]],
    high: float = 92.0,
    mid: float = 75.0,
    limit: int = 5,
    min_margin: float = 5.0,
):
    """options: [(key, label)]。返回 (level, [(score, key, label)])，level∈{high,mid,low}。

    仅当 top1>=high 且与 top2 分差 >= min_margin 才自动接受（high）；
    分差不足 → 强制 mid 候选，禁止自信地猜错。
    """
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
        # 精确匹配（100）→ 无歧义，直接接受（南京 vs 南京市 的 partial 同分不算歧义）
        if scored[0][0] >= 100.0:
            return "high", scored[:limit]
        margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0)
        if margin >= min_margin:
            return "high", scored[:limit]
        return "mid", scored[:limit]  # 分差不足 → 强制候选
    if scored:
        return "mid", scored[:limit]
    return "low", []


def fuzzy_resolve_pinyin(
    token: str,
    options: list[tuple[str, str, str, float]],
    high: float = 92.0,
    mid: float = 75.0,
    limit: int = 5,
    min_margin: float = 5.0,
):
    """拼音加权模糊：options: [(key, label, pinyin, weight)]。

    得分 = max(字符相似度, 拼音相似度[含部分匹配])；weight 只参与排序，不改变阈值，
    避免“自信地填错”。同样要求 top1-top2 >= min_margin 才自动接受。
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
        # 精确匹配（100）→ 无歧义，直接接受
        if hits[0][0] >= 100.0:
            return "high", hits
        margin = hits[0][0] - (hits[1][0] if len(hits) > 1 else 0)
        if margin >= min_margin:
            return "high", hits
        return "mid", hits
    if hits:
        return "mid", hits
    return "low", []
