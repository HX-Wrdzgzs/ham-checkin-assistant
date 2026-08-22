"""应用配置与用户数据路径。

配置、SQLite、日志和备份默认位于用户 LocalAppData，而不是程序目录；
这样 EXE 放在任意目录、通过快捷方式或安装器启动都不会改变数据位置。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path


def _program_dir() -> Path:
    """程序/资源目录，只用于读取资源，不用于写运行时数据。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _user_data_dir() -> Path:
    """返回当前用户可写的运行时目录，不依赖 EXE 的位置或工作目录。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "HAM点名助手"
        # 极少数精简 Windows 环境没有 LOCALAPPDATA 时的安全回退。
        return Path.home() / "AppData" / "Local" / "HAM点名助手"
    base = os.environ.get("XDG_STATE_HOME") or os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "ham-checkin-assistant"
    return Path.home() / ".local" / "state" / "ham-checkin-assistant"


PROGRAM_DIR = _program_dir()
# APP_DIR 保留为兼容名称：它代表程序目录，不再代表可写数据目录。
APP_DIR = PROGRAM_DIR
USER_DATA_DIR = _user_data_dir()
CONFIG_PATH = USER_DATA_DIR / "config.json"


def _copy_tree_without_overwrite(source: Path, target: Path) -> None:
    """复制旧运行目录，但不覆盖目标中已有的任何用户文件。"""
    if not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        dest = target / relative
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif item.is_file() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


def _legacy_path(root: Path, value, default_name: str) -> Path:
    """按旧版本规则解析相对路径；绝对路径代表用户明确指定的位置。"""
    raw = str(value or default_name).strip() or default_name
    path = Path(raw)
    return path if path.is_absolute() else root / path


def migrate_legacy_runtime(legacy_root: Path | None = None,
                           target_root: Path | None = None) -> tuple[bool, str]:
    """把旧版 EXE 同目录运行数据复制到用户目录。

    只在目标配置不存在时由默认 ``Settings()`` 调用。复制采用“目标已有文件
    不覆盖”策略，旧目录也不会删除，方便用户在迁移异常时恢复。返回
    ``(成功, 提示)``，不把迁移失败伪装成新空数据库。
    """
    legacy_root = Path(legacy_root or PROGRAM_DIR)
    target_root = Path(target_root or USER_DATA_DIR)
    if legacy_root.resolve() == target_root.resolve():
        return True, ""

    legacy_config = legacy_root / "config.json"
    if not legacy_config.exists():
        # 没有旧配置时，仅当旧版运行目录确实存在才迁移默认目录。
        if not any((legacy_root / name).exists()
                   for name in ("data", "logs", "backup")):
            return True, ""
        legacy_values = {}
    else:
        try:
            with legacy_config.open(encoding="utf-8") as stream:
                legacy_values = json.load(stream)
            if not isinstance(legacy_values, dict):
                legacy_values = {}
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"旧配置读取失败：{exc}"

    try:
        target_root.mkdir(parents=True, exist_ok=True)
        for key, default_name in (("data_dir", "data"),
                                  ("logs_dir", "logs"),
                                  ("backup_dir", "backup")):
            raw = legacy_values.get(key, default_name)
            source = _legacy_path(legacy_root, raw, default_name)
            # 绝对路径是用户主动指定的数据位置，不复制也不改写。
            if not Path(str(raw or default_name)).is_absolute():
                _copy_tree_without_overwrite(source, target_root / str(raw or default_name))

        target_config = target_root / "config.json"
        if legacy_config.exists() and not target_config.exists():
            shutil.copy2(legacy_config, target_config)
    except (OSError, shutil.Error) as exc:
        return False, f"旧运行数据迁移失败：{exc}"
    return True, f"已从 {legacy_root} 迁移旧运行数据"


def _default_legacy_root() -> Path | None:
    """冻结版才自动迁移 EXE 同目录；源码目录不应被当成用户数据目录。"""
    if not getattr(sys, "frozen", False):
        return None
    if PROGRAM_DIR.resolve() == USER_DATA_DIR.resolve():
        return None
    return PROGRAM_DIR

DEFAULTS: dict = {
    # 常规
    "default_province": "江苏",
    "default_repeater_name": "江苏省中继",
    "default_operator_callsign": "",
    # 快捷键
    "global_hotkey": "Ctrl+Space",
    # 快速点名写入 / 下一位按键。默认保留 Enter，避免升级后改变既有操作习惯。
    "quick_submit_key": "Enter",
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


QUICK_SUBMIT_KEY_OPTIONS = (
    "Enter",
    "Space",
    "Ctrl+Enter",
    "Shift+Enter",
    "Alt+Enter",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
)


def normalize_quick_submit_key(value) -> str:
    """把用户配置的快速点名提交键规范为稳定名称。"""
    raw = str(value or "").strip().replace(" ", "")
    aliases = {
        "enter": "Enter", "return": "Enter",
        "space": "Space", "spacebar": "Space",
        "ctrl+enter": "Ctrl+Enter", "control+enter": "Ctrl+Enter",
        "shift+enter": "Shift+Enter", "alt+enter": "Alt+Enter",
    }
    lowered = raw.lower()
    if lowered in aliases:
        return aliases[lowered]
    upper = raw.upper()
    if upper.startswith("F") and upper[1:].isdigit():
        candidate = f"F{int(upper[1:])}"
        if candidate in QUICK_SUBMIT_KEY_OPTIONS:
            return candidate
    return "Enter"


def is_valid_quick_submit_key(value) -> bool:
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return False
    normalized = normalize_quick_submit_key(raw)
    return normalized != "Enter" or raw.lower() in {"enter", "return"}


class Settings:
    """线程安全的配置读写。改动即时落盘。"""

    def __init__(self, path: Path | None = None) -> None:
        self._migration_note = ""
        if path is None:
            legacy_root = _default_legacy_root()
            if legacy_root is not None and not CONFIG_PATH.exists():
                ok, note = migrate_legacy_runtime(legacy_root, USER_DATA_DIR)
                if not ok:
                    # 迁移失败时继续使用旧配置/旧目录，避免启动一个空数据库，
                    # 直到用户处理权限或磁盘问题后再迁移。
                    legacy_config = legacy_root / "config.json"
                    if legacy_config.exists():
                        self._path = legacy_config
                        self._migration_note = note
                    else:
                        raise RuntimeError(note)
                else:
                    self._migration_note = note
            if not hasattr(self, "_path"):
                self._path = CONFIG_PATH
        else:
            self._path = Path(path)
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

    @property
    def migration_note(self) -> str:
        """旧版运行数据迁移提示；空串表示没有发生迁移。"""
        return self._migration_note

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
        submit_key = candidate.get(
            "quick_submit_key", self.get("quick_submit_key", "Enter"))
        if not is_valid_quick_submit_key(submit_key):
            errors.append("quick_submit_key 不是支持的快速点名提交键")
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

    def _runtime_dir(self, key: str, default_name: str) -> Path:
        raw = str(self.get(key, default_name) or default_name).strip() or default_name
        path = Path(raw)
        # 相对路径以 config.json 所在的用户数据目录为基准，而不是 cwd/EXE 目录。
        return path if path.is_absolute() else self._path.parent / path

    @property
    def data_dir(self) -> Path:
        return self._runtime_dir("data_dir", "data")

    @property
    def logs_dir(self) -> Path:
        return self._runtime_dir("logs_dir", "logs")

    @property
    def backup_dir(self) -> Path:
        return self._runtime_dir("backup_dir", "backup")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ham_checkin.db"

    @property
    def path(self) -> Path:
        """配置文件路径（自动备份元数据需记录 config checksum）。"""
        return self._path


settings = Settings()
