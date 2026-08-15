"""打包脚本：生成 Windows EXE（PyInstaller）。

用法：
    pip install pyinstaller
    python build.py
产物在 dist/HAM点名助手/

数据保护（任务书第一阶段 #2）：
- dist 重建前完整备份 runtime（data/、logs/、backup/、config.json）。
- build 失败后也必须恢复 runtime（try/finally）。
- 部署到 Downloads 前保留既有 runtime，绝不直接丢用户数据。
- 部署顺序：build → 校验产物 → 保留既有 runtime → 原子替换程序文件 → 恢复 runtime。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "HAM点名助手"
ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / NAME
BAK = ROOT / "build" / f"{NAME}_databak"
DEPLOY_BAK = ROOT / "build" / f"{NAME}_deploy_bak"
_RUNTIME = ("data", "logs", "backup", "config.json")


def backup_runtime(dist: Path = DIST, bak: Path = BAK) -> None:
    """打包前备份运行时数据（data/、logs/、backup/、config.json）。"""
    if not dist.exists():
        return
    if bak.exists():
        shutil.rmtree(bak)
    bak.mkdir(parents=True)
    for item in _RUNTIME:
        src = dist / item
        if src.is_dir():
            shutil.copytree(src, bak / item)
        elif src.exists():
            shutil.copy2(src, bak / item)


def restore_runtime(dist: Path = DIST, bak: Path = BAK) -> None:
    """打包后把运行时数据恢复到新 exe 旁，确保重新打包不丢数据。"""
    if not bak.exists():
        return
    dist.mkdir(parents=True, exist_ok=True)
    for item in _RUNTIME:
        src = bak / item
        if src.is_dir():
            shutil.copytree(src, dist / item, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, dist / item)


def _verify_artifact(src_dist: Path) -> bool:
    """部署前校验产物完整（至少 EXE 存在）。"""
    exe = src_dist / f"{NAME}.exe"
    if not exe.exists():
        return False
    return True


def deploy_program(src_dist: Path, target: Path, runtime_bak: Path) -> bool:
    """可回滚部署（P1-15）。

    顺序：复制到 target.new → 校验产物 → 保留既有 runtime →
    target → target.old → target.new → target → 恢复 runtime → 成功后删 old。
    任何失败自动 rollback（恢复 target.old），绝不留下半成品。
    """
    if not src_dist.exists():
        return False
    parent = target.parent
    target_new = parent / (target.name + ".new")
    target_old = parent / (target.name + ".old")
    # 1) 只复制程序载荷到 target.new。
    #    src_dist 旁可能保留着上一次运行的 data/logs/backup/config.json；
    #    这些是用户运行时数据，不能在首次部署到 Downloads 时被复制进发布包。
    def ignore_runtime(_path: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _RUNTIME}

    if target_new.exists():
        shutil.rmtree(target_new)
    shutil.copytree(src_dist, target_new, ignore=ignore_runtime)
    # 2) smoke verify
    if not _verify_artifact(target_new):
        shutil.rmtree(target_new)
        return False
    had_target = target.exists()
    # 3) 保留既有 runtime → 原子切换
    if had_target:
        backup_runtime(target, runtime_bak)
        if target_old.exists():
            shutil.rmtree(target_old)
        os.replace(target, target_old)   # target -> target.old
    try:
        os.replace(target_new, target)   # target.new -> target
    except Exception:  # noqa: BLE001
        if had_target and target_old.exists():
            os.replace(target_old, target)  # rollback
        return False
    # 4) 恢复 runtime，成功后删除 old
    if had_target:
        restore_runtime(target, runtime_bak)
        try:
            shutil.rmtree(target_old)
        except OSError:
            pass
    return True


def build_exe() -> int:
    """运行 PyInstaller，返回退出码。"""
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
    return subprocess.call(cmd)


def main() -> int:
    backup_runtime()
    code = -1  # P3：异常路径下 code 也必有值，杜绝 UnboundLocalError
    try:
        code = build_exe()
    finally:
        # build 失败也必须恢复 runtime（任务书第一阶段 #2）
        restore_runtime()
    if code == 0:
        dl = Path.home() / "Downloads"
        if dl.exists():
            deploy_program(DIST, dl / NAME, DEPLOY_BAK)
        else:
            print("未找到下载文件夹，跳过部署:", dl)
    return code


if __name__ == "__main__":
    sys.exit(main())
