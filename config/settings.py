"""应用配置：加载/保存 config.json，提供默认值。"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
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
    # 快速点名：停止输入多久后合并保存一次 Excel（毫秒）
    "excel_save_delay_ms": 600,
    "excel_template": "",
    "excel_sheet_name": "",
    # 正常退出后自动恢复上次本地场次；异常退出仍进入崩溃恢复。
    "clean_shutdown": False,
    "last_local_session_id": None,
    # 365dt
    "dt365_uid": "ET6RPQCR",
    "dt365_url": "https://api.365dt.net/dianming/user/ranking.asp?uid={uid}",
    # 默认同步规模：首次 100~300 即可，避免一次性抓 1597（任务书第二阶段 #18）
    "dt365_max_fetch": 200,
    # NRL Nanny（只读监听，绝不自动写库）
    "nrl_nanny_url": "https://nrlnanny-nanjing.bd4rfg.cn",
    "nrl_poll_interval": 5.0,
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
        self._corrupt_note = ""  # P2：配置损坏时保留坏文件并记录提示
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    loaded = json.load(f)
                for k, v in loaded.items():
                    self._data[k] = v
            except json.JSONDecodeError as e:
                # P2：损坏配置绝不静默丢弃——改名保留原文件，供用户/支持检查
                try:
                    bad = self._path.with_suffix(
                        self._path.suffix + f".corrupt-{datetime.now():%Y%m%d%H%M%S}")
                    os.replace(self._path, bad)
                    self._corrupt_note = (
                        f"配置文件损坏，已备份为 {bad.name}，本次使用默认设置")
                except OSError:
                    self._corrupt_note = "配置文件损坏，且无法备份坏文件，本次使用默认设置"
            except OSError:
                self._corrupt_note = "配置文件无法读取，本次使用默认设置"

    @property
    def corrupt_config_note(self) -> str:
        """配置损坏提示（空串=正常）。UI 启动时展示。"""
        return self._corrupt_note

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
        return self.validate_candidate(dict(self._data))

    def validate_candidate(self, candidate: dict) -> list[str]:
        """校验一组候选配置值（P1-13：先验后写，不污染当前配置）。

        用于 UI 收集候选 → 校验 → 合法才 atomic save。
        """
        errors: list[str] = []
        mid = candidate.get("fuzzy_mid", self.get("fuzzy_mid", 75))
        high = candidate.get("fuzzy_high", self.get("fuzzy_high", 92))
        try:
            if float(mid) >= float(high):
                errors.append("fuzzy_mid 必须小于 fuzzy_high")
        except (TypeError, ValueError):
            errors.append("fuzzy_mid / fuzzy_high 必须为数字")
        for key in ("dt365_max_fetch", "backup_keep", "excel_save_delay_ms"):
            v = candidate.get(key, self.get(key, 0))
            try:
                if float(v) <= 0:
                    errors.append(f"{key} 必须为正数")
                elif key == "excel_save_delay_ms" and not 100 <= float(v) <= 5000:
                    errors.append("excel_save_delay_ms 必须在 100~5000 毫秒之间")
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

    @property
    def path(self) -> Path:
        """配置文件路径（自动备份元数据需记录 config checksum）。"""
        return self._path


settings = Settings()
