"""回归测试：build/deploy 数据保护（任务书第一阶段 #2）。

不运行真实 PyInstaller；只测 backup_runtime / restore_runtime / deploy_program 的
数据保全语义，全部在 tempfile 内完成，绝不动真实 dist/Downloads。
"""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build import (
    backup_runtime,
    _write_build_version,
    deploy_program,
    migrate_legacy_runtime,
    remove_legacy_program,
    restore_runtime,
)

DB_BYTES = b"db-bytes"
BACKUP_BYTES = b"backup-bytes"
CONFIG_TEXT = '{"default_province": "江苏"}'


def _make_runtime(root: Path) -> Path:
    d = root
    (d / "data").mkdir(parents=True)
    (d / "backup").mkdir(parents=True)
    (d / "logs").mkdir(parents=True)
    (d / "data" / "ham_checkin.db").write_bytes(DB_BYTES)
    (d / "backup" / "ham_checkin_2026-08-01.db").write_bytes(BACKUP_BYTES)
    (d / "config.json").write_text(CONFIG_TEXT, encoding="utf-8")
    return d


class TestBuildProtection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_build_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_test_build_version_file_uses_fixed_packaged_name(self):
        """测试版临时目录内的文件名必须固定，冻结后才能被 version.py 找到。"""
        import build

        with patch.object(build, "ROOT", self.tmp):
            version_root = _write_build_version("HX-HAM-0.0.2")
        try:
            version_file = version_root / "build_version.json"
            self.assertEqual(version_file.read_text(encoding="utf-8").strip(),
                             '{"version": "HX-HAM-0.0.2"}')
        finally:
            shutil.rmtree(version_root, ignore_errors=True)

    def test_build_preserves_database(self):
        dist = _make_runtime(self.tmp / "dist")
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
        dist = _make_runtime(self.tmp / "dist")
        bak = self.tmp / "bak"
        new_dist = self.tmp / "new_dist"
        backup_runtime(dist, bak)
        shutil.rmtree(dist)
        restore_runtime(new_dist, bak)
        b = new_dist / "backup" / "ham_checkin_2026-08-01.db"
        self.assertTrue(b.exists(), "build 不得删除 backup")
        self.assertEqual(b.read_bytes(), BACKUP_BYTES)

    def test_build_preserves_config(self):
        dist = _make_runtime(self.tmp / "dist")
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
        dist = _make_runtime(self.tmp / "dist")
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
        """部署到已有目标：新 EXE + 既有 DB/backup/config 全保留。"""
        target_root = _make_runtime(self.tmp / "target")
        target = target_root / "HAM点名助手.exe"
        target.write_bytes(b"old-exe")
        src = self.tmp / "src" / "HAM点名助手.exe"
        src.parent.mkdir()
        src.write_bytes(b"new-exe")
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), b"new-exe", "新 EXE 应部署")
        self.assertEqual((target_root / "data" / "ham_checkin.db").read_bytes(), DB_BYTES,
                         "部署不得覆盖已有 DB")
        self.assertEqual((target_root / "backup" / "ham_checkin_2026-08-01.db").read_bytes(),
                         BACKUP_BYTES, "部署不得删除 backup")
        self.assertEqual((target_root / "config.json").read_text(encoding="utf-8"), CONFIG_TEXT,
                         "部署不得覆盖用户 config")

    def test_deploy_into_empty_target(self):
        """目标不存在 → 直接部署程序文件。"""
        src = self.tmp / "src" / "HAM点名助手.exe"
        src.parent.mkdir()
        src.write_bytes(b"new-exe")
        target = self.tmp / "target" / "HAM点名助手.exe"
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        self.assertTrue(target.exists())

    def test_deploy_new_target_excludes_source_runtime(self):
        """首次部署到 Downloads 时不得把 src_dist 的运行数据带入发布包。"""
        src_root = _make_runtime(self.tmp / "src")
        src = src_root / "HAM点名助手.exe"
        src.write_bytes(b"new-exe")
        target = self.tmp / "target" / "HAM点名助手.exe"
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        self.assertTrue(target.exists())
        self.assertFalse((target.parent / "data").exists())
        self.assertFalse((target.parent / "backup").exists())
        self.assertFalse((target.parent / "logs").exists())
        self.assertFalse((target.parent / "config.json").exists())

    def test_deploy_uses_atomic_rename_no_half_target(self):
        """P1-15：部署走 target.new → 原子切换，不留半成品 target.new/old。

        规范：不允许 build 覆盖已有 DB → 旧 runtime（含 DB）必须恢复。
        """
        src_root = _make_runtime(self.tmp / "src")
        src = src_root / "HAM点名助手.exe"
        src.write_bytes(b"new-exe")
        (src_root / "data" / "ham_checkin.db").write_bytes(b"fresh-db")
        target_root = _make_runtime(self.tmp / "target")  # 已有 runtime（db-bytes）
        target = target_root / "HAM点名助手.exe"
        target.write_bytes(b"old-exe")
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertTrue(ok)
        # 没有残留 .new / .old
        self.assertFalse((target_root / "HAM点名助手.new.exe").exists())
        self.assertFalse((target_root / "HAM点名助手.old.exe").exists())
        # 既有 DB 必须保留（不得被新 build 的 runtime 覆盖）
        self.assertEqual((target_root / "data" / "ham_checkin.db").read_bytes(), DB_BYTES,
                         "既有 DB 必须保留")
        self.assertEqual((target_root / "config.json").read_text(encoding="utf-8"), CONFIG_TEXT,
                         "旧 config 应恢复")

    def test_deploy_succeeds_when_old_exe_is_temporarily_locked(self):
        """旧版进程锁住 .old.exe 时，新 EXE 已切换也应报告部署成功。"""
        target_root = _make_runtime(self.tmp / "target")
        target = target_root / "HAM点名助手.exe"
        target.write_bytes(b"old-exe")
        src = self.tmp / "src" / "HAM点名助手.exe"
        src.parent.mkdir()
        src.write_bytes(b"new-exe")
        target_old = target_root / "HAM点名助手.old.exe"

        real_unlink = Path.unlink

        def lock_old(path, missing_ok=False):
            if path == target_old:
                raise PermissionError("simulated running old process")
            return real_unlink(path, missing_ok=missing_ok)

        cp1252_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        with (
            patch.object(Path, "unlink", autospec=True, side_effect=lock_old),
            patch("sys.stdout", cp1252_stdout),
        ):
            ok = deploy_program(src, target, self.tmp / "dep_bak")

        self.assertTrue(ok, "旧备份暂时不能删除不应否定已完成的新 EXE 切换")
        self.assertEqual(target.read_bytes(), b"new-exe")
        self.assertTrue(target_old.exists(), "被占用的旧版备份应保留到下次清理")

    def test_deploy_uses_numbered_backup_when_old_backup_is_locked(self):
        """已有固定名旧备份被占用时，部署应改用编号备份继续切换。"""
        target_root = _make_runtime(self.tmp / "target")
        target = target_root / "HAM点名助手.exe"
        target.write_bytes(b"old-exe")
        target_old = target_root / "HAM点名助手.old.exe"
        target_old.write_bytes(b"locked-backup")
        src = self.tmp / "src" / "HAM点名助手.exe"
        src.parent.mkdir()
        src.write_bytes(b"new-exe")

        real_unlink = Path.unlink

        def lock_old(path, missing_ok=False):
            if path == target_old:
                raise PermissionError("simulated running old backup")
            return real_unlink(path, missing_ok=missing_ok)

        with patch.object(Path, "unlink", autospec=True, side_effect=lock_old):
            ok = deploy_program(src, target, self.tmp / "dep_bak")

        self.assertTrue(ok)
        self.assertEqual(target.read_bytes(), b"new-exe")
        self.assertEqual(target_old.read_bytes(), b"locked-backup")

    def test_deploy_artifact_verify_fails(self):
        """P1-15：产物缺少 EXE → 拒绝部署（smoke verify）。"""
        src = self.tmp / "src" / "not-an-exe"
        src.parent.mkdir()
        src.write_bytes(b"not-an-exe")
        target_root = self.tmp / "target"
        target_root.mkdir()
        target = target_root / "HAM点名助手.exe"
        ok = deploy_program(src, target, self.tmp / "dep_bak")
        self.assertFalse(ok)
        self.assertFalse((target_root / "HAM点名助手.new.exe").exists(), "失败不得留 target.new")
        self.assertTrue(target_root.exists(), "失败不得破坏原 target")

    def test_migrate_legacy_runtime_does_not_overwrite_target(self):
        """旧文件夹版数据只补迁移，不覆盖单文件版已有数据。"""
        legacy = _make_runtime(self.tmp / "legacy")
        target = self.tmp / "downloads"
        target.mkdir()
        (target / "data").mkdir()
        (target / "data" / "ham_checkin.db").write_bytes(b"newer-db")
        self.assertTrue(migrate_legacy_runtime(legacy, target))
        self.assertEqual((target / "data" / "ham_checkin.db").read_bytes(), b"newer-db")
        self.assertEqual((target / "backup" / "ham_checkin_2026-08-01.db").read_bytes(),
                         BACKUP_BYTES)

    def test_remove_legacy_program_only_when_no_runtime(self):
        """无运行数据的旧文件夹版可以清理；有数据时必须保留。"""
        empty_legacy = self.tmp / "empty-legacy"
        empty_legacy.mkdir()
        (empty_legacy / "HAM点名助手.exe").write_bytes(b"old-exe")
        self.assertTrue(remove_legacy_program(empty_legacy))
        self.assertFalse(empty_legacy.exists())

        data_legacy = _make_runtime(self.tmp / "data-legacy")
        self.assertFalse(remove_legacy_program(data_legacy))
        self.assertTrue(data_legacy.exists())


if __name__ == "__main__":
    unittest.main()
