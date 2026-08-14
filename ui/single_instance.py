"""单实例保护：Windows 用 CreateMutexW；非 Windows 用原子 lock 目录兜底。

第二个实例启动时发现已有实例必须拒绝，避免：
- 打开第二个 SQLite writer
- 注册第二个 Excel controller
- 启动第二个 365dt sync
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ERROR_ALREADY_EXISTS = 183

_handle = None
_lock_dir: Path | None = None


def acquire(lock_name: str) -> bool:
    """获取单实例锁。返回 False 表示已有实例在运行。"""
    global _handle, _lock_dir
    if sys.platform == "win32":
        import ctypes

        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _handle = _kernel32.CreateMutexW(None, False, lock_name)
        if _handle is None or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
        return True
    # 非 Windows：原子目录锁（进程退出后由 release 清理；测试环境用唯一 name）
    d = Path(tempfile.gettempdir()) / f"ham_checkin_{lock_name}.lock"
    try:
        d.mkdir()
        _lock_dir = d
        return True
    except FileExistsError:
        return False


def release() -> None:
    global _handle, _lock_dir
    if sys.platform == "win32" and _handle:
        import ctypes

        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CloseHandle(_handle)
        _handle = None
    if _lock_dir:
        try:
            _lock_dir.rmdir()
        except OSError:
            pass
        _lock_dir = None
