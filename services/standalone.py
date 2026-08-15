"""后台 worker 独立数据栈（P1-2：worker 使用自己的 SQLite connection，不共享主连接）。

UI 线程用 AppService 的主 Repository；365dt/import 等 worker 用这里构建的
独立 connection + Repository + SyncService，WAL 下可安全并发读写同一库文件。
"""
from __future__ import annotations

from database.db import connect
from database.repository import Repository
from database.seed import seed_default_aliases
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from providers.dt365 import Dt365Provider
from services.standardizer import Standardizer
from services.sync_service import SyncService


def build_standalone_sync(settings):
    """构建 worker 用的独立同步服务。

    返回 (SyncService, conn)；调用方必须在结束后关闭 conn（worker 自己负责）。
    """
    conn = connect(settings.db_path)
    repo = Repository(conn)
    seed_default_aliases(repo)
    store = AliasStore(repo)
    region = RegionIndex(settings.get("default_province", "江苏"))
    std = Standardizer(store, region)
    provider = Dt365Provider(
        settings.get("dt365_uid", ""),
        max_fetch=int(settings.get("dt365_max_fetch", 200)),
    )
    return SyncService(repo, provider, std), conn
