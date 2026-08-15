"""回归测试：同步线程生命周期（任务书第二阶段 #21~#23）。

- 同一时间只允许一个同步任务（服务级锁）。
- _SyncWorker.run 总异常保护：异常也必须发 done。
"""
from __future__ import annotations

import unittest

from tests.helpers import make_service


class _BlockingProvider:
    """fetch_ranking 抛异常或空；用于验证锁与异常路径。"""
    name = "365dt"
    uid = "UID_T"

    def __init__(self, mode="empty"):
        self.mode = mode
        self.max_fetch = 10

    def fetch_ranking(self):
        if self.mode == "error":
            raise RuntimeError("boom")
        return {"stats": 0, "list": []}

    def fetch_many_stats(self, callsigns, progress=None):
        return []


class TestSyncLifecycle(unittest.TestCase):
    def test_sync_in_progress_rejects_concurrent(self):
        """同步进行中再次触发必须被拒绝（不新开线程）。"""
        svc = make_service()
        try:
            svc._sync_in_progress = True  # 模拟已有任务在跑
            res = svc.sync_365dt()
            self.assertFalse(res["ok"])
            self.assertIn("同步正在进行", res["message"])
        finally:
            svc.close()

    def test_sync_releases_lock_after_run(self):
        """同步结束后锁必须释放（finally）。"""
        svc = make_service()
        try:
            # 用会抛异常的模式验证 finally 释放锁
            import tempfile
            from pathlib import Path

            from database.db import connect
            from database.repository import Repository
            from database.seed import seed_default_aliases
            from normalizers.dictionaries import AliasStore
            from normalizers.region_index import RegionIndex
            from services.standardizer import Standardizer
            from services.sync_service import SyncService

            tmp = Path(tempfile.mkdtemp())
            conn = connect(tmp / "t.db")
            repo = Repository(conn)
            seed_default_aliases(repo)
            std = Standardizer(AliasStore(repo), RegionIndex("江苏"))
            svc.sync_service = SyncService(repo, _BlockingProvider(mode="error"), std)
            res = svc.sync_365dt()
            self.assertFalse(res["ok"])
            self.assertFalse(svc._sync_in_progress, "异常后锁必须释放")
            # 释放后可再次同步（不报“正在进行”）
            svc.sync_service = SyncService(repo, _BlockingProvider(mode="empty"), std)
            res2 = svc.sync_365dt()
            self.assertTrue(res2["ok"], res2)
            self.assertFalse(svc._sync_in_progress)
            conn.close()
        finally:
            svc.close()


class TestSyncWorker(unittest.TestCase):
    def test_worker_run_emits_done_on_exception(self):
        """worker.run 异常时也必须发出 done（UI 永远能恢复）。"""
        from unittest.mock import patch

        from tests.helpers import make_settings
        from ui.worker_manager import SyncWorker

        settings, _tmp = make_settings()
        w = SyncWorker(settings)
        emitted = []

        def on_done(result):
            emitted.append(result)

        w.done.connect(on_done)
        with patch("ui.worker_manager.build_standalone_sync",
                   side_effect=RuntimeError("worker boom")):
            w.run()  # 直接调用 run（同步路径），不依赖 Qt 事件循环
        self.assertEqual(len(emitted), 1, "异常也必须发出 done")
        self.assertFalse(emitted[0]["ok"])


class TestWorkerManager(unittest.TestCase):
    def test_submit_rejects_when_busy(self):
        """WorkerManager 同一时间只允许一个任务（P1-3）。"""
        from unittest.mock import MagicMock

        from tests.helpers import make_settings
        from ui.worker_manager import WorkerManager

        settings, _tmp = make_settings()
        mgr = WorkerManager(settings)
        fake = MagicMock()
        fake.isRunning.return_value = True
        mgr._current = fake  # 模拟已有任务在跑
        ok = mgr.submit_sync(lambda r: None)
        self.assertFalse(ok, "已有任务时必须拒绝")
        mgr.shutdown()  # 不阻塞（fake 已结束）
        self.assertFalse(mgr.busy())


if __name__ == "__main__":
    unittest.main()
