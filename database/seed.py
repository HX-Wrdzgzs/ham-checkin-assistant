"""首次启动时向数据库写入默认词典（仅当对应表为空时）。"""
from __future__ import annotations

from database.repository import Repository
from normalizers.alias_defaults import (
    ANTENNA_ALIASES, DEVICE_ALIASES, POWER_ALIASES, QTH_ALIASES,
)


def seed_default_aliases(repo: Repository) -> None:
    """内置默认别名：缺失即插入（source=default），已有默认值随版本更新，不动用户自建。

    同时清理已退役的默认别名（source=default 且不在当前默认表中），如旧版 baofeng。
    """
    current = {
        "device": {a.strip().lower() for a, _ in DEVICE_ALIASES},
        "antenna": {a.strip().lower() for a, _ in ANTENNA_ALIASES},
        "power": {a.strip().lower() for a, _ in POWER_ALIASES},
        "qth": {a.strip().lower() for a, *_ in QTH_ALIASES},
    }
    for kind in ("device", "antenna", "power", "qth"):
        for a in repo.get_aliases(kind):
            if a.source == "default" and a.alias not in current[kind]:
                repo.delete_alias(kind, a.alias)

    for alias, std in DEVICE_ALIASES:
        repo.upsert_default_alias("device", alias, std)
    for alias, std in ANTENNA_ALIASES:
        repo.upsert_default_alias("antenna", alias, std)
    for alias, std in POWER_ALIASES:
        repo.upsert_default_alias("power", alias, std)
    for alias, prov, city, dist, std in QTH_ALIASES:
        repo.upsert_default_alias("qth", alias, std, province=prov, city=city, district=dist)
