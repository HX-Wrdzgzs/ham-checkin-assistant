using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.Tests;

public sealed class ParserTests
{
    private readonly InputParser _parser = new(CatalogLoader.CreateBuiltIn());

    [Fact]
    public void RepeatedYzFillsQthAndOriginalAntenna()
    {
        var result = _parser.Parse("ba4rll qyt6900 5w yz yz");

        Assert.Equal("BA4RLL", result.Callsign.Value);
        Assert.Equal("全易通 QYT-6900", result.Device.Value);
        Assert.Equal("5W", result.Power.Value);
        Assert.Equal("江苏省扬州市", result.Qth.Value);
        Assert.Equal("原装天线", result.Antenna.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void SingleYzKeepsLegacyQthMeaning()
    {
        var result = _parser.Parse("bg4tki yz");

        Assert.Equal("江苏省扬州市", result.Qth.Value);
        Assert.Empty(result.Antenna.Value);
    }

    [Fact]
    public void ExplicitQthMakesYzAnAntenna()
    {
        var result = _parser.Parse("bg6xhb vrn76 yz 湖北");

        Assert.Equal("湖北省", result.Qth.Value);
        Assert.Equal("原装天线", result.Antenna.Value);
        Assert.Equal("威诺 VR-N76", result.Device.Value);
    }

    [Theory]
    [InlineData("ba4aaa njxw pd780 4.2m 5w", "江苏省南京市玄武区", "海能达 PD-780", "4.2米玻璃钢", "5W")]
    [InlineData("ba4aaa njqx r6 y h", "江苏省南京市栖霞区", "摩托罗拉 R6", "原装天线", "高")]
    [InlineData("ba4aaa yz uvk6 771 1w", "江苏省扬州市", "泉盛 UV-K6", "SRH-771", "1W")]
    [InlineData("ba4aaa jsjr pd780 yz h", "江苏省镇江市句容市", "海能达 PD-780", "原装天线", "高")]
    [InlineData("ba4aaa 江苏盐城 r7 原装 低", "江苏省盐城市", "摩托罗拉 R7", "原装天线", "低")]
    [InlineData("ba4aaa 扬州邗江 bfuv36 7900 高", "江苏省扬州市邗江区", "宝峰 UV-36", "钻石 7900", "高")]
    [InlineData("ba4aaa 板桥新城 m8268 车载苗子 5w", "江苏省南京市雨花台区板桥新城", "摩托罗拉 M8268", "车载苗子", "5W")]
    [InlineData("ba4aaa 南京市鼓楼中山路169号 pd780 1.8米玻璃钢 5w", "江苏省南京市鼓楼区中山路169号", "海能达 PD-780", "1.8米玻璃钢", "5W")]
    [InlineData("ba4aaa njjbxq p6620 车苗 25w", "江苏省南京市江北新区", "摩托罗拉 P6620", "车载苗子", "25W")]
    [InlineData("ba4aaa ft-400xd 车苗 南通汽车东站 满", "江苏省南通市汽车东站", "八重洲 FTM-400XD", "车载苗子", "满")]
    public void GoldenCasesAreDeterministic(
        string input,
        string qth,
        string device,
        string antenna,
        string power)
    {
        var result = _parser.Parse(input);

        Assert.Equal(qth, result.Qth.Value);
        Assert.Equal(device, result.Device.Value);
        Assert.Equal(antenna, result.Antenna.Value);
        Assert.Equal(power, result.Power.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4tmt njqx 摩托罗拉 gm338 5单元八木 25w", "江苏省南京市栖霞区", "摩托罗拉 GM338")]
    [InlineData("ba4vna jsxs 泉盛 tk11 原 高", "江苏省盐城市响水县", "泉盛 TK11")]
    [InlineData("ba4soe 江苏盐城 即时通 d900 x300 满", "江苏省盐城市", "即时通 D900")]
    [InlineData("ba4tlh njjn 威派克斯 2108 770 25w", "江苏省南京市江宁区", "威派克斯 2108")]
    [InlineData("ba4vyd njgl 宝锋 ar-152 srh-771 10w", "江苏省南京市鼓楼区", "宝锋 AR-152")]
    public void RecordedWorkbookDeviceVocabularyKeepsTheUserBrandAndDoesNotStealTokens(
        string input,
        string expectedQth,
        string expectedDevice)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Equal(expectedDevice, result.Device.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4qdv njjn yaesu ft-1907r 1.2米玻璃钢 25w", "1.2米玻璃钢")]
    [InlineData("ba4aaa njgl srh-771", "SRH-771")]
    [InlineData("ba4aaa njgl srh-518", "SRH-518")]
    public void RecordedWorkbookAntennaVocabularyIsRecognized(
        string input,
        string expectedAntenna)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedAntenna, result.Antenna.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void SplitModelCanBeResolved()
    {
        var result = _parser.Parse("ba4aaa qyt 6900 5w njxw");
        Assert.Equal("全易通 QYT-6900", result.Device.Value);
    }

    [Theory]
    [InlineData("ba4aaa pd780南通", "江苏省南通市", "海能达 PD-780")]
    [InlineData("ba4aaa 江苏张家港", "江苏省苏州市张家港市", "")]
    [InlineData("ba4aaa shxh", "上海市徐汇区", "")]
    [InlineData("ba4aaa zjhz", "浙江省杭州市", "")]
    [InlineData("ba4aaa 盐城响水", "江苏省盐城市响水县", "")]
    public void CrossProvinceAdministrativeShortcutsAreExpanded(
        string input,
        string qth,
        string device)
    {
        var result = _parser.Parse(input);

        Assert.Equal(qth, result.Qth.Value);
        Assert.Equal(device, result.Device.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4aaa jscz", "江苏省常州市")]
    [InlineData("ba4aaa jsha", "江苏省淮安市")]
    [InlineData("ba4aaa jsxz", "江苏省徐州市")]
    [InlineData("ba4aaa jssq", "江苏省宿迁市")]
    [InlineData("ba4aaa jsyz", "江苏省扬州市")]
    [InlineData("ba4aaa ahmas", "安徽省马鞍山市")]
    [InlineData("ba4vnm yz jsxs 高 k6", "江苏省盐城市响水县")]
    [InlineData("ba4aaa czxb", "江苏省常州市新北区")]
    [InlineData("ba4aaa czjt", "江苏省常州市金坛区")]
    [InlineData("ba4aaa szks", "江苏省苏州市昆山市")]
    [InlineData("ba4aaa szzjg", "江苏省苏州市张家港市")]
    [InlineData("ba4aaa shbs", "上海市宝山区")]
    [InlineData("ba4aaa hncs", "湖南省长沙市")]
    [InlineData("ba4aaa 山东qd", "山东省青岛市")]
    [InlineData("ba4aaa 安徽mas", "安徽省马鞍山市")]
    [InlineData("ba4aaa 湖南cs", "湖南省长沙市")]
    [InlineData("ba4aaa 上海宝山大场", "上海市宝山区大场")]
    [InlineData("ba4aaa 南京师范大学仙林校区", "江苏省南京市南京师范大学仙林校区")]
    public void ProductionShortcutsFromRecordedCheckinsExpandToFullAdministrativeQth(
        string input,
        string expectedQth)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4aaa 湖南长沙", "湖南省长沙市")]
    [InlineData("ba4aaa jsycxs", "江苏省盐城市响水县")]
    [InlineData("ba4aaa jsxs", "江苏省盐城市响水县")]
    [InlineData("ba4aaa nj师范大学仙林校区", "江苏省南京市南京师范大学仙林校区")]
    public void MixedCityAndDistrictShortcutsDoNotSelectAFalseCounty(
        string input,
        string expectedQth)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4aaa 2.4m玻璃钢", "2.4米玻璃钢")]
    [InlineData("ba4aaa pd780 zs7900", "钻石 7900")]
    [InlineData("ba4aaa 775拉杆", "775拉杆")]
    [InlineData("ba4aaa 棒杆天线", "棒杆天线")]
    [InlineData("ba4aaa 棒子天线", "棒子天线")]
    [InlineData("ba4aaa pd780 nr770", "NR770")]
    public void RecordedAntennaVocabularyIsRecognizedWithoutLeavingUnknownTokens(
        string input,
        string expectedAntenna)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedAntenna, result.Antenna.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void RecordedMixedModelAndPowerVocabularyIsRecognized()
    {
        var result = _parser.Parse("bh4syc mt 小功率 棒子天线 szzjg");

        Assert.Equal("摩托罗拉车台", result.Device.Value);
        Assert.Equal("小功率", result.Power.Value);
        Assert.Equal("棒子天线", result.Antenna.Value);
        Assert.Equal("江苏省苏州市张家港市", result.Qth.Value);
        Assert.Contains("mt", result.Tokens, StringComparer.OrdinalIgnoreCase);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void BuiltInCatalogContainsNationwideAdministrativeSnapshot()
    {
        var catalog = CatalogLoader.CreateBuiltIn();

        Assert.True(catalog.QthPlaceCount >= 2500);
        Assert.Equal("上海市宝山区", new InputParser(catalog).Parse("ba4aaa shbs").Qth.Value);
        Assert.Equal("湖南省长沙市", new InputParser(catalog).Parse("ba4aaa hncs").Qth.Value);
        Assert.Equal("山东省威海市", new InputParser(catalog).Parse("ba4aaa sdwh").Qth.Value);
    }

    [Fact]
    public void AmbiguousAdministrativeShortcutRequiresExplicitQthChoice()
    {
        var result = _parser.Parse("ba4aaa bj");

        Assert.Empty(result.Qth.Value);
        Assert.Equal("需要选择", result.Qth.Source);
        Assert.Equal("bj", result.Qth.Raw);
        Assert.Contains("北京市", result.Qth.Candidates!);
        Assert.Contains("贵州省毕节市", result.Qth.Candidates!);
        Assert.Contains("bj", result.Unmatched);
    }

    [Theory]
    [InlineData("hesjz", "河北省石家庄市")]
    [InlineData("sxty", "山西省太原市")]
    [InlineData("lnsy", "辽宁省沈阳市")]
    [InlineData("jlcc", "吉林省长春市")]
    [InlineData("hljheb", "黑龙江省哈尔滨市")]
    [InlineData("jxnc", "江西省南昌市")]
    [InlineData("sdjn", "山东省济南市")]
    [InlineData("hazz", "河南省郑州市")]
    [InlineData("hbwh", "湖北省武汉市")]
    [InlineData("hncs", "湖南省长沙市")]
    [InlineData("gdgz", "广东省广州市")]
    [InlineData("gxnn", "广西壮族自治区南宁市")]
    [InlineData("sccd", "四川省成都市")]
    [InlineData("gzgy", "贵州省贵阳市")]
    [InlineData("ynkm", "云南省昆明市")]
    [InlineData("snxa", "陕西省西安市")]
    [InlineData("gslz", "甘肃省兰州市")]
    [InlineData("qhxn", "青海省西宁市")]
    [InlineData("nxyc", "宁夏回族自治区银川市")]
    [InlineData("xjwlmq", "新疆维吾尔自治区乌鲁木齐市")]
    public void PrefixedCityShortcutsWorkAcrossTheNation(
        string shortcut,
        string expectedQth)
    {
        var result = _parser.Parse($"ba4aaa {shortcut}");

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("zjhzxh", "浙江省杭州市西湖区")]
    [InlineData("gdszns", "广东省深圳市南山区")]
    [InlineData("hncsyl", "湖南省长沙市岳麓区")]
    [InlineData("sccdwh", "四川省成都市武侯区")]
    [InlineData("ynkmwh", "云南省昆明市五华区")]
    [InlineData("xjwlmqts", "新疆维吾尔自治区乌鲁木齐市天山区")]
    [InlineData("sdjnlx", "山东省济南市历下区")]
    [InlineData("hnhk", "海南省海口市")]
    [InlineData("sxxa", "陕西省西安市")]
    [InlineData("nmhhht", "内蒙古自治区呼和浩特市")]
    [InlineData("hlheb", "黑龙江省哈尔滨市")]
    public void PrefixedDistrictShortcutsWorkAcrossAdditionalProvinces(
        string shortcut,
        string expectedQth)
    {
        var result = _parser.Parse($"ba4aaa {shortcut}");

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void EveryUniqueBuiltInAdministrativeAsciiAliasResolvesNationwide()
    {
        var catalog = CatalogLoader.CreateBuiltIn();
        var cases = NationwideAdminCatalog.Entries
            .Where(static entry => string.Equals(entry.Kind, "admin_region", StringComparison.Ordinal))
            .SelectMany(entry => NationwideAdminCatalog.GetAliases(entry)
                .Where(static alias => alias.Length >= 2
                    && alias.All(static character => character is >= 'a' and <= 'z'))
                .Select(alias => (Alias: alias, entry.Canonical)))
            .GroupBy(static item => item.Alias, StringComparer.Ordinal)
            .Where(static group => group.Select(item => item.Canonical)
                .Distinct(StringComparer.Ordinal).Count() == 1)
            .Select(static group => (Alias: group.Key, Canonical: group.First().Canonical))
            // A short token such as “ht” is also a legitimate device name in
            // the field parser. It is tested in the ambiguity cases below;
            // the nationwide administrative sweep must measure unambiguous
            // aliases only.
            .Where(item => catalog.ResolveDevice(item.Alias) is null
                && catalog.ResolveAntenna(item.Alias) is null
                && catalog.ResolvePower(item.Alias) is null)
            .ToArray();

        var failures = new List<string>();
        foreach (var item in cases)
        {
            var result = _parser.Parse($"ba4aaa {item.Alias}");
            var expected = catalog.ResolveQth(item.Alias)?.Canonical;
            if (expected is null
                || !string.Equals(result.Qth.Value, expected, StringComparison.Ordinal)
                || result.Unmatched.Count != 0)
            {
                failures.Add($"{item.Alias} => {result.Qth.Value} / {expected ?? item.Canonical}; unmatched={result.UnmatchedText}");
                if (failures.Count == 20)
                {
                    break;
                }
            }
        }

        Assert.True(failures.Count == 0,
            $"全国行政区缩写失败 {failures.Count} 项（样例：{string.Join(" | ", failures)}）");
        Assert.True(cases.Length >= 2500,
            $"内置行政区缩写样本过少：{cases.Length}");
    }

    [Fact]
    public void RecordedMixedProvinceAndCityInputKeepsTheWholeLine()
    {
        var result = _parser.Parse("bg4sv jsjr shks8600 yz 高");

        Assert.Equal("BG4SV", result.Callsign.Value);
        Assert.Equal("江苏省镇江市句容市", result.Qth.Value);
        Assert.Equal("森海克斯 8600", result.Device.Value);
        Assert.Equal("原装天线", result.Antenna.Value);
        Assert.Equal("高", result.Power.Value);
        Assert.Empty(result.Unmatched);
    }

    [Theory]
    [InlineData("ba4aaa 丰台南路", "北京市丰台区丰台南路")]
    [InlineData("ba4aaa 盐仓桥", "江苏省南京市鼓楼区盐仓桥")]
    [InlineData("ba4aaa 凤台路", "江苏省南京市秦淮区凤台路")]
    [InlineData("ba4aaa 安徽乌江", "安徽省马鞍山市和县乌江镇")]
    public void VerifiedRoadAndLandmarkAliasesExpandToPreciseQth(
        string input,
        string expectedQth)
    {
        var result = _parser.Parse(input);

        Assert.Equal(expectedQth, result.Qth.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void AlternateProvinceShortcutCollisionRequiresExplicitChoice()
    {
        var result = _parser.Parse("ba4aaa hnzz");

        Assert.Equal("hnzz", result.Qth.Raw);
        Assert.Equal("需要选择", result.Qth.Source);
        Assert.Contains("河南省郑州市", result.Qth.Candidates!);
        Assert.Contains("湖南省株洲市", result.Qth.Candidates!);
        Assert.Contains("hnzz", result.Unmatched, StringComparer.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("bh4gbn 上海徐汇 73ham", "上海市徐汇区", "73HAM")]
    [InlineData("bd4wkm szzjg k5 yz 满", "江苏省苏州市张家港市", "泉盛 UV-K5")]
    [InlineData("ba4vna 盐城响水县 73ham", "江苏省盐城市响水县", "73HAM")]
    [InlineData("bg7kmy 云南昆明 ht", "云南省昆明市", "HT")]
    [InlineData("vr2wle 香港 ht", "香港特别行政区", "HT")]
    public void VideoDerivedAdministrativeInputsKeepFullProvinceAndCity(
        string input,
        string qth,
        string device)
    {
        var result = _parser.Parse(input);

        Assert.Equal(qth, result.Qth.Value);
        Assert.Equal(device, result.Device.Value);
    }

    [Fact]
    public void VideoVisiblePd660ProDraftPreservesTheExactUncatalogedModel()
    {
        // 2026-10-04 录屏中可直接读到的草稿：该写法没有在当前工信部快照或
        // 用户别名中形成可靠的“品牌 + 型号”证据，不能擅自改成另一个 PD660
        // 变体；先保留用户原文，等待用户确认后再加入别名。
        var result = _parser.Parse("bh4gbn 上海徐汇 pd660pro");

        Assert.Equal("BH4GBN", result.Callsign.Value);
        Assert.Equal("上海市徐汇区", result.Qth.Value);
        Assert.Equal("pd660pro", result.Device.Value);
        Assert.Equal("未收录型号原文", result.Device.Source);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void VideoDerivedGluedModelKeepsUnknownFollowingTokenUnmatched()
    {
        var result = _parser.Parse("bi4sid pd780南通 xz50 低");

        Assert.Equal("江苏省南通市", result.Qth.Value);
        Assert.Equal("海能达 PD-780", result.Device.Value);
        Assert.Equal("低", result.Power.Value);
        Assert.Equal("XZ50", result.Antenna.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void VideoDerivedKt8900AndQthDoNotCreateInventedDistrict()
    {
        var result = _parser.Parse("ba4vud kt8900 20w sgm507 njgl");

        Assert.Equal("江苏省南京市鼓楼区", result.Qth.Value);
        Assert.Equal("KT-8900", result.Device.Value);
        Assert.Equal("SGM507", result.Antenna.Value);
        Assert.Equal("20W", result.Power.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void VideoVisibleUnknownProvinceAbbreviationStaysInQthInsteadOfBeingDropped()
    {
        // 2026-10-04 录屏中可读到的“山东qcd”。qcd 的含义没有足够的
        // 行政区证据，不能猜成青岛或其他城市，但省份前缀明确，所以应
        // 保留在 QTH 原文中，方便后续字段编辑，而不是落到设备或未识别。
        var result = _parser.Parse("ba4ilg 山东qcd ht");

        Assert.Equal("BA4ILG", result.Callsign.Value);
        Assert.Equal("山东qcd", result.Qth.Value);
        Assert.Equal("HT", result.Device.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void VideoVisibleChineseQthWithAttachedSuffixIsNotLost()
    {
        var result = _parser.Parse("ba4vfw 广东省汕头市m507 kt8900d 25w");

        Assert.Equal("广东省汕头市m507", result.Qth.Value);
        Assert.Equal("KT-8900D", result.Device.Value);
        Assert.Equal("25W", result.Power.Value);
        Assert.Empty(result.Unmatched);
    }

    [Fact]
    public void KnownNanjingUniversityNameIsNotTruncatedToSuffix()
    {
        var result = _parser.Parse("ba4aaa 南京邮电大学 ht");

        Assert.Equal("江苏省南京市南京邮电大学", result.Qth.Value);
        Assert.Equal("HT", result.Device.Value);
    }

    [Fact]
    public void IncompleteCallsignIsNotInventedAsQth()
    {
        var result = _parser.Parse("bh8");

        Assert.DoesNotContain("北海", result.Qth.Value, StringComparison.Ordinal);
        Assert.Contains("bh8", result.Unmatched);
    }

    [Fact]
    public void UnknownModelIsKeptAsDeviceWithoutInventedQth()
    {
        var result = _parser.Parse("ba4aaa sgm507 5w");

        Assert.DoesNotContain("韶关", result.Qth.Value, StringComparison.Ordinal);
        Assert.Equal("sgm507", result.Device.Value);
        Assert.Equal("未收录型号原文", result.Device.Source);
    }

    [Fact]
    public void UnknownModelIsPreservedInsteadOfDropped()
    {
        var result = _parser.Parse("ba4aaa XZ-991 5w mystery");

        Assert.Equal("XZ-991", result.Device.Value);
        Assert.Equal("未收录型号原文", result.Device.Source);
        Assert.Contains("mystery", result.Unmatched);
    }
}
