"""回归测试：365dt 真增量契约（任务书第二阶段 #12~#20 / Test Stage 10）。

不访问真实服务器，用可控 Fake Provider 验证：
- 第二次无变化同步不再拉取
- 同一呼号 count 变化 → 拉取并插入新增历史（Day1 A / Day2 A+B）
- 部分失败 → partial + retry
- UID 切换隔离
- DB 级去重 / 同分钟多记录身份
- max_fetch 上限（不双倍）
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.db import connect
from database.models import Checkin
from database.repository import Repository
from database.seed import seed_default_aliases
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from services.standardizer import Standardizer
from services.sync_service import SyncService


def _env():
    tmp = Path(tempfile.mkdtemp())
    conn = connect(tmp / "sync.db")
    repo = Repository(conn)
    seed_default_aliases(repo)
    store = AliasStore(repo)
    region = RegionIndex("江苏")
    std = Standardizer(store, region)
    return conn, repo, std


def _h(date, time, console="", equip="", address="", signal="59"):
    return {"date": date, "time": time, "console": console, "equipment": equip,
            "address": address, "signal": signal}


class _Fake365:
    name = "365dt"

    def __init__(self, uid="UID_A", max_fetch=200, ranking=None, stats=None, fail=()):
        self.uid = uid
        self.max_fetch = max_fetch
        self._ranking = ranking or {}
        self._stats = stats or {}
        self._fail = set(fail)
        self.failed: list[str] = []
        self.fetched_callsigns: list[str] = []

    def fetch_ranking(self):
        return {"stats": len(self._ranking),
                "list": [{"name": k, "count": v} for k, v in self._ranking.items()]}

    def fetch_many_stats(self, callsigns, progress=None):
        self.fetched_callsigns = list(callsigns)
        self.failed = []
        out = []
        for cs in callsigns:
            if cs in self._fail:
                self.failed.append(cs)
                continue
            if cs in self._stats:
                out.append({"callsign": cs, "history": self._stats[cs]})
        return out


class TestIncrementalSync(unittest.TestCase):
    def test_initial_sync(self):
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")]})
            svc = SyncService(repo, prov, std)
            res = svc.sync_once()
            self.assertTrue(res["ok"])
            self.assertEqual(res["inserted"], 1)
            st = repo.get_source_station_state("365dt", "UID_A", "BA4XXX")
            self.assertEqual(st["ranking_count"], 1)
            self.assertEqual(st["status"], "ok")
        finally:
            conn.close()

    def test_second_no_change_sync_does_not_fetch(self):
        """count 未变化 → 第二次同步不拉取任何呼号（真增量核心）。"""
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")]})
            svc = SyncService(repo, prov, std)
            svc.sync_once()
            prov.fetched_callsigns = []
            res2 = svc.sync_once()
            self.assertTrue(res2["ok"])
            self.assertEqual(res2["inserted"], 0)
            self.assertEqual(prov.fetched_callsigns, [], "count 未变 → 不得重新拉取")
        finally:
            conn.close()

    def test_count_change_fetches_new_history(self):
        """Day1 BA4XXX history=A；Day2 count 变 → 拉取 A+B → 必须插入 B。"""
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")]})
            svc = SyncService(repo, prov, std)
            svc.sync_once()
            total1 = repo.as_dict_rows("SELECT COUNT(*) c FROM checkins")[0]["c"]
            # Day2：count 变 2，history 多一条 B
            prov._ranking = {"BA4XXX": 2}
            prov._stats = {"BA4XXX": [_h("2026-08-01", "20:00"),
                                      _h("2026-08-02", "20:00")]}
            res2 = svc.sync_once()
            self.assertTrue(res2["ok"])
            self.assertEqual(res2["inserted"], 1, "B 必须被插入")
            self.assertEqual(res2["skipped"], 1, "A 被去重跳过")
            total2 = repo.as_dict_rows("SELECT COUNT(*) c FROM checkins")[0]["c"]
            self.assertEqual(total2, total1 + 1)
        finally:
            conn.close()

    def test_partial_failure_marks_partial_and_retry(self):
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 2, "BG4TKI": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")],
                                   "BG4TKI": [_h("2026-08-01", "21:00")]},
                            fail=("BA4XXX",))
            svc = SyncService(repo, prov, std)
            res = svc.sync_once()
            self.assertTrue(res["ok"])
            self.assertTrue(res["partial"], "部分失败必须 partial")
            self.assertIn("BA4XXX", res["failed"])
            state = repo.get_sync_state("365dt")
            self.assertEqual(state.status, "partial")
            st = repo.get_source_station_state("365dt", "UID_A", "BA4XXX")
            self.assertEqual(st["status"], "failed", "失败呼号保留 retry 状态")
            # 下一次同步仍会重试失败呼号
            prov._fail = set()
            prov._stats["BA4XXX"] = [_h("2026-08-01", "20:00")]
            svc.sync_once()
            self.assertIn("BA4XXX", prov.fetched_callsigns, "失败呼号必须进入重试列表")
        finally:
            conn.close()

    def test_uid_switch_isolates_state(self):
        conn, repo, std = _env()
        try:
            prov = _Fake365(uid="UID_A", ranking={"BA4XXX": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")]})
            svc = SyncService(repo, prov, std)
            svc.sync_once()
            self.assertIsNotNone(repo.get_source_station_state("365dt", "UID_A", "BA4XXX"))
            # 切换 UID → 新命名空间，不得复用旧状态
            prov.uid = "UID_B"
            prov.fetched_callsigns = []
            svc.sync_once()
            self.assertEqual(prov.fetched_callsigns, ["BA4XXX"],
                             "UID 切换后必须重新同步（新命名空间）")
            self.assertIsNotNone(repo.get_source_station_state("365dt", "UID_B", "BA4XXX"))
        finally:
            conn.close()

    def test_record_dedupe_by_db(self):
        """同一记录重复出现 → DB UNIQUE 去重，不重复插入。"""
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 1},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00")]})
            svc = SyncService(repo, prov, std)
            svc.sync_once()
            # 人为再插同一条 → add_checkin_dedupe 返回 False
            c = Checkin(session_id=1, callsign="BA4XXX", source="365dt",
                        source_record_id=svc._record_id("UID_A", "BA4XXX",
                                                        _h("2026-08-01", "20:00")))
            self.assertFalse(repo.add_checkin_dedupe(c), "重复记录必须被 DB 拒绝")
        finally:
            conn.close()

    def test_same_minute_multiple_records(self):
        """同分钟多条记录（不同 console）→ 身份不同，都插入。"""
        conn, repo, std = _env()
        try:
            prov = _Fake365(ranking={"BA4XXX": 2},
                            stats={"BA4XXX": [_h("2026-08-01", "20:00", console="1"),
                                              _h("2026-08-01", "20:00", console="2")]})
            svc = SyncService(repo, prov, std)
            res = svc.sync_once()
            self.assertEqual(res["inserted"], 2, "同分钟不同 console 应算不同记录")
        finally:
            conn.close()

    def test_max_fetch_bounds_total(self):
        """单次拉取总量 <= max_fetch，不双倍。"""
        conn, repo, std = _env()
        try:
            ranking = {f"BG{i:04d}": 1 for i in range(500)}
            prov = _Fake365(max_fetch=200, ranking=ranking)
            svc = SyncService(repo, prov, std)
            svc.sync_once()
            self.assertLessEqual(len(prov.fetched_callsigns), 200,
                                 "单次拉取不得超过 max_fetch")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
