"""NRL Nanny 只读监听（第四阶段）。

NRL Nanny 是网控实时点名记录页面。本模块只负责：
- 轮询抓取原始内容（raw 保留）
- 从原始内容中提取呼号候选
- 绝不写数据库、绝不自动提交签到（只提供候选给用户点选）

错误模型（供测试覆盖）：
- 超时 → requests.Timeout
- 连接重置 → requests.ConnectionError
- 非法响应（非文本/坏 JSON）→ 视为无效响应，返回错误标记
- 空活动 → 正常返回无候选
"""
from __future__ import annotations

import json
import re
import time

import requests

from normalizers.callsign import CALLSIGN_RE

# 呼号候选：标准呼号（含 / 后缀）
_CANDIDATE_RE = re.compile(
    r"(?<![A-Z0-9])[A-Z]{1,2}[0-9][A-Z0-9]{1,4}(?:/[A-Z0-9]{1,3})?(?![A-Z0-9])",
    re.IGNORECASE,
)


class NrlNannyProvider:
    """NRL Nanny 活动源。只读，无副作用。"""

    def __init__(self, url: str = "", timeout: float = 8.0) -> None:
        self.url = (url or "").strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ham-checkin-assistant/1.0"})
        # 最近活动（原始内容保留，环形缓冲）
        self.recent: list[dict] = []
        self.max_recent = 50

    # ---------- 抓取 ----------
    def fetch(self) -> dict:
        """抓取一次并解析。返回 {"ok": bool, "raw": str, "candidates": [...], "error": str}。

        网络错误抛 requests 异常（由服务层映射为 degraded/error 状态）。
        """
        if not self.url:
            return {"ok": False, "raw": "", "candidates": [],
                    "error": "未配置 NRL Nanny 地址"}
        resp = self.session.get(self.url, timeout=self.timeout)
        resp.raise_for_status()
        text = resp.text or ""
        candidates = self._extract_candidates(text)
        self._push(text, candidates)
        return {"ok": True, "raw": text, "candidates": candidates, "error": ""}

    # ---------- 解析 ----------
    def _extract_candidates(self, raw: str) -> list[str]:
        """从原始内容提取呼号候选（保序去重）。"""
        if not raw:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for m in _CANDIDATE_RE.finditer(raw):
            cs = m.group(0).upper().replace(" ", "")
            if CALLSIGN_RE.match(cs) and cs not in seen:
                seen.add(cs)
                out.append(cs)
        return out

    def _push(self, raw: str, candidates: list[str]) -> None:
        """保留最近活动（含原始内容）。"""
        self.recent.append({
            "time": time.strftime("%H:%M:%S"),
            "raw": raw,
            "candidates": candidates,
        })
        if len(self.recent) > self.max_recent:
            self.recent = self.recent[-self.max_recent:]

    def clear(self) -> None:
        self.recent = []


def parse_activity(raw: str) -> list[dict]:
    """把原始内容解析为结构化活动条目（尽量容忍未知格式）。

    兼容两类输入：
    - JSON（{"list":[{"callsign":..,"time":..}, ...]} 或数组）
    - 纯文本/HTML（逐行提取呼号与时间）
    返回 [{"time": str, "callsign": str, "raw": str}, ...]。
    """
    if not raw:
        return []
    entries: list[dict] = []
    # JSON 尝试
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        rows = data.get("list") or data.get("data") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = None
    if rows:
        for r in rows:
            if not isinstance(r, dict):
                continue
            cs = str(r.get("callsign", "") or "").upper().strip()
            if CALLSIGN_RE.match(cs):
                entries.append({"time": str(r.get("time", "") or ""),
                                "callsign": cs,
                                "raw": json.dumps(r, ensure_ascii=False)})
        return entries
    # 文本/HTML：按行提取呼号
    for line in (raw.splitlines() or [raw]):
        m = _CANDIDATE_RE.search(line or "")
        if m:
            cs = m.group(0).upper()
            if CALLSIGN_RE.match(cs):
                entries.append({"time": "", "callsign": cs, "raw": line.strip()})
    return entries
