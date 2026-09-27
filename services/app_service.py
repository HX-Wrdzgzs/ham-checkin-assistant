"""主应用服务：UI 与数据层之间的唯一门面。

UI → AppService → Repository / Provider / ExcelController
SQLite 写入成功后才写 Excel；Excel 失败不影响 SQLite。
"""
from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from config.settings import CONFIG_PATH, Settings
from core.logging_setup import get_logger, setup_logging
from core.parser import Parser
from core.predictor import Predictor
from database.db import backup_daily, connect
from database.miit_catalog import MiitCatalogRepository
from database.qth_places import QthPlaceCatalog
from database.models import Checkin, ParseResult, Session
from database.repository import Repository
from database.seed import seed_default_aliases
from excel.controller import ExcelController
from excel.exporter import export_session as exporter_export, hhmm
from normalizers.dictionaries import AliasStore, norm_key
from normalizers.device_aliases import device_model_abbreviations
from normalizers.region_index import RegionIndex
from normalizers.regions import REGIONS
from providers.dt365 import Dt365Provider
from providers.excel_import import ExcelImportProvider
from providers.miit import model_abbreviations
from services.completion_service import CompletionEngine, full_qth_candidate
from services.miit_catalog_service import MiitCatalogSyncService
from services.qth_place_service import QthPlaceService
from services.standardizer import Standardizer
from services.sync_service import SyncService

app_log = get_logger("app")


def _norm(v) -> str:
    return str(v or "").strip()


def _remove_unmatched_value(unmatched: str, value: str) -> str:
    """从未识别 token 中消费一次已被人工归类的值。

    未识别内容由解析 token 以空格拼接保存，因此既要支持单 token，
    也要支持用户输入 ``海能达 pdc580`` 后形成的连续多 token 片段。
    只移除一次，重复出现的同名内容仍然保留，避免误删用户备注。
    """
    parts = str(unmatched or "").split()
    target = norm_key(value)
    if not parts or not target:
        return str(unmatched or "").strip()
    # 从长片段到短片段匹配，优先消费完整的中文品牌+型号组合。
    for width in range(len(parts), 0, -1):
        for start in range(0, len(parts) - width + 1):
            if norm_key("".join(parts[start:start + width])) != target:
                continue
            remaining = parts[:start] + parts[start + width:]
            return " ".join(remaining)
    return " ".join(parts)


def _remove_unmatched_span(unmatched: str, start, end) -> str:
    """按预览时记录的 token 区间消费未识别内容。

    处理重复 ``yz`` 时不能再次按字符串找“第一个 yz”，否则用户选择
    第二个 token 也会误删第一个。区间从原始快照计算，并由调用方按倒序
    消费，前面的 token 位置不会被后面的删除影响。
    """
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return str(unmatched or "").strip()
    parts = str(unmatched or "").split()
    if start < 0 or end <= start or end > len(parts):
        return str(unmatched or "").strip()
    return " ".join(parts[:start] + parts[end:])


def build_consistency_report(sqlite_checkins: list, excel_rows: list[dict]) -> tuple[bool, str]:
    """比对 SQLite 本场记录与 Excel 读回数据（任务书第一阶段 #14）。

    检测：DUPLICATE_SEQUENCE / INVALID_SEQUENCE / MISSING_IN_EXCEL /
    EXTRA_IN_EXCEL / FIELD_DIFF / IDENTITY_CONFLICT。
    excel_rows 由 controller.read_data() 提供，含内部空行与 _row 行号，
    空行后的数据也会被继续检查，不会被 dict 覆盖吞掉。
    """
    lines = [f"SQLite：{len(sqlite_checkins)} 条　Excel：{len(excel_rows)} 行"]
    diffs: list[str] = []
    excel_by_seq: dict[str, dict] = {}
    seen_seq: dict[str, int] = {}
    for row in excel_rows:
        s = _norm(row.get("sequence"))
        if not s:
            continue  # 空序列行：非数据行，跳过（但扫描不中断）
        seen_seq[s] = seen_seq.get(s, 0) + 1
        if s not in excel_by_seq:
            excel_by_seq[s] = row

    sqlite_seqs = {str(c.sequence_no) for c in sqlite_checkins}

    # 重复 / 非法序列（单独报告，禁止 dict 覆盖吞掉）
    for s, n in seen_seq.items():
        if n > 1:
            diffs.append(f"DUPLICATE_SEQUENCE #{s} 出现 {n} 次")
        if not s.isdigit() or int(s) <= 0:
            diffs.append(f"INVALID_SEQUENCE #{s}")

    for c in sqlite_checkins:
        key = str(c.sequence_no)
        ex = excel_by_seq.get(key)
        if ex is None:
            diffs.append(f"MISSING_IN_EXCEL #{c.sequence_no} {c.callsign}")
            continue
        if _norm(ex.get("callsign")).upper() != _norm(c.callsign).upper():
            diffs.append(f"IDENTITY_CONFLICT #{c.sequence_no} 呼号："
                         f"SQLite={c.callsign} Excel={ex.get('callsign')}")
            continue
        if _norm(ex.get("time")) != _norm(hhmm(c.checkin_time)):
            diffs.append(f"FIELD_DIFF #{c.sequence_no} TIME："
                         f"SQLite={hhmm(c.checkin_time)} Excel={ex.get('time')}")
        for field, attr in (("qth", "qth_standard"), ("device", "device_standard"),
                            ("antenna", "antenna_standard"), ("power", "power_standard"),
                            ("signal", "signal"), ("unmatched", "unmatched")):
            if _norm(ex.get(field)) != _norm(getattr(c, attr, "")):
                diffs.append(f"FIELD_DIFF #{c.sequence_no} {field.upper()}："
                             f"SQLite={getattr(c, attr, '')} Excel={ex.get(field)}")

    # Excel 多出的行（EXTRA_IN_EXCEL）
    for s in sorted(seen_seq, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0)):
        if s.isdigit() and int(s) > 0 and s not in sqlite_seqs:
            diffs.append(f"EXTRA_IN_EXCEL #{s}")

    if not diffs:
        return True, "\n".join(lines) + "\n\n结果：PASS"
    head = "\n".join(lines) + f"\n\n发现差异（{len(diffs)} 处）："
    return False, head + "\n" + "\n".join(diffs[:60])


