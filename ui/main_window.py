"""主窗口：选项卡 + 托盘 + 悬浮快速录入窗 + 全局快捷键 + 崩溃恢复 + 启动同步。"""
from __future__ import annotations


from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTabWidget,
    QVBoxLayout, QWidget,
)

from services.app_service import AppService
from ui.hotkey import GlobalHotkey
from ui.pages import (
    HistoryPage, MonitorPage, SessionPage, SettingsPage, StationPage,
)
from ui.quick_input import QuickInputPanel
from ui.worker_manager import WorkerManager


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
        # 快速点名：SQLite 立即提交，Excel 在输入空闲后合并 Save。
        # dirty 只表示本进程有“已写入 Excel 内存但尚未 Save”的记录。
        self._excel_flush_dirty = False
        self._excel_flush_failed = False
        self._undo_in_progress = False
        self._excel_flush_timer = QTimer(self)
        self._excel_flush_timer.setSingleShot(True)
        self._excel_flush_timer.timeout.connect(self._flush_excel_pending)
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
        self.session_page.excel_update_requested.connect(self._submit_excel_update)
        self.station_page = StationPage(service)
        # 统一后台任务管理器（P1-3）：单一任务 + 有序退出
        self._workers = WorkerManager(service.settings, self)
        self.history_page = HistoryPage(service, workers=self._workers)
        self.settings_page = SettingsPage(service)
        # NRL Nanny 只读监听（第四阶段）：点击候选填入快速录入框，绝不自动提交
        self.monitor_page = MonitorPage(
            service,
            fill_candidate=lambda cs: self._fill_quick_input(cs))
        self.quick_panel.input.textChanged.connect(self._on_input_activity)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.quick_panel, "快速点名")
        self.tabs.addTab(self.session_page, "本场记录")
        self.tabs.addTab(self.station_page, "呼号库")
        self.tabs.addTab(self.history_page, "历史数据")
        self.tabs.addTab(self.monitor_page, "NRL 监听")
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
        self.floating.panel.input.textChanged.connect(self._on_input_activity)
        self._save_excel_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_excel_shortcut.activated.connect(
            lambda: self._flush_excel_pending(manual=True))
        self.hotkey = GlobalHotkey(str(service.settings.get("global_hotkey", "Ctrl+Space")), self)
        self.hotkey.activated.connect(self._toggle_floating)
        self.hotkey.start()
        # P1-14：设置保存后热更新全局快捷键 / 悬浮窗外观
        self.settings_page._on_settings_applied = self._apply_settings_callback

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
        if self._excel_flush_dirty and not self._flush_excel_pending(manual=True):
            return
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
            if (self.service.current_session() is not None
                    and target.id != self.service.current_session().id
                    and self._excel_flush_dirty
                    and not self._flush_excel_pending(manual=True)):
                return
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

    def _excel_save_delay_ms(self) -> int:
        try:
            value = int(self.service.settings.get("excel_save_delay_ms", 600))
        except (TypeError, ValueError):
            value = 600
        return max(100, min(value, 5000))

    def _schedule_excel_flush(self) -> None:
        if (not self._excel_flush_dirty
                or not bool(self.service.settings.get("excel_auto_save", True))
                or self._excel_flush_failed):
            return
        self._excel_flush_timer.start(self._excel_save_delay_ms())

    def _on_input_activity(self, text: str) -> None:
        """输入中持续重置 Excel 保存计时器，只在真正空闲后 Save。"""
        if text.strip():
            self._schedule_excel_flush()

    def _flush_excel_pending(self, manual: bool = False) -> bool:
        """空闲/手动保存 Excel；返回 False 表示本次保存失败。"""
        self._excel_flush_timer.stop()
        if not manual and not self._excel_flush_dirty:
            return True
        ok, msg = self.service.flush_excel_pending()
        if ok:
            self._excel_flush_dirty = False
            self._excel_flush_failed = False
            if msg != "没有缺失记录":
                self.statusBar().showMessage(f"Excel：{msg}", 5000)
                self.session_page.refresh()
            return True
        self._excel_flush_failed = True
        self.statusBar().showMessage(f"Excel：{msg}", 8000)
        self._feedback(f"Excel：{msg}", ok=False)
        return False

    def _submit_excel_update(self, task: dict) -> None:
        """把修改后的单行 Excel 同步交给独立 worker，主窗口不等待 COM Save。"""
        if self._workers.submit_excel_update(task, self._excel_update_done):
            self.statusBar().showMessage("Excel 正在后台保存修改…", 6000)
            return
        # 同步/导入任务占用 worker 时不强行抢占；SQLite 已更新，记录保持 pending，
        # 用户可稍后点击“保存/补同步”重试，避免为了 Excel 再次阻塞主线程。
        self.statusBar().showMessage(
            "Excel 后台任务忙，修改已保存在 SQLite，稍后点击“保存/补同步”重试", 8000)
        self._feedback("Excel 后台任务忙，修改已保存在 SQLite，稍后补同步", ok=False)

    def _excel_update_done(self, result: dict) -> None:
        """后台 Excel 更新完成后回到 UI 线程写入同步状态并刷新表格。"""
        ok, msg = self.service.finish_deferred_excel_update(result)
        if ok:
            self.statusBar().showMessage(f"Excel：{msg}", 6000)
        else:
            self.statusBar().showMessage(f"Excel：{msg}", 8000)
            self._feedback(f"Excel：{msg}", ok=False)
        self.session_page.refresh()

    def _on_submitted(self, result) -> None:
        # 先把记录写入 SQLite/Excel 内存，Save 留给空闲计时器合并处理；
        # 这样下一位呼号可以立即开始输入，不会被 Excel COM Save 卡住。
        res = self.service.commit(result, save_excel=False)
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
        elif res.get("excel_state") == "written":
            self._excel_flush_dirty = True
            self._excel_flush_failed = False
            msg += "　Excel：待保存"
            self._schedule_excel_flush()
        elif not res.get("excel_persisted", False):
            msg += f"　Excel: {res.get('excel_msg')}"
        self.statusBar().showMessage(msg, 5000)
        self._feedback(msg)
        self.session_page.refresh()
        self.quick_panel._refresh_meta()
        self.floating.panel._refresh_meta()

    def _on_undo(self) -> None:
        if self._undo_in_progress:
            return
        self._undo_in_progress = True
        self._excel_flush_timer.stop()
        self._excel_flush_dirty = False
        self._excel_flush_failed = False
        try:
            # 记录级撤销不能触发同步 COM 重排；否则 Excel 卡顿会冻结窗口并
            # 让用户后续的 Ctrl+Z 连续变成多次业务撤销。
            res = self.service.undo_last(sync_excel=False)
            if res.get("ok"):
                msg = (f"已撤销 #{res['checkin'].sequence_no} {res['checkin'].callsign}"
                       f"　Excel：{res.get('excel_msg', '')}")
                self.statusBar().showMessage(msg, 8000)
                self._feedback(msg)
            else:
                msg = res.get("message", "撤销失败")
                self.statusBar().showMessage(msg, 5000)
                self._feedback(msg, ok=False)
            self.session_page.refresh()
            self.quick_panel._refresh_meta()
            self.floating.panel._refresh_meta()
        finally:
            self._undo_in_progress = False

    def _fill_quick_input(self, callsign: str) -> None:
        """NRL Nanny 候选点击 → 填入快速录入框（绝不自动提交）。"""
        cs = (callsign or "").strip().upper()
        if not cs:
            return
        text = self.quick_panel.input.text().strip()
        self.quick_panel.input.setText(f"{text + ' ' if text else ''}{cs} ")
        self.quick_panel._schedule_parse()
        self.quick_panel.input.setFocus()

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
    def _apply_settings_callback(self, candidate: dict) -> None:
        """P1-14：设置保存后立即应用 UI 层运行时（全局快捷键 / 悬浮窗外观）。"""
        new_hk = str(candidate.get("global_hotkey") or "Ctrl+Space")
        if new_hk != getattr(self.hotkey, "sequence", ""):
            try:
                self.hotkey.stop()
                self.hotkey = GlobalHotkey(new_hk, self)
                self.hotkey.activated.connect(self._toggle_floating)
                self.hotkey.start()
            except Exception:  # noqa: BLE001
                pass
        try:
            opacity = float(candidate.get("window_opacity", 0.95))
            on_top = bool(candidate.get("window_on_top", True))
            self.floating.setWindowOpacity(max(0.2, min(1.0, opacity)))
            self.floating.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        except Exception:  # noqa: BLE001
            pass

    def _startup_sync(self) -> None:
        # P1-3：统一 WorkerManager 提交；已有任务则跳过
        self._workers.submit_sync(self._sync_done, message_cb=self.history_page._log)

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
        # 退出前最后一次冲刷快速录入留下的 written 行；失败也不丢 SQLite，
        # 数据库状态会保留为未同步，下一次可从“补同步缺失”继续。
        self._flush_excel_pending(manual=True)
        self.floating.save_position()
        self.hotkey.stop()
        # 第四阶段：应用退出时先安全停止 NRL 监听线程
        try:
            self.monitor_page.monitor.stop()
        except Exception:  # noqa: BLE001
            pass
        # P1-3：统一停止后台任务（stop accepting → cancel → wait → worker 关自己 DB）
        self._workers.shutdown(timeout_ms=8000)
        # 正常退出不应在下次启动被误判为崩溃；只记录本地场次，外部历史场次不进入恢复。
        self.service.mark_clean_shutdown()
        self.service.close()
        self._tray.hide()
        QApplication.quit()
