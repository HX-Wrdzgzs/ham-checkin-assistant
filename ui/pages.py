"""主窗口各选项卡页面。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from excel.exporter import hhmm, export_template
from services.app_service import AppService
from ui.source_labels import field_name, source_label


def _button(text: str, on_click=None, icon_text: str = "") -> QPushButton:
    b = QPushButton(f"{icon_text} {text}".strip())
    if on_click:
        b.clicked.connect(on_click)
    return b


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

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.table = QTableWidget()
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.info_lbl = QLabel("")
        self.stats_lbl = QLabel("")
        self.excel_lbl = QLabel("○ 未连接")
        self._ids: list[int] = []
        btn_row = QHBoxLayout()
        btn_row.addWidget(_button("撤销选中/上一行", self._undo, "↶"))
        btn_row.addWidget(_button("修改选中", self._edit, "✎"))
        btn_row.addWidget(_button("导出本场", self._export, "⇩"))
        btn_row.addWidget(_button("连接 Excel", self._connect, "🔌"))
        btn_row.addWidget(_button("补同步缺失", self._sync_missing, "⇢"))
        btn_row.addWidget(_button("一致性检查", self._check, "✔"))
        btn_row.addWidget(_button("复制本场", self._copy, "⧉"))
        btn_row.addWidget(_button("结束本场", self._end, "⏹"))
        btn_row.addStretch()
        lay = QVBoxLayout(self)
        lay.addWidget(self.info_lbl)
        lay.addWidget(self.excel_lbl)
        lay.addWidget(self.stats_lbl)
        lay.addLayout(btn_row)
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
                 c.qth_standard, c.device_standard, c.antenna_standard,
                 c.power_standard, c.signal, source_label(c.source)]
                for c in checkins]
        _fill_table(self.table,
                    ["序号", "时间", "呼号", "QTH", "设备", "天线", "功率", "信号", "来源"],
                    rows, stretch_col=3)

    def _selected_row(self) -> int:
        return self.table.currentRow()

    def _undo(self) -> None:
        self.service.undo_last()
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
        res = self.service.update_checkin(self._ids[row], field_map[field], new_value.strip())
        if not res.get("ok"):
            QMessageBox.warning(self, "修改", res.get("message", "修改失败"))
        elif res.get("excel_msg"):
            QMessageBox.information(self, "修改", f"已更新（{res['excel_msg']}）")
        self.refresh()

    def _export(self) -> None:
        session = self.service.current_session()
        if not session:
            return
        default = str(Path.cwd() / f"{session.name or '点名'}_{session.date or ''}.xlsx")
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
        stations = self.service.search_stations(kw or "") if kw else self.service.all_callsigns()[:200]
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

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
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
        paths, _ = QFileDialog.getOpenFileNames(self, "选择历史 Excel", "", "Excel (*.xlsx *.xls)")
        if not paths:
            return
        res = self.service.import_excel_files(paths)
        for p, (imp, skip, msg) in res.items():
            self._log(f"{Path(p).name}：{msg}")
        self.refresh()

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder:
            return
        res = self.service.import_excel_folder(folder)
        for p, (imp, skip, msg) in res.items():
            self._log(f"{Path(p).name}：{msg}")
        self.refresh()

    def _sync(self) -> None:
        self._sync_threaded()

    def _sync_threaded(self) -> None:
        self._sync_worker = _SyncWorker(self.service)
        self._sync_worker.finished.connect(self._sync_done)
        self._sync_worker.message.connect(self._log)
        self.status_lbl.setText("365dt 同步中…")
        self._sync_worker.start()

    def _sync_done(self, result: dict) -> None:
        if result.get("ok"):
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
        lay.addWidget(QLabel("从导入历史推导的常用缩写建议："))
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


class _SyncWorker(QThread):
    message = Signal(str)
    done = Signal(dict)

    def __init__(self, service: AppService) -> None:
        super().__init__()
        self.service = service

    def run(self) -> None:
        def progress(done, total, msg):
            self.message.emit(f"  {msg}")
        result = self.service.sync_365dt(progress)
        self.done.emit(result)


# --------------------------------------------------------------------------
class SettingsPage(QWidget):
    """设置：常规 / Excel / 365dt / 阈值 / 词典管理。"""

    def __init__(self, service: AppService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.s = service.settings
        tabs = QTabWidget()
        tabs.addTab(self._build_general(), "常规")
        tabs.addTab(self._build_excel(), "Excel")
        tabs.addTab(self._build_sync(), "365dt / 监听")
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
        self.sp_backup = QSpinBox(); self.sp_backup.setRange(1, 90); self.sp_backup.setValue(int(self.s.get("backup_keep", 30)))
        f.addRow("默认省份", self.ed_default_province)
        f.addRow("默认中继名称", self.ed_default_repeater)
        f.addRow("默认主控呼号", self.ed_default_operator)
        f.addRow("全局快捷键", self.ed_hotkey)
        f.addRow("备份保留份数", self.sp_backup)
        self.lbl_db = QLabel(str(self.s.db_path))
        f.addRow("数据库文件", self.lbl_db)
        return w

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
        self.cb_auto_save = QCheckBox("提交时自动保存 Excel")
        self.cb_auto_save.setChecked(bool(self.s.get("excel_auto_save", True)))
        f.addRow("", self.cb_auto_save)
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
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "点名模板.xlsx", "Excel (*.xlsx)")
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
        return w

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
        self.s.set_many(
            default_province=self.ed_default_province.text().strip() or "江苏",
            default_repeater_name=self.ed_default_repeater.text().strip(),
            default_operator_callsign=self.ed_default_operator.text().strip(),
            global_hotkey=self.ed_hotkey.text().strip() or "Ctrl+Space",
            backup_keep=self.sp_backup.value(),
            excel_template=self.ed_excel_path.text().strip(),
            excel_sheet_name=self.ed_excel_sheet.text().strip(),
            excel_auto_save=self.cb_auto_save.isChecked(),
            dt365_uid=self.ed_uid.text().strip(),
            dt365_max_fetch=self.sp_fetch.value(),
            fuzzy_high=float(self.sp_high.value()),
            fuzzy_mid=float(self.sp_mid.value()),
        )
        # 省份改变时重建区划索引
        self.service.rebuild_region()
        QMessageBox.information(self, "设置", "已保存（部分设置重启后完全生效）")
