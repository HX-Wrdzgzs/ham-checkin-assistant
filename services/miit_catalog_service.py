"""工信部电台型号库同步编排器。

网络、分类和 SQLite 交换分层：该服务只负责顺序分页、有限重试、断点和
统计；本地搜索不经过这里，也不会因为用户输入一个型号而联网。
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable

from database.miit_catalog import MiitCatalogRepository
from providers.miit import (
    CATEGORY_ID,
    FILTER_RULE_VERSION,
    MiitProvider,
    MiitQueryError,
    _stable_article_id,
    clean_text,
    classify_radio_device,
    parse_miit_row,
)

ProgressCallback = Callable[[dict], None]


class MiitCatalogSyncError(RuntimeError):
    """同步未完成，正式资料库仍保持上一份完整快照。"""


def _new_id() -> str:
    return f"miit-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


class MiitCatalogSyncService:
    """顺序同步 category 352，并把通过筛选的记录写入独立资料库。"""

    def __init__(self, path=None, *, provider: MiitProvider | None = None,
                 catalog: MiitCatalogRepository | None = None,
                 timeout: float = 20.0) -> None:
        self.catalog = catalog or MiitCatalogRepository(path)
        self.provider = provider or MiitProvider(timeout=timeout)
        self.retry_count = 0
        # 供非 Qt 调用方使用的取消控制；Qt worker 仍可传入自己的 Event，
        # 从而在一个 WorkerManager 中安全隔离多个服务实例。
        self._control_stop_event = threading.Event()

    def status(self) -> dict:
        return self.catalog.status()

    def start_miit_catalog_sync(self, full: bool = True, *,
                                progress: ProgressCallback | None = None,
                                stop_event: threading.Event | None = None,
                                page_size: int = 1000,
                                max_incremental_pages: int = 10) -> dict:
        """开始一次新的同步；首次下载和“重新完整同步”都走这里。

        该入口是同步编排器的明确服务 API。实际执行应放在调用方的后台
        worker 中；本方法本身不会创建线程，也不会让快速录入隐式联网。
        """
        self._control_stop_event.clear()
        return self.sync(
            full=bool(full),
            resume=False,
            progress=progress,
            stop_event=stop_event or self._control_stop_event,
            page_size=page_size,
            max_incremental_pages=max_incremental_pages,
        )

    def resume_miit_catalog_sync(self, *,
                                 progress: ProgressCallback | None = None,
                                 stop_event: threading.Event | None = None,
                                 page_size: int = 1000) -> dict:
        """从最后一个完整页面之后继续完整同步。"""
        self._control_stop_event.clear()
        return self.sync(
            full=True,
            resume=True,
            progress=progress,
            stop_event=stop_event or self._control_stop_event,
            page_size=page_size,
        )

    def cancel_miit_catalog_sync(self) -> None:
        """请求取消当前服务实例的同步；已提交的完整页仍保留为断点。"""
        self._control_stop_event.set()

    @staticmethod
    def _emit(callback: ProgressCallback | None, payload: dict) -> None:
        if callback is not None:
            callback(dict(payload))

    @staticmethod
    def _cancelled(stop_event: threading.Event | None) -> bool:
        return bool(stop_event is not None and stop_event.is_set())

    @staticmethod
    def _wait(stop_event: threading.Event | None, seconds: float) -> bool:
        if stop_event is None:
            time.sleep(seconds)
            return False
        return stop_event.wait(seconds)

    @staticmethod
    def _page_sizes(requested: int) -> list[int]:
        requested = max(5, min(int(requested), 1000))
        lower = [size for size in (1000, 500, 200, 100, 50, 20, 5)
                 if size < requested]
        return list(dict.fromkeys([requested, *lower]))

    def _requested_page_size(self, requested: int) -> int:
        """把请求分页归一到 provider 可接受的分页粒度。"""
        size = max(5, min(int(requested), 1000))
        server_size = int(getattr(self.provider, "server_page_size", 1) or 1)
        if server_size > 1:
            size = max(server_size, (size // server_size) * server_size)
        return size

    def _page_number_step(self, page_size: int) -> int:
        step = getattr(self.provider, "page_number_step", None)
        if callable(step):
            return max(1, int(step(page_size)))
        server_size = int(getattr(self.provider, "server_page_size", 1) or 1)
        if server_size > 1:
            return max(1, int(page_size) // server_size)
        return 1

    def _fetch_page(self, page: int, page_size: int, *, first_page: bool,
                    stop_event: threading.Event | None) -> tuple[dict, int]:
        """有限重试；首个请求被分页大小拒绝时降级到更小分页。"""
        sizes = self._page_sizes(page_size) if first_page else [page_size]
        last_error: Exception | None = None
        for size_index, size in enumerate(sizes):
            for attempt in range(3):
                if self._cancelled(stop_event):
                    raise MiitCatalogSyncError("用户取消了工信部型号库同步")
                try:
                    data = self.provider.fetch_page(
                        "", page=page, page_size=size,
                    )
                    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                        raise MiitQueryError("工信部分页返回格式无法识别")
                    return data, size
                except Exception as exc:  # noqa: BLE001 - worker 会把失败留痕
                    last_error = exc
                    if attempt < 2:
                        self.retry_count += 1
                        if self._wait(stop_event, 0.8 * (2 ** attempt)):
                            raise MiitCatalogSyncError(
                                "用户取消了工信部型号库同步"
                            ) from None
            # 首页尝试过一个大小后降级；不是并发重试，避免轰击官网。
            if size_index + 1 < len(sizes):
                continue
        raise MiitCatalogSyncError(
            f"工信部第 {page} 页读取失败：{last_error or '未知错误'}"
        )

    def _fetch_canonical_block(self, start_page: int, page_size: int,
                               *, stop_event: threading.Event | None) -> dict | None:
        """用官网前端分页粒度拼回一个异常大页。

        当前官网在少数页码上会返回与大 ``pageSize`` 不一致的数据块。先用
        500/200/100/50/20 条的分块逐级降级，最后才回到前端默认的 5 条，
        避免一次异常就产生 200 个串行请求。只有 ``MiitProvider`` 声明了
        canonical_page_size 时才启用这个兜底，普通测试 provider 和未来的
        其他接口不会被强行增加请求次数。
        """
        canonical_size = int(getattr(self.provider, "canonical_page_size", 0) or 0)
        if (canonical_size <= 0 or page_size <= canonical_size
                or page_size % canonical_size):
            return None
        chunk_sizes = [size for size in (500, 200, 100, 50, 20, canonical_size)
                       if canonical_size <= size < page_size
                       and size % canonical_size == 0]
        last_error: Exception | None = None
        for chunk_size in dict.fromkeys(chunk_sizes):
            chunk_count = math.ceil(page_size / chunk_size)
            rows: list[dict] = []
            page_ids: set[str] = set()
            reported_total = 0
            try:
                for offset in range(chunk_count):
                    if self._cancelled(stop_event):
                        raise MiitCatalogSyncError("用户取消了工信部型号库同步")
                    data, _ = self._fetch_page(
                        start_page + offset * (chunk_size // canonical_size),
                        chunk_size,
                        first_page=False, stop_event=stop_event,
                    )
                    total = int(data.get("total") or 0)
                    reported_total = max(reported_total, total)
                    part = [row for row in data.get("list", []) if isinstance(row, dict)]
                    if not part:
                        break
                    for raw in part:
                        article_id = _stable_article_id(raw)
                        if article_id in page_ids:
                            raise MiitCatalogSyncError(
                                f"分块兜底返回重复记录 ID：{article_id}"
                            )
                        page_ids.add(article_id)
                    rows.extend(part)
                    if len(part) < chunk_size:
                        break
                return {"total": reported_total, "list": rows}
            except MiitCatalogSyncError as exc:
                if self._cancelled(stop_event):
                    raise
                # 大分块可能被官网拒绝或在该页返回异常；继续尝试更小的
                # 分块，只有所有粒度都失败才让本页安全失败。
                last_error = exc
                continue
            except Exception as exc:  # noqa: BLE001 - 尝试更小的安全分块
                last_error = exc
                continue
        if last_error is not None:
            raise MiitCatalogSyncError(
                f"工信部异常页分块兜底失败：{last_error}"
            ) from last_error
        return None

    def _page_needs_canonical_recovery(self, rows: list[dict],
                                       reported_total: int, stats: dict) -> bool:
        """判断大页是否明显不是当前连续分页中的这一块。"""
        if not rows:
            return False
        page_ids: set[str] = set()
        has_same_page_duplicate = False
        has_cross_page_overlap = False
        for raw in rows:
            article_id = _stable_article_id(raw)
            if article_id in page_ids:
                has_same_page_duplicate = True
                break
            page_ids.add(article_id)
            if article_id in self._seen_ids:
                has_cross_page_overlap = True
        if has_same_page_duplicate:
            # 同页重复属于硬错误，交给主循环报错，不能通过兜底把坏页吞掉。
            return False
        if has_cross_page_overlap and int(stats.get("scan_cycle", 1) or 1) == 1:
            return True
        expected_total = int(stats.get("total") or 0)
        if not expected_total or not reported_total:
            return False
        # 官网正常新增/撤销少量记录时允许 total 漂移；大幅跳变通常说明
        # 大页来自另一份服务端快照，应该改用官方 5 条分页核对。
        threshold = max(100, math.ceil(expected_total * 0.01))
        return abs(reported_total - expected_total) > threshold

    @staticmethod
    def _stats_from_run(run: dict | None) -> dict:
        run = run or {}
        try:
            unknown = json.loads(run.get("unknown_names_json") or "{}")
        except (TypeError, ValueError):
            unknown = {}
        return {
            "scanned": int(run.get("scanned_count") or 0),
            "retained": int(run.get("retained_count") or 0),
            "excluded": int(run.get("excluded_count") or 0),
            "unknown": int(run.get("unknown_count") or 0),
            "total": int(run.get("total_count") or 0),
            "pages": int(run.get("total_pages") or 0),
            "completed_pages": int(run.get("completed_pages") or 0),
            "unknown_names": Counter({str(k): int(v) for k, v in unknown.items()}),
            "new_or_changed": 0,
        }

    @staticmethod
    def _classify_row(row: dict) -> tuple[dict | None, str, str]:
        name = clean_text(row.get("articleField02"))
        keep, _device_class, reason = classify_radio_device(name)
        parsed = parse_miit_row(row, category_id=CATEGORY_ID)
        if parsed is not None:
            return parsed.to_dict(), "retained", reason
        if name and reason.startswith("排除"):
            return None, "excluded", reason
        return None, "unknown", reason

    def _progress_payload(self, sync_id: str, mode: str, page: int,
                          page_size: int, stats: dict, status: str = "running") -> dict:
        return {
            "sync_id": sync_id,
            "mode": mode,
            "category_id": CATEGORY_ID,
            "filter_rule_version": FILTER_RULE_VERSION,
            "page": page,
            "page_size": page_size,
            "total_pages": stats["pages"],
            "total": stats["total"],
            "scanned": stats["scanned"],
            "completed_pages": stats["completed_pages"],
            "retained": stats["retained"],
            "excluded": stats["excluded"],
            "unknown": stats["unknown"],
            "new_or_changed": stats.get("new_or_changed", 0),
            "scan_cycle": stats.get("scan_cycle", 1),
            "page_in_cycle": stats.get("page_in_cycle", page),
            "retry_count": self.retry_count,
            "status": status,
        }

    def sync(self, *, full: bool = True, resume: bool = True,
             progress: ProgressCallback | None = None,
             stop_event: threading.Event | None = None, page_size: int = 1000,
             max_incremental_pages: int = 10) -> dict:
        """执行完整或快速头部同步，返回可直接展示的统计结果。"""
        self.retry_count = 0
        self._seen_ids: set[str] = set()
        if stop_event is None:
            stop_event = getattr(self, "_control_stop_event", None)
        if not full and self.catalog.get_resume_info(full=True):
            # 增量检查不能清理一个尚未完成的完整快照，否则会破坏用户的
            # 断点续传能力；请先继续或明确点击“重新完整同步”。
            return {
                "ok": False,
                "mode": "incremental",
                "category_id": CATEGORY_ID,
                "filter_rule_version": FILTER_RULE_VERSION,
                "status": "blocked",
                "message": "存在未完成的完整同步断点，请先继续或重新完整同步",
            }
        resume_info = self.catalog.get_resume_info(full=True) if full and resume else None
        if resume_info:
            run = resume_info["run"]
            checkpoint = resume_info["checkpoint"]
            sync_id = str(run["sync_id"])
            run = self.catalog.create_run(
                sync_id, "full", int(checkpoint.get("page_size") or page_size), resume=True,
            )
            start_page = int(checkpoint.get("current_page") or 0) + 1
            effective_size = self._requested_page_size(
                int(checkpoint.get("page_size") or page_size)
            )
            stats = self._stats_from_run(run)
        else:
            sync_id = _new_id()
            mode = "full" if full else "incremental"
            effective_size = self._requested_page_size(page_size)
            run = self.catalog.create_run(sync_id, mode, effective_size, resume=False)
            start_page = 1
            stats = self._stats_from_run(run)

        # 完整同步的断点除了电台暂存记录外，还保存了所有已见过的官网 ID。
        # 官网列表可能在分页期间发生位移；恢复时必须把已扫描过的排除项和
        # 未分类项也纳入去重，否则重启后会把唯一计数算大，掩盖漏页风险。
        if full and resume_info:
            self._seen_ids.update(self.catalog.sync_seen_ids(sync_id))
            # 兼容引入 seen_ids 之前已经存在的旧断点。
            self._seen_ids.update(self.catalog.staging_article_ids(sync_id))

        consecutive_empty = 0
        stable_incremental_pages = 0
        page_step = self._page_number_step(effective_size)
        # 防止服务端异常地重复返回非空页面时无限循环。正常官网总数的
        # 三倍页数已经给官网实时位移留下充足余量；达到上限则安全失败，
        # 不会把不完整快照换成正式库。
        full_page_limit = max(1000, (stats["pages"] or 1) * 3 + 20)
        try:
            page = start_page
            max_pages = None if full else max(1, int(max_incremental_pages))
            while True:
                if self._cancelled(stop_event):
                    raise MiitCatalogSyncError("用户取消了工信部型号库同步")
                if full and page > full_page_limit:
                    raise MiitCatalogSyncError(
                        f"官网分页持续变化，超过安全扫描上限 {full_page_limit} 页"
                    )
                if max_pages is not None and page >= start_page + max_pages:
                    break
                first_page = page == start_page
                # 官网按前端默认 5 条计算 currentPage，即便响应 list 已经是
                # 1000 条；超过理论页数时从第 1 个大页开始补扫，覆盖官网
                # 在同步期间插入/删除记录造成的偏移缺口。``page`` 仍保存
                # 绝对扫描位置，断点续传不会跳过这轮补扫。
                if full and stats["total"]:
                    cycle_pages = max(1, math.ceil(stats["total"] / effective_size))
                    page_in_cycle = ((page - 1) % cycle_pages) + 1
                    stats["scan_cycle"] = ((page - 1) // cycle_pages) + 1
                else:
                    page_in_cycle = page
                    stats["scan_cycle"] = 1
                stats["page_in_cycle"] = page_in_cycle
                request_page = 1 + (page_in_cycle - 1) * page_step
                data, used_size = self._fetch_page(
                    request_page, effective_size, first_page=first_page,
                    stop_event=stop_event,
                )
                if used_size != effective_size:
                    effective_size = used_size
                    page_step = self._page_number_step(effective_size)
                    self.catalog.update_run(sync_id, page_size=effective_size)
                rows = [row for row in data.get("list", []) if isinstance(row, dict)]
                reported_total = int(data.get("total") or 0)
                if full and effective_size > int(
                        getattr(self.provider, "canonical_page_size", 0) or 0
                ) and self._page_needs_canonical_recovery(
                    rows, reported_total, stats,
                ):
                    recovered = self._fetch_canonical_block(
                        request_page, effective_size, stop_event=stop_event,
                    )
                    if recovered is not None:
                        rows = [
                            row for row in recovered.get("list", [])
                            if isinstance(row, dict)
                        ]
                        if recovered.get("total"):
                            reported_total = int(recovered["total"])
                if reported_total:
                    stats["total"] = max(stats["total"], reported_total)
                stats["pages"] = max(1, math.ceil(stats["total"] / effective_size)) if stats["total"] else 1
                if full:
                    full_page_limit = max(
                        full_page_limit, stats["pages"] * 3 + 20,
                    )
                if not rows:
                    consecutive_empty += 1
                    if full and stats["scanned"] < stats["total"]:
                        raise MiitCatalogSyncError(
                            f"第 {page} 页为空，但官网总数为 {stats['total']}，分页不完整"
                        )
                    break
                consecutive_empty = 0

                page_ids: set[str] = set()
                last_article_id = ""
                parsed_rows: list[dict] = []
                page_seen_ids: list[str] = []
                page_new_or_changed = 0
                for raw in rows:
                    article_id = _stable_article_id(raw)
                    if article_id in page_ids:
                        raise MiitCatalogSyncError(
                            f"第 {page} 页返回重复记录 ID：{article_id}"
                        )
                    page_ids.add(article_id)
                    last_article_id = article_id
                    # 跨页重复是官网实时列表位移的可恢复现象：跳过重复行，
                    # 继续抓取后续页，并在最后用唯一 ID 数量做完整性校验。
                    # 同页重复仍在上方直接失败，避免把服务端坏页静默吞掉。
                    if article_id in self._seen_ids:
                        continue
                    self._seen_ids.add(article_id)
                    page_seen_ids.append(article_id)
                    parsed, kind, _reason = self._classify_row(raw)
                    stats["scanned"] += 1
                    if kind == "retained" and parsed is not None:
                        parsed_rows.append(parsed)
                        stats["retained"] += 1
                        if (not full and self.catalog.article_fingerprint(article_id)
                                != str(parsed.get("content_hash") or "")):
                            page_new_or_changed += 1
                    elif kind == "excluded":
                        stats["excluded"] += 1
                    else:
                        stats["unknown"] += 1
                        name = clean_text(raw.get("articleField02")) or "（设备名称为空）"
                        stats["unknown_names"][name] += 1

                if not full:
                    self.catalog.stage_rows(sync_id, parsed_rows)
                    stats["new_or_changed"] += page_new_or_changed
                stats["completed_pages"] = page
                if full:
                    self.catalog.record_full_page(
                        sync_id,
                        parsed_rows,
                        total_count=stats["total"],
                        scanned_count=stats["scanned"],
                        retained_count=stats["retained"],
                        excluded_count=stats["excluded"],
                        unknown_count=stats["unknown"],
                        total_pages=stats["pages"],
                        completed_pages=page,
                        retry_count=self.retry_count,
                        unknown_names_json=json.dumps(
                            dict(stats["unknown_names"]), ensure_ascii=False,
                        ),
                        page_size=effective_size,
                        last_article_id=last_article_id,
                        seen_ids=page_seen_ids,
                    )
                else:
                    self.catalog.update_run(
                        sync_id,
                        total_count=stats["total"], scanned_count=stats["scanned"],
                        retained_count=stats["retained"], excluded_count=stats["excluded"],
                        unknown_count=stats["unknown"], total_pages=stats["pages"],
                        completed_pages=page, retry_count=self.retry_count,
                        unknown_names_json=json.dumps(
                            dict(stats["unknown_names"]), ensure_ascii=False,
                        ),
                        page_size=effective_size,
                    )
                self._emit(progress, self._progress_payload(
                    sync_id, "full" if full else "incremental", page, effective_size, stats,
                ))
                page += 1
                if full and stats["total"]:
                    # 扫描过的唯一官网 ID 达到 total 才允许结束；如果官网
                    # 在分页期间发生位移，下一轮会从第 1 个大页补齐缺口。
                    if stats["scanned"] >= stats["total"]:
                        break
                if full and not stats["total"] and len(rows) < effective_size:
                    break
                if not full and consecutive_empty:
                    break
                if not full:
                    stable_incremental_pages = (
                        stable_incremental_pages + 1 if page_new_or_changed == 0 else 0
                    )
                    # 官网按最新记录倒序返回时，连续几页全部已在正式快照中，
                    # 后面的历史页不必每周重复下载；完整扫描仍负责撤销/删除校验。
                    if stable_incremental_pages >= 3:
                        break

            if full:
                # 官网页面正常会提供 total；若某次响应缺失 total，
                # 以读到的最后短页作为完整边界，而不是只读第一页。
                if not stats["total"]:
                    stats["total"] = stats["scanned"]
                    stats["pages"] = stats["completed_pages"]
                if stats["scanned"] < stats["total"]:
                    raise MiitCatalogSyncError(
                        f"官网扫描不完整：已扫描 {stats['scanned']} / {stats['total']} 条"
                    )
                result = self.catalog.finalize_full_run(
                    sync_id, scanned_count=stats["scanned"], retained_count=stats["retained"],
                    excluded_count=stats["excluded"], unknown_count=stats["unknown"],
                    total_count=stats["total"], total_pages=stats["pages"],
                    completed_pages=stats["completed_pages"], retry_count=self.retry_count,
                    unknown_names=dict(stats["unknown_names"]),
                )
            else:
                result = self.catalog.finish_incremental(
                    sync_id, scanned_count=stats["scanned"], retained_count=stats["retained"],
                    excluded_count=stats["excluded"], unknown_count=stats["unknown"],
                    total_count=stats["total"], total_pages=stats["pages"],
                    completed_pages=stats["completed_pages"], retry_count=self.retry_count,
                    unknown_names=dict(stats["unknown_names"]),
                )
            payload = self._progress_payload(
                sync_id, "full" if full else "incremental", stats["completed_pages"],
                effective_size, stats, status="completed",
            )
            payload.update({"ok": True, "catalog": result, "unknown_names": dict(stats["unknown_names"])})
            self._emit(progress, payload)
            return payload
        except MiitCatalogSyncError as exc:
            status = "cancelled" if "取消" in str(exc) else "failed"
            self.catalog.fail_run(sync_id, status, str(exc))
            payload = self._progress_payload(
                sync_id, "full" if full else "incremental", stats["completed_pages"],
                effective_size, stats, status=status,
            )
            payload.update({"ok": False, "message": str(exc),
                           "unknown_names": dict(stats["unknown_names"])})
            self._emit(progress, payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            self.catalog.fail_run(sync_id, "failed", str(exc))
            payload = self._progress_payload(
                sync_id, "full" if full else "incremental", stats["completed_pages"],
                effective_size, stats, status="failed",
            )
            payload.update({"ok": False, "message": f"同步异常：{exc}",
                           "unknown_names": dict(stats["unknown_names"])})
            self._emit(progress, payload)
            return payload
