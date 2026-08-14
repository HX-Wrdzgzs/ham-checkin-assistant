"""回归测试：模糊 margin（任务书第二阶段 #5）。

规则：仅当 top1>=high 且 top1-top2>=min_margin 才自动接受；
分差不足 → 强制 candidates，禁止自信地猜错。
"""
from __future__ import annotations

import unittest

from core.fuzzy_resolver import fuzzy_resolve, fuzzy_resolve_pinyin


class TestFuzzyMargin(unittest.TestCase):
    def test_clear_winner_can_auto_accept(self):
        """唯一高分 → 自动接受（high）。"""
        opts = [("nanjing", "南京"), ("wuxi", "无锡"), ("suzhou", "苏州")]
        level, hits = fuzzy_resolve("nanjng", opts, high=92.0, mid=75.0, min_margin=5.0)
        self.assertEqual(level, "high")
        self.assertEqual(hits[0][2], "南京")

    def test_close_scores_require_confirmation(self):
        """top1 与 top2 分差不足 → 强制候选（mid）。"""
        # 构造两个高度相近的 key（只差一位，都与 token 高度相似）
        opts = [("abcd", "A"), ("abce", "B")]
        level, hits = fuzzy_resolve("abcf", opts, high=92.0, mid=75.0, min_margin=8.0)
        self.assertEqual(level, "mid", "分差不足必须强制候选")
        self.assertEqual(len(hits), 2)

    def test_margin_ignored_when_only_one_match(self):
        """只有一个匹配 → 无歧义，自动接受。"""
        opts = [("wuxi", "无锡")]
        level, hits = fuzzy_resolve("wixi", opts, high=70.0, mid=50.0, min_margin=5.0)
        self.assertEqual(level, "high")
        self.assertEqual(hits[0][2], "无锡")

    def test_pinyin_close_scores_require_confirmation(self):
        """拼音模糊同样受 margin 约束。"""
        opts = [("k1", "甲", "abcd", 0.0), ("k2", "乙", "abce", 0.0)]
        level, hits = fuzzy_resolve_pinyin("abcf", opts, high=92.0, mid=75.0,
                                           min_margin=8.0)
        self.assertEqual(level, "mid", "拼音分差不足必须强制候选")
        self.assertEqual(len(hits), 2)

    def test_pinyin_clear_winner_auto_accept(self):
        opts = [("nj", "南京", "nanjing", 3.0), ("yz", "扬州", "yangzhou", 0.0),
                ("xz", "徐州", "xuzhou", 0.0)]
        level, hits = fuzzy_resolve_pinyin("nanjing", opts, high=92.0, mid=75.0,
                                           min_margin=5.0)
        self.assertEqual(level, "high")
        self.assertEqual(hits[0][2], "南京")


if __name__ == "__main__":
    unittest.main()
