"""QTH 地点库后台同步。

每次同步先用程序内置行政区生成可验证的本地快照，再可选地从用户配置的
地点包和天地图缓存少量已出现的地址。失败时只保留旧的远程记录；快速录入
始终只查 SQLite，不等待网络。
"""
from __future__ import annotations

import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from normalizers.region_index import initials
from normalizers.regions import REGIONS
from providers.qth import QthProviderError, TiandituProvider


SYNC_VERSION = "qth-sync-v1"
BUILTIN_SOURCE = "builtin-region"
REMOTE_PACK_SOURCE = "remote-pack"

_PROVINCE_SUFFIXES = ("省", "自治区", "特别行政区", "市")
_CITY_SUFFIXES = ("市", "地区", "盟", "自治州")
_DISTRICT_SUFFIXES = ("区", "县", "市", "旗", "林区")


def _text(value) -> str:
    return str(value or "").strip()


def _province_full(name: str) -> str:
    if name in {"北京", "天津", "上海", "重庆"}:
        return f"{name}市"
    if name in {"内蒙古", "广西", "西藏", "宁夏", "新疆"}:
        return {
            "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区",
            "西藏": "西藏自治区", "宁夏": "宁夏回族自治区",
            "新疆": "新疆维吾尔自治区",
        }[name]
    if name in {"香港", "澳门"}:
        return f"{name}特别行政区"
    return name if name.endswith(_PROVINCE_SUFFIXES) else f"{name}省"


def _city_full(name: str) -> str:
    if not name:
        return ""
    return name if name.endswith(_CITY_SUFFIXES) else f"{name}市"


def _district_full(name: str, province: str) -> str:
    if not name:
        return ""
    if name.endswith(_DISTRICT_SUFFIXES):
        return name
    # 与现有补全引擎保持同一套江苏县级市规则，避免启动同步后同一地点
    # 在“地点库”和“行政区索引”显示不同。
    jiangsu_cities = {
        "新沂", "邳州", "东台", "仪征", "高邮", "靖江", "泰兴", "兴化",
        "启东", "如皋", "海安", "丹阳", "扬中", "句容", "溧阳", "江阴",
        "宜兴", "常熟", "张家港", "昆山", "太仓",
    }
    if province == "江苏" and name in jiangsu_cities:
        return f"{name}市"
    return f"{name}区"


def builtin_region_records() -> list[dict]:
    """把当前随程序发布的行政区索引同步为地点库来源。"""
    records: list[dict] = []
    for province, cities in REGIONS.items():
        province_full = _province_full(province)
        records.append({
            "place_id": f"region:{province}",
            "name": province_full,
            "aliases": [province, province_full],
            "province": province_full,
            "canonical_qth": province_full,
            "kind": "admin_region",
            "source": BUILTIN_SOURCE,
            "source_record_id": province,
        })
        for city, districts in cities.items():
            if city == province:
                city_full = ""
                city_canonical = province_full
            else:
                city_full = _city_full(city)
                city_canonical = province_full + city_full
            records.append({
                "place_id": f"region:{province}:{city}",
                "name": city_full or province_full,
                "aliases": [city, city_full or province_full, initials(city)],
                "province": province_full,
                "city": city_full,
                "canonical_qth": city_canonical,
                "kind": "admin_region",
                "source": BUILTIN_SOURCE,
                "source_record_id": f"{province}:{city}",
            })
            for district in districts:
                district_full = _district_full(district, province)
                canonical = city_canonical + district_full
                records.append({
                    "place_id": f"region:{province}:{city}:{district}",
                    "name": district_full,
                    "aliases": [district, district_full, initials(city + district)],
                    "province": province_full,
                    "city": city_full,
                    "district": district_full,
                    "canonical_qth": canonical,
                    "kind": "admin_region",
                    "source": BUILTIN_SOURCE,
                    "source_record_id": f"{province}:{city}:{district}",
                })
    return records


