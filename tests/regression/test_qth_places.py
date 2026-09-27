from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from unittest.mock import patch

from database.qth_places import QthPlaceCatalog
from services.qth_place_sync_service import QthPlaceSyncService
from tests.helpers import make_service


class TestQthPlaceCatalogIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = make_service()

    def tearDown(self) -> None:
        self.svc.close()

    def _install_places(self) -> None:
        self.svc.qth_place_catalog.upsert_many([
            {
                "place_id": "road-nanjing-zhongshan-169",
                "name": "中山路169号",
                "aliases": ["中山路", "中山路一六九号"],
                "province": "江苏省",
                "city": "南京市",
                "district": "鼓楼区",
                "canonical_qth": "江苏省南京市鼓楼区中山路169号",
                "kind": "road_address",
                "source": "fixture",
            },
        ])

    def test_exact_road_resolves_to_full_admin_chain_and_keeps_raw(self):
        self._install_places()
        self.svc.create_session("地点测试", "2026-09-05")
        result = self.svc.parse("ba4aaa 中山路169号")
        self.assertEqual(result.qth.value, "江苏省南京市鼓楼区中山路169号")
        self.assertEqual(result.qth.source, "place")
        self.assertEqual(result.unmatched, [])

        committed = self.svc.commit(result, save_excel=False)
        checkin = self.svc.repo.get_checkin(committed["checkin"].id)
        self.assertEqual(checkin.qth_raw, "中山路169号")
        self.assertEqual(checkin.qth_standard, "江苏省南京市鼓楼区中山路169号")

    def test_mixed_admin_abbreviation_keeps_address_tail(self):
        self.svc.create_session("混合地址测试", "2026-09-05")
        result = self.svc.parse("ba4aaa njgl中山路169号")
        self.assertEqual(result.qth.value, "南京鼓楼中山路169号")
        self.assertEqual(result.unmatched, [])
        self.assertEqual(
            self.svc.full_qth(result.qth.value, result.qth.raw),
            "江苏省南京市鼓楼区中山路169号",
        )

    def test_same_road_name_is_candidate_not_silent_choice(self):
        self.svc.qth_place_catalog.upsert_many([
            {
                "place_id": "road-1", "name": "人民路", "aliases": [],
                "province": "江苏省", "city": "南京市", "district": "鼓楼区",
                "canonical_qth": "江苏省南京市鼓楼区人民路", "source": "fixture",
            },
            {
                "place_id": "road-2", "name": "人民路", "aliases": [],
                "province": "安徽省", "city": "芜湖市", "district": "镜湖区",
                "canonical_qth": "安徽省芜湖市镜湖区人民路", "source": "fixture",
            },
        ])
        result = self.svc.parse("ba4aaa 人民路")
        self.assertNotEqual(result.qth.source, "place")
        self.assertEqual(result.qth.value, "人民路")
        self.assertEqual(result.unmatched, [])
        candidates = self.svc.search_qth_places("人民路", limit=5)
        self.assertEqual(
            {item["canonical_qth"] for item in candidates},
            {"江苏省南京市鼓楼区人民路", "安徽省芜湖市镜湖区人民路"},
        )

    def test_miit_completion_inserts_canonical_brand_model(self):
        class _Catalog:
            def search(self, query, limit=3, **kwargs):
                if str(query).casefold() == "r6":
                    return [{
                        "model": "R6",
                        "standard_name": "摩托罗拉 R6",
                        "device_class": "手持台",
                        "applicant": "Motorola Solutions",
                    }]
                return []

        self.svc.miit_catalog = _Catalog()
        self.svc.parser.radio_catalog = self.svc.miit_catalog
        self.svc.completion_engine.catalog = self.svc.miit_catalog
        hits = self.svc.complete("r6")
        self.assertTrue(
            any("摩托罗拉 R6" in label and value == "摩托罗拉 R6"
                for label, value in hits),
            hits,
        )

    def test_short_unapproved_branded_model_is_canonical_and_learns_abbreviation(self):
        """品牌已明确时，未内置的短型号也要保留品牌并学习裸缩写。"""
        self.svc.create_session("短型号测试", "2026-09-05")
        compact = self.svc.parse("ba4aac 摩托罗拉X6200")
        self.assertEqual(compact.device.value, "摩托罗拉 X6200")
        self.assertEqual(compact.device.source, "input")
        self.assertEqual(compact.unmatched, [])

        first = self.svc.parse("ba4aaa 摩托罗拉 X6200")
        self.assertEqual(first.device.value, "摩托罗拉 X6200")
        self.assertEqual(first.device.source, "input")
        self.assertEqual(first.unmatched, [])

        committed = self.svc.commit(first, save_excel=False)
        self.assertTrue(committed["ok"])

        second = self.svc.parse("ba4bbb x6200")
        self.assertEqual(second.device.value, "摩托罗拉 X6200")
        self.assertEqual(second.device.source, "observed_alias")
        self.assertEqual(second.unmatched, [])

    def test_fast_commit_does_not_touch_connected_excel(self):
        self.svc.create_session("Excel 热路径测试", "2026-09-05")
        result = self.svc.parse("ba4aaa njxw k6 y 5")
        self.svc.excel.sheet = object()
        self.svc.excel.write = Mock()
        response = self.svc.commit(result, save_excel=False)
        self.assertTrue(response["ok"])
        self.svc.excel.write.assert_not_called()

    def test_background_sync_installs_builtin_admin_aliases(self):
        """后台同步后，njxw 应能离线展开成完整省市区。"""
        with TemporaryDirectory(prefix="ham_qth_sync_") as temp:
            catalog = QthPlaceCatalog(Path(temp) / "qth.db")
            try:
                result = QthPlaceSyncService(catalog).sync()
                self.assertTrue(result["ok"], result)
                self.assertGreater(result["builtin"], 0)
                place = catalog.resolve_unique("njxw")
                self.assertIsNotNone(place)
                self.assertEqual(place["canonical_qth"], "江苏省南京市玄武区")
                self.assertEqual(catalog.quick_check(), "ok")
            finally:
                catalog.close()

    def test_background_sync_caches_explicit_tianditu_results_locally(self):
        """天地图只在后台被调用，结果写入独立地点库供后续离线使用。"""
        fake_rows = [{
            "place_id": "tianditu:test-road",
            "name": "中山路169号",
            "aliases": ["中山路169号"],
            "province": "江苏省",
            "city": "南京市",
            "district": "玄武区",
            "canonical_qth": "江苏省南京市玄武区中山路169号",
            "kind": "tianditu_place",
        }]
        with TemporaryDirectory(prefix="ham_qth_sync_") as temp:
            catalog = QthPlaceCatalog(Path(temp) / "qth.db")
            try:
                with patch(
                        "services.qth_place_sync_service.TiandituProvider.search_places",
                        return_value=fake_rows) as search:
                    result = QthPlaceSyncService(catalog).sync(
                        tianditu_token="test-token",
                        queries=["中山路169号"],
                        max_online_queries=1,
                    )
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["online"], 1)
                search.assert_called_once()
                place = catalog.resolve_unique("中山路169号")
                self.assertIsNotNone(place)
                self.assertEqual(
                    place["canonical_qth"], "江苏省南京市玄武区中山路169号"
                )
            finally:
                catalog.close()

    def test_broken_remote_pack_keeps_previous_remote_snapshot(self):
        """远程包解析失败时不能把已解析的前半段写入正式来源。"""
        with TemporaryDirectory(prefix="ham_qth_sync_") as temp:
            catalog = QthPlaceCatalog(Path(temp) / "qth.db")
            try:
                catalog.upsert_many([{
                    "place_id": "remote:old",
                    "name": "旧地点",
                    "province": "江苏省",
                    "city": "南京市",
                    "district": "玄武区",
                    "canonical_qth": "江苏省南京市玄武区旧地点",
                }], default_source="remote-pack")
                service = QthPlaceSyncService(catalog)
                with patch.object(
                        service,
                        "_download_pack",
                        return_value=(200, (
                            '{"place_id":"remote:new","name":"新地点",'
                            '"province":"江苏省","city":"南京市",'
                            '"district":"玄武区",'
                            '"canonical_qth":"江苏省南京市玄武区新地点"}\n'
                            '{broken-json}\n'
                        ).encode(), {})):
                    result = service.sync(remote_url="https://example.com/qth.jsonl")
                self.assertFalse(result["ok"])
                self.assertIsNotNone(catalog.resolve_unique("旧地点"))
                self.assertIsNone(catalog.resolve_unique("新地点"))
            finally:
                catalog.close()


if __name__ == "__main__":
    unittest.main()
