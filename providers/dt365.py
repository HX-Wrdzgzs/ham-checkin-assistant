"""365dt 数据源（规格第 55~63 节）。

已探明的公开接口：
- 排行：GET /dianming/public/api/ranking.asp?uid=UID
  → {"stats": N, "list": [{"rank":1,"name":"BA4SAK","count":150}, ...]}
- 呼号详情：GET /dianming/public/api/getCallsignStats.asp?callsign=X&uid=UID
  → {"callsign":"...", "history":[{"date":"2026-08-07","time":"21:22",
       "equipment":"...","power":"5W","antenna":"...","address":"...",
       "signal":"59","console":"..."}, ...]}

约束：低频、低并发、有超时、有限重试（max 3，指数退避，尊重 Retry-After）、增量优先。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from providers.base import DataProvider

API_BASE = "https://api.365dt.net/dianming"
UA = "ham-checkin-assistant/1.0 (local; contact: operator)"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class Dt365Provider(DataProvider):
    name = "365dt"

    def __init__(self, uid: str, max_fetch: int = 200,
                 concurrency: int = 5, timeout: int = 8,
                 retries: int = 3, retry_delay_base: float = 1.0) -> None:
        self.uid = uid
        self.max_fetch = max_fetch
        self.concurrency = concurrency
        self.timeout = timeout
        self.retries = retries
        self.retry_delay_base = retry_delay_base  # 测试可设为 0
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

    # ---------- 带重试的 GET（任务书第二阶段 #17） ----------
    def _get_with_retry(self, url: str, **params) -> requests.Response:
        """有限重试 + 指数退避 + 尊重 Retry-After。禁止无限重试。"""
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    ra = resp.headers.get("Retry-After")
                    delay = float(ra) if ra and ra.replace(".", "", 1).isdigit() else \
                        (self.retry_delay_base * (2 ** attempt))
                    time.sleep(delay)
                    continue
                if resp.status_code in RETRYABLE_STATUS:
                    time.sleep(self.retry_delay_base * (2 ** attempt))
                    continue
                resp.raise_for_status()
                return resp
            except requests.Timeout as e:
                last_exc = e
            except requests.ConnectionError as e:
                last_exc = e
            if attempt + 1 < self.retries:
                time.sleep(self.retry_delay_base * (2 ** attempt))
        raise last_exc or requests.ConnectionError(f"请求失败（重试 {self.retries} 次后放弃）: {url}")

    # ---------- 抓取 ----------
    def fetch_ranking(self) -> dict:
        """GET ranking.asp，失败抛异常。"""
        resp = self._get_with_retry(f"{API_BASE}/public/api/ranking.asp", uid=self.uid)
        return resp.json()

    def fetch_callsign_stats(self, callsign: str) -> dict | None:
        """GET getCallsignStats.asp；无数据返回 None，网络错误抛异常。"""
        resp = self._get_with_retry(
            f"{API_BASE}/public/api/getCallsignStats.asp",
            callsign=callsign, uid=self.uid)
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
                    self.failed.append(callsign)  # 单点失败不阻塞整体，但记下可 retry
                if progress:
                    progress(done, total, f"同步 {callsign} {done}/{total}")
        return out

    def select_callsigns(self, ranking_list: list[dict], local_callsigns: set[str],
                         first_sync: bool) -> list[str]:
        """选择需要拉取详情的呼号（增量 + 有上限，总量 <= max_fetch，不双倍）。

        新流程由 SyncService 基于 source_station_state 决策，此方法保留供兼容。
        """
        names = [item.get("name", "") for item in ranking_list if item.get("name")]
        new = [c for c in names if c not in local_callsigns]
        if first_sync:
            known = [c for c in local_callsigns if c in set(names)]
            pool = (new + known)[: self.max_fetch]
        else:
            pool = new[: self.max_fetch]
        seen = set()
        return [c for c in pool if not (c in seen or seen.add(c))]
