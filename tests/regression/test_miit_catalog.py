"""工信部电台资料库：筛选、断点、原子换库和离线检索回归测试。"""
from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import Mock, patch

from database.miit_catalog import MiitCatalogRepository
from providers.miit import MiitProvider, classify_radio_device, model_abbreviations
from services.miit_catalog_service import MiitCatalogSyncService


def _row(article_id: str, name: str, model: str, *, applicant: str = "测试单位",
         extra: str = "") -> dict:
    return {
        "articleId": article_id,
        "articleField01": f"证-{article_id}",
        "articleField02": name,
        "articleField03": model,
        "articleField04": applicant,
        "articleField06": "2030年12月31日",
        "articleField09": "5W",
        "articleField13": f"CODE-{article_id}",
        "articleField14": f"CMIIT-{article_id}",
        "unknownOfficialField": extra,
    }


class _FakeProvider:
    def __init__(self, rows: list[dict], *, reject_above: int | None = None) -> None:
        self.rows = rows
        self.reject_above = reject_above
        self.calls: list[tuple[int, int]] = []

    def fetch_page(self, query: str = "", *, page: int = 1, page_size: int = 1000) -> dict:
        self.calls.append((page, page_size))
        if self.reject_above is not None and page_size > self.reject_above:
            raise RuntimeError(f"分页 {page_size} 被官网拒绝")
        start = (page - 1) * page_size
        return {"total": len(self.rows), "list": self.rows[start:start + page_size]}


class TestMiitRadioClassifier(unittest.TestCase):
    def test_large_page_uses_frontend_five_row_offset(self):
        provider = MiitProvider()
        self.assertEqual(provider.page_number_step(1000), 200)

    def test_provider_fetch_uses_a_reusable_http_session(self):
        provider = MiitProvider()
        try:
            inner = {
                "success": True,
                "data": {"tbAppArticle": {"total": 0, "list": []}},
            }
            response = Mock()
            response.json.return_value = {
                "success": True,
                "data": json.dumps(inner, ensure_ascii=False),
            }
            provider.session.post = Mock(return_value=response)

            result = provider.fetch_page("", page=1, page_size=1000)

            self.assertEqual(result["total"], 0)
            provider.session.post.assert_called_once()
        finally:
            provider.close()

    def test_keeps_radio_terms_and_excludes_non_radio_terms(self):
        keep = [
            "调频手持台",
            "调频手持台（业余业务）",
            "业余手持台",
            "调频手台(业余业务)",
            "调频手持机",
            "调频车载台",
            "公众对讲机",
            "专用对讲机手持台",
            "调频基站",
            "数字对讲系统基站",
            "数字对讲机转发台",
            "调频基地台",
            "中继台",
            "短波单边带电台（业余业务）",
            "短波单边带单台",
            "调频电台",
            "业余无线电设备",
        ]
        exclude = [
            "蓝牙设备",
            "WLAN/蓝牙模块",
            "5G/WLAN/蓝牙终端",
            "GSM/LTE移动电话机",
            "无线通信模块",
            "ZigBee模组",
            "LoRa数据终端",
            "无线路由器",
            "RFID读写器",
            "遥控钥匙",
            "定位终端",
            "无线充电设备",
        ]
        for name in keep:
            self.assertTrue(classify_radio_device(name)[0], name)
        for name in exclude:
            self.assertFalse(classify_radio_device(name)[0], name)

    def test_radio_main_category_wins_over_optional_bluetooth(self):
        keep, device_class, reason = classify_radio_device("调频手持台（带蓝牙）")
        self.assertTrue(keep)
        self.assertEqual(device_class, "手持台")
        self.assertIn("手持台", reason)

    def test_official_model_can_generate_explainable_abbreviations(self):
        self.assertEqual(model_abbreviations("UV-K5")[:2], ("uvk5", "k5"))
        self.assertEqual(model_abbreviations("QYT-6900"), ("qyt6900",))
        self.assertNotIn("uv", model_abbreviations("UV-K5"),
                         "不能把品牌前缀/单独字母当成型号缩写")


