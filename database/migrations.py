"""数据库版本迁移：PRAGMA user_version 驱动，自动升级，不要求删库。

原则（第二轮审计 P0-2）：
- 迁移**不得**直接 DELETE 历史签到；序列冲突稳定重新编号。
- source_record 冲突必须按完整字段确认后才处理；假冲突保留两条。
- 迁移前后记录有效/总记录数，写入 migration_log 报告。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


def _renumber_duplicate_sequences(conn: sqlite3.Connection) -> int:
    """同一 session 内重复的**有效**序列稳定重新编号（不删除任何记录）。

    保留最早（MIN id）原序号，其余按 id 顺序从「会话最大序号+1」起顺延。
    返回重编号条数。幂等。
    """
    seen: set = set()
    to_fix: list = []  # (id, session_id)
    rows = conn.execute(
        "SELECT session_id, sequence_no, id FROM checkins "
        "WHERE is_deleted=0 AND sequence_no IS NOT NULL "
        "ORDER BY session_id, sequence_no, id"
    ).fetchall()
    for r in rows:
        key = (r["session_id"], r["sequence_no"])
        if key in seen:
            to_fix.append((r["id"], r["session_id"]))
        else:
            seen.add(key)
    by_session: dict[int, list] = {}
    for rid, sid in to_fix:
        by_session.setdefault(sid, []).append(rid)
    fixed = 0
    for sid, ids in by_session.items():
        m = conn.execute(
            "SELECT COALESCE(MAX(sequence_no),0) m FROM checkins WHERE session_id=?",
            (sid,),
        ).fetchone()
        nxt = int(m["m"]) + 1
        for rid in ids:
            conn.execute("UPDATE checkins SET sequence_no=? WHERE id=?", (nxt, rid))
            nxt += 1
            fixed += 1
    return fixed


def _resolve_source_record_collisions(conn: sqlite3.Connection) -> dict:
    """按完整字段确认后才处理 (source, source_record_id) 冲突（不直接 DELETE）。

    - 真重复（关键字段全等）→ 软删除（is_deleted=1）非最早记录，保留历史行。
    - 假冲突（关键字段不同）→ 保留两条，清空后一条 source_record_id 并计入告警。
    返回 {"merged": n, "kept_both": n}。
    """
    rows = conn.execute(
        """SELECT id, source, source_record_id, callsign, checkin_time,
                  qth_standard, device_standard, antenna_standard, power_standard, signal,
                  is_deleted
           FROM checkins
           WHERE source_record_id IS NOT NULL AND source_record_id != ''
           ORDER BY source, source_record_id, id"""
    ).fetchall()
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["source"], r["source_record_id"]), []).append(dict(r))

    def _key(r: dict) -> tuple:
        return (r["callsign"], r["checkin_time"], r["qth_standard"],
                r["device_standard"], r["antenna_standard"], r["power_standard"], r["signal"])

    merged = kept_both = 0
    now = datetime.now().isoformat(timespec="seconds")
    for recs in groups.values():
        if len(recs) < 2:
            continue
        # 以第一个有效记录为基准；已软删记录不参与去重（索引已排除）
        first = next((r for r in recs if r["is_deleted"] == 0), None)
        if first is None:
            continue
        for r in recs:
            if r is first or r["is_deleted"] == 1:
                continue
            if _key(r) == _key(first):
                conn.execute(
                    "UPDATE checkins SET is_deleted=1, deleted_at=? WHERE id=?",
                    (now, r["id"]))
                merged += 1
            else:
                conn.execute(
                    "UPDATE checkins SET source_record_id='' WHERE id=?", (r["id"],))
                kept_both += 1
    return {"merged": merged, "kept_both": kept_both}


def _log_migration(conn: sqlite3.Connection, version: int, action: str, detail: str) -> None:
    """写入迁移报告（任务书第二轮 P0-2：迁移前后必须留痕）。"""
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO migration_log(version, started_at, finished_at, action, detail) "
            "VALUES(?,?,?,?,?)",
            (version, ts, ts, action, detail),
        )
    except sqlite3.Error:
        pass


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """P0-1/P0-2：序号唯一索引改为「仅有效记录」partial + 非破坏性重编号 + 报告。"""
    n_before_active = conn.execute(
        "SELECT COUNT(*) c FROM checkins WHERE is_deleted=0").fetchone()["c"]
    n_before_all = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
    # 删除旧的全量唯一索引（若存在）
    conn.execute("DROP INDEX IF EXISTS uq_checkins_session_seq")
    fixed = _renumber_duplicate_sequences(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_session_seq "
        "ON checkins(session_id, sequence_no) WHERE is_deleted=0")
    n_after_active = conn.execute(
        "SELECT COUNT(*) c FROM checkins WHERE is_deleted=0").fetchone()["c"]
    n_after_all = conn.execute("SELECT COUNT(*) c FROM checkins").fetchone()["c"]
    detail = (
        f"renumbered={fixed} active_before={n_before_active} active_after={n_after_active} "
        f"total_before={n_before_all} total_after={n_after_all}"
    )
    _log_migration(conn, 8, "sequence_partial_unique", detail)


MIGRATIONS: dict[int, list] = {
    1: [
        # 点名场次
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            operator_callsign TEXT,
            repeater_name TEXT,
            started_at TEXT,
            ended_at TEXT,
            excel_path TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            updated_at TEXT
        )
        """,
        # 报到记录
        """
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            sequence_no INTEGER,
            checkin_time TEXT,
            callsign TEXT,
            qth_raw TEXT,
            qth_standard TEXT,
            device_raw TEXT,
            device_standard TEXT,
            antenna_raw TEXT,
            antenna_standard TEXT,
            power_raw TEXT,
            power_standard TEXT,
            signal TEXT,
            source TEXT,
            raw_input TEXT,
            source_record_id TEXT,
            source_url TEXT,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """,
        # 呼号概要
        """
        CREATE TABLE IF NOT EXISTS stations (
            callsign TEXT PRIMARY KEY,
            first_seen TEXT,
            last_seen TEXT,
            checkin_count INTEGER DEFAULT 0,
            last_qth TEXT,
            last_device TEXT,
            last_antenna TEXT,
            last_power TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """,
        # 呼号习惯画像（字段级别统计）
        """
        CREATE TABLE IF NOT EXISTS station_profiles (
            callsign TEXT NOT NULL,
            field_type TEXT NOT NULL,
            field_value TEXT NOT NULL,
            use_count INTEGER DEFAULT 0,
            last_used TEXT,
            PRIMARY KEY (callsign, field_type, field_value)
        )
        """,
        # 各类别名词典
        """
        CREATE TABLE IF NOT EXISTS qth_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL,
            province TEXT,
            city TEXT,
            district TEXT,
            standard_value TEXT NOT NULL,
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            source TEXT DEFAULT 'default',
            UNIQUE(alias)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS device_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL,
            standard_value TEXT NOT NULL,
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            source TEXT DEFAULT 'default',
            UNIQUE(alias)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS antenna_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL,
            standard_value TEXT NOT NULL,
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            source TEXT DEFAULT 'default',
            UNIQUE(alias)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS power_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL,
            standard_value TEXT NOT NULL,
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            source TEXT DEFAULT 'default',
            UNIQUE(alias)
        )
        """,
        # 外部导入原始数据
        """
        CREATE TABLE IF NOT EXISTS raw_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            source_file TEXT,
            sheet_name TEXT,
            row_number INTEGER,
            raw_json TEXT,
            record_hash TEXT,
            imported_at TEXT,
            UNIQUE(source, source_file, sheet_name, row_number)
        )
        """,
        # 同步状态
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            source TEXT PRIMARY KEY,
            source_uid TEXT,
            last_check_at TEXT,
            last_success_at TEXT,
            last_record_id TEXT,
            last_session_id TEXT,
            last_hash TEXT,
            status TEXT,
            error_message TEXT
        )
        """,
        # 修改审计
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_at TEXT
        )
        """,
        # 索引（性能要求）
        "CREATE INDEX IF NOT EXISTS idx_checkins_session ON checkins(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_callsign ON checkins(callsign)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_time ON checkins(checkin_time)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_qth ON checkins(qth_standard)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_device ON checkins(device_standard)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_source ON checkins(source)",
        "CREATE INDEX IF NOT EXISTS idx_profiles_callsign ON station_profiles(callsign)",
        "CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(record_id)",
    ],
    2: [
        # 跟踪每条记录是否已写入 Excel（用于断线后“只补缺失”的增量同步）
        "ALTER TABLE checkins ADD COLUMN excel_synced INTEGER DEFAULT 0",
        "ALTER TABLE checkins ADD COLUMN excel_row INTEGER",
    ],
    3: [
        # 任务书第一阶段 #3（第二轮 P0-1/P0-2 修正）：
        # 序号唯一索引仅约束「有效记录」（WHERE is_deleted=0），撤销后可复用序号；
        # 重复序列稳定重新编号，**不删除**任何签到。
        lambda conn: _renumber_duplicate_sequences(conn),
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_session_seq "
        "ON checkins(session_id, sequence_no) WHERE is_deleted=0",
    ],
    4: [
        # 任务书第一阶段 #5：Excel 绑定是 Session 级的，记录每个场次的 sheet 名。
        "ALTER TABLE sessions ADD COLUMN excel_sheet_name TEXT",
    ],
    5: [
        # 任务书第一阶段 #9/#10：Excel 同步状态机。
        # pending/written/persisted/verified/conflict/error + 错误信息 + 同步时间 + 绑定指纹。
        "ALTER TABLE checkins ADD COLUMN excel_sync_status TEXT DEFAULT 'pending'",
        "ALTER TABLE checkins ADD COLUMN excel_last_error TEXT",
        "ALTER TABLE checkins ADD COLUMN excel_synced_at TEXT",
        "ALTER TABLE checkins ADD COLUMN excel_binding_id TEXT",
        # 旧库回填：excel_synced=1 视为已持久化并验证
        "UPDATE checkins SET excel_sync_status = CASE WHEN excel_synced=1 "
        "THEN 'verified' ELSE 'pending' END",
    ],
    6: [
        # 任务书第二阶段 #12~#14：365dt 真增量。
        # per-callsign 同步状态（(source, uid, callsign) 命名空间，UID 切换自动隔离）。
        """
        CREATE TABLE IF NOT EXISTS source_station_state (
            source TEXT NOT NULL,
            source_uid TEXT NOT NULL,
            callsign TEXT NOT NULL,
            ranking_count INTEGER DEFAULT 0,
            last_history_key TEXT,
            last_seen_at TEXT,
            last_fetch_at TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            PRIMARY KEY (source, source_uid, callsign)
        )
        """,
        # 由数据库负责最终去重：UNIQUE(source, source_record_id)（仅非空 source_record_id）。
        # 冲突按完整字段确认后处理（真重复软删、假冲突保留两条），绝不直接 DELETE。
        lambda conn: _resolve_source_record_collisions(conn),
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_source_record "
        "ON checkins(source, source_record_id) "
        "WHERE is_deleted=0 AND source_record_id IS NOT NULL AND source_record_id != ''",
        # 外部场次稳定键：避免结束用户同名场次（任务书第二阶段 #20）
        "ALTER TABLE sessions ADD COLUMN external_source TEXT",
        "ALTER TABLE sessions ADD COLUMN external_uid TEXT",
        "ALTER TABLE sessions ADD COLUMN external_key TEXT",
    ],
    7: [
        # 任务书第三阶段 #2：导入文件完成状态（只有 completed 才能整文件跳过）。
        """
        CREATE TABLE IF NOT EXISTS import_jobs (
            source TEXT NOT NULL,
            source_file TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            imported_count INTEGER DEFAULT 0,
            error_message TEXT,
            updated_at TEXT,
            PRIMARY KEY (source, source_file)
        )
        """,
    ],
    8: [
        # 迁移报告表（P0-2：迁移前后记录数留痕）
        """
        CREATE TABLE IF NOT EXISTS migration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER,
            started_at TEXT,
            finished_at TEXT,
            action TEXT,
            detail TEXT
        )
        """,
        # 旧库升级：删旧全量索引 → 稳定重编号 → 建「仅有效记录」partial 索引 → 写报告
        lambda conn: _migrate_v8(conn),
    ],
    9: [
        # P2：sync_state 改为 (source, source_uid) 命名空间（UID 切换隔离）。
        lambda conn: _migrate_v9_sync_state_uid(conn),
    ],
    10: [
        # P2：checkins.session_id → sessions.id 外键 + is_deleted/status CHECK 约束。
        # SQLite 不支持 ALTER ADD CONSTRAINT，需重建表；先清理孤儿记录并归一化取值。
        lambda conn: _migrate_v10_constraints(conn),
    ],
    11: [
        # 保留解析器未识别 token，供 Excel“未识别”列和后续人工整理使用。
        "ALTER TABLE checkins ADD COLUMN unmatched TEXT DEFAULT ''",
    ],
}


