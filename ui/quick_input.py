"""快速录入面板：输入 → 解析预览 → 提交/接受历史/清空/撤销。

快捷键：
Enter 提交；Tab 接受历史；Esc 清空；Ctrl+Shift+Z 撤销上一条。
输入补全：输入中会弹出轻量候选（↑↓ 选择，Enter/Tab 接受）。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel, QLineEdit, QListWidget, QVBoxLayout, QWidget,
)

from config.settings import normalize_quick_submit_key
from database.models import ParseResult
from services.app_service import AppService
from ui.source_labels import source_label


class _InputEdit(QLineEdit):
    submit_pressed = Signal()
    tab_pressed = Signal()
    esc_pressed = Signal()
    undo_pressed = Signal()
    down_pressed = Signal()
    up_pressed = Signal()
    completion_accept = Signal()
    completion_dismiss = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._popup = None
        # 用户是否已主动用 ↑/↓ 选择候选：只有进入选择态，Enter 才确认候选；
        # 否则 Enter 始终正常提交，绝不因补全弹窗被劫持（如输入 ba4rll）。
        self._completion_navigated = False
        self._submit_key = "Enter"
        self._space_submit_allowed = None

    def set_submit_key(self, value: str) -> None:
        self._submit_key = normalize_quick_submit_key(value)

    @staticmethod
    def _event_modifiers(event):
        mask = (Qt.KeyboardModifier.ControlModifier |
                Qt.KeyboardModifier.ShiftModifier |
                Qt.KeyboardModifier.AltModifier |
                Qt.KeyboardModifier.MetaModifier)
        return event.modifiers() & mask

    def _matches_submit_key(self, event) -> bool:
        key = event.key()
        mods = self._event_modifiers(event)
        wanted = self._submit_key
        if wanted == "Enter":
            return key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not mods
        if wanted == "Ctrl+Enter":
            return (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and mods == Qt.KeyboardModifier.ControlModifier)
        if wanted == "Shift+Enter":
            return (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and mods == Qt.KeyboardModifier.ShiftModifier)
        if wanted == "Alt+Enter":
            return (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and mods == Qt.KeyboardModifier.AltModifier)
        if wanted == "Space":
            return key == Qt.Key.Key_Space and not mods
        if wanted.startswith("F") and wanted[1:].isdigit() and not mods:
            return key == getattr(Qt.Key, f"Key_{wanted}")
        return False

    def _popup_visible(self) -> bool:
        return self._popup is not None and self._popup.isVisible()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        # Enter 在补全“选择态”下仍用于确认候选；否则只在配置命中时提交。
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._popup_visible() and self._completion_navigated:
                self.completion_accept.emit()
                event.accept()
                return
            # Space 模式保留 Ctrl+Enter 作为完整字段的安全提交方式。
            if (self._submit_key == "Space"
                    and self._event_modifiers(event) == Qt.KeyboardModifier.ControlModifier):
                self.submit_pressed.emit()
                event.accept()
                return
            if self._matches_submit_key(event):
                self.submit_pressed.emit()
                event.accept()
                return
            # 未配置为提交键的 Enter 不再推进下一位。
            event.accept()
            return
        if key == Qt.Key.Key_Space and self._matches_submit_key(event):
            allowed = self._space_submit_allowed
            if allowed is None or allowed():
                self.submit_pressed.emit()
                event.accept()
                return
            # 当前不是“单呼号快速提交”状态时，空格仍作为正常字段分隔符。
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if self._popup_visible():
                self.completion_accept.emit()
                event.accept()
                return
            self.tab_pressed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            if self._popup_visible():
                self.completion_dismiss.emit()
                event.accept()
                return
            self.esc_pressed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self.down_pressed.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.up_pressed.emit()
            event.accept()
            return
        # Ctrl+Z 必须保留 QLineEdit 自己的文字撤销能力；此前这里把它
        # 劫持成“撤销上一条”，用户整理输入时连续按 Ctrl+Z 会误删多条记录。
        # 记录级撤销改为不与文本编辑冲突的 Ctrl+Shift+Z。
        if (key == Qt.Key.Key_Z
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.undo_pressed.emit()
            event.accept()
            return
        if self._matches_submit_key(event):
            self.submit_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class QuickInputPanel(QWidget):
    submitted = Signal(object)   # ParseResult

    def __init__(self, service: AppService, parent=None, compact: bool = False) -> None:
        super().__init__(parent)
        self.service = service
        self._result: ParseResult | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._do_parse)

        # 轻量候选弹出框（输入自动补全）—— 先建好再连接信号
        # 用 ToolTip 而非 Popup：Popup 窗口显示时会抓取鼠标+键盘，导致用户
        # 无法继续输入 ba4rll、回车也被弹窗吃掉（2026-08-14 实测根因）。
        # ToolTip 不抢焦点/键盘，输入框始终接收按键。
        self.popup = QListWidget(self)
        self.popup.setWindowFlags(Qt.WindowType.ToolTip |
                                  Qt.WindowType.FramelessWindowHint)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.popup.setMaximumHeight(220)
        self.popup.itemClicked.connect(lambda *_: self._accept_completion())
        self.popup.hide()
        self._completion_items: list[tuple[str, str]] = []
        self._completion_token = ""

        self.input = _InputEdit()
        self.input.setPlaceholderText("输入：呼号 QTH 设备 天线 功率（可乱序）")
        self.input._popup = self.popup
        self.input.set_submit_key(str(service.settings.get("quick_submit_key", "Enter")))
        self.input._space_submit_allowed = self._space_submit_allowed
        self.input.textChanged.connect(self._schedule_parse)
        self.input.submit_pressed.connect(self._submit)
        self.input.tab_pressed.connect(self._accept_history)
        self.input.esc_pressed.connect(self._clear)
        self.input.undo_pressed.connect(self._undo)
        self.input.down_pressed.connect(self._popup_down)
        self.input.up_pressed.connect(self._popup_up)
        self.input.completion_accept.connect(self._accept_completion)
        self.input.completion_dismiss.connect(self.popup.hide)

        self.callsign_lbl = QLabel("")
        self.callsign_lbl.setStyleSheet("font-size:20px; font-weight:bold; color:#1565C0;")
        self.detail_lbl = QLabel("")
        self.detail_lbl.setWordWrap(True)
        self.history_lbl = QLabel("")
        self.history_lbl.setStyleSheet("color:#4E5D6C;")
        self.dup_lbl = QLabel("")
        self.dup_lbl.setStyleSheet("color:#C62828;")
        self.feedback_lbl = QLabel("")
        self.feedback_lbl.setStyleSheet("color:#2E7D32; font-weight:bold;")
        self.meta_lbl = QLabel("")
        self.meta_lbl.setStyleSheet("color:#78909C;")
        self.hint_lbl = QLabel("")
        self._refresh_hint()
        self.hint_lbl.setStyleSheet("color:#90A4AE; font-size:11px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.addWidget(self.input)
        lay.addWidget(self.callsign_lbl)
        lay.addWidget(self.detail_lbl)
        lay.addWidget(self.history_lbl)
        lay.addWidget(self.dup_lbl)
        lay.addWidget(self.feedback_lbl)
        lay.addWidget(self.meta_lbl)
        if not compact:
            lay.addWidget(self.hint_lbl)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.setInterval(6000)
        self._feedback_timer.timeout.connect(lambda: self.feedback_lbl.setText(""))

        self._refresh_meta()

    # ---------- 公共 ----------
    def focus_input(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def clear(self) -> None:
        self.input.clear()

    def apply_submit_key(self, value: str) -> None:
        """热更新快速点名写入 / 下一位按键。"""
        self.input.set_submit_key(value)
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        key = self.input._submit_key
        if key == "Space":
            submit_text = "Space 单呼号写入/下一位（Shift+Space 继续补字段，Ctrl+Enter 完整提交）"
        else:
            submit_text = f"{key} 写入/下一位"
        self.hint_lbl.setText(
            f"{submit_text}　Tab 接受历史　Esc 清空　Ctrl+Shift+Z 撤销上一条")

    def _space_submit_allowed(self) -> bool:
        text = self.input.text().strip()
        if not text or any(ch.isspace() for ch in text):
            return False
        result = self._result
        if result is None or result.raw_text != text:
            result = self.service.parse(text)
        return bool(result.callsign.value)

    def set_feedback(self, text: str, ok: bool = True) -> None:
        self.feedback_lbl.setText(text)
        self.feedback_lbl.setStyleSheet(
            "color:#2E7D32; font-weight:bold;" if ok else "color:#C62828; font-weight:bold;")
        self._feedback_timer.start()

    def _refresh_meta(self) -> None:
        session = self.service.current_session()
        seq = self.service.repo.next_sequence(session.id) if session else "-"
        now = datetime.now().strftime("%H:%M")
        self.meta_lbl.setText(f"# {seq}　　当前 {now}")

    # ---------- 解析 ----------
    def _schedule_parse(self) -> None:
        if getattr(self.service, "_closed", False):
            self._timer.stop()
            return
        self._refresh_meta()
        # 用户继续打字 = 离开“选择态”：Enter 恢复为提交，不再确认候选
        self.input._completion_navigated = False
        # 输入已成完整缩写时立即隐藏补全弹窗，避免回车被残留弹窗劫持
        last = self.input.text().rsplit(" ", 1)[-1].strip().lower()
        if last and self.service.token_is_complete(last):
            self._completion_token = ""
            self.popup.hide()
        self._timer.start()

    def _do_parse(self) -> None:
        if getattr(self.service, "_closed", False):
            self._timer.stop()
            self.popup.hide()
            return
        text = self.input.text()
        if not text.strip():
            self._result = None
            self.popup.hide()
            self._render_empty()
            return
        self._result = self.service.parse(text)
        self._render()
        self._update_completion()

    # ---------- 输入自动补全 ----------
    def _update_completion(self) -> None:
        text = self.input.text()
        last = text.rsplit(" ", 1)[-1].strip().lower()
        if not text.strip() or not last or len(last) < 2:
            self._completion_token = ""
            self.popup.hide()
            return
        if self.service.token_is_complete(last):
            self._completion_token = ""
            self.popup.hide()
            return
        if " " not in text:
            # 首词通常是呼号：只做呼号补全（来自历史站库），如 rll → BA4RLL
            items = self.service.complete_callsign(last)
        else:
            items = self.service.complete(last)
        # 防抖/防闪烁：token 未变化且弹窗已显示 → 不动
        if getattr(self, "_completion_token", "") == last and self.popup.isVisible():
            return
        self._completion_token = last
        if not items:
            self.popup.hide()
            return
        self._completion_items = items
        self.popup.clear()
        for label, _ in items:
            self.popup.addItem(label)
        geo = self.input.geometry()
        self.popup.setMinimumWidth(geo.width())
        self.popup.move(self.input.mapToGlobal(geo.bottomLeft()))
        self.popup.setCurrentRow(0)
        if not self.popup.isVisible():
            self.popup.show()
        # 弹窗显示后强制输入框保持焦点：继续打字 ba4rll 不会被弹窗拦截
        self.input.setFocus()

    def _popup_down(self) -> None:
        if not self.popup.isVisible():
            return
        self.input._completion_navigated = True  # 进入选择态：Enter 将确认候选
        r = self.popup.currentRow() + 1
        if r >= self.popup.count():
            r = 0
        self.popup.setCurrentRow(r)

    def _popup_up(self) -> None:
        if not self.popup.isVisible():
            return
        self.input._completion_navigated = True  # 进入选择态：Enter 将确认候选
        r = self.popup.currentRow() - 1
        if r < 0:
            r = self.popup.count() - 1
        self.popup.setCurrentRow(r)

    def _accept_completion(self) -> None:
        if not self.popup.isVisible() or not self._completion_items:
            return
        row = self.popup.currentRow()
        if row < 0:
            row = 0
        if row >= len(self._completion_items):
            return
        value = self._completion_items[row][1]
        text = self.input.text()
        head, _, _ = text.rpartition(" ")
        self.input.setText(f"{head} {value} " if head else f"{value} ")
        self.popup.hide()

    def _render_empty(self) -> None:
        self.callsign_lbl.setText("")
        self.detail_lbl.setText("")
        self.history_lbl.setText("")
        self.dup_lbl.setText("")

    def _render(self) -> None:
        r = self._result
        if r is None:
            return
        fields = r.fields()

        # 呼号行
        cs_parts = []
        if r.callsign.value:
            cs_parts.append(r.callsign.value)
            if r.callsign.candidates:
                cs_parts.append(f"（{r.callsign.candidates[0]}）")
        self.callsign_lbl.setText(" ".join(cs_parts))

        # 明细行
        parts = []
        for key in ("qth", "device", "antenna", "power"):
            f = fields[key]
            if f.value:
                parts.append(f"{f.value} [{source_label(f.source)}]")
            elif f.candidates:
                parts.append(f"{' / '.join(f.candidates[:2])} [候选]")
        # P2：明确显示未匹配 token，提示用户无法解析的内容
        if r.unmatched:
            parts.append(f"未识别：{' '.join(r.unmatched)}")
        self.detail_lbl.setText("　|　".join(parts))

        # 历史建议（P0-4：次数 + 最近 / 常用）
        hist_lines = []
        if r.callsign.value and r.history:
            count = 0
            st = self.service.repo.get_station(r.callsign.value)
            if st:
                count = st.get("checkin_count", 0)
            recent = [info["recent"] for info in r.history.values() if info.get("recent")]
            freq = [info["frequent"] for info in r.history.values()
                    if info.get("frequent") and info["frequent"] != info["recent"]]
            if count:
                hist_lines.append(f"历史：{count}次")
            if recent:
                hist_lines.append("最近：" + " / ".join(recent))
            if freq:
                hist_lines.append("常用：" + " / ".join(freq))
        self.history_lbl.setText("　".join(hist_lines))

        # 重复提示
        if r.callsign.value:
            session = self.service.current_session()
            dup = None
            if session:
                dup = self.service.repo.duplicate_in_session(session.id, r.callsign.value)
            if dup:
                t = dup.checkin_time
                if len(t) >= 16:
                    t = t[11:16]
                self.dup_lbl.setText(
                    f"本场已签到　上次 {t}　{dup.qth_standard or ''}　"
                    f"{dup.device_standard or ''}　{dup.power_standard or ''}")
            else:
                self.dup_lbl.setText("")
        else:
            self.dup_lbl.setText("")

    # ---------- 动作 ----------
    def _submit(self) -> None:
        self.popup.hide()  # 回车即提交，绝不被弹窗拦截
        text = self.input.text()
        if not text.strip():
            return
        # 回车时立即解析当前文本，避免防抖定时器未触发导致“没记录”
        if self._result is None or self._result.raw_text != text:
            self._result = self.service.parse(text)
            self._render()
        if self._result and self._result.callsign.value:
            result = self._result
            # 先清空并保持焦点，再通知业务层提交。Excel/数据库即使暂时较慢，
            # 录入框也立即进入“下一位”状态，不让操作员看见旧呼号。
            self._clear()
            self.submitted.emit(result)
        else:
            self.set_feedback("缺少呼号，无法提交", ok=False)

    def _accept_history(self) -> None:
        if not self._result:
            return
        # Tab：把历史建议合入字段（显式接受）后，才能随 Enter 提交（任务书第二阶段 #1/#2）
        self._result = self.service.accept_history(self._result)
        self._render()

    def _clear(self) -> None:
        self.input.clear()
        self._render_empty()

    undo_requested = Signal()

    def _undo(self) -> None:
        self._clear()
        self.undo_requested.emit()
