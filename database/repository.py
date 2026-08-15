"""数据访问层：所有 SQL 都集中在这里，UI/Service 不直接执行 SQL。"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime
from typing import Iterable

from database.models import (
    Alias, AuditEntry, Checkin, RawImport, Session, StationProfile, SyncState,
)

TABLE_ALIAS = {
    "qth": "qth_aliases",
    "device": "device_aliases",
    "antenna": "antenna_aliases",
    "power": "power_aliases",
}

# 被改过的旧默认值（用于把旧版误标为 user 的内置别名安全升级）
LEGACY_DEFAULTS = {
    ("antenna", "771"): "771",
    ("antenna", "518"): "518",
}

_FIELD_MAP = {
    "qth": "qth_standard",
    "device": "device_standard",
    "antenna": "antenna_standard",
    "power": "power_standard",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        # 进程内序列分配锁：多线程并发提交时避免读到同一序号（数据库 UNIQUE 索引兜底）。
        self._alloc_lock = threading.Lock()

    # ---------- sessions ----------
    def create_session(self, name: str, date: str, operator_callsign: str = "",
                       repeater_name: str = "", excel_path: str = "",
                       excel_sheet_name: str = "") -> Session:
        ts = now_iso()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO sessions(name, date, operator_callsign, repeater_name,
                   started_at, excel_path, excel_sheet_name, status, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?, 'active', ?, ?)""",
                (name, date, operator_callsign, repeater_name, ts, excel_path,
                 excel_sheet_name, ts, ts),
            )
        return self.get_session(cur.lastrowid)

    def get_session(self, session_id: int) -> Session | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self, limit: int = 200, local_only: bool = False) -> list[Session]:
        where = " WHERE external_source IS NULL OR TRIM(external_source)=''" if local_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM sessions{where} ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._session_from_row(r) for r in rows]

    def find_session_by_name(self, name: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        return self._session_from_row(row) if row else None

    def find_session_by_external(self, source: str, uid: str, external_key: str) -> Session | None:
        """按稳定外部键找场次（任务书第二阶段 #20：避免结束用户同名场次）。"""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE external_source=? AND external_uid=? AND external_key=? "
            "ORDER BY id DESC LIMIT 1",
            (source, uid, external_key),
        ).fetchone()
        return self._session_from_row(row) if row else None

    def find_or_create_external_session(self, source: str, uid: str, external_key: str,
                                        name: str, date: str) -> Session:
        """按外部键查找，找不到则创建并结束（历史场次不作为进行中）。"""
        s = self.find_session_by_external(source, uid, external_key)
        if s is not None:
            return s
        ts = now_iso()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO sessions(name, date, started_at, status,
                   external_source, external_uid, external_key, created_at, updated_at)
                   VALUES(?,?,?,'active',?,?,?,?,?)""",
                (name, date, ts, source, uid, external_key, ts, ts),
            )
            self.conn.execute(
                "UPDATE sessions SET status='ended', ended_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), cur.lastrowid),
            )
        return self.get_session(cur.lastrowid)

    def active_sessions(self, local_only: bool = False) -> list[Session]:
        where = " AND (external_source IS NULL OR TRIM(external_source)='')" if local_only else ""
        rows = self.conn.execute(
            f"SELECT * FROM sessions WHERE status='active'{where} ORDER BY id"
        ).fetchall()
        return [self._session_from_row(r) for r in rows]

    def end_session(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET status='ended', ended_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), session_id),
            )

    def update_session(self, session_id: int, **fields) -> None:
        if not fields:
            return
        keys = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE sessions SET {keys}, updated_at=? WHERE id=?",
                (*fields.values(), now_iso(), session_id),
            )

    @staticmethod
    def _session_from_row(row) -> Session:
        return Session(**{k: row[k] for k in row.keys()})

    # ---------- checkins ----------
    def next_sequence(self, session_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(sequence_no),0) m FROM checkins WHERE session_id=? AND is_deleted=0",
            (session_id,),
        ).fetchone()
        return int(row["m"]) + 1

    def allocate_sequence(self, session_id: int) -> int:
        """线程安全地分配下一序号（任务书第一阶段 #3：并发不产生重复序号）。"""
        with self._alloc_lock:
            return self.next_sequence(session_id)

    def add_checkin_with_seq(self, session_id: int, c: Checkin) -> Checkin:
        """分配序号并插入，进程内原子；数据库 UNIQUE(session_id, sequence_no) 兜底。"""
        with self._alloc_lock:
            c.sequence_no = self.next_sequence(session_id)
            return self.add_checkin(c)

    def add_checkin(self, c: Checkin) -> Checkin:
        ts = now_iso()
        c.created_at = ts
        c.updated_at = ts
        if not c.checkin_time:
            c.checkin_time = ts
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO checkins(session_id, sequence_no, checkin_time, callsign,
                   qth_raw, qth_standard, device_raw, device_standard,
                   antenna_raw, antenna_standard, power_raw, power_standard,
                   signal, source, raw_input, source_record_id, source_url, unmatched,
                   is_deleted, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (c.session_id, c.sequence_no, c.checkin_time, c.callsign,
                 c.qth_raw, c.qth_standard, c.device_raw, c.device_standard,
                 c.antenna_raw, c.antenna_standard, c.power_raw, c.power_standard,
                 c.signal, c.source, c.raw_input, c.source_record_id, c.source_url,
                 c.unmatched,
                 c.created_at, c.updated_at),
            )
            c.id = cur.lastrowid
        return c

    def get_checkin(self, checkin_id: int) -> Checkin | None:
        row = self.conn.execute("SELECT * FROM checkins WHERE id=?", (checkin_id,)).fetchone()
        return self._checkin_from_row(row) if row else None

    def list_checkins(self, session_id: int, include_deleted: bool = False) -> list[Checkin]:
        sql = "SELECT * FROM checkins WHERE session_id=?"
        if not include_deleted:
            sql += " AND is_deleted=0"
        sql += " ORDER BY sequence_no"
        rows = self.conn.execute(sql, (session_id,)).fetchall()
        return [self._checkin_from_row(r) for r in rows]

    def last_checkin(self, session_id: int) -> Checkin | None:
        row = self.conn.execute(
            "SELECT * FROM checkins WHERE session_id=? AND is_deleted=0 "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return self._checkin_from_row(row) if row else None

    def duplicate_in_session(self, session_id: int, callsign: str) -> Checkin | None:
        if not callsign:
            return None
        row = self.conn.execute(
            "SELECT * FROM checkins WHERE session_id=? AND callsign=? AND is_deleted=0 "
            "ORDER BY id DESC LIMIT 1",
            (session_id, callsign),
        ).fetchone()
        return self._checkin_from_row(row) if row else None

    def checkin_exists_by_source_id(self, source_record_id: str) -> bool:
        if not source_record_id:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM checkins WHERE source_record_id=? LIMIT 1", (source_record_id,)
        ).fetchone()
        return row is not None

    def add_checkin_dedupe(self, c: Checkin) -> bool:
        """按 UNIQUE(source, source_record_id) 去重（P2：只把 source_record 冲突当重复）。

        - 先确认是否已有同 (source, source_record_id) 的有效记录 → 是则重复（False）。
        - 否则插入；非 source_record 的 IntegrityError（如序列）必须上抛，不误判为重复。
        """
        if c.source_record_id:
            dup = self.conn.execute(
                "SELECT 1 FROM checkins WHERE source=? AND source_record_id=? AND is_deleted=0 "
                "LIMIT 1",
                (c.source, c.source_record_id),
            ).fetchone()
            if dup:
                return False
        with self._alloc_lock:
            c.sequence_no = self.next_sequence(c.session_id)
            self.add_checkin(c)
        return True

    def _is_source_record_dup(self, c: Checkin) -> bool:
        """是否已有同 (source, source_record_id) 的有效记录（P2 精确去重）。"""
        if not c.source_record_id:
            return False
        return self.conn.execute(
            "SELECT 1 FROM checkins WHERE source=? AND source_record_id=? AND is_deleted=0 "
            "LIMIT 1",
            (c.source, c.source_record_id),
        ).fetchone() is not None

    def soft_delete_checkin(self, checkin_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET is_deleted=1, deleted_at=?, updated_at=? WHERE id=?",
                (now_iso(), now_iso(), checkin_id),
            )

    def update_checkin(self, checkin_id: int, **fields) -> None:
        if not fields:
            return
        keys = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE checkins SET {keys}, updated_at=? WHERE id=?",
                (*fields.values(), now_iso(), checkin_id),
            )

    # ---------- Excel 同步跟踪（任务书第一阶段 #9/#10 状态机） ----------
    # 状态：pending / written / persisted / verified / conflict / error
    # conflict 也必须能被“保存/补同步”重新处理；否则一次行身份冲突后，
    # 记录会永久脱离重试队列，用户只能靠整场重写才能恢复。
    _UNSYNCED_STATES = ("pending", "written", "error", "conflict")

    def set_excel_state(self, checkin_id: int, status: str, row: int | None = None,
                        error: str = "", synced_at: str = "", binding_id: str = "") -> None:
        """更新单条记录的 Excel 同步状态。"""
        with self.conn:
            sql = ("UPDATE checkins SET excel_sync_status=?, excel_last_error=?, "
                   "excel_synced_at=COALESCE(?, excel_synced_at)")
            params: list = [status, error]
            if synced_at:
                params.append(synced_at)
            else:
                params.append(None)
            if row is not None:
                sql += ", excel_row=?"
                params.append(row)
            if binding_id:
                sql += ", excel_binding_id=?"
                params.append(binding_id)
            if status == "persisted" or status == "verified":
                sql += ", excel_synced=1"
            else:
                sql += ", excel_synced=0"
            sql += " WHERE id=?"
            params.append(checkin_id)
            self.conn.execute(sql, tuple(params))

    def set_excel_states_atomic(self, states: list[dict]) -> None:
        """单事务批量更新 Excel 同步状态（P1-7：excel_sync_missing 一次 commit）。

        states: [{"checkin_id", "status", "row", "error"}]；未 Save 永远不进 persisted/verified。
        """
        with self.conn:
            for s in states:
                cid = s["checkin_id"]
                status = s.get("status", "error")
                row = s.get("row")
                error = s.get("error", "")
                synced = 1 if status in ("persisted", "verified") else 0
                synced_at = now_iso() if synced else None
                self.conn.execute(
                    """UPDATE checkins SET excel_sync_status=?, excel_last_error=?,
                       excel_synced_at=COALESCE(?, excel_synced_at),
                       excel_row=COALESCE(?, excel_row),
                       excel_synced=? WHERE id=?""",
                    (status, error, synced_at, row, synced, cid),
                )

    def mark_excel_synced(self, checkin_id: int, excel_row: int | None = None) -> None:
        """兼容旧接口：标记为 verified。"""
        self.set_excel_state(checkin_id, "verified", row=excel_row,
                             synced_at=now_iso())

    def list_unsynced(self, session_id: int) -> list[Checkin]:
        placeholders = ",".join("?" * len(self._UNSYNCED_STATES))
        rows = self.conn.execute(
            "SELECT * FROM checkins WHERE session_id=? AND is_deleted=0 "
            f"AND excel_sync_status IN ({placeholders}) ORDER BY sequence_no",
            (session_id, *self._UNSYNCED_STATES),
        ).fetchall()
        return [self._checkin_from_row(r) for r in rows]

    def reset_excel_sync(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET excel_sync_status='pending', excel_row=NULL, "
                "excel_last_error='' WHERE session_id=? AND is_deleted=0",
                (session_id,))

    def mark_all_excel_synced(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET excel_sync_status='verified', excel_synced=1, "
                "excel_synced_at=? WHERE session_id=? AND is_deleted=0",
                (now_iso(), session_id))

    @staticmethod
    def _checkin_from_row(row) -> Checkin:
        return Checkin(**{k: row[k] for k in row.keys()})

    # ---------- stations / profiles ----------
    def _upsert_station_from_checkin(self, c: Checkin) -> None:
        """（已废弃，改用 rebuild_station）根据一条签到记录更新呼号概要。"""
        if not c.callsign:
            return
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """INSERT INTO stations(callsign, first_seen, last_seen, checkin_count,
                   last_qth, last_device, last_antenna, last_power, created_at, updated_at)
                   VALUES(?,?,?,1,?,?,?,?,?,?)
                   ON CONFLICT(callsign) DO UPDATE SET
                     last_seen=excluded.last_seen,
                     checkin_count=checkin_count+1,
                     last_qth=excluded.last_qth,
                     last_device=excluded.last_device,
                     last_antenna=excluded.last_antenna,
                     last_power=excluded.last_power,
                     updated_at=excluded.updated_at""",
                (c.callsign, c.checkin_time, c.checkin_time,
                 c.qth_standard, c.device_standard, c.antenna_standard, c.power_standard,
                 now, now),
            )

    def get_station(self, callsign: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM stations WHERE callsign=?", (callsign,)).fetchone()
        return dict(row) if row else None

    def search_stations(self, keyword: str, limit: int = 100) -> list[dict]:
        kw = f"%{keyword}%"
        rows = self.conn.execute(
            "SELECT * FROM stations WHERE callsign LIKE ? ORDER BY checkin_count DESC LIMIT ?",
            (kw, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- station/profile 投影重建（任务书第一阶段 #15/#16/#17） ----------
    # checkins 是唯一事实源；stations / station_profiles 只是投影/cache，
    # 编辑/撤销/导入/改呼号后调用 rebuild_* 保持一致性，绝不手工 count+1。

    def rebuild_station(self, callsign: str) -> None:
        """按 checkins（时间序）重建单个呼号的 station 投影。幂等。"""
        if not callsign:
            return
        callsign = callsign.upper()
        with self.conn:
            row = self.conn.execute(
                """SELECT MIN(checkin_time) AS first_seen,
                          MAX(checkin_time) AS last_seen, COUNT(*) AS n
                   FROM checkins WHERE callsign=? AND is_deleted=0""",
                (callsign,),
            ).fetchone()
            n = int(row["n"] or 0)
            if n == 0:
                self.conn.execute("DELETE FROM stations WHERE callsign=?", (callsign,))
                return
            latest = self.conn.execute(
                """SELECT qth_standard, device_standard, antenna_standard, power_standard
                   FROM checkins WHERE callsign=? AND is_deleted=0
                   ORDER BY checkin_time DESC, id DESC LIMIT 1""",
                (callsign,),
            ).fetchone()
            now = now_iso()
            self.conn.execute(
                """INSERT INTO stations(callsign, first_seen, last_seen, checkin_count,
                   last_qth, last_device, last_antenna, last_power, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(callsign) DO UPDATE SET
                     first_seen=excluded.first_seen,
                     last_seen=excluded.last_seen,
                     checkin_count=excluded.checkin_count,
                     last_qth=excluded.last_qth,
                     last_device=excluded.last_device,
                     last_antenna=excluded.last_antenna,
                     last_power=excluded.last_power,
                     updated_at=excluded.updated_at""",
                (callsign, row["first_seen"], row["last_seen"], n,
                 latest["qth_standard"], latest["device_standard"],
                 latest["antenna_standard"], latest["power_standard"], now, now),
            )

    def rebuild_all_stations(self) -> int:
        with self.conn:
            calls = [r["callsign"] for r in self.conn.execute(
                "SELECT DISTINCT callsign FROM checkins WHERE is_deleted=0 AND callsign!=''")]
        for cs in calls:
            self.rebuild_station(cs)
        return len(calls)

    def rebuild_profiles_for(self, callsign: str) -> None:
        """按 checkins 重建单个呼号的画像投影。幂等。"""
        if not callsign:
            return
        callsign = callsign.upper()
        with self.conn:
            self.conn.execute(
                "DELETE FROM station_profiles WHERE callsign=?", (callsign,))
            rows = self.conn.execute(
                """SELECT qth_standard, device_standard, antenna_standard, power_standard,
                          checkin_time
                   FROM checkins WHERE callsign=? AND is_deleted=0 ORDER BY checkin_time""",
                (callsign,),
            ).fetchall()
            for r in rows:
                for ft in ("qth", "device", "antenna", "power"):
                    v = r[f"{ft}_standard"]
                    if v:
                        self.conn.execute(
                            """INSERT INTO station_profiles(callsign, field_type, field_value,
                               use_count, last_used) VALUES(?,?,?,1,?)
                               ON CONFLICT(callsign, field_type, field_value) DO UPDATE SET
                                 use_count=use_count+1,
                                 last_used=CASE WHEN ? > last_used THEN ? ELSE last_used END""",
                            (callsign, ft, v, r["checkin_time"], r["checkin_time"], r["checkin_time"]),
                        )

    def rebuild_all_profiles(self) -> int:
        with self.conn:
            calls = [r["callsign"] for r in self.conn.execute(
                "SELECT DISTINCT callsign FROM checkins WHERE is_deleted=0 AND callsign!=''")]
        for cs in calls:
            self.rebuild_profiles_for(cs)
        return len(calls)


    def _bump_profile(self, callsign: str, field_type: str, field_value: str) -> None:
        if not callsign or not field_type or not field_value:
            return
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """INSERT INTO station_profiles(callsign, field_type, field_value, use_count, last_used)
                   VALUES(?,?,?,1,?)
                   ON CONFLICT(callsign, field_type, field_value) DO UPDATE SET
                     use_count=use_count+1, last_used=excluded.last_used""",
                (callsign, field_type, field_value, now),
            )

    def _update_profiles_from_checkin(self, c: Checkin) -> None:
        for ft in ("qth", "device", "antenna", "power"):
            val = getattr(c, f"{ft}_standard")
            self._bump_profile(c.callsign, ft, val)

    def profiles_for(self, callsign: str, field_type: str, limit: int = 5) -> list[StationProfile]:
        rows = self.conn.execute(
            """SELECT * FROM station_profiles WHERE callsign=? AND field_type=?
               ORDER BY use_count DESC LIMIT ?""",
            (callsign, field_type, limit),
        ).fetchall()
        return [StationProfile(**{k: r[k] for k in r.keys()}) for r in rows]

    def refresh_station_profiles_for(self, callsign: str) -> None:
        """重算单个呼号的画像（修改记录后保持画像一致）。"""
        with self.conn:
            self.conn.execute(
                "DELETE FROM station_profiles WHERE callsign=?", (callsign,))
            rows = self.conn.execute(
                "SELECT qth_standard, device_standard, antenna_standard, power_standard, "
                "checkin_time FROM checkins WHERE callsign=? AND is_deleted=0",
                (callsign,),
            ).fetchall()
            for r in rows:
                for ft in ("qth_standard", "device_standard", "antenna_standard", "power_standard"):
                    v = r[ft]
                    if v:
                        self.conn.execute(
                            """INSERT INTO station_profiles(callsign, field_type, field_value, use_count, last_used)
                               VALUES(?,?,?,1,?)
                               ON CONFLICT(callsign, field_type, field_value) DO UPDATE SET
                                 use_count=use_count+1,
                                 last_used=CASE WHEN ? > last_used THEN ? ELSE last_used END""",
                            (callsign, ft[:-9], v, r["checkin_time"], r["checkin_time"], r["checkin_time"]),
                        )

    def rebuild_profiles(self) -> int:
        """重新计算所有呼号画像。"""
        with self.conn:
            self.conn.execute("DELETE FROM station_profiles")
            rows = self.conn.execute(
                "SELECT callsign, qth_standard, device_standard, antenna_standard, power_standard, "
                "checkin_time FROM checkins WHERE is_deleted=0 AND callsign!=''"
            ).fetchall()
        with self.conn:
            for r in rows:
                for ft in ("qth_standard", "device_standard", "antenna_standard", "power_standard"):
                    v = r[ft]
                    if v:
                        self.conn.execute(
                            """INSERT INTO station_profiles(callsign, field_type, field_value, use_count, last_used)
                               VALUES(?,?,?,1,?)
                               ON CONFLICT(callsign, field_type, field_value) DO UPDATE SET
                                 use_count=use_count+1,
                                 last_used=CASE WHEN ? > last_used THEN ? ELSE last_used END""",
                            (r["callsign"], ft[:-9], v, r["checkin_time"], r["checkin_time"], r["checkin_time"]),
                        )
        return len(rows)

    def station_history(self, callsign: str, limit: int = 50) -> list[Checkin]:
        rows = self.conn.execute(
            "SELECT * FROM checkins WHERE callsign=? AND is_deleted=0 "
            "ORDER BY checkin_time DESC LIMIT ?",
            (callsign, limit),
        ).fetchall()
        return [self._checkin_from_row(r) for r in rows]

    def recent_history(self, callsign: str) -> Checkin | None:
        """最近一次非本地录入也可能算，但优先看实际签到；这里按时间最新。"""
        row = self.conn.execute(
            "SELECT * FROM checkins WHERE callsign=? AND is_deleted=0 "
            "ORDER BY checkin_time DESC LIMIT 1",
            (callsign,),
        ).fetchone()
        return self._checkin_from_row(row) if row else None

    # ---------- aliases ----------
    def get_aliases(self, kind: str, enabled_only: bool = True) -> list[Alias]:
        table = TABLE_ALIAS[kind]
        sql = f"SELECT * FROM {table}"
        if enabled_only:
            sql += " WHERE enabled=1"
        rows = self.conn.execute(sql).fetchall()
        out = []
        for r in rows:
            a = Alias(id=r["id"], alias=(r["alias"] or "").strip().lower(),
                      standard_value=r["standard_value"], priority=r["priority"],
                      enabled=r["enabled"], source=r["source"])
            for k in ("province", "city", "district"):
                if k in r.keys():
                    setattr(a, k, r[k])
            out.append(a)
        return out

    def set_alias(self, kind: str, alias: str, standard_value: str, **extra) -> None:
        table = TABLE_ALIAS[kind]
        alias = alias.strip().lower()
        standard_value = standard_value.strip()
        if not alias or not standard_value:
            return
        with self.conn:
            cur = self.conn.execute(
                f"SELECT id FROM {table} WHERE alias=?", (alias,)
            ).fetchone()
            if cur:
                self.conn.execute(
                    f"UPDATE {table} SET standard_value=?, priority=?, source=? WHERE id=?",
                    (standard_value, extra.get("priority", 100), "user", cur["id"]),
                )
            else:
                cols = "alias, standard_value, priority, source"
                vals = (alias, standard_value, extra.get("priority", 100), "user")
                if kind == "qth":
                    cols = "alias, province, city, district, standard_value, priority, source"
                    vals = (alias, extra.get("province", ""), extra.get("city", ""),
                            extra.get("district", ""), standard_value,
                            extra.get("priority", 100), "user")
                self.conn.execute(
                    f"INSERT INTO {table}({cols}) VALUES({','.join('?' * len(vals))})", vals,
                )

    def delete_alias(self, kind: str, alias: str) -> None:
        table = TABLE_ALIAS[kind]
        with self.conn:
            self.conn.execute(f"DELETE FROM {table} WHERE alias=?", (alias.strip().lower(),))

    def upsert_default_alias(self, kind: str, alias: str, standard_value: str, **extra) -> None:
        """内置默认别名随版本更新：缺失则插入(source=default)。

        - source='default'：直接更新为标准值（版本升级）。
        - source='user' 且存的是旧默认值：升级为当前默认（迁移旧库，不覆盖真实用户修改）。
        - source='user' 且存的是别的内容：视为用户自定义，不动。
        """
        table = TABLE_ALIAS[kind]
        alias = alias.strip().lower()
        standard_value = standard_value.strip()
        if not alias or not standard_value:
            return
        row = self.conn.execute(
            f"SELECT id, source, standard_value FROM {table} WHERE alias=?",
            (alias,)).fetchone()
        with self.conn:
            if row is None:
                if kind == "qth":
                    self.conn.execute(
                        f"INSERT INTO {table}(alias, province, city, district, standard_value, priority, source) "
                        f"VALUES(?,?,?,?,?,?, 'default')",
                        (alias, extra.get("province", ""), extra.get("city", ""),
                         extra.get("district", ""), standard_value,
                         extra.get("priority", 100)))
                else:
                    self.conn.execute(
                        f"INSERT INTO {table}(alias, standard_value, priority, source) "
                        f"VALUES(?,?,?, 'default')",
                        (alias, standard_value, extra.get("priority", 100)))
                return
            if row["source"] == "default":
                self.conn.execute(
                    f"UPDATE {table} SET standard_value=? WHERE id=?", (standard_value, row["id"]))
            else:  # source='user'：仅当存的是旧默认值才升级
                legacy = LEGACY_DEFAULTS.get((kind, alias), standard_value)
                if (row["standard_value"] or "").strip().lower() == legacy.strip().lower():
                    self.conn.execute(
                        f"UPDATE {table} SET standard_value=?, source='default' WHERE id=?",
                        (standard_value, row["id"]))

    def alias_count(self, kind: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) c FROM {TABLE_ALIAS[kind]}").fetchone()["c"]

    # ---------- raw imports / dedup ----------
    @staticmethod
    def file_hash(path: str) -> str:
        """文件指纹 = 文件名 + 内容（P0-3：同名内容文件不同名不得误判已导入）。

        日期常编码在文件名里（2026-08-08.xlsx），内容可能完全相同；
        仅哈希内容会让不同日期文件被当成同一文件跳过。
        """
        h = hashlib.sha256()
        h.update(str(path).encode("utf-8"))
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def record_hash(*parts: str) -> str:
        return hashlib.sha256("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()

    def raw_import_exists(self, source: str, file_hash: str, sheet: str, row: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM raw_imports WHERE source=? AND source_file=? AND sheet_name=? AND row_number=?",
            (source, file_hash, sheet, row),
        ).fetchone()
        return row is not None

    def file_imported(self, source: str, file_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM raw_imports WHERE source=? AND source_file=? LIMIT 1",
            (source, file_hash),
        ).fetchone()
        return row is not None

    # ---------- 导入 job 状态（任务书第三阶段 #2） ----------
    def import_job_completed(self, source: str, file_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM import_jobs WHERE source=? AND source_file=? AND status='completed'",
            (source, file_hash),
        ).fetchone()
        return row is not None

    def mark_import_job(self, source: str, file_hash: str, status: str,
                        imported_count: int = 0, error: str = "") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO import_jobs(source, source_file, status, imported_count,
                   error_message, updated_at) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(source, source_file) DO UPDATE SET
                     status=excluded.status,
                     imported_count=excluded.imported_count,
                     error_message=excluded.error_message,
                     updated_at=excluded.updated_at""",
                (source, file_hash, status, imported_count, error, now_iso()),
            )

    def import_records_atomic(self, session_id: int, raw_imports: list[RawImport],
                              checkins: list[Checkin]) -> tuple[int, int]:
        """单事务导入：raw_imports + checkins 原子写入（任务书第三阶段 #1）。

        - source_record 重复 → 逐条跳过（DB 负责跨文件去重）。
        - 任意非去重异常 → 整个事务回滚，0 half-import。
        - 序列在分配锁内分配，避免并发重复。
        """
        imported = skipped = 0
        with self._alloc_lock:
            with self.conn:
                for r in raw_imports:
                    self.conn.execute(
                        """INSERT INTO raw_imports(source, source_file, sheet_name, row_number,
                           raw_json, record_hash, imported_at) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(source, source_file, sheet_name, row_number) DO NOTHING""",
                        (r.source, r.source_file, r.sheet_name, r.row_number,
                         r.raw_json, r.record_hash, now_iso()),
                    )
                for c in checkins:
                    ts = now_iso()
                    c.created_at = ts
                    c.updated_at = ts
                    c.sequence_no = self.next_sequence(session_id)
                    if not c.checkin_time:
                        c.checkin_time = ts
                    try:
                        self.conn.execute(
                            """INSERT INTO checkins(session_id, sequence_no, checkin_time, callsign,
                               qth_raw, qth_standard, device_raw, device_standard,
                               antenna_raw, antenna_standard, power_raw, power_standard,
                               signal, source, raw_input, source_record_id, source_url, unmatched,
                               is_deleted, created_at, updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                            (c.session_id, c.sequence_no, c.checkin_time, c.callsign,
                             c.qth_raw, c.qth_standard, c.device_raw, c.device_standard,
                             c.antenna_raw, c.antenna_standard, c.power_raw, c.power_standard,
                             c.signal, c.source, c.raw_input, c.source_record_id, c.source_url,
                             c.unmatched,
                             c.created_at, c.updated_at),
                        )
                        imported += 1
                    except sqlite3.IntegrityError:
                        # 仅在确认为 source_record 冲突时跳过，否则上抛（P2）
                        if self._is_source_record_dup(c):
                            skipped += 1
                        else:
                            raise
        return imported, skipped

    def import_file_atomic(self, source: str, session_name: str, date: str,
                           raw_imports: list[RawImport],
                           checkins: list[Checkin]) -> tuple[int, int]:
        """单事务导入整文件：session 创建 → raw_imports → checkins → 结束场次（P1-8）。

        - 失败整体回滚：无 ghost active session、无半导入 raw_imports/checkins。
        - source_record 重复 → 逐条跳过。
        - 返回 (imported, skipped)。
        """
        imported = skipped = 0
        ts = now_iso()
        with self._alloc_lock:
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO sessions(name, date, started_at, status, repeater_name,
                       created_at, updated_at) VALUES(?,?,?,'active',?,?,?)""",
                    (session_name, date, ts, "历史导入", ts, ts))
                session_id = cur.lastrowid
                for r in raw_imports:
                    self.conn.execute(
                        """INSERT INTO raw_imports(source, source_file, sheet_name, row_number,
                           raw_json, record_hash, imported_at) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(source, source_file, sheet_name, row_number) DO NOTHING""",
                        (r.source, r.source_file, r.sheet_name, r.row_number,
                         r.raw_json, r.record_hash, now_iso()),
                    )
                for c in checkins:
                    c.session_id = session_id
                    c.created_at = c.updated_at = now_iso()
                    c.sequence_no = self.next_sequence(session_id)
                    if not c.checkin_time:
                        c.checkin_time = c.created_at
                    try:
                        self.conn.execute(
                            """INSERT INTO checkins(session_id, sequence_no, checkin_time, callsign,
                               qth_raw, qth_standard, device_raw, device_standard,
                               antenna_raw, antenna_standard, power_raw, power_standard,
                               signal, source, raw_input, source_record_id, source_url, unmatched,
                               is_deleted, created_at, updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                            (c.session_id, c.sequence_no, c.checkin_time, c.callsign,
                             c.qth_raw, c.qth_standard, c.device_raw, c.device_standard,
                             c.antenna_raw, c.antenna_standard, c.power_raw, c.power_standard,
                             c.signal, c.source, c.raw_input, c.source_record_id, c.source_url,
                             c.unmatched,
                             c.created_at, c.updated_at),
                        )
                        imported += 1
                    except sqlite3.IntegrityError:
                        # 仅在确认为 source_record 冲突时跳过，否则上抛（P2）
                        if self._is_source_record_dup(c):
                            skipped += 1
                        else:
                            raise
                # 结束场次（同一事务，绝不留下 active ghost session）
                self.conn.execute(
                    "UPDATE sessions SET status='ended', ended_at=?, updated_at=? WHERE id=?",
                    (now_iso(), now_iso(), session_id))
        return imported, skipped

    def record_import(self, r: RawImport) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO raw_imports(source, source_file, sheet_name, row_number,
                   raw_json, record_hash, imported_at) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(source, source_file, sheet_name, row_number) DO NOTHING""",
                (r.source, r.source_file, r.sheet_name, r.row_number,
                 r.raw_json, r.record_hash, now_iso()),
            )

    def list_raw_imports(self, limit: int = 200) -> list[RawImport]:
        rows = self.conn.execute(
            "SELECT * FROM raw_imports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [RawImport(**{k: r[k] for k in r.keys()}) for r in rows]

    # ---------- sync state ----------
    def get_sync_state(self, source: str, source_uid: str = "") -> SyncState | None:
        row = self.conn.execute(
            "SELECT * FROM sync_state WHERE source=? AND source_uid=?",
            (source, source_uid or ""),
        ).fetchone()
        return SyncState(**{k: row[k] for k in row.keys()}) if row else None

    def set_sync_state(self, s: SyncState) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO sync_state(source, source_uid, last_check_at, last_success_at,
                   last_record_id, last_session_id, last_hash, status, error_message)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source, source_uid) DO UPDATE SET
                     last_check_at=excluded.last_check_at,
                     last_success_at=excluded.last_success_at,
                     last_record_id=excluded.last_record_id,
                     last_session_id=excluded.last_session_id,
                     last_hash=excluded.last_hash,
                     status=excluded.status,
                     error_message=excluded.error_message""",
                (s.source, s.source_uid or "", s.last_check_at, s.last_success_at,
                 s.last_record_id, s.last_session_id, s.last_hash, s.status, s.error_message),
            )

    # ---------- source station state（任务书第二阶段 #12/#13 真增量） ----------
    def get_source_station_state(self, source: str, uid: str, callsign: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM source_station_state WHERE source=? AND source_uid=? AND callsign=?",
            (source, uid, callsign),
        ).fetchone()
        return dict(row) if row else None

    def upsert_source_station_state(self, source: str, uid: str, callsign: str, *,
                                    ranking_count: int = 0, last_history_key: str = "",
                                    last_seen_at: str = "", last_fetch_at: str = "",
                                    status: str = "pending", error_message: str = "") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO source_station_state(source, source_uid, callsign,
                   ranking_count, last_history_key, last_seen_at, last_fetch_at,
                   status, error_message)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source, source_uid, callsign) DO UPDATE SET
                     ranking_count=excluded.ranking_count,
                     last_history_key=COALESCE(excluded.last_history_key, last_history_key),
                     last_seen_at=COALESCE(excluded.last_seen_at, last_seen_at),
                     last_fetch_at=COALESCE(excluded.last_fetch_at, last_fetch_at),
                     status=excluded.status,
                     error_message=excluded.error_message""",
                (source, uid, callsign, ranking_count, last_history_key, last_seen_at,
                 last_fetch_at, status, error_message),
            )

    def list_retryable_source_stations(self, source: str, uid: str, limit: int = 100) -> list[dict]:
        """上次失败/未同步的呼号（retry 候选）。"""
        rows = self.conn.execute(
            "SELECT * FROM source_station_state WHERE source=? AND source_uid=? "
            "AND status IN ('failed','pending') ORDER BY last_fetch_at IS NULL DESC, "
            "callsign LIMIT ?",
            (source, uid, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_source_station_keys(self, source: str, uid: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT callsign FROM source_station_state WHERE source=? AND source_uid=?",
            (source, uid),
        ).fetchall()
        return {r["callsign"] for r in rows}

    def source_station_states(self, source: str, uid: str) -> dict[str, dict]:
        """当前 (source, uid) 命名空间下所有 per-callsign 状态（批量读取）。"""
        rows = self.conn.execute(
            "SELECT * FROM source_station_state WHERE source=? AND source_uid=?",
            (source, uid),
        ).fetchall()
        return {r["callsign"]: dict(r) for r in rows}

    # ---------- audit ----------
    def add_audit(self, record_id: int, field_name: str, old_value: str, new_value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO audit_log(record_id, field_name, old_value, new_value, changed_at) "
                "VALUES(?,?,?,?,?)",
                (record_id, field_name, old_value, new_value, now_iso()),
            )

    def list_audit(self, record_id: int | None = None, limit: int = 200) -> list[AuditEntry]:
        if record_id:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE record_id=? ORDER BY id DESC LIMIT ?",
                (record_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [AuditEntry(**{k: r[k] for k in r.keys()}) for r in rows]

    def as_dict_rows(self, sql: str, params: Iterable = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]
