"""数据访问层：所有 SQL 都集中在这里，UI/Service 不直接执行 SQL。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
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

    # ---------- sessions ----------
    def create_session(self, name: str, date: str, operator_callsign: str = "",
                       repeater_name: str = "", excel_path: str = "") -> Session:
        ts = now_iso()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO sessions(name, date, operator_callsign, repeater_name,
                   started_at, excel_path, status, created_at, updated_at)
                   VALUES(?,?,?,?,?,?, 'active', ?, ?)""",
                (name, date, operator_callsign, repeater_name, ts, excel_path, ts, ts),
            )
        return self.get_session(cur.lastrowid)

    def get_session(self, session_id: int) -> Session | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self, limit: int = 200) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._session_from_row(r) for r in rows]

    def find_session_by_name(self, name: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        return self._session_from_row(row) if row else None

    def active_sessions(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE status='active' ORDER BY id"
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
                   signal, source, raw_input, source_record_id, source_url,
                   is_deleted, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (c.session_id, c.sequence_no, c.checkin_time, c.callsign,
                 c.qth_raw, c.qth_standard, c.device_raw, c.device_standard,
                 c.antenna_raw, c.antenna_standard, c.power_raw, c.power_standard,
                 c.signal, c.source, c.raw_input, c.source_record_id, c.source_url,
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

    # ---------- Excel 同步跟踪（V2：断线后只补缺失记录） ----------
    def mark_excel_synced(self, checkin_id: int, excel_row: int | None = None) -> None:
        if excel_row is not None:
            with self.conn:
                self.conn.execute(
                    "UPDATE checkins SET excel_synced=1, excel_row=? WHERE id=?",
                    (excel_row, checkin_id))
        else:
            with self.conn:
                self.conn.execute(
                    "UPDATE checkins SET excel_synced=1 WHERE id=?", (checkin_id,))

    def list_unsynced(self, session_id: int) -> list[Checkin]:
        rows = self.conn.execute(
            "SELECT * FROM checkins WHERE session_id=? AND is_deleted=0 AND excel_synced=0 "
            "ORDER BY sequence_no",
            (session_id,),
        ).fetchall()
        return [self._checkin_from_row(r) for r in rows]

    def reset_excel_sync(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET excel_synced=0, excel_row=NULL WHERE session_id=?",
                (session_id,))

    def mark_all_excel_synced(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE checkins SET excel_synced=1 WHERE session_id=? AND is_deleted=0",
                (session_id,))

    @staticmethod
    def _checkin_from_row(row) -> Checkin:
        return Checkin(**{k: row[k] for k in row.keys()})

    # ---------- stations / profiles ----------
    def upsert_station_from_checkin(self, c: Checkin) -> None:
        """根据一条签到记录更新呼号概要。"""
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

    def bump_profile(self, callsign: str, field_type: str, field_value: str) -> None:
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

    def update_profiles_from_checkin(self, c: Checkin) -> None:
        for ft in ("qth", "device", "antenna", "power"):
            val = getattr(c, f"{ft}_standard")
            self.bump_profile(c.callsign, ft, val)

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
        h = hashlib.sha256()
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
    def get_sync_state(self, source: str) -> SyncState | None:
        row = self.conn.execute(
            "SELECT * FROM sync_state WHERE source=?", (source,)
        ).fetchone()
        return SyncState(**{k: row[k] for k in row.keys()}) if row else None

    def set_sync_state(self, s: SyncState) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO sync_state(source, source_uid, last_check_at, last_success_at,
                   last_record_id, last_session_id, last_hash, status, error_message)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source) DO UPDATE SET
                     source_uid=excluded.source_uid,
                     last_check_at=excluded.last_check_at,
                     last_success_at=excluded.last_success_at,
                     last_record_id=excluded.last_record_id,
                     last_session_id=excluded.last_session_id,
                     last_hash=excluded.last_hash,
                     status=excluded.status,
                     error_message=excluded.error_message""",
                (s.source, s.source_uid, s.last_check_at, s.last_success_at,
                 s.last_record_id, s.last_session_id, s.last_hash, s.status, s.error_message),
            )

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
