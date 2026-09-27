"""主窗口各选项卡页面。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QProgressBar,
)

from config.settings import QUICK_SUBMIT_KEY_OPTIONS, normalize_quick_submit_key
from excel.exporter import hhmm, export_template
from normalizers.device_aliases import device_model_abbreviations
from services.app_service import AppService
from services.monitor_service import MonitorService
from ui.source_labels import source_label


def _button(text: str, on_click=None, icon_text: str = "") -> QPushButton:
    b = QPushButton(f"{icon_text} {text}".strip())
    if on_click:
        b.clicked.connect(on_click)
    return b


def _documents_dir() -> Path:
    """用户导出文件的默认位置，不随软件启动目录变化。"""
    raw = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(raw) if raw else Path.home() / "Documents"


def _fill_table(table: QTableWidget, headers: list[str], rows: list[list], stretch_col: int = -1):
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(val if val is not None else "")))
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch_col >= 0:
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)


# --------------------------------------------------------------------------
class SessionPage(QWidget):
    """本场记录：查看/修改/撤销/导出/Excel 连接与一致性。"""

    excel_update_requested = Signal(object)

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.table = QTableWidget()
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.info_lbl = QLabel("")
        self.stats_lbl = QLabel("")
        self.excel_lbl = QLabel("○ 未连接")
        self._ids: list[int] = []
        self._undo_in_progress = False
        # 操作按钮分成两行，避免 12 个按钮的总 minimumSizeHint 把主窗口
        # 撑到 1200 像素以上。窗口变窄时表格可以横向滚动，操作区仍然可用。
        actions = [
            _button("撤销选中/上一行", self._undo, "↶"),
            _button("修改选中", self._edit, "✎"),
            _button("资料补全", self._complete_records, "✦"),
            _button("选择场次补全", self._choose_completion_session, "⌕"),
            _button("补全记录", self._show_completion_batches, "▤"),
            _button("撤销补全", self._undo_completion, "↶"),
            _button("导出本场", self._export, "⇩"),
            _button("连接 Excel", self._connect, "🔌"),
            _button("保存/补同步", self._sync_missing, "⇢"),
            _button("一致性检查", self._check, "✔"),
            _button("复制本场", self._copy, "⧉"),
            _button("结束本场", self._end, "⏹"),
        ]
        action_rows = QVBoxLayout()
        action_rows.setContentsMargins(0, 0, 0, 0)
        for start in range(0, len(actions), 6):
            row = QHBoxLayout()
            for button in actions[start:start + 6]:
                row.addWidget(button)
            row.addStretch()
            action_rows.addLayout(row)
        lay = QVBoxLayout(self)
        lay.addWidget(self.info_lbl)
        lay.addWidget(self.excel_lbl)
        lay.addWidget(self.stats_lbl)
        lay.addLayout(action_rows)
        lay.addWidget(self.table)

    def refresh(self) -> None:
        session = self.service.current_session()
        if not session:
            self.info_lbl.setText("未选择场次")
            self.stats_lbl.setText("")
            self.excel_lbl.setText("○ 未连接")
            self._ids = []
            _fill_table(self.table, [], [])
            return
        checkins = self.service.list_checkins(session.id)
        self._ids = [c.id for c in checkins]
        self.info_lbl.setText(
            f"{session.name}　{session.date}　状态:{session.status}　共 {len(checkins)} 条")
        stats = self.service.session_stats(session.id)
        self.stats_lbl.setText(
            f"本场报到 {stats['total']}　首次出现 {stats['first']}　"
            f"重复报到 {stats['dup']}　省外 {stats['outside']}")
        self.excel_lbl.setText(self.service.excel_status_text())
        rows = [[c.sequence_no, hhmm(c.checkin_time), c.callsign,
                 self.service.full_qth(c.qth_standard), c.device_standard, c.antenna_standard,
                 c.power_standard, c.signal, source_label(c.source), c.unmatched]
                for c in checkins]
        _fill_table(self.table,
                    ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率", "信号", "来源", "未识别"],
                    rows, stretch_col=3)

    def _selected_row(self) -> int:
        return self.table.currentRow()

    def _undo(self) -> None:
        if self._undo_in_progress:
            return
        self._undo_in_progress = True
        try:
            # 整场 Excel 重排包含 COM Save，不能在按钮事件里同步执行。
            # 数据库先安全软删除，Excel 保留原表并留下可补同步状态。
            result = self.service.undo_last(sync_excel=False)
        finally:
            self._undo_in_progress = False
        if result.get("ok"):
            c = result["checkin"]
            self._show_status(
                f"已撤销 #{c.sequence_no} {c.callsign}　Excel：{result.get('excel_msg', '')}")
        else:
            self._show_status(result.get("message", "撤销失败"))
        self.refresh()

    def _edit(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self._ids):
            return
        field_map = {"QTH": "qth", "设备": "device", "天线": "antenna",
                     "功率": "power", "信号": "signal"}
        field, ok = QInputDialog.getItem(self, "修改", "选择字段：",
                                         list(field_map.keys()), 0, False)
        if not ok:
            return
        new_value, ok = QInputDialog.getText(self, "修改", f"新的{field}：")
        if not ok:
            return
        # 修改入口不再同步等待 Excel.Save；主窗口把快照交给独立 COM worker。
        res = self.service.update_checkin(
            self._ids[row], field_map[field], new_value.strip(), defer_excel=True)
        if not res.get("ok"):
            QMessageBox.warning(self, "修改", res.get("message", "修改失败"))
        else:
            task = res.get("excel_task")
            if task is not None:
                self.excel_update_requested.emit(task)
                self._show_status("SQLite 已更新，Excel 正在后台保存，不会阻塞窗口")
            elif res.get("excel_msg"):
                self._show_status(f"已更新（{res['excel_msg']}）")
        self.refresh()

    def _show_status(self, message: str) -> None:
        """成功提示使用状态栏，避免修改完成后再弹模态框挡住快速操作。"""
        window = self.window()
        status_bar = getattr(window, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage(message, 6000)

    def _complete_records(self) -> None:
        session = self.service.current_session()
        if session is None:
            session = self._choose_local_session("选择需要补全的本地场次")
        if session is None:
            return
        self._complete_for_session(session)

    def _choose_completion_session(self) -> None:
        session = self._choose_local_session("选择需要补全的本地场次")
        if session is not None:
            self._complete_for_session(session)

    def _choose_local_session(self, title: str):
        sessions = self.service.all_sessions()
        if not sessions:
            QMessageBox.information(self, "资料补全", "暂无本地场次")
            return None
        current = self.service.current_session()
        items = [
            f"[{s.id}] {s.name}　{s.date}　({s.status})"
            for s in sessions
        ]
        default = next((i for i, s in enumerate(sessions)
                        if current is not None and s.id == current.id), 0)
        choice, ok = QInputDialog.getItem(self, title, "场次（活动/已结束均可，外部历史已过滤）：",
                                          items, default, False)
        if not ok:
            return None
        return sessions[items.index(choice)]

    def _complete_for_session(self, session) -> None:
        suggestions = self.service.completion_suggestions(session.id)
        if not suggestions:
            QMessageBox.information(
                self, "资料补全",
                f"「{session.name}」暂时没有可确认的补全建议。\n"
                "未识别原文仍然完整保存在 SQLite/Excel 中，可先导入历史或补充词典后再试。")
            return
        from ui.completion_dialog import CompletionDialog

        dialog = CompletionDialog(self.service, session.id, suggestions, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.apply_result:
            return
        result = dialog.apply_result
        task = result.get("excel_task")
        if task is not None:
            self.excel_update_requested.emit(task)
        status_suffix = "（已结束场次保持 ended，未重新开启）" if session.status == "ended" else ""
        self._show_status(result.get("message", "资料补全已保存") + status_suffix)
        self.refresh()

    def _undo_completion(self) -> None:
        session = self.service.current_session()
        if session is None:
            session = self._choose_local_session("选择要撤销补全的本地场次")
        if session is None:
            return
        answer = QMessageBox.question(
            self, "撤销资料补全",
            "撤销当前场次最后一批资料补全？\n"
            "如果补全后又手工修改过相关字段，软件会拒绝撤销以避免覆盖。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.service.undo_last_completion(session.id)
        if not result.get("ok"):
            QMessageBox.warning(self, "撤销资料补全", result.get("message", "撤销失败"))
            return
        task = result.get("excel_task")
        if task is not None:
            self.excel_update_requested.emit(task)
        self._show_status(result.get("message", "已撤销上一批资料补全"))
        self.refresh()

    def _show_completion_batches(self) -> None:
        session = self._choose_local_session("查看哪个场次的补全记录")
        if session is None:
            return
        batches = self.service.list_completion_batches(session.id, limit=100)
        if not batches:
            QMessageBox.information(self, "补全记录", f"「{session.name}」还没有补全批次")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"补全记录：{session.name}（{session.date}）")
        dialog.resize(1050, 560)
        table = QTableWidget(len(batches), 8)
        table.setHorizontalHeaderLabels(
            ["批次", "应用时间", "状态", "记录数", "字段数", "Excel", "Excel错误", "查看"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, batch in enumerate(batches):
            values = [
                batch.get("batch_id", ""), batch.get("created_at", ""),
                batch.get("status", ""), batch.get("record_count", 0),
                batch.get("change_count", 0), batch.get("excel_status", ""),
                batch.get("excel_error", ""), "双击查看明细",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, batch.get("batch_id"))
                table.setItem(row, col, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        detail = QTextEdit(); detail.setReadOnly(True); detail.setMinimumHeight(180)

        def show_detail(_row: int, _column: int = 0) -> None:
            current_row = table.currentRow()
            if current_row < 0:
                return
            batch_id = str(table.item(current_row, 0).data(Qt.ItemDataRole.UserRole) or "")
            details = self.service.completion_batch_details(batch_id)
            detail.setPlainText("\n".join(
                f"#{item.get('record_id')} {item.get('field_name')}: "
                f"{item.get('old_value') or '（空）'} → {item.get('new_value') or '（空）'}；"
                f"未识别：{item.get('old_unmatched') or '（空）'} → "
                f"{item.get('new_unmatched') or '（空）'}；"
                f"来源：{item.get('source_type')} / {item.get('source_detail') or '-'}；"
                f"置信度：{item.get('confidence', 0)}%；"
                f"工信部记录：{item.get('miit_article_id') or '-'}；"
                f"状态：{item.get('status')}"
                for item in details
            ) or "该批次没有字段明细")

        table.cellClicked.connect(show_detail)
        table.cellDoubleClicked.connect(show_detail)
        if batches:
            table.selectRow(0)
            show_detail(0)
        close_button = _button("关闭", dialog.reject)
        button_row = QHBoxLayout(); button_row.addStretch(); button_row.addWidget(close_button)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "补全先写入 SQLite，再异步同步对应场次的 Excel。Excel 失败不会删除补全，"
            "可从本场记录重新补同步。"))
        layout.addWidget(table)
        layout.addWidget(detail)
        layout.addLayout(button_row)
        dialog.exec()

    def _export(self) -> None:
        session = self.service.current_session()
        if not session:
            return
        default = str(_documents_dir() / f"{session.name or '点名'}_{session.date or ''}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "导出本场", default, "Excel (*.xlsx)")
        if path:
            self.service.export_session(session.id, path)
            QMessageBox.information(self, "导出", f"已导出：\n{path}")

    def _connect(self) -> None:
        ok, msg = self.service.excel_connect()
        QMessageBox.information(self, "连接 Excel", msg)
        self.refresh()

    def _sync_missing(self) -> None:
        ok, msg = self.service.excel_sync_missing()
        QMessageBox.information(self, "补同步", msg)
        self.refresh()

    def _check(self) -> None:
        ok, msg = self.service.check_consistency()
        box = QMessageBox(self)
        box.setWindowTitle("一致性检查")
        box.setText(msg)
        box.exec()

    def _copy(self) -> None:
        text = self.service.copy_session_text()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制本场", f"已复制 {text.count(chr(10)) + 1} 行到剪贴板")

    def _end(self) -> None:
        self.service.end_current_session()
        QMessageBox.information(self, "场次", "本场已结束")


# --------------------------------------------------------------------------
class StationPage(QWidget):
    """呼号库：搜索呼号，显示画像与历史。"""

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.search = QLineEdit()
        self.search.setPlaceholderText("输入呼号搜索")
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget()
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(220)
        split_lay = QVBoxLayout()
        split_lay.addWidget(self.table)
        split_lay.addWidget(self.detail)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addLayout(split_lay)

    def refresh(self) -> None:
        kw = self.search.text().strip()
        stations = self.service.list_stations(kw, limit=200)
        rows = [[s["callsign"], s["checkin_count"], s["last_seen"], s["last_qth"],
                 s["last_device"], s["last_power"]]
                for s in stations]
        _fill_table(self.table, ["呼号", "次数", "最近", "QTH", "设备", "功率"], rows, stretch_col=0)
        if rows:
            self.table.selectRow(0)

    def _show_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        callsign = self.table.item(row, 0).text()
        info = self.service.station_summary(callsign)
        st = info["station"] or {}
        lines = [f"呼号：{callsign}", f"签到次数：{st.get('checkin_count', 0)}",
                 f"首次：{st.get('first_seen', '-')}　最近：{st.get('last_seen', '-')}", ""]
        for ft, label in (("qth", "QTH"), ("device", "设备"), ("antenna", "天线"), ("power", "功率")):
            freq = " / ".join(info["profiles"].get(ft, [])[:5]) or "-"
            lines.append(f"最常用{label}：{freq}")
        lines.append("")
        lines.append("最近历史：")
        for c in info["history"][:10]:
            lines.append(f"  {hhmm(c.checkin_time)} {c.callsign} {c.qth_standard or ''} "
                         f"{c.device_standard or ''} {c.antenna_standard or ''} {c.power_standard or ''}")
        self.detail.setPlainText("\n".join(lines))


# --------------------------------------------------------------------------
class HistoryPage(QWidget):
    """历史数据：导入 Excel / 文件夹 / 立即检查 365dt / 重算画像 / 日志。"""

    def __init__(self, service: AppService, parent=None, workers=None) -> None:
        super().__init__(parent)
        self.service = service
        # P1-3：共享 WorkerManager（由主窗口创建）；没有则建一个独立的
        self.workers = workers
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        btn_row = QHBoxLayout()
        btn_row.addWidget(_button("导入 Excel 文件", self._import_files))
        btn_row.addWidget(_button("导入文件夹", self._import_folder))
        btn_row.addWidget(_button("立即检查 365dt", self._sync, "⟳"))
        btn_row.addWidget(_button("重新计算画像", self._rebuild))
        btn_row.addWidget(_button("生成词典建议", self._suggest_aliases, "⚡"))
        btn_row.addStretch()
        self.status_lbl = QLabel("")
        lay = QVBoxLayout(self)
        lay.addLayout(btn_row)
        lay.addWidget(self.status_lbl)
        lay.addWidget(QLabel("导入日志："))
        lay.addWidget(self.log_view)

    def refresh(self) -> None:
        self.status_lbl.setText(
            f"365dt：{self.service.sync_state_text()}　|　原始导入记录："
            f"{len(self.service.raw_imports())}")

    def _log(self, text: str) -> None:
        self.log_view.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    def _import_files(self) -> None:
        # P2：只支持 .xlsx，文件选择器不再提供 .xls；导入在 worker 中执行（大文件不卡 UI）
        paths, _ = QFileDialog.getOpenFileNames(self, "选择历史 Excel", "", "Excel (*.xlsx)")
        if not paths:
            return
        self._ensure_workers()
        if not self.workers.submit_import(
                [Path(p) for p in paths],
                done_cb=self._import_done, message_cb=self._log):
            self._log("已有任务在进行，请稍候")

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder:
            return
        self._ensure_workers()
        if not self.workers.submit_import(
                Path(folder), done_cb=self._import_done,
                message_cb=self._log, folder=True):
            self._log("已有任务在进行，请稍候")

    def _ensure_workers(self) -> None:
        if self.workers is None:
            from ui.worker_manager import WorkerManager
            self.workers = WorkerManager(self.service.settings, self)

    def _import_done(self, res: dict) -> None:
        if "__error__" in res:
            self._log(str(res["__error__"]))
        else:
            # ImportWorker 使用独立 SQLite 连接；任务完成后在主线程刷新
            # 历史观察缩写，让未核准机型也能在下一次输入中补全。
            self.service.refresh_observed_device_aliases()
            self._log(f"导入完成：{len(res)} 个文件")
        self.refresh()

    def _sync(self) -> None:
        # P1-3：统一 WorkerManager（单任务），已有任务则提示
        if self.workers is None:
            from ui.worker_manager import WorkerManager
            self.workers = WorkerManager(self.service.settings, self)
        if not self.workers.submit_sync(self._sync_done, message_cb=self._log):
            self._log("同步正在进行，请稍候")
            return
        self.status_lbl.setText("365dt 同步中…")

    def _sync_done(self, result: dict) -> None:
        self.status_lbl.setText("")
        if result.get("ok"):
            # SyncWorker 同样使用独立连接，365dt 写入完成后重新读取
            # 观察型号，避免把后台刚同步的机型等到下次启动才可用。
            self.service.refresh_observed_device_aliases()
            failed = result.get("failed") or []
            msg = (f"365dt 同步完成：新增 {result.get('inserted')} 条，"
                   f"跳过 {result.get('skipped')} 条")
            if failed:
                shown = "、".join(failed[:5]) + ("…" if len(failed) > 5 else "")
                msg += f"；{len(failed)} 个呼号拉取失败（{shown}），可再点一次重试"
            self._log(msg)
        else:
            self._log(f"365dt 同步失败：{result.get('message')}")
        self.refresh()

    def _rebuild(self) -> None:
        n = self.service.repo.rebuild_profiles()
        self._log(f"画像已重算（{n} 条记录）")

    def _suggest_aliases(self) -> None:
        sugg = self.service.suggest_aliases_from_imports()
        if not sugg:
            QMessageBox.information(
                self, "词典建议",
                "暂无建议。\n需要先导入 365dt 或 Excel 历史数据，且其中的缩写尚未收录词典。")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"词典建议（{len(sugg)} 条，勾选后加入）")
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["加入", "类型", "别名", "标准值", "次数"])
        table.setRowCount(len(sugg))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for r, s in enumerate(sugg):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setCheckState(Qt.CheckState.Checked)
            table.setItem(r, 0, it)
            table.setItem(r, 1, QTableWidgetItem(s["kind"]))
            table.setItem(r, 2, QTableWidgetItem(s["alias"]))
            table.setItem(r, 3, QTableWidgetItem(s["standard"]))
            table.setItem(r, 4, QTableWidgetItem(str(s["count"])))
        table.verticalHeader().setVisible(False)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        btn_ok = _button("加入选中", lambda: dlg.accept())
        btn_cancel = _button("取消", lambda: dlg.reject())
        row = QHBoxLayout(); row.addStretch(); row.addWidget(btn_ok); row.addWidget(btn_cancel)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "从本地签到、365dt 和 Excel 历史记录推导设备/QTH 缩写；"
            "只生成建议，勾选“加入选中”后才会永久写入词典："
        ))
        lay.addWidget(table)
        lay.addLayout(row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        picked = []
        for r, s in enumerate(sugg):
            if table.item(r, 0).checkState() == Qt.CheckState.Checked:
                picked.append(s)
        if not picked:
            return
        added = self.service.add_alias_suggestions(picked)
        self._log(f"已加入词典建议 {added} 条")
        self.refresh()


# --------------------------------------------------------------------------
class SettingsPage(QWidget):
    """设置：常规 / Excel / 365dt / 阈值 / 词典管理。"""

    qth_sync_requested = Signal()
    qth_sync_cancel_requested = Signal()
    def __init__(self, service: AppService, workers=None, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.s = service.settings
        self.workers = workers
        # P1-14：保存后 UI 层回调（如重新注册全局快捷键），由主窗口注入
        self._on_settings_applied = None
        tabs = QTabWidget()
        tabs.addTab(self._build_general(), "常规")
        tabs.addTab(self._build_excel(), "Excel")
        tabs.addTab(self._build_sync(), "365dt / 监听")
        tabs.addTab(self._build_qth_places(), "QTH 地点")
        tabs.addTab(self._build_thresholds(), "解析")
        tabs.addTab(self._build_aliases(), "词典")
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(_button("保存设置", self._save, "💾"))

    # ---- 常规 ----
    def _build_general(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_default_province = QLineEdit(str(self.s.get("default_province")))
        self.ed_default_repeater = QLineEdit(str(self.s.get("default_repeater_name")))
        self.ed_default_operator = QLineEdit(str(self.s.get("default_operator_callsign")))
        self.ed_hotkey = QLineEdit(str(self.s.get("global_hotkey")))
        self.cb_submit_key = QComboBox()
        submit_labels = {
            "Enter": "Enter（默认）",
            "Space": "Space / 空格（单呼号快速提交）",
            "Ctrl+Enter": "Ctrl+Enter",
            "Shift+Enter": "Shift+Enter",
            "Alt+Enter": "Alt+Enter",
        }
        for key in QUICK_SUBMIT_KEY_OPTIONS:
            self.cb_submit_key.addItem(submit_labels.get(key, key), key)
        current_submit = normalize_quick_submit_key(
            self.s.get("quick_submit_key", "Enter"))
        idx = self.cb_submit_key.findData(current_submit)
        self.cb_submit_key.setCurrentIndex(max(0, idx))
        self.cb_submit_key.setToolTip(
            "选择 Space 后，单独输入有效呼号时按空格即可写入并进入下一位；"
            "如需继续录入 QTH/设备，请用 Shift+Space 输入第一个分隔空格，完整字段可用 Ctrl+Enter 提交。")
        self.sp_backup = QSpinBox(); self.sp_backup.setRange(1, 90); self.sp_backup.setValue(int(self.s.get("backup_keep", 30)))
        f.addRow("默认省份", self.ed_default_province)
        f.addRow("默认中继名称", self.ed_default_repeater)
        f.addRow("默认主控呼号", self.ed_default_operator)
        f.addRow("全局快捷键", self.ed_hotkey)
        f.addRow("快速点名写入键", self.cb_submit_key)
        f.addRow("备份保留份数", self.sp_backup)
        # P2：悬浮窗透明度 / 置顶控件
        self.sp_opacity = QDoubleSpinBox(); self.sp_opacity.setRange(0.3, 1.0)
        self.sp_opacity.setSingleStep(0.05)
        self.sp_opacity.setValue(float(self.s.get("window_opacity", 0.95)))
        f.addRow("悬浮窗透明度", self.sp_opacity)
        self.cb_ontop = QCheckBox("悬浮窗置顶")
        self.cb_ontop.setChecked(bool(self.s.get("window_on_top", True)))
        f.addRow("", self.cb_ontop)
        self.lbl_db = QLabel(str(self.s.db_path))
        self.lbl_db.setWordWrap(True)
        self.lbl_db.setMinimumWidth(0)
        self.lbl_db.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        f.addRow("数据库文件", self.lbl_db)
        # P2：备份 / 恢复
        row = QHBoxLayout()
        row.addWidget(_button("立即备份", self._backup_now, "💾"))
        row.addWidget(_button("从备份恢复…", self._restore_backup, "↩"))
        f.addRow("", row)
        return w

    def _backup_now(self) -> None:
        ok, msg = self.service.backup_now()
        QMessageBox.information(self, "备份", msg) if ok else \
            QMessageBox.warning(self, "备份失败", msg)

    def _restore_backup(self) -> None:
        """P2：列出备份（含 quick_check 状态）供选择恢复。"""
        backups = self.service.list_backups()
        if not backups:
            QMessageBox.information(self, "恢复", "暂无备份")
            return
        names = [f"{b['name']}{'（有效）' if b['valid'] else '（损坏）'}" for b in backups]
        item, ok = QInputDialog.getItem(self, "从备份恢复", "选择备份：", names, 0, False)
        if not ok:
            return
        idx = names.index(item)
        b = backups[idx]
        if not b["valid"]:
            QMessageBox.warning(self, "恢复", "该备份已损坏（quick_check 失败），拒绝恢复")
            return
        if QMessageBox.question(self, "恢复", "恢复将覆盖当前数据库，确定？") != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self.service.restore_backup(b["name"])
        QMessageBox.information(self, "恢复", msg) if ok else \
            QMessageBox.warning(self, "恢复失败", msg)

    # ---- Excel ----
    def _build_excel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_excel_path = QLineEdit(str(self.s.get("excel_template")))
        btn = _button("浏览…", self._pick_excel)
        row = QHBoxLayout(); row.addWidget(self.ed_excel_path); row.addWidget(btn)
        f.addRow("Excel 文件", row)
        self.ed_excel_sheet = QLineEdit(str(self.s.get("excel_sheet_name")))
        f.addRow("Sheet 名称", self.ed_excel_sheet)
        self.cb_auto_save = QCheckBox("连接 Excel 后允许传统自动同步（快速点名不使用）")
        self.cb_auto_save.setChecked(bool(self.s.get("excel_auto_save", True)))
        self.cb_auto_save.setToolTip(
            "快速点名始终只写 SQLite；此选项只影响已连接 Excel 后的旧版同步/补同步路径。"
        )
        f.addRow("", self.cb_auto_save)
        self.sp_excel_delay = QSpinBox()
        self.sp_excel_delay.setRange(100, 5000)
        self.sp_excel_delay.setSingleStep(50)
        self.sp_excel_delay.setValue(int(self.s.get("excel_save_delay_ms", 600)))
        self.sp_excel_delay.setToolTip(
            "仅用于兼容传统 Excel 内存写入路径；快速点名不等待 Excel，也不会触发此计时器。"
        )
        f.addRow("传统 Excel 空闲保存延迟（毫秒）", self.sp_excel_delay)
        f.addRow("", _button("连接 Excel", self._connect_excel))
        f.addRow("", _button("生成空白模板", self._make_template))
        return w

    def _pick_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel", "", "Excel (*.xlsx *.xls)")
        if path:
            self.ed_excel_path.setText(path)

    def _connect_excel(self):
        ok, msg = self.service.excel_connect(self.ed_excel_path.text(), self.ed_excel_sheet.text())
        QMessageBox.information(self, "Excel", msg)

    def _make_template(self):
        default = str(_documents_dir() / "点名模板.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", default, "Excel (*.xlsx)")
        if path:
            export_template(path)
            QMessageBox.information(self, "模板", f"已生成：{path}")

    # ---- 365dt ----
    def _build_sync(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ed_uid = QLineEdit(str(self.s.get("dt365_uid")))
        f.addRow("365dt UID", self.ed_uid)
        self.sp_fetch = QSpinBox()
        self.sp_fetch.setRange(10, 1597)
        self.sp_fetch.setValue(int(self.s.get("dt365_max_fetch", 300)))
        self.sp_fetch.setToolTip("每次同步最多拉取多少个呼号的历史（365dt 每个呼号约返回最近 50 条）")
        f.addRow("每次拉取呼号数", self.sp_fetch)

        # 工信部电台型号库：首次下载/更新均在后台运行，快速点名不依赖网络。
        self.miit_auto = QCheckBox("每周空闲时检查电台型号库更新（不打断点名）")
        self.miit_auto.setChecked(bool(self.s.get("miit_catalog_auto_update", False)))
        f.addRow("工信部自动检查", self.miit_auto)
        self.sp_miit_page = QSpinBox()
        self.sp_miit_page.setRange(5, 1000)
        self.sp_miit_page.setSingleStep(50)
        self.sp_miit_page.setValue(int(self.s.get("miit_catalog_page_size", 1000)))
        self.sp_miit_page.setToolTip("官网拒绝大分页时会自动降级；单线程顺序请求")
        f.addRow("型号库每页数量", self.sp_miit_page)
        self.miit_status = QLabel("")
        self.miit_status.setWordWrap(True)
        self.miit_status.setMinimumWidth(0)
        self.miit_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        f.addRow("型号库状态", self.miit_status)
        self.miit_progress = QProgressBar()
        self.miit_progress.setRange(0, 100)
        self.miit_progress.setValue(0)
        f.addRow("同步进度", self.miit_progress)
        miit_buttons = QHBoxLayout()
        miit_buttons.addWidget(_button("首次下载电台型号库", self._start_miit_full, "⇩"))
        miit_buttons.addWidget(_button("更新电台型号库", self._start_miit_incremental, "⟳"))
        miit_buttons.addWidget(_button("重新完整同步", self._restart_miit_full, "↻"))
        miit_buttons.addWidget(_button("取消同步", self._cancel_miit, "⏹"))
        miit_buttons.addWidget(_button("打开型号库搜索", self._open_miit_search, "⌕"))
        f.addRow("工信部电台库", miit_buttons)
        self._refresh_miit_status()
        return w

    # ---- QTH 地点包 ----
    def _build_qth_places(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.qth_place_status = QLabel("")
        self.qth_place_status.setWordWrap(True)
        self.qth_place_status.setMinimumWidth(0)
        self.qth_place_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        f.addRow("本地地点库", self.qth_place_status)
        self.ed_qth_provinces = QLineEdit(
            ",".join(self.s.get("qth_place_selected_provinces", ["江苏"]) or [])
        )
        self.ed_qth_provinces.setToolTip("用于以后下载/安装地点包，多个省份用逗号分隔")
        f.addRow("计划使用省份", self.ed_qth_provinces)
        self.cb_qth_auto = QCheckBox("启动后后台同步 QTH（不阻塞快速点名）")
        self.cb_qth_auto.setChecked(bool(self.s.get("qth_place_auto_update", True)))
        self.cb_qth_auto.setToolTip(
            "行政区划来自程序内置快照；道路、学校、车站等详细地点需要配置地点包或天地图 Key。"
        )
        f.addRow("后台自动同步", self.cb_qth_auto)
        self.sp_qth_interval = QSpinBox()
        self.sp_qth_interval.setRange(1, 720)
        self.sp_qth_interval.setSuffix(" 小时")
        self.sp_qth_interval.setValue(
            int(self.s.get("qth_place_sync_interval_hours", 24) or 24)
        )
        self.sp_qth_interval.setToolTip("自动同步的最短间隔；手动点击同步不受此间隔限制")
        f.addRow("自动同步间隔", self.sp_qth_interval)
        self.ed_qth_pack_url = QLineEdit(str(self.s.get("qth_place_pack_url", "") or ""))
        self.ed_qth_pack_url.setPlaceholderText("可选：HTTPS JSONL / CSV 地点包地址")
        self.ed_qth_pack_url.setToolTip(
            "如果你有自己的公开地点包，可填 HTTPS 地址；支持 ETag/Last-Modified 缓存。"
        )
        f.addRow("远程地点包", self.ed_qth_pack_url)
        self.ed_qth_tianditu_token = QLineEdit(
            str(self.s.get("qth_tianditu_token", "") or "")
        )
        self.ed_qth_tianditu_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_qth_tianditu_token.setPlaceholderText("可选：天地图 tk / Key")
        self.ed_qth_tianditu_token.setToolTip(
            "只用于后台缓存已保存过的道路/学校/车站等 QTH，不用于全网抓取。"
        )
        f.addRow("天地图 Key", self.ed_qth_tianditu_token)
        self.sp_qth_online_limit = QSpinBox()
        self.sp_qth_online_limit.setRange(0, 50)
        self.sp_qth_online_limit.setSuffix(" 条")
        self.sp_qth_online_limit.setValue(
            int(self.s.get("qth_online_query_limit", 5) or 0)
        )
        self.sp_qth_online_limit.setToolTip("每次后台最多缓存多少条本地历史道路 QTH；0 表示不请求天地图")
        f.addRow("每次在线缓存上限", self.sp_qth_online_limit)
        sync_buttons = QHBoxLayout()
        sync_buttons.addWidget(_button("立即同步 QTH", self.qth_sync_requested.emit, "↻"))
        sync_buttons.addWidget(_button("取消同步", self.qth_sync_cancel_requested.emit, "■"))
        sync_buttons.addStretch()
        f.addRow("手动同步", sync_buttons)
        f.addRow(
            "导入地点包",
            _button("导入 JSONL / CSV 地点包…", self._pick_qth_place_pack, "⇩"),
        )
        qth_help = QLabel(
            "内置行政区会在后台自动校准；远程地点包每行至少包含 name、province、city、"
            "district、canonical_qth，可选 aliases、kind。天地图需要用户自行申请 Key，"
            "这里只缓存已保存过的道路/学校/车站 QTH，不做全网抓取。输入时始终只查本地库，"
            "唯一精确命中才自动采用，同名地点会保留候选供选择。网络失败会保留旧库，"
            "不会阻塞点名或删除已有记录。"
        )
        # 说明文字必须允许换行，否则 QFormLayout 会按整行文本计算
        # minimumSizeHint，把主窗口最小宽度撑到两千像素以上，导致用户无法
        # 拖窄窗口。让标签随设置页宽度换行，同时保留可读的最小高度。
        qth_help.setWordWrap(True)
        qth_help.setMinimumWidth(0)
        f.addRow("说明", qth_help)
        self._refresh_qth_place_status()
        return w

    def _refresh_qth_place_status(self) -> None:
        label = getattr(self, "qth_place_status", None)
        if label is None:
            return
        status = self.service.qth_place_status()
        sync_status = status.get("last_sync_status") or "未同步"
        sync_message = status.get("last_sync_message") or ""
        success_at = status.get("last_success_at") or "尚未成功同步"
        label.setText(
            f"记录 {status.get('count', 0)} 条；最近写入：{status.get('updated_at') or '尚未导入'}\n"
            f"最近成功同步：{success_at}；状态：{sync_status}\n"
            f"{sync_message}\n"
            f"文件：{status.get('path', self.s.qth_place_catalog_path)}"
        )

    def _pick_qth_place_pack(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 QTH 地点包", "",
            "地点包 (*.jsonl *.ndjson *.json *.csv *.gz *.zip)",
        )
        if not path:
            return
        if self.workers is None:
            result = self.service.import_qth_place_pack(path)
            self._qth_place_import_done(result)
            return
        if not self.workers.submit_qth_place_import(path, self._qth_place_import_done):
            QMessageBox.information(
                self, "QTH 地点包", "当前已有后台任务（同步、导入或 Excel 保存），请稍后再试。"
            )
            return
        self.qth_place_status.setText("正在后台导入地点包；快速点名仍可继续。")

    def _qth_place_import_done(self, result: dict) -> None:
        if result.get("ok"):
            refreshed = self.service.refresh_qth_place_catalog()
            self._refresh_qth_place_status()
            if refreshed.get("ok"):
                QMessageBox.information(
                    self, "QTH 地点包", f"已导入/更新 {result.get('count', 0)} 条地点。"
                )
            else:
                QMessageBox.warning(
                    self, "QTH 地点包",
                    "地点包已写入，但主界面刷新失败：" + str(refreshed.get("message")),
                )
        else:
            self._refresh_qth_place_status()
            QMessageBox.warning(self, "QTH 地点包", str(result.get("message") or "导入失败"))

    # ---- 阈值 ----
    def _build_thresholds(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.sp_high = QSpinBox(); self.sp_high.setRange(60, 100); self.sp_high.setValue(int(float(self.s.get("fuzzy_high", 92))))
        self.sp_mid = QSpinBox(); self.sp_mid.setRange(40, 99); self.sp_mid.setValue(int(float(self.s.get("fuzzy_mid", 75))))
        f.addRow("高置信阈值（自动展开）", self.sp_high)
        f.addRow("中置信阈值（候选）", self.sp_mid)
        return w

    # ---- 词典 ----
    def _build_aliases(self) -> QWidget:
        tabs = QTabWidget()
        self._alias_tables = {}
        for kind, title in (("qth", "QTH 别名"), ("device", "设备别名"),
                            ("antenna", "天线别名"), ("power", "功率别名")):
            tabs.addTab(self._alias_tab(kind), title)
        return tabs

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 每次切到设置页都刷新词典，确保“生成词典建议”加入的别名立即可见
        for kind in ("qth", "device", "antenna", "power"):
            self._reload_alias(kind)
        self._refresh_miit_status()
        self._refresh_qth_place_status()

    def _refresh_miit_status(self, progress: dict | None = None) -> None:
        status = self.service.miit_catalog_status()
        run = status.get("run") or {}
        if progress:
            total = int(progress.get("total") or 0)
            scanned = int(progress.get("scanned") or 0)
            pages = int(progress.get("total_pages") or 0)
            page = int(progress.get("page") or 0)
            if total:
                self.miit_progress.setValue(max(0, min(100, int(scanned * 100 / total))))
            self.miit_status.setText(
                f"后台同步：第 {page}/{pages or '?'} 页，已扫描 {scanned} 条，"
                f"保留电台 {progress.get('retained', 0)} 条，"
                f"排除 {progress.get('excluded', 0)} 条，未分类 {progress.get('unknown', 0)} 条"
            )
            return
        if run.get("status") in {"running", "cancelled", "failed"}:
            self.miit_status.setText(
                f"上次同步状态：{run.get('status')}；已扫描 {run.get('scanned_count', 0)} 条。"
                + (f"原因：{run.get('last_error')}" if run.get("last_error") else "")
            )
        else:
            updated = status.get("updated_at") or "尚未完成同步"
            self.miit_status.setText(
                f"本地电台型号：{status.get('count', 0)} 条；最近完成：{updated}；"
                f"规则：{status.get('filter_rule_version', 'radio-v1')}\n"
                f"文件：{status.get('path', self.s.miit_catalog_path)}"
            )

    def _start_miit_full(self) -> None:
        self._start_miit_sync(full=True, resume=True)

    def _restart_miit_full(self) -> None:
        self._start_miit_sync(full=True, resume=False)

    def _start_miit_incremental(self) -> None:
        self._start_miit_sync(full=False)

    def _start_miit_sync(self, *, full: bool, resume: bool = True) -> None:
        if self.workers is None:
            QMessageBox.warning(self, "型号库", "后台任务管理器尚未就绪")
            return
        if not self.workers.submit_miit_catalog(
                full=full, resume=resume,
                done_cb=self._miit_done, progress_cb=self._miit_progress):
            QMessageBox.information(
                self, "型号库", "当前已有后台任务（同步、导入或 Excel 保存），请稍后再试。")
            return
        self.miit_progress.setValue(0)
        if not full:
            action = "正在后台检查更新"
        elif resume:
            action = "正在后台继续读取"
        else:
            action = "正在后台重新读取"
        self.miit_status.setText(
            action
            + "工信部“无线电发射设备型号核准”（category 352），"
            "不会写入蓝牙、模块、手机等非电台记录。"
        )

    def _cancel_miit(self) -> None:
        if self.workers is not None and self.workers.cancel_miit_catalog():
            self.miit_status.setText("正在取消；已完成页会保留断点，下次可继续。")
        else:
            self.miit_status.setText("当前没有正在运行的型号库同步。")

    def _miit_progress(self, payload: dict) -> None:
        self._refresh_miit_status(payload)

    def _miit_done(self, result: dict) -> None:
        refreshed = self.service.refresh_miit_catalog()
        if result.get("ok"):
            self._refresh_miit_status()
            self.miit_progress.setValue(100)
            self._show_status(
                f"工信部电台型号库完成：扫描 {result.get('scanned', 0)} 条，"
                f"保留 {result.get('retained', 0)} 条，排除 {result.get('excluded', 0)} 条"
            )
        else:
            self._refresh_miit_status(result)
            QMessageBox.warning(self, "型号库同步失败", str(result.get("message") or "同步失败"))
        if not refreshed.get("ok"):
            self.miit_status.setText(
                self.miit_status.text() + "\n主界面刷新失败：" + str(refreshed.get("message"))
            )

    def _open_miit_search(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("本地工信部电台型号库搜索")
        dialog.resize(820, 480)
        query = QLineEdit()
        query.setPlaceholderText("型号/品牌/申请单位/核准代码（只查本地，不联网）")
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        detail = QTextEdit(); detail.setReadOnly(True); detail.setMaximumHeight(130)

        def search() -> None:
            # 型号库搜索是资料核对入口，不应沿用现场补全的 3 条候选上限；
            # 搜索品牌（如“泉盛”）时要能看到完整匹配列表。
            rows = self.service.search_miit_radio_models(query.text(), limit=200)
            _fill_table(
                table,
                ["标准名称", "官方型号", "类别", "申请单位", "核准代码", "有效期"],
                [[r.get("standard_name"), r.get("model"), r.get("device_class"),
                  r.get("applicant"), r.get("approval_code"),
                  r.get("expiry_status") or "未标记过期"] for r in rows],
                stretch_col=0,
            )
            detail.setPlainText("\n".join(
                f"{r.get('standard_name') or r.get('model')}：记录 {r.get('article_id')}；"
                f"CMIIT {r.get('cmiit_id') or '-'}；匹配：{r.get('match_reason')}；"
                f"历史核准 {r.get('historical_count', 1)} 条"
                for r in rows
            ))

        row = QHBoxLayout(); row.addWidget(query); row.addWidget(_button("搜索", search, "⌕"))
        lay = QVBoxLayout(dialog); lay.addLayout(row); lay.addWidget(table); lay.addWidget(detail)
        query.returnPressed.connect(search)
        dialog.exec()

    def _alias_tab(self, kind: str) -> QWidget:
        w = QWidget()
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._alias_tables[kind] = table
        add_row = QHBoxLayout()
        ed_alias = QLineEdit(); ed_alias.setPlaceholderText("别名（如 k6）")
        ed_std = QLineEdit(); ed_std.setPlaceholderText("标准值（如 泉盛 UV-K6）")
        add_row.addWidget(ed_alias); add_row.addWidget(ed_std)
        add_row.addWidget(_button("添加", lambda: self._add_alias(kind, ed_alias, ed_std), "＋"))
        if kind == "qth":
            add_row.addWidget(_button("生成缩写", lambda: self._gen_abbr(ed_alias, ed_std), "⚡"))
        elif kind == "device":
            add_row.addWidget(_button("生成缩写", lambda: self._gen_device_abbr(ed_alias, ed_std), "⚡"))
        add_row.addWidget(_button("删除选中", lambda: self._del_alias(kind, table), "－"))
        lay = QVBoxLayout(w)
        lay.addWidget(table)
        lay.addLayout(add_row)
        self._reload_alias(kind)
        return w

    def _gen_abbr(self, ed_alias: QLineEdit, ed_std: QLineEdit) -> None:
        abbr, conflicts = self.service.suggest_qth_abbr(ed_std.text().strip())
        if not abbr:
            QMessageBox.warning(self, "生成缩写", "无法识别该 QTH（" + "；".join(conflicts) + "）")
            return
        ed_alias.setText(abbr)
        if conflicts:
            QMessageBox.warning(self, "生成缩写",
                                f"缩写 {abbr} 已被其他 QTH 占用：{'、'.join(conflicts)}\n"
                                f"请手动改别名，不能覆盖。")

    def _gen_device_abbr(self, ed_alias: QLineEdit, ed_std: QLineEdit) -> None:
        """从用户确认的设备标准名生成主型号缩写，不调用工信部。"""
        values = device_model_abbreviations(ed_std.text().strip())
        if not values:
            QMessageBox.warning(
                self, "生成设备缩写",
                "未找到明确的字母+数字型号。请先填写完整设备名，例如：摩托罗拉 M8268。",
            )
            return
        ed_alias.setText(values[0])
        if len(values) > 1:
            QMessageBox.information(
                self, "生成设备缩写",
                f"已填入主缩写：{values[0]}\n"
                f"还可使用：{'、'.join(values[1:])}\n"
                "点击“添加”后可再分别加入其他缩写。",
            )

    def _reload_alias(self, kind: str) -> None:
        table = self._alias_tables.get(kind)
        if not table:
            return
        aliases = self.service.get_aliases(kind)
        headers = ["别名", "标准值"] + (["省", "市", "区"] if kind == "qth" else [])
        rows = []
        for a in aliases:
            if kind == "qth":
                rows.append([a.alias, a.standard_value, a.province or "", a.city or "", a.district or ""])
            else:
                rows.append([a.alias, a.standard_value])
        _fill_table(table, headers, rows, stretch_col=1)

    def _add_alias(self, kind: str, ed_alias: QLineEdit, ed_std: QLineEdit) -> None:
        alias, std = ed_alias.text().strip(), ed_std.text().strip()
        if alias and std:
            self.service.set_alias(kind, alias, std)
            self._reload_alias(kind)
            ed_alias.clear(); ed_std.clear()

    def _del_alias(self, kind: str, table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            self.service.delete_alias(kind, table.item(row, 0).text())
            self._reload_alias(kind)

    # ---- 保存 ----
    def _save(self) -> None:
        # P1-13：先收集候选 → 校验候选 → 合法才 atomic save（不得先写非法值）
        candidate = {
            "default_province": self.ed_default_province.text().strip() or "江苏",
            "default_repeater_name": self.ed_default_repeater.text().strip(),
            "default_operator_callsign": self.ed_default_operator.text().strip(),
            "global_hotkey": self.ed_hotkey.text().strip() or "Ctrl+Space",
            "quick_submit_key": str(self.cb_submit_key.currentData() or "Enter"),
            "backup_keep": self.sp_backup.value(),
            "window_opacity": float(self.sp_opacity.value()),
            "window_on_top": self.cb_ontop.isChecked(),
            "excel_template": self.ed_excel_path.text().strip(),
            "excel_sheet_name": self.ed_excel_sheet.text().strip(),
            "excel_auto_save": self.cb_auto_save.isChecked(),
            "excel_save_delay_ms": self.sp_excel_delay.value(),
            "dt365_uid": self.ed_uid.text().strip(),
            "dt365_max_fetch": self.sp_fetch.value(),
            "miit_catalog_auto_update": self.miit_auto.isChecked(),
            "miit_catalog_page_size": self.sp_miit_page.value(),
            "qth_place_auto_update": self.cb_qth_auto.isChecked(),
            "qth_place_selected_provinces": [
                item.strip() for item in self.ed_qth_provinces.text().split(",") if item.strip()
            ],
            "qth_place_sync_interval_hours": self.sp_qth_interval.value(),
            "qth_place_pack_url": self.ed_qth_pack_url.text().strip(),
            "qth_tianditu_token": self.ed_qth_tianditu_token.text().strip(),
            "qth_online_query_limit": self.sp_qth_online_limit.value(),
            "fuzzy_high": float(self.sp_high.value()),
            "fuzzy_mid": float(self.sp_mid.value()),
        }
        errors = self.s.validate_candidate(candidate)
        if errors:
            QMessageBox.warning(self, "设置校验失败", "\n".join(errors))
            return
        ok = self.s.set_many(**candidate)
        # P1-14：保存后立即应用运行时（parser 阈值/省份/365dt provider）
        self.service.apply_runtime_settings()
        if not ok:
            # 任务书第三阶段 #16：保存失败必须提示，不得假装成功
            QMessageBox.warning(self, "设置", "配置保存失败（磁盘错误），请检查写入权限")
            return
        if self._on_settings_applied is not None:
            try:
                self._on_settings_applied(candidate)
            except Exception:  # noqa: BLE001
                pass
        QMessageBox.information(self, "设置", "已保存（已即时生效）")


# --------------------------------------------------------------------------
class MonitorPage(QWidget):
    """NRL Nanny 只读监听（第四阶段）。

    启动/停止/重连、状态显示、最近活动、候选呼号提取、点击候选填入 QuickInput。
    **绝不写数据库、绝不自动提交**——只提供候选。
    """

    _state_changed = Signal(str, str)
    _activity = Signal(list)
    _candidates = Signal(list)

    def __init__(self, service: AppService, parent=None,
                 fill_candidate=None) -> None:
        super().__init__(parent)
        self.service = service
        self.fill_candidate = fill_candidate or (lambda cs: None)
        url = str(service.settings.get("nrl_nanny_url", ""))
        poll = float(service.settings.get("nrl_poll_interval", 5.0))
        self.monitor = MonitorService(url=url, poll_interval=poll, timeout=8.0)
        # 后台线程回调 → Qt 信号（排队到主线程更新 UI）
        self.monitor.on_state = self._state_changed.emit
        self.monitor.on_activity = self._activity.emit
        self.monitor.on_candidates = self._candidates.emit
        self._state_changed.connect(self._on_state)
        self._activity.connect(self._on_activity)
        self._candidates.connect(self._on_candidates)

        self.status_lbl = QLabel("● 未监听（offline）")
        self.url_lbl = QLabel(f"地址：{url or '（未配置）'}")
        self.cand_box = QWidget()
        self.cand_lay = QVBoxLayout(self.cand_box)
        self.cand_lay.setContentsMargins(0, 0, 0, 0)
        self.cand_lay.addWidget(QLabel("（无候选）"))
        self.activity = QListWidget()
        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setMaximumHeight(140)
        self.activity.itemClicked.connect(self._activity_clicked)

        btn_row = QHBoxLayout()
        self.btn_start = _button("启动监听", self._start, "▶")
        self.btn_stop = _button("停止监听", self._stop, "⏹")
        self.btn_reconnect = _button("重新连接", self._reconnect, "⟳")
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_reconnect)
        btn_row.addStretch()
        btn_row.addWidget(_button("填入 QuickInput", self._fill_first_candidate, "⤵"))

        lay = QVBoxLayout(self)
        lay.addWidget(self.url_lbl)
        lay.addWidget(self.status_lbl)
        lay.addLayout(btn_row)
        lay.addWidget(QLabel("候选呼号（点击或“填入 QuickInput”）——只作候选，绝不自动提交："))
        lay.addWidget(self.cand_box)
        lay.addWidget(QLabel("最近活动（点击填入呼号）："))
        lay.addWidget(self.activity)
        lay.addWidget(QLabel("原始内容（保留）："))
        lay.addWidget(self.raw_view)

    # ---------- 启停 ----------
    def _start(self) -> None:
        if self.monitor.start():
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)

    def _stop(self) -> None:
        self.monitor.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_lbl.setText("● 未监听（offline）")

    def _reconnect(self) -> None:
        self.monitor.reconnect()
        self.status_lbl.setText("⟳ 重连中…")

    # ---------- 回调（主线程） ----------
    def _on_state(self, state: str, msg: str) -> None:
        color = {"online": "#2E7D32", "degraded": "#EF6C00",
                 "error": "#C62828", "connecting": "#1565C0",
                 "offline": "#616161"}.get(state, "#616161")
        self.status_lbl.setStyleSheet(f"color:{color}; font-weight:bold;")
        self.status_lbl.setText(f"● {msg}（{state}）")

    def _on_activity(self, entries: list) -> None:
        for e in entries[:20]:
            self.activity.insertItem(0, f"{e.get('time', '')} {e.get('callsign', '')}")

    def _on_candidates(self, candidates: list) -> None:
        while self.cand_lay.count():
            item = self.cand_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for cs in candidates[:12]:
            btn = QPushButton(cs)
            btn.clicked.connect(lambda _=False, c=cs: self._fill(c))
            self.cand_lay.addWidget(btn)
        if not candidates:
            self.cand_lay.addWidget(QLabel("（无候选）"))
        self.cand_box.updateGeometry()

    # ---------- 填入 QuickInput ----------
    def _fill(self, callsign: str) -> None:
        self.fill_candidate(callsign)

    def _fill_first_candidate(self) -> None:
        cs = self.monitor.candidates[0] if self.monitor.candidates else ""
        if cs:
            self._fill(cs)

    def _activity_clicked(self, item) -> None:
        parts = (item.text() or "").split()
        cs = parts[-1] if parts else ""
        if cs:
            self._fill(cs)

    def closeEvent(self, event) -> None:
        self.monitor.stop()  # 应用退出/关页时安全停止监听线程
        super().closeEvent(event)
