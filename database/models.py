"""数据模型：与表结构对应的 dataclass。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Session:
    id: int | None = None
    name: str = ""
    date: str = ""
    operator_callsign: str = ""
    repeater_name: str = ""
    started_at: str = ""
    ended_at: str = ""
    excel_path: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Checkin:
    id: int | None = None
    session_id: int = 0
    sequence_no: int = 0
    checkin_time: str = ""
    callsign: str = ""
    qth_raw: str = ""
    qth_standard: str = ""
    device_raw: str = ""
    device_standard: str = ""
    antenna_raw: str = ""
    antenna_standard: str = ""
    power_raw: str = ""
    power_standard: str = ""
    signal: str = ""
    source: str = "local"
    raw_input: str = ""
    source_record_id: str = ""
    source_url: str = ""
    is_deleted: int = 0
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    excel_synced: int = 0
    excel_row: int | None = None


@dataclass
class StationProfile:
    callsign: str = ""
    field_type: str = ""  # qth/device/antenna/power
    field_value: str = ""
    use_count: int = 0
    last_used: str = ""


@dataclass
class Alias:
    id: int | None = None
    alias: str = ""
    standard_value: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    priority: int = 100
    enabled: int = 1
    source: str = "default"


@dataclass
class RawImport:
    id: int | None = None
    source: str = ""
    source_file: str = ""
    sheet_name: str = ""
    row_number: int = 0
    raw_json: str = ""
    record_hash: str = ""
    imported_at: str = ""


@dataclass
class SyncState:
    source: str = ""
    source_uid: str = ""
    last_check_at: str = ""
    last_success_at: str = ""
    last_record_id: str = ""
    last_session_id: str = ""
    last_hash: str = ""
    status: str = ""
    error_message: str = ""


@dataclass
class AuditEntry:
    id: int | None = None
    record_id: int = 0
    field_name: str = ""
    old_value: str = ""
    new_value: str = ""
    changed_at: str = ""


@dataclass
class ParseField:
    """Parser 单个字段结果。source: input/alias/history_recent/history_frequent/fuzzy/manual"""
    value: str = ""
    source: str = ""
    confidence: float = 0.0
    candidates: list[str] = field(default_factory=list)
    raw: str = ""  # 用户输入的原始 token


@dataclass
class ParseResult:
    raw_text: str = ""
    tokens: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    callsign: ParseField = field(default_factory=ParseField)
    qth: ParseField = field(default_factory=ParseField)
    device: ParseField = field(default_factory=ParseField)
    antenna: ParseField = field(default_factory=ParseField)
    power: ParseField = field(default_factory=ParseField)
    signal: ParseField = field(default_factory=ParseField)
    # 历史建议（呼号已知时）
    history: dict = field(default_factory=dict)

    def fields(self):
        return {
            "callsign": self.callsign,
            "qth": self.qth,
            "device": self.device,
            "antenna": self.antenna,
            "power": self.power,
            "signal": self.signal,
        }
