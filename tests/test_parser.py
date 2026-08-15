"""Parser 与 QTH/历史/模糊 测试（规格第 94~99 节）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.parser import Parser
from core.predictor import Predictor
from database.db import connect
from database.models import Checkin
from database.repository import Repository
from database.seed import seed_default_aliases
from normalizers.dictionaries import AliasStore
from normalizers.region_index import RegionIndex


def make_parser():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    conn = connect(tmp)
    repo = Repository(conn)
    seed_default_aliases(repo)
    store = AliasStore(repo)
    region = RegionIndex("江苏")
    predictor = Predictor(repo)
    return Parser(store, region, predictor), repo, conn


class TestParser(unittest.TestCase):
    def setUp(self):
        self.parser, self.repo, self.conn = make_parser()

    def tearDown(self):
        self.conn.close()

    def test_basic(self):
        r = self.parser.parse("bg4tki njqx k6 y 5")
        self.assertEqual(r.callsign.value, "BG4TKI")
        self.assertEqual(r.qth.value, "南京栖霞")
        self.assertEqual(r.device.value, "泉盛 UV-K6")
        self.assertEqual(r.antenna.value, "原")
        self.assertEqual(r.power.value, "5W")
        self.assertEqual(r.unmatched, [])

    def test_field_order_equivalent(self):
        variants = [
            "bg4tki njqx k6 y 5",
            "bg4tki k6 njqx y 5",
            "BG4TKI 南京栖霞 K6 5W 原",
            "南京栖霞 BG4TKI K6 5W 原",
        ]
        for v in variants:
            r = self.parser.parse(v)
            self.assertEqual(r.callsign.value, "BG4TKI", v)
            self.assertEqual(r.qth.value, "南京栖霞", v)
            self.assertEqual(r.device.value, "泉盛 UV-K6", v)
            self.assertEqual(r.antenna.value, "原", v)
            self.assertEqual(r.power.value, "5W", v)

    def test_qth_abbr(self):
        self.assertEqual(self.parser.parse("njqx").qth.value, "南京栖霞")
        self.assertEqual(self.parser.parse("ahwh").qth.value, "安徽芜湖")
        self.assertEqual(self.parser.parse("zjhz").qth.value, "浙江杭州")
        self.assertEqual(self.parser.parse("shpd").qth.value, "上海浦东")
        self.assertEqual(self.parser.parse("gdgzth").qth.value, "广东广州天河")

    def test_qth_dup_must_offer_candidates(self):
        r = self.parser.parse("gl")
        self.assertGreaterEqual(len(r.qth.candidates), 2, "gl 必须返回多个候选")
        self.assertIn("南京鼓楼", r.qth.candidates)
        self.assertIn("徐州鼓楼", r.qth.candidates)

    def test_yz_city_wins_over_district(self):
        """yz 同属 扬州(市) 与 仪征(区)，城市级优先 → 自动展开扬州，不需选择。"""
        self.assertEqual(self.parser.parse("bg4tki yz").qth.value, "扬州")
        # 同级歧义仍须选择（gl → 南京鼓楼/徐州鼓楼）
        r = self.parser.parse("gl")
        self.assertGreaterEqual(len(r.qth.candidates), 2)

    def test_repeated_yz_can_fill_qth_and_antenna(self):
        """同一个缩写可按字段消费：第一个 yz 是扬州，第二个 yz 是原装天线。"""
        r = self.parser.parse("ba4rll qyt6900 5w yz yz")
        self.assertEqual(r.callsign.value, "BA4RLL")
        self.assertEqual(r.qth.value, "扬州")
        self.assertEqual(r.antenna.value, "原")
        self.assertEqual(r.device.value, "全易通 QYT-6900")
        self.assertEqual(r.power.value, "5W")
        self.assertEqual(r.unmatched, [])

    def test_observed_free_text_fields_are_not_misclassified_or_dropped(self):
        """现场常见的未收录值也要落到字段/未识别，而不是被 QTH 兜底吞掉。"""
        cases = [
            ("ba4rll 1907 25 njgl 4.2米玻璃钢", "南京鼓楼", "YAESU FT-1907R",
             "4.2米玻璃钢", "25W", []),
            ("ba4qdi icom705 504天线 10w 东南大学四牌楼校区",
             "东南大学四牌楼校区", "ICOM IC-705", "504天线", "10W", []),
            ("ba4tlc ryt6900 yz 5 南京江宁", "南京江宁", "全易通 QYT-6900",
             "原", "5W", []),
            ("bg4x yz mysterytoken", "扬州", "", "", "", ["mysterytoken"]),
        ]
        for text, qth, device, antenna, power, unmatched in cases:
            with self.subTest(text=text):
                r = self.parser.parse(text)
                self.assertEqual(r.qth.value, qth)
                self.assertEqual(r.device.value, device)
                self.assertEqual(r.antenna.value, antenna)
                self.assertEqual(r.power.value, power)
                self.assertEqual(r.unmatched, unmatched)

    def test_single_yz_with_explicit_chinese_qth_is_antenna(self):
        """“yz 湖北”中湖北是现场 QTH，yz 不应抢成扬州。"""
        r = self.parser.parse("bg6xhb vr-n76 yz ht 湖北")
        self.assertEqual(r.qth.value, "湖北")
        self.assertEqual(r.device.value, "威诺 VR-N76")
        self.assertEqual(r.antenna.value, "原")
        self.assertEqual(r.unmatched, ["ht"])

    def test_late_roster_compound_device_forms(self):
        """名单后半段的品牌+型号写法必须作为一个设备消费。"""
        cases = [
            ("ba4vdx bf 5rh srh-771 5w 江宁", "BF 5RH", "南京江宁"),
            ("bg4qbf bf 5rmini yz 5w zj", "BF 5R Mini", "镇江"),
            ("ba4uom bf uv-32 njqx yz 高", "BF UV-32", "南京栖霞"),
            ("ba4tmu bf uv-5r njqh yz 5w", "BF UV-5R", "南京秦淮"),
            ("ba4tlh wpks 2108 770 25 南京江宁", "WPks 2108", "南京江宁"),
            ("ba4tlc ryt 6900 yz 5 南京江宁", "全易通 QYT-6900", "南京江宁"),
        ]
        for text, device, qth in cases:
            with self.subTest(text=text):
                r = self.parser.parse(text)
                self.assertEqual(r.device.value, device)
                self.assertEqual(r.qth.value, qth)
                self.assertEqual(r.unmatched, [])

    def test_compound_antenna_text_is_kept_as_antenna(self):
        r = self.parser.parse("bg6xhb vr-n76 HT湖北上台 湖北")
        self.assertEqual(r.qth.value, "湖北")
        self.assertEqual(r.device.value, "威诺 VR-N76")
        self.assertEqual(r.antenna.value, "HT湖北上台")
        self.assertEqual(r.unmatched, [])

    def test_yz_before_specific_qth_is_not_false_antenna(self):
        """“yz yzjd”中的前置 yz 是地点前缀，不应凭空写成原装天线。"""
        r = self.parser.parse("ba4vrm nrl yz yzjd")
        self.assertEqual(r.qth.value, "扬州江都")
        self.assertEqual(r.antenna.value, "")
        self.assertEqual(r.unmatched, [])

    def test_chinese_not_collapsed(self):
        """“南京南/南京南站”不得被静默折叠成“南京”，应保留原文。"""
        self.assertEqual(self.parser.parse("南京南").qth.value, "南京南")
        self.assertEqual(self.parser.parse("南京南站").qth.value, "南京南站")
        # 完整行政区划链仍正常标准化
        self.assertEqual(self.parser.parse("南京栖霞").qth.value, "南京栖霞")
        self.assertEqual(self.parser.parse("江苏省南京市栖霞区6楼").qth.value, "南京栖霞")
        self.assertEqual(self.parser.parse("bg4tki 南京南").qth.value, "南京南")

    def test_history_suggestion_not_auto(self):
        """历史只是建议，绝不写入实际字段；Tab 接受后才进入字段。

        （原实现把历史直接写进 qth.value 并标记 history_recent，导致「只输呼号
        → Enter 直接提交历史值」。按任务书第二阶段 #1/#2 已改：parse 只填 result.history。）
        """
        s = self.repo.create_session("测试", "2026-08-08")
        c = Checkin(session_id=s.id, sequence_no=1, checkin_time="2026-08-08T10:00:00",
                    callsign="BA4XXX", qth_standard="南京栖霞", device_standard="K6",
                    antenna_standard="771", power_standard="5W", source="local")
        self.repo.add_checkin(c)
        self.repo.rebuild_profiles_for(c.callsign)
        self.repo.rebuild_station(c.callsign)
        r = self.parser.parse("ba4xxx")
        self.assertEqual(r.callsign.value, "BA4XXX")
        # 历史只是建议，不自动提交：实际字段必须为空
        self.assertEqual(r.qth.value, "")
        self.assertEqual(r.qth.source, "")
        self.assertEqual(r.history["qth"]["recent"], "南京栖霞")
        # Tab 接受后才进入字段
        r2 = self.parser.accept_history(r)
        self.assertEqual(r2.qth.value, "南京栖霞")
        self.assertEqual(r2.qth.source, "manual")

    def test_partial_history(self):
        s = self.repo.create_session("测试", "2026-08-08")
        c = Checkin(session_id=s.id, sequence_no=1, checkin_time="2026-08-08T10:00:00",
                    callsign="BA4XXX", qth_standard="南京栖霞", device_standard="K6",
                    antenna_standard="771", power_standard="5W", source="local")
        self.repo.add_checkin(c)
        self.repo.rebuild_profiles_for(c.callsign)
        r = self.parser.parse("ba4xxx 10")
        self.assertEqual(r.power.value, "10W")
        self.assertEqual(r.power.source, "input")  # 本次输入优先
        # 历史不进字段，只作建议
        self.assertEqual(r.qth.value, "")
        self.assertEqual(r.device.value, "")
        self.assertEqual(r.history["qth"]["recent"], "南京栖霞")
        self.assertEqual(r.history["device"]["recent"], "K6")
        # 显式输入不被历史覆盖
        r2 = self.parser.accept_history(r)
        self.assertEqual(r2.power.value, "10W")
        self.assertEqual(r2.qth.value, "南京栖霞")

    def test_fuzzy_njqix(self):
        r = self.parser.parse("bg4tki njqix k6")
        self.assertEqual(r.callsign.value, "BG4TKI")
        # njqix vs njqx 约 88.9%，属中置信 → 显示候选而非自动展开
        self.assertEqual(r.qth.value, "")
        self.assertIn("南京栖霞", r.qth.candidates)

    def test_fuzzy_pinyin(self):
        # 全拼音输入：nanjing → 南京；qixia → 南京栖霞（拼音部分匹配高置信自动展开）
        self.assertEqual(self.parser.parse("bg4tki nanjing").qth.value, "南京")
        self.assertEqual(self.parser.parse("bg4tki qixia").qth.value, "南京栖霞")
        self.assertEqual(self.parser.parse("bg4tki anhuiwuhu").qth.value, "安徽芜湖")

    def test_fuzzy_qth_ambiguous_key_not_auto_accepted(self):
        """P2：歧义缩写地点（gl → 南京鼓楼/徐州鼓楼）拼音模糊命中时强制候选，
        不得按 key 丢弃歧义地点而自信猜错（"gulou" 模糊命中鼓楼）。"""
        r = self.parser.parse("bg4tki gulou")
        self.assertEqual(r.qth.value, "", "歧义地点不得自动接受")
        self.assertIn("南京鼓楼", r.qth.candidates)
        self.assertIn("徐州鼓楼", r.qth.candidates)
        # 明确地点仍正常自动接受
        self.assertEqual(self.parser.parse("bg4tki qixia").qth.value, "南京栖霞")

    def test_alias_beats_callsign_and_power(self):
        # id52 长得像呼号，但已收录为设备 → 按设备解析
        self.assertEqual(self.parser.parse("id52").device.value, "ICOM ID-52 PLUS")
        # 1907 是设备代号，不能当功率
        self.assertEqual(self.parser.parse("bg4tki 1907").device.value, "YAESU FT-1907R")
        self.assertEqual(self.parser.parse("bg4tki 1907").power.value, "")
        # 771 → 规范化 SRH-771
        self.assertEqual(self.parser.parse("771").antenna.value, "SRH-771")
        # 常规功率仍正常
        self.assertEqual(self.parser.parse("bg4tki 5").power.value, "5W")


if __name__ == "__main__":
    unittest.main()
