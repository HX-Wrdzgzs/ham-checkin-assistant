"""回归测试：Settings 原子写 + schema 校验（任务书第三阶段 #16/#17）。

- 保存走 tmp → fsync → 原子替换，不留 .tmp 残留。
- 保存失败必须返回 False（UI 提示，不假装成功）。
- fuzzy_mid < fuzzy_high 等 schema 校验。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings


class TestSettingsAtomic(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_cfg_"))

    def test_config_atomic_write(self):
        """原子写：保存后配置存在、内容正确、无 .tmp 残留。"""
        p = self.tmp / "config.json"
        s = Settings(path=p)
        ok = s.set_many(default_province="安徽", fuzzy_high=95.0)
        self.assertTrue(ok)
        self.assertTrue(p.exists())
        self.assertFalse((self.tmp / "config.json.tmp").exists(), "不得残留 .tmp")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["default_province"], "安徽")
        self.assertEqual(data["fuzzy_high"], 95.0)

    def test_config_save_returns_error(self):
        """保存失败必须返回 False（父目录不可写）。"""
        blocker = self.tmp / "blocker"
        blocker.write_bytes(b"i am a file")
        p = blocker / "config.json"  # 父路径是文件 → mkdir 失败
        s = Settings(path=p)
        ok = s.set("default_province", "安徽")
        self.assertFalse(ok, "保存失败必须返回 False")
        self.assertFalse(p.exists())

    def test_settings_schema_validation(self):
        p = self.tmp / "config.json"
        s = Settings(path=p)
        s.set_many(fuzzy_mid=95.0, fuzzy_high=92.0)
        errors = s.validate()
        self.assertTrue(any("fuzzy_mid" in e and "fuzzy_high" in e for e in errors),
                        f"应报告 fuzzy 顺序错误：{errors}")
        # 修正后无错误
        s.set_many(fuzzy_mid=75.0, fuzzy_high=92.0)
        self.assertEqual(s.validate(), [])

    def test_settings_schema_validation_bad_value(self):
        p = self.tmp / "config.json"
        s = Settings(path=p)
        s.set("backup_keep", -5)
        errors = s.validate()
        self.assertTrue(any("backup_keep" in e for e in errors))

    def test_validate_candidate_before_write(self):
        """P1-13：校验候选值而不污染当前配置。"""
        p = self.tmp / "config.json"
        s = Settings(path=p)
        s.set_many(fuzzy_mid=75.0, fuzzy_high=92.0)
        # 非法候选（fuzzy_mid >= fuzzy_high）→ 报错，且当前配置未被污染
        errors = s.validate_candidate({"fuzzy_mid": 95.0, "fuzzy_high": 92.0})
        self.assertTrue(errors)
        self.assertEqual(s.get("fuzzy_mid"), 75.0, "候选校验不得改动当前配置")
        self.assertEqual(s.get("fuzzy_high"), 92.0)
        # 合法候选 → 无错误
        self.assertEqual(s.validate_candidate({"fuzzy_mid": 75.0, "fuzzy_high": 92.0}), [])
        # backup_keep 非法
        self.assertTrue(s.validate_candidate({"backup_keep": 0}))
        self.assertTrue(s.validate_candidate({"dt365_max_fetch": -1}))

    def test_corrupt_config_preserved_and_noted(self):
        """P2：损坏配置保留坏文件（改名留档）+ corrupt_config_note 提示。"""
        p = self.tmp / "config.json"
        p.write_text("{ this is not valid json !!!", encoding="utf-8")
        s = Settings(path=p)
        self.assertNotEqual(s.corrupt_config_note, "", "损坏必须记录提示")
        # 坏文件被保留（改名），未丢失
        kept = list(self.tmp.glob("config.json.corrupt-*"))
        self.assertEqual(len(kept), 1, "坏文件必须改名保留")
        self.assertIn("已备份为", s.corrupt_config_note)
        # 默认值仍可用，且可正常保存新配置
        self.assertEqual(s.get("fuzzy_high"), 92.0)
        self.assertTrue(s.save())
        self.assertTrue(p.exists())


if __name__ == "__main__":
    unittest.main()
