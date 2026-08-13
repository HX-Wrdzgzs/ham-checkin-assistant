"""365dt 同步服务：每次启动检查一次（由 UI/AppService 触发），增量导入 SQLite。

错误处理：网络/DNS/超时/改版都不阻塞启动，仅记录 sync_state 与日志。
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

    def sync_once(self, progress=None) -> dict:
        """同步一次，返回摘要。progress(done, total, msg)。"""
        now = datetime.now().isoformat(timespec="seconds")
        state = self.repo.get_sync_state(self.SOURCE) or SyncState(source=self.SOURCE)
        state.last_check_at = now
        try:
            ranking = self.provider.fetch_ranking()
        except Exception as e:  # noqa: BLE001
            state.status = "error"
            state.error_message = str(e)[:500]
            self.repo.set_sync_state(state)
            log.warning("365dt fetch ranking failed: %s", e)
            return {"ok": False, "message": f"365dt 同步失败：{e}"}

        names = {r.get("name") for r in ranking.get("list", [])}
        local = {s["callsign"] for s in self.repo.as_dict_rows(
            "SELECT callsign FROM stations WHERE callsign!=''")}
        first_sync = not state.last_success_at
        callsigns = self.provider.select_callsigns(ranking.get("list", []), local, first_sync)

        stats = self.provider.fetch_many_stats(callsigns, progress)
        inserted = 0
        skipped = 0
        session_cache: dict[str, int] = {}
        for data in stats:
            callsign = (data.get("callsign") or "").upper()
            for h in data.get("history", []):
                date, time = (h.get("date") or ""), (h.get("time") or "")
                src_id = self.repo.record_hash(self.SOURCE, self.provider.uid, callsign, date, time)
                if self.repo.checkin_exists_by_source_id(src_id):
                    skipped += 1
                    continue
                sid = self._session_for_date(date, session_cache)
                checkin = self._build_checkin(sid, callsign, h, src_id)
                checkin.sequence_no = self.repo.next_sequence(sid)
                self.repo.add_checkin(checkin)
                self.repo.update_profiles_from_checkin(checkin)
                self.repo.upsert_station_from_checkin(checkin)
                inserted += 1

        state.status = "ok"
        state.source_uid = self.provider.uid
        state.last_success_at = datetime.now().isoformat(timespec="seconds")
        state.error_message = ""
        state.last_hash = str(ranking.get("stats", ""))
        self.repo.set_sync_state(state)
        failed = list(getattr(self.provider, "failed", []))
        log.info("365dt sync ok: ranking=%s fetched=%d inserted=%d skipped=%d failed=%s",
                 ranking.get("stats"), len(stats), inserted, skipped, failed)
        return {
            "ok": True, "inserted": inserted, "skipped": skipped,
            "fetched": len(stats), "total": ranking.get("stats", 0),
            "failed": failed,
        }

    def _session_for_date(self, date: str, cache: dict) -> int:
        if date in cache:
            return cache[date]
        name = date or "未标注日期"
        session = self.repo.find_session_by_name(name)
        if session is None:
            session = self.repo.create_session(name=name, date=date, repeater_name="365dt历史")
        self.repo.end_session(session.id)  # 历史场次不作为“进行中”
        cache[date] = session.id
        return session.id

    def _build_checkin(self, session_id: int, callsign: str, h: dict, src_id: str) -> Checkin:
        date, time = h.get("date", ""), h.get("time", "")
        checkin_time = f"{date}T{time}" if date and time else (date or datetime.now().strftime("%Y-%m-%d"))
        address = h.get("address", "") or ""
        equip = h.get("equipment", "") or ""
        ant = h.get("antenna", "") or ""
        pwr = h.get("power", "") or ""
        c = Checkin(
            session_id=session_id, checkin_time=checkin_time,
            callsign=callsign,
            qth_raw=address, device_raw=equip, antenna_raw=ant, power_raw=pwr,
            signal=h.get("signal", "") or "",
            source=self.SOURCE, raw_input=f"{callsign} {equip} {pwr} {ant} {address}",
            source_record_id=src_id,
            source_url=f"https://api.365dt.net/dianming/user/ranking.asp?uid={self.provider.uid}",
        )
        c.qth_standard = self.standardizer.standardize("qth", address) or address
        c.device_standard = self.standardizer.standardize("device", equip) or equip
        c.antenna_standard = self.standardizer.standardize("antenna", ant) or ant
        c.power_standard = self.standardizer.standardize("power", pwr) or pwr
        return c
