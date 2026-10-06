using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.Tests;

public sealed class FieldParserTests
{
    private readonly FieldParser _parser = new(CatalogLoader.CreateBuiltIn());

    [Theory]
    [InlineData("njxw", "江苏省南京市玄武区")]
    [InlineData("njgl中山路169号", "江苏省南京市鼓楼区中山路169号")]
    [InlineData("南京鼓楼", "江苏省南京市鼓楼区")]
    [InlineData("南京市鼓楼中山路169号", "江苏省南京市鼓楼区中山路169号")]
    [InlineData("江宁区禄口镇", "江苏省南京市江宁区禄口镇")]
    [InlineData("njjbxq", "江苏省南京市江北新区")]
    [InlineData("江北新区工业大学", "江苏省南京市江北新区工业大学")]
    [InlineData("玄武湖", "江苏省南京市玄武湖")]
    [InlineData("南京马群", "江苏省南京市马群")]
    [InlineData("西安门地铁站", "江苏省南京市西安门地铁站")]
    [InlineData("丰台南路", "北京市丰台区丰台南路")]
    [InlineData("盐仓桥", "江苏省南京市鼓楼区盐仓桥")]
    [InlineData("凤台路", "江苏省南京市秦淮区凤台路")]
    [InlineData("安徽乌江", "安徽省马鞍山市和县乌江镇")]
    [InlineData("ahwh", "安徽省芜湖市")]
    public void QthAbbreviationExpandsAdministrativePrefix(string input, string expected)
    {
        var result = _parser.Parse(FieldKind.Qth, input);

        Assert.Equal(expected, result.CanonicalValue);
        Assert.Contains(input, result.ConsumedTokens);
    }

    [Theory]
    [InlineData(FieldKind.Device, "pd780", "海能达 PD-780")]
    [InlineData(FieldKind.Device, "r6", "摩托罗拉 R6")]
    [InlineData(FieldKind.Device, "uvk5", "泉盛 UV-K5")]
    [InlineData(FieldKind.Device, "泉盛 UV-K6", "泉盛 UV-K6")]
    [InlineData(FieldKind.Device, "海能达 PD-780G", "海能达 PD-780G")]
    [InlineData(FieldKind.Device, "p6620", "摩托罗拉 P6620")]
    [InlineData(FieldKind.Device, "bfuv5r", "宝峰 UV-5R")]
    [InlineData(FieldKind.Device, "bfuv36", "宝峰 UV-36")]
    [InlineData(FieldKind.Device, "ft70d", "YAESU FT-70DR")]
    [InlineData(FieldKind.Device, "宝峰 5rhpro", "宝峰 UV-5R Pro")]
    [InlineData(FieldKind.Antenna, "4.2m", "4.2米玻璃钢")]
    [InlineData(FieldKind.Antenna, "1.8米玻璃钢", "1.8米玻璃钢")]
    [InlineData(FieldKind.Antenna, "2.4米玻璃钢", "2.4米玻璃钢")]
    [InlineData(FieldKind.Antenna, "车苗", "车载苗子")]
    [InlineData(FieldKind.Antenna, "原装天线", "原装天线")]
    [InlineData(FieldKind.Antenna, "srh701", "SRH-701")]
    [InlineData(FieldKind.Antenna, "橡胶天线", "橡胶天线")]
    [InlineData(FieldKind.Antenna, "十字交叉偶极天线", "十字交叉偶极天线")]
    [InlineData(FieldKind.Power, "25w", "25W")]
    public void KnownAbbreviationsUseCanonicalFieldValue(FieldKind field, string input, string expected)
    {
        var result = _parser.Parse(field, input);

        Assert.Equal(expected, result.CanonicalValue);
        Assert.Contains(input, result.ConsumedTokens);
    }

    [Fact]
    public void FieldParserDoesNotCrossInterpretAnotherField()
    {
        var result = _parser.Parse(FieldKind.Qth, "pd780");

        Assert.Equal("pd780", result.CanonicalValue);
        Assert.DoesNotContain("海能达", result.CanonicalValue);
        Assert.Empty(result.ConsumedTokens);
    }