def _migrate_v10_constraints(conn: sqlite3.Connection) -> None:
    """重建 checkins/sessions 加入外键与 CHECK，使非法引用/取值无法再写入。"""
    # 1) 清理孤儿记录：父场次已不存在，保留无意义且阻碍外键启用
    n_orphans = conn.execute(
        """SELECT COUNT(*) c FROM checkins c
           WHERE c.session_id IS NOT NULL AND NOT EXISTS(
               SELECT 1 FROM sessions s WHERE s.id = c.session_id)"""
    ).fetchone()["c"]
    conn.execute(
        """DELETE FROM checkins WHERE session_id IS NOT NULL AND NOT EXISTS(
               SELECT 1 FROM sessions s WHERE s.id = checkins.session_id)"""
    )
    # 2) 归一化历史脏取值（不丢数据，只归到合法值）
    conn.execute("UPDATE checkins SET is_deleted=1 WHERE is_deleted NOT IN (0,1)")
    conn.execute("UPDATE sessions SET status='active' WHERE status NOT IN ('active','ended')")
    # 3) 重建 sessions：加 CHECK(status)。RENAME 保留索引同名，故先 DROP。
    conn.execute("ALTER TABLE sessions RENAME TO sessions_old")
    conn.execute(
        """CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            operator_callsign TEXT,
            repeater_name TEXT,
            started_at TEXT,
            ended_at TEXT,
            excel_path TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','ended')),
            created_at TEXT,
            updated_at TEXT,
            excel_sheet_name TEXT,
            external_source TEXT,
            external_uid TEXT,
            external_key TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO sessions(id, name, date, operator_callsign, repeater_name,
           started_at, ended_at, excel_path, status, created_at, updated_at,
           excel_sheet_name, external_source, external_uid, external_key)
           SELECT id, name, date, operator_callsign, repeater_name,
           started_at, ended_at, excel_path, status, created_at, updated_at,
           excel_sheet_name, external_source, external_uid, external_key
           FROM sessions_old"""
    )
    conn.execute("DROP TABLE sessions_old")
    # 4) 重建 checkins：FK + CHECK。RENAME 会把索引挂到旧表且保留同名，先显式 DROP。
    for idx in ("uq_checkins_session_seq", "uq_checkins_source_record",
                "idx_checkins_session", "idx_checkins_callsign", "idx_checkins_time",
                "idx_checkins_qth", "idx_checkins_device", "idx_checkins_source"):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.execute("ALTER TABLE checkins RENAME TO checkins_old")
    conn.execute(
        """CREATE TABLE checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL
                REFERENCES sessions(id) ON DELETE RESTRICT,
            sequence_no INTEGER,
            checkin_time TEXT,
            callsign TEXT,
            qth_raw TEXT,
            qth_standard TEXT,
            device_raw TEXT,
            device_standard TEXT,
            antenna_raw TEXT,
            antenna_standard TEXT,
            power_raw TEXT,
            power_standard TEXT,
            signal TEXT,
            source TEXT,
            raw_input TEXT,
            source_record_id TEXT,
            source_url TEXT,
            is_deleted INTEGER DEFAULT 0 CHECK(is_deleted IN (0,1)),
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            excel_synced INTEGER DEFAULT 0,
            excel_row INTEGER,
            excel_sync_status TEXT DEFAULT 'pending',
            excel_last_error TEXT,
            excel_synced_at TEXT,
            excel_binding_id TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO checkins(id, session_id, sequence_no, checkin_time, callsign,
           qth_raw, qth_standard, device_raw, device_standard, antenna_raw,
           antenna_standard, power_raw, power_standard, signal, source, raw_input,
           source_record_id, source_url, is_deleted, deleted_at, created_at, updated_at,
           excel_synced, excel_row, excel_sync_status, excel_last_error, excel_synced_at,
           excel_binding_id)
           SELECT id, session_id, sequence_no, checkin_time, callsign,
           qth_raw, qth_standard, device_raw, device_standard, antenna_raw,
           antenna_standard, power_raw, power_standard, signal, source, raw_input,
           source_record_id, source_url, is_deleted, deleted_at, created_at, updated_at,
           excel_synced, excel_row, excel_sync_status, excel_last_error, excel_synced_at,
           excel_binding_id FROM checkins_old"""
    )
    # 5) 重建索引（部分唯一索引回到新表；旧表上的索引随 DROP 一并清除）
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_session_seq "
        "ON checkins(session_id, sequence_no) WHERE is_deleted=0"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_source_record "
        "ON checkins(source, source_record_id) "
        "WHERE is_deleted=0 AND source_record_id IS NOT NULL AND source_record_id != ''"
    )
    for col in ("session", "callsign", "time", "qth", "device", "source"):
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_checkins_{col} ON checkins("
            + {"session": "session_id", "callsign": "callsign", "time": "checkin_time",
               "qth": "qth_standard", "device": "device_standard", "source": "source"}
            [col] + ")"
        )
    conn.execute("DROP TABLE checkins_old")
    _log_migration(
        conn, 10, "fk_check_constraints",
        f"orphan_deleted={n_orphans} checkins_rebuilt=True",
    )


