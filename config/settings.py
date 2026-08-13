"""应用配置：加载/保存 config.json，提供默认值。"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path


def _app_dir() -> Path:
    """应用数据根目录：冻结(exe)时用 exe 所在目录，源码运行时用项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS: dict = {
    # 常规
    "default_province": "江苏",
    "default_repeater_name": "江苏省中继",
    "default_operator_callsign": "",
    # 快捷键
    "global_hotkey": "Ctrl+Space",
    # Excel
    "excel_auto_save": True,
    "excel_template": "",
    "excel_sheet_name": "",
    # 365dt
    "dt365_uid": "ET6RPQCR",
    "dt365_url": "https://api.365dt.net/dianming/user/ranking.asp?uid={uid}",
    "dt365_max_fetch": 1597,
    # 目录
    "data_dir": "data",
    "logs_dir": "logs",
    "backup_dir": "backup",
    "backup_keep": 30,
    # 模糊匹配阈值
    "fuzzy_high": 92.0,
    "fuzzy_mid": 75.0,
    # 悬浮窗
    "window_opacity": 0.95,
    "window_on_top": True,
    "window_position": None,
}


class Settings:
    """线程安全的配置读写。改动即时落盘。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else CONFIG_PATH
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k, v in loaded.items():
                    self._data[k] = v
            except (OSError, json.JSONDecodeError):
                # 配置损坏时回退默认值，不阻塞启动
                pass

    def save(self) -> None:
        with self._lock:
            try:
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
        self.save()

    def set_many(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                self._data[k] = v
        self.save()

    @property
    def data_dir(self) -> Path:
        return APP_DIR / self.get("data_dir")

    @property
    def logs_dir(self) -> Path:
        return APP_DIR / self.get("logs_dir")

    @property
    def backup_dir(self) -> Path:
        return APP_DIR / self.get("backup_dir")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ham_checkin.db"


settings = Settings()
