"""Release 产物生成回归测试：真实 hash 驱动清单，不访问 GitHub。"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from release import (
    CHECKSUM_ASSET_NAME,
    GITHUB_LEGACY_UPLOAD_ASSET_NAME,
    LEGACY_RELEASE_ASSET_NAME,
    RELEASE_ASSET_NAME,
    prepare_release,
)


class TestReleasePrepare(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ham_release_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prepare_release_uses_actual_exe_sha256(self):
        exe = self.tmp / "dist" / "HAM点名助手.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"real-built-exe-bytes")
        release_dir = self.tmp / "release"
        manifest_path = self.tmp / "updates" / "latest.json"

        manifest = prepare_release(
            exe,
            version="1.2.3",
            tag_name="v1.2.3",
            release_dir=release_dir,
            manifest_path=manifest_path,
        )
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        self.assertEqual((release_dir / RELEASE_ASSET_NAME).read_bytes(), exe.read_bytes())
        self.assertEqual(
            (release_dir / LEGACY_RELEASE_ASSET_NAME).read_bytes(), exe.read_bytes())
        self.assertEqual(
            (release_dir / GITHUB_LEGACY_UPLOAD_ASSET_NAME).read_bytes(), exe.read_bytes())
        self.assertEqual(
            (release_dir / CHECKSUM_ASSET_NAME).read_text(encoding="utf-8"),
            f"{digest}  {RELEASE_ASSET_NAME}\n"
            f"{digest}  {LEGACY_RELEASE_ASSET_NAME}\n",
        )
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, manifest)
        self.assertEqual(saved["sha256"], digest)
        self.assertTrue(saved["download_url"].endswith("/v1.2.3/HAM.exe"))

    def test_prepare_release_overwrites_stale_same_size_same_mtime_asset(self):
        exe = self.tmp / "dist" / "HAM点名助手.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"new-build")
        release_dir = self.tmp / "release"
        release_dir.mkdir()
        release_exe = release_dir / RELEASE_ASSET_NAME
        release_exe.write_bytes(b"old-build")
        shutil.copystat(exe, release_exe)

        prepare_release(
            exe,
            version="1.2.3",
            tag_name="v1.2.3",
            release_dir=release_dir,
            manifest_path=self.tmp / "latest.json",
        )

        self.assertEqual(release_exe.read_bytes(), b"new-build")
        self.assertEqual(
            (release_dir / LEGACY_RELEASE_ASSET_NAME).read_bytes(), b"new-build")
        self.assertEqual(
            (release_dir / GITHUB_LEGACY_UPLOAD_ASSET_NAME).read_bytes(), b"new-build")

    def test_prepare_release_rejects_tag_version_mismatch(self):
        exe = self.tmp / "HAM点名助手.exe"
        exe.write_bytes(b"exe")
        with self.assertRaisesRegex(ValueError, "Tag.*不一致"):
            prepare_release(
                exe,
                version="1.2.3",
                tag_name="v1.2.4",
                release_dir=self.tmp / "release",
                manifest_path=self.tmp / "latest.json",
            )

    def test_prepare_release_rejects_missing_exe_without_touching_manifest(self):
        manifest = self.tmp / "latest.json"
        manifest.write_text('{"version":"old"}\n', encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            prepare_release(
                self.tmp / "missing.exe",
                version="1.2.3",
                release_dir=self.tmp / "release",
                manifest_path=manifest,
            )
        self.assertEqual(manifest.read_text(encoding="utf-8"), '{"version":"old"}\n')


if __name__ == "__main__":
    unittest.main()
