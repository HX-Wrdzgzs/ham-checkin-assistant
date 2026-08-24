"""应用版本与冻结版构建版本覆盖。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


DEFAULT_VERSION = "0.9.4"
BUILD_VERSION_FILE = "build_version.json"
_SUPPORTED_VERSION_RE = re.compile(
    r"^(?:\d+\.\d+\.\d+|HX-HAM-\d+\.\d+\.\d+)$"
)
_NUMERIC_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def is_supported_version(value: str) -> bool:
    """判断版本是否可用于稳定构建或明确标记的测试构建。"""
    return bool(_SUPPORTED_VERSION_RE.fullmatch(str(value or "").strip()))


def _version_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        # PyInstaller 单文件程序会把 build_version.json 解压到 _MEIPASS 根目录。
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    # 源码运行不读取项目目录中的临时构建文件，避免一次测试构建污染开发环境的版本。
    return [root / BUILD_VERSION_FILE for root in candidates]


def _load_frozen_build_version() -> str | None:
    """读取单文件 EXE 随包携带的版本覆盖值。"""
    for path in _version_file_candidates():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        value = str(payload.get("version") or "").strip()
        if is_supported_version(value):
            return value
    return None


__version__ = _load_frozen_build_version() or DEFAULT_VERSION

_numeric_match = _NUMERIC_VERSION_RE.search(__version__)
if _numeric_match is None:  # pragma: no cover - 仅防止错误构建文件污染运行时
    __version_number__ = DEFAULT_VERSION
else:
    __version_number__ = ".".join(_numeric_match.groups())
