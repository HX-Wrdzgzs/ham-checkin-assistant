"""江苏省中继 HAM 智能点名录入助手 —— 入口。

纯本地：规则 + 缩写 + SQLite 历史 + 统计 + 模糊匹配，无任何 AI 依赖。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from config.settings import settings
from core.logging_setup import get_logger

log = get_logger("app")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("江苏省中继点名助手")
    app.setOrganizationName("HAM")

    from services.app_service import AppService

    svc = AppService(settings)

    from ui.main_window import MainWindow

    win = MainWindow(svc)
    win.show()
    # 默认显示悬浮快速录入窗，方便主控直接输入
    win._toggle_floating()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
