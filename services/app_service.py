"""主应用服务：UI 与数据层之间的唯一门面。

UI → AppService → Repository / Provider / ExcelController
SQLite 写入成功后才写 Excel；Excel 失败不影响 SQLite。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config.settings import Settings
from core.logging_setup import get_logger, setup_logging
from core.parser import Parser
from core.predictor import Predictor
from database.db import backup_daily, connect
from database.models import Checkin, ParseResult, Session
from database.repository import Repository
from database.seed import seed_default_aliases
from excel.controller import ExcelController
from excel.exporter import export_session as exporter_export, hhmm
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex
from normalizers.regions import REGIONS
from providers.dt365 import Dt365Provider
from providers.excel_import import ExcelImportProvider
from services.standardizer import Standardizer
from services.sync_service import SyncService

app_log = get_logger("app")

# 设备别名建议：剥离的常见品牌前缀
_BRANDS = ("yaesu", "icom", "kenwood", "anytone", "motorola", "quansheng",
           "baofeng", "wouxun", "vertex", "alincotw", "retvis", "jim")


def _norm(v) -> str:
    return str(v or "").strip()


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
                            ("signal", "signal")):
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
        setup_logging(settings.logs_dir)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        backup_daily(settings.db_path, settings.backup_dir, int(settings.get("backup_keep", 30)))

        self.conn = connect(settings.db_path)
        self.repo = Repository(self.conn)
        seed_default_aliases(self.repo)
        self.store = AliasStore(self.repo)
        self.region = RegionIndex(settings.get("default_province", "江苏"))
        self.predictor = Predictor(self.repo)
        self.parser = Parser(
            self.store, self.region, self.predictor,
            fuzzy_high=float(settings.get("fuzzy_high", 92)),
            fuzzy_mid=float(settings.get("fuzzy_mid", 75)),
            fuzzy_margin=float(settings.get("fuzzy_margin", 5)),
        )
        # 预热解析缓存（模糊选项/频率），避免首键卡顿
        self.parser._qth_fuzzy_options()
        self._value_frequency()
        self.standardizer = Standardizer(self.store, self.region)
        self.excel = ExcelController()
        self.excel_provider = ExcelImportProvider(self.repo)
        self.sync_service = SyncService(
            self.repo,
            Dt365Provider(settings.get("dt365_uid"), max_fetch=int(settings.get("dt365_max_fetch", 60))),
            self.standardizer,
        )
        self._current_session_id: int | None = None
        self._sync_in_progress = False
        app_log.info("AppService ready, db=%s", settings.db_path)

    # ---------- 场次 ----------
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
            name=name or f"第{len(self.repo.list_sessions()) + 1}场点名",
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
        return self.repo.active_sessions()

    def startup_sessions(self) -> list[Session]:
        """启动时读取的已有 active sessions（崩溃残留）。

        正确顺序（任务书第一阶段 #5）：打开 DB → 读已有 active → 崩溃恢复 →
        处理完成 → 仍无 current session 才创建新场次。禁止先建再恢复。
        """
        return self.repo.active_sessions()

    def handle_crash_recovery(self, choice) -> int | None:
        """崩溃恢复决策。choice: 'end_all' / 'defer' / session_id(str)。

        返回恢复的 session_id（或 None）。绝不创建幽灵 active session。
        """
        if choice == "end_all":
            for s in self.repo.active_sessions():
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
        if s is None or s.status != "active":
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
        return self.repo.list_sessions()

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

    # ---------- 解析与提交 ----------
    def parse(self, text: str) -> ParseResult:
        return self.parser.parse(text)

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
        }

    def commit(self, result: ParseResult) -> dict:
        """确认一条记录：SQLite COMMIT 成功后再写 Excel。

        Excel 写入走状态机（任务书第一阶段 #9/#10/#11）：
        写内存(written) → Save(persisted) → 失败则 DB 保持 error/pending。
        只有 Save 成功才把 DB 状态置为 persisted。
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
        c = Checkin(
            session_id=session.id,
            sequence_no=self.repo.allocate_sequence(session.id),
            checkin_time=datetime.now().isoformat(timespec="seconds"),
            callsign=result.callsign.value,
            qth_raw=f["qth"].raw or f["qth"].value, qth_standard=f["qth"].value,
            device_raw=f["device"].raw or f["device"].value, device_standard=f["device"].value,
            antenna_raw=f["antenna"].raw or f["antenna"].value, antenna_standard=f["antenna"].value,
            power_raw=f["power"].raw or f["power"].value, power_standard=f["power"].value,
            signal=f["signal"].value,
            source="local",
            raw_input=result.raw_text,
        )
        dup = self.repo.duplicate_in_session(session.id, c.callsign)
        self.repo.add_checkin(c)
        # station/profile 是 checkins 的投影：按时间重建，避免 count+1 漂移
        self.repo.rebuild_station(c.callsign)
        self.repo.rebuild_profiles_for(c.callsign)
        self._invalidate_runtime_caches()
        app_log.info("committed #%d %s", c.sequence_no, c.callsign)

        # --- Excel：写 → Save → 确认成功 → 才更新 DB 状态 ---
        excel_ok, excel_msg, excel_row, excel_state = True, "未连接 Excel", None, "pending"
        if self.excel.sheet is not None:
            now = datetime.now().isoformat(timespec="seconds")
            write_ok, write_msg, excel_row = self.excel.write(
                self._excel_values(c), auto_save=False)
            if not write_ok:
                excel_ok, excel_msg, excel_state = False, write_msg, "error"
                self.repo.set_excel_state(c.id, "error", row=excel_row,
                                          error=write_msg, binding_id=self.excel.binding_id)
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
                "excel_row": excel_row, "excel_state": excel_state}

    def _invalidate_runtime_caches(self) -> None:
        """统一缓存失效入口（提交/撤销/编辑/导入/同步后调用，任务书第二阶段 #10）。"""
        if hasattr(self, "_freq_cache"):
            del self._freq_cache
        self.parser.invalidate_caches()

    def undo_last(self) -> dict:
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
        excel_msg = "未连接 Excel"
        if self.excel.sheet is not None:
            excel_ok, excel_msg = self.excel_resync()
            if not excel_ok:
                app_log.warning("undo excel resync failed: %s", excel_msg)
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
        """整场重写（撤销/彻底重排后使用）：只清理受管列并重写，之后全部标记 persisted。

        rewrite_all 或 Save 失败时不标记已同步（任务书第一阶段 #7/#11）。
        """
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        checkins = self.repo.list_checkins(session.id)
        self.repo.reset_excel_sync(session.id)
        ok, msg = self.excel.rewrite_all(
            checkins, self._excel_values,
            auto_save=bool(self.settings.get("excel_auto_save", True)))
        if ok:
            self.repo.mark_all_excel_synced(session.id)
        return ok, msg

    def excel_sync_missing(self) -> tuple[bool, str]:
        """补同步：collect pending → 全部写入 → Save → 验证 → 单事务标记 persisted/verified。

        任何一步失败都不得提前把成功状态写入 DB（任务书第一阶段 #12）。
        """
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        if self.excel.sheet is None:
            return False, "未连接 Excel，请先连接"
        unsynced = self.repo.list_unsynced(session.id)
        if not unsynced:
            return True, "没有缺失记录"
        self.excel.reset_next_row()
        now = datetime.now().isoformat(timespec="seconds")
        rows: dict[int, int] = {}
        # 1) 全部写入（不 Save，不提前标成功）
        for c in unsynced:
            ok, msg, row = self.excel.write(self._excel_values(c), auto_save=False)
            if not ok:
                self.repo.set_excel_state(c.id, "error", error=msg,
                                          binding_id=self.excel.binding_id)
                return False, f"补同步失败（#{c.sequence_no} {c.callsign}）：{msg}"
            rows[c.id] = row
        # 2) Save 一次
        save_ok, save_msg = self.excel.save()
        if not save_ok:
            for c in unsynced:
                self.repo.set_excel_state(c.id, "error", error=save_msg,
                                          binding_id=self.excel.binding_id)
            return False, f"Excel 保存失败：{save_msg}"
        # 3) 读回验证写入行（身份校验）
        conflicts = []
        for c in unsynced:
            r = rows.get(c.id)
            if r is None or not self.excel.verify_row_identity(r, c.sequence_no, c.callsign):
                conflicts.append(f"#{c.sequence_no} {c.callsign}")
        if conflicts:
            for c in unsynced:
                self.repo.set_excel_state(c.id, "conflict", row=rows.get(c.id),
                                          error="行身份不匹配", binding_id=self.excel.binding_id)
            return False, "补同步行身份冲突：" + ",".join(conflicts)
        # 4) 单事务标记 persisted
        for c in unsynced:
            self.repo.set_excel_state(c.id, "persisted", row=rows[c.id],
                                      synced_at=now, binding_id=self.excel.binding_id)
        return True, f"已补同步 {len(unsynced)} 条缺失记录"

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
        return self.excel_provider.import_files([Path(p) for p in paths], self.standardizer)

    def import_excel_folder(self, folder: str) -> dict:
        return self.excel_provider.import_folder(Path(folder), self.standardizer)

    def raw_imports(self) -> list:
        return self.repo.list_raw_imports()

    # ---------- 365dt ----------
    def sync_365dt(self, progress=None) -> dict:
        """同一时间只允许一个同步任务（任务书第二阶段 #21）。"""
        if getattr(self, "_sync_in_progress", False):
            return {"ok": False, "message": "同步正在进行，请稍候"}
        self._sync_in_progress = True
        try:
            return self.sync_service.sync_once(progress)
        finally:
            self._sync_in_progress = False

    def sync_state_text(self) -> str:
        st = self.repo.get_sync_state("365dt")
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
        self.parser.invalidate_caches()

    # ---------- 词典管理 ----------
    def get_aliases(self, kind: str):
        return self.repo.get_aliases(kind)

    def set_alias(self, kind: str, alias: str, standard: str, **extra) -> None:
        self.repo.set_alias(kind, alias, standard, **extra)
        self.store.reload()
        self.parser.invalidate_caches()

    def delete_alias(self, kind: str, alias: str) -> None:
        self.repo.delete_alias(kind, alias)
        self.store.reload()
        self.parser.invalidate_caches()

    # ---------- 从导入历史自动生成词典建议（人工确认，不自动写死） ----------
    def suggest_aliases_from_imports(self, min_count: int = 2, limit: int = 100) -> list[dict]:
        """扫描 365dt / Excel 导入历史，从「原始值→标准值」推导别名建议。

        例：device_raw「八重洲 FT-1907R」→ 建议 ft1907r → YAESU FT-1907R
            qth_standard「盐城」→ 建议 yc → 盐城（无冲突时）
        只给「建议」，由用户在界面勾选后加入，绝不自动覆盖。
        """
        rows = self.repo.as_dict_rows(
            """SELECT device_raw, device_standard, qth_standard
               FROM checkins
               WHERE source IN ('365dt','excel_import') AND is_deleted=0""")
        dev: dict[str, dict[str, int]] = {}
        qth_std: dict[str, int] = {}
        for r in rows:
            raw, std = (r["device_raw"] or ""), (r["device_standard"] or "")
            if raw and std:
                # 去掉标点/空格，剥离中英文品牌前缀，再取“字母开头 ≥3 位”代号：
                # 八重洲 FT-857D → FT857D → ft857d
                code = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]", "", raw)
                code = re.sub(r"^[\u4e00-\u9fff]+", "", code)
                low = code.lower()
                for b in _BRANDS:
                    if low.startswith(b) and len(code) > len(b):
                        code = code[len(b):]
                        break
                for tok in re.findall(r"[A-Za-z][A-Za-z0-9]{2,11}", code):
                    key = tok.lower()
                    if key in self.store.device:  # 已有别名，跳过
                        continue
                    dev.setdefault(key, {})
                    dev[key][std] = dev[key].get(std, 0) + 1
            q = r["qth_standard"] or ""
            if q:
                qth_std[q] = qth_std.get(q, 0) + 1

        out: list[dict] = []
        for key, stdmap in dev.items():
            best, best_n = max(stdmap.items(), key=lambda kv: kv[1])
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

    def update_checkin(self, checkin_id: int, field: str, new_value: str) -> dict:
        """修改记录：SQLite + 审计 + Excel 就地更新（先做行身份校验）+ 投影重建。

        修改呼号时按任务书第一阶段 #16：保存 old_callsign → 更新 → 重建旧站/新站
        → 同步 Excel → 审计。
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
        old_callsign = c.callsign
        self.repo.update_checkin(checkin_id, **{target: new_value})
        self.repo.add_audit(checkin_id, field, old, new_value)

        excel_msg = "未连接 Excel"
        if field == "callsign":
            excel_msg = self._update_callsign_excel(c, new_value)
        elif col:
            excel_msg = self._update_field_excel(c, col, new_value)

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
        return {"ok": True, "excel_msg": excel_msg}

    def _update_field_excel(self, c: Checkin, col: str, new_value: str) -> str:
        """就地更新 Excel 行：先验证 row.sequence==sequence_no 且 row.callsign==callsign。

        不匹配 → 搜索唯一匹配 → 唯一才更新；否则标记 conflict 绝不乱写（任务书第一阶段 #8/#9）。
        """
        if self.excel.sheet is None:
            return "未连接 Excel"
        excel_field = self._EXCEL_FIELD.get(col)
        if excel_field is None:
            return ""
        auto = bool(self.settings.get("excel_auto_save", True))
        now = datetime.now().isoformat(timespec="seconds")
        row = c.excel_row
        if row and self.excel.verify_row_identity(row, c.sequence_no, c.callsign):
            ok, msg = self.excel.update_row(row, {excel_field: new_value}, auto_save=auto)
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
        ok, msg = self.excel.update_row(found, {excel_field: new_value}, auto_save=auto)
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
        auto = bool(self.settings.get("excel_auto_save", True))
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
        ok, msg = self.excel.update_row(row, {"callsign": new_value}, auto_save=auto)
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
        if t in self.store.qth or t in self.store.device:
            return True
        if t in self.store.antenna or t in self.store.power:
            return True
        if len(self.region.resolve_initials(t)) == 1:
            return True
        if self.repo.get_station(t.upper()):
            return True
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
        freq = self._value_frequency()
        out: list[tuple[str, str]] = []
        seen_label: set[str] = set()

        def add(label: str, value: str):
            if label and label not in seen_label:
                seen_label.add(label)
                out.append((label, value))

        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in t)
        if has_cjk:
            for k, entries in self.region.by_name.items():
                if k.startswith(t):
                    for e in entries[:1]:
                        add(e.display, e.display)
        else:
            # 该前缀精确命中的区划（层级优先：城市>区县），如 yz→扬州
            for e in self.region.resolve_initials(t):
                add(f"{e.display}（{t}）", e.display)
            # 更长前缀键：nj → 南京玄武 / 南京栖霞…
            for k, entries in self.region.by_initials.items():
                if k.startswith(t) and k != t:
                    for e in entries[:1]:
                        add(f"{e.display}（{k}）", e.display)
            for k, a in self.store.qth.items():
                if k.startswith(t):
                    add(a.standard_value, a.standard_value)
        for kind in ("device", "antenna", "power"):
            d = {"device": self.store.device, "antenna": self.store.antenna,
                 "power": self.store.power}[kind]
            for k, a in d.items():
                if k.startswith(t):
                    # 插入缩写 key（如 id52），保证再次解析命中；预览区显示完整标准名
                    add(a.standard_value, k)
        # 按历史使用频率排序（当前场次出现优先已由“已选呼号”场景覆盖，这里用全局频率）
        out.sort(key=lambda item: -freq.get(item[1], 0))
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
                if e.display == sv:
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

    def close(self) -> None:
        # 任务书第二阶段 #25 退出顺序：释放 Excel → 关闭 worker DB → 关闭主 DB。
        try:
            self.excel.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
