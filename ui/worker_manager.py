"""统一后台任务生命周期（P1-3）。

管理 startup 365dt / manual 365dt / 未来 import / NRL worker。
- 同一时间只允许一个任务。
- 退出顺序：stop accepting → request cancel → wait workers → worker 关闭自己的 DB。

每个 worker 使用独立 SQLite connection（P1-2），绝不共享主连接。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from database.db import connect
from database.repository import Repository
from database.seed import seed_default_aliases
from excel.controller import ExcelController
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from providers.excel_import import ExcelImportProvider
from services.standalone import build_standalone_sync
from services.standardizer import Standardizer


class ImportWorker(QThread):
    """Excel 历史导入 worker（P2：大文件导入不阻塞 UI，独立连接）。"""

    message = Signal(str)
    done = Signal(dict)

    def __init__(self, settings, paths, folder: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.paths = paths
        self.folder = folder

    def run(self) -> None:
        conn = None
        try:
            conn = connect(self.settings.db_path)
            repo = Repository(conn)
            seed_default_aliases(repo)
            store = AliasStore(repo)
            region = RegionIndex(self.settings.get("default_province", "江苏"))
            std = Standardizer(store, region)
            provider = ExcelImportProvider(repo)
            if self.folder:
                res = provider.import_folder(self.paths, std)
            else:
                res = provider.import_files(self.paths, std)
            for p, (imp, skip, msg) in res.items():
                self.message.emit(f"{p}：{msg}")
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.done.emit({"__error__": f"导入异常：{e}"})
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass


class SyncWorker(QThread):
    """365dt 同步 worker：独立连接，run() 总异常保护。"""

    message = Signal(str)
    done = Signal(dict)

    def __init__(self, settings) -> None:
        super().__init__()
        self.settings = settings

    def run(self) -> None:
        svc = None
        conn = None
        try:
            svc, conn = build_standalone_sync(self.settings)
            self.settings = None  # 释放引用

            def progress(done, total, msg):
                self.message.emit(f"  {msg}")

            result = svc.sync_once(progress)
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            # 总异常保护：UI 永远能收到 done（任务书第二阶段 #23）
            self.done.emit({"ok": False, "message": f"同步异常：{e}"})
        finally:
            if conn is not None:
                try:
                    conn.close()  # worker 关闭自己的 DB（P1-2）
                except Exception:  # noqa: BLE001
                    pass


class ExcelUpdateWorker(QThread):
    """后台执行一次 Excel 单行修改及 Save，避免 COM 阻塞 Qt 主线程。

    每个 worker 自己初始化 COM 并创建 ExcelController，不复用主线程的
    COM proxy；这样 Excel 保存慢时只会让该 worker 等待，窗口仍可响应。
    """

    done = Signal(dict)

    def __init__(self, task: dict) -> None:
        super().__init__()
        self.task = dict(task)

    def run(self) -> None:
        controller = None
        pythoncom = None
        com_initialized = False
        result = {
            "checkin_id": self.task.get("checkin_id"),
            "binding_id": self.task.get("binding_id", ""),
            "row": self.task.get("row"),
        }
        try:
            try:
                import pythoncom

                pythoncom.CoInitialize()
                com_initialized = True
            except Exception as e:  # noqa: BLE001
                result.update(ok=False, state="error", message=f"Excel COM 初始化失败：{e}")
                self.done.emit(result)
                return

            controller = ExcelController()
            ok, msg = controller.connect(
                str(self.task.get("excel_path") or ""),
                str(self.task.get("sheet_name") or ""),
                auto_detect_sheet=False,
            )
            if not ok:
                result.update(ok=False, state="error", message=msg)
                self.done.emit(result)
                return

            row = self.task.get("row")
            sequence = self.task.get("sequence")
            callsign = str(self.task.get("callsign") or "")
            if not row or not controller.verify_row_identity(row, sequence, callsign):
                row = controller.find_row(sequence, callsign)
            if row is None:
                result.update(
                    ok=False,
                    state="conflict",
                    message="Excel 行身份冲突，已标记，未修改",
                )
                self.done.emit(result)
                return

            updates = self.task.get("updates")
            if not isinstance(updates, dict) or not updates:
                # 兼容旧版本/旧任务快照，仍支持单字段任务。
                updates = {
                    str(self.task.get("excel_field")): self.task.get("new_value", "")
                }
            ok, msg = controller.update_row(int(row), updates, auto_save=True)
            result.update(
                ok=ok,
                state="persisted" if ok else "error",
                message=msg,
                row=int(row),
            )
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            result.update(ok=False, state="error", message=f"Excel 后台更新异常：{e}")
            self.done.emit(result)
        finally:
            if controller is not None:
                try:
                    controller.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            if com_initialized and pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass


class WorkerManager(QObject):
    """后台任务管理器：同一时间一个任务，退出时有序停止。"""

    def __init__(self, settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._current: QThread | None = None
        self._accepting = True

    def busy(self) -> bool:
        return self._current is not None and self._current.isRunning()

    def submit_sync(self, done_cb, message_cb=None) -> bool:
        """提交一个 365dt 同步任务。已有任务时拒绝（任务书第二阶段 #21）。"""
        if not self._accepting or self.busy():
            return False
        w = SyncWorker(self.settings)
        w.done.connect(done_cb)
        if message_cb is not None:
            w.message.connect(message_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._current = w
        w.start()
        return True

    def submit_import(self, paths, done_cb, message_cb=None, folder: bool = False) -> bool:
        """提交 Excel 导入任务（P2：独立连接 worker，不阻塞 UI）。"""
        if not self._accepting or self.busy():
            return False
        w = ImportWorker(self.settings, paths, folder=folder)
        w.done.connect(done_cb)
        if message_cb is not None:
            w.message.connect(message_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._current = w
        w.start()
        return True

    def submit_excel_update(self, task: dict, done_cb) -> bool:
        """后台修改 Excel 单行；主线程只负责接收结果并更新 SQLite 状态。"""
        if not self._accepting or self.busy():
            return False
        w = ExcelUpdateWorker(task)
        w.done.connect(done_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._current = w
        w.start()
        return True

    def _on_finished(self, worker: QThread) -> None:
        if self._current is worker:
            self._current = None

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """stop accepting → request cancel → wait workers → worker 自行关闭 DB。"""
        self._accepting = False
        w = self._current
        if w is not None and w.isRunning():
            w.requestInterruption()
            w.wait(timeout_ms)
        self._current = None
