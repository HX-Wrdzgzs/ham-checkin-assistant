"""本场资料补全预览，以及用户主动触发的工信部型号核准查询。"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from providers.miit import MiitProvider, MiitQueryError, RESULT_PAGE_URL
from services.app_service import AppService


class MiitSearchWorker(QThread):
    """显式查询也必须离开 UI 线程，官网慢时不能冻结记录页。"""

    result = Signal(object)

    def __init__(self, query: str, parent=None) -> None:
        super().__init__(parent)
        self.query = query

    def run(self) -> None:
        try:
            results = MiitProvider().search(self.query, limit=3)
            self.result.emit({"ok": True, "query": self.query, "results": results})
        except MiitQueryError as exc:
            self.result.emit({"ok": False, "query": self.query, "error": str(exc)})
        except Exception:  # noqa: BLE001
            self.result.emit({
                "ok": False,
                "query": self.query,
                "error": "工信部查询暂时不可用，请稍后重试或打开官网查询",
            })


class MiitResultDialog(QDialog):
    def __init__(self, query: str, results: list[dict], *, cached: bool = False,
                 origin: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("工信部型号核准候选")
        self.resize(1050, 430)
        self.results = list(results[:3])
        origin = origin or ("本地缓存" if cached else "工信部公开查询")
        intro = QLabel(
            f"关键词：{query}　来源：{origin}\n"
            "请选择与台友实际上报一致的型号。核准结果证明型号存在，不代表台友本次一定使用该设备。"
        )
        intro.setWordWrap(True)
        table = QTableWidget(len(self.results), 7)
        table.setHorizontalHeaderLabels(
            ["设备型号", "设备类别", "设备名称", "申请单位", "核准代码", "CMIIT ID", "发证日期"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, result in enumerate(self.results):
            values = [
                result.get("model", ""),
                result.get("device_class", ""),
                result.get("device_name", ""),
                result.get("applicant", ""),
                result.get("approval_code", ""),
                result.get("cmiit_id", ""),
                result.get("approved_at", ""),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value or "")))
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        if self.results:
            table.selectRow(0)
        self.table = table

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("采用所选型号")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(table)
        layout.addWidget(buttons)

    def selected_result(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.results):
            return dict(self.results[row])
        return None


class CompletionDialog(QDialog):
    """建议预览：安全项默认勾选，推测/覆盖项必须人工选择。"""

    _HEADERS = ["应用", "序号", "呼号", "字段", "当前值", "建议值", "来源", "置信度", "处理级别"]

    def __init__(self, service: AppService, session_id: int,
                 suggestions: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.session_id = session_id
        self.suggestions = [dict(item) for item in suggestions]
        self.apply_result: dict | None = None
        self._miit_worker: MiitSearchWorker | None = None
        self._miit_target_record_id: int | None = None
        self.setWindowTitle("本场资料补全")
        self.resize(1500, 760)

        intro = QLabel(
            "安全补齐会默认勾选：未识别原文的精确恢复、确定性词典、明确行政区划，以及同次报到中的等价规范值。\n"
            "覆盖已有且含义不同的内容、冲突历史、工信部候选默认不勾选；街道、天线类型和功率不会凭设备规格猜造。"
        )
        intro.setWordWrap(True)
        self.stats = QLabel("")
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._HEADERS))
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._update_stats)
        self._reload_table()

        action_row = QHBoxLayout()
        safe_button = QPushButton("只选安全项")
        safe_button.clicked.connect(self._select_safe)
        clear_button = QPushButton("全部取消")
        clear_button.clicked.connect(self._clear_selection)
        self.local_miit_button = QPushButton("搜索本地型号库")
        self.local_miit_button.clicked.connect(self._search_local_miit)
        self.miit_button = QPushButton("在线查询工信部（手动）")
        self.miit_button.clicked.connect(self._query_miit)
        official_button = QPushButton("打开工信部查询页")
        official_button.clicked.connect(self._open_official)
        action_row.addWidget(safe_button)
        action_row.addWidget(clear_button)
        action_row.addSpacing(18)
        action_row.addWidget(self.local_miit_button)
        action_row.addWidget(self.miit_button)
        action_row.addWidget(official_button)
        action_row.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用选中补全")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.stats)
        layout.addLayout(action_row)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self._update_stats()

    def _reload_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.suggestions))
        for row, item in enumerate(self.suggestions):
            check = QTableWidgetItem("")
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                           Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Checked if item.get("default_selected") else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, check)
            values = [
                item.get("sequence_no", ""),
                item.get("callsign", ""),
                item.get("field_label", item.get("field", "")),
                item.get("old_value", ""),
                item.get("proposed_value", ""),
                item.get("source_label", ""),
                f"{int(item.get('confidence') or 0)}%",
                item.get("risk", ""),
            ]
            for offset, value in enumerate(values, start=1):
                cell = QTableWidgetItem(str(value or ""))
                if offset != 5:  # “建议值”允许直接修正，其余列只读。
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell.setToolTip(str(item.get("source_detail") or ""))
                self.table.setItem(row, offset, cell)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.blockSignals(False)

    def _update_stats(self, *_args) -> None:
        selected = 0
        safe = 0
        for row, item in enumerate(self.suggestions):
            check = self.table.item(row, 0)
            if check and check.checkState() == Qt.CheckState.Checked:
                selected += 1
                if item.get("default_selected"):
                    safe += 1
        self.stats.setText(
            f"共 {len(self.suggestions)} 项建议　已选 {selected} 项（其中默认安全项 {safe} 项）　"
            "鼠标停在“来源”上可查看依据"
        )

    def _select_safe(self) -> None:
        for row, item in enumerate(self.suggestions):
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if item.get("default_selected") else Qt.CheckState.Unchecked)

    def _clear_selection(self) -> None:
        for row in range(len(self.suggestions)):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)

    def _current_suggestion(self) -> tuple[int, dict] | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.suggestions):
            return row, self.suggestions[row]
        return None

    def _query_miit(self) -> None:
        current = self._current_suggestion()
        if current is None:
            QMessageBox.information(self, "工信部型号核准", "请先选中要核对的记录")
            return
        _row, suggestion = current
        record_id = int(suggestion["record_id"])
        checkin = self.service.repo.get_checkin(record_id)
        if checkin is None:
            QMessageBox.warning(self, "工信部型号核准", "记录已变化，请关闭后重新生成补全建议")
            return
        default = suggestion.get("proposed_value", "") if suggestion.get("field") == "device" else ""
        default = default or checkin.device_standard
        query, ok = QInputDialog.getText(
            self, "工信部型号核准", "输入设备型号关键词（建议只输入型号，如 UV-K6）：",
            text=str(default or ""))
        query = query.strip()
        if not ok or not query:
            return
        if self._miit_worker is not None and self._miit_worker.isRunning():
            return
        self._miit_target_record_id = record_id
        self.miit_button.setEnabled(False)
        self.miit_button.setText("工信部查询中…")
        worker = MiitSearchWorker(query, self)
        worker.result.connect(self._miit_done)
        worker.finished.connect(lambda: self._miit_finished(worker))
        self._miit_worker = worker
        worker.start()

    def _search_local_miit(self) -> None:
        """只查本地已验证快照；快速录入/补全不会因型号查询隐式联网。"""
        current = self._current_suggestion()
        if current is None:
            QMessageBox.information(self, "本地型号库", "请先选中要核对的记录")
            return
        _row, suggestion = current
        if suggestion.get("field") != "device":
            QMessageBox.information(self, "本地型号库", "本地工信部库只用于核对设备字段")
            return
        checkin = self.service.repo.get_checkin(int(suggestion["record_id"]))
        if checkin is None:
            QMessageBox.warning(self, "本地型号库", "记录已变化，请关闭后重新生成补全建议")
            return
        default = suggestion.get("proposed_value", "") or checkin.device_standard
        query, ok = QInputDialog.getText(
            self, "本地型号库", "输入设备型号关键词（只查本地，不联网）：",
            text=str(default or ""))
        query = query.strip()
        if not ok or not query:
            return
        results = self.service.search_miit_radio_models(query, limit=3)
        if not results:
            QMessageBox.information(
                self, "本地型号库",
                "本地没有匹配记录。请先在设置页下载电台型号库；需要临时核对时可使用“在线查询工信部（手动）”。")
            return
        dialog = MiitResultDialog(
            query, results, origin="本地已验证电台型号库", parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = dialog.selected_result()
            if chosen:
                self._adopt_miit_result(chosen)

    def _miit_finished(self, worker: MiitSearchWorker) -> None:
        if self._miit_worker is worker:
            self._miit_worker = None
        self.miit_button.setEnabled(True)
        self.miit_button.setText("在线查询工信部（手动）")

    def _miit_done(self, payload: dict) -> None:
        query = str(payload.get("query") or "")
        cached = False
        results = payload.get("results") or []
        if payload.get("ok") and results:
            self.service.cache_miit_device_results(query, results)
        elif not results:
            results = self.service.cached_miit_device_results(query, limit=3)
            cached = bool(results)
        if not results:
            QMessageBox.warning(
                self, "工信部型号核准",
                f"{payload.get('error') or '没有找到匹配的型号核准记录'}\n\n"
                "可以打开官网缩短关键词后重试；软件不会因此修改任何记录。")
            return
        dialog = MiitResultDialog(query, results, cached=cached, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_result()
        if chosen:
            self._adopt_miit_result(chosen)

    def _adopt_miit_result(self, result: dict) -> None:
        record_id = self._miit_target_record_id
        if record_id is None:
            return
        checkin = self.service.repo.get_checkin(record_id)
        if checkin is None:
            return
        proposed = str(result.get("standard_name") or result.get("model") or "").strip()
        if not proposed or proposed == checkin.device_standard:
            return
        detail_parts = [
            str(result.get("device_name") or "").strip(),
            str(result.get("applicant") or "").strip(),
            f"核准代码 {result.get('approval_code')}" if result.get("approval_code") else "",
        ]
        detail = "；".join(part for part in detail_parts if part)
        target_row = next(
            (row for row, item in enumerate(self.suggestions)
             if int(item["record_id"]) == record_id and item["field"] == "device"),
            None,
        )
        if target_row is None:
            suggestion = {
                "record_id": record_id,
                "session_id": checkin.session_id,
                "sequence_no": checkin.sequence_no,
                "callsign": checkin.callsign,
                "field": "device",
                "field_label": "设备",
                "old_value": checkin.device_standard,
                "old_unmatched": checkin.unmatched,
                "proposed_value": proposed,
                "source_type": "miit_user_selected",
                "source_label": "工信部核准（人工选择）",
                "source_detail": detail,
                "confidence": 100,
                "default_selected": True,
                "risk": "人工已确认",
                "evidence": "",
                "candidate_id": str(result.get("article_id") or ""),
                "miit_article_id": str(result.get("article_id") or ""),
                "miit_sync_run_id": str(result.get("miit_sync_run_id") or ""),
            }
            self.suggestions.append(suggestion)
            self._reload_table()
            target_row = len(self.suggestions) - 1
        else:
            item = self.suggestions[target_row]
            item.update(
                proposed_value=proposed,
                source_type="miit_user_selected",
                source_label="工信部核准（人工选择）",
                source_detail=detail,
                confidence=100,
                default_selected=True,
                risk="人工已确认",
                evidence="",
                candidate_id=str(result.get("article_id") or ""),
                miit_article_id=str(result.get("article_id") or ""),
                miit_sync_run_id=str(result.get("miit_sync_run_id") or ""),
            )
            self.table.item(target_row, 5).setText(proposed)
            self.table.item(target_row, 6).setText(item["source_label"])
            self.table.item(target_row, 7).setText("100%")
            self.table.item(target_row, 8).setText("人工已确认")
        self.table.item(target_row, 0).setCheckState(Qt.CheckState.Checked)
        self.table.selectRow(target_row)
        self._update_stats()

    def _open_official(self) -> None:
        current = self._current_suggestion()
        query = ""
        if current is not None:
            _row, item = current
            if item.get("field") == "device":
                query = str(item.get("proposed_value") or item.get("old_value") or "").strip()
        if query:
            QApplication.clipboard().setText(query)
        webbrowser.open(RESULT_PAGE_URL)
        QMessageBox.information(
            self, "工信部型号核准",
            "已打开官方结果查询页。" + ("设备关键词也已复制到剪贴板。" if query else ""))

    def _apply(self) -> None:
        selected: list[dict] = []
        for row, original in enumerate(self.suggestions):
            check = self.table.item(row, 0)
            if not check or check.checkState() != Qt.CheckState.Checked:
                continue
            item = dict(original)
            proposed = self.table.item(row, 5).text().strip()
            if proposed != str(original.get("proposed_value") or "").strip():
                item["source_type"] = "manual_review"
                item["source_label"] = "补全预览中人工修改"
                item["source_detail"] = (
                    f"用户将原建议“{original.get('proposed_value', '')}”改为“{proposed}”后应用")
                item["confidence"] = 100
                item["evidence"] = ""
            item["proposed_value"] = proposed
            selected.append(item)
        result = self.service.apply_completion_suggestions(selected, self.session_id)
        if not result.get("ok"):
            QMessageBox.warning(self, "资料补全", result.get("message", "应用失败"))
            return
        self.apply_result = result
        self.accept()

    def reject(self) -> None:
        if self._miit_worker is not None and self._miit_worker.isRunning():
            QMessageBox.information(self, "工信部型号核准", "查询正在后台完成，请稍候再关闭窗口")
            return
        super().reject()
