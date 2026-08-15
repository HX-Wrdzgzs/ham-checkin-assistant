"""回归测试：UI 冒烟（Release Gate：UI smoke PASS）。

offscreen 模式下实例化 MainWindow，验证选项卡齐全（含 NRL 监听页），
应用退出路径安全停止 monitor / worker / service。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestUiSmoke(unittest.TestCase):
    def test_mainwindow_instantiates_with_all_tabs(self):
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        from tests.helpers import make_service
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        # 冒烟不启动 365dt 同步线程，也不弹崩溃恢复对话框
        with mock.patch.object(MainWindow, "_startup_sync",
                               lambda self: None), \
             mock.patch.object(MainWindow, "_startup_after_recovery",
                               lambda self: None):
            w = MainWindow(svc)
        try:
            w.show()
            names = [w.tabs.tabText(i) for i in range(w.tabs.count())]
            for expected in ("快速点名", "本场记录", "呼号库", "历史数据", "NRL 监听", "设置"):
                self.assertIn(expected, names, f"缺少选项卡：{expected}")
        finally:
            # 应用退出路径：停 hotkey → monitor → worker shutdown → service close
            try:
                w.hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                w.monitor_page.monitor.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                w._workers.shutdown(timeout_ms=2000)
            except Exception:  # noqa: BLE001
                pass
            try:
                svc.close()
            except Exception:  # noqa: BLE001
                pass
            w.deleteLater()
            app.processEvents()

    def test_quick_commit_batches_excel_save_after_idle(self):
        """主窗口快速路径：连续提交只写内存，停手后定时器一次 Save。"""
        from unittest import mock
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from tests.helpers import make_service
        from tests.helpers.mock_excel import MockApp, install_mock_app, make_workbook
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        svc.create_session("快速保存", "2026-08-14")
        wb = make_workbook("C:/tmp/quick-save.xlsx")
        install_mock_app(svc.excel, MockApp([wb], wb))
        ok, msg = svc.excel_connect(str(wb.FullName), wb.Sheets("点名表").Name)
        self.assertTrue(ok, msg)
        with mock.patch.object(MainWindow, "_startup_sync", lambda self: None), \
             mock.patch.object(MainWindow, "_startup_after_recovery", lambda self: None):
            w = MainWindow(svc)
        try:
            w._on_submitted(svc.parse("bg4tki njqx k6 y 5"))
            w._on_submitted(svc.parse("ba4xxx njqx k6 y 5"))
            self.assertEqual(wb.save_count, 0)
            QTest.qWait(750)
            app.processEvents()
            self.assertEqual(wb.save_count, 1)
            rows = svc.repo.list_checkins(svc.current_session().id)
            self.assertEqual([c.excel_sync_status for c in rows], ["persisted", "persisted"])
        finally:
            try:
                w.hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                w.monitor_page.monitor.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                w._workers.shutdown(timeout_ms=2000)
            except Exception:  # noqa: BLE001
                pass
            try:
                svc.close()
            except Exception:  # noqa: BLE001
                pass
            w.deleteLater()
            app.processEvents()

    def test_monitor_page_readonly_no_db(self):
        """NRL 监听页只读：MonitorService 无 DB 依赖。"""
        from services.monitor_service import MonitorService

        m = MonitorService(url="")
        self.assertFalse(hasattr(m, "repo"))
        self.assertFalse(hasattr(m, "conn"))
        m.stop()

    def test_completion_enter_not_hijacked_by_default(self):
        """P2：补全弹窗不劫持 Enter——未主动选择时 Enter 提交；打字即离开选择态。

        用户输入 ba4rll 全程不被补全卡住；只有按过 ↑/↓ 才进入选择态。
        """
        from PySide6.QtWidgets import QApplication
        from tests.helpers import make_service
        from ui.quick_input import QuickInputPanel

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        panel = QuickInputPanel(svc)
        try:
            # 默认未进入选择态 → Enter 应走提交而非确认候选
            self.assertFalse(panel.input._completion_navigated,
                             "默认不得劫持 Enter")
            # 模拟先选择过 → 继续打字必须离开选择态（ba → ba4 后回车是提交）
            panel.input._completion_navigated = True
            panel.input.setText("ba4")
            app.processEvents()
            self.assertFalse(panel.input._completion_navigated,
                             "继续打字必须复位选择态，Enter 恢复为提交")
        finally:
            svc.close()
            panel.deleteLater()

    def test_ctrl_z_is_text_undo_and_ctrl_shift_z_is_record_undo(self):
        """整理输入时 Ctrl+Z 不得误触发业务撤销。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from tests.helpers import make_service
        from ui.quick_input import QuickInputPanel

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        panel = QuickInputPanel(svc)
        undo_events = []
        panel.input.undo_pressed.connect(lambda: undo_events.append(True))
        panel.show()
        try:
            panel.input.setFocus()
            QTest.keyClicks(panel.input, "abc")
            QTest.keyClick(panel.input, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            app.processEvents()
            self.assertEqual(undo_events, [], "Ctrl+Z 只能撤销输入文字")
            self.assertNotEqual(panel.input.text(), "abc",
                                "Ctrl+Z 应交给输入框文本撤销（Qt 可能按一次编辑批量撤销）")

            modifiers = (Qt.KeyboardModifier.ControlModifier |
                         Qt.KeyboardModifier.ShiftModifier)
            QTest.keyClick(panel.input, Qt.Key.Key_Z, modifiers)
            app.processEvents()
            self.assertEqual(len(undo_events), 1,
                             "只有 Ctrl+Shift+Z 才能触发记录级撤销")
        finally:
            svc.close()
            panel.deleteLater()

    def test_enter_clears_input_before_commit_callback(self):
        """Enter 后先进入下一位输入状态，业务提交回调不会阻塞清空动作。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from tests.helpers import make_service
        from ui.quick_input import QuickInputPanel

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        panel = QuickInputPanel(svc)
        panel.show()
        observed = []
        panel.submitted.connect(
            lambda result: observed.append((result.callsign.value, panel.input.text())))
        try:
            panel.input.setFocus()
            QTest.keyClicks(panel.input, "bg4tki njqx k6 y 5")
            QTest.keyClick(panel.input, Qt.Key.Key_Return)
            app.processEvents()
            self.assertEqual(observed, [("BG4TKI", "")])
            self.assertEqual(panel.input.text(), "")
        finally:
            svc.close()
            panel.deleteLater()

    def test_typing_not_blocked_by_popup_and_enter_confirms(self):
        """P2：弹窗显示后仍能继续打字（ba→4→rll 不被抢焦点）；↑↓+Enter 确认候选。"""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from database.models import Checkin
        from tests.helpers import make_service
        from ui.quick_input import QuickInputPanel

        app = QApplication.instance() or QApplication([])
        svc = make_service()
        # 造一个历史站库：BA4RLL，使 complete_callsign("ba") 有候选
        s = svc.create_session("t", "2026-08-08")
        svc.repo.add_checkin(Checkin(
            session_id=s.id, sequence_no=1, callsign="BA4RLL",
            qth_standard="南京栖霞", checkin_time="2026-08-08T20:00:00", source="local"))
        svc.repo.rebuild_station("BA4RLL")
        panel = QuickInputPanel(svc)
        panel.show()
        try:
            # 1) 输入 ba → 弹窗出现，但焦点/输入不被抢走
            QTest.keyClicks(panel.input, "ba")
            panel._do_parse()  # 直接触发补全（绕过 120ms 防抖定时器）
            self.assertTrue(panel.popup.isVisible(), "ba 应弹出呼号候选")
            # 2) 继续输入 4 → 必须能打进输入框（弹窗不抢键盘）
            QTest.keyClicks(panel.input, "4")
            self.assertEqual(panel.input.text(), "ba4", "弹窗不得拦截继续输入 4")
            # 3) 输入完整 rll → token 完整，弹窗自动隐藏，回车即提交
            QTest.keyClicks(panel.input, "rll")
            panel._do_parse()
            self.assertFalse(panel.popup.isVisible(), "完整呼号应隐藏弹窗")
            # 4) ↑/↓ 选择后 Enter 确认候选（输入前缀重新触发选择态）
            panel.input.clear()
            QTest.keyClicks(panel.input, "ba")
            panel._do_parse()
            self.assertTrue(panel.popup.isVisible())
            QTest.keyClick(panel.input, Qt.Key.Key_Down)   # 进入选择态
            QTest.keyClick(panel.input, Qt.Key.Key_Return)  # 确认候选
            self.assertTrue(panel.input.text().startswith("BA4RLL"),
                            f"选择后 Enter 应填入候选，实际={panel.input.text()!r}")
            self.assertFalse(panel.popup.isVisible(), "确认后弹窗应关闭")
        finally:
            svc.close()
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
