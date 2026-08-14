"""回归测试：呼号规则强化（任务书第二阶段 #8）。

- 接受 BA4XXX/P、BA4XXX/4、BA4XXX/M
- 拒绝 ///、A///、////
- / 后缀：主体必须合法 + 后缀合法
"""
from __future__ import annotations

import unittest

from normalizers.callsign import normalize_callsign
from tests.helpers import make_service


class TestNormalizeCallsign(unittest.TestCase):
    def test_accept_portable_suffix(self):
        for s in ("BA4XXX/P", "BA4XXX/4", "BA4XXX/M"):
            std, valid, issues = normalize_callsign(s)
            self.assertEqual(std, s)
            self.assertTrue(valid, f"{s} 应合法：{issues}")

    def test_reject_bad_slash_forms(self):
        for s in ("///", "A///", "////", "BA4XXX/", "/BA4XXX"):
            std, valid, _ = normalize_callsign(s)
            self.assertFalse(valid, f"{s} 必须拒绝")

    def test_reject_bad_suffix(self):
        _, valid, issues = normalize_callsign("BA4XXX/TOOLONGSUFFIX")
        self.assertFalse(valid)


class TestParserCallsignRule(unittest.TestCase):
    def test_parser_accepts_valid_slash(self):
        svc = make_service()
        try:
            for s in ("ba4xxx/p", "ba4xxx/4", "ba4xxx/m"):
                r = svc.parse(s)
                self.assertEqual(r.callsign.value, s.upper(), s)
        finally:
            svc.close()

    def test_parser_rejects_bad_slash(self):
        svc = make_service()
        try:
            for s in ("///", "A///", "////"):
                r = svc.parse(s)
                self.assertEqual(r.callsign.value, "", f"{s} 不得被当作呼号")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
