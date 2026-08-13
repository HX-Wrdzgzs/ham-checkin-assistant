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
    """比对 SQLite 本场记录与 Excel 读回数据（P0-6）。返回 (是否一致, 报告文本)。"""
    excel_by_seq: dict[int, dict] = {}
    for row in excel_rows:
        seq = _norm(row.get("sequence"))
        if seq.isdigit():
            excel_by_seq[int(seq)] = row
    lines = [f"SQLite：{len(sqlite_checkins)} 条　Excel：{len(excel_rows)} 行"]
    diffs: list[str] = []
    sqlite_seqs = {c.sequence_no for c in sqlite_checkins}

    for c in sqlite_checkins:
        ex = excel_by_seq.get(c.sequence_no)
        if ex is None:
            diffs.append(f"#{c.sequence_no} {c.callsign}：Excel 缺失")
            continue
        if _norm(ex.get("callsign")).upper() != _norm(c.callsign).upper():
            diffs.append(f"#{c.sequence_no} 呼号不同：SQLite={c.callsign} Excel={ex.get('callsign')}")
        if _norm(ex.get("time")) != _norm(hhmm(c.checkin_time)):
            diffs.append(f"#{c.sequence_no} 时间不同：SQLite={hhmm(c.checkin_time)} Excel={ex.get('time')}")
        for field in ("qth", "device", "antenna", "power"):
            if _norm(ex.get(field)) != _norm(getattr(c, f"{field}_standard")):
                diffs.append(f"#{c.sequence_no} {field.upper()}不同：SQLite={getattr(c, f'{field}_standard')} Excel={ex.get(field)}")

    for seq in sorted(excel_by_seq):
        if seq > 0 and seq not in sqlite_seqs:
            diffs.append(f"#{seq} SQLite 缺失（Excel 多出）")

    if not diffs:
        return True, "\n".join(lines) + "\n\n结果：PASS"
    head = "\n".join(lines) + f"\n\n发现差异（{len(diffs)} 处）："
    return False, head + "\n" + "\n".join(diffs[:40])


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
        app_log.info("AppService ready, db=%s", settings.db_path)

    # ---------- 场次 ----------
    def create_session(self, name: str = "", date: str = "") -> Session:
        session = self.repo.create_session(
            name=name or f"第{len(self.repo.list_sessions()) + 1}场点名",
            date=date or datetime.now().strftime("%Y-%m-%d"),
            operator_callsign=self.settings.get("default_operator_callsign", ""),
            repeater_name=self.settings.get("default_repeater_name", ""),
            excel_path=self.settings.get("excel_template", ""),
        )
        self._current_session_id = session.id
        return session

    def current_session(self) -> Session | None:
        if self._current_session_id is None:
            return None
        return self.repo.get_session(self._current_session_id)

    def set_current_session(self, session_id: int | None) -> None:
        self._current_session_id = session_id

    def active_sessions(self) -> list[Session]:
        return self.repo.active_sessions()

    def all_sessions(self) -> list[Session]:
        return self.repo.list_sessions()

    def end_current_session(self) -> None:
        s = self.current_session()
        if s:
            self.repo.end_session(s.id)

    def list_checkins(self, session_id: int | None = None) -> list[Checkin]:
        sid = session_id or (self.current_session().id if self.current_session() else None)
        if sid is None:
            return []
        return self.repo.list_checkins(sid)

    # ---------- 解析与提交 ----------
    def parse(self, text: str) -> ParseResult:
        return self.parser.parse(text)

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
        """确认一条记录：SQLite COMMIT 成功后再写 Excel。"""
        if not result.callsign.value:
            return {"ok": False, "message": "缺少呼号，无法提交"}
        session = self.current_session()
        if session is None:
            # 无当前场次时自动创建，保证录入不中断
            session = self.create_session()
            app_log.info("auto-created session #%d %s", session.id, session.name)

        f = result.fields()
        c = Checkin(
            session_id=session.id,
            sequence_no=self.repo.next_sequence(session.id),
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
        self.repo.update_profiles_from_checkin(c)
        self.repo.upsert_station_from_checkin(c)
        app_log.info("committed #%d %s", c.sequence_no, c.callsign)

        excel_ok, excel_msg, excel_row = True, "未连接 Excel", None
        if self.excel.sheet is not None:
            excel_ok, excel_msg, excel_row = self.excel.write(
                self._excel_values(c), auto_save=bool(self.settings.get("excel_auto_save", True)))
        if excel_ok and excel_row is not None:
            self.repo.mark_excel_synced(c.id, excel_row)
        return {"ok": True, "checkin": c, "duplicate": dup,
                "excel_ok": excel_ok, "excel_msg": excel_msg}

    def undo_last(self) -> dict:
        session = self.current_session()
        if session is None:
            return {"ok": False, "message": "尚未选择场次"}
        last = self.repo.last_checkin(session.id)
        if last is None:
            return {"ok": False, "message": "没有可撤销的记录"}
        self.repo.soft_delete_checkin(last.id)
        app_log.info("undo #%d %s", last.sequence_no, last.callsign)
        excel_msg = "未连接 Excel"
        if self.excel.sheet is not None:
            _, excel_msg = self.excel_resync()
        return {"ok": True, "checkin": last, "excel_msg": excel_msg}

    # ---------- Excel ----------
    def excel_connect(self, excel_path: str = "", sheet_name: str = "") -> tuple[bool, str]:
        ok, msg = self.excel.connect(
            excel_path or self.settings.get("excel_template", ""),
            sheet_name or self.settings.get("excel_sheet_name", ""),
        )
        if ok:
            self.settings.set("excel_template", self.excel.excel_path)
        return ok, msg

    def excel_resync(self) -> tuple[bool, str]:
        """整场重写（撤销/彻底重排后使用）：清空并重写，之后全部标记已同步。"""
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
        """只补同步尚未写入 Excel 的缺失记录（不重写整场）。"""
        session = self.current_session()
        if session is None:
            return False, "无当前场次"
        if self.excel.sheet is None:
            return False, "未连接 Excel，请先连接"
        unsynced = self.repo.list_unsynced(session.id)
        for c in unsynced:
            ok, msg, row = self.excel.write(self._excel_values(c), auto_save=False)
            if not ok:
                return False, f"补同步失败（#{c.sequence_no} {c.callsign}）：{msg}"
            self.repo.mark_excel_synced(c.id, row)
        if unsynced:
            self.excel.save()
        return True, f"已补同步 {len(unsynced)} 条缺失记录"

    def excel_status_text(self) -> str:
        if self.excel.sheet is None:
            return "○ 未连接"
        try:
            name = self.excel.sheet.Name
        except Exception:  # noqa: BLE001
            name = "?"
        return f"● 已连接：{name}"

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
        return self.sync_service.sync_once(progress)

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
        """修改记录：SQLite + 审计 + Excel 就地更新 + 画像重算（P2-34）。"""
        c = self.repo.get_checkin(checkin_id)
        if c is None:
            return {"ok": False, "message": "记录不存在"}
        col = {"qth": "qth_standard", "device": "device_standard",
               "antenna": "antenna_standard", "power": "power_standard"}.get(field)
        if col is None and field not in ("signal", "callsign"):
            return {"ok": False, "message": "不支持的字段"}
        target = col or field
        old = getattr(c, target, "")
        self.repo.update_checkin(checkin_id, **{target: new_value})
        self.repo.add_audit(checkin_id, field, old, new_value)
        # Excel 就地更新（该记录已同步且行号已知时）
        excel_msg = "未连接 Excel"
        if col and self.excel.sheet is not None and c.excel_row:
            ok, excel_msg = self.excel.update_row(
                c.excel_row, {self._EXCEL_FIELD[col]: new_value},
                auto_save=bool(self.settings.get("excel_auto_save", True)))
        else:
            excel_msg = ""
        # 画像重算该呼号
        if col:
            self.repo.refresh_station_profiles_for(c.callsign)
            self.repo.upsert_station_from_checkin(self.repo.get_checkin(checkin_id))
        return {"ok": True, "excel_msg": excel_msg}

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
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