    [Theory]
    [InlineData("宁夏银川", "宁夏回族自治区银川市")]
    [InlineData("山西晋中", "山西省晋中市")]
    public void ProvinceAndCityAbbreviationsExpandWithMatchingAdminRecord(
        string input,
        string expected)
    {
        var qths = new Dictionary<string, IReadOnlyList<QthCandidate>>(StringComparer.Ordinal)
        {
            ["银川市"] = new[]
            {
                new QthCandidate("宁夏回族自治区银川市", "宁夏回族自治区", "银川市", "", "admin_region")
            },
            ["晋中市"] = new[]
            {
                new QthCandidate("山西省晋中市", "山西省", "晋中市", "", "admin_region")
            }
        };
        var snapshot = new CatalogSnapshot(
            new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal),
            new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal),
            new Dictionary<string, string>(StringComparer.Ordinal),
            new Dictionary<string, string>(StringComparer.Ordinal),
            qths);

        var result = new FieldParser(snapshot).Parse(FieldKind.Qth, input);

        Assert.Equal(expected, result.CanonicalValue);
        Assert.Equal("全国行政区库", result.Source);
    }

    [Fact]
    public void ForeignQthRemainsManualUntilAPlaceCatalogProvidesIt()
    {
        var result = _parser.Parse(FieldKind.Qth, "德国");

        Assert.Equal("德国", result.CanonicalValue);
        Assert.Equal("人工输入（待确认）", result.Source);
    }

    [Fact]
    public void EveryUniqueNationwideAsciiCityAliasExpands()
    {
        var snapshot = CatalogLoader.CreateBuiltIn();
        var aliases = NationwideAdminCatalog.Entries
            .Where(static entry => entry.Kind == "admin_region")
            .SelectMany(entry => NationwideAdminCatalog.GetAliases(entry)
                .Where(static alias => alias.Length >= 2
                    && alias.All(static character => char.IsAsciiLetterOrDigit(character)))
                .Select(alias => new { Key = TextNormalizer.NormalizeKey(alias), Alias = alias, entry.Canonical }))
            .Where(static item => item.Key.Length > 0)
            .GroupBy(static item => item.Key, StringComparer.Ordinal)
            .Select(group => new
            {
                Alias = group.First().Alias,
                Canonicals = group.Select(static item => item.Canonical)
                    .Distinct(StringComparer.Ordinal)
                    .ToArray()
            })
            .Where(static item => item.Canonicals.Length == 1)
            .ToArray();

        Assert.NotEmpty(aliases);
        foreach (var item in aliases)
        {
            var result = snapshot.ResolveQthInput(item.Alias);
            Assert.True(result is not null, $"Alias '{item.Alias}' expected '{item.Canonicals[0]}'");
            Assert.Equal(NormalizeExpectedQth(item.Canonicals[0]), result!.Canonical);
        }
    }

    private static string NormalizeExpectedQth(string value) => value switch
    {
        "江苏省盐城市响水区" => "江苏省盐城市响水县",
        "江苏省盐城市滨海区" => "江苏省盐城市滨海县",
        "云南省楚雄市楚雄市" => "云南省楚雄市",
        "云南省文山市文山市" => "云南省文山市",
        "云南省大理市大理市" => "云南省大理市",
        "甘肃省临夏市临夏市" => "甘肃省临夏市",
        "青海省玉树市玉树市" => "青海省玉树市",
        "新疆维吾尔自治区昌吉市昌吉市" => "新疆维吾尔自治区昌吉市",
        "新疆维吾尔自治区阿克苏市阿克苏市" => "新疆维吾尔自治区阿克苏市",
        "新疆维吾尔自治区喀什市喀什市" => "新疆维吾尔自治区喀什市",
        "新疆维吾尔自治区和田市和田市" => "新疆维吾尔自治区和田市",
        "新疆维吾尔自治区塔城市塔城市" => "新疆维吾尔自治区塔城市",
        "新疆维吾尔自治区阿勒泰市阿勒泰市" => "新疆维吾尔自治区阿勒泰市",
        _ => value
    };
}
