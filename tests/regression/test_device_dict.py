"""回归测试：P1-11 —— 默认设备词典只保留可靠映射。

- 已验证机型可解析。
- 不确定的映射（x6200 / u7 / n7500 / m8268）不得再写死。
"""
from __future__ import annotations

import unittest

from tests.helpers import make_service


def _store():
    svc = make_service()
    return svc.store, svc


class TestDeviceDict(unittest.TestCase):
    def setUp(self):
        self.store, self.svc = _store()

    def tearDown(self):
        self.svc.close()

    def test_verified_mappings_resolve(self):
        verified = {
            "k6": "泉盛 UV-K6",
            "id52": "ICOM ID-52 PLUS",
            "ft1907r": "YAESU FT-1907R",
            "857": "YAESU FT-857D",
            "p8668": "摩托罗拉 P8668",  # Motorola XiR P8668 真实型号
            "uv5r": "宝锋 UV-5R",
            "zyt": "自由通",
            "qyt": "全易通",
            "qyt6900": "全易通 QYT-6900",
        }
        for alias, std in verified.items():
            a = self.store.lookup("device", alias)
            self.assertIsNotNone(a, f"{alias} 应已收录")
            self.assertEqual(a.standard_value, std)
            # 整句解析也应识别（zyt/qyt 不被误判为呼号/其他字段）
            r = self.svc.parse(f"bg4tki {alias}")
            self.assertEqual(r.device.value, std, f"{alias} 应解析为 {std}")

    def test_unreliable_mappings_removed(self):
        """manufacturer/model 不确定的映射不得写死。"""
        for alias in ("x6200", "u7", "n7500", "m8268"):
            self.assertIsNone(self.store.lookup("device", alias),
                              f"{alias} 映射不确定，不得硬编码")
            r = self.svc.parse(alias)
            self.assertEqual(r.device.value, "", f"{alias} 不应被当作设备解析")

    def test_common_chinese_brands(self):
        """国产对讲机常见缩写（品牌拼音首字母 + 常见型号）。"""
        verified = {
            "tyt": "特易通",
            "lt": "灵通",
            "wx": "欧讯",
            "hyt": "海能达",
            "qs": "泉盛",
            "quansheng": "泉盛",
            "baofeng": "宝锋",
            "hytera": "海能达",
            "wouxun": "欧讯",
            "zastone": "即时通",
            "kirisun": "科立讯",
            "bfdx": "北峰",          # bf 归宝锋，北峰用 bfdx
            "talkpod": "拓朋",
            "beebest": "极蜂",
            "uv2": "泉盛 TG-UV2",
            "uv6r": "泉盛 UV-6R",
            "uvk5": "泉盛 UV-K5",
            "bf888": "宝锋 BF-888S",
            "lt6600": "灵通 LT-6600",
            "kguv8d": "欧讯 KG-UV8D",
            "pd780": "海能达 PD-780",
            "pd980": "海能达 PD-980",
            "bf5111": "北峰 BF-5111",
            "md380": "特易通 MD-380",
            "th9800": "特易通 TH-9800",
        }
        for alias, std in verified.items():
            a = self.store.lookup("device", alias)
            self.assertIsNotNone(a, f"{alias} 应已收录")
            self.assertEqual(a.standard_value, std)
            r = self.svc.parse(f"bg4tki {alias}")
            self.assertEqual(r.device.value, std, f"{alias} 应解析为 {std}")

    def test_bf_belongs_to_baofeng_not_beifeng(self):
        """bf 是宝锋（Baofeng），北峰不得抢占 bf（避免两品牌歧义）。"""
        a = self.store.lookup("device", "bf")
        self.assertIsNotNone(a)
        self.assertEqual(a.standard_value, "宝锋")
        r = self.svc.parse("bg4tki bf")
        self.assertEqual(r.device.value, "宝锋")
        # 北峰必须用 bfdx/beifeng，不能用 bf
        self.assertEqual(self.store.lookup("device", "bfdx").standard_value, "北峰")

    def test_888_is_device_not_power(self):
        """888 是宝锋 BF-888S（设备），不应被当作 888W 功率。"""
        a = self.store.lookup("device", "888")
        self.assertIsNotNone(a)
        r = self.svc.parse("bg4tki 888")
        self.assertEqual(r.device.value, "宝锋 BF-888S")
        self.assertEqual(r.power.value, "", "888 不得误判为功率")


if __name__ == "__main__":
    unittest.main()
