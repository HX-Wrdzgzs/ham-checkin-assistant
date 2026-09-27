"""统一后台任务生命周期（P1-3）。

管理 startup 365dt / manual 365dt / 未来 import / NRL worker。
- 现场同步、导入、Excel 写入之间只允许一个任务；独立的工信部型号库
  worker 可以与现场任务并行。
- 退出顺序：stop accepting → request cancel → wait workers → worker 关闭自己的 DB。

每个 worker 使用独立 SQLite connection（P1-2），绝不共享主连接。
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QThread, Signal

from database.db import connect
from database.repository import Repository
from database.qth_places import QthPlaceCatalog
from database.seed import seed_default_aliases
from excel.controller import ExcelController
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from providers.excel_import import ExcelImportProvider
from services.standalone import build_standalone_sync
from services.standardizer import Standardizer
from services.miit_catalog_service import MiitCatalogSyncService
from services.qth_place_sync_service import QthPlaceSyncService


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


class QthPlaceImportWorker(QThread):
    """地点包导入 worker；大 JSONL/CSV 不应冻结设置页或快速点名。"""

    done = Signal(dict)

    def __init__(self, settings, path) -> None:
        super().__init__()
        self.settings = settings
        self.path = str(path)

    def run(self) -> None:
        catalog = None
        try:
            catalog = QthPlaceCatalog(self.settings.qth_place_catalog_path)
            count = catalog.import_file(self.path)
            self.done.emit({"ok": True, "count": count, "status": catalog.status()})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"ok": False, "message": f"地点包导入异常：{exc}"})
        finally:
            if catalog is not None:
                try:
                    catalog.close()
                except Exception:  # noqa: BLE001
                    pass


class QthPlaceSyncWorker(QThread):
    """QTH 地点库后台同步；不占用主线程或主 SQLite 连接。"""

    progress = Signal(dict)
    done = Signal(dict)

    def __init__(self, settings, queries=None) -> None:
        super().__init__()
        self.settings = settings
        self.queries = list(queries or [])
        self.cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.requestInterruption()

    def run(self) -> None:
        catalog = None
        try:
            catalog = QthPlaceCatalog(self.settings.qth_place_catalog_path)
            service = QthPlaceSyncService(
                catalog,
                default_province=str(
                    self.settings.get("default_province", "江苏") or "江苏"
                ),
            )
            result = service.sync(
                remote_url=str(self.settings.get("qth_place_pack_url", "") or ""),
                tianditu_token=str(
                    self.settings.get("qth_tianditu_token", "") or ""
                ),
                queries=self.queries,
                stop_event=self.cancel_event,
                max_online_queries=int(
                    self.settings.get("qth_online_query_limit", 5) or 0
                ),
                progress=self.progress.emit,
            )
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.done.emit({
                "ok": False,
                "status": "failed",
                "message": f"QTH 地点库同步异常：{exc}",
            })
        finally:
            if catalog is not None:
                try:
                    catalog.close()
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


class MiitCatalogWorker(QThread):
    """工信部电台型号库同步：顺序网络请求，独立资料库连接。"""

    progress = Signal(dict)
    done = Signal(dict)

    def __init__(self, settings, *, full: bool = True, resume: bool = True) -> None:
        super().__init__()
        self.settings = settings
        self.full = bool(full)
        self.resume = bool(resume)
        self.cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.requestInterruption()

    def run(self) -> None:
        svc = None
        try:
            svc = MiitCatalogSyncService(
                self.settings.miit_catalog_path,
            )
            result = svc.sync(
                full=self.full,
                resume=self.resume,
                page_size=int(self.settings.get("miit_catalog_page_size", 1000)),
                stop_event=self.cancel_event,
                progress=self.progress.emit,
            )
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"ok": False, "status": "failed", "message": f"型号库同步异常：{exc}"})
        finally:
            if svc is not None:
                try:
                    svc.catalog.close()
                except Exception:  # noqa: BLE001
                    pass
                provider = getattr(svc, "provider", None)
                close_provider = getattr(provider, "close", None)
                if callable(close_provider):
                    try:
                        close_provider()
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

    def _batch_failure(self, message: str, state: str = "error") -> dict:
        return {
            "batch": True,
            "batch_id": self.task.get("batch_id", ""),
            "binding_id": self.task.get("binding_id", ""),
            "ok": False,
            "message": message,
            "items": [
                {
                    "checkin_id": item.get("checkin_id"),
                    "row": item.get("row"),
                    "ok": False,
                    "state": state,
                    "message": message,
                }
                for item in (self.task.get("items") or [])
            ],
        }

    def _run_batch(self, controller: ExcelController) -> dict:
        """同一工作簿内逐行校验、更新，最后只 Save 一次。"""
        item_results: list[dict] = []
        writable_results: list[dict] = []
        for item in self.task.get("items") or []:
            result = {
                "checkin_id": item.get("checkin_id"),
                "row": item.get("row"),
                "ok": False,
                "state": "error",
                "message": "",
            }
            row = item.get("row")
            sequence = item.get("sequence")
            callsign = str(item.get("callsign") or "")
            if not row or not controller.verify_row_identity(row, sequence, callsign):
                row = controller.find_row(sequence, callsign)
            if row is None:
                result.update(
                    state="conflict",
                    message="Excel 行身份冲突，已跳过该行",
                )
                item_results.append(result)
                continue
            updates = item.get("updates")
            if not isinstance(updates, dict) or not updates:
                result.update(message="补全任务没有可写入字段")
                item_results.append(result)
                continue
            ok, msg = controller.update_row(int(row), updates, auto_save=False)
            result.update(row=int(row), ok=ok, state="written" if ok else "error", message=msg)
            item_results.append(result)
            if ok:
                writable_results.append(result)

        if writable_results:
            saved, save_msg = controller.save()
            for result in writable_results:
                if saved:
                    result.update(ok=True, state="persisted", message=save_msg)
                else:
                    result.update(ok=False, state="error", message=save_msg)
        ok_count = sum(1 for item in item_results if item.get("ok"))
        return {
            "batch": True,
            "batch_id": self.task.get("batch_id", ""),
            "binding_id": self.task.get("binding_id", ""),
            "ok": bool(item_results) and ok_count == len(item_results),
            "message": f"Excel 批量处理 {len(item_results)} 条，成功 {ok_count} 条",
            "items": item_results,
        }

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
                if self.task.get("batch"):
                    result = self._batch_failure(f"Excel COM 初始化失败：{e}")
                else:
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
                if self.task.get("batch"):
                    result = self._batch_failure(msg)
                else:
                    result.update(ok=False, state="error", message=msg)
                self.done.emit(result)
                return

            if self.task.get("batch"):
                self.done.emit(self._run_batch(controller))
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
            if self.task.get("batch"):
                result = self._batch_failure(f"Excel 后台批量更新异常：{e}")
            else:
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
        # 工信部完整扫描使用独立资料库连接，允许它与现场 SQLite/Excel
        # worker 并行，避免 20 万级分页阻塞保存或补同步。
        self._miit_current: MiitCatalogWorker | None = None
        # QTH 同步只写独立地点库；和地点包导入共用一把闸门，避免两个
        # 线程同时替换 QTH FTS 索引。
        self._qth_current: QthPlaceSyncWorker | None = None
        self._accepting = True

    def busy(self) -> bool:
        """是否有任意后台任务；供自动检查判断是否处于空闲状态。"""
        return self._general_busy() or (
            (self._miit_current is not None and self._miit_current.isRunning())
            or (self._qth_current is not None and self._qth_current.isRunning())
        )

    def _general_busy(self) -> bool:
        """现场同步/导入/Excel 写入之间仍保持单任务闸门。"""
        return self._current is not None and self._current.isRunning()

    def qth_busy(self) -> bool:
        """地点库是否已有同步/导入；地点库与现场任务使用不同文件。"""
        return self._qth_current is not None and self._qth_current.isRunning()

    def submit_sync(self, done_cb, message_cb=None) -> bool:
        """提交一个 365dt 同步任务。已有任务时拒绝（任务书第二阶段 #21）。"""
        if not self._accepting or self._general_busy():
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
        if not self._accepting or self._general_busy():
            return False
        w = ImportWorker(self.settings, paths, folder=folder)
        w.done.connect(done_cb)
        if message_cb is not None:
            w.message.connect(message_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._current = w
        w.start()
        return True

    def submit_qth_place_import(self, path, done_cb) -> bool:
        """后台导入道路/地标地点包；可与 Excel/365dt 并行，和 QTH 同步互斥。"""
        if not self._accepting or self.qth_busy():
            return False
        w = QthPlaceImportWorker(self.settings, path)
        w.done.connect(done_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._qth_current = w
        w.start()
        return True

    def submit_qth_place_sync(self, queries, done_cb, progress_cb=None) -> bool:
        """提交 QTH 同步；可与现场任务并行，但不和地点包导入同时写库。"""
        if not self._accepting or self.qth_busy():
            return False
        w = QthPlaceSyncWorker(self.settings, queries=queries)
        w.done.connect(done_cb)
        if progress_cb is not None:
            w.progress.connect(progress_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._qth_current = w
        w.start()
        return True

    def cancel_qth_place_sync(self) -> bool:
        """只取消 QTH 同步，不中断正在进行的 Excel/365dt 任务。"""
        worker = self._qth_current
        if not isinstance(worker, QthPlaceSyncWorker) or not worker.isRunning():
            return False
        worker.request_cancel()
        return True

    def submit_excel_update(self, task: dict, done_cb) -> bool:
        """后台修改 Excel 单行；主线程只负责接收结果并更新 SQLite 状态。"""
        if not self._accepting or self._general_busy():
            return False
        w = ExcelUpdateWorker(task)
        w.done.connect(done_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._current = w
        w.start()
        return True

    def submit_miit_catalog(self, *, full: bool, resume: bool = True,
                            done_cb, progress_cb=None) -> bool:
        """提交工信部电台库同步；它可与现场 Excel/SQLite worker 并行。"""
        if (not self._accepting or
                (self._miit_current is not None and self._miit_current.isRunning())):
            return False
        w = MiitCatalogWorker(self.settings, full=full, resume=resume)
        w.done.connect(done_cb)
        if progress_cb is not None:
            w.progress.connect(progress_cb)
        w.finished.connect(lambda: self._on_finished(w))
        self._miit_current = w
        w.start()
        return True

    def cancel_current(self) -> bool:
        worker = self._current
        if worker is None or not worker.isRunning():
            return False
        cancel = getattr(worker, "request_cancel", None)
        if callable(cancel):
            cancel()
        else:
            worker.requestInterruption()
        return True

    def cancel_miit_catalog(self) -> bool:
        """仅允许取消型号库 worker，不误伤正在运行的 Excel/365dt 任务。"""
        worker = self._miit_current
        if not isinstance(worker, MiitCatalogWorker) or not worker.isRunning():
            return False
        worker.request_cancel()
        return True

    def _on_finished(self, worker: QThread) -> None:
        if self._current is worker:
            self._current = None
        if self._miit_current is worker:
            self._miit_current = None
        if self._qth_current is worker:
            self._qth_current = None

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """stop accepting → request cancel → wait workers → worker 自行关闭 DB。"""
        self._accepting = False
        workers = [worker for worker in (self._current, self._miit_current, self._qth_current)
                   if worker is not None]
        for w in workers:
            if not w.isRunning():
                continue
            cancel = getattr(w, "request_cancel", None)
            if callable(cancel):
                cancel()
            else:
                w.requestInterruption()
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        for w in workers:
            if not w.isRunning():
                continue
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            w.wait(remaining)
        self._current = None
        self._miit_current = None
        self._qth_current = None
