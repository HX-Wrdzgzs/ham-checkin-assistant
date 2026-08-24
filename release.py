"""准备 GitHub Release 自动更新产物。

输入必须是一次真实 PyInstaller 构建出的 EXE。脚本会生成稳定 ASCII 主资产
``release/HAM.exe``、旧客户端兼容副本 ``release/HAM点名助手.exe``、GitHub
上传用的 ASCII 兼容副本 ``release/HAM-legacy.exe``、
``release/SHA256SUMS.txt``，并原子刷新 ``updates/latest.json``。
三个 EXE 必须是完全相同的二进制内容；清单中的 SHA256 永远从实际 EXE 计算，禁止手填。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from version import __version__

REPOSITORY = "HX-Wrdzgzs/ham-checkin-assistant"
ROOT = Path(__file__).resolve().parent
DEFAULT_EXE = ROOT / "dist" / "HAM点名助手.exe"
DEFAULT_RELEASE_DIR = ROOT / "release"
# 本地默认只写 release/，避免在 GitHub Release 尚未上传时提前污染线上备用清单。
# CI 在 Release 附件上传前显式传入 updates/latest.json，随后上传成功后才推送 main。
DEFAULT_MANIFEST = DEFAULT_RELEASE_DIR / "latest.json"
RELEASE_ASSET_NAME = "HAM.exe"
LEGACY_RELEASE_ASSET_NAME = "HAM点名助手.exe"
# GitHub Release API 会把非 ASCII 上传文件名归一化为 HAM.exe。使用独立的
# ASCII 物理名并设置中文 label，才能同时保留主资产和旧客户端可匹配的中文 label。
GITHUB_LEGACY_UPLOAD_ASSET_NAME = "HAM-legacy.exe"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _changelog_notes(version: str, changelog_path: Path = ROOT / "CHANGELOG.md") -> str:
    """提取指定版本的变更正文，供 API 限流时的备用清单展示。"""
    if not changelog_path.is_file():
        return ""
    text = changelog_path.read_text(encoding="utf-8")
    heading = re.compile(rf"^##\s+{re.escape(version)}(?:\s|\(|$)", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        return ""
    rest = text[match.end():]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    if next_heading is not None:
        rest = rest[:next_heading.start()]
    return rest.strip()


def prepare_release(
    exe_path: Path = DEFAULT_EXE,
    *,
    version: str = __version__,
    tag_name: str | None = None,
    release_dir: Path = DEFAULT_RELEASE_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict:
    """从真实 EXE 生成 Release 附件和备用更新清单。"""
    exe_path = Path(exe_path)
    release_dir = Path(release_dir)
    manifest_path = Path(manifest_path)
    version = str(version).strip()
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"非法版本号：{version!r}")
    expected_tag = f"v{version}"
    tag_name = str(tag_name or expected_tag).strip()
    if tag_name != expected_tag:
        raise ValueError(
            f"Tag 与 version.py 不一致：期望 {expected_tag}，实际 {tag_name}")
    if not exe_path.is_file() or exe_path.suffix.lower() != ".exe" or exe_path.stat().st_size <= 0:
        raise FileNotFoundError(f"没有有效的构建产物：{exe_path}")

    release_dir.mkdir(parents=True, exist_ok=True)
    release_exe = release_dir / RELEASE_ASSET_NAME
    if exe_path.resolve() != release_exe.resolve():
        # Release 附件必须无条件来自本次明确指定的构建产物。不要用大小/mtime
        # 推断内容一致，否则极端情况下可能把历史 HAM.exe 当成本次产物继续发布。
        shutil.copy2(exe_path, release_exe)
    digest = sha256_file(release_exe)

    # v0.9.2/v0.9.3 的 updater 只接受中文 name/label 和中文 checksum 行。
    # GitHub API 会把非 ASCII 上传名归一化为 HAM.exe，因此本地同时保留中文
    # 兼容副本和一个 ASCII 物理上传副本；工作流会给后者设置中文 label。
    legacy_release_exe = release_dir / LEGACY_RELEASE_ASSET_NAME
    shutil.copy2(release_exe, legacy_release_exe)
    github_legacy_release_exe = release_dir / GITHUB_LEGACY_UPLOAD_ASSET_NAME
    shutil.copy2(release_exe, github_legacy_release_exe)
    for compatibility_exe in (legacy_release_exe, github_legacy_release_exe):
        if sha256_file(compatibility_exe) != digest:
            raise RuntimeError("主资产和旧客户端兼容资产的 SHA256 不一致")

    checksum_path = release_dir / CHECKSUM_ASSET_NAME
    _atomic_write_text(
        checksum_path,
        f"{digest}  {RELEASE_ASSET_NAME}\n"
        f"{digest}  {LEGACY_RELEASE_ASSET_NAME}\n",
    )

    release_base = f"https://github.com/{REPOSITORY}/releases"
    manifest = {
        "version": version,
        "tag_name": tag_name,
        "html_url": f"{release_base}/tag/{tag_name}",
        "download_url": f"{release_base}/download/{tag_name}/{RELEASE_ASSET_NAME}",
        "asset_name": RELEASE_ASSET_NAME,
        "sha256": digest,
    }
    release_notes = _changelog_notes(version)
    if release_notes:
        manifest["release_notes"] = release_notes
    _atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 HAM 点名助手 GitHub Release 产物")
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--tag", default=None)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = prepare_release(
        args.exe,
        version=args.version,
        tag_name=args.tag,
        release_dir=args.release_dir,
        manifest_path=args.manifest,
    )
    print(
        f"Release {manifest['tag_name']} 已准备："
        f"{args.release_dir / RELEASE_ASSET_NAME}，SHA256={manifest['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
