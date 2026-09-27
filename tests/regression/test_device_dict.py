"""回归测试：P1-11 —— 默认设备词典只保留可靠映射。

- 已验证机型可解析。
- 不确定的映射（x6200 / u7 / n7500）不得再写死。
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
            "r6": "摩托罗拉 R6",
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
        for alias in ("x6200", "u7", "n7500"):
            self.assertIsNone(self.store.lookup("device", alias),
                              f"{alias} 映射不确定，不得硬编码")
            r = self.svc.parse(alias)
            self.assertEqual(r.device.value, "", f"{alias} 不应被当作设备解析")

    def test_devices_from_supplied_roster_have_shortcuts(self):
        """用户提供的名单样本中的设备缩写应可直接复用。"""
        verified = {
            "m8268": "摩托罗拉 M8268",
            "m8668": "摩托罗拉 M8668",
            "p8260": "摩托罗拉 P8260",
            "r7": "摩托罗拉 R7",
            "shk8800": "森海克斯 SHK-8800",
            "tm481": "建武TM-481",
            "tm8118": "TM-8118",
            "tm800": "HYT-TM800",
            "uvk6": "泉盛 UV-K6",
            "uvk18": "泉盛 UV-K1(8)",
            "uv5rmini": "宝锋 UV-5R Mini",
            "1907r": "YAESU FT-1907R",
            "5dr": "YAESU FT-5DR",
        }
        for alias, standard in verified.items():
            item = self.store.lookup("device", alias)
            self.assertIsNotNone(item, f"{alias} 应已收录")
            self.assertEqual(item.standard_value, standard)
            result = self.svc.parse(f"BA4AAA {alias}")
            self.assertEqual(result.device.value, standard, alias)
            self.assertEqual(result.unmatched, [], alias)
            self.assertIn((standard, alias), self.svc.complete(alias), alias)

    def test_roster_brand_and_model_forms_are_normalized(self):
        """名单中的带品牌写法和无空格写法不能落到未识别。"""
        cases = {
            "BA4AAA 摩托罗拉 M8268": "摩托罗拉 M8268",
            "BA4AAA 森海克斯 SHK-8800": "森海克斯 SHK-8800",
            "BA4AAA 建武 TM-481": "建武TM-481",
            "BA4AAA 建武TM-481": "建武TM-481",
            "BA4AAA 泉盛 UV-K1(8)": "泉盛 UV-K1(8)",
            "BA4AAA HYT-TM800": "HYT-TM800",
        }
        for text, standard in cases.items():
            result = self.svc.parse(text)
            self.assertEqual(result.device.value, standard, text)
            self.assertEqual(result.unmatched, [], text)

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
