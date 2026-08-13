"""数据库版本迁移：PRAGMA user_version 驱动，自动升级，不要求删库。"""
from __future__ import annotations

import sqlite3

MIGRATIONS: dict[int, list[str]] = {
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
}


def get_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """把数据库升级到最新版本，返回升级前版本号。"""
    current = get_version(conn)
    target = max(MIGRATIONS)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        with conn:  # 事务提交
            for stmt in MIGRATIONS[version]:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
    return current
