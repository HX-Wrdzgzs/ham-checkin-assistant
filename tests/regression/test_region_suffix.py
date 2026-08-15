"""回归测试：P1-10 —— 行政区划只剥离真正行政后缀，不删名称本身字符。"""
from __future__ import annotations

import unittest

from normalizers.region_index import RegionIndex


class TestRegionNameResolution(unittest.TestCase):
    def setUp(self):
        self.ri = RegionIndex("江苏")

    def test_suffix_cases_resolve_correctly(self):
        """带区/后缀的完整区划名应解析到正确条目（不误删名称字符）。

        数据中区县名不带「区」后缀（如 市南），canonical display 相应去后缀。
        """
        for name, expect in [
            ("青岛市南区", "山东青岛市南"),
            ("青岛市北区", "山东青岛市北"),
            ("济南市中区", "山东济南市中"),
            ("山东青岛市南", "山东青岛市南"),
            ("山东青岛市北", "山东青岛市北"),
            ("山东济南市中", "山东济南市中"),
        ]:
            entries = self.ri.resolve_name(name)
            self.assertTrue(entries, f"{name} 应解析")
            self.assertIn(expect, {e.display for e in entries}, name)

    def test_unknown_district_not_corrupted(self):
        """数据未覆盖的区县（如 黑龙江大庆让胡路）不得被错误折叠，返回空即可。"""
        self.assertEqual(self.ri.resolve_name("黑龙江大庆让胡路"), [])

    def test_nanjing_nan_not_collapsed(self):
        """「南京南」不得被折叠成「南京」（回归 P1-10 安全性）。"""
        self.assertEqual(self.ri.resolve_name("南京南"), [])

    def test_full_chain(self):
        entries = self.ri.resolve_name("江苏省南京市栖霞区")
        self.assertEqual({e.display for e in entries}, {"南京栖霞"})

    def test_full_chain_with_detail(self):
        entries = self.ri.resolve_name("江苏省南京市栖霞区6楼")
        self.assertEqual({e.display for e in entries}, {"南京栖霞"})


if __name__ == "__main__":
    unittest.main()
