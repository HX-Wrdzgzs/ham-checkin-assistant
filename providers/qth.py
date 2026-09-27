"""QTH 可选在线数据源。

地点搜索不能在快速录入热路径偷偷联网。这里提供天地图的显式/后台缓存
接口；调用方必须已经配置用户自己的 tk，结果会先验证结构，再由同步服务
写入独立的本地地点库。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from hashlib import sha256


TIANDITU_SEARCH_URL = "https://api.tianditu.gov.cn/v2/search"
TIANDITU_GEOCODER_URL = "https://api.tianditu.gov.cn/geocoder"
TIANDITU_SOURCE_URL = "https://lbs.tianditu.gov.cn/server/search2.html"
_CHINA_BOUND = "73,3,136,54"


class QthProviderError(RuntimeError):
    """在线地点服务不可用或返回内容不符合预期。"""


class TiandituProvider:
    """天地图地点搜索适配器；不负责写本地数据库。"""

    def __init__(self, token: str, *, timeout: float = 8.0) -> None:
        self.token = str(token or "").strip()
        self.timeout = max(2.0, min(float(timeout), 30.0))

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _get_json(self, url: str, params: dict[str, str]) -> dict:
        if not self.configured:
            raise QthProviderError("未配置天地图 Key")
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{url}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "HAM-checkin-assistant/0.9 (QTH cache)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError,
                json.JSONDecodeError) as exc:
            raise QthProviderError(f"天地图请求失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise QthProviderError("天地图返回格式异常")
        status = str(payload.get("status") or "")
        if status not in ("", "0"):
            raise QthProviderError(str(payload.get("msg") or f"服务状态 {status}"))
        return payload

    @staticmethod
    def _text(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def _join_admin(province: str, city: str, district: str) -> str:
        parts = [str(value or "").strip() for value in (province, city, district)]
        result = ""
        for part in parts:
            if part and not result.endswith(part):
                result += part
        return result

    def search_places(self, keyword: str, *, region: str = "", limit: int = 8) -> list[dict]:
        """搜索 POI/地名并转换为地点库可接受的候选记录。

        这是后台缓存接口，不是输入框联想接口；调用方应限制频率并缓存结果。
        ``region`` 会作为关键字前缀帮助天地图缩小范围，不会把省份写成猜测值。
        """
        keyword = self._text(keyword)
        if len(keyword) < 2:
            return []
        query = keyword
        region = self._text(region)
        if region and region not in query:
            query = f"{region}{query}"
        post = {
            "keyWord": query,
            "level": 12,
            "mapBound": _CHINA_BOUND,
            "queryType": 7,
            "start": 0,
            "count": max(1, min(int(limit), 10)),
        }
        payload = self._get_json(
            TIANDITU_SEARCH_URL,
            {
                "postStr": json.dumps(post, ensure_ascii=False, separators=(",", ":")),
                "type": "query",
                "tk": self.token,
            },
        )
        output: list[dict] = []
        pois = payload.get("pois")
        if not isinstance(pois, list):
            return output
        for index, poi in enumerate(pois):
            if not isinstance(poi, dict):
                continue
            province = self._text(poi.get("province"))
            city = self._text(poi.get("city"))
            district = self._text(poi.get("county") or poi.get("district"))
            if not province or not city or not district:
                # 没有完整行政链的结果只能作为在线候选，不能污染离线库。
                continue
            name = self._text(poi.get("name")) or keyword
            address = self._text(poi.get("address"))
            detail = address or name
            admin = self._join_admin(province, city, district)
            for prefix in (province, city, district, admin):
                if detail.startswith(prefix):
                    detail = detail[len(prefix):].strip()
            canonical = admin + (detail or name)
            stable_id = self._text(
                poi.get("hotPointID") or poi.get("uuid") or poi.get("id")
            )
            if not stable_id:
                stable_id = sha256(
                    f"{province}|{city}|{district}|{name}|{address}".encode()
                ).hexdigest()[:24]
            source_record_id = f"{stable_id}:{index}"
            output.append({
                "place_id": f"tianditu:{stable_id}",
                "name": name,
                "aliases": [keyword, query, address] if address else [keyword, query],
                "province": province,
                "city": city,
                "district": district,
                "canonical_qth": canonical,
                "kind": "tianditu_place",
                "source": "tianditu",
                "source_record_id": source_record_id,
                "source_url": TIANDITU_SOURCE_URL,
                "raw_json": poi,
            })
        return output
