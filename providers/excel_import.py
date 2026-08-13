"""Excel 历史批量导入：单文件/多文件/整个文件夹。

去重：file_hash + sheet_name + row_number（raw_imports UNIQUE 约束）+ record_hash。
同一文件重复导入不会产生重复记录。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook

from database.models import Checkin, RawImport
from database.repository import Repository
from excel import template
from excel.exporter import hhmm
from providers.base import DataProvider


class ExcelImportProvider(DataProvider):
    name = "excel_import"

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def check_updates(self) -> dict:
        return {"has_new": False}

    def fetch_records(self) -> list[dict]:
        return []

    def normalize_record(self, raw: dict) -> dict:
        return raw

    # ---------- 导入 ----------
    def import_file(self, path: Path, standardizer=None) -> tuple[int, int, str]:
        """返回 (导入数, 跳过数, 说明)。"""
        path = Path(path)
        if not path.exists():
            return 0, 0, "文件不存在"
        fh = self.repo.file_hash(str(path))
        if self._file_imported(fh):
            return 0, 0, "该文件已导入过（已跳过）"

        wb = load_workbook(path, data_only=True, read_only=True)
        rows: list[dict] = []
        first_date = ""
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            data = [[c.value for c in row] for row in ws.iter_rows()]
            header_idx, mapping = template.find_header_row(data)
            if header_idx is None or not mapping.get("callsign"):
                continue
            for ri in range(header_idx + 1, len(data)):
                row_vals = data[ri]
                rec = self._row_to_record(mapping, row_vals, fh, sheet_name, ri)
                if rec is None:
                    continue
                if not first_date:
                    first_date = rec.get("date", "")
                rows.append(rec)
        wb.close()
        if not rows:
            return 0, 0, "未识别到有效数据行"

        date = self._guess_date(path, rows, first_date)
        session = self.repo.create_session(
            name=path.stem, date=date, repeater_name="历史导入"
        )
        imported = 0
        for rec in rows:
            checkin = self._build_checkin(session.id, rec, standardizer)
            seq = self.repo.next_sequence(session.id)
            checkin.sequence_no = seq
            self.repo.add_checkin(checkin)
            self.repo.update_profiles_from_checkin(checkin)
            self.repo.upsert_station_from_checkin(checkin)
            imported += 1
        self.repo.end_session(session.id)
        return imported, len(rows) - imported, f"导入 {imported} 条"

    def import_files(self, paths: Iterable[Path], standardizer=None) -> dict[str, tuple[int, int, str]]:
        out = {}
        for p in paths:
            try:
                out[str(p)] = self.import_file(Path(p), standardizer)
            except Exception as e:  # noqa: BLE001
                out[str(p)] = (0, 0, f"失败：{e}")
        return out

    def import_folder(self, folder: Path, standardizer=None) -> dict[str, tuple[int, int, str]]:
        files = sorted(folder.glob("*.xlsx")) + sorted(folder.glob("*.xls"))
        return self.import_files(files, standardizer)

    # ---------- 内部 ----------
    def _file_imported(self, fh: str) -> bool:
        return self.repo.file_imported("excel_import", fh)

    def _row_to_record(self, mapping: dict, row_vals: list, fh: str, sheet: str, ri: int) -> dict | None:
        def get(field: str) -> str:
            col = mapping.get(field)
            if col is None or col >= len(row_vals):
                return ""
            v = row_vals[col]
            return str(v).strip() if v is not None else ""

        callsign = get("callsign")
        if not callsign:
            return None
        rec = {
            "callsign": callsign,
            "time": get("time"),
            "qth": get("qth"),
            "device": get("device"),
            "antenna": get("antenna"),
            "power": get("power"),
            "signal": get("signal"),
            "date": get("date"),
            "raw_json": json.dumps({k: get(k) for k in
                                    ("sequence", "time", "callsign", "qth", "device", "antenna", "power", "signal")},
                                   ensure_ascii=False),
        }
        rec["record_hash"] = self.repo.record_hash(
            "excel_import", fh, sheet, str(ri), rec["raw_json"])
        # 登记原始数据（UNIQUE 去重）
        self.repo.record_import(RawImport(
            source="excel_import", source_file=fh, sheet_name=sheet,
            row_number=ri, raw_json=rec["raw_json"], record_hash=rec["record_hash"],
        ))
        return rec

    @staticmethod
    def _guess_date(path: Path, rows: list[dict], first_date: str) -> str:
        if first_date:
            return first_date
        m = re.search(r"(\d{4}[-_.]?\d{2}[-_.]?\d{2})", path.stem)
        if m:
            return m.group(1).replace("_", "-").replace(".", "-")
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")

    def _build_checkin(self, session_id: int, rec: dict, standardizer) -> Checkin:
        now = datetime.now().isoformat(timespec="seconds")
        c = Checkin(
            session_id=session_id,
            checkin_time=rec.get("time") or now,
            callsign=(rec.get("callsign") or "").upper(),
            qth_raw=rec.get("qth", ""), device_raw=rec.get("device", ""),
            antenna_raw=rec.get("antenna", ""), power_raw=rec.get("power", ""),
            signal=rec.get("signal", ""),
            source="excel_import",
            raw_input=rec.get("raw_json", ""),
            source_record_id=rec.get("record_hash", ""),
            source_url=str(rec.get("source_url", "")),
        )
        if standardizer:
            c.qth_standard = standardizer.standardize("qth", c.qth_raw) or c.qth_raw
            c.device_standard = standardizer.standardize("device", c.device_raw) or c.device_raw
            c.antenna_standard = standardizer.standardize("antenna", c.antenna_raw) or c.antenna_raw
            c.power_standard = standardizer.standardize("power", c.power_raw) or c.power_raw
        else:
            c.qth_standard = c.qth_raw
            c.device_standard = c.device_raw
            c.antenna_standard = c.antenna_raw
            c.power_standard = c.power_raw
        return c
