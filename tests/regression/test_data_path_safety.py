"""回归测试：生产配置的数据目录消失时不得静默创建空数据库。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.settings import Settings


class TestDataPathSafety(unittest.TestCase):
    def test_missing_custom_runtime_data_dir_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="ham_runtime_cfg_") as raw:
            root = Path(raw)
            config_path = root / "config.json"
            settings = Settings(path=config_path)
            settings.set_many(
                data_dir=str(root / "missing-data"),
                logs_dir=str(root / "logs"),
                backup_dir=str(root / "backup"),
            )
            with mock.patch("services.app_service.CONFIG_PATH", config_path):
                from services.app_service import AppService

                with self.assertRaisesRegex(RuntimeError, "数据目录或数据库文件不存在"):
                    AppService(settings)

            self.assertFalse((root / "missing-data").exists(),
                             "拒绝启动时不得创建空数据目录")

    def test_existing_empty_custom_data_dir_does_not_create_new_database(self):
        with tempfile.TemporaryDirectory(prefix="ham_runtime_cfg_empty_") as raw:
            root = Path(raw)
            config_path = root / "config.json"
            data_dir = root / "empty-data"
            data_dir.mkdir()
            settings = Settings(path=config_path)
            settings.set_many(
                data_dir=str(data_dir),
                logs_dir=str(root / "logs"),
                backup_dir=str(root / "backup"),
            )
            with mock.patch("services.app_service.CONFIG_PATH", config_path):
                from services.app_service import AppService

                with self.assertRaisesRegex(RuntimeError, "数据目录或数据库文件不存在"):
                    AppService(settings)

            self.assertEqual(list(data_dir.iterdir()), [],
                             "拒绝启动时不得在空数据目录创建新数据库")


if __name__ == "__main__":
    unittest.main()
