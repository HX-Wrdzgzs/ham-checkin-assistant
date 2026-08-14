"""江苏省中继 HAM 智能点名录入助手 —— 入口。

纯本地：规则 + 缩写 + SQLite 历史 + 统计 + 模糊匹配，无任何 AI 依赖。
"""
from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from config.settings import settings
from core.logging_setup import get_logger

log = get_logger("app")

SINGLE_INSTANCE_LOCK = "Global\\HAMCheckinAssistant_SingleInstance"


def _install_exception_hooks() -> None:
    """全局异常处理（任务书第四阶段 #8）：未捕获异常/线程异常/日志都保留到日志文件。"""

    def excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("Unhandled exception:\n%s", text)
        try:
            from core.logging_setup import log_file_path

            log.error("详情见日志：%s", log_file_path())
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = excepthook
    # 线程异常（QThread.run 等）也会进入 sys.excepthook
    if hasattr(sys, "threading"):
        import threading

        def thread_hook(args):
            exc_type, exc_value, exc_tb = args.exc_type, args.exc_value, args.exc_tb
            text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            log.error("Unhandled thread exception:\n%s", text)

        threading.excepthook = thread_hook
    # Qt 消息（qWarning/qCritical 等）重定向到日志
    qInstallMessageHandler(_qt_message_handler)


def _qt_message_handler(mode, context, message):
    if mode >= 3:  # QtWarningMsg=3 及以上写日志，避免刷屏
        log.warning("Qt: %s", message)
    return None


def main() -> int:
    _install_exception_hooks()
    from ui.single_instance import acquire

    if not acquire(SINGLE_INSTANCE_LOCK):
        # 第二个实例：拒绝启动，避免第二个 SQLite writer / Excel controller / 365dt sync。
        # （把已有窗口拉到前台留作后续增强；此处最少实现：提示后退出。）
        return _second_instance_message()

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


def _second_instance_message() -> int:
    app = QApplication(sys.argv)
    QMessageBox.warning(None, "已在运行",
                        "点名助手已有一个实例在运行，请勿重复启动。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
