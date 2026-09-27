"""QTH 地点补全服务。

服务层把地点库的本地检索、唯一命中规则和用户确认后的学习分开，确保
输入框不会隐式联网，也不会把模糊候选直接写进点名记录。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from database.qth_places import QthPlaceCatalog, normalize_place_text


class QthPlaceService:
    def __init__(self, catalog: QthPlaceCatalog) -> None:
        self.catalog = catalog

    def search(self, query: str, limit: int = 8) -> list[dict]:
        return self.catalog.search(query, limit=limit)

    def resolve(self, query: str) -> dict | None:
        """返回唯一精确地点；多个同名道路永不静默选择。"""
        return self.catalog.resolve_unique(query)

    def learn(self, raw: str, canonical_qth: str, *, kind: str = "learned") -> bool:
        """保存用户已经确认过的地点映射，供以后离线补全。"""
        raw = str(raw or "").strip()
        canonical_qth = str(canonical_qth or "").strip()
        if len(normalize_place_text(raw)) < 2 or not canonical_qth:
            return False
        key = hashlib.sha256(
            f"{normalize_place_text(raw)}\n{canonical_qth}".encode()
        ).hexdigest()[:24]
        return bool(self.catalog.upsert_many([{
            "place_id": f"learned:{key}",
            "name": raw,
            "aliases": [raw],
            "canonical_qth": canonical_qth,
            "kind": kind,
            "source": "learned",
            "source_record_id": key,
        }], default_source="learned"))

    def import_pack(self, path: Path | str, *, source: str = "pack") -> int:
        return self.catalog.import_file(path, source=source)

    def status(self) -> dict:
        return self.catalog.status()

    def close(self) -> None:
        self.catalog.close()
