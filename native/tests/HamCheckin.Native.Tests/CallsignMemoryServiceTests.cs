using System.Diagnostics.CodeAnalysis;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Memory;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

/// <summary>
/// S1 呼号记忆：只依赖临时 SQLite 的 checkins 历史，验证字段级 Top3 聚合、
/// 归一化呼号、空值过滤和 50 条历史窗口，不触碰生产库。
/// </summary>
[SuppressMessage("Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "xUnit invokes IAsyncLifetime.DisposeAsync after every test instance.")]
public sealed class CallsignMemoryServiceTests : IAsyncLifetime
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(), $"ham-callsign-memory-{Guid.NewGuid():N}");
    private NativeStore _store = null!;
    private SessionInfo _session = null!;

    public async Task InitializeAsync()
    {
        _store = new NativeStore(Path.Combine(_root, "data", "ham_checkin_native.db"));
        await _store.InitializeAsync();
        _session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 22));
    }

    [Fact]
    public async Task LoadAsyncRanksEachFieldByCountThenRecencyAndSkipsBlankValues()
    {
        await AddAsync("BA4RLL", "南京玄武", "PD780", "", "5W");
        await AddAsync("BA4RLL", "南京玄武", "UV5R", "玻璃钢", "5W");
        await AddAsync("BA4RLL", "南京玄武", "PD780", "   ", "8W");
        await AddAsync("BA4RLL", "苏州姑苏", "PD780", "玻璃钢", "8W");
        await AddAsync("BA4RLL", "苏州姑苏", "FT818", "偶极", "8W");
        await AddAsync("BA4RLL", "无锡梁溪", "PD780", "   ", "5W");
        var cz = await AddAsync("BA4RLL", "常州天宁", "UV5R", "玻璃钢", "5W");
        await AddAsync("BD4XYZ", "上海浦东", "XYZRIG", "XYZANT", "1W");

        var before = await _store.LoadRecentAsync(_session.Id, 500);
        var snapshot = await new CallsignMemoryService(_store).LoadAsync(" BA4RLL ");
        var after = await _store.LoadRecentAsync(_session.Id, 500);

        Assert.Equal("BA4RLL", snapshot.Callsign);
        Assert.Equal(cz.CheckinTime, snapshot.LastCheckinTime);
        Assert.False(string.IsNullOrWhiteSpace(snapshot.LastCheckinTime));

        // 计数优先、同计数按最近 id：南京 3 > 苏州 2 > 常州 1（无锡同 1 但更早）。
        AssertField(snapshot, FieldKind.Qth,
            ("南京玄武", 3),
            ("苏州姑苏", 2),
            ("常州天宁", 1));

        // PD780 出现 4 次，占满窗口后仍按次数优先；空白设备值被过滤。
        AssertField(snapshot, FieldKind.Device,
            ("PD780", 4),
            ("UV5R", 2),
            ("FT818", 1));

        AssertField(snapshot, FieldKind.Antenna,
            ("玻璃钢", 3),
            ("偶极", 1));

        AssertField(snapshot, FieldKind.Power,
            ("5W", 4),
            ("8W", 3));

        Assert.Equal(10, snapshot.Fields.Count);
        Assert.DoesNotContain(snapshot.Fields, static hint => string.IsNullOrWhiteSpace(hint.Value));

        // 只读查询不得新增/修改记录。
        Assert.Equal(before.Select(static row => row.Id), after.Select(static row => row.Id));
        Assert.Equal("ok", await _store.QuickCheckAsync());
    }

    [Fact]
    public async Task LoadAsyncNormalizesLookupAndReturnsEmptyForBlankWithoutStoreAccess()
    {
        await AddAsync("BA4RLL", "南京玄武", "PD780", "玻璃钢", "5W");

        var snapshot = await new CallsignMemoryService(_store).LoadAsync("  ba4rll  ");

        Assert.Equal("BA4RLL", snapshot.Callsign);
        Assert.Equal(4, snapshot.Fields.Count);

        // 空呼号必须在碰到存储之前返回单例；传入 null 存储可证明没有查询。
        var noStore = new CallsignMemoryService(null!);
        Assert.Same(CallsignMemorySnapshot.Empty, await noStore.LoadAsync("   "));
        Assert.Same(CallsignMemorySnapshot.Empty, await noStore.LoadAsync(null));
    }

    [Fact]
    public async Task LoadAsyncIgnoresRowsOlderThanTheFiftyRowHistoryWindow()
    {
        Assert.Equal(50, CallsignMemoryService.HistoryLimit);

        for (var index = 0; index < 5; index++)
        {
            await AddAsync("BA4RLL", "限外老值", "PD780", "玻璃钢", "5W");
        }

        for (var index = 0; index < 50; index++)
        {
            await AddAsync("BA4RLL", "南京玄武", "PD780", "玻璃钢", "5W");
        }

        var snapshot = await new CallsignMemoryService(_store).LoadAsync("BA4RLL");
        var qth = Assert.Single(snapshot.Fields.Where(static hint => hint.Field == FieldKind.Qth));

        Assert.Equal("南京玄武", qth.Value);
        Assert.Equal(50, qth.UseCount);
        Assert.DoesNotContain(snapshot.Fields, static hint => hint.Value == "限外老值");
    }

    public async Task DisposeAsync()
    {
        await _store.DisposeAsync();
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    private async Task<CheckinEntry> AddAsync(
        string callsign,
        string qth,
        string device,
        string antenna,
        string power) =>
        await _store.AddCheckinAsync(_session, Parse(callsign, qth, device, antenna, power));

    private static ParseResult Parse(
        string callsign,
        string qth,
        string device,
        string antenna,
        string power) => new(
        $"{callsign} {qth} {device} {antenna} {power}".Trim(),
        new[] { callsign },
        Field(callsign),
        Field(qth),
        Field(device),
        Field(antenna),
        Field(power),
        ParseField.Empty,
        Array.Empty<string>());

    private static ParseField Field(string value) =>
        string.IsNullOrWhiteSpace(value)
            ? ParseField.Empty
            : new ParseField(value, "测试", 1.0, value);

    private static void AssertField(
        CallsignMemorySnapshot snapshot,
        FieldKind field,
        params (string Value, int UseCount)[] expected)
    {
        var actual = snapshot.Fields.Where(hint => hint.Field == field).ToArray();
        Assert.Equal(expected.Length, actual.Length);
        for (var index = 0; index < expected.Length; index++)
        {
            Assert.Equal(field, actual[index].Field);
            Assert.Equal(expected[index].Value, actual[index].Value);
            Assert.Equal(expected[index].UseCount, actual[index].UseCount);
        }
    }
}
