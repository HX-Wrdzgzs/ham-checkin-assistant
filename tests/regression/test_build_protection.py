"""回归测试：build/deploy 数据保护（任务书第一阶段 #2）。

不运行真实 PyInstaller；只测 backup_runtime / restore_runtime / deploy_program 的
数据保全语义，全部在 tempfile 内完成，绝不动真实 dist/Downloads。
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from build import backup_runtime, deploy_program, restore_runtime

DB_BYTES = b"db-bytes"
BACKUP_BYTES = b"backup-bytes"
CONFIG_TEXT = '{"default_province": "江苏"}'


def _make_dist(base: Path) -> Path:
    d = base / "dist"
    (d / "data").mkdir(parents=True)
    (d / "backup").mkdir(parents=True)
    (d / "logs").mkdir(parents=True)
    (d / "data" / "ham_checkin.db").write_bytes(DB_BYTES)
    (d / "backup" / "ham_checkin_2026-08-01.db").write_bytes(BACKUP_BYTES)
    (d / "config.json").write_text(CONFIG_TEXT, encoding="utf-8")
    (d / "app.exe").write_bytes(b"exe-bytes")
    return d


class TestBuildProtection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_build_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_preserves_database(self):
        dist = _make_dist(self.tmp)
        bak = self.tmp / "bak"
        new_dist = self.tmp / "new_dist"
        backup_runtime(dist, bak)
        # 模拟 build 清空 dist
        shutil.rmtree(dist)
        restore_runtime(new_dist, bak)
        db = new_dist / "data" / "ham_checkin.db"
        self.assertTrue(db.exists(), "build 后 DB 必须恢复")
        self.assertEqual(db.read_bytes(), DB_BYTES)

    def test_build_preserves_backup(self):
        dist = _make_dist(self.tmp)
        bak = self.tmp / "bak"
        new_dist = self.tmp / "new_dist"
        backup_runtime(dist, bak)
        shutil.rmtree(dist)
        restore_runtime(new_dist, bak)
        b = new_dist / "backup" / "ham_checkin_2026-08-01.db"
        self.assertTrue(b.exists(), "build 不得删除 backup")
        self.assertEqual(b.read_bytes(), BACKUP_BYTES)

    def test_build_preserves_config(self):
        dist = _make_dist(self.tmp)
        bak = self.tmp / "bak"
        new_dist = self.tmp / "new_dist"
        backup_runtime(dist, bak)
        shutil.rmtree(dist)
        restore_runtime(new_dist, bak)
        cfg = new_dist / "config.json"
        self.assertTrue(cfg.exists(), "build 不得覆盖用户 config")
        self.assertEqual(cfg.read_text(encoding="utf-8"), CONFIG_TEXT)

    def test_failed_build_restores_runtime(self):
        """build 失败（dist 被弄坏）后 finally 里的 restore 仍要恢复 runtime。"""
        dist = _make_dist(self.tmp)
        bak = self.tmp / "bak"
        backup_runtime(dist, bak)
        # 模拟 build 失败把 dist 内容清掉
        for item in list(dist.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        restore_runtime(dist, bak)  # 对应 main() 的 finally
        self.assertEqual((dist / "data" / "ham_checkin.db").read_bytes(), DB_BYTES)
        self.assertEqual((dist / "config.json").read_text(encoding="utf-8"), CONFIG_TEXT)


class TestDeployProtection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_deploy_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deploy_preserves_existing_runtime(self):
        """部署到已有目标目录：新程序文件 + 既有 DB/backup/config 全保留。"""
        target = _make_dist(self.tmp / "target")
        src = self.tmp / "src"
        src.mkdir()
        (src / "HAM点名助手.exe").write_bytes(b"new-exe")
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        self.assertTrue((target / "HAM点名助手.exe").exists(), "新程序文件应部署")
        self.assertEqual((target / "data" / "ham_checkin.db").read_bytes(), DB_BYTES,
                         "部署不得覆盖已有 DB")
        self.assertEqual((target / "backup" / "ham_checkin_2026-08-01.db").read_bytes(),
                         BACKUP_BYTES, "部署不得删除 backup")
        self.assertEqual((target / "config.json").read_text(encoding="utf-8"), CONFIG_TEXT,
                         "部署不得覆盖用户 config")

    def test_deploy_into_empty_target(self):
        """目标不存在 → 直接部署程序文件。"""
        src = self.tmp / "src"
        src.mkdir()
        (src / "HAM点名助手.exe").write_bytes(b"new-exe")
        target = self.tmp / "target"
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        self.assertTrue((target / "HAM点名助手.exe").exists())


if __name__ == "__main__":
    unittest.main()
