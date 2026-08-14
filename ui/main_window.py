"""主窗口：选项卡 + 托盘 + 悬浮快速录入窗 + 全局快捷键 + 崩溃恢复 + 启动同步。"""
from __future__ import annotations


from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTabWidget,
    QVBoxLayout, QWidget,
)

from services.app_service import AppService
from ui.hotkey import GlobalHotkey
from ui.pages import (
    HistoryPage, SessionPage, SettingsPage, StationPage,
)
from ui.quick_input import QuickInputPanel
from ui.pages import _SyncWorker


def _app_icon() -> QIcon:
    import sys as _sys
    from pathlib import Path
    base = Path(getattr(_sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    ico = base / "assets" / "icon.ico"
    if ico.exists():
        return QIcon(str(ico))
    # 兜底：找不到图标文件时绘制一个
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setBrush(Qt.GlobalColor.blue)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(Qt.GlobalColor.white)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "HAM")
    p.end()
    return QIcon(pix)


class FloatingQuickWindow(QWidget):
    """置顶、可拖动、可调透明度的小悬浮窗。"""

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.service = service
        self.setWindowTitle("快速录入")
        self.panel = QuickInputPanel(service, self, compact=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.panel)
        self.setWindowOpacity(float(service.settings.get("window_opacity", 0.95)))
        pos = service.settings.get("window_position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            self.move(int(pos["x"]), int(pos["y"]))
        self._drag = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        super().mouseReleaseEvent(e)

    def save_position(self) -> None:
        pos = self.pos()
        self.service.settings.set("window_position", {"x": pos.x(), "y": pos.y()})


class MainWindow(QMainWindow):
    def __init__(self, service: AppService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("江苏省中继点名助手")
        self.setWindowIcon(_app_icon())
        self.resize(860, 640)

        # 顶部：当前场次 + 操作
        self.session_lbl = QLabel("")
        self.btn_new_session = QPushButton("新建场次")
        self.btn_new_session.clicked.connect(self._new_session)
        self.btn_pick_session = QPushButton("选择场次")
        self.btn_pick_session.clicked.connect(self._pick_session)
        self.btn_floating = QPushButton("悬浮窗")
        self.btn_floating.setCheckable(True)
        self.btn_floating.clicked.connect(self._toggle_floating)
        top = QHBoxLayout()
        top.addWidget(self.session_lbl)
        top.addStretch()
        top.addWidget(self.btn_floating)
        top.addWidget(self.btn_new_session)
        top.addWidget(self.btn_pick_session)
        top_w = QWidget(); top_w.setLayout(top)

        # 选项卡
        self.quick_panel = QuickInputPanel(service)
        self.quick_panel.submitted.connect(self._on_submitted)
        self.quick_panel.undo_requested.connect(self._on_undo)
        self.session_page = SessionPage(service)
        self.station_page = StationPage(service)
        self.history_page = HistoryPage(service)
        self.settings_page = SettingsPage(service)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.quick_panel, "快速点名")
        self.tabs.addTab(self.session_page, "本场记录")
        self.tabs.addTab(self.station_page, "呼号库")
        self.tabs.addTab(self.history_page, "历史数据")
        self.tabs.addTab(self.settings_page, "设置")

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(top_w)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.statusBar().showMessage("就绪")

        # 悬浮窗 + 快捷键 + 托盘
        self.floating = FloatingQuickWindow(service)
        self.floating.panel.submitted.connect(self._on_submitted)
        self.floating.panel.undo_requested.connect(self._on_undo)
        self.hotkey = GlobalHotkey(str(service.settings.get("global_hotkey", "Ctrl+Space")), self)
        self.hotkey.activated.connect(self._toggle_floating)
        self.hotkey.start()

        self._tray = QSystemTrayIcon(_app_icon(), self)
        menu = QMenu()
        act_show = QAction("显示/隐藏悬浮窗", self); act_show.triggered.connect(self._toggle_floating)
        act_main = QAction("打开主窗口", self); act_main.triggered.connect(self._show_main)
        act_quit = QAction("退出", self); act_quit.triggered.connect(self._quit)
        menu.addAction(act_show); menu.addAction(act_main); menu.addSeparator(); menu.addAction(act_quit)
        self._tray.setContextMenu(menu)
        self._tray.setToolTip("江苏省中继点名助手")
        self._tray.activated.connect(lambda reason: self._show_main() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self._tray.show()

        # 崩溃恢复 + 初始化
        # 必须在窗口 show 之后再弹恢复对话框：直接在这里弹模态框时父窗口
        # 尚未可见，对话框会不可见地阻塞 __init__，导致窗口不出现、启动同步
        # 也不执行（ponytail: 2026-08-08 启动卡死 bug）。延迟到事件循环跑起来。
        # 正确顺序（任务书第一阶段 #5）：读已有 active → 崩溃恢复 → 处理完成
        # → 仍无 current session 才创建新场次（绝不先建 ghost 再恢复）。
        QTimer.singleShot(0, self._startup_after_recovery)
        self._refresh_session()
        self._refresh_all()
        self._startup_sync()

    def _startup_after_recovery(self) -> None:
        self._crash_recovery()
        # 恢复处理完成后仍无当前场次 → 才创建新场次
        if self.service.current_session() is None:
            self.service.create_session()
        self._refresh_all()

    # ---------- 刷新 ----------
    def _refresh_session(self) -> None:
        s = self.service.current_session()
        if s:
            n = self.service.repo.next_sequence(s.id)
            self.session_lbl.setText(f"当前场次：{s.name}　{s.date}　(下一序号 {n})")
        else:
            self.session_lbl.setText("未选择场次")

    def _refresh_all(self) -> None:
        self._refresh_session()
        self.quick_panel._refresh_meta()
        self.session_page.refresh()
        self.history_page.refresh()

    # ---------- 场次 ----------
    def _new_session(self) -> None:
        self.service.create_session()
        self._refresh_all()

    def _pick_session(self) -> None:
        sessions = self.service.all_sessions()
        if not sessions:
            QMessageBox.information(self, "场次", "暂无场次，请先新建")
            return
        items = [f"[{s.id}] {s.name}　{s.date}　({s.status})" for s in sessions]
        choice, ok = QInputDialog.getItem(self, "选择场次", "选择当前场次：", items, 0, False)
        if ok:
            idx = items.index(choice)
            target = sessions[idx]
            if not self.service.set_current_session(target.id):
                # ended 场次默认只读，需显式重新打开（任务书第一阶段 #4）
                again = QMessageBox.question(
                    self, "场次已结束",
                    f"「{target.name}」已结束（只读）。\n是否重新打开该场次以便继续录入？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if again == QMessageBox.Yes:
                    self.service.reopen_session(target.id)
                else:
                    return
            self._refresh_all()

    def _crash_recovery(self) -> None:
        active = self.service.startup_sessions()
        if not active:
            return
        items = [f"[{s.id}] {s.name}　{s.date}" for s in active]
        items += ["── 结束所有未结束场次 ──", "── 稍后处理 ──"]
        choice, ok = QInputDialog.getItem(self, "检测到未结束点名",
                                          "上次有未结束的场次：\n" + "\n".join(
                                              f"{s.name} {s.date}" for s in active),
                                          items, 0, False)
        if not ok:
            self.service.handle_crash_recovery("defer")
            return
        idx = items.index(choice)
        if idx < len(active):
            sid = self.service.handle_crash_recovery(str(active[idx].id))
            if sid is not None:
                ok2, msg = self.service.excel_connect()
                self.statusBar().showMessage(f"已继续场次，Excel：{msg}", 5000)
        elif "结束所有" in choice:
            self.service.handle_crash_recovery("end_all")
        else:
            self.service.handle_crash_recovery("defer")

    # ---------- 提交 / 撤销 ----------
    def _feedback(self, text: str, ok: bool = True) -> None:
        self.quick_panel.set_feedback(text, ok)
        self.floating.panel.set_feedback(text, ok)

    def _on_submitted(self, result) -> None:
        res = self.service.commit(result)
        if not res.get("ok"):
            msg = res.get("message", "提交失败")
            self.statusBar().showMessage(msg, 5000)
            self._feedback(msg, ok=False)
            return
        c = res["checkin"]
        msg = f"已写入 #{c.sequence_no} {c.callsign}"
        if res.get("duplicate"):
            msg += "（本场重复）"
        if not res.get("excel_ok"):
            msg += f"　Excel: {res.get('excel_msg')}"
        self.statusBar().showMessage(msg, 5000)
        self._feedback(msg)
        self.session_page.refresh()
        self.quick_panel._refresh_meta()
        self.floating.panel._refresh_meta()

    def _on_undo(self) -> None:
        res = self.service.undo_last()
        if res.get("ok"):
            msg = f"已撤销 #{res['checkin'].sequence_no} {res['checkin'].callsign}"
            self.statusBar().showMessage(msg, 5000)
            self._feedback(msg)
        else:
            msg = res.get("message", "撤销失败")
            self.statusBar().showMessage(msg, 5000)
            self._feedback(msg, ok=False)
        self.session_page.refresh()
        self.quick_panel._refresh_meta()
        self.floating.panel._refresh_meta()

    # ---------- 悬浮窗 ----------
    def _toggle_floating(self) -> None:
        if self.floating.isVisible():
            self.floating.hide()
            self.btn_floating.setChecked(False)
        else:
            self.floating.show()
            self.floating.raise_()
            self.floating.activateWindow()
            self.floating.panel.focus_input()
            self.btn_floating.setChecked(True)

    def _show_main(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    # ---------- 365dt 启动一次 ----------
    def _startup_sync(self) -> None:
        self._sync_worker = _SyncWorker(self.service)
        self._sync_worker.done.connect(self._sync_done)
        self._sync_worker.start()

    def _sync_done(self, result: dict) -> None:
        if result.get("ok"):
            failed = result.get("failed") or []
            if failed:
                shown = "、".join(failed[:5]) + ("…" if len(failed) > 5 else "")
                msg = (f"365dt 已同步：新增 {result.get('inserted')} 条，"
                       f"{len(failed)} 个呼号拉取失败（{shown}），可在历史数据页重试")
            else:
                msg = f"365dt 已同步：新增 {result.get('inserted')} 条"
            self.statusBar().showMessage(msg, 8000)
            self.history_page._log(msg)
        else:
            self.statusBar().showMessage(f"365dt 同步失败（不影响本地使用）", 8000)
            self.history_page._log(f"启动同步失败：{result.get('message')}")
        self.station_page.refresh()
        self.history_page.refresh()

    # ---------- 关闭 / 退出 ----------
    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
        self.statusBar().showMessage("已最小化到托盘（右键托盘图标退出）", 5000)

    def _quit(self) -> None:
        self.floating.save_position()
        self.hotkey.stop()
        # 任务书第二阶段 #25：停止/等待后台 worker，不能 close DB 时 worker 还在跑
        w = getattr(self, "_sync_worker", None)
        if w is not None and w.isRunning():
            w.wait(3000)
        self.service.close()
        self._tray.hide()
        QApplication.quit()
