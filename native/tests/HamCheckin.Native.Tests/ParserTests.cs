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

        Assert.Equal("湖北", result.Qth.Value);
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

    [Fact]
    public void SplitModelCanBeResolved()
    {
        var result = _parser.Parse("ba4aaa qyt 6900 5w njxw");
        Assert.Equal("全易通 QYT-6900", result.Device.Value);
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
