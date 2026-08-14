"""应用配置：加载/保存 config.json，提供默认值。"""
from __future__ import annotations

import json
import os
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
    # 默认同步规模：首次 100~300 即可，避免一次性抓 1597（任务书第二阶段 #18）
    "dt365_max_fetch": 200,
    # 目录
    "data_dir": "data",
    "logs_dir": "logs",
    "backup_dir": "backup",
    "backup_keep": 30,
    # 模糊匹配阈值
    "fuzzy_high": 92.0,
    "fuzzy_mid": 75.0,
    "fuzzy_margin": 5.0,
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

    def save(self) -> bool:
        """原子写配置：tmp → flush → fsync → 原子替换（任务书第三阶段 #16）。

        返回 True=成功，False=失败（调用方必须提示用户，不得假装保存成功）。
        """
        with self._lock:
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path)
                return True
            except OSError:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                return False

    def validate(self) -> list[str]:
        """配置 schema 校验（任务书第三阶段 #17），返回问题列表。"""
        errors: list[str] = []
        try:
            mid = float(self.get("fuzzy_mid", 75))
            high = float(self.get("fuzzy_high", 92))
        except (TypeError, ValueError):
            errors.append("fuzzy_mid / fuzzy_high 必须为数字")
            mid, high = 75, 92
        if mid >= high:
            errors.append("fuzzy_mid 必须小于 fuzzy_high")
        for key in ("dt365_max_fetch", "backup_keep"):
            try:
                if float(self.get(key, 0)) <= 0:
                    errors.append(f"{key} 必须为正数")
            except (TypeError, ValueError):
                errors.append(f"{key} 必须为数字")
        return errors

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key: str, value) -> bool:
        with self._lock:
            self._data[key] = value
        return self.save()

    def set_many(self, **kwargs) -> bool:
        with self._lock:
            for k, v in kwargs.items():
                self._data[k] = v
        return self.save()

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
