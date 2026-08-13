"""打包脚本：生成 Windows EXE（PyInstaller）。

用法：
    pip install pyinstaller
    python build.py
产物在 dist/HAM点名助手/

重要：PyInstaller --noconfirm 会删除并重建 dist/HAM点名助手（含运行时数据）。
本脚本在打包前把 exe 旁的 data/、logs/、config.json 备份，打包后恢复，避免丢失数据库。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

NAME = "HAM点名助手"
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / NAME
BAK = ROOT / "build" / f"{NAME}_databak"
_RUNTIME = ("data", "logs", "config.json")


def backup_runtime() -> None:
    """打包前备份运行时数据（data/、logs/、config.json）。"""
    if not DIST.exists():
        return
    if BAK.exists():
        shutil.rmtree(BAK)
    BAK.mkdir(parents=True)
    for item in _RUNTIME:
        src = DIST / item
        if src.is_dir():
            shutil.copytree(src, BAK / item)
        elif src.exists():
            shutil.copy2(src, BAK / item)


def restore_runtime() -> None:
    """打包后把运行时数据恢复到新 exe 旁，确保重新打包不丢数据。"""
    if not BAK.exists():
        return
    DIST.mkdir(parents=True, exist_ok=True)
    for item in _RUNTIME:
        src = BAK / item
        if src.is_dir():
            shutil.copytree(src, DIST / item, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, DIST / item)


def deploy_to_downloads() -> None:
    """打包后把整个软件复制到用户「下载」文件夹，方便直接使用。"""
    dl = Path.home() / "Downloads"
    if not dl.exists():
        print("未找到下载文件夹，跳过部署:", dl)
        return
    target = dl / NAME
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(DIST, target)
    print(f"已输出到下载文件夹: {target}")


def main() -> int:
    backup_runtime()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name", NAME,
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", f"{ROOT / 'assets'};assets",
        # data/、logs/、backup/、config.json 均为运行时在 exe 旁自动创建，
        # 不打包进内部，避免写入临时解压目录导致数据丢失。
        "app.py",
    ]
    print("Running:", " ".join(cmd))
    code = subprocess.call(cmd)
    restore_runtime()
    if code == 0:
        deploy_to_downloads()
    return code


if __name__ == "__main__":
    sys.exit(main())
