"""回归测试：365dt 重试（P2：Retry-After 尊重但设上限，禁止无限等待）。"""
from __future__ import annotations

import unittest
from unittest import mock

import requests

from providers.dt365 import Dt365Provider


class _Resp:
    def __init__(self, status=200, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestDt365Retry(unittest.TestCase):
    def test_retry_after_capped_at_max_wait(self):
        """Retry-After 很大时只等 retry_max_wait，不无限卡死。"""
        p = Dt365Provider("UID", retries=2, retry_delay_base=0,
                          retry_max_wait=3.0)
        calls = []
        fake = _Resp(429, {"Retry-After": "9999"})

        def _get(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return fake
            return _Resp(200, payload={"stats": 1, "list": []})

        p.session.get = _get
        with mock.patch("providers.dt365.time.sleep") as m:
            data = p.fetch_ranking()
        self.assertEqual(data["stats"], 1)
        slept = [c.args[0] for c in m.call_args_list]
        self.assertTrue(slept, "必须 sleep 后才重试")
        self.assertLessEqual(slept[0], 3.0, "等待不得超过 retry_max_wait")

    def test_retry_exhausts_then_raises(self):
        """重试耗尽后抛异常，绝不无限重试。"""
        p = Dt365Provider("UID", retries=2, retry_delay_base=0)
        p.session.get = lambda *a, **k: _Resp(500)
        with mock.patch("providers.dt365.time.sleep"):
            with self.assertRaises(requests.exceptions.RequestException):
                p.fetch_ranking()


if __name__ == "__main__":
    unittest.main()