def _migrate_v9_sync_state_uid(conn: sqlite3.Connection) -> None:
    """重建 sync_state：主键 (source, source_uid)，旧数据以现有 source_uid 迁移。"""
    conn.execute(
        """CREATE TABLE sync_state_new (
            source TEXT NOT NULL,
            source_uid TEXT NOT NULL DEFAULT '',
            last_check_at TEXT,
            last_success_at TEXT,
            last_record_id TEXT,
            last_session_id TEXT,
            last_hash TEXT,
            status TEXT,
            error_message TEXT,
            PRIMARY KEY (source, source_uid)
        )"""
    )
    conn.execute(
        """INSERT INTO sync_state_new(source, source_uid, last_check_at, last_success_at,
           last_record_id, last_session_id, last_hash, status, error_message)
           SELECT source, COALESCE(source_uid, ''), last_check_at, last_success_at,
                  last_record_id, last_session_id, last_hash, status, error_message
           FROM sync_state"""
    )
    conn.execute("DROP TABLE sync_state")
    conn.execute("ALTER TABLE sync_state_new RENAME TO sync_state")


def get_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """把数据库升级到最新版本，返回升级前版本号。

    迁移步骤可以是 SQL 字符串或可调用对象（callable(conn)）。
    """
    current = get_version(conn)
    target = max(MIGRATIONS)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        with conn:  # 事务提交
            for stmt in MIGRATIONS[version]:
                if callable(stmt):
                    stmt(conn)
                else:
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
    return current
