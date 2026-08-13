"""日志：logs/app.log、excel.log、sync.log、import.log。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False
_loggers: dict[str, logging.Logger] = {}


def setup_logging(logs_dir: Path) -> None:
    global _configured
    if _configured:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    for name in ("app", "excel", "sync", "import"):
        logger = logging.getLogger(f"ham.{name}")
        logger.setLevel(logging.INFO)
        logger.propagate = False  # 各自独立文件，避免向根 logger 重复写
        handler = RotatingFileHandler(
            logs_dir / f"{name}.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        _loggers[name] = logger
    # 根日志兜底
    root = logging.getLogger("ham")
    if not root.handlers:
        root.setLevel(logging.INFO)
        root_handler = RotatingFileHandler(
            logs_dir / "app.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        root_handler.setFormatter(fmt)
        root.addHandler(root_handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ham.{name}")
