"""365dt 同步服务：真增量（任务书第二阶段 #12~#20）。

核心变化：
- 不再用「callsign not in local stations」判断是否需要同步。
- 基于 source_station_state（per-callsign）判断：count 变化 / 未同步 / 上次失败 → 拉取。
- 记录身份含 source_uid（UID 隔离），由 DB UNIQUE(source, source_record_id) 最终去重。
- 部分失败 → status=partial，失败呼号保留 retry 状态。
- 外部场次用稳定键（source+uid+date），绝不误结束用户同名场次。
- 单次拉取数量 <= max_fetch（不双倍）。
"""
from __future__ import annotations

from datetime import datetime

from core.logging_setup import get_logger
from database.models import Checkin, SyncState
from database.repository import Repository
from providers.dt365 import Dt365Provider
from services.standardizer import Standardizer

log = get_logger("sync")


class SyncService:
    SOURCE = "365dt"

    def __init__(self, repo: Repository, provider: Dt365Provider,
                 standardizer: Standardizer) -> None:
        self.repo = repo
        self.provider = provider
        self.standardizer = standardizer
        self.max_fetch = int(getattr(provider, "max_fetch", 60) or 60)

    def sync_once(self, progress=None) -> dict:
        """同步一次。返回 {ok, inserted, skipped, fetched, total, failed, partial, message}。"""
        source = self.SOURCE
        uid = self.provider.uid
        now = datetime.now().isoformat(timespec="seconds")
        state = self.repo.get_sync_state(source, uid) or SyncState(source=source, source_uid=uid)
        state.last_check_at = now
        state.source_uid = uid
        try:
            ranking = self.provider.fetch_ranking()
        except Exception as e:  # noqa: BLE001
            state.status = "error"
            state.error_message = str(e)[:500]
            self.repo.set_sync_state(state)
            log.warning("365dt fetch ranking failed: %s", e)
            return {"ok": False, "message": f"365dt 同步失败：{e}"}

        ranking_map = {str(item.get("name", "")).upper(): int(item.get("count", 0) or 0)
                       for item in ranking.get("list", []) if item.get("name")}
        first_sync = not state.last_success_at

        callsigns = self._select_incremental(ranking_map, uid, first_sync)
        if not callsigns:
            state.status = "ok"
            state.source_uid = uid
            state.last_success_at = now
            state.last_hash = str(ranking.get("stats", ""))
            state.error_message = ""
            self.repo.set_sync_state(state)
            return {"ok": True, "inserted": 0, "skipped": 0, "fetched": 0,
                    "total": ranking.get("stats", 0), "failed": [], "partial": False}

        stats = self.provider.fetch_many_stats(callsigns, progress)
        failed = list(getattr(self.provider, "failed", []))
        inserted = skipped = 0
        affected_callsigns: set[str] = set()
        for data in stats:
            callsign = (data.get("callsign") or "").upper()
            last_key = ""
            for h in data.get("history", []):
                src_id = self._record_id(uid, callsign, h)
                if not src_id:
                    continue
                last_key = self._history_key(h)
                checkin = self._build_checkin(callsign, h, src_id, uid)
                if self.repo.add_checkin_dedupe(checkin):
                    inserted += 1
                    affected_callsigns.add(callsign)
                else:
                    skipped += 1
            # 成功获取的呼号更新状态
            self.repo.upsert_source_station_state(
                source, uid, callsign,
                ranking_count=ranking_map.get(callsign, 0),
                last_history_key=last_key, last_seen_at=now, last_fetch_at=now,
                status="ok")
        # 重建受影响的 station/profile 投影（checkins 为唯一事实源）
        for cs in affected_callsigns:
            self.repo.rebuild_station(cs)
            self.repo.rebuild_profiles_for(cs)

        # 失败呼号保留 retry 状态（任务书第二阶段 #16/#17）
        for cs in failed:
            self.repo.upsert_source_station_state(
                source, uid, cs.upper(), ranking_count=ranking_map.get(cs.upper(), 0),
                last_fetch_at=now, status="failed", error_message="fetch failed")

        partial = bool(failed)
        state.status = "partial" if partial else "ok"
        state.source_uid = uid
        state.last_success_at = now
        state.last_hash = str(ranking.get("stats", ""))
        state.error_message = "" if not partial else f"{len(failed)} 个呼号失败"
        self.repo.set_sync_state(state)
        log.info("365dt sync: ranking=%s fetched=%d inserted=%d skipped=%d failed=%s partial=%s",
                 ranking.get("stats"), len(stats), inserted, skipped, failed, partial)
        return {"ok": True, "inserted": inserted, "skipped": skipped,
                "fetched": len(stats), "total": ranking.get("stats", 0),
                "failed": failed, "partial": partial}

    # ---------- 真增量选择（任务书第二阶段 #12/#13/#19） ----------
    def _select_incremental(self, ranking_map: dict, uid: str, first_sync: bool) -> list[str]:
        """基于 per-callsign 状态选择：count 变化 / 未同步 / 上次失败 → 拉取。

        单次总量 <= max_fetch（不双倍，任务书第二阶段 #19）。
        """
        states = self.repo.source_station_states(self.SOURCE, uid)
        needed: list[str] = []
        for cs, count in ranking_map.items():
            st = states.get(cs)
            if st is None:
                needed.append(cs)              # 未同步
            elif st["status"] == "failed":
                needed.append(cs)              # 上次失败 → retry
            elif int(st["ranking_count"] or 0) != int(count):
                needed.append(cs)              # count 变化 → 拉取新增历史
        return needed[: self.max_fetch]

    # ---------- 记录身份（任务书第二阶段 #15/#14） ----------
    def _record_id(self, uid: str, callsign: str, h: dict) -> str:
        """稳定身份：source + source_uid + callsign + date + time + console + equipment + address + signal。"""
        return self.repo.record_hash(
            self.SOURCE, uid, callsign,
            h.get("date", "") or "", h.get("time", "") or "",
            h.get("console", "") or "", h.get("equipment", "") or "",
            h.get("address", "") or "", h.get("signal", "") or "")

    @staticmethod
    def _history_key(h: dict) -> str:
        return "|".join([h.get("date", "") or "", h.get("time", "") or "",
                         h.get("console", "") or ""])

    # ---------- 场次与记录 ----------
    def _session_for_date(self, date: str, uid: str) -> int:
        """用稳定外部键找/建场次，绝不误结束用户同名场次（任务书第二阶段 #20）。"""
        name = date or "未标注日期"
        session = self.repo.find_or_create_external_session(
            self.SOURCE, uid, date or name, name, date)
        return session.id

    def _build_checkin(self, callsign: str, h: dict, src_id: str, uid: str) -> Checkin:
        from core.datetime_util import normalize_checkin_time

        date, time = h.get("date", ""), h.get("time", "")
        # 任务书第三阶段 #6：统一 YYYY-MM-DDTHH:MM:SS
        checkin_time = normalize_checkin_time(date, time)
        address = h.get("address", "") or ""
        equip = h.get("equipment", "") or ""
        ant = h.get("antenna", "") or ""
        pwr = h.get("power", "") or ""
        c = Checkin(
            session_id=self._session_for_date(date, uid),
            checkin_time=checkin_time,
            callsign=callsign,
            qth_raw=address, device_raw=equip, antenna_raw=ant, power_raw=pwr,
            signal=h.get("signal", "") or "",
            source=self.SOURCE, raw_input=f"{callsign} {equip} {pwr} {ant} {address}",
            source_record_id=src_id,
            source_url=f"https://api.365dt.net/dianming/user/ranking.asp?uid={uid}",
        )
        c.qth_standard = self.standardizer.standardize("qth", address) or address
        c.device_standard = self.standardizer.standardize("device", equip) or equip
        c.antenna_standard = self.standardizer.standardize("antenna", ant) or ant
        c.power_standard = self.standardizer.standardize("power", pwr) or pwr
        return c

