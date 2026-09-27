"""回归测试：本场资料补全、来源留痕、整批撤销和工信部候选排序。"""
from __future__ import annotations

import hashlib
import unittest

from database.models import Checkin
from providers.miit import MiitProvider, _signed_params
from services.completion_service import full_qth_candidate
from tests.helpers import make_service
from ui.worker_manager import ExcelUpdateWorker


def _add(repo, session_id: int, sequence: int, callsign: str, *,
         time: str, qth: str = "", device: str = "", antenna: str = "",
         power: str = "", source: str = "local", unmatched: str = "") -> Checkin:
    item = Checkin(
        session_id=session_id,
        sequence_no=sequence,
        checkin_time=time,
        callsign=callsign,
        qth_standard=qth,
        device_standard=device,
        antenna_standard=antenna,
        power_standard=power,
        source=source,
        unmatched=unmatched,
    )
    repo.add_checkin(item)
    return item


class TestCompletionSuggestions(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = make_service()

    def tearDown(self) -> None:
        self.svc.close()

    def _external(self, key: str = "history"):
        return self.svc.repo.find_or_create_external_session(
            "365dt", "TEST", key, key, "2026-08-21")

    def test_same_event_completes_screenshot_pair_and_can_undo(self):
        current = self.svc.create_session("本场", "2026-08-21")
        history = self._external()
        _add(
            self.svc.repo, history.id, 1, "BA4TMI",
            time="2026-08-21T20:04:00",
            qth="江苏省南京市江宁区牛首山",
            device="威泰克斯 VX-2200",
            antenna="八木天线",
            power="25W",
            source="365dt",
        )
        local = _add(
            self.svc.repo, current.id, 1, "BA4TMI",
            time="2026-08-21T20:04:39",
            qth="南京市江宁区牛首山",
            device="wpks2200",
            antenna="八木",
            power="25W",
        )

        suggestions = self.svc.completion_suggestions(current.id)
        by_field = {item["field"]: item for item in suggestions}
        self.assertEqual(by_field["qth"]["proposed_value"], "江苏省南京市江宁区牛首山")
        self.assertEqual(by_field["device"]["proposed_value"], "威泰克斯 VX-2200")
        self.assertEqual(by_field["antenna"]["proposed_value"], "八木天线")
        self.assertNotIn("power", by_field, "相同功率不应制造无意义建议")
        self.assertTrue(all(item["default_selected"] for item in by_field.values()))
        self.assertTrue(all(item["source_type"] == "same_event" for item in by_field.values()))

        applied = self.svc.apply_completion_suggestions(list(by_field.values()), current.id)
        self.assertTrue(applied["ok"], applied)
        after = self.svc.repo.get_checkin(local.id)
        self.assertEqual(after.qth_standard, "江苏省南京市江宁区牛首山")
        self.assertEqual(after.device_standard, "威泰克斯 VX-2200")
        self.assertEqual(after.antenna_standard, "八木天线")
        logs = self.svc.repo.as_dict_rows(
            "SELECT * FROM completion_log WHERE batch_id=?", (applied["batch_id"],))
        self.assertEqual(len(logs), 3)

        undone = self.svc.undo_last_completion(current.id)
        self.assertTrue(undone["ok"], undone)
        restored = self.svc.repo.get_checkin(local.id)
        self.assertEqual(restored.qth_standard, "南京市江宁区牛首山")
        self.assertEqual(restored.device_standard, "wpks2200")
        self.assertEqual(restored.antenna_standard, "八木")

    def test_unmatched_device_and_antenna_are_recovered_without_losing_raw_text(self):
        current = self.svc.create_session("本场", "2026-08-21")
        local = _add(
            self.svc.repo, current.id, 1, "BA4RLL",
            time="2026-08-21T20:00:00",
            qth="南京江宁",
            unmatched="qyt6900 yz",
        )
        suggestions = self.svc.completion_suggestions(current.id)
        recovered = [item for item in suggestions
                     if item["field"] in ("device", "antenna")]
        self.assertEqual({item["field"] for item in recovered}, {"device", "antenna"})
        self.assertTrue(all(item["default_selected"] for item in recovered))
        self.assertEqual({item["evidence"] for item in recovered}, {"qyt6900", "yz"})

        applied = self.svc.apply_completion_suggestions(recovered, current.id)
        self.assertTrue(applied["ok"], applied)
        after = self.svc.repo.get_checkin(local.id)
        self.assertEqual(after.device_standard, "全易通 QYT-6900")
        self.assertEqual(after.antenna_standard, "原装天线")
        self.assertEqual(after.unmatched, "")

    def test_ambiguous_yz_is_not_preselected_when_both_fields_are_empty(self):
        current = self.svc.create_session("本场", "2026-08-21")
        local = _add(
            self.svc.repo, current.id, 1, "BA4AAA",
            time="2026-08-21T20:00:00", unmatched="yz")
        suggestions = self.svc.completion_suggestions(current.id)
        yz = [item for item in suggestions if item.get("evidence") == "yz"]
        self.assertEqual({item["field"] for item in yz}, {"qth", "antenna"})
        self.assertTrue(all(not item["default_selected"] for item in yz))
        self.assertEqual(
            {item["choice_group"] for item in yz},
            {f"record:{local.id}:unmatched:0:1"},
        )

    def test_repeated_yz_tokens_keep_independent_token_positions(self):
        current = self.svc.create_session("本场", "2026-08-21")
        local = _add(
            self.svc.repo, current.id, 1, "BA4AAA",
            time="2026-08-21T20:00:00", unmatched="yz yz")
        suggestions = self.svc.completion_suggestions(current.id)
        by_field = {item["field"]: item for item in suggestions}
        self.assertEqual(set(by_field), {"qth", "antenna"})
        self.assertEqual(
            {(item["evidence_token_start"], item["evidence_token_end"])
             for item in by_field.values()},
            {(0, 1), (1, 2)},
        )
        self.assertEqual(len({item["choice_group"] for item in by_field.values()}), 2)
        self.assertTrue(all(item["default_selected"] for item in by_field.values()))
        applied = self.svc.apply_completion_suggestions(list(by_field.values()), current.id)
        self.assertTrue(applied["ok"], applied)
        after = self.svc.repo.get_checkin(local.id)
        self.assertEqual(after.unmatched, "")
        self.assertTrue(after.qth_standard)
        self.assertTrue(after.antenna_standard)

    def test_conflicting_history_and_ht_link_require_confirmation(self):
        current = self.svc.create_session("本场", "2026-08-21")
        history1 = self._external("h1")
        history2 = self._external("h2")
        _add(self.svc.repo, history1.id, 1, "BA4AAA", time="2026-07-01T10:00:00",
             qth="江苏省南京市江宁区", source="365dt")
        _add(self.svc.repo, history2.id, 1, "BA4AAA", time="2026-07-02T10:00:00",
             qth="江苏省徐州市鼓楼区", source="365dt")
        _add(self.svc.repo, current.id, 1, "BA4AAA", time="2026-08-21T20:00:00")

        link_history = self._external("link")
        _add(self.svc.repo, link_history.id, 1, "BA4HTT", time="2026-08-21T20:01:00",
             device="HT链路", source="365dt")
        _add(self.svc.repo, current.id, 2, "BA4HTT", time="2026-08-21T20:01:30",
             device="HT")

        suggestions = self.svc.completion_suggestions(current.id)
        qth = next(item for item in suggestions
                   if item["callsign"] == "BA4AAA" and item["field"] == "qth")
        self.assertFalse(qth["default_selected"])
        self.assertIn("2 个不同历史值", qth["source_detail"])
        link = next(item for item in suggestions
                    if item["callsign"] == "BA4HTT" and item["field"] == "device")
        self.assertEqual(link["proposed_value"], "HT链路")
        self.assertFalse(link["default_selected"])

    def test_history_profile_does_not_default_add_landmark_to_qth(self):
        current = self.svc.create_session("本场", "2026-08-21")
        for key, day in (("landmark-1", "2026-07-01"), ("landmark-2", "2026-07-02")):
            history = self._external(key)
            _add(
                self.svc.repo,
                history.id,
                1,
                "BA4AAA",
                time=f"{day}T10:00:00",
                qth="江苏省南京市江宁区牛首山",
                source="365dt",
            )
        _add(self.svc.repo, current.id, 1, "BA4AAA", time="2026-08-21T20:00:00")

        qth = next(
            item for item in self.svc.completion_suggestions(current.id)
            if item["field"] == "qth"
        )
        self.assertEqual(qth["source_type"], "history_profile")
        self.assertFalse(qth["default_selected"])
        self.assertIn("街道和地标", qth["source_detail"])

    def test_unmatched_catalog_candidate_keeps_miit_sync_provenance(self):
        class _Catalog:
            def search(self, query, limit=3):
                if query.lower().replace("-", "") != "uvk6":
                    return []
                return [{
                    "article_id": "miit-article-1",
                    "miit_sync_run_id": "miit-run-1",
                    "model": "UV-K6",
                    "standard_name": "泉盛 UV-K6",
                    "device_name": "调频手持台（业余业务）",
                }]

        self.svc.completion_engine.catalog = _Catalog()
        current = self.svc.create_session("本场", "2026-08-21")
        _add(
            self.svc.repo,
            current.id,
            1,
            "BA4AAA",
            time="2026-08-21T20:00:00",
            unmatched="UV-K6",
        )
        item = next(
            item for item in self.svc.completion_suggestions(current.id)
            if item["field"] == "device"
        )
        self.assertEqual(item["miit_article_id"], "miit-article-1")
        self.assertEqual(item["miit_sync_run_id"], "miit-run-1")

    def test_stale_preview_aborts_entire_batch_and_manual_edit_blocks_undo(self):
        current = self.svc.create_session("本场", "2026-08-21")
        first = _add(self.svc.repo, current.id, 1, "BA4AAA",
                     time="2026-08-21T20:00:00", unmatched="k6")
        second = _add(self.svc.repo, current.id, 2, "BA4BBB",
                      time="2026-08-21T20:01:00", unmatched="k5")
        suggestions = self.svc.completion_suggestions(current.id)
        self.svc.repo.update_checkin(second.id, device_standard="用户刚刚修改")
        failed = self.svc.apply_completion_suggestions(suggestions, current.id)
        self.assertFalse(failed["ok"])
        self.assertEqual(self.svc.repo.get_checkin(first.id).device_standard, "")
        self.assertEqual(
            self.svc.repo.as_dict_rows("SELECT * FROM completion_log"), [],
            "快照冲突时整批不得部分写入")

        fresh = [item for item in self.svc.completion_suggestions(current.id)
                 if item["record_id"] == first.id]
        applied = self.svc.apply_completion_suggestions(fresh, current.id)
        self.assertTrue(applied["ok"], applied)
        self.svc.repo.update_checkin(first.id, device_standard="补全后人工修改")
        undone = self.svc.undo_last_completion(current.id)
        self.assertFalse(undone["ok"])
        self.assertEqual(self.svc.repo.get_checkin(first.id).device_standard, "补全后人工修改")

    def test_qth_suffix_completion_disambiguates_city_context(self):
        self.assertEqual(
            full_qth_candidate("徐州鼓楼", self.svc.region),
            "江苏省徐州市鼓楼区",
        )
        self.assertEqual(full_qth_candidate("鼓楼", self.svc.region), "")
        self.assertEqual(
            full_qth_candidate("江宁大学城", self.svc.region),
            "江苏省南京市江宁区大学城",
        )

    def test_qth_city_and_direct_city_abbreviations_expand(self):
        self.assertEqual(self.svc.full_qth("扬州"), "江苏省扬州市")
        self.assertEqual(self.svc.full_qth("南京"), "江苏省南京市")
        self.assertEqual(self.svc.full_qth("上海浦东"), "上海市浦东新区")
        self.assertEqual(self.svc.full_qth("浙江杭州"), "浙江省杭州市")


class TestMiitProviderAndCache(unittest.TestCase):
    def test_public_page_sign_and_radio_ranking(self):
        params = _signed_params("UV-K6", 1, 5, timestamp=123456789)
        unsigned = {key: value for key, value in params.items() if key != "sign"}
        payload = "&".join(f"{key}={value}" for key, value in unsigned.items())
        self.assertEqual(params["sign"], hashlib.new("sm3", payload.encode()).hexdigest())

        rows = [
            {
                "articleField02": "蓝牙设备",
                "articleField03": "<span style='color:red'>K6</span>",
                "articleField04": "某科技公司",
            },
            {
                "articleField02": "调频手持台(业余业务)",
                "articleField03": "<span style='color:red'>UV-K6</span>",
                "articleField04": "福建泉盛电子有限公司",
                "articleField13": "2023FP9522",
            },
        ]
        ranked = MiitProvider._rank("K6", rows)
        self.assertEqual(ranked[0].model, "UV-K6")
        self.assertEqual(ranked[0].standard_name, "泉盛 UV-K6")

    def test_cached_official_result_is_review_only(self):
        svc = make_service()
        try:
            session = svc.create_session("本场", "2026-08-21")
            svc.cache_miit_device_results("UV-K6", [{
                "model": "UV-K6",
                "standard_name": "泉盛 UV-K6",
                "device_name": "调频手持台(业余业务)",
                "applicant": "福建泉盛电子有限公司",
                "approval_code": "2023FP9522",
                "source_url": "https://ythzxfw.miit.gov.cn/jgcx/index.html",
            }])
            _add(svc.repo, session.id, 1, "BA4AAA", time="2026-08-21T20:00:00",
                 device="UV-K6")
            item = next(x for x in svc.completion_suggestions(session.id)
                        if x["field"] == "device")
            self.assertEqual(item["proposed_value"], "泉盛 UV-K6")
            self.assertEqual(item["source_type"], "miit_cache")
            self.assertFalse(item["default_selected"])
        finally:
            svc.close()


class Test现场InputNormalization(unittest.TestCase):
    def test_abbreviations_expand_qth_and_measurement_antenna_on_commit(self):
        svc = make_service()
        try:
            svc.create_session("本场", "2026-08-28")
            result = svc.parse("ba4aaa njxw k1 4.2m")
            self.assertEqual(result.device.value, "泉盛 UV-K1")
            self.assertEqual(result.antenna.value, "4.2米玻璃钢")
            self.assertEqual(result.unmatched, [])

            committed = svc.commit(result)
            checkin = svc.repo.get_checkin(committed["checkin"].id)
            self.assertEqual(checkin.qth_standard, "江苏省南京市玄武区")
            self.assertEqual(checkin.device_standard, "泉盛 UV-K1")
            self.assertEqual(checkin.antenna_standard, "4.2米玻璃钢")
            self.assertEqual(checkin.unmatched, "")
            self.assertIn(
                ("泉盛 UV-K1", "k1"), svc.complete("k1"),
            )
            self.assertIn(
                ("泉盛 UV-K6", "k6"), svc.complete("k6"),
            )
        finally:
            svc.close()

    def test_unapproved_brand_model_is_kept_and_learns_safe_abbreviation(self):
        """未核准机型不依赖 MIIT；明确输入过一次后可观察缩写。"""
        svc = make_service()
        try:
            svc.create_session("本场", "2026-08-28")
            first = svc.parse("ba4aaa 摩托罗拉 x6200")
            self.assertEqual(first.device.value, "摩托罗拉 X6200")
            self.assertEqual(first.device.source, "input")
            self.assertEqual(first.unmatched, [])

            committed = svc.commit(first)
            self.assertTrue(committed["ok"])
            self.assertIn(
                ("摩托罗拉 X6200（历史缩写 x6200）", "x6200"),
                svc.complete("x62"),
            )

            next_result = svc.parse("ba4bbb x6200")
            self.assertEqual(next_result.device.value, "摩托罗拉 X6200")
            self.assertEqual(next_result.device.source, "observed_alias")
            self.assertEqual(next_result.unmatched, [])
        finally:
            svc.close()

    def test_conflicting_observed_abbreviation_is_not_auto_selected(self):
        """同一缩写指向两个明确型号时，必须留给人工词典确认。"""
        svc = make_service()
        try:
            session = svc.create_session("本场", "2026-08-28")
            for seq, standard in ((1, "摩托罗拉 X6200"), (2, "其他品牌 X6200")):
                svc.repo.add_checkin(Checkin(
                    session_id=session.id, sequence_no=seq,
                    checkin_time=f"2026-08-28T20:0{seq}:00",
                    callsign=f"BA4AA{seq}", device_raw="x6200",
                    device_standard=standard, source="local",
                ))
            svc.refresh_observed_device_aliases()
            self.assertNotIn("x6200", svc.parser.observed_device_aliases)
            result = svc.parse("ba4ccc x6200")
            self.assertNotEqual(result.device.source, "observed_alias")
        finally:
            svc.close()

    def test_official_model_suffix_abbreviation_can_be_parsed_from_local_catalog(self):
        """工信部快照中的唯一型号后缀可以直接解析，不联网。"""
        svc = make_service()
        try:
            class _Catalog:
                def exact_model(self, query,):
                    return []

                def abbreviation_matches(self, query, limit=50):
                    if str(query).lower() == "k7":
                        return [{
                            "article_id": "miit-k7",
                            "standard_name": "泉盛 UV-K7",
                            "model": "UV-K7",
                        }]
                    return []

            svc.parser.radio_catalog = _Catalog()
            result = svc.parse("ba4aaa k7")
            self.assertEqual(result.device.value, "泉盛 UV-K7")
            self.assertEqual(result.device.source, "miit_catalog")
            self.assertEqual(result.unmatched, [])
        finally:
            svc.close()


class _BatchExcel:
    def __init__(self) -> None:
        self.saved = 0
        self.updated: list[tuple[int, dict, bool]] = []

    def verify_row_identity(self, row, sequence, callsign):
        return row in (5, 6)

    def find_row(self, sequence, callsign):
        return None

    def update_row(self, row, updates, auto_save=True):
        self.updated.append((row, dict(updates), auto_save))
        return True, f"written {row}"

    def save(self):
        self.saved += 1
        return True, "saved"


class TestBatchExcelWorker(unittest.TestCase):
    def test_batch_updates_rows_then_saves_once(self):
        task = {
            "batch": True,
            "batch_id": "b1",
            "items": [
                {"checkin_id": 1, "row": 5, "sequence": 1,
                 "callsign": "BA4AAA", "updates": {"device": "K6"}},
                {"checkin_id": 2, "row": 6, "sequence": 2,
                 "callsign": "BA4BBB", "updates": {"qth": "南京"}},
            ],
        }
        worker = ExcelUpdateWorker(task)
        excel = _BatchExcel()
        result = worker._run_batch(excel)
        self.assertTrue(result["ok"], result)
        self.assertEqual(excel.saved, 1)
        self.assertEqual(len(excel.updated), 2)
        self.assertTrue(all(not update[2] for update in excel.updated))


if __name__ == "__main__":
    unittest.main()
