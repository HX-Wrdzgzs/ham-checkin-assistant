"""独立的工信部电台型号资料库。

该数据库与点名业务数据库完全分离，默认位于 LocalAppData 下。同步线程可以
写入临时/暂存记录，而快速录入线程只读取上一次已经验证完成的正式快照；完整
同步成功前，旧快照不会被替换。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from rapidfuzz import fuzz

from providers.miit import FILTER_RULE_VERSION, model_abbreviations, normalize_model

CATALOG_SCHEMA_VERSION = 2
CATALOG_SEARCH_MAX_LIMIT = 500
_SEARCH_CANDIDATE_LIMIT = 1000

DEVICE_COLUMNS = (
    "article_id", "category_id", "standard_name", "model", "normalized_model",
    "device_name", "device_class", "applicant", "brand", "certificate_no", "remarks",
    "valid_for", "frequency_tolerance", "frequency_range", "transmit_power", "bandwidth",
    "spurious_emission_limit", "approved_at", "approval_code", "cmiit_id", "modulation",
    "technical_system", "create_time", "deleted_flag", "display_flag", "source_url",
    "content_hash", "filter_rule_version", "raw_json", "first_seen_at", "last_seen_at",
)

_META_DEFAULTS = {
    "schema_version": str(CATALOG_SCHEMA_VERSION),
    "filter_rule_version": FILTER_RULE_VERSION,
    "active_sync_id": "",
    "active_updated_at": "",
    "active_scanned_count": "0",
    "active_count": "0",
}

_SAFE_RUN_FIELDS = {
    "total_count", "scanned_count", "retained_count", "excluded_count", "unknown_count",
    "total_pages", "completed_pages", "retry_count", "status", "last_error",
    "unknown_names_json", "page_size", "ended_at", "updated_at", "rule_version",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _expiry_status(value: str) -> str:
    """只在官方有效期明确写成日期且已经过去时提示过期。"""
    text = str(value or "").strip()
    dates = re.findall(r"(?:19|20)\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?", text)
    parsed = []
    for item in dates:
        cleaned = re.sub(r"[年月./]", "-", item).replace("日", "")
        try:
            parsed.append(datetime.strptime(cleaned, "%Y-%m-%d").date())
        except ValueError:
            continue
    if parsed and max(parsed) < date.today():
        return "核准有效期已过"
    return ""


def _natural_model_key(value: str) -> tuple[tuple[int, object], ...]:
    """让型号按 ``K1, K2, K10`` 的人类习惯排序，而不是字典序。"""
    text = normalize_model(value)
    parts = re.split(r"(\d+)", text)
    return tuple((0, int(part)) if part.isdigit() else (1, part)
                 for part in parts if part)


def _contains_casefold(value: str, query: str) -> bool:
    return bool(query and query.casefold() in str(value or "").casefold())


class MiitCatalogRepository:
    """型号库专用 SQLite 访问层。

    一个进程可能同时存在主线程只读连接和同步 worker 连接，因此每个实例有
    自己的锁和连接；SQLite WAL/短事务负责跨连接协作。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            str(self.path), timeout=30, check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._fts_available = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        columns = ",\n            ".join(
            f"{name} TEXT NOT NULL DEFAULT ''" for name in DEVICE_COLUMNS
        )
        with self._lock, self.conn:
            self.conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS miit_radio_devices (
                    {columns},
                    PRIMARY KEY(article_id)
                );
                CREATE INDEX IF NOT EXISTS idx_miit_radio_model
                    ON miit_radio_devices(normalized_model);
                CREATE INDEX IF NOT EXISTS idx_miit_radio_applicant
                    ON miit_radio_devices(applicant);
                CREATE INDEX IF NOT EXISTS idx_miit_radio_approval
                    ON miit_radio_devices(approval_code);
                CREATE TABLE IF NOT EXISTS miit_radio_devices_staging (
                    sync_id TEXT NOT NULL,
                    {columns},
                    PRIMARY KEY(sync_id, article_id)
                );
                CREATE INDEX IF NOT EXISTS idx_miit_staging_sync
                    ON miit_radio_devices_staging(sync_id);
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS miit_sync_runs (
                    sync_id TEXT PRIMARY KEY,
                    sync_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT DEFAULT '',
                    total_count INTEGER DEFAULT 0,
                    scanned_count INTEGER DEFAULT 0,
                    retained_count INTEGER DEFAULT 0,
                    excluded_count INTEGER DEFAULT 0,
                    unknown_count INTEGER DEFAULT 0,
                    total_pages INTEGER DEFAULT 0,
                    completed_pages INTEGER DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    last_error TEXT DEFAULT '',
                    unknown_names_json TEXT DEFAULT '{{}}',
                    page_size INTEGER DEFAULT 1000,
                    rule_version TEXT NOT NULL DEFAULT '{FILTER_RULE_VERSION}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS miit_sync_checkpoint (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    sync_id TEXT NOT NULL,
                    current_page INTEGER NOT NULL DEFAULT 0,
                    page_size INTEGER NOT NULL DEFAULT 1000,
                    scanned_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    last_article_id TEXT DEFAULT '',
                    staging_path TEXT DEFAULT '',
                    last_success_at TEXT NOT NULL
                );
                -- 完整同步的临时去重索引。这里只保存官网记录 ID，不保存非电台
                -- 设备内容；用于官网分页位移和进程重启后的安全断点续传。
                CREATE TABLE IF NOT EXISTS miit_sync_seen_ids (
                    sync_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    PRIMARY KEY(sync_id, article_id)
                ) WITHOUT ROWID;
                """
            )
            for key, value in _META_DEFAULTS.items():
                if key in {"schema_version", "filter_rule_version"}:
                    self.conn.execute(
                        "INSERT INTO catalog_meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
                else:
                    self.conn.execute(
                        "INSERT INTO catalog_meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO NOTHING",
                        (key, value),
                    )
            try:
                self.conn.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS miit_radio_devices_fts
                       USING fts5(article_id UNINDEXED, model, normalized_model,
                                  standard_name, device_name, applicant, brand,
                                  certificate_no, approval_code, cmiit_id)"""
                )
            except sqlite3.OperationalError:
                # 某些精简 Python SQLite 没有 FTS5；规范字段索引仍可用，且不影响
                # 数据完整性。若以后运行环境支持 FTS5，仍可重建库启用。
                self._fts_available = False
                self.conn.execute(
                    """CREATE TABLE IF NOT EXISTS miit_radio_devices_fts (
                       article_id TEXT PRIMARY KEY, model TEXT, normalized_model TEXT,
                       standard_name TEXT, device_name TEXT, applicant TEXT, brand TEXT,
                       certificate_no TEXT, approval_code TEXT, cmiit_id TEXT)"""
                )
            self._fts_available = self._detect_fts()
            # 只在索引不存在或数量不一致时重建。旧版每次启动都全量
            # DELETE + INSERT，型号库较大时会把启动误认为“卡死”。
            device_count = int(self.conn.execute(
                "SELECT COUNT(*) AS c FROM miit_radio_devices"
            ).fetchone()["c"])
            fts_count = int(self.conn.execute(
                "SELECT COUNT(*) AS c FROM miit_radio_devices_fts"
            ).fetchone()["c"])
            if device_count != fts_count:
                self._rebuild_fts_locked()

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass

    def reopen(self) -> None:
        """让长期运行的 UI 连接看见 worker 刚完成的 WAL 提交。"""
        with self._lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self._fts_available = self._detect_fts()

    def _detect_fts(self) -> bool:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='miit_radio_devices_fts'"
        ).fetchone()
        return bool(row and "VIRTUAL TABLE" in str(row["sql"] or "").upper())

    def _rebuild_fts_locked(self) -> None:
        if self._fts_available:
            self.conn.execute("DELETE FROM miit_radio_devices_fts")
            self.conn.execute(
                """INSERT INTO miit_radio_devices_fts(
                    article_id, model, normalized_model, standard_name, device_name,
                    applicant, brand, certificate_no, approval_code, cmiit_id)
                   SELECT article_id, model, normalized_model, standard_name, device_name,
                          applicant, brand, certificate_no, approval_code, cmiit_id
                   FROM miit_radio_devices"""
            )
        else:
            self.conn.execute("DELETE FROM miit_radio_devices_fts")
            self.conn.execute(
                """INSERT INTO miit_radio_devices_fts(
                    article_id, model, normalized_model, standard_name, device_name,
                    applicant, brand, certificate_no, approval_code, cmiit_id)
                   SELECT article_id, model, normalized_model, standard_name, device_name,
                          applicant, brand, certificate_no, approval_code, cmiit_id
                   FROM miit_radio_devices"""
            )

    def _set_meta_locked(self, key: str, value) -> None:
        self.conn.execute(
            """INSERT INTO catalog_meta(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, str(value if value is not None else "")),
        )

    def _meta_locked(self) -> dict:
        rows = self.conn.execute("SELECT key,value FROM catalog_meta").fetchall()
        values = dict(_META_DEFAULTS)
        values.update({row["key"]: row["value"] for row in rows})
        return values

    def count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM miit_radio_devices").fetchone()
            return int(row["c"])

    def size_bytes(self) -> int:
        total = 0
        for path in (self.path, self.path.with_name(self.path.name + "-wal"),
                     self.path.with_name(self.path.name + "-shm")):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def quick_check(self) -> str:
        with self._lock:
            row = self.conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else ""

    def status(self) -> dict:
        with self._lock:
            meta = self._meta_locked()
            run = self.conn.execute(
                "SELECT * FROM miit_sync_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            checkpoint = self.conn.execute(
                "SELECT * FROM miit_sync_checkpoint WHERE singleton=1"
            ).fetchone()
            return {
                "path": str(self.path),
                "count": int(meta.get("active_count", self.count())),
                "active_sync_id": meta.get("active_sync_id", ""),
                "updated_at": meta.get("active_updated_at", ""),
                "scanned_count": int(meta.get("active_scanned_count", 0) or 0),
                "filter_rule_version": meta.get("filter_rule_version", FILTER_RULE_VERSION),
                "size_bytes": self.size_bytes(),
                "run": dict(run) if run is not None else None,
                "checkpoint": dict(checkpoint) if checkpoint is not None else None,
            }

    def get_resume_info(self, full: bool = True) -> dict | None:
        with self._lock:
            checkpoint = self.conn.execute(
                "SELECT * FROM miit_sync_checkpoint WHERE singleton=1"
            ).fetchone()
            if checkpoint is None:
                return None
            run = self.conn.execute(
                "SELECT * FROM miit_sync_runs WHERE sync_id=?",
                (checkpoint["sync_id"],),
            ).fetchone()
            if run is None or (full and run["sync_type"] != "full"):
                return None
            if run["status"] not in {"running", "cancelled", "failed"}:
                return None
            return {"checkpoint": _row_dict(checkpoint), "run": _row_dict(run)}

    def get_run(self, sync_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM miit_sync_runs WHERE sync_id=?", (sync_id,)
            ).fetchone()
            return _row_dict(row) if row else None

    def create_run(self, sync_id: str, sync_type: str, page_size: int,
                   *, resume: bool = False) -> dict:
        now = _now()
        with self._lock, self.conn:
            if not resume:
                # 同一进程只允许一个同步任务；重新开始时清理所有旧半成品，
                # 但不触碰正式快照和历史同步记录。
                self.conn.execute("DELETE FROM miit_radio_devices_staging")
                self.conn.execute("DELETE FROM miit_sync_checkpoint WHERE singleton=1")
                self.conn.execute("DELETE FROM miit_sync_seen_ids")
                self.conn.execute(
                    """INSERT OR REPLACE INTO miit_sync_runs(
                       sync_id,sync_type,started_at,status,page_size,rule_version,updated_at)
                       VALUES(?,?,?,'running',?,?,?)""",
                    (sync_id, sync_type, now, int(page_size), FILTER_RULE_VERSION, now),
                )
            else:
                self.conn.execute(
                    "UPDATE miit_sync_runs SET status='running', last_error='', updated_at=? WHERE sync_id=?",
                    (now, sync_id),
                )
            row = self.conn.execute(
                "SELECT * FROM miit_sync_runs WHERE sync_id=?", (sync_id,)
            ).fetchone()
            return _row_dict(row)

    def update_run(self, sync_id: str, **fields) -> None:
        fields = {key: value for key, value in fields.items() if key in _SAFE_RUN_FIELDS}
        if not fields:
            return
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self._lock, self.conn:
            self.conn.execute(
                f"UPDATE miit_sync_runs SET {assignments} WHERE sync_id=?",
                (*fields.values(), sync_id),
            )

    def write_checkpoint(self, sync_id: str, *, current_page: int, page_size: int,
                         scanned_count: int, total_count: int,
                         last_article_id: str = "", staging_path: str = "") -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO miit_sync_checkpoint(
                   singleton,sync_id,current_page,page_size,scanned_count,total_count,
                   last_article_id,staging_path,last_success_at)
                   VALUES(1,?,?,?,?,?,?,?,?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     sync_id=excluded.sync_id,current_page=excluded.current_page,
                     page_size=excluded.page_size,scanned_count=excluded.scanned_count,
                     total_count=excluded.total_count,last_article_id=excluded.last_article_id,
                     staging_path=excluded.staging_path,last_success_at=excluded.last_success_at""",
                (sync_id, int(current_page), int(page_size), int(scanned_count), int(total_count),
                 last_article_id, staging_path, _now()),
            )

    def stage_rows(self, sync_id: str, rows: list[dict]) -> None:
        if not rows:
            return
        with self._lock, self.conn:
            self._stage_rows_locked(sync_id, rows)

    def sync_seen_ids(self, sync_id: str) -> set[str]:
        """返回该完整同步已经成功提交过的官网记录 ID。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT article_id FROM miit_sync_seen_ids WHERE sync_id=?",
                (sync_id,),
            ).fetchall()
            return {str(row["article_id"]) for row in rows}

    def staging_article_ids(self, sync_id: str) -> set[str]:
        """兼容升级前断点：返回暂存电台记录的官网 ID。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT article_id FROM miit_radio_devices_staging WHERE sync_id=?",
                (sync_id,),
            ).fetchall()
            return {str(row["article_id"]) for row in rows}

    def _stage_rows_locked(self, sync_id: str, rows: list[dict]) -> None:
        """在调用方已持有锁/事务时暂存一页记录。"""
        if not rows:
            return
        placeholders = ",".join("?" for _ in DEVICE_COLUMNS)
        update_columns = [column for column in DEVICE_COLUMNS[1:]
                          if column != "first_seen_at"]
        sql = (
            f"INSERT INTO miit_radio_devices_staging(sync_id,{','.join(DEVICE_COLUMNS)}) "
            f"VALUES(?,{placeholders}) ON CONFLICT(sync_id,article_id) DO UPDATE SET "
            + ",".join(f"{column}=excluded.{column}" for column in update_columns)
        )
        now = _now()
        values = []
        for row in rows:
            values.append((
                sync_id,
                *[str(row.get(column) or (now if column in {"first_seen_at", "last_seen_at"} else ""))
                  for column in DEVICE_COLUMNS],
            ))
        self.conn.executemany(sql, values)

    def record_full_page(self, sync_id: str, rows: list[dict], *,
                         total_count: int, scanned_count: int,
                         retained_count: int, excluded_count: int,
                         unknown_count: int, total_pages: int,
                         completed_pages: int, retry_count: int,
                         unknown_names_json: str, page_size: int,
                         last_article_id: str = "",
                         seen_ids: list[str] | tuple[str, ...] = ()) -> None:
        """原子记录完整同步的一页及其断点。

        暂存记录、运行统计和 checkpoint 必须同事务提交。这样即使进程在
        页面处理后立即崩溃，恢复时也只会从最后一个完整页面的下一页继续，
        不会出现“暂存了一半但断点没推进”的重复/丢失窗口。
        """
        now = _now()
        with self._lock, self.conn:
            self._stage_rows_locked(sync_id, rows)
            if seen_ids:
                self.conn.executemany(
                    "INSERT OR IGNORE INTO miit_sync_seen_ids(sync_id,article_id) "
                    "VALUES(?,?)",
                    ((sync_id, str(article_id)) for article_id in seen_ids),
                )
            self.conn.execute(
                """UPDATE miit_sync_runs SET total_count=?, scanned_count=?,
                   retained_count=?, excluded_count=?, unknown_count=?,
                   total_pages=?, completed_pages=?, retry_count=?,
                   unknown_names_json=?, page_size=?, updated_at=? WHERE sync_id=?""",
                (total_count, scanned_count, retained_count, excluded_count,
                 unknown_count, total_pages, completed_pages, retry_count,
                 unknown_names_json, page_size, now, sync_id),
            )
            self.conn.execute(
                """INSERT INTO miit_sync_checkpoint(
                   singleton,sync_id,current_page,page_size,scanned_count,total_count,
                   last_article_id,staging_path,last_success_at)
                   VALUES(1,?,?,?,?,?,?,?,?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     sync_id=excluded.sync_id,current_page=excluded.current_page,
                     page_size=excluded.page_size,scanned_count=excluded.scanned_count,
                     total_count=excluded.total_count,last_article_id=excluded.last_article_id,
                     staging_path=excluded.staging_path,last_success_at=excluded.last_success_at""",
                (sync_id, int(completed_pages), int(page_size), int(scanned_count),
                 int(total_count), last_article_id, str(self.path), now),
            )

    def staging_article_exists(self, sync_id: str, article_id: str) -> bool:
        """检查断点续传时已完成页是否已经暂存过某个官网 ID。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM miit_radio_devices_staging "
                "WHERE sync_id=? AND article_id=? LIMIT 1",
                (sync_id, article_id),
            ).fetchone()
            return row is not None

    def article_fingerprint(self, article_id: str) -> str:
        """返回正式快照中的内容哈希；不存在时返回空字符串。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT content_hash FROM miit_radio_devices WHERE article_id=?",
                (article_id,),
            ).fetchone()
            return str(row["content_hash"] or "") if row else ""

    def finalize_full_run(self, sync_id: str, *, scanned_count: int,
                          retained_count: int, excluded_count: int,
                          unknown_count: int, total_count: int, total_pages: int,
                          completed_pages: int, retry_count: int,
                          unknown_names: dict[str, int]) -> dict:
        """验证暂存快照后一次性替换正式数据。失败由事务自动保留旧快照。"""
        with self._lock:
            quick = self.conn.execute("PRAGMA quick_check").fetchone()
            if not quick or str(quick[0]).lower() != "ok":
                raise sqlite3.DatabaseError("型号库 quick_check 失败，拒绝换库")
            row = self.conn.execute(
                """SELECT COUNT(*) AS c, COUNT(DISTINCT article_id) AS d
                   FROM miit_radio_devices_staging WHERE sync_id=?""",
                (sync_id,),
            ).fetchone()
            if int(row["c"]) != int(row["d"]):
                raise sqlite3.DatabaseError("暂存型号库存在重复官网记录 ID，拒绝换库")
            if int(row["c"]) != int(retained_count):
                raise sqlite3.DatabaseError(
                    f"暂存型号库记录数不一致：暂存 {row['c']}，统计 {retained_count}，拒绝换库"
                )
            if int(scanned_count) < int(total_count):
                raise sqlite3.DatabaseError("官网扫描数量不足，拒绝换库")
            now = _now()
            with self.conn:
                self.conn.execute("DELETE FROM miit_radio_devices")
                self.conn.execute(
                    f"""INSERT INTO miit_radio_devices({','.join(DEVICE_COLUMNS)})
                        SELECT {','.join(DEVICE_COLUMNS)}
                        FROM miit_radio_devices_staging WHERE sync_id=?""",
                    (sync_id,),
                )
                self._rebuild_fts_locked()
                post_quick = self.conn.execute("PRAGMA quick_check").fetchone()
                if not post_quick or str(post_quick[0]).lower() != "ok":
                    raise sqlite3.DatabaseError("换库后的型号库 quick_check 失败，已保留旧快照")
                fts_count = int(self.conn.execute(
                    "SELECT COUNT(*) AS c FROM miit_radio_devices_fts"
                ).fetchone()["c"])
                active_count = int(self.conn.execute(
                    "SELECT COUNT(*) AS c FROM miit_radio_devices"
                ).fetchone()["c"])
                if fts_count != active_count:
                    raise sqlite3.DatabaseError("型号库全文索引记录数不一致，已保留旧快照")
                self._set_meta_locked("active_sync_id", sync_id)
                self._set_meta_locked("active_updated_at", now)
                self._set_meta_locked("active_scanned_count", scanned_count)
                self._set_meta_locked("active_count", retained_count)
                self._set_meta_locked("filter_rule_version", FILTER_RULE_VERSION)
                self.conn.execute(
                    """UPDATE miit_sync_runs SET status='completed', ended_at=?,
                       total_count=?, scanned_count=?, retained_count=?, excluded_count=?,
                       unknown_count=?, total_pages=?, completed_pages=?, retry_count=?,
                       unknown_names_json=?, last_error='', updated_at=? WHERE sync_id=?""",
                    (now, total_count, scanned_count, retained_count, excluded_count,
                     unknown_count, total_pages, completed_pages, retry_count,
                     json.dumps(unknown_names, ensure_ascii=False, sort_keys=True), now, sync_id),
                )
                self.conn.execute("DELETE FROM miit_radio_devices_staging WHERE sync_id=?", (sync_id,))
                self.conn.execute("DELETE FROM miit_sync_seen_ids WHERE sync_id=?", (sync_id,))
                self.conn.execute("DELETE FROM miit_sync_checkpoint WHERE singleton=1")
            return self.status()

    def finish_incremental(self, sync_id: str, *, scanned_count: int,
                           retained_count: int, excluded_count: int, unknown_count: int,
                           total_count: int, total_pages: int, completed_pages: int,
                           retry_count: int, unknown_names: dict[str, int]) -> dict:
        """将头部扫描结果一次性应用到正式库；完整校验仍由 full 模式负责。"""
        now = _now()
        with self._lock, self.conn:
            rows = self.conn.execute(
                "SELECT * FROM miit_radio_devices_staging WHERE sync_id=?", (sync_id,)
            ).fetchall()
            for row in rows:
                values = [row[column] for column in DEVICE_COLUMNS]
                assignments = ",".join(
                    ("first_seen_at=COALESCE(NULLIF(miit_radio_devices.first_seen_at,''), "
                     "excluded.first_seen_at)" if column == "first_seen_at"
                     else f"{column}=excluded.{column}")
                    for column in DEVICE_COLUMNS[1:]
                )
                self.conn.execute(
                    f"""INSERT INTO miit_radio_devices({','.join(DEVICE_COLUMNS)})
                        VALUES({','.join('?' for _ in DEVICE_COLUMNS)})
                        ON CONFLICT(article_id) DO UPDATE SET {assignments}""",
                    values,
                )
            self._rebuild_fts_locked()
            post_quick = self.conn.execute("PRAGMA quick_check").fetchone()
            if not post_quick or str(post_quick[0]).lower() != "ok":
                raise sqlite3.DatabaseError("增量更新后的型号库 quick_check 失败")
            fts_count = int(self.conn.execute(
                "SELECT COUNT(*) AS c FROM miit_radio_devices_fts"
            ).fetchone()["c"])
            active_count = int(self.conn.execute(
                "SELECT COUNT(*) AS c FROM miit_radio_devices"
            ).fetchone()["c"])
            if fts_count != active_count:
                raise sqlite3.DatabaseError("增量更新后全文索引记录数不一致")
            self._set_meta_locked("active_sync_id", sync_id)
            self._set_meta_locked("active_updated_at", now)
            self._set_meta_locked("active_scanned_count", scanned_count)
            self._set_meta_locked("active_count", self.count())
            self._set_meta_locked("filter_rule_version", FILTER_RULE_VERSION)
            self.conn.execute(
                """UPDATE miit_sync_runs SET status='completed', ended_at=?,
                   total_count=?, scanned_count=?, retained_count=?, excluded_count=?,
                   unknown_count=?, total_pages=?, completed_pages=?, retry_count=?,
                   unknown_names_json=?, last_error='', updated_at=? WHERE sync_id=?""",
                (now, total_count, scanned_count, retained_count, excluded_count, unknown_count,
                 total_pages, completed_pages, retry_count,
                 json.dumps(unknown_names, ensure_ascii=False, sort_keys=True), now, sync_id),
            )
            self.conn.execute("DELETE FROM miit_radio_devices_staging WHERE sync_id=?", (sync_id,))
            self.conn.execute("DELETE FROM miit_sync_checkpoint WHERE singleton=1")
        return self.status()

    def fail_run(self, sync_id: str, status: str, message: str) -> None:
        if status not in {"failed", "cancelled"}:
            status = "failed"
        self.update_run(sync_id, status=status, last_error=str(message)[:2000], ended_at=_now())

    def _fetch_candidates_locked(self, query: str, *, allow_fuzzy: bool = True) -> list[dict]:
        normalized = normalize_model(query)
        if not normalized:
            return []
        # 先走规范型号的等值/前缀索引，避免每次键入短型号都对
        # 20 万条记录执行全字段 LIKE；无型号命中时才做有限字段检索。
        rows = self.conn.execute(
            """SELECT * FROM miit_radio_devices
               WHERE normalized_model=? OR normalized_model LIKE ?
               ORDER BY CASE WHEN normalized_model=? THEN 0 ELSE 1 END,
                        approved_at DESC, create_time DESC
               LIMIT 200""",
            (normalized, f"{normalized}%", normalized),
        ).fetchall()

        # 现场常把 UV-K5/UV-K6 简写成 K5/K6。仅查询型号前缀会把
        # ``uvk6`` 漏掉，因此对短的字母+数字片段补一次包含检索，再在
        # search() 中用“型号完整/后缀/前缀”分级排序。该分支只对型号样式
        # 的查询开启，品牌中文检索仍由 FTS/字段检索处理。
        if (len(normalized) >= 2
                and re.fullmatch(r"[a-z0-9]+", normalized)
                and re.search(r"[a-z]", normalized)
                and re.search(r"\d", normalized)):
            contains_rows = self.conn.execute(
                """SELECT * FROM miit_radio_devices
                   WHERE normalized_model LIKE ?
                   ORDER BY approved_at DESC, create_time DESC
                   LIMIT ?""",
                (f"%{normalized}%", _SEARCH_CANDIDATE_LIMIT),
            ).fetchall()
            existing = {str(row["article_id"]) for row in rows}
            rows = list(rows) + [row for row in contains_rows
                                 if str(row["article_id"]) not in existing]

        if not rows and self._fts_available:
            # 申请单位、设备名称、核准代码等非型号关键词优先走 FTS，
            # 避免每次整理输入都对 20 万级正式快照执行多列 LIKE。
            terms = [
                term.replace('"', '""')
                for term in re.findall(r"[0-9A-Za-z\u4e00-\u9fff]+", str(query or ""))
            ]
            if terms:
                fts_query = " AND ".join(f'"{term}"' for term in terms)
                try:
                    rows = self.conn.execute(
                        """SELECT d.* FROM miit_radio_devices AS d
                           JOIN miit_radio_devices_fts AS f
                             ON f.article_id=d.article_id
                           WHERE miit_radio_devices_fts MATCH ?
                           ORDER BY d.approved_at DESC, d.create_time DESC
                           LIMIT ?""",
                        (fts_query, _SEARCH_CANDIDATE_LIMIT),
                    ).fetchall()
                except sqlite3.OperationalError:
                    # 兼容某些 FTS5 tokenizer/关键字组合；普通字段检索仍可用。
                    rows = []
        if not rows and len(normalized) >= 2:
            like = f"%{normalized}%"
            rows = self.conn.execute(
                """SELECT * FROM miit_radio_devices
                   WHERE LOWER(standard_name) LIKE LOWER(?)
                      OR LOWER(model) LIKE LOWER(?) OR LOWER(device_name) LIKE LOWER(?)
                      OR LOWER(applicant) LIKE LOWER(?) OR LOWER(brand) LIKE LOWER(?)
                      OR LOWER(certificate_no) LIKE LOWER(?)
                      OR LOWER(approval_code) LIKE LOWER(?) OR LOWER(cmiit_id) LIKE LOWER(?)
                   ORDER BY approved_at DESC, create_time DESC
                   LIMIT ?""",
                (like, like, like, like, like, like, like, like,
                 _SEARCH_CANDIDATE_LIMIT),
            ).fetchall()
        if allow_fuzzy and not rows and len(normalized) >= 3:
            # 最后才做型号模糊匹配。只读取轻量比较列计算分数，随后最多
            # 取 100 条完整记录，避免输入框每次防抖都搬运全部 raw_json。
            model_rows = self.conn.execute(
                "SELECT article_id, normalized_model FROM miit_radio_devices "
                "WHERE normalized_model != ''"
            ).fetchall()
            fuzzy_hits = sorted(
                (
                    fuzz.ratio(normalized, str(row["normalized_model"])),
                    str(row["article_id"]),
                )
                for row in model_rows
                if fuzz.ratio(normalized, str(row["normalized_model"]))
                >= (70 if len(normalized) <= 4 else 60)
            )
            if fuzzy_hits:
                ids = [article_id for _score, article_id in fuzzy_hits[-100:]]
                complete_rows = self.conn.execute(
                    f"SELECT * FROM miit_radio_devices WHERE article_id IN ({','.join('?' * len(ids))})",
                    tuple(ids),
                ).fetchall()
                by_id = {str(row["article_id"]): row for row in complete_rows}
                rows = [by_id[article_id] for article_id in ids if article_id in by_id]
        return [_row_dict(row) for row in rows]

    def search(self, query: str, limit: int = 3, *, allow_fuzzy: bool = True) -> list[dict]:
        """本地离线检索；不会触发任何网络请求。"""
        with self._lock:
            normalized = normalize_model(query)
            if not normalized:
                return []
            raw_query = str(query or "").strip().casefold()
            rows = self._fetch_candidates_locked(query, allow_fuzzy=allow_fuzzy)

            def rank(row: dict) -> tuple:
                model_key = str(row.get("normalized_model") or "")
                model_exact = int(model_key == normalized)
                model_suffix = int(
                    len(normalized) >= 2 and model_key.endswith(normalized)
                    and model_key != normalized
                )
                model_prefix = int(model_key.startswith(normalized))
                model_contains = int(normalized in model_key)
                searchable = (
                    row.get("standard_name"), row.get("device_name"),
                    row.get("applicant"), row.get("brand"),
                    row.get("model"), row.get("certificate_no"),
                    row.get("approval_code"), row.get("cmiit_id"),
                )
                field_exact = int(any(
                    raw_query and raw_query == str(value or "").strip().casefold()
                    for value in searchable
                ))
                field_contains = int(any(
                    _contains_casefold(value, raw_query) for value in searchable
                ))
                fuzzy_score = fuzz.ratio(normalized, model_key)
                return (
                    model_exact, model_suffix, model_prefix, model_contains,
                    field_exact, field_contains, fuzzy_score,
                    _natural_model_key(row.get("model") or model_key),
                    str(row.get("approved_at") or ""),
                    str(row.get("create_time") or ""),
                )

            grouped: dict[str, list[dict]] = {}
            active_sync_id = self._meta_locked().get("active_sync_id", "")
            for row in rows:
                grouped.setdefault(row.get("normalized_model") or normalize_model(row.get("model")), []).append(row)
            output: list[dict] = []
            for _model_key, group in grouped.items():
                best = max(
                    group,
                    key=rank,
                )
                best = dict(best)
                best["historical_count"] = len(group)
                best["miit_sync_run_id"] = active_sync_id
                best["expiry_status"] = _expiry_status(best.get("valid_for", ""))
                model_key = str(best.get("normalized_model") or "")
                searchable = (
                    best.get("standard_name"), best.get("device_name"),
                    best.get("applicant"), best.get("brand"),
                    best.get("model"), best.get("certificate_no"),
                    best.get("approval_code"), best.get("cmiit_id"),
                )
                field_match = any(
                    _contains_casefold(value, raw_query) for value in searchable
                )
                best["match_reason"] = (
                    "型号完全一致" if model_key == normalized else
                    "型号后缀匹配" if len(normalized) >= 2 and model_key.endswith(normalized)
                    else "型号前缀匹配" if model_key.startswith(normalized)
                    else "型号包含匹配" if normalized in model_key
                    or model_key in normalized
                    else "品牌/申请单位匹配" if field_match
                    else "型号模糊匹配"
                )
                output.append(best)
            output.sort(key=lambda row: tuple(
                -value if isinstance(value, (int, float)) else value
                for value in rank(row)
            ))
            try:
                requested = int(limit)
            except (TypeError, ValueError):
                requested = 3
            return output[: max(1, min(requested, CATALOG_SEARCH_MAX_LIMIT))]

    def exact_model(self, query: str) -> list[dict]:
        normalized = normalize_model(query)
        if not normalized:
            return []
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM miit_radio_devices WHERE normalized_model=? ORDER BY approved_at DESC",
                (normalized,),
            ).fetchall()
            return [_row_dict(row) for row in rows]

    def abbreviation_matches(self, query: str, limit: int = 50) -> list[dict]:
        """查找“型号本身生成的完整/后缀缩写”，不执行网络请求。

        ``exact_model`` 只能命中 ``UV-K5`` 这样的官方完整型号；现场常写
        ``K5``。这里复用同一份本地候选查询，再严格要求 query 是官方型号
        生成的缩写，避免把任意模糊包含结果当成确定设备。
        """
        normalized = normalize_model(query)
        if (len(normalized) < 2 or not re.search(r"[a-z]", normalized)
                or not re.search(r"\d", normalized)):
            return []
        with self._lock:
            candidates = self._fetch_candidates_locked(query, allow_fuzzy=False)
            matches: list[dict] = []
            seen: set[str] = set()
            for row in candidates:
                article_id = str(row["article_id"])
                if article_id in seen:
                    continue
                model = str(row["model"] or "")
                if normalized not in model_abbreviations(model):
                    continue
                seen.add(article_id)
                matches.append(_row_dict(row))
                if len(matches) >= max(1, min(int(limit), CATALOG_SEARCH_MAX_LIMIT)):
                    break
            return matches

    def article(self, article_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM miit_radio_devices WHERE article_id=?", (article_id,)
            ).fetchone()
            return _row_dict(row) if row else None
