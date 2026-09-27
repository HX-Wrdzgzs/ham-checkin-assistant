"""本地道路/地标 QTH 资料库。

该库只保存地点名称与行政区划映射，不保存地图几何，也不参与工信部型号
库和点名主数据库。快速录入只查询本地 SQLite；地点包可以在场后导入或由
上层下载器安装，失败时不会影响点名记录。
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path


PLACE_SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_place_text(value: str) -> str:
    """地点比较键：大小写/全角兼容，去掉空白与常见标点。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s\-_—‐（）()，,。．.：:；;、/\\]+", "", text)


def _text(value) -> str:
    return str(value or "").strip()


def _aliases(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[|;,；\n]+", _text(value))
    out: list[str] = []
    for item in values:
        item = _text(item)
        if item and item not in out:
            out.append(item)
    return out


def _canonical(province: str, city: str, district: str) -> str:
    return "".join(part for part in (province, city, district) if part)


class QthPlaceCatalog:
    """地点资料库读写层；正式搜索不发起网络请求。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._fts_available = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS qth_places (
                    place_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '',
                    normalized_aliases TEXT NOT NULL DEFAULT '',
                    province TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    district TEXT NOT NULL DEFAULT '',
                    canonical_qth TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    source_record_id TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_qth_places_name
                    ON qth_places(normalized_name);
                CREATE INDEX IF NOT EXISTS idx_qth_places_admin
                    ON qth_places(province, city, district);
                CREATE TABLE IF NOT EXISTS qth_place_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self.conn.execute(
                "INSERT INTO qth_place_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO NOTHING",
                (str(PLACE_SCHEMA_VERSION),),
            )
            try:
                self.conn.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS qth_places_fts
                       USING fts5(place_id UNINDEXED, name, aliases,
                                  normalized_name, normalized_aliases,
                                  canonical_qth, province, city, district)"""
                )
            except sqlite3.OperationalError:
                self.conn.execute(
                    """CREATE TABLE IF NOT EXISTS qth_places_fts (
                       place_id TEXT PRIMARY KEY, name TEXT, aliases TEXT,
                       normalized_name TEXT, normalized_aliases TEXT,
                       canonical_qth TEXT, province TEXT, city TEXT, district TEXT)"""
                )
            row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='qth_places_fts'"
            ).fetchone()
            self._fts_available = bool(row and "VIRTUAL TABLE" in str(row[0] or "").upper())
            places = int(self.conn.execute("SELECT COUNT(*) FROM qth_places").fetchone()[0])
            indexed = int(self.conn.execute("SELECT COUNT(*) FROM qth_places_fts").fetchone()[0])
            if places != indexed:
                self._rebuild_fts_locked()

    def _rebuild_fts_locked(self) -> None:
        self.conn.execute("DELETE FROM qth_places_fts")
        self.conn.execute(
            """INSERT INTO qth_places_fts(
                place_id, name, aliases, normalized_name, normalized_aliases,
                canonical_qth, province, city, district)
               SELECT place_id, name, aliases, normalized_name, normalized_aliases,
                      canonical_qth, province, city, district
               FROM qth_places"""
        )

    def _sync_fts_rows_locked(self, rows: list[dict]) -> None:
        """只同步本次变更的地点，避免每条签到都重建整张索引。"""
        if not rows:
            return
        self.conn.executemany(
            "DELETE FROM qth_places_fts WHERE place_id=?",
            ((item["place_id"],) for item in rows),
        )
        self.conn.executemany(
            """INSERT INTO qth_places_fts(
                   place_id, name, aliases, normalized_name, normalized_aliases,
                   canonical_qth, province, city, district)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [(
                item["place_id"], item["name"], item["aliases"],
                item["normalized_name"], item["normalized_aliases"],
                item["canonical_qth"], item["province"], item["city"],
                item["district"],
            ) for item in rows],
        )

    def get_meta(self, key: str, default: str = "") -> str:
        """读取地点库同步元数据。元数据和地点记录共用同一 SQLite 文件。"""
        row = self.conn.execute(
            "SELECT value FROM qth_place_meta WHERE key=?", (str(key),)
        ).fetchone()
        return str(row[0]) if row is not None else str(default)

    def set_meta(self, key: str, value: str) -> None:
        """原子保存一项同步元数据。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO qth_place_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value or "")),
            )

    def set_meta_many(self, values: dict[str, str]) -> None:
        """一次事务保存多项同步元数据。"""
        if not values:
            return
        with self.conn:
            self.conn.executemany(
                "INSERT INTO qth_place_meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ((str(key), str(value or "")) for key, value in values.items()),
            )

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def reopen(self) -> None:
        self.close()
        self.conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._fts_available = False
        self._ensure_schema()

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM qth_places").fetchone()[0])

    def size_bytes(self) -> int:
        total = 0
        for path in (self.path, self.path.with_name(self.path.name + "-wal"),
                     self.path.with_name(self.path.name + "-shm")):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def quick_check(self) -> str:
        row = self.conn.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row else ""

    def status(self) -> dict:
        sources = self.conn.execute(
            "SELECT source, COUNT(*) AS count FROM qth_places GROUP BY source ORDER BY source"
        ).fetchall()
        row = self.conn.execute("SELECT MAX(updated_at) FROM qth_places").fetchone()
        return {
            "path": str(self.path),
            "count": self.count(),
            "size_bytes": self.size_bytes(),
            "updated_at": str(row[0] or "") if row else "",
            "sources": {str(item["source"]): int(item["count"]) for item in sources},
            "fts": self._fts_available,
            "schema_version": PLACE_SCHEMA_VERSION,
            "last_sync_at": self.get_meta("last_sync_at"),
            "last_success_at": self.get_meta("last_success_at"),
            "last_sync_status": self.get_meta("last_sync_status"),
            "last_sync_message": self.get_meta("last_sync_message"),
            "remote_etag": self.get_meta("remote_etag"),
            "remote_last_modified": self.get_meta("remote_last_modified"),
        }

    @staticmethod
    def _record(record: dict, default_source: str = "pack") -> dict | None:
        if not isinstance(record, dict):
            return None
        name = _text(record.get("name") or record.get("place_name") or record.get("address"))
        province = _text(record.get("province") or record.get("省"))
        city = _text(record.get("city") or record.get("市"))
        district = _text(record.get("district") or record.get("区") or record.get("county"))
        canonical = _text(record.get("canonical_qth") or record.get("qth"))
        if not canonical:
            canonical = _canonical(province, city, district)
        if not name or not canonical:
            return None
        aliases = _aliases(record.get("aliases") or record.get("alias"))
        source = _text(record.get("source")) or default_source
        source_record_id = _text(record.get("source_record_id") or record.get("id"))
        if not source_record_id:
            source_record_id = hashlib.sha256(
                json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:24]
        place_id = _text(record.get("place_id")) or f"{source}:{source_record_id}"
        raw_json = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "place_id": place_id,
            "name": name,
            "normalized_name": normalize_place_text(name),
            "aliases": "|".join(aliases),
            "normalized_aliases": "|".join(normalize_place_text(item) for item in aliases),
            "province": province,
            "city": city,
            "district": district,
            "canonical_qth": canonical,
            "kind": _text(record.get("kind") or record.get("type")),
            "source": source,
            "source_record_id": source_record_id,
            "source_url": _text(record.get("source_url") or record.get("url")),
            "content_hash": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            "raw_json": raw_json,
            "updated_at": _now(),
        }

    def upsert_many(self, records, *, default_source: str = "pack") -> int:
        normalized = [item for raw in records
                      if (item := self._record(raw, default_source)) is not None]
        if not normalized:
            return 0
        columns = (
            "place_id", "name", "normalized_name", "aliases", "normalized_aliases",
            "province", "city", "district", "canonical_qth", "kind", "source",
            "source_record_id", "source_url", "content_hash", "raw_json", "updated_at",
        )
        placeholders = ",".join("?" for _ in columns)
        assignments = ",".join(f"{column}=excluded.{column}" for column in columns[1:])
        with self.conn:
            for item in normalized:
                self.conn.execute(
                    f"INSERT INTO qth_places({','.join(columns)}) VALUES({placeholders}) "
                    f"ON CONFLICT(place_id) DO UPDATE SET {assignments}",
                    tuple(item[column] for column in columns),
                )
            # 只更新本次变更的索引行。若导入的是大地点包，也不会在每条
            # 用户签到时再次扫描和重建整张 FTS 表。
            self._sync_fts_rows_locked(normalized)
        return len(normalized)

    def replace_source(self, records, *, source: str) -> int:
        """原子替换一个受控来源的记录，并同步全文索引。

        只允许同步服务调用此方法。用户学习样本和手动地点包使用独立
        ``source``，不会被内置行政区或远程地点源的刷新删除。
        """
        source = _text(source)
        if not source:
            return 0
        normalized = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item["source"] = source
            record = self._record(item, source)
            if record is not None:
                normalized.append(record)
        # 同一个来源不能因为远程重复数据制造同名主键错误；保留最后一条
        # 已规范化记录，顺序稳定且不会影响其它来源。
        unique: dict[str, dict] = {}
        for item in normalized:
            unique[item["place_id"]] = item
        normalized = list(unique.values())
        columns = (
            "place_id", "name", "normalized_name", "aliases", "normalized_aliases",
            "province", "city", "district", "canonical_qth", "kind", "source",
            "source_record_id", "source_url", "content_hash", "raw_json", "updated_at",
        )
        placeholders = ",".join("?" for _ in columns)
        assignments = ",".join(f"{column}=excluded.{column}" for column in columns[1:])
        with self.conn:
            # 先从 FTS 中清理旧来源，再删除主表；整个操作在同一事务中，
            # 读线程最多看到旧快照或新快照，不会看到半套地点数据。
            self.conn.execute(
                "DELETE FROM qth_places_fts WHERE place_id IN "
                "(SELECT place_id FROM qth_places WHERE source=?)", (source,)
            )
            self.conn.execute("DELETE FROM qth_places WHERE source=?", (source,))
            if normalized:
                self.conn.executemany(
                    f"INSERT INTO qth_places({','.join(columns)}) VALUES({placeholders}) "
                    f"ON CONFLICT(place_id) DO UPDATE SET {assignments}",
                    [tuple(item[column] for column in columns) for item in normalized],
                )
                self._sync_fts_rows_locked(normalized)
        return len(normalized)

    def _like_rows(self, query: str, limit: int) -> list[dict]:
        pattern = f"%{query}%"
        rows = self.conn.execute(
            """SELECT * FROM qth_places
               WHERE normalized_name LIKE ?
                  OR normalized_aliases LIKE ?
                  OR canonical_qth LIKE ?
                  OR province LIKE ? OR city LIKE ? OR district LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, pattern,
             max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 8) -> list[dict]:
        normalized = normalize_place_text(query)
        if len(normalized) < 2:
            return []
        try:
            rows = self._like_rows(normalized, max(20, limit * 8))
        except sqlite3.Error:
            return []

        def rank(row: dict) -> tuple:
            name = str(row.get("normalized_name") or "")
            aliases = str(row.get("normalized_aliases") or "").split("|")
            exact_name = int(name == normalized)
            exact_alias = int(normalized in aliases)
            prefix = int(name.startswith(normalized) or any(a.startswith(normalized) for a in aliases))
            contains = int(normalized in name or any(normalized in a for a in aliases))
            return (exact_name, exact_alias, prefix, contains,
                    len(name), str(row.get("name") or ""))

        rows.sort(key=rank, reverse=True)
        output: list[dict] = []
        for row in rows:
            item = dict(row)
            score = rank(row)
            item["match_score"] = score[0] * 100 + score[1] * 95 + score[2] * 80 + score[3] * 60
            item["match_reason"] = (
                "地点名称完全一致" if score[0] else
                "地点别名完全一致" if score[1] else
                "地点名称前缀匹配" if score[2] else "地点名称包含匹配"
            )
            output.append(item)
        return output[:max(1, min(int(limit), 50))]

    def resolve_unique(self, query: str) -> dict | None:
        """仅对名称/别名唯一精确命中自动解析；模糊命中必须由用户选择。"""
        normalized = normalize_place_text(query)
        if len(normalized) < 2:
            return None
        # 现场解析的热路径只需要“完全命中”。先走名称索引，避免每输入
        # 一条道路都对整张地点表做 ``%query%`` 扫描；别名再用边界匹配，
        # 防止把 ``人民路``误命中为 ``人民路口``。
        pattern_start = f"{normalized}|%"
        pattern_middle = f"%|{normalized}|%"
        pattern_end = f"%|{normalized}"
        rows = self.conn.execute(
            """SELECT * FROM qth_places
               WHERE normalized_name=?
                  OR normalized_aliases=?
                  OR normalized_aliases LIKE ?
                  OR normalized_aliases LIKE ?
                  OR normalized_aliases LIKE ?""",
            (normalized, normalized, pattern_start, pattern_middle, pattern_end),
        ).fetchall()
        exact = [dict(row) for row in rows]
        if len(exact) == 1:
            return exact[0]
        return None

    def import_file(self, path: Path | str, *, source: str = "pack") -> int:
        """导入 JSON/JSONL/CSV 地点包；不删除已有地点。"""
        target = Path(path)
        suffix = target.suffix.casefold()
        if suffix == ".zip":
            with zipfile.ZipFile(target) as archive:
                names = [name for name in archive.namelist()
                         if name.casefold().endswith((".jsonl", ".ndjson", ".json", ".csv"))]
                if not names:
                    return 0
                with archive.open(names[0], "r") as stream:
                    with io.TextIOWrapper(stream, encoding="utf-8-sig") as text_stream:
                        return self._import_stream(text_stream, names[0], source)
        if suffix == ".gz":
            with gzip.open(target, "rt", encoding="utf-8-sig") as stream:
                return self._import_stream(stream, target.stem, source)
        with target.open("r", encoding="utf-8-sig", newline="") as stream:
            return self._import_stream(stream, target.name, source)

    def replace_file(self, path: Path | str, *, source: str) -> int:
        """解析完整地点包后原子替换一个受控来源。

        远程同步不能沿用 ``import_file`` 的分批追加语义：文件尾部损坏或
        JSONL 中途出现坏行时，旧版本若已写入前几批就会留下半包。这里先让
        ``replace_source`` 完整消费并规范化输入，只有全部解析成功才开启
        删除/插入事务；解析失败时正式来源保持不变。
        """
        target = Path(path)
        suffix = target.suffix.casefold()
        if suffix == ".zip":
            with zipfile.ZipFile(target) as archive:
                names = [name for name in archive.namelist()
                         if name.casefold().endswith((".jsonl", ".ndjson", ".json", ".csv"))]
                if not names:
                    return 0
                with archive.open(names[0], "r") as stream:
                    with io.TextIOWrapper(stream, encoding="utf-8-sig") as text_stream:
                        return self.replace_source(
                            self._records_from_stream(text_stream, names[0]), source=source
                        )
        if suffix == ".gz":
            with gzip.open(target, "rt", encoding="utf-8-sig") as stream:
                return self.replace_source(
                    self._records_from_stream(stream, target.stem), source=source
                )
        with target.open("r", encoding="utf-8-sig", newline="") as stream:
            return self.replace_source(
                self._records_from_stream(stream, target.name), source=source
            )

    def _import_text(self, text: str, name: str, source: str) -> int:
        """兼容内存文本调用方；文件导入优先走流式路径。"""
        return self._import_stream(io.StringIO(text), name, source)

    @staticmethod
    def _records_from_stream(stream, name: str):
        """从已打开的地点包流产生原始记录；解析异常交给调用方处理。"""
        lower = str(name).casefold()
        if lower.endswith(".csv"):
            return csv.DictReader(stream)
        if lower.endswith((".jsonl", ".ndjson")):
            return (json.loads(line) for line in stream if line.strip())
        payload = json.load(stream)
        return payload.get("places", []) if isinstance(payload, dict) else payload

    def _import_stream(self, stream, name: str, source: str) -> int:
        lower = str(name).casefold()
        if lower.endswith(".csv"):
            records = csv.DictReader(stream)
        elif lower.endswith((".jsonl", ".ndjson")):
            records = (json.loads(line) for line in stream if line.strip())
        else:
            # JSON 数组本身需要由标准库一次解码；推荐大地点包使用
            # JSONL/CSV，此两种格式会按小批次流式导入。
            payload = json.load(stream)
            records = payload.get("places", []) if isinstance(payload, dict) else payload
        if not isinstance(records, list) and not hasattr(records, "__iter__"):
            return 0
        total = 0
        batch: list[dict] = []
        for record in records:
            batch.append(record)
            if len(batch) >= 1000:
                total += self.upsert_many(batch, default_source=source)
                batch.clear()
        if batch:
            total += self.upsert_many(batch, default_source=source)
        return total
