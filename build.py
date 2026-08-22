"""打包脚本：生成 Windows 单文件 EXE（PyInstaller）。

用法：
    pip install pyinstaller
    python build.py
产物在 dist/HAM点名助手.exe，最终部署到 Downloads/HAM点名助手.exe。

数据保护（任务书第一阶段 #2）：
- 构建前完整备份旧版构建目录中的 runtime（仅用于兼容旧文件夹版）。
- build 失败后也必须恢复 legacy runtime（try/finally）。
- 部署到 Downloads 前保留既有 runtime，首次启动由程序迁移到 LocalAppData。
- 部署顺序：build → 校验单文件产物 → 保留既有 runtime → 原子替换 EXE → 恢复 runtime。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "HAM点名助手"
ROOT = Path(__file__).resolve().parent
DIST_ROOT = ROOT / "dist"
DIST_EXE = DIST_ROOT / f"{NAME}.exe"
LEGACY_DIST = DIST_ROOT / NAME
BAK = ROOT / "build" / f"{NAME}_databak"
DEPLOY_BAK = ROOT / "build" / f"{NAME}_deploy_bak"
_RUNTIME = ("data", "logs", "backup", "config.json")


def backup_runtime(root: Path = LEGACY_DIST, bak: Path = BAK) -> None:
    """备份指定目录下的运行时数据。"""
    if not root.exists():
        return
    if bak.exists():
        shutil.rmtree(bak)
    bak.mkdir(parents=True)
    for item in _RUNTIME:
        src = root / item
        if src.is_dir():
            shutil.copytree(src, bak / item)
        elif src.exists():
            shutil.copy2(src, bak / item)


def restore_runtime(root: Path = LEGACY_DIST, bak: Path = BAK) -> None:
    """把备份的运行时数据恢复到指定目录。"""
    if not bak.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    for item in _RUNTIME:
        src = bak / item
        if src.is_dir():
            shutil.copytree(src, root / item, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, root / item)


def _verify_artifact(exe: Path) -> bool:
    """部署前校验单文件产物完整。"""
    return exe.is_file() and exe.suffix.lower() == ".exe" and exe.stat().st_size > 0


def _runtime_present(root: Path) -> bool:
    """判断目录中是否存在需要保护的运行时文件。"""
    return any((root / item).exists() for item in _RUNTIME)


def migrate_legacy_runtime(legacy_root: Path, target_root: Path) -> bool:
    """把旧文件夹版的运行数据补迁移到目标目录，供旧版本兼容。

    只补齐目标中不存在的项目，绝不覆盖用户已经在单文件版旁边产生的
    数据；新的运行时默认会在 LocalAppData 使用自己的用户数据目录。
    """
    if not legacy_root.exists():
        return True
    target_root.mkdir(parents=True, exist_ok=True)
    try:
        for item in _RUNTIME:
            src = legacy_root / item
            dst = target_root / item
            if not src.exists() or dst.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    except (OSError, shutil.Error):
        return False
    return True


def remove_legacy_program(legacy_root: Path) -> bool:
    """仅删除不含运行数据的旧文件夹版程序。"""
    if not legacy_root.exists():
        return True
    if not legacy_root.is_dir() or _runtime_present(legacy_root):
        return False
    try:
        shutil.rmtree(legacy_root)
    except OSError:
        return False
    return not legacy_root.exists()


def deploy_program(src_exe: Path, target_exe: Path, runtime_bak: Path) -> bool:
    """以可回滚方式部署单文件 EXE（P1-15）。

    顺序：复制到 target.new → 校验产物 → 备份同级 runtime →
    target.exe → target.old → target.new → target.exe → 恢复 runtime。
    任何失败自动 rollback，绝不留下半成品。
    """
    if not _verify_artifact(src_exe):
        return False
    parent = target_exe.parent
    parent.mkdir(parents=True, exist_ok=True)
    # 临时文件仍保留 .exe 后缀，便于复用同一份产物校验逻辑。
    target_new = parent / f"{target_exe.stem}.new{target_exe.suffix}"
    target_old = parent / f"{target_exe.stem}.old{target_exe.suffix}"
    moved_old = False
    installed_new = False
    try:
        if target_new.exists():
            target_new.unlink()
        shutil.copy2(src_exe, target_new)
        if not _verify_artifact(target_new):
            target_new.unlink(missing_ok=True)
            return False

        # 兼容旧版同目录 runtime；新版运行时会在首次启动时迁移到 LocalAppData。
        backup_runtime(parent, runtime_bak)
        if target_old.exists():
            try:
                target_old.unlink()
            except OSError:
                # 已运行的旧版本可能锁住固定名称的备份。不要覆盖它，改用编号备份，
                # 这样用户关闭旧进程前仍可继续构建和切换新版本。
                for backup_no in range(1, 101):
                    candidate = parent / (
                        f"{target_exe.stem}.old-{backup_no}{target_exe.suffix}"
                    )
                    if not candidate.exists():
                        target_old = candidate
                        break
                    try:
                        candidate.unlink()
                    except OSError:
                        continue
                else:
                    raise OSError("no available EXE backup path")
        if target_exe.exists():
            os.replace(target_exe, target_old)
            moved_old = True
        os.replace(target_new, target_exe)
        installed_new = True
        restore_runtime(parent, runtime_bak)
    except (OSError, shutil.Error):
        try:
            target_new.unlink(missing_ok=True)
        except OSError:
            pass
        if installed_new:
            try:
                target_exe.unlink(missing_ok=True)
            except OSError:
                pass
        if moved_old and not target_exe.exists() and target_old.exists():
            try:
                os.replace(target_old, target_exe)
            except OSError:
                pass
        return False

    # 新 EXE 和兼容 runtime 都已就位，才清理旧 EXE 备份。
    if target_old.exists():
        try:
            target_old.unlink()
        except OSError:
            # 旧版进程仍在运行时，Windows 可能暂时不允许删除备份文件。
            # 新 EXE 已经完成原子切换，保留 .old.exe 比把一次成功部署误报成失败更安全；
            # 下一次构建或用户退出旧进程后再清理即可。
            print("旧版 EXE 仍被使用，暂时保留备份:", target_old)
    return True


def build_exe() -> int:
    """运行 PyInstaller，返回退出码。"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", f"{ROOT / 'assets'};assets",
        # data/、logs/、backup/、config.json 均由新版在 LocalAppData 创建，
        # 不打包进内部，避免写入临时解压目录或安装目录导致数据丢失。
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
            target_exe = dl / f"{NAME}.exe"
            if deploy_program(DIST_EXE, target_exe, DEPLOY_BAK):
                legacy_root = dl / NAME
                if migrate_legacy_runtime(legacy_root, dl):
                    if remove_legacy_program(legacy_root):
                        print("已移除不含运行数据的旧文件夹版:", legacy_root)
                    elif legacy_root.exists():
                        print("旧文件夹版含运行数据，已保留:", legacy_root)
                else:
                    print("旧文件夹版运行数据迁移失败，已保留旧目录:", legacy_root)
                    return 1
            else:
                print("单文件 EXE 部署失败，未覆盖现有程序。")
                return 1
        else:
            print("未找到下载文件夹，跳过部署:", dl)
    return code


if __name__ == "__main__":
    sys.exit(main())
