"""365dt 数据源（规格第 55~63 节）。

已探明的公开接口：
- 排行：GET /dianming/public/api/ranking.asp?uid=UID
  → {"stats": N, "list": [{"rank":1,"name":"BA4SAK","count":150}, ...]}
- 呼号详情：GET /dianming/public/api/getCallsignStats.asp?callsign=X&uid=UID
  → {"callsign":"...", "history":[{"date":"2026-08-07","time":"21:22",
       "equipment":"...","power":"5W","antenna":"...","address":"...",
       "signal":"59","console":"..."}, ...]}

约束：低频、低并发、有超时、有限重试、增量优先。首次同步有上限（可配置）。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from providers.base import DataProvider

API_BASE = "https://api.365dt.net/dianming"
UA = "ham-checkin-assistant/1.0 (local; contact: operator)"


class Dt365Provider(DataProvider):
    name = "365dt"

    def __init__(self, uid: str, max_fetch: int = 60,
                 concurrency: int = 5, timeout: int = 8) -> None:
        self.uid = uid
        self.max_fetch = max_fetch
        self.concurrency = concurrency
        self.timeout = timeout
        self.failed: list[str] = []  # 最近一次 fetch_many_stats 失败的呼号
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": f"{API_BASE}/user/ranking.asp?uid={uid}",
        })

    # ---------- DataProvider 接口 ----------
    def check_updates(self) -> dict:
        ranking = self.fetch_ranking()
        return {"has_new": bool(ranking.get("list")), "stats": ranking.get("stats", 0)}

    def fetch_records(self) -> list[dict]:
        return self.fetch_ranking().get("list", [])

    def normalize_record(self, raw: dict) -> dict:
        return raw

    # ---------- 抓取 ----------
    def fetch_ranking(self) -> dict:
        """GET ranking.asp，失败抛异常。"""
        resp = self.session.get(f"{API_BASE}/public/api/ranking.asp", params={"uid": self.uid},
                                timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_callsign_stats(self, callsign: str) -> dict | None:
        """GET getCallsignStats.asp；无数据返回 None，网络错误抛异常。"""
        resp = self.session.get(
            f"{API_BASE}/public/api/getCallsignStats.asp",
            params={"callsign": callsign, "uid": self.uid},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None
        if data.get("error") or not data.get("history"):
            return None
        return data

    def fetch_many_stats(self, callsigns: list[str], progress=None) -> list[dict]:
        """有界并发抓取多个呼号详情。progress(done, total, msg)。"""
        self.failed = []
        out: list[dict] = []
        total = len(callsigns)
        done = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futs = {ex.submit(self.fetch_callsign_stats, c): c for c in callsigns}
            for fut in as_completed(futs):
                callsign = futs[fut]
                done += 1
                try:
                    data = fut.result()
                    if data:
                        out.append(data)
                except requests.RequestException:
                    self.failed.append(callsign)  # 单点失败不阻塞整体，但记下可提示
                if progress:
                    progress(done, total, f"同步 {callsign} {done}/{total}")
        return out

    def select_callsigns(self, ranking_list: list[dict], local_callsigns: set[str],
                         first_sync: bool) -> list[str]:
        """选择需要拉取详情的呼号（增量 + 有上限）。"""
        names = [item.get("name", "") for item in ranking_list if item.get("name")]
        if first_sync:
            # 首次：排行靠前的（排名即按次数排序）+ 本地已知呼号
            pool = [c for c in names if c not in local_callsigns]
            pool = pool[: self.max_fetch]
            known = [c for c in local_callsigns if c in set(names)]
            pool.extend(known[: self.max_fetch])
        else:
            # 增量：仅排行里新增的呼号
            pool = [c for c in names if c not in local_callsigns][: self.max_fetch]
        # 去重保序
        seen = set()
        return [c for c in pool if not (c in seen or seen.add(c))]
