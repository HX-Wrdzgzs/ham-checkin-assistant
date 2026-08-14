"""回归测试：时间规范化（任务书第三阶段 #6）。

数据库统一 YYYY-MM-DDTHH:MM:SS；Excel 的 2000 / 20:00 / 20:00:00 / datetime 单元格全标准化。
"""
from __future__ import annotations

import unittest

from core.datetime_util import normalize_checkin_time, normalize_time_token


class TestDatetimeCanonical(unittest.TestCase):
    def test_time_token_forms(self):
        self.assertEqual(normalize_time_token("2000"), "20:00:00")
        self.assertEqual(normalize_time_token("20:00"), "20:00:00")
        self.assertEqual(normalize_time_token("20:00:00"), "20:00:00")
        self.assertIsNone(normalize_time_token("abc"))
        self.assertIsNone(normalize_time_token(""))

    def test_checkin_time_canonical(self):
        self.assertEqual(normalize_checkin_time("2026-08-08", "2000"),
                         "2026-08-08T20:00:00")
        self.assertEqual(normalize_checkin_time("2026-08-08", "20:00"),
                         "2026-08-08T20:00:00")
        self.assertEqual(normalize_checkin_time("2026-08-08", "20:00:00"),
                         "2026-08-08T20:00:00")
        # 缺时间 → 00:00:00；缺日期 → 用今天（只验证格式）
        t1 = normalize_checkin_time("2026-08-08", "")
        self.assertEqual(t1, "2026-08-08T00:00:00")
        t2 = normalize_checkin_time("", "20:00")
        self.assertRegex(t2, r"^\d{4}-\d{2}-\d{2}T20:00:00$")

    def test_excel_datetime_cell(self):
        """Excel datetime 单元格读回（'2026-08-08 20:00:00'）从中取日期+时间。"""
        self.assertEqual(normalize_checkin_time("", "2026-08-08 20:00:00"),
                         "2026-08-08T20:00:00")
        self.assertEqual(normalize_checkin_time("", "2026/8/8 20:00"),
                         "2026-08-08T20:00:00")

    def test_no_legacy_time_mix(self):
        """禁止库中同时存在 20:00 / 2000 / 2026-08-13T20:00 三种形态。"""
        a = normalize_checkin_time("2026-08-13", "2000")
        b = normalize_checkin_time("2026-08-13", "20:00")
        c = normalize_checkin_time("2026-08-13", "20:00:00")
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        self.assertEqual(c, "2026-08-13T20:00:00")


if __name__ == "__main__":
    unittest.main()