class QthPlaceSyncService:
    """在独立 QthPlaceCatalog 连接中执行可回滚的后台同步。"""

    def __init__(self, catalog, *, default_province: str = "江苏") -> None:
        self.catalog = catalog
        self.default_province = _text(default_province) or "江苏"

    def _set_status(self, status: str, message: str) -> None:
        values = {
            "sync_version": SYNC_VERSION,
            "last_sync_at": datetime.now().isoformat(timespec="seconds"),
            "last_sync_status": status,
            "last_sync_message": message,
        }
        if status == "completed":
            values["last_success_at"] = values["last_sync_at"]
        self.catalog.set_meta_many(values)

    @staticmethod
    def _download_pack(url: str, *, etag: str = "", last_modified: str = "",
                       timeout: float = 20.0, max_bytes: int = 100 * 1024 * 1024) -> tuple[int, bytes, dict]:
        parsed = urllib.parse.urlparse(_text(url))
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise QthProviderError("地点包地址必须是 HTTPS")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, application/x-ndjson, text/csv",
                "User-Agent": "HAM-checkin-assistant/0.9 (QTH catalog sync)",
            },
        )
        if etag:
            request.add_header("If-None-Match", etag)
        if last_modified:
            request.add_header("If-Modified-Since", last_modified)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise QthProviderError("地点包超过 100 MB 安全限制")
                return int(response.getcode() or 200), body, headers
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return 304, b"", {}
            raise QthProviderError(f"地点包下载失败：HTTP {exc.code}") from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise QthProviderError(f"地点包下载失败：{exc}") from exc

    def _import_remote_pack(self, url: str) -> tuple[int, str]:
        etag = self.catalog.get_meta("remote_etag")
        last_modified = self.catalog.get_meta("remote_last_modified")
        code, body, headers = self._download_pack(
            url, etag=etag, last_modified=last_modified,
        )
        if code == 304:
            return 0, "远程地点包无变化"
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jsonl"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    prefix="ham-qth-pack-", suffix=suffix, delete=False) as stream:
                stream.write(body)
                tmp_path = Path(stream.name)
            count = self.catalog.replace_file(tmp_path, source=REMOTE_PACK_SOURCE)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        self.catalog.set_meta_many({
            "remote_url": url,
            "remote_etag": headers.get("etag", ""),
            "remote_last_modified": headers.get("last-modified", ""),
        })
        return count, f"远程地点包更新 {count} 条"

    def sync(self, *, remote_url: str = "", tianditu_token: str = "",
             queries: list[str] | None = None, stop_event=None,
             max_online_queries: int = 5, progress=None) -> dict:
        """执行一次同步；所有远程数据都经过本地事务写入。

        ``queries`` 只允许来自用户已经输入/保存过的 QTH，默认最多缓存五个，
        天地图请求之间由 provider 调用方控制；不做全国 POI 批量抓取。
        """
        if stop_event is not None and stop_event.is_set():
            self._set_status("cancelled", "同步已取消")
            return {"ok": False, "status": "cancelled", "message": "同步已取消"}
        builtin_count = self.catalog.replace_source(
            builtin_region_records(), source=BUILTIN_SOURCE,
        )
        details = [f"内置行政区 {builtin_count} 条"]
        remote_count = 0
        online_count = 0
        try:
            if _text(remote_url):
                remote_count, remote_message = self._import_remote_pack(_text(remote_url))
                details.append(remote_message)
            provider = TiandituProvider(tianditu_token)
            unique_queries = list(dict.fromkeys(_text(item) for item in (queries or []) if _text(item)))
            for query in unique_queries[:max(0, int(max_online_queries))]:
                if stop_event is not None and stop_event.is_set():
                    self._set_status("cancelled", "同步已取消，旧地点记录保持不变")
                    return {"ok": False, "status": "cancelled", "message": "同步已取消"}
                if not provider.configured:
                    break
                rows = provider.search_places(
                    query, region=self.default_province, limit=5,
                )
                if rows:
                    online_count += self.catalog.upsert_many(rows, default_source="tianditu")
            if online_count:
                details.append(f"天地图缓存 {online_count} 条")
            if not _text(remote_url) and not provider.configured:
                details.append("未配置远程地点包或天地图 Key")
            message = "；".join(details)
            self._set_status("completed", message)
            if progress is not None:
                progress({"stage": "completed", "message": message})
            return {
                "ok": True, "status": "completed", "builtin": builtin_count,
                "remote": remote_count, "online": online_count,
                "message": message, "status_payload": self.catalog.status(),
            }
        except Exception as exc:  # noqa: BLE001
            # 内置行政区已经是一次完整事务；远程失败不会清掉旧远程来源。
            message = f"{exc}；已保留上次可用地点库"
            self._set_status("failed", message)
            return {
                "ok": False, "status": "failed", "builtin": builtin_count,
                "remote": remote_count, "online": online_count,
                "message": message, "status_payload": self.catalog.status(),
            }