class TestMiitCatalogSync(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory(prefix="ham_miit_catalog_")
        self.catalog = MiitCatalogRepository(Path(self.tmp.name) / "miit_radio_catalog.db")

    def tearDown(self) -> None:
        self.catalog.close()
        self.tmp.cleanup()

    def _rows(self) -> list[dict]:
        return [
            _row("1", "调频手持台（业余业务）", "<b>UV-K6</b>", applicant="泉盛电子"),
            _row("2", "蓝牙设备", "K6"),
            _row("3", "暂未分类的无线终端", "UNKNOWN-1", extra="保留原始字段"),
            _row("4", "调频车载台", "QYT-6900", applicant="全易通电子"),
            _row("5", "中继台", "DR-2X", applicant="八重洲"),
            _row("6", "LTE移动电话机", "PHONE-5G"),
            _row("7", "调频基地台（带蓝牙）", "BASE-900", applicant="测试台厂"),
        ]

    def test_full_sync_falls_back_page_size_and_only_persists_radio_records(self):
        provider = _FakeProvider(self._rows(), reject_above=5)
        service = MiitCatalogSyncService(catalog=self.catalog, provider=provider)
        # 测试分页降级，不让重试退避拖慢整个测试；生产服务仍使用退避。
        with patch.object(service, "_wait", return_value=False):
            result = service.sync(full=True, page_size=1000)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 7)
        self.assertEqual(result["retained"], 4)
        self.assertEqual(result["excluded"], 2)
        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["page_size"], 5)
        self.assertEqual(result["completed_pages"], 2)
        self.assertEqual(self.catalog.count(), 4)
        self.assertEqual(self.catalog.quick_check().lower(), "ok")
        self.assertEqual({row["model"] for row in self.catalog.search("K6", limit=3)}, {"UV-K6"})
        self.assertEqual(
            {row["model"] for row in self.catalog.search("QYT-6900", limit=3)},
            {"QYT-6900"},
        )
        self.assertFalse(self.catalog.search("PHONE-5G", limit=3))
        row = self.catalog.search("UNKNOWN-1", limit=3)
        self.assertFalse(row, "未分类记录不能进入本地可用型号库")
        run = self.catalog.status()["run"]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(json.loads(run["unknown_names_json"]), {"暂未分类的无线终端": 1})
        self.assertEqual(provider.calls[-1], (2, 5))
        self.assertEqual(
            self.catalog.search("QYT-6900", limit=1)[0]["miit_sync_run_id"],
            run["sync_id"],
        )
        path = self.catalog.path
        self.catalog.close()
        reopened = MiitCatalogRepository(path)
        try:
            self.assertEqual(reopened.status()["count"], 4)
            self.assertEqual(reopened.status()["scanned_count"], 7)
        finally:
            reopened.close()

    def test_local_model_search_reports_fuzzy_match_without_auto_correction(self):
        provider = _FakeProvider([
            _row("1", "调频手持台（业余业务）", "UV-K6", applicant="泉盛电子"),
        ])
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=5)
        self.assertTrue(result["ok"], result)
        candidates = self.catalog.search("UV-K7", limit=3)
        self.assertEqual(candidates[0]["model"], "UV-K6")
        self.assertEqual(candidates[0]["match_reason"], "型号模糊匹配")

    def test_brand_search_returns_all_models_and_short_model_matches_uv_suffix(self):
        provider = _FakeProvider([
            _row("qs-1", "调频手持台", "UV-K1", applicant="福建泉盛电子有限公司"),
            _row("qs-2", "调频手持台", "UV-K5", applicant="福建泉盛电子有限公司"),
            _row("qs-3", "调频手持台", "UV-K6", applicant="福建泉盛电子有限公司"),
            _row("qs-4", "调频车载台", "QYT-6900", applicant="全易通电子"),
        ])
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=10)
        self.assertTrue(result["ok"], result)

        brand_rows = self.catalog.search("泉盛", limit=20)
        self.assertEqual(
            {row["model"] for row in brand_rows}, {"UV-K1", "UV-K5", "UV-K6"},
        )
        self.assertTrue(all(row["match_reason"] == "品牌/申请单位匹配"
                            for row in brand_rows), brand_rows)

        short_rows = self.catalog.search("K6", limit=20)
        self.assertEqual(short_rows[0]["model"], "UV-K6")
        self.assertEqual(short_rows[0]["match_reason"], "型号后缀匹配")
        abbreviation_rows = self.catalog.abbreviation_matches("K6", limit=20)
        self.assertEqual({row["model"] for row in abbreviation_rows}, {"UV-K6"})

    def test_full_sync_handles_page_without_reported_total(self):
        class _NoTotalProvider(_FakeProvider):
            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                data = super().fetch_page(query, page=page, page_size=page_size)
                data.pop("total", None)
                return data

        rows = self._rows()[:4]
        provider = _NoTotalProvider(rows)
        service = MiitCatalogSyncService(catalog=self.catalog, provider=provider)
        result = service.sync(full=True, page_size=5)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 4)
        self.assertEqual(result["total"], 4)
        self.assertEqual(self.catalog.count(), 2)

    def test_fixed_five_row_server_can_use_large_pages_without_overlap(self):
        class _FixedFiveOffsetProvider(_FakeProvider):
            server_page_size = 5

            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                self.calls.append((page, page_size))
                start = max(0, page - 1) * self.server_page_size
                return {
                    "total": len(self.rows),
                    "list": self.rows[start:start + page_size],
                }

        rows = [
            _row(str(index), "调频手持台", f"UV-{index}")
            for index in range(15)
        ]
        provider = _FixedFiveOffsetProvider(rows)
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=10)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 15)
        self.assertEqual(self.catalog.count(), 15)
        self.assertEqual(provider.calls, [(1, 10), (3, 10)])

    def test_cross_page_duplicate_is_deduped_and_extra_page_recovers_unique_total(self):
        rows = [
            _row(str(index), "调频手持台", f"UV-{index}")
            for index in range(1, 13)
        ]

        class _OverlapProvider:
            def __init__(self) -> None:
                self.calls: list[tuple[int, int]] = []
                self.page_one_calls = 0
                self.pages = {
                    1: rows[0:5],
                    2: [rows[4], *rows[5:9]],
                    3: [rows[8], *rows[9:11]],
                }

            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                self.calls.append((page, page_size))
                if page == 1:
                    self.page_one_calls += 1
                    if self.page_one_calls == 2:
                        # 第 3 页跨页去重后还缺少最后一条；第 4 个绝对
                        # 扫描位置会重新读取第 1 个大页以恢复该缺口。
                        page_rows = [rows[0], rows[1], rows[2], rows[3], rows[11]]
                    else:
                        page_rows = self.pages[1]
                else:
                    page_rows = self.pages.get(page, [])
                return {"total": 12, "list": page_rows}

        provider = _OverlapProvider()
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=5)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 12)
        self.assertEqual(result["completed_pages"], 4)
        self.assertEqual(self.catalog.count(), 12)
        self.assertEqual(provider.calls, [(1, 5), (2, 5), (3, 5), (1, 5)])

    def test_full_sync_follows_a_growing_reported_total(self):
        rows = [
            _row(str(index), "调频车载台", f"QYT-{index}")
            for index in range(1, 13)
        ]

        class _GrowingTotalProvider(_FakeProvider):
            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                self.calls.append((page, page_size))
                total = 7 if page == 1 else 12
                start = (page - 1) * page_size
                return {"total": total, "list": rows[start:start + page_size]}

        provider = _GrowingTotalProvider(rows)
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=5)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["total"], 12)
        self.assertEqual(result["scanned"], 12)
        self.assertEqual(self.catalog.count(), 12)
        self.assertEqual(provider.calls, [(1, 5), (2, 5), (3, 5)])

    def test_corrupt_large_page_falls_back_to_canonical_small_pages(self):
        rows = [
            _row(str(index), "调频车载台", f"QYT-{index}")
            for index in range(1, 21)
        ]

        class _BadLargePageProvider:
            server_page_size = 5
            canonical_page_size = 5

            def __init__(self) -> None:
                self.calls: list[tuple[int, int]] = []

            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                self.calls.append((page, page_size))
                if page_size == 10:
                    # 第二个大页错误地重复了第一页；官方 5 条页仍然
                    # 能提供这个块的正确内容。
                    page_rows = rows[0:10] if page == 1 else rows[0:10]
                else:
                    start = (page - 1) * page_size
                    page_rows = rows[start:start + page_size]
                return {"total": 20, "list": page_rows}

        provider = _BadLargePageProvider()
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=10)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 20)
        self.assertEqual(self.catalog.count(), 20)
        self.assertEqual(provider.calls, [(1, 10), (3, 10), (3, 5), (4, 5)])

    def test_large_anomaly_uses_progressive_chunks_before_five_row_fallback(self):
        rows = [
            _row(str(index), "调频车载台", f"QYT-{index}")
            for index in range(1, 1501)
        ]

        class _ProgressiveProvider:
            server_page_size = 5
            canonical_page_size = 5

            def __init__(self) -> None:
                self.calls: list[tuple[int, int]] = []

            def fetch_page(self, query: str = "", *, page: int = 1,
                           page_size: int = 1000) -> dict:
                self.calls.append((page, page_size))
                if page_size == 1000 and page == 201:
                    # 模拟官网在第二个 1000 条块返回第一页快照；服务应
                    # 用 500 条分块恢复，而不是直接发出 200 个 5 条请求。
                    page_rows = rows[:1000]
                else:
                    start = (page - 1) * self.server_page_size
                    page_rows = rows[start:start + page_size]
                return {"total": len(rows), "list": page_rows}

        provider = _ProgressiveProvider()
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=provider,
        ).sync(full=True, page_size=1000)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["scanned"], 1500)
        self.assertEqual(self.catalog.count(), 1500)
        self.assertEqual(
            provider.calls,
            [(1, 1000), (201, 1000), (201, 500), (301, 500)],
        )

    def test_cancel_preserves_old_snapshot_and_resume_finishes_staging(self):
        old_provider = _FakeProvider([_row("old", "调频手持台", "OLD-1")])
        old_service = MiitCatalogSyncService(catalog=self.catalog, provider=old_provider)
        self.assertTrue(old_service.sync(full=True, page_size=5)["ok"])
        self.assertEqual(self.catalog.count(), 1)

        provider = _FakeProvider(self._rows())
        service = MiitCatalogSyncService(catalog=self.catalog, provider=provider)
        stop = threading.Event()

        def cancel_after_first_page(payload: dict) -> None:
            if payload.get("page") == 1:
                stop.set()

        cancelled = service.sync(
            full=True, page_size=5, stop_event=stop, progress=cancel_after_first_page,
        )
        self.assertFalse(cancelled["ok"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.catalog.count(), 1, "取消不得替换上一份完整快照")
        checkpoint = self.catalog.status()["checkpoint"]
        self.assertEqual(checkpoint["current_page"], 1)
        self.assertEqual(len(self.catalog.sync_seen_ids(checkpoint["sync_id"])), 5)

        resumed = service.sync(full=True, resume=True, page_size=5)
        self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(self.catalog.count(), 4)
        self.assertIsNone(self.catalog.status()["checkpoint"])
        self.assertEqual(self.catalog.status()["run"]["status"], "completed")

    def test_duplicate_article_id_rejects_atomic_swap(self):
        old_provider = _FakeProvider([_row("old", "调频手持台", "OLD-1")])
        self.assertTrue(
            MiitCatalogSyncService(catalog=self.catalog, provider=old_provider)
            .sync(full=True, page_size=5)["ok"]
        )
        duplicate_rows = [
            _row("1", "调频手持台", "NEW-1"),
            _row("1", "调频车载台", "NEW-2"),
        ]
        result = MiitCatalogSyncService(
            catalog=self.catalog, provider=_FakeProvider(duplicate_rows),
        ).sync(full=True, page_size=5)
        self.assertFalse(result["ok"])
        self.assertEqual(self.catalog.count(), 1)
        self.assertEqual(self.catalog.search("OLD-1", limit=3)[0]["model"], "OLD-1")


if __name__ == "__main__":
    unittest.main()
