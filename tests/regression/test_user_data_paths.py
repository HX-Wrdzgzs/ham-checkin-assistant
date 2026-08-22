"""回归测试：运行时数据不依赖 EXE 或当前工作目录。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.settings import Settings, migrate_legacy_runtime


class TestUserDataPaths(unittest.TestCase):
    def test_relative_runtime_paths_use_config_directory(self):
        with tempfile.TemporaryDirectory(prefix="ham_paths_") as raw:
            root = Path(raw)
            settings = Settings(path=root / "config.json")
            self.assertEqual(settings.data_dir, root / "data")
            self.assertEqual(settings.logs_dir, root / "logs")
            self.assertEqual(settings.backup_dir, root / "backup")

    def test_legacy_runtime_migrates_without_overwriting_target_files(self):
        with tempfile.TemporaryDirectory(prefix="ham_migrate_") as raw:
            root = Path(raw)
            legacy = root / "installed"
            target = root / "localappdata" / "HAM点名助手"
            (legacy / "data").mkdir(parents=True)
            (legacy / "logs").mkdir()
            (legacy / "backup").mkdir()
            (legacy / "data" / "ham_checkin.db").write_bytes(b"old-db")
            (legacy / "logs" / "app.log").write_text("old-log", encoding="utf-8")
            (legacy / "config.json").write_text(
                json.dumps({"data_dir": "data", "logs_dir": "logs", "backup_dir": "backup"}),
                encoding="utf-8",
            )

            ok, note = migrate_legacy_runtime(legacy, target)
            self.assertTrue(ok, note)
            self.assertTrue((target / "config.json").exists())
            self.assertEqual((target / "data" / "ham_checkin.db").read_bytes(), b"old-db")
            self.assertEqual((target / "logs" / "app.log").read_text(encoding="utf-8"),
                             "old-log")

            # 再次迁移不得覆盖用户已经在新目录产生的数据。
            (target / "data" / "ham_checkin.db").write_bytes(b"new-db")
            (legacy / "data" / "ham_checkin.db").write_bytes(b"changed-old-db")
            ok2, note2 = migrate_legacy_runtime(legacy, target)
            self.assertTrue(ok2, note2)
            self.assertEqual((target / "data" / "ham_checkin.db").read_bytes(), b"new-db")

    def test_frozen_default_settings_use_user_directory_and_migrate(self):
        with tempfile.TemporaryDirectory(prefix="ham_frozen_paths_") as raw:
            root = Path(raw)
            legacy = root / "program"
            target = root / "user-data"
            (legacy / "data").mkdir(parents=True)
            (legacy / "data" / "ham_checkin.db").write_bytes(b"db")
            (legacy / "config.json").write_text(
                json.dumps({"data_dir": "data"}), encoding="utf-8")

            with (
                mock.patch("config.settings.PROGRAM_DIR", legacy),
                mock.patch("config.settings.USER_DATA_DIR", target),
                mock.patch("config.settings.CONFIG_PATH", target / "config.json"),
                mock.patch.object(sys, "frozen", True, create=True),
            ):
                settings = Settings()

            self.assertEqual(settings.path, target / "config.json")
            self.assertEqual(settings.data_dir, target / "data")
            self.assertEqual((target / "data" / "ham_checkin.db").read_bytes(), b"db")
            self.assertFalse((legacy / "data" / "ham_checkin.db").samefile(
                target / "data" / "ham_checkin.db"))


if __name__ == "__main__":
    unittest.main()
