"""工信部“无线电发射设备型号核准”数据客户端与电台筛选规则。

工信部结果查询页包含多个行政许可事项。本模块只请求 ``352``（无线电发射
设备型号核准），并把官网返回的字段转换成稳定的内部记录。筛选发生在内存
中，调用方只有在分类通过后才会把记录写入独立的本地型号库。

这里没有把“搜索官网”混入快速录入：快速录入只应该查询本地资料库；网络
请求由设置页的显式同步或用户主动查询触发。
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass

import requests
from rapidfuzz import fuzz

RESULT_PAGE_URL = "https://ythzxfw.miit.gov.cn/jgcx/index.html"
GATEWAY_URL = (
    "https://ythzxfw.miit.gov.cn/api-gateway/jpaas-jags-server/interface/gateway"
)
_GATEWAY_URL = GATEWAY_URL  # 兼容旧版调用方
CATEGORY_ID = "352"  # 无线电发射设备型号核准
_CATEGORY_ID = CATEGORY_ID  # 兼容旧版测试/调用方
FILTER_RULE_VERSION = "radio-v2"
# 官网前端的 limitPageSize 固定为 5。接口虽然允许返回更大的 list，
# 但 currentPage 的偏移仍按这个单位计算（pageSize=1000 时下一页是 201）。
SERVER_PAGE_SIZE = 5

_TAG_RE = re.compile(r"<[^>]*>")
_NORMALIZE_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")

# “主要设备类别”关键词。顺序影响 device_class 的展示，不影响是否保留。
RADIO_INCLUDE_TERMS: tuple[tuple[str, str], ...] = (
    ("调频手持台", "手持台"),
    ("业余手持台", "手持台"),
    ("调频手台", "手持台"),
    ("业余手台", "手持台"),
    ("调频手持机", "手持台"),
    ("业余手持机", "手持台"),
    ("手持台", "手持台"),
    ("调频车载台", "车载台"),
    ("车载台", "车载台"),
    ("公众对讲机", "对讲机"),
    ("对讲机", "对讲机"),
    ("调频基站", "基地台"),
    ("数字对讲系统基站", "基地台"),
    ("数字对讲机系统基站", "基地台"),
    ("基地台", "基地台"),
    ("固定台", "固定台"),
    ("中继台", "中继台"),
    ("中转台", "中转台"),
    ("转发台", "转发台"),
    ("收发信机", "收发信机"),
    ("短波电台", "短波电台"),
    ("单边带电台", "单边带电台"),
    ("短波单边带单台", "短波电台"),
    ("单边带单台", "短波电台"),
    ("业余无线电设备", "业余无线电设备"),
    ("无线电台", "无线电台"),
    ("调频电台", "无线电台"),
    ("调幅电台", "无线电台"),
    ("调频台", "调频台"),
)

# 这些词单独出现时代表消费电子、数据终端或零部件，不应进入电台库。
RADIO_EXCLUDE_TERMS: tuple[str, ...] = (
    "蓝牙", "bluetooth", "wlan", "wapi", "zigbee", "uwb", "nfc", "rfid",
    "lora", "nb-iot", "nbiot", "lte", "4g", "5g", "gsm",
    "模块", "模组", "芯片", "无线通信模块",
    "移动电话机", "手机", "平板", "笔记本", "路由器", "网关", "热点",
    "遥控器", "无线钥匙", "门禁", "标签", "读写器", "定位终端",
    "数据终端", "物联网终端", "无线充电", "雷达", "广播发射机", "电视发射机",
)

_APPLICANT_BRANDS = (
    ("泉盛", "泉盛"),
    ("全易通", "全易通"),
    ("摩托罗拉", "摩托罗拉"),
    ("motorola", "摩托罗拉"),
    ("motorola solutions", "摩托罗拉"),
    ("艾可慕", "ICOM"),
    ("ICOM", "ICOM"),
    ("八重洲", "YAESU"),
    ("YAESU", "YAESU"),
    ("威泰克斯", "威泰克斯"),
    ("海能达", "海能达"),
    ("hytera", "海能达"),
    ("宝锋", "宝锋"),
    ("baofeng", "宝锋"),
    ("科立讯", "科立讯"),
    ("北峰", "北峰"),
    ("建伍", "KENWOOD"),
    ("KENWOOD", "KENWOOD"),
    ("欧讯", "欧讯"),
    ("灵通", "灵通"),
    ("即时通", "即时通"),
)


class MiitQueryError(RuntimeError):
    """公开查询暂时不可用或返回了无法识别的数据。"""


def clean_text(value) -> str:
    """去掉官网高亮 HTML、全角空格和多余空白，但不丢字段内容。"""
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text).replace("\u3000", " ")
    return " ".join(text.split()).strip()


_clean = clean_text  # 兼容旧版导入


def normalize_model(value: str) -> str:
    """型号比较键：大小写不敏感，忽略空格、连字符、下划线等符号。"""
    return _NORMALIZE_RE.sub("", clean_text(value).lower())


def model_abbreviations(model: str) -> tuple[str, ...]:
    """返回适合现场输入补全的型号缩写。

    只从官方型号本身生成可解释的键：完整型号、连字符后的字母/数字段，
    以及带括号备注前的基础型号。例如 ``UV-K5`` 会得到 ``uvk5`` 和
    ``k5``，``UV-K1(8)`` 会得到 ``uvk18`` 和 ``k1``。不会凭空把品牌、
    功率或相似数字塞进候选。
    """
    text = clean_text(model)
    full = normalize_model(text)
    if not full:
        return ()
    values: list[str] = [full]
    for segment in re.split(r"[-_/\s]+", text):
        segment_key = normalize_model(segment)
        if (len(segment_key) >= 2 and not segment_key.isdigit()
                and re.search(r"\d", segment_key)):
            values.append(segment_key)
        base = re.match(r"^[A-Za-z]+\d+[A-Za-z]*", segment)
        if base:
            base_key = normalize_model(base.group(0))
            if len(base_key) >= 2:
                values.append(base_key)
    return tuple(dict.fromkeys(values))


def _norm(value: str) -> str:
    return normalize_model(value)


def classify_radio_device(device_name: str) -> tuple[bool, str, str]:
    """按官方设备名称分类，返回 ``(是否保留, 类别, 原因)``。

    明确的电台主类别优先于“蓝牙/WLAN”等附加能力描述，例如“调频手持台
    （带蓝牙）”仍然是手持台；只有没有明确电台类别时，排除词才会把记录挡掉。
    """
    name = clean_text(device_name).lower()
    if not name:
        return False, "", "设备名称为空"
    included = next(((term, cls) for term, cls in RADIO_INCLUDE_TERMS if term.lower() in name), None)
    if included:
        term, device_class = included
        return True, device_class, f"命中电台类别：{term}"
    for term in RADIO_EXCLUDE_TERMS:
        if term.lower() in name:
            return False, "", f"排除非电台设备：{term}"
    return False, "", "未命中电台分类规则"


def is_radio_device(device_name: str) -> bool:
    return classify_radio_device(device_name)[0]


def _brand_from(applicant: str, model: str = "") -> str:
    text = f"{clean_text(applicant)} {clean_text(model)}"
    for needle, brand in _APPLICANT_BRANDS:
        if needle.lower() in text.lower():
            return brand
    return ""


def _stable_article_id(row: dict) -> str:
    value = clean_text(row.get("articleId") or row.get("article_id") or row.get("id"))
    if value:
        return value
    # 官网异常缺少 articleId 时仍保证本次记录可去重，但不伪造官网 ID。
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "row-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MiitDeviceResult:
    """官网一条型号核准记录，包含规范字段与原始数据。"""

    model: str
    article_id: str = ""
    category_id: str = CATEGORY_ID
    standard_name: str = ""
    normalized_model: str = ""
    device_name: str = ""
    device_class: str = ""
    applicant: str = ""
    brand: str = ""
    certificate_no: str = ""
    remarks: str = ""
    valid_for: str = ""
    frequency_tolerance: str = ""
    frequency_range: str = ""
    transmit_power: str = ""
    bandwidth: str = ""
    spurious_emission_limit: str = ""
    approved_at: str = ""
    approval_code: str = ""
    cmiit_id: str = ""
    modulation: str = ""
    technical_system: str = ""
    create_time: str = ""
    deleted_flag: str = ""
    display_flag: str = ""
    source_url: str = RESULT_PAGE_URL
    content_hash: str = ""
    filter_rule_version: str = FILTER_RULE_VERSION
    raw_json: str = ""
    score: float = 0.0

    def __post_init__(self) -> None:
        if not self.normalized_model:
            object.__setattr__(self, "normalized_model", normalize_model(self.model))
        if not self.standard_name:
            brand = self.brand or _brand_from(self.applicant, self.model)
            object.__setattr__(
                self, "standard_name", f"{brand} {self.model}".strip() if brand else self.model,
            )

    def to_dict(self) -> dict:
        return asdict(self)


# 计划中的统一数据契约名称；保留 MiitDeviceResult 作为已有调用方的兼容名。
MiitRadioDevice = MiitDeviceResult


def parse_miit_row(row: dict, *, category_id: str = CATEGORY_ID,
                   source_url: str = RESULT_PAGE_URL) -> MiitDeviceResult | None:
    """把官网 articleField01~16 转成完整记录；不符合电台规则返回 None。"""
    if not isinstance(row, dict):
        return None
    cleaned = {str(key): clean_text(value) for key, value in row.items()}
    model = cleaned.get("articleField03", "")
    device_name = cleaned.get("articleField02", "")
    keep, device_class, _reason = classify_radio_device(device_name)
    if not keep or not model:
        return None
    applicant = cleaned.get("articleField04", "")
    brand = _brand_from(applicant, model)
    article_id = _stable_article_id(row)
    raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    return MiitDeviceResult(
        model=model,
        article_id=article_id,
        category_id=category_id,
        standard_name=f"{brand} {model}".strip() if brand else model,
        normalized_model=normalize_model(model),
        device_name=device_name,
        device_class=device_class,
        applicant=applicant,
        brand=brand,
        certificate_no=cleaned.get("articleField01", ""),
        remarks=cleaned.get("articleField05", ""),
        valid_for=cleaned.get("articleField06", ""),
        frequency_tolerance=cleaned.get("articleField07", ""),
        frequency_range=cleaned.get("articleField08", ""),
        transmit_power=cleaned.get("articleField09", ""),
        bandwidth=cleaned.get("articleField10", ""),
        spurious_emission_limit=cleaned.get("articleField11", ""),
        approved_at=cleaned.get("articleField12", ""),
        approval_code=cleaned.get("articleField13", ""),
        cmiit_id=cleaned.get("articleField14", ""),
        modulation=cleaned.get("articleField15", ""),
        technical_system=cleaned.get("articleField16", ""),
        create_time=cleaned.get("createTime", ""),
        deleted_flag=cleaned.get("delFlag", ""),
        display_flag=cleaned.get("resultShowFlag", ""),
        source_url=source_url,
        content_hash=content_hash,
        raw_json=raw_json,
    )


def _signed_params(search_content: str, page: int, page_size: int,
                   *, timestamp: int | None = None,
                   category_id: str = CATEGORY_ID) -> dict:
    """按官网公开页面的参数顺序和 SM3 规则生成请求参数。"""
    biz = {
        "notOnePage": "",
        "categoryId": str(category_id),
        "currentPage": int(page),
        "pageSize": int(page_size),
        "searchContent": search_content,
    }
    params = {
        "app_id": "bjgxb",
        "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        "charset": "UTF-8",
        "interface_id": "queryResultPublicity2",
        "origin": "0",
        "timestamp": int(timestamp if timestamp is not None else time.time() * 1000),
        "version": "1.0",
    }
    payload = "&".join(f"{key}={value}" for key, value in params.items())
    params["sign"] = hashlib.new("sm3", payload.encode("utf-8")).hexdigest()
    return params


def extract_page_data(outer: dict) -> dict:
    """解析官网外层 JSON，保留 list/total 等分页字段。"""
    if not isinstance(outer, dict) or not outer.get("success") or not outer.get("data"):
        raise MiitQueryError("工信部查询服务暂时没有返回结果")
    try:
        inner = json.loads(outer["data"])
        page_data = inner.get("data", {}).get("tbAppArticle")
    except (TypeError, ValueError, AttributeError) as exc:
        raise MiitQueryError("工信部查询返回的数据格式暂时无法识别") from exc
    if not isinstance(inner, dict) or not inner.get("success") or not isinstance(page_data, dict):
        raise MiitQueryError("工信部查询返回的数据格式暂时无法识别")
    rows = page_data.get("list")
    if rows is None:
        rows = page_data.get("records")
    if not isinstance(rows, list):
        raise MiitQueryError("工信部查询返回的数据格式暂时无法识别")
    page_data["list"] = rows
    return page_data


class MiitProvider:
    """工信部型号核准客户端。

    ``search`` 保留给旧版“主动查询”入口；完整资料库同步使用 ``fetch_page``
    逐页读取 category 352，再由 ``parse_miit_row`` 分类落库。
    """

    def __init__(self, timeout: float = 10.0, max_pages: int = 4,
                 category_id: str = CATEGORY_ID) -> None:
        self.timeout = max(2.0, float(timeout))
        self.max_pages = max(1, int(max_pages))
        self.category_id = str(category_id)
        self.server_page_size = SERVER_PAGE_SIZE
        self.canonical_page_size = SERVER_PAGE_SIZE
        # 官网会通过会话 cookie/连接把分页请求路由到相同的数据节点。
        # 每页重新 requests.post 会在全量扫描中混用不同节点，导致 total、
        # 排序和分页边界互相不一致，产生无法恢复的假缺口。
        self.session = requests.Session()

    def close(self) -> None:
        """释放同步 worker 使用的 HTTP 会话。"""
        self.session.close()

    def page_number_step(self, page_size: int) -> int:
        """返回官网 currentPage 为一个大页应前进的步长。"""
        size = max(self.server_page_size, int(page_size))
        return max(1, size // self.server_page_size)

    def search(self, query: str, limit: int = 3) -> list[dict]:
        query = str(query or "").strip()
        if len(query) < 2:
            raise MiitQueryError("型号关键词至少需要 2 个字符")
        if len(query) > 80:
            raise MiitQueryError("型号关键词过长，请只输入品牌或型号")

        page_size = 5
        records: list[dict] = []
        total = 0
        for page in range(1, self.max_pages + 1):
            data = self.fetch_page(query, page, page_size)
            total = int(data.get("total") or 0)
            records.extend(row for row in data.get("list", []) if isinstance(row, dict))
            page_count = max(1, math.ceil(total / page_size)) if total else 1
            if page >= page_count or not data.get("list"):
                break
        ranked = self._rank(query, records)
        return [item.to_dict() for item in ranked[: max(1, min(int(limit), 3))]]

    def fetch_page(self, query: str = "", page: int = 1, page_size: int = 1000) -> dict:
        """读取一页官方结果；重试/退避由同步服务控制。"""
        try:
            response = self.session.post(
                GATEWAY_URL,
                data=_signed_params(query, page, page_size, category_id=self.category_id),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return extract_page_data(response.json())
        except MiitQueryError:
            raise
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            raise MiitQueryError("工信部查询暂时不可用，请稍后重试或打开官网查询") from exc

    def _fetch_page(self, query: str, page: int, page_size: int) -> dict:
        return self.fetch_page(query, page, page_size)

    @staticmethod
    def _rank(query: str, rows: Iterable[dict]) -> list[MiitDeviceResult]:
        query_key = normalize_model(query)
        unique: dict[tuple[str, str, str], MiitDeviceResult] = {}
        for row in rows:
            item = parse_miit_row(row)
            if item is None:
                continue
            model_key = item.normalized_model
            score = float(fuzz.ratio(query_key, model_key))
            if model_key == query_key:
                score += 45
            elif query_key and query_key in model_key:
                score += 28
            if item.device_class in {"手持台", "车载台", "对讲机", "业余无线电设备"}:
                score += 10
            if "业余业务" in item.device_name:
                score += 12
            scored = MiitDeviceResult(**{**item.to_dict(), "score": score})
            key = (scored.normalized_model, scored.applicant, scored.approval_code)
            old = unique.get(key)
            if old is None or scored.score > old.score:
                unique[key] = scored
        return sorted(
            unique.values(),
            key=lambda item: (-item.score, item.normalized_model, item.approved_at),
        )
