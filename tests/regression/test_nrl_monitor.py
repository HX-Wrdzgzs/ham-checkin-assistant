"""回归测试：NRL Nanny 只读监听（第四阶段）。

覆盖：网络超时 / 连接重置 / 非法响应 / 空活动 / 请求中停止 / 应用退出期间停止。
核心不变量：**绝不写数据库、绝不自动提交**（本模块无任何 DB 依赖）。
"""
from __future__ import annotations

import threading
import time
import unittest

import requests

from providers.nrl_nanny import NrlNannyProvider, parse_activity
from services.monitor_service import (
    DEGRADED, ERROR, OFFLINE, ONLINE, MonitorService,
)

RAW_OK = "20:00 BG4TKI 南京栖霞 K6 | 20:01 BA4XXX 徐州鼓楼 | noise"


class _Resp:
    def __init__(self, text="", status=200, headers=None):
        self.text = text
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class TestNrlProvider(unittest.TestCase):
    def test_extract_candidates(self):
        p = NrlNannyProvider()
        cands = p._extract_candidates(RAW_OK)
        self.assertIn("BG4TKI", cands)
        self.assertIn("BA4XXX", cands)
        self.assertEqual(len(cands), 2, "保序去重")

    def test_empty_activity(self):
        """空活动：正常返回无候选，不报错。"""
        p = NrlNannyProvider(url="http://x")
        p.session.get = lambda *a, **k: _Resp(text="")
        res = p.fetch()
        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], [])
        self.assertEqual(parse_activity(""), [])

    def test_json_activity(self):
        entries = parse_activity('{"list":[{"callsign":"bg4tki","time":"20:00"},'
                                 '{"callsign":"not-a-call","time":"20:01"}]}')
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["callsign"], "BG4TKI")

    def test_invalid_response_raises(self):
        """非法响应（HTTP 500）→ raise_for_status 抛异常（映射为 error）。"""
        p = NrlNannyProvider(url="http://x")
        p.session.get = lambda *a, **k: _Resp(text="boom", status=500)
        with self.assertRaises(requests.exceptions.HTTPError):
            p.fetch()


class TestMonitorService(unittest.TestCase):
    def _svc(self, fetch_result):
        svc = MonitorService(url="http://x", poll_interval=1.0, timeout=2.0,
                             max_retries=1)
        p = svc.provider
        if isinstance(fetch_result, Exception):
            def _fail(*a, **k):
                raise fetch_result
            p.fetch = _fail
        else:
            def _ok(*a, **k):
                return fetch_result
            p.fetch = _ok
        return svc

    def test_online_and_candidates_callback(self):
        svc = self._svc({"ok": True, "raw": RAW_OK, "candidates": ["BG4TKI", "BA4XXX"],
                         "error": ""})
        states = []
        cands = []
        svc.on_state = lambda s, m: states.append(s)
        svc.on_candidates = lambda c: cands.append(c)
        try:
            svc.start()
            time.sleep(0.5)
        finally:
            svc.stop()
        self.assertEqual(svc.state, OFFLINE, "stop 后必须回到 offline")
        self.assertIn(ONLINE, states, "应经历 online 状态")
        self.assertTrue(any("BG4TKI" in c for c in cands), "候选呼号必须回调")

    def test_timeout_maps_to_degraded_then_error(self):
        svc = MonitorService(url="http://x", poll_interval=1.0, timeout=2.0,
                             max_retries=2)

        def _fail(*a, **k):
            raise requests.Timeout("t")
        svc.provider.fetch = _fail
        states = []
        svc.on_state = lambda s, m: states.append(s)
        try:
            svc.start()
            time.sleep(1.6)  # degraded(~0s) → 等 1s → error(~1.1s)
        finally:
            svc.stop()
        self.assertIn(DEGRADED, states, "超时应先 degraded（重试阈值内）")
        self.assertIn(ERROR, states, "重试耗尽应进入 error")

    def test_connection_reset_maps_to_error(self):
        svc = self._svc(requests.ConnectionError("reset"))
        svc.max_retries = 1
        states = []
        svc.on_state = lambda s, m: states.append(s)
        try:
            svc.start()
            time.sleep(0.6)
        finally:
            svc.stop()
        self.assertTrue(any(s in (DEGRADED, ERROR) for s in states),
                        "连接重置必须进入 degraded/error")

    def test_stop_during_request_does_not_hang(self):
        """请求进行中调用 stop：必须快速返回（socket timeout 有限，join 安全）。"""
        svc = self._svc({"ok": True, "raw": "", "candidates": [], "error": ""})
        # 让 fetch 阻塞到 stop 信号
        started = threading.Event()
        release = threading.Event()

        def _blocking(*a, **k):
            started.set()
            release.wait(5)
            return {"ok": True, "raw": "BG4TKI", "candidates": ["BG4TKI"], "error": ""}
        svc.provider.fetch = _blocking
        try:
            svc.start()
            self.assertTrue(started.wait(2), "fetch 必须已开始")
            t0 = time.monotonic()
            svc.stop()
            # stop 的 join 上限 = max(3.0, timeout+1)≈3s，绝不无限等待
            self.assertLess(time.monotonic() - t0, 4.0, "stop 不得悬挂")
            self.assertEqual(svc.state, OFFLINE)
        finally:
            release.set()
            svc.stop()

    def test_app_exit_during_monitor(self):
        """应用退出期间 stop：线程安全退出，无异常泄漏。"""
        svc = self._svc({"ok": True, "raw": "BG4TKI", "candidates": ["BG4TKI"],
                         "error": ""})
        svc.start()
        time.sleep(0.3)
        svc.stop()  # 模拟 app.aboutToQuit → release → service.close 路径
        self.assertEqual(svc.state, OFFLINE)

    def test_monitor_never_writes_db(self):
        """只读不变量：MonitorService 不含任何 DB 引用/写入路径。"""
        svc = MonitorService(url="")
        self.assertFalse(hasattr(svc, "repo"), "不得持有 DB 仓库")
        self.assertFalse(hasattr(svc, "conn"), "不得持有 DB 连接")
        self.assertIsNone(svc.provider.repo if hasattr(svc.provider, "repo") else None)


if __name__ == "__main__":
    unittest.main()