class AppService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        configured_data_dir = str(settings.get("data_dir", "data") or "data").strip()
        default_data_dir = configured_data_dir.replace("/", "\\").lower() in {
            "data", ".\\data",
        }
        # 生产配置指向一个已经消失的自定义目录，或目录还在但数据库文件已丢失
        # 时，绝不能自动 mkdir/建库后打开空数据库。那会把“原数据库不可用”
        # 伪装成“没有历史记录”，造成更大的数据丢失风险。测试/临时 Settings
        # 仍允许按原逻辑创建隔离目录。
        is_runtime_config = (Path(settings.path).resolve().as_posix().lower()
                             == Path(CONFIG_PATH).resolve().as_posix().lower())
        if (is_runtime_config and not default_data_dir
                and (not settings.data_dir.exists() or not settings.db_path.exists())):
            raise RuntimeError(
                "配置的数据目录或数据库文件不存在，已停止启动以防创建空数据库："
                f"{settings.db_path}\n请先恢复原数据库/备份，或在配置中选择可靠的本地 data 目录。"
            )
        setup_logging(settings.logs_dir)
        if settings.migration_note:
            app_log.info("runtime migration: %s", settings.migration_note)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        backup_daily(settings.db_path, settings.backup_dir,
                     int(settings.get("backup_keep", 30)), config_path=settings.path)

        self.conn = connect(settings.db_path)
        self.repo = Repository(self.conn)
        # 工信部资料库是可选的独立快照：损坏/尚未下载时不能阻止本地点名。
        try:
            self.miit_catalog = MiitCatalogRepository(settings.miit_catalog_path)
        except Exception as exc:  # noqa: BLE001
            self.miit_catalog = None
            app_log.warning("MIIT catalog unavailable; local check-in remains usable: %s", exc)
        try:
            self.qth_place_catalog = QthPlaceCatalog(settings.qth_place_catalog_path)
            self.qth_place_service = QthPlaceService(self.qth_place_catalog)
        except Exception as exc:  # noqa: BLE001
            self.qth_place_catalog = None
            self.qth_place_service = None
            app_log.warning("QTH place catalog unavailable; admin QTH remains usable: %s", exc)
        seed_default_aliases(self.repo)
        self.store = AliasStore(self.repo)
        self.region = RegionIndex(settings.get("default_province", "江苏"))
        self.predictor = Predictor(self.repo)
        self.parser = Parser(
            self.store, self.region, self.predictor,
            fuzzy_high=float(settings.get("fuzzy_high", 92)),
            fuzzy_mid=float(settings.get("fuzzy_mid", 75)),
            fuzzy_margin=float(settings.get("fuzzy_margin", 5)),
            radio_catalog=self.miit_catalog,
            qth_places=self.qth_place_service,
        )
        # 预热解析缓存（模糊选项/频率），避免首键卡顿
        self.parser._qth_fuzzy_options()
        self._value_frequency()
        self.standardizer = Standardizer(self.store, self.region)
        self.completion_engine = CompletionEngine(
            self.repo, self.standardizer, self.region, catalog=self.miit_catalog,
            place_resolver=self.qth_place_service,
        )
        # 从已有签到/导入记录建立“观察缩写”索引。它不修改数据库，也不
        # 冒充工信部核准；只在一个缩写唯一指向一个已明确标准值时参与
        # 现场解析，冲突值会留给设置页人工确认。
        self._observed_device_evidence: dict[str, Counter[str]] = {}
        self._observed_device_aliases: dict[str, str] = {}
        self.refresh_observed_device_aliases()
        self.excel = ExcelController()
        self.excel_provider = ExcelImportProvider(self.repo)
        self.sync_service = SyncService(
            self.repo,
            Dt365Provider(settings.get("dt365_uid"), max_fetch=int(settings.get("dt365_max_fetch", 60))),
            self.standardizer,
        )
        self._current_session_id: int | None = None
        self._sync_in_progress = False
        self._closed = False
        # 正常退出写入 clean_shutdown；启动时立即消费标记，异常退出则保持 False，
        # 这样只有真正中断的本地 active 场次才会进入恢复提示。
        self._clean_shutdown = bool(settings.get("clean_shutdown", False))
        try:
            self._last_local_session_id = int(settings.get("last_local_session_id") or 0)
        except (TypeError, ValueError):
            self._last_local_session_id = 0
        if self._clean_shutdown:
            settings.set("clean_shutdown", False)
        app_log.info("AppService ready, db=%s", settings.db_path)

    # ---------- 场次 ----------
    def _next_session_number(self) -> int:
        """P2：自动场次名不依赖 list 长度——取已用「第N场点名」编号最大值 +1。
        即使有删除/手工命名/编号空洞也不会重名。"""
        import re
        n = 0
        for r in self.repo.as_dict_rows("SELECT name FROM sessions"):
            m = re.match(r"^第(\d+)场点名$", r["name"] or "")
            if m:
                n = max(n, int(m.group(1)))
        return n + 1

    def _apply_excel_binding(self, session: Session) -> None:
        """切换场次时应用该场次的 Excel 绑定：断开旧绑定 → 连接目标 → 校验表头。

        无绑定的场次保持未连接；A 场 Excel 绝不继承给 B 场（任务书第一阶段 #5）。
        """
        self.excel.disconnect()
        if not session.excel_path:
            return
        ok, msg = self.excel.connect(session.excel_path, session.excel_sheet_name)
        if not ok:
            app_log.warning("session #%d excel binding connect failed: %s", session.id, msg)

    def create_session(self, name: str = "", date: str = "",
                       excel_path: str = "", excel_sheet_name: str = "") -> Session:
        """新建场次。默认无 Excel 绑定（A 场 Excel 绝不继承给 B 场，任务书第一阶段 #5）。

        绑定只能通过显式 excel_connect() 写入当前场次。
        """
        session = self.repo.create_session(
            name=name or f"第{self._next_session_number()}场点名",
            date=date or datetime.now().strftime("%Y-%m-%d"),
            operator_callsign=self.settings.get("default_operator_callsign", ""),
            repeater_name=self.settings.get("default_repeater_name", ""),
            excel_path=excel_path,
            excel_sheet_name=excel_sheet_name,
        )
        self._current_session_id = session.id
        self._apply_excel_binding(session)
        return session

    def current_session(self) -> Session | None:
        if self._current_session_id is None:
            return None
        return self.repo.get_session(self._current_session_id)

    def set_current_session(self, session_id: int | None) -> bool:
        """设置当前场次。ended 场次拒绝（必须显式 reopen），返回是否成功。"""
        if session_id is None:
            self._current_session_id = None
            self.excel.disconnect()
            return True
        s = self.repo.get_session(session_id)
        if s is None:
            self._current_session_id = None
            self.excel.disconnect()
            return False
        if s.status == "ended":
            # ended 场次默认只读，禁止 set 后直接写（任务书第一阶段 #4）
            return False
        self._current_session_id = session_id
        self._apply_excel_binding(s)
        return True

    def reopen_session(self, session_id: int) -> bool:
        """显式重新打开已结束场次（恢复可写）。只有显式调用才允许。"""
        s = self.repo.get_session(session_id)
        if s is None or s.status != "ended":
            return False
        self.repo.update_session(session_id, status="active")
        self._current_session_id = session_id
        self._apply_excel_binding(s)
        app_log.info("reopened session #%d %s", session_id, s.name)
        return True

    def active_sessions(self) -> list[Session]:
        return self.repo.active_sessions(local_only=True)

    def startup_sessions(self) -> list[Session]:
        """启动时读取的已有 active sessions（崩溃残留）。

        正确顺序（任务书第一阶段 #5）：打开 DB → 读已有 active → 崩溃恢复 →
        处理完成 → 仍无 current session 才创建新场次。禁止先建再恢复。
        """
        active = self.repo.active_sessions(local_only=True)
        if self._clean_shutdown and self._last_local_session_id:
            previous = next((s for s in active if s.id == self._last_local_session_id), None)
            if previous is not None:
                # 旧版本会在这里恢复 last_local_session_id，造成正常重启后
                # 自动跳到上一次场次。现在正常启动统一由 UI 选择“第 1 场”
                # 作为默认；保留这个分支只是为了兼容旧配置并明确跳过崩溃提示。
                app_log.info(
                    "clean startup found previous local session #%d %s; "
                    "default session selection is deferred to the UI",
                    previous.id, previous.name,
                )
                return []
        return active

    def select_default_startup_session(self) -> Session | None:
        """选择正常启动的默认本地场次，不恢复上次场次也不连接 Excel。

        优先选择名称严格为“第 1 场点名”的可写场次；如果旧数据库没有
        这个标准名称，则选择最早创建的本地 active 场次。结束场次保持只读，
        不会被启动逻辑偷偷 reopen。
        """
        active = [s for s in self.all_sessions() if s.status == "active"]
        if not active:
            return None

        def is_first_named(session: Session) -> bool:
            return bool(re.fullmatch(r"第0*1场点名", str(session.name or "").strip()))

        first_named = [s for s in active if is_first_named(s)]
        selected = min(first_named or active, key=lambda s: int(s.id or 0))
        self._current_session_id = selected.id
        # 启动默认选场次也不自动连接该场次的 Excel；连接必须由用户明确触发。
        app_log.info(
            "clean startup selected default local session #%d %s; Excel remains disconnected",
            selected.id, selected.name,
        )
        return selected

    def handle_crash_recovery(self, choice) -> int | None:
        """崩溃恢复决策。choice: 'end_all' / 'defer' / session_id(str)。

        返回恢复的 session_id（或 None）。绝不创建幽灵 active session。
        """
        if choice == "end_all":
            for s in self.repo.active_sessions(local_only=True):
                self.repo.end_session(s.id)
            self._current_session_id = None
            return None
        if choice == "defer":
            self._current_session_id = None
            return None
        try:
            sid = int(choice)
        except (TypeError, ValueError):
            self._current_session_id = None
            return None
        s = self.repo.get_session(sid)
        if (s is None or s.status != "active"
                or (s.external_source or "").strip()):
            self._current_session_id = None
            return None
        self._current_session_id = sid
        return sid

    def ensure_session(self) -> Session:
        """恢复处理完成后仍无 current session → 才创建新场次（避免 ghost active session）。"""
        s = self.current_session()
        if s is None:
            s = self.create_session()
        return s

    def all_sessions(self) -> list[Session]:
        return self.repo.list_sessions(local_only=True)

    def mark_clean_shutdown(self) -> bool:
        """记录正常退出状态；下次启动默认选择第一场，不再恢复上次停留场次。"""
        session = self.current_session()
        sid = None
        if session is not None and not (session.external_source or "").strip():
            sid = session.id
        return self.settings.set_many(clean_shutdown=True,
                                      last_local_session_id=sid)

    def end_current_session(self) -> None:
        s = self.current_session()
        if s:
            self.repo.end_session(s.id)
        # 结束后清空当前场次：后续提交必须新建或显式选择，绝不续写 ended（任务书第一阶段 #4）
        self._current_session_id = None

    def list_checkins(self, session_id: int | None = None) -> list[Checkin]:
        sid = session_id or (self.current_session().id if self.current_session() else None)
        if sid is None:
            return []
        return self.repo.list_checkins(sid)

    # ---------- 本场资料补全（与实时 Parser 分离） ----------
    def completion_suggestions(self, session_id: int | None = None) -> list[dict]:
        session = self.repo.get_session(session_id) if session_id else self.current_session()
        if session is None:
            return []
        return self.completion_engine.suggest_session(session.id)

    # ---------- 工信部电台型号库 ----------
    def miit_catalog_status(self) -> dict:
        if self.miit_catalog is None:
            return {
                "path": str(self.settings.miit_catalog_path), "count": 0,
                "filter_rule_version": "radio-v1", "error": "本地型号库暂不可用",
            }
        try:
            return self.miit_catalog.status()
        except Exception as exc:  # noqa: BLE001
            return {"path": str(self.settings.miit_catalog_path), "count": 0,
                    "error": str(exc)}

    def refresh_miit_catalog(self) -> dict:
        """同步 worker 完成后刷新主线程的只读连接。"""
        if self.miit_catalog is None:
            try:
                self.miit_catalog = MiitCatalogRepository(self.settings.miit_catalog_path)
                self.parser.radio_catalog = self.miit_catalog
                self.completion_engine.catalog = self.miit_catalog
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"型号库打开失败：{exc}"}
        else:
            try:
                self.miit_catalog.reopen()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"型号库刷新失败：{exc}"}
        return {"ok": True, "status": self.miit_catalog_status()}

    def search_miit_radio_models(self, query: str, limit: int = 3) -> list[dict]:
        """只查本地正式快照；该入口绝不发起网络请求。"""
        if self.miit_catalog is None:
            return []
        try:
            return self.miit_catalog.search(query, limit=limit)
        except Exception:  # noqa: BLE001
            app_log.exception("MIIT local catalog search failed")
            return []

    def new_miit_catalog_sync(self, *, provider=None) -> MiitCatalogSyncService:
        """为后台线程创建独立连接的同步服务。"""
        return MiitCatalogSyncService(
            self.settings.miit_catalog_path, provider=provider,
        )

    def cache_miit_device_results(self, query: str, results: list[dict]) -> int:
        """主线程缓存用户主动查询到的公开型号核准结果。"""
        return self.repo.cache_miit_device_results(query, results)

    def cached_miit_device_results(self, query: str, limit: int = 3) -> list[dict]:
        return self.repo.find_miit_device_cache(query, limit=limit)

    def _build_completion_excel_task(self, session_id: int, batch_id: str,
                                      changes: list[dict]) -> dict | None:
        """把整批补全合成一个 Excel worker 任务，只连接和 Save 一次。"""
        session = self.repo.get_session(session_id)
        if session is None:
            return None
        current = self.current_session()
        if current is not None and current.id == session_id and self.excel.sheet is not None:
            excel_path = self.excel.excel_path or self.excel.binding_id
            try:
                sheet_name = str(self.excel.sheet.Name or "")
            except Exception:  # noqa: BLE001
                sheet_name = session.excel_sheet_name or ""
            binding_id = self.excel.binding_id
        else:
            # 补全已结束场次时不能借用当前场次的 Excel 连接；只使用该场次
            # 自己保存的路径和 sheet，连接失败也不会影响 SQLite 批次。
            excel_path = str(session.excel_path or "")
            sheet_name = str(session.excel_sheet_name or "")
            binding_id = excel_path
        if not excel_path:
            return None

        fields_by_record: dict[int, set[str]] = {}
        unmatched_changed: set[int] = set()
        for change in changes:
            record_id = int(change["record_id"])
            fields_by_record.setdefault(record_id, set()).add(str(change["field"]))
            if str(change.get("old_unmatched") or "") != str(change.get("new_unmatched") or ""):
                unmatched_changed.add(record_id)

        items: list[dict] = []
        field_to_excel = {"qth": "qth", "device": "device", "antenna": "antenna",
                          "power": "power"}
        for record_id, fields in fields_by_record.items():
            checkin = self.repo.get_checkin(record_id)
            if checkin is None or checkin.session_id != session_id:
                continue
            updates = {
                field_to_excel[field]: getattr(checkin, f"{field}_standard", "")
                for field in fields
            }
            if record_id in unmatched_changed:
                updates["unmatched"] = checkin.unmatched
            items.append({
                "checkin_id": checkin.id,
                "row": checkin.excel_row,
                "sequence": checkin.sequence_no,
                "callsign": checkin.callsign,
                "updates": updates,
            })
        if not items:
            return None
        return {
            "batch": True,
            "batch_id": batch_id,
            "binding_id": binding_id,
            "excel_path": excel_path,
            "sheet_name": sheet_name,
            "items": items,
        }

    def apply_completion_suggestions(self, selected: list[dict],
                                     session_id: int | None = None) -> dict:
        """原子应用预览中选中的建议，再异步批量同步 Excel。"""
        session = self.repo.get_session(session_id) if session_id else self.current_session()
        if session is None:
            return {"ok": False, "message": "未选择本地场次"}
        if not selected:
            return {"ok": False, "message": "尚未勾选任何补全项"}

        prepared: list[dict] = []
        initial_unmatched: dict[int, str] = {}
        final_unmatched: dict[int, str] = {}
        seen: set[tuple[int, str]] = set()
        selected_groups: set[tuple[int, str]] = set()
        for raw in selected:
            try:
                record_id = int(raw["record_id"])
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "message": "补全建议缺少有效记录编号，请重新生成"}
            field = str(raw.get("field") or "")
            if field not in ("qth", "device", "antenna", "power"):
                return {"ok": False, "message": "补全建议包含不支持的字段，请重新生成"}
            key = (record_id, field)
            if key in seen:
                return {"ok": False, "message": "同一记录字段被重复选中"}
            seen.add(key)
            choice_group = str(raw.get("choice_group") or "").strip()
            group_key = (record_id, choice_group)
            if choice_group and group_key in selected_groups:
                return {
                    "ok": False,
                    "message": "同一段未识别原文被同时解释成多个字段，请只保留一个候选",
                }
            if choice_group:
                selected_groups.add(group_key)
            checkin = self.repo.get_checkin(record_id)
            if checkin is None or checkin.session_id != session.id:
                return {"ok": False, "message": "补全记录已变化，请重新生成建议"}
            snapshot_unmatched = str(raw.get("old_unmatched") or "").strip()
            if record_id in initial_unmatched and initial_unmatched[record_id] != snapshot_unmatched:
                return {"ok": False, "message": "补全快照不一致，请重新生成建议"}
            initial_unmatched[record_id] = snapshot_unmatched
            final_unmatched.setdefault(record_id, snapshot_unmatched)
            new_value = str(raw.get("proposed_value") or "").strip()
            if not new_value:
                return {"ok": False, "message": "补全值不能为空"}
            prepared.append({
                "record_id": record_id,
                "field": field,
                "old_value": str(raw.get("old_value") or "").strip(),
                "new_value": new_value,
                "old_unmatched": snapshot_unmatched,
                "source_type": str(raw.get("source_type") or "manual_review"),
                "source_detail": str(raw.get("source_detail") or ""),
                "confidence": int(raw.get("confidence") or 0),
                "candidate_id": str(raw.get("candidate_id") or ""),
                "choice_group": choice_group,
                "evidence": str(raw.get("evidence") or "").strip(),
                "evidence_token_start": raw.get("evidence_token_start"),
                "evidence_token_end": raw.get("evidence_token_end"),
                "miit_article_id": str(raw.get("miit_article_id") or ""),
                "miit_sync_run_id": str(raw.get("miit_sync_run_id") or ""),
            })
        # token 区间相对于 old_unmatched 快照，按起点倒序删除；没有区间的
        # 旧版/人工建议继续使用兼容的单次字符串消费。
        by_record: dict[int, list[dict]] = {}
        for change in prepared:
            by_record.setdefault(int(change["record_id"]), []).append(change)
        for record_id, changes in by_record.items():
            current = final_unmatched[record_id]
            ranged: list[dict] = []
            fallback: list[dict] = []
            for change in changes:
                start, end = change.get("evidence_token_start"), change.get("evidence_token_end")
                if start is None or end is None:
                    fallback.append(change)
                else:
                    ranged.append(change)
            for change in sorted(
                    ranged,
                    key=lambda item: int(item.get("evidence_token_start") or 0),
                    reverse=True):
                current = _remove_unmatched_span(
                    current, change.get("evidence_token_start"), change.get("evidence_token_end"))
            for change in fallback:
                evidence = str(change.get("evidence") or "").strip()
                if evidence:
                    current = _remove_unmatched_value(current, evidence)
            final_unmatched[record_id] = current
        for change in prepared:
            change["new_unmatched"] = final_unmatched[int(change["record_id"])]

        batch_id = f"{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        try:
            changed_ids = self.repo.apply_completion_batch(
                session.id, batch_id, prepared)
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        except Exception:  # noqa: BLE001
            app_log.exception("completion batch apply failed")
            return {"ok": False, "message": "资料补全保存失败，数据库未应用该批次"}

        callsigns = {self.repo.get_checkin(record_id).callsign for record_id in changed_ids
                     if self.repo.get_checkin(record_id) is not None}
        for callsign in callsigns:
            self.repo.rebuild_profiles_for(callsign)
            self.repo.rebuild_station(callsign)
        self._invalidate_runtime_caches()
        self.refresh_observed_device_aliases()
        excel_task = self._build_completion_excel_task(session.id, batch_id, prepared)
        self.repo.update_completion_excel_status(
            batch_id, "pending" if excel_task else "not_required",
        )
        return {
            "ok": True,
            "batch_id": batch_id,
            "change_count": len(prepared),
            "record_count": len(changed_ids),
            "excel_task": excel_task,
            "message": (
                f"已补全 {len(changed_ids)} 条记录、{len(prepared)} 个字段"
                + ("，Excel 正在后台批量保存" if excel_task else "，SQLite 已安全保存")
            ),
        }

    def apply_completion_batch(self, session_id: int, selections: list[dict]) -> dict:
        """计划中的批次 API 名称；保持旧的参数顺序兼容。"""
        return self.apply_completion_suggestions(selections, session_id)

    def undo_last_completion(self, session_id: int | None = None) -> dict:
        session = self.repo.get_session(session_id) if session_id else self.current_session()
        if session is None:
            return {"ok": False, "message": "未选择本地场次"}
        result = self.repo.undo_last_completion_batch(session.id)
        if not result.get("ok"):
            return result
        actions = result.get("actions") or []
        callsigns = set()
        for record_id in result.get("record_ids") or []:
            checkin = self.repo.get_checkin(record_id)
            if checkin is not None:
                callsigns.add(checkin.callsign)
        for callsign in callsigns:
            self.repo.rebuild_profiles_for(callsign)
            self.repo.rebuild_station(callsign)
        self._invalidate_runtime_caches()
        self.refresh_observed_device_aliases()
        excel_changes = [{
            "record_id": action["record_id"],
            "field": action["field_name"],
            "old_unmatched": action["new_unmatched"],
            "new_unmatched": action["old_unmatched"],
        } for action in actions]
        excel_task = self._build_completion_excel_task(
            session.id, str(result["batch_id"]), excel_changes)
        self.repo.update_completion_excel_status(
            str(result["batch_id"]), "pending" if excel_task else "not_required",
        )
        result["excel_task"] = excel_task
        result["message"] = (
            f"已撤销上一批资料补全（{result['change_count']} 个字段）"
            + ("，Excel 正在后台恢复" if excel_task else "")
        )
        return result

    def undo_last_completion_batch(self, session_id: int) -> dict:
        """计划中的安全撤销 API 名称；只撤销指定本地场次最后一批。"""
        return self.undo_last_completion(session_id)

    # ---------- 解析与提交 ----------
    def parse(self, text: str) -> ParseResult:
        return self.parser.parse(text)

    def full_qth(self, value: str, raw: str = "") -> str:
        """将可确认的 QTH 输出为完整省/市/区县名称。

        Parser 仍保留短标准值以兼容历史画像和低层调用；进入点名记录时，
        commit() 会用这里的结果作为新的标准值。raw 优先用于保留“大学城、
        牛首山、6楼”等行政区划之后的现场细节。
        """
        for candidate in (raw, value):
            if self.qth_place_service is not None:
                try:
                    place = self.qth_place_service.resolve(candidate)
                except Exception:  # noqa: BLE001
                    place = None
                if place:
                    canonical = _norm(place.get("canonical_qth"))
                    if canonical:
                        return canonical
            expanded = full_qth_candidate(candidate, self.region)
            if expanded:
                return expanded
        return _norm(value)

    def search_qth_places(self, query: str, limit: int = 8) -> list[dict]:
        """本地道路/地标检索；不会隐式访问网络。"""
        if self.qth_place_service is None:
            return []
        try:
            return self.qth_place_service.search(query, limit=limit)
        except Exception:  # noqa: BLE001
            return []

    def qth_place_sync_queries(self, limit: int = 5) -> list[str]:
        """返回可供后台地点源缓存的历史 QTH 原文。

        只挑明显的道路/学校/车站/门牌等地点文本；行政区缩写和纯行政区
        不上传。是否联网由设置中的地点包地址或天地图 Key 决定。
        """
        rows = self.repo.as_dict_rows(
            """SELECT qth_raw, qth_standard FROM checkins
               WHERE is_deleted=0 AND TRIM(qth_raw)<>''
               ORDER BY updated_at DESC, id DESC LIMIT 500"""
        )
        markers = ("路", "街", "道", "巷", "号", "站", "机场", "大学",
                   "校园", "门", "镇", "桥", "园", "广场", "小区")
        values: list[str] = []
        for row in rows:
            raw = _norm(row.get("qth_raw"))
            standard = _norm(row.get("qth_standard"))
            if len(raw) < 2 or not any(marker in raw for marker in markers):
                continue
            if raw == standard and standard.startswith(("江苏省", "浙江省", "安徽省")):
                # 已经是完整行政链且没有新的地点尾部，不需要重复查询。
                continue
            if raw not in values:
                values.append(raw)
            if len(values) >= max(0, min(int(limit), 50)):
                break
        return values

    def refresh_qth_place_catalog(self) -> dict:
        """地点包 worker 完成后刷新主线程连接和解析缓存。"""
        if self.qth_place_service is None:
            try:
                self.qth_place_catalog = QthPlaceCatalog(self.settings.qth_place_catalog_path)
                self.qth_place_service = QthPlaceService(self.qth_place_catalog)
                self.parser.qth_norm.set_places(self.qth_place_service)
                self.completion_engine.place_resolver = self.qth_place_service
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"地点库打开失败：{exc}"}
        else:
            try:
                self.qth_place_catalog.reopen()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"地点库刷新失败：{exc}"}
        self._invalidate_runtime_caches()
        return {"ok": True, "status": self.qth_place_service.status()}

    def import_qth_place_pack(self, path: str, *, source: str = "pack") -> dict:
        """导入本地 QTH 地点包，成功后立即可用于离线补全。"""
        if self.qth_place_service is None:
            return {"ok": False, "message": "本地地点库不可用"}
        try:
            count = self.qth_place_service.import_pack(path, source=source)
            return {"ok": True, "count": count,
                    "status": self.qth_place_service.status()}
        except Exception as exc:  # noqa: BLE001
            app_log.warning("QTH place pack import failed: %s", exc)
            return {"ok": False, "message": f"地点包导入失败：{exc}"}

    def qth_place_status(self) -> dict:
        if self.qth_place_service is None:
            return {"path": str(self.settings.qth_place_catalog_path), "count": 0,
                    "message": "地点库不可用"}
        try:
            return self.qth_place_service.status()
        except Exception as exc:  # noqa: BLE001
            return {"path": str(self.settings.qth_place_catalog_path), "count": 0,
                    "message": str(exc)}

    def list_completion_batches(self, session_id: int | None = None,
                                limit: int = 100) -> list[dict]:
        return self.repo.list_completion_batches(session_id, limit=limit)

    def completion_batch_details(self, batch_id: str) -> list[dict]:
        return self.repo.completion_batch_details(batch_id)

    def accept_history(self, result: ParseResult) -> ParseResult:
        """Tab：接受历史建议（仅补缺失字段），进入提交 payload（任务书第二阶段 #1/#2）。"""
        return self.parser.accept_history(result)

    def _excel_values(self, c: Checkin) -> dict:
        return {
            "sequence": c.sequence_no,
            "time": hhmm(c.checkin_time),
            "callsign": c.callsign,
            "qth": c.qth_standard,
            "device": c.device_standard,
            "antenna": c.antenna_standard,
            "power": c.power_standard,
            "signal": c.signal,
            "unmatched": c.unmatched,
        }

    def commit(self, result: ParseResult, *, save_excel: bool | None = None) -> dict:
        """确认一条记录，先安全提交 SQLite，再按调用契约处理 Excel。

        ``save_excel=False`` 是快速点名专用路径：不连接、不读取、不写入
        Excel COM，记录保存到 SQLite 后由场后导出处理。其它调用仍支持旧的
        Excel 状态机：写内存(written) → Save(persisted)；失败则数据库保留
        error/pending 状态，绝不把未持久化内容标成已同步。

        ``save_excel`` 的含义：
        - ``None``：沿用设置项 ``excel_auto_save``（服务层兼容行为）；
        - ``False``：只提交 SQLite，返回 ``excel_state=deferred``；
        - ``True``：连接已存在时立即写入并保存 Excel。
        """
        if not result.callsign.value:
            return {"ok": False, "message": "缺少呼号，无法提交"}
        session = self.current_session()
        if session is None or session.status == "ended":
            # 无当前场次 / 当前场次已结束：自动新建场次。绝不写入 ended 场次。
            if session is not None:
                app_log.info("current session #%d is ended, auto-creating new session", session.id)
            session = self.create_session()
            app_log.info("auto-created session #%d %s", session.id, session.name)

        f = result.fields()
        qth_value = f["qth"].value
        # 只有本次实际输入了 QTH 才自动展开。Tab 接受的历史值保持其原有
        # 画像写法，避免把“历史只在显式接受后进入提交”变成隐式迁移。
        if f["qth"].raw:
            qth_value = self.full_qth(qth_value, f["qth"].raw)
        c = Checkin(
            session_id=session.id,
            # sequence_no 由 add_checkin_with_seq 在分配锁内原子分配（P1-1）
            sequence_no=0,
            checkin_time=datetime.now().isoformat(timespec="seconds"),
            callsign=result.callsign.value,
            qth_raw=f["qth"].raw or f["qth"].value, qth_standard=qth_value,
            device_raw=f["device"].raw or f["device"].value, device_standard=f["device"].value,
            antenna_raw=f["antenna"].raw or f["antenna"].value, antenna_standard=f["antenna"].value,
            power_raw=f["power"].raw or f["power"].value, power_standard=f["power"].value,
            signal=f["signal"].value,
            source="local",
            raw_input=result.raw_text,
            unmatched=" ".join(result.unmatched),
        )
        dup = self.repo.duplicate_in_session(session.id, c.callsign)
        # 原子：分配序号 + 插入在同一分配锁内（正式业务使用安全接口，P1-1）
        self.repo.add_checkin_with_seq(session.id, c)
        # station/profile 是 checkins 的投影：按时间重建，避免 count+1 漂移
        self.repo.rebuild_station(c.callsign)
        self.repo.rebuild_profiles_for(c.callsign)
        self._invalidate_runtime_caches()
        self._add_observed_device_evidence(c.device_raw, c.device_standard)
        # 用户已经确认并提交的道路/门牌/地标是安全的本地学习样本；行政
        # 区缩写本身不写入地点库，避免把 njxw 这类已有区划别名伪装成道路。
        qth_raw = _norm(f["qth"].raw)
        if (self.qth_place_service is not None and qth_raw and qth_value
                and any(marker in qth_raw for marker in
                        ("路", "街", "道", "巷", "号", "站", "机场", "大学", "校园", "门", "镇"))):
            try:
                self.qth_place_service.learn(qth_raw, qth_value)
            except Exception as exc:  # noqa: BLE001
                app_log.debug("QTH place learning skipped: %s", exc)
        app_log.info("committed #%d %s", c.sequence_no, c.callsign)

        # --- Excel：快速点名明确不进入 COM 热路径 ---
        # ``save_excel=False`` 是 UI 的快速录入契约：只提交 SQLite，既不
        # 连接 Excel，也不写入 Excel 内存。这样 Excel 卡顿/弹窗/锁文件都
        # 不会阻塞输入，更不会因为半写状态让用户误以为记录丢失。
        excel_ok, excel_msg, excel_row, excel_state = True, "未连接 Excel", None, "pending"
        if save_excel is False:
            excel_msg, excel_state = "已写入 SQLite，等待场后导出", "deferred"
        elif self.excel.sheet is not None:
            should_save = (bool(self.settings.get("excel_auto_save", True))
                           if save_excel is None else bool(save_excel))
            now = datetime.now().isoformat(timespec="seconds")
            write_ok, write_msg, excel_row = self.excel.write(
                self._excel_values(c), auto_save=False)
            if not write_ok:
                excel_ok, excel_msg, excel_state = False, write_msg, "error"
                self.repo.set_excel_state(c.id, "error", row=excel_row,
                                          error=write_msg, binding_id=self.excel.binding_id)
            elif not should_save:
                # 快速点名路径：只写当前 Excel 内存，等待空闲批量 Save。
                excel_state = "written"
                excel_msg = f"已写入第 {excel_row} 行，等待保存"
                self.repo.set_excel_state(c.id, "written", row=excel_row,
                                          error="", binding_id=self.excel.binding_id)
            else:
                save_ok, save_msg = self.excel.save()
                if save_ok:
                    excel_state = "persisted"
                    self.repo.set_excel_state(c.id, "persisted", row=excel_row,
                                              synced_at=now, binding_id=self.excel.binding_id)
                else:
                    excel_ok, excel_msg, excel_state = False, save_msg, "error"
                    self.repo.set_excel_state(c.id, "error", row=excel_row,
                                              error=save_msg, binding_id=self.excel.binding_id)
        return {"ok": True, "checkin": c, "duplicate": dup,
                "excel_ok": excel_ok, "excel_msg": excel_msg,
                "excel_persisted": excel_state in ("persisted", "verified"),
                "excel_row": excel_row, "excel_state": excel_state}

    def _invalidate_runtime_caches(self) -> None:
        """统一缓存失效入口（提交/撤销/编辑/导入/同步后调用，任务书第二阶段 #10）。"""
        if hasattr(self, "_freq_cache"):
            del self._freq_cache
        self.parser.invalidate_caches()

    def _rebuild_observed_device_aliases(self) -> None:
        """把观察证据折叠成唯一的临时设备缩写映射。

        观察索引只允许“一个缩写 → 一个已经存在的标准设备值”。同一
        缩写若对应多个标准值，则不自动解析，仍可由用户在词典页明确
        指定；这条边界对未核准型号尤其重要。
        """
        reserved = set(self.store.device)
        aliases: dict[str, str] = {}
        for alias, values in self._observed_device_evidence.items():
            if alias in reserved or not values:
                continue
            ranked = values.most_common()
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                aliases[alias] = ranked[0][0]
        self._observed_device_aliases = aliases
        self.parser.set_observed_device_aliases(aliases)
        self.completion_engine.set_observed_device_aliases(aliases)

    def _add_observed_device_evidence(self, raw: str, standard: str) -> None:
        """增量加入一条已保存记录，不扫描全表，避免连续点名卡顿。"""
        standard = _norm(standard)
        if not standard:
            return
        for alias in device_model_abbreviations(raw, standard):
            # 标准值本身就是裸型号时，不需要建立“m8268 -> m8268”这种
            # 无意义映射；标准值带品牌时仍会得到 m8268 -> 品牌+型号。
            if alias == standard.strip().lower():
                continue
            self._observed_device_evidence.setdefault(alias, Counter())[standard] += 1
        self._rebuild_observed_device_aliases()

    def refresh_observed_device_aliases(self) -> dict[str, str]:
        """从当前本地记录重建观察缩写索引并返回安全映射。

        该方法只读主 SQLite，适合在导入/365dt 后台任务完成回调中调用；
        快速提交路径使用 ``_add_observed_device_evidence`` 的增量版本。
        """
        rows = self.repo.as_dict_rows(
            """SELECT device_raw, device_standard, COUNT(*) AS use_count
               FROM checkins
               WHERE is_deleted=0 AND TRIM(device_standard)!=''
               GROUP BY device_raw, device_standard"""
        )
        evidence: dict[str, Counter[str]] = defaultdict(Counter)
        for row in rows:
            standard = _norm(row.get("device_standard"))
            if not standard:
                continue
            for alias in device_model_abbreviations(
                    row.get("device_raw", ""), standard):
                if alias == standard.strip().lower():
                    continue
                evidence[alias][standard] += int(row.get("use_count") or 1)
        self._observed_device_evidence = dict(evidence)
        self._rebuild_observed_device_aliases()
        return dict(self._observed_device_aliases)

    def undo_last(self, *, sync_excel: bool = True) -> dict:
        """撤销本场最后一条有效记录。

        ``sync_excel`` 默认保持旧服务层行为，便于脚本/测试显式要求整场重排。
        UI 快捷撤销必须传 False：Excel 的整场重写包含 COM 清空、写入、Save 和
        读回验证，不能在 Qt 主线程中执行，否则 Excel 卡顿时会把后续按键排队，
        造成连续多条记录被误撤销。此模式宁可暂时保留 Excel 原表，也不自动
        清空或覆盖用户数据。
        """
        session = self.current_session()
        if session is None:
            return {"ok": False, "message": "尚未选择场次"}
        last = self.repo.last_checkin(session.id)
        if last is None:
            return {"ok": False, "message": "没有可撤销的记录"}
        self.repo.soft_delete_checkin(last.id)
        app_log.info("undo #%d %s", last.sequence_no, last.callsign)
        # 撤销后重建该呼号投影 + 失效缓存（任务书第一阶段 #17）
        self.repo.rebuild_station(last.callsign)
        self.repo.rebuild_profiles_for(last.callsign)
        self._invalidate_runtime_caches()
        self.refresh_observed_device_aliases()
        excel_msg = "未连接 Excel"
        if self.excel.sheet is not None and sync_excel:
            excel_ok, excel_msg = self.excel_resync()
            if not excel_ok:
                app_log.warning("undo excel resync failed: %s", excel_msg)
        elif self.excel.sheet is not None:
            excel_msg = "未自动重排（为防卡顿保留原表，稍后补同步）"
        return {"ok": True, "checkin": last, "excel_msg": excel_msg}

    # ---------- Excel ----------
    def excel_connect(self, excel_path: str = "", sheet_name: str = "") -> tuple[bool, str]:
        ok, msg = self.excel.connect(
            excel_path or self.settings.get("excel_template", ""),
            sheet_name or self.settings.get("excel_sheet_name", ""),
        )
        if ok:
            self.settings.set("excel_template", self.excel.excel_path)
            self.settings.set("excel_sheet_name", getattr(self.excel.sheet, "Name", "") or "")
            # 把绑定写入当前场次（Session 级绑定，任务书第一阶段 #5）
            s = self.current_session()
            if s is not None:
                self.repo.update_session(s.id, excel_path=self.excel.excel_path,
                                         excel_sheet_name=getattr(self.excel.sheet, "Name", "") or "")
        return ok, msg

    def excel_resync(self) -> tuple[bool, str]:
        """整场重写：只清理受管列 → Save → readback → 逐行 verify → 单事务标状态。

        P1-6：不逐行记录真实 row / readback 验证，绝不全量假标成功。
        失败（Save 失败 / 行身份冲突）→ error / conflict。
        """
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        if self.excel.sheet is None:
            return False, "未连接 Excel"
        checkins = self.repo.list_checkins(session.id)
        snapshot = self.excel.snapshot_managed_rows()
        self.repo.reset_excel_sync(session.id)
        # 1) rewrite（写受管列，不 Save）
        ok, msg = self.excel.rewrite_all(checkins, self._excel_values, auto_save=False)
        if not ok:
            self.excel.restore_managed_rows(snapshot)
            return False, msg
        # 2) Save
        save_ok, save_msg = self.excel.save()
        if not save_ok:
            restored = self.excel.restore_managed_rows(snapshot)
            if not restored:
                save_msg += "；且无法恢复工作簿内存内容"
            self.repo.set_excel_states_atomic([
                {"checkin_id": c.id, "status": "error", "row": None, "error": save_msg}
                for c in checkins])
            return False, f"Excel 保存失败：{save_msg}"
        # 3) readback + 逐行 verify（sequence+callsign）→ 保存每条 excel_row
        start = (self.excel.header_row or 1) + 1
        states = []
        conflicts = []
        for idx, c in enumerate(checkins):
            row = start + idx
            if not self.excel.verify_row_identity(row, c.sequence_no, c.callsign):
                conflicts.append(f"#{c.sequence_no} {c.callsign}")
                states.append({"checkin_id": c.id, "status": "conflict",
                               "row": row, "error": "行身份不匹配"})
            else:
                states.append({"checkin_id": c.id, "status": "verified",
                               "row": row, "error": ""})
        self.repo.set_excel_states_atomic(states)  # P1-7 单事务
        if conflicts:
            return False, "resync 行身份冲突：" + ",".join(conflicts[:40])
        return True, f"已重写 {len(checkins)} 行并验证"

    def flush_excel_pending(self) -> tuple[bool, str]:
        """一次性保存当前场次所有未持久化 Excel 记录。

        ``written`` 记录如果原行仍能通过 sequence+callsign 身份校验，只做
        Save，不重复追加；``pending``/``error`` 或行已漂移的记录才追加新行。
        这样快速录入的空闲批量保存不会产生重复行，且 Save/读回失败仍会留在
        未同步状态中。

        任何一步失败都不得提前把成功状态写入 DB。
        """
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        if self.excel.sheet is None:
            return False, "未连接 Excel，请先连接"
        unsynced = self.repo.list_unsynced(session.id)
        if not unsynced:
            return True, "没有缺失记录"
        rows: dict[int, int] = {}
        to_write = []
        for c in unsynced:
            if (c.excel_sync_status == "written" and c.excel_row
                    and self.excel.verify_row_identity(c.excel_row, c.sequence_no, c.callsign)):
                rows[c.id] = c.excel_row
            else:
                to_write.append(c)

        self.excel.reset_next_row()
        for c in to_write:
            ok, msg, row = self.excel.write(self._excel_values(c), auto_save=False)
            if not ok:
                # 已经写入内存的前序记录保留 written，失败项标 error；下一次
                # 重试会复用仍然有效的 written 行，不重复追加。
                states = [
                    {"checkin_id": item.id, "status": "written", "row": rows[item.id],
                     "error": ""}
                    for item in unsynced if item.id in rows
                ]
                states.append({"checkin_id": c.id, "status": "error", "row": row,
                               "error": msg})
                self.repo.set_excel_states_atomic(states)
                return False, f"补同步失败（#{c.sequence_no} {c.callsign}）：{msg}"
            rows[c.id] = row
        # 2) Save 一次
        save_ok, save_msg = self.excel.save()
        if not save_ok:
            # P1-7：单事务批量标 error
            self.repo.set_excel_states_atomic([
                {"checkin_id": c.id, "status": "error", "row": rows.get(c.id), "error": save_msg}
                for c in unsynced])
            return False, f"Excel 保存失败：{save_msg}"
        # 3) 读回验证写入行（身份校验）
        conflicts = []
        for c in unsynced:
            r = rows.get(c.id)
            if r is None or not self.excel.verify_row_identity(r, c.sequence_no, c.callsign):
                conflicts.append(f"#{c.sequence_no} {c.callsign}")
        if conflicts:
            # P1-7：单事务批量标 conflict
            self.repo.set_excel_states_atomic([
                {"checkin_id": c.id, "status": "conflict", "row": rows.get(c.id),
                 "error": "行身份不匹配"}
                for c in unsynced])
            return False, "补同步行身份冲突：" + ",".join(conflicts)
        # 4) 单事务标记 persisted（P1-7）
        self.repo.set_excel_states_atomic([
            {"checkin_id": c.id, "status": "persisted", "row": rows[c.id], "error": ""}
            for c in unsynced])
        return True, f"已补同步 {len(unsynced)} 条缺失记录"

    def excel_sync_missing(self) -> tuple[bool, str]:
        """兼容旧入口：保存/补同步当前场次的未持久化记录。"""
        return self.flush_excel_pending()

    def excel_status_text(self) -> str:
        if self.excel.sheet is None:
            return "○ 未连接"
        try:
            wb = self.excel.excel_path or ""
            name = self.excel.sheet.Name
        except Exception:  # noqa: BLE001
            name = "?"
        return f"● 已连接：{name}（{wb}）"

    def check_consistency(self) -> tuple[bool, str]:
        """SQLite 本场 vs Excel 读回数据比对（P0-6）。"""
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        if self.excel.sheet is None:
            return False, "未连接 Excel，无法比对"
        sqlite = self.repo.list_checkins(session.id)
        excel_rows = self.excel.read_data()
        ok, report = build_consistency_report(sqlite, excel_rows)
        return ok, report

    def export_session(self, session_id: int, dest: str) -> str:
        return exporter_export(self.repo, session_id, dest)

    # ---------- 统计 / 复制（P2 轻量） ----------
    def session_stats(self, session_id: int | None = None) -> dict:
        """场次统计。

        - total: 记录总数
        - first: 本场「首次通联」呼号数（该呼号全局最早记录在本场）
        - dup: 重复报到呼号数（同一呼号在本场出现 >1 次的**呼号个数**）
        - outside: 非默认省份 QTH 记录数
        """
        sid = session_id or (self.current_session().id if self.current_session() else None)
        if sid is None:
            return {"total": 0, "first": 0, "dup": 0, "outside": 0}
        checkins = self.repo.list_checkins(sid)
        province = self.settings.get("default_province", "江苏")
        per_callsign: dict[str, int] = {}
        for c in checkins:
            per_callsign[c.callsign] = per_callsign.get(c.callsign, 0) + 1
        dup = sum(1 for v in per_callsign.values() if v > 1)
        # 首次出现：该呼号全局最早记录在本场
        global_first = {r["callsign"]: r["t"] for r in self.repo.as_dict_rows(
            "SELECT callsign, MIN(checkin_time) t FROM checkins WHERE is_deleted=0 "
            "AND callsign!='' GROUP BY callsign")}
        first = 0
        seen_cs = set()
        for c in checkins:
            if c.callsign not in seen_cs and global_first.get(c.callsign) == c.checkin_time:
                first += 1
            seen_cs.add(c.callsign)
        # 省外：标准显示以“非默认省份”开头（省内省略省份，如“南京栖霞”）
        province_names = [p for p in REGIONS if p != province]
        outside = 0
        for c in checkins:
            q = c.qth_standard or ""
            if q and any(q.startswith(p) for p in province_names):
                outside += 1
        return {"total": len(checkins), "first": first, "dup": dup, "outside": outside}

    def copy_session_text(self, session_id: int | None = None) -> str:
        sid = session_id or (self.current_session().id if self.current_session() else None)
        if sid is None:
            return ""
        lines = []
        for c in self.repo.list_checkins(sid):
            lines.append(f"{c.sequence_no:03d} {hhmm(c.checkin_time)} {c.callsign} "
                         f"{c.qth_standard or ''} {c.device_standard or ''} "
                         f"{c.antenna_standard or ''} {c.power_standard or ''}")
        return "\n".join(lines)

    # ---------- 导入 ----------
    def import_excel_files(self, paths: list[str]) -> dict:
        result = self.excel_provider.import_files([Path(p) for p in paths], self.standardizer)
        self.refresh_observed_device_aliases()
        return result

    def import_excel_folder(self, folder: str) -> dict:
        result = self.excel_provider.import_folder(Path(folder), self.standardizer)
        self.refresh_observed_device_aliases()
        return result

    def raw_imports(self) -> list:
        return self.repo.list_raw_imports()

    # ---------- 365dt ----------
    def sync_365dt(self, progress=None) -> dict:
        """同一时间只允许一个同步任务（任务书第二阶段 #21）。"""
        if getattr(self, "_sync_in_progress", False):
            return {"ok": False, "message": "同步正在进行，请稍候"}
        self._sync_in_progress = True
        try:
            result = self.sync_service.sync_once(progress)
            self.refresh_observed_device_aliases()
            return result
        finally:
            self._sync_in_progress = False

    def sync_state_text(self) -> str:
        st = self.repo.get_sync_state("365dt", self.settings.get("dt365_uid", ""))
        if not st:
            return "未同步"
        if st.status == "error":
            return f"上次失败：{st.error_message[:60]}"
        return f"上次成功：{st.last_success_at or '-'}"

    # ---------- 呼号库 ----------
    def search_stations(self, keyword: str) -> list[dict]:
        return self.repo.search_stations(keyword)

    def station_summary(self, callsign: str) -> dict:
        callsign = (callsign or "").upper()
        station = self.repo.get_station(callsign)
        profiles = {ft: [p.field_value for p in self.repo.profiles_for(callsign, ft, 5)]
                    for ft in ("qth", "device", "antenna", "power")}
        history = self.repo.station_history(callsign, 30)
        return {"callsign": callsign, "station": station, "profiles": profiles,
                "history": history}

    def all_callsigns(self) -> list[str]:
        return [r["callsign"] for r in self.repo.as_dict_rows(
            "SELECT callsign FROM stations WHERE callsign!='' ORDER BY checkin_count DESC")]

    def list_stations(self, keyword: str = "", limit: int = 200) -> list[dict]:
        """呼号库列表：始终返回统一 dict（修复 StationPage 类型错误，任务书第一阶段 #18）。

        字段固定：callsign / checkin_count / last_seen / last_qth / last_device / last_power。
        """
        rows = self.repo.search_stations(keyword, limit=limit) if keyword \
            else self.repo.as_dict_rows(
                "SELECT * FROM stations WHERE callsign!='' "
                "ORDER BY checkin_count DESC LIMIT ?", (limit,))
        return [
            {"callsign": r["callsign"], "checkin_count": r["checkin_count"],
             "last_seen": r["last_seen"], "last_qth": r["last_qth"],
             "last_device": r["last_device"], "last_power": r["last_power"]}
            for r in rows
        ]

    def rebuild_region(self) -> None:
        """默认省份改变时重建区划索引（同步更新 Parser / 标准器引用）。"""
        self.region = RegionIndex(self.settings.get("default_province", "江苏"))
        self.parser.region = self.region
        self.parser.qth_norm.region = self.region
        self.standardizer.qth_norm.region = self.region
        self.completion_engine.region = self.region
        self.parser.invalidate_caches()

    def apply_runtime_settings(self) -> None:
        """保存设置后立即应用运行时（P1-14：不出现 JSON 新值 / runtime 旧值）。

        热生效：default_province / fuzzy_* / dt365_uid / dt365_max_fetch。
        global_hotkey / window_* 由 UI 层单独处理（SettingsPage 通过回调）。
        """
        self.rebuild_region()
        # 模糊阈值
        self.parser.fuzzy_high = float(self.settings.get("fuzzy_high", 92))
        self.parser.fuzzy_mid = float(self.settings.get("fuzzy_mid", 75))
        self.parser.fuzzy_margin = float(self.settings.get("fuzzy_margin", 5))
        # 365dt provider（UID / 规模变化 → 重建，进入新命名空间）
        self.sync_service.provider = Dt365Provider(
            self.settings.get("dt365_uid", ""),
            max_fetch=int(self.settings.get("dt365_max_fetch", 200)),
        )
        self._invalidate_runtime_caches()

    # ---------- 词典管理 ----------
    def get_aliases(self, kind: str):
        return self.repo.get_aliases(kind)

    def set_alias(self, kind: str, alias: str, standard: str, **extra) -> None:
        self.repo.set_alias(kind, alias, standard, **extra)
        self.store.reload()
        self.parser.invalidate_caches()
        if kind == "device":
            # 手工词典优先级最高；同时从观察索引移除同名临时候选，
            # 避免补全列表同时出现“缩写”和“历史缩写”两条。
            self._rebuild_observed_device_aliases()

    def delete_alias(self, kind: str, alias: str) -> None:
        self.repo.delete_alias(kind, alias)
        self.store.reload()
        self.parser.invalidate_caches()
        if kind == "device":
            # 删除手工别名后恢复仍然有效的历史唯一映射。
            self._rebuild_observed_device_aliases()

    # ---------- 从历史/导入记录自动生成词典建议（人工确认，不自动写死） ----------
    def suggest_aliases_from_imports(self, min_count: int = 2, limit: int = 100) -> list[dict]:
        """扫描本地、365dt、Excel 记录，从「原始值→标准值」推导别名建议。

        例：device_raw「摩托罗拉 GM 338」→ 建议 gm338 → 摩托罗拉 GM 338
            qth_standard「盐城」→ 建议 yc → 盐城（无冲突时）
        只给「建议」，由用户在界面勾选后加入，绝不自动覆盖；未核准
        机型不需要也不会因为没有工信部记录而被丢弃。
        """
        rows = self.repo.as_dict_rows(
            """SELECT device_raw, device_standard, qth_standard, source
               FROM checkins
               WHERE is_deleted=0""")
        dev: dict[str, dict[str, int]] = {}
        qth_std: dict[str, int] = {}
        for r in rows:
            raw, std = (r["device_raw"] or ""), (r["device_standard"] or "")
            if raw and std:
                for key in device_model_abbreviations(raw, std):
                    if key in self.store.device:  # 已有别名，跳过
                        continue
                    dev.setdefault(key, {})
                    dev[key][std] = dev[key].get(std, 0) + 1
            q = r["qth_standard"] or ""
            if q:
                qth_std[q] = qth_std.get(q, 0) + 1

        out: list[dict] = []
        for key, stdmap in dev.items():
            ranked = sorted(stdmap.items(), key=lambda kv: (-kv[1], kv[0]))
            best, best_n = ranked[0]
            if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
                # 例如两个品牌都把“gm338”写成自己的型号时，不给出
                # 看似确定的词典建议；用户可以在设备词典中手工指定。
                continue
            if best_n >= min_count:
                out.append({"kind": "device", "alias": key,
                            "standard": best, "count": best_n})
        for std, n in qth_std.items():
            if n < min_count:
                continue
            abbr, conflicts = self.suggest_qth_abbr(std)
            if (abbr and not conflicts
                    and not any(a.alias == abbr for a in self.store.qth.values())):
                out.append({"kind": "qth", "alias": abbr,
                            "standard": std, "count": n})
        out.sort(key=lambda x: -x["count"])
        return out[:limit]

    def add_alias_suggestions(self, suggestions: list[dict]) -> int:
        """加入选中的建议，返回成功数量。"""
        added = 0
        for s in suggestions:
            if s["kind"] == "qth":
                self.set_alias("qth", s["alias"], s["standard"])
            else:
                self.set_alias(s["kind"], s["alias"], s["standard"])
            added += 1
        return added

    # ---------- 审计 / 修改 ----------
    _EXCEL_FIELD = {"qth_standard": "qth", "device_standard": "device",
                    "antenna_standard": "antenna", "power_standard": "power"}

    def _build_deferred_excel_task(self, c: Checkin, field: str,
                                   new_value: str,
                                   *, extra_updates: dict[str, str] | None = None
                                   ) -> dict | None:
        """为 UI 修改构造独立 COM worker 所需的快照，不携带主线程 COM proxy。"""
        if self.excel.sheet is None:
            return None
        if field == "callsign":
            excel_field = "callsign"
        elif field == "signal":
            excel_field = "signal"
        else:
            excel_field = self._EXCEL_FIELD.get(
                {"qth": "qth_standard", "device": "device_standard",
                 "antenna": "antenna_standard", "power": "power_standard"}.get(field, ""),
            )
        if not excel_field:
            return None
        try:
            sheet_name = str(self.excel.sheet.Name or "")
        except Exception:  # noqa: BLE001
            sheet_name = ""
        excel_path = self.excel.excel_path or self.excel.binding_id
        if not excel_path:
            return None
        updates = {excel_field: new_value}
        if extra_updates:
            updates.update(extra_updates)
        return {
            "checkin_id": c.id,
            "binding_id": self.excel.binding_id,
            "excel_path": excel_path,
            "sheet_name": sheet_name,
            "row": c.excel_row,
            "sequence": c.sequence_no,
            # 呼号修改时这里必须是修改前的值，用来验证原 Excel 行身份。
            "callsign": c.callsign,
            "excel_field": excel_field,
            "new_value": new_value,
            # 兼容旧任务字段，同时允许一次后台 Save 更新多个相关列。
            "updates": updates,
        }

    def update_checkin(self, checkin_id: int, field: str, new_value: str,
                       *, defer_excel: bool = False) -> dict:
        """修改记录：SQLite + 审计 + Excel 就地更新（先做行身份校验）+ 投影重建。

        修改呼号时按任务书第一阶段 #16：保存 old_callsign → 更新 → 重建旧站/新站
        → 同步 Excel → 审计。

        ``defer_excel=True`` 供 UI 修改入口使用：SQLite 立即更新，Excel 单行更新
        与 Save 交给独立 COM worker，避免 Excel 慢 Save 阻塞 Qt 主线程。默认值保持
        同步行为，兼容服务层调用和旧 API。
        """
        c = self.repo.get_checkin(checkin_id)
        if c is None:
            return {"ok": False, "message": "记录不存在"}
        col = {"qth": "qth_standard", "device": "device_standard",
               "antenna": "antenna_standard", "power": "power_standard"}.get(field)
        if col is None and field not in ("signal", "callsign"):
            return {"ok": False, "message": "不支持的字段"}
        target = col or field
        old = getattr(c, target, "")
        new_value = (new_value or "").strip()
        if field == "callsign":
            # P2：呼号修改必须先规范化+校验，非法值拒绝写入（绝不静默存脏数据）
            from normalizers.callsign import normalize_callsign
            norm, valid, issues = normalize_callsign(new_value)
            if not valid:
                return {"ok": False,
                        "message": f"呼号不合法：{'；'.join(issues) or '格式错误'}"}
            new_value = norm
        old_callsign = c.callsign
        old_unmatched = _norm(c.unmatched)
        new_unmatched = old_unmatched
        # 设备/天线/QTH 手工归类时，若旧的“未识别”列中正好有这个值，
        # 同时消费一次。这样人工修正不会在标准列和未识别列各留一份。
        if col:
            new_unmatched = _remove_unmatched_value(old_unmatched, new_value)
        updates = {target: new_value}
        if new_unmatched != old_unmatched:
            updates["unmatched"] = new_unmatched
        self.repo.update_checkin(checkin_id, **updates)
        self.repo.add_audit(checkin_id, field, old, new_value)
        if new_unmatched != old_unmatched:
            self.repo.add_audit(checkin_id, "unmatched", old_unmatched, new_unmatched)

        excel_task = None
        excel_msg = "未连接 Excel"
        if defer_excel:
            extra_excel_updates = ({"unmatched": new_unmatched}
                                    if new_unmatched != old_unmatched else None)
            excel_task = self._build_deferred_excel_task(
                c, field, new_value, extra_updates=extra_excel_updates)
            if excel_task is not None:
                self.repo.set_excel_state(
                    c.id, "pending", row=excel_task.get("row"), error="",
                    binding_id=excel_task.get("binding_id", ""),
                )
                excel_msg = "Excel 后台同步中"
        elif field == "callsign":
            excel_msg = self._update_callsign_excel(c, new_value)
        elif field == "signal":
            # P1-4：信号修改必须同步 Excel signal 列（行身份校验一致）
            excel_msg = self._update_field_excel(c, "signal", new_value)
        elif col:
            excel_updates = {self._EXCEL_FIELD[col]: new_value}
            if new_unmatched != old_unmatched:
                excel_updates["unmatched"] = new_unmatched
            excel_msg = self._update_fields_excel(c, excel_updates)

        # 投影重建（checkins 为唯一事实源，绝不 count+1）
        if field == "callsign":
            new_cs = (new_value or "").strip().upper() or c.callsign
            self.repo.rebuild_profiles_for(old_callsign)
            self.repo.rebuild_station(old_callsign)   # 旧呼号：无记录 → 删除投影
            self.repo.rebuild_profiles_for(new_cs)
            self.repo.rebuild_station(new_cs)         # 新呼号
        else:
            self.repo.rebuild_profiles_for(c.callsign)
            self.repo.rebuild_station(c.callsign)
        self._invalidate_runtime_caches()
        if field == "device":
            # 编辑设备属于低频操作，允许这里做一次完整重建，确保新确认
            # 的非工信部型号缩写立即可用于下一条现场输入。
            self.refresh_observed_device_aliases()
        return {"ok": True, "excel_msg": excel_msg, "excel_task": excel_task}

    def finish_deferred_excel_update(self, result: dict) -> tuple[bool, str]:
        """接收后台 Excel worker 结果，并在主线程安全更新同步状态。"""
        if result.get("batch"):
            item_results = result.get("items") or []
            states: list[dict] = []
            success = 0
            for item in item_results:
                try:
                    checkin_id = int(item.get("checkin_id"))
                except (TypeError, ValueError):
                    continue
                ok = bool(item.get("ok"))
                if ok:
                    success += 1
                state = "persisted" if ok else (
                    "conflict" if item.get("state") == "conflict" else "error")
                states.append({
                    "checkin_id": checkin_id,
                    "status": state,
                    "row": item.get("row"),
                    "error": "" if ok else str(item.get("message") or "Excel 批量更新失败"),
                })
            if states:
                self.repo.set_excel_states_atomic(states)
            failed = len(states) - success
            if not states:
                self.repo.update_completion_excel_status(
                    str(result.get("batch_id") or ""), "error", str(result.get("message") or ""),
                )
                return False, str(result.get("message") or "Excel 批量结果缺少记录状态")
            if failed:
                self.repo.update_completion_excel_status(
                    str(result.get("batch_id") or ""), "partial",
                    f"成功 {success} 条，失败/冲突 {failed} 条",
                )
                return False, f"批量保存完成 {success} 条，失败/冲突 {failed} 条；可点击“保存/补同步”重试"
            self.repo.update_completion_excel_status(
                str(result.get("batch_id") or ""), "persisted", "",
            )
            return True, f"已批量保存 {success} 条补全记录"
        try:
            checkin_id = int(result.get("checkin_id"))
        except (TypeError, ValueError):
            return False, "Excel 后台结果缺少记录编号"
        row = result.get("row")
        binding_id = str(result.get("binding_id") or "")
        if result.get("ok"):
            msg = str(result.get("message") or "Excel 已更新")
            self.repo.set_excel_state(
                checkin_id, "persisted", row=row,
                synced_at=datetime.now().isoformat(timespec="seconds"),
                binding_id=binding_id,
            )
            return True, msg
        state = "conflict" if result.get("state") == "conflict" else "error"
        msg = str(result.get("message") or "Excel 后台更新失败")
        self.repo.set_excel_state(
            checkin_id, state, row=row, error=msg, binding_id=binding_id,
        )
        return False, msg

    def _update_field_excel(self, c: Checkin, excel_field: str, new_value: str) -> str:
        return self._update_fields_excel(c, {excel_field: new_value})

    def _update_fields_excel(self, c: Checkin, updates: dict[str, str]) -> str:
        """就地更新 Excel 行：先验证 row.sequence==sequence_no 且 row.callsign==callsign。

        不匹配 → 搜索唯一匹配 → 唯一才更新；否则标记 conflict 绝不乱写（任务书第一阶段 #8/#9）。
        P1-5：程序写入必须 Save，绝不未 Save 就标 persisted。
        """
        if self.excel.sheet is None:
            return "未连接 Excel"
        now = datetime.now().isoformat(timespec="seconds")
        row = c.excel_row
        if row and self.excel.verify_row_identity(row, c.sequence_no, c.callsign):
            ok, msg = self.excel.update_row(row, updates, auto_save=True)
            if ok:
                self.repo.set_excel_state(c.id, "persisted", row=row, synced_at=now,
                                          binding_id=self.excel.binding_id)
                return msg
            self.repo.set_excel_state(c.id, "error", row=row, error=msg,
                                      binding_id=self.excel.binding_id)
            return msg
        # 身份不匹配：搜索唯一匹配
        found = self.excel.find_row(c.sequence_no, c.callsign)
        if found is None:
            self.repo.set_excel_state(c.id, "conflict", row=row,
                                      error="行身份不匹配且无唯一匹配",
                                      binding_id=self.excel.binding_id)
            return "Excel 行身份冲突，已标记，未修改"
        ok, msg = self.excel.update_row(found, updates, auto_save=True)
        if ok:
            self.repo.set_excel_state(c.id, "persisted", row=found, synced_at=now,
                                      binding_id=self.excel.binding_id)
            return f"已在第 {found} 行更新"
        self.repo.set_excel_state(c.id, "error", row=found, error=msg,
                                  binding_id=self.excel.binding_id)
        return msg

    def _update_callsign_excel(self, c: Checkin, new_value: str) -> str:
        """修改呼号时同步 Excel 行（同样先做身份校验）。"""
        if self.excel.sheet is None:
            return "未连接 Excel"
        now = datetime.now().isoformat(timespec="seconds")
        row = c.excel_row
        if not row or not self.excel.verify_row_identity(row, c.sequence_no, c.callsign):
            found = self.excel.find_row(c.sequence_no, c.callsign)
            if found is None:
                self.repo.set_excel_state(c.id, "conflict", row=row,
                                          error="行身份不匹配且无唯一匹配",
                                          binding_id=self.excel.binding_id)
                return "Excel 行身份冲突，已标记，未修改"
            row = found
        ok, msg = self.excel.update_row(row, {"callsign": new_value}, auto_save=True)
        if ok:
            self.repo.set_excel_state(c.id, "persisted", row=row, synced_at=now,
                                      binding_id=self.excel.binding_id)
            return msg
        self.repo.set_excel_state(c.id, "error", row=row, error=msg,
                                  binding_id=self.excel.binding_id)
        return msg

    # ---------- 输入自动补全（V2.6，轻量候选） ----------
    def token_is_complete(self, token: str) -> bool:
        """token 已是「完整唯一值」→ 不弹补全，直接回车提交。

        - 精确别名（5→5W、k6、njqx…）
        - 区划唯一命中（jsyz→扬州、nj→南京、yz→扬州…）
        - 精确命中已知呼号（ba4rll → BA4RLL）
        只有无法唯一解析的部分前缀（njq、id、rll…）才弹候选。
        """
        from normalizers.dictionaries import norm_key
        t = norm_key(token)
        if not t:
            return False
        if self.parser.resolve_device_token(token)[0]:
            return True
        if t in self.store.qth:
            return True
        if t in self.store.antenna or t in self.store.power:
            return True
        if len(self.region.resolve_initials(t)) == 1:
            return True
        if self.repo.get_station(t.upper()):
            return True
        if self.qth_place_service is not None:
            try:
                if self.qth_place_service.resolve(token):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def complete_callsign(self, token: str, limit: int = 8) -> list[tuple[str, str]]:
        """呼号补全：从历史站库搜索（前缀或包含），如 rll → BA4RLL。"""
        t = (token or "").strip()
        if len(t) < 2:
            return []
        rows = self.repo.search_stations(t, limit=limit)
        out = []
        seen = set()
        for r in rows:
            cs = r["callsign"]
            if cs and cs not in seen:
                seen.add(cs)
                out.append((cs, cs))
        return out

    def complete(self, token: str, limit: int = 8) -> list[tuple[str, str]]:
        """根据当前输入的最后一个 token 给出候选 (标签, 替换值)。"""
        t = (token or "").strip().lower()
        if not t:
            return []
        # 设备型号允许在现场写成 UV-K5 / uv k5 / uv_k5；候选前缀比较
        # 使用同一归一化键，避免搜索能命中但补全列表被标点挡掉。
        device_query = t if any("\u4e00" <= ch <= "\u9fff" for ch in t) else (
            re.sub(r"[^0-9a-z]", "", t) or t
        )
        freq = self._value_frequency()
        out: list[tuple[str, str]] = []
        canon: dict[str, str] = {}  # value -> canonical（排序用；abbr 值映射回标准名）
        seen_label: set[str] = set()

        def qth_value(value: str) -> str:
            return self.full_qth(value)

        def add(label: str, value: str, canonical: str | None = None):
            if label and label not in seen_label:
                seen_label.add(label)
                out.append((label, value))
                canon[value] = canonical or value

        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in t)
        if has_cjk:
            expanded = qth_value(t)
            if expanded and norm_key(expanded) != norm_key(t):
                add(expanded, expanded)
            for k, entries in self.region.by_name.items():
                if k.startswith(t):
                    for e in entries[:1]:
                        full = qth_value(e.display)
                        add(full, full)
            if self.qth_place_service is not None and len(t) >= 2:
                try:
                    places = self.qth_place_service.search(t, limit=max(3, min(limit, 8)))
                except Exception:  # noqa: BLE001
                    places = []
                for place in places:
                    canonical = str(place.get("canonical_qth") or "").strip()
                    name = str(place.get("name") or "").strip()
                    if canonical:
                        label = f"{canonical}（地点：{name}）" if name else canonical
                        add(label, canonical)
        else:
            # 该前缀精确命中的区划（层级优先：城市>区县），如 yz→扬州
            for e in self.region.resolve_initials(t):
                full = qth_value(e.display)
                add(f"{full}（{t}）", full)
            # 更长前缀键：nj → 南京玄武 / 南京栖霞…
            for k, entries in self.region.by_initials.items():
                if k.startswith(t) and k != t:
                    for e in entries[:1]:
                        full = qth_value(e.display)
                        add(f"{full}（{k}）", full)
            for k, a in self.store.qth.items():
                if k.startswith(t):
                    full = qth_value(a.standard_value)
                    add(full, full)
        for kind in ("device", "antenna", "power"):
            d = {"device": self.store.device, "antenna": self.store.antenna,
                 "power": self.store.power}[kind]
            prefix = device_query if kind == "device" else t
            for k, a in d.items():
                if k.startswith(prefix):
                    # 插入缩写 key（如 id52），保证再次解析命中；预览区显示完整标准名
                    add(a.standard_value, k, canonical=a.standard_value)
        # 未核准或旧型号不一定有工信部记录，但如果历史中已经明确
        # 保存过“原始型号 → 标准设备”，就可以提供可审阅的临时缩写。
        # 选择后仍替换为短 key，Parser 会用同一份内存索引解析它。
        for abbreviation, standard in self._observed_device_aliases.items():
            if abbreviation.startswith(device_query):
                add(f"{standard}（历史缩写 {abbreviation}）",
                    abbreviation, canonical=standard)
        # 工信部资料库只提供本地候选。只有“像型号”或明确品牌检索时才查
        # 资料库，避免用户输入南京/道路等 QTH 时每次按键都扫描型号库。
        # 查询使用快速模式，不做几十万条记录的模糊全表评分。
        miit_brands = (
            "泉盛", "全易通", "摩托罗拉", "海能达", "宝锋", "八重洲",
            "艾可慕", "建伍", "威泰克斯", "YAESU", "ICOM", "KENWOOD",
        )
        looks_like_model = bool(
            re.fullmatch(r"[a-z0-9._-]+", t, re.I)
            and re.search(r"[a-z]", t, re.I)
            and re.search(r"\d", t)
        )
        looks_like_brand_search = any(brand.casefold() in t.casefold() for brand in miit_brands)
        if self.miit_catalog is not None and len(t) >= 2 and (
                looks_like_model or looks_like_brand_search):
            try:
                catalog_hits = self.miit_catalog.search(
                    t, limit=max(3, min(limit, 12)), allow_fuzzy=False,
                )
            except TypeError:
                # 兼容旧版资料库/测试替身；正式实现走上面的快速模式。
                try:
                    catalog_hits = self.miit_catalog.search(
                        t, limit=max(3, min(limit, 12)),
                    )
                except Exception:  # noqa: BLE001
                    catalog_hits = []
            except Exception:  # noqa: BLE001
                catalog_hits = []
            for item in catalog_hits:
                model = str(item.get("model") or "").strip()
                standard = str(item.get("standard_name") or model).strip()
                if not model:
                    continue
                detail = str(item.get("device_class") or "电台")
                applicant = str(item.get("applicant") or "").strip()
                suffix = f"；{applicant}" if applicant else ""
                # 接受后直接写入可读规范值，而不是把裸型号（如 ``R6`` /
                # ``PD780``）留在输入框。规范值仍由 Parser 再次校验，且
                # 不会影响本地别名候选（k5/k6 等仍保留短键）。
                add(f"{standard}（工信部{detail}{suffix}）", standard, canonical=standard)
                for abbreviation in model_abbreviations(model):
                    if (abbreviation == norm_key(model)
                            or not abbreviation.startswith(device_query)):
                        continue
                    # 缩写只用于搜索和展示；接受后仍写入完整规范名。
                    add(
                        f"{standard}（缩写 {abbreviation}；工信部{detail}{suffix}）",
                        standard,
                        canonical=standard,
                    )
        # P2：按**标准值**的历史使用频率排序（device/antenna/power 的 value 是缩写 key，
        # 频率表存的是标准值，直接用 value 查会永远为 0）
        out.sort(key=lambda item: -freq.get(canon.get(item[1], item[1]), 0))
        return out[:limit]

    def _value_frequency(self) -> dict[str, int]:
        if not hasattr(self, "_freq_cache"):
            rows = self.repo.as_dict_rows(
                "SELECT field_value, SUM(use_count) c FROM station_profiles "
                "WHERE field_type IN ('qth','device','antenna','power') "
                "GROUP BY field_value")
            self._freq_cache = {r["field_value"]: r["c"] for r in rows}
        return self._freq_cache

    # ---------- 自动生成 QTH 缩写建议（V2.2） ----------
    def suggest_qth_abbr(self, standard_value: str) -> tuple[str, list[str]]:
        """根据标准 QTH 生成拼音首字母缩写；返回 (缩写, 冲突列表)。"""
        from normalizers.region_index import initials as _initials
        sv = (standard_value or "").strip()
        if not sv:
            return "", ["空值"]
        entry = None
        for entries in self.region.by_name.values():
            for e in entries:
                if e.display == sv or self.full_qth(e.display) == sv:
                    entry = e
                    break
            if entry:
                break
        if entry is None:
            return "", ["无法识别该 QTH"]
        parts = [entry.province]
        if entry.city and entry.city != entry.province:
            parts.append(entry.city)
        if entry.district:
            parts.append(entry.district)
        if entry.province == self.settings.get("default_province", "江苏"):
            parts = parts[1:]
        abbr = "".join(_initials(p) for p in parts)
        conflicts = [a.standard_value for a in self.store.qth.values()
                     if a.alias == abbr and a.standard_value != sv]
        return abbr, conflicts

    # ---------- 备份 / 恢复 ----------
    def backup_now(self) -> tuple[bool, str]:
        """手动立即备份；失败必须返回 False 供 UI 提示（不静默）。"""
        try:
            b = backup_daily(self.settings.db_path, self.settings.backup_dir,
                             int(self.settings.get("backup_keep", 30)),
                             config_path=self.settings.path)
        except Exception as e:  # noqa: BLE001
            return False, f"备份失败：{e}"
        if b is None:
            return False, "备份失败（详见日志）"
        return True, f"已备份到 {b.name}"

    def list_backups(self) -> list[dict]:
        from database.db import list_backups
        from database.db import _quick_check_ok
        import sqlite3
        out = []
        for p in list_backups(self.settings.backup_dir):
            ok = False
            try:
                c = sqlite3.connect(str(p))
                try:
                    ok = _quick_check_ok(c)
                finally:
                    c.close()
            except sqlite3.Error:
                ok = False
            out.append({"path": p, "name": p.name, "valid": ok})
        return out

    def restore_backup(self, backup_name: str) -> tuple[bool, str]:
        """从备份恢复数据库（当前连接需先关闭；UI 提示重启生效）。"""
        from database.db import restore_backup
        target = self.settings.backup_dir / backup_name
        if not target.exists():
            return False, f"备份不存在：{backup_name}"
        try:
            self.excel.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
        ok, msg = restore_backup(target, self.settings.db_path)
        # 恢复后重连，保证后续操作可用
        self.conn = connect(self.settings.db_path)
        self.repo = Repository(self.conn)
        if not ok:
            return False, msg
        return True, f"{msg}（建议重启应用）"

    def close(self) -> None:
        # 任务书第二阶段 #25 退出顺序：释放 Excel → 关闭 worker DB → 关闭主 DB。
        self._closed = True
        try:
            self.excel.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.miit_catalog is not None:
                self.miit_catalog.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.qth_place_service is not None:
                self.qth_place_service.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
