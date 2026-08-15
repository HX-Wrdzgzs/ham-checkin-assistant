"""回归测试：P1-14 —— 设置保存后立即应用运行时（不出现 JSON 新值 / runtime 旧值）。"""
from __future__ import annotations

import unittest

from tests.helpers import make_service


class TestSettingsHotUpdate(unittest.TestCase):
    def setUp(self):
        self.svc = make_service()

    def tearDown(self):
        self.svc.close()

    def test_fuzzy_thresholds_apply(self):
        self.svc.settings.set("fuzzy_high", 96.0)
        self.svc.settings.set("fuzzy_mid", 80.0)
        self.svc.settings.set("fuzzy_margin", 6.0)
        self.svc.apply_runtime_settings()
        self.assertEqual(self.svc.parser.fuzzy_high, 96.0)
        self.assertEqual(self.svc.parser.fuzzy_mid, 80.0)
        self.assertEqual(self.svc.parser.fuzzy_margin, 6.0)

    def test_dt365_provider_recreated(self):
        self.svc.settings.set("dt365_uid", "NEW_UID")
        self.svc.settings.set("dt365_max_fetch", 300)
        self.svc.apply_runtime_settings()
        self.assertEqual(self.svc.sync_service.provider.uid, "NEW_UID")
        self.assertEqual(self.svc.sync_service.provider.max_fetch, 300)

    def test_default_province_rebuilds_region(self):
        self.svc.settings.set("default_province", "安徽")
        self.svc.apply_runtime_settings()
        self.assertEqual(self.svc.region.default_province, "安徽")

    def test_runtime_matches_config(self):
        """保存后 runtime 与 config 一致（P1-14 核心不变量）。"""
        self.svc.settings.set_many(fuzzy_high=95.0, dt365_uid="U2")
        self.svc.apply_runtime_settings()
        self.assertEqual(self.svc.parser.fuzzy_high,
                         float(self.svc.settings.get("fuzzy_high")))
        self.assertEqual(self.svc.sync_service.provider.uid,
                         self.svc.settings.get("dt365_uid"))


if __name__ == "__main__":
    unittest.main()
