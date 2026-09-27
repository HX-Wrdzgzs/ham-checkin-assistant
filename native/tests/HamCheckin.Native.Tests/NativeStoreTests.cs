using System.Diagnostics.CodeAnalysis;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

[SuppressMessage("Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "xUnit invokes IAsyncLifetime.DisposeAsync after every test instance.")]
public sealed class NativeStoreTests : IAsyncLifetime
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"ham-native-store-{Guid.NewGuid():N}");
    private NativeStore _store = null!;

    public async Task InitializeAsync()
    {
        _store = new NativeStore(Path.Combine(_root, "data", "test.db"));
        await _store.InitializeAsync();
    }

    [Fact]
    public async Task SubmissionIsAtomicAndSequenceIsContinuous()
    {
        var parser = new InputParser(CatalogLoader.CreateBuiltIn());
        var session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));

        for (var index = 0; index < 25; index++)
        {
            await _store.AddCheckinAsync(session,
                parser.Parse($"ba4a{index % 10}a qyt6900 5w yz yz"));
        }

        var rows = await _store.LoadRecentAsync(session.Id, 100);
        Assert.Equal(25, rows.Count);
        Assert.Equal(Enumerable.Range(1, 25).Reverse(), rows.Select(static row => row.SequenceNo));
        Assert.All(rows, static row => Assert.Equal("全易通 QYT-6900", row.Device));
        Assert.Equal("ok", await _store.QuickCheckAsync());
    }

    [Fact]
    public async Task FailedValidationDoesNotCreatePartialRow()
    {
        var session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));

        await Assert.ThrowsAsync<ArgumentException>(() =>
            _store.AddCheckinAsync(session, ParseResult.Empty));

        Assert.Empty(await _store.LoadRecentAsync(session.Id));
    }

    [Fact]
    public async Task SessionLifecycleListsMetadataAndCreatesNextDefaultAfterEnded()
    {
        var first = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));
        Assert.Equal("第1场点名", first.Name);

        var edited = await _store.UpdateSessionInfoAsync(
            first, "BA4THG", "江苏省中继", "C:\\Users\\Public\\第1场.xlsx", "第1场点名");
        Assert.Equal("BA4THG", edited.OperatorCallsign);
        Assert.Equal("江苏省中继", edited.RepeaterName);

        var created = await _store.CreateSessionAsync(
            "特别场", "2026-09-24", "BD4RFG", "临时中继");
        var sessions = await _store.ListSessionsAsync();
        Assert.Equal(2, sessions.Count);
        Assert.Contains(sessions, item => item.Name == "特别场" && item.OperatorCallsign == "BD4RFG");

        await _store.SetSessionStatusAsync(first.Id, "ended");
        await _store.SetSessionStatusAsync(created.Id, "ended");
        var next = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));
        Assert.Equal("第2场点名", next.Name);
        Assert.Equal("active", next.Status);

        var reopened = await _store.SetSessionStatusAsync(first.Id, "active");
        Assert.Equal("active", reopened.Status);
        Assert.Equal(created.Id, (await _store.GetSessionAsync(created.Id))!.Id);
    }

    [Fact]
    public async Task FieldEditChangesOnlySelectedFieldAndConsumesOnlyAdoptedToken()
    {
        var parser = new InputParser(CatalogLoader.CreateBuiltIn());
        var session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));
        var row = await _store.AddCheckinAsync(session,
            parser.Parse("ba4aaa njxw pd780 4.2m 5w mystery1 mystery2"));

        var request = await _store.CreateFieldEditRequestAsync(row.Id, FieldKind.Qth);
        Assert.NotNull(request);
        Assert.Equal("海能达 PD-780", row.Device);
        Assert.Equal("4.2米玻璃钢", row.Antenna);
        Assert.Contains("mystery1", request!.UnmatchedCurrent);
        Assert.Contains("mystery2", request.UnmatchedCurrent);

        var updated = await _store.ApplyFieldEditAsync(new FieldEditCommit(
            row.Id, FieldKind.Qth, request.CurrentValue, "江苏省南京市鼓楼区",
            "njgl", new[] { "mystery1" }, true, request.ExpectedUpdatedAt, "QTH 行政区库"));

        Assert.Equal("江苏省南京市鼓楼区", updated.Qth);
        Assert.Equal(row.Device, updated.Device);
        Assert.Equal(row.Antenna, updated.Antenna);
        Assert.Equal("mystery2", updated.Unmatched);
        Assert.Equal("江苏省南京市鼓楼区", (await _store.CreateFieldEditRequestAsync(row.Id, FieldKind.Qth))!.CurrentValue);
        Assert.Equal("ok", await _store.QuickCheckAsync());
    }

    [Fact]
    public async Task FieldEditCanConsumeTheSecondOfTwoEqualUnmatchedTokens()
    {
        var session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 24));
        var parsed = new ParseResult(
            "BA4AAA YZ YZ",
            new[] { "BA4AAA", "YZ", "YZ" },
            new ParseField("BA4AAA", "输入", 1.0, "BA4AAA"),
            ParseField.Empty,
            ParseField.Empty,
            ParseField.Empty,
            ParseField.Empty,
            ParseField.Empty,
            new[] { "YZ", "YZ" });
        var row = await _store.AddCheckinAsync(session, parsed);
        var request = await _store.CreateFieldEditRequestAsync(row.Id, FieldKind.Antenna);

        var updated = await _store.ApplyFieldEditAsync(new FieldEditCommit(
            row.Id,
            FieldKind.Antenna,
            request!.CurrentValue,
            "原装天线",
            "YZ",
            new[] { "YZ" },
            true,
            request.ExpectedUpdatedAt,
            "天线别名",
            new[] { 1 }));

        Assert.Equal("原装天线", updated.Antenna);
        Assert.Equal("YZ", updated.Unmatched);
    }

    public async Task DisposeAsync()
    {
        await _store.DisposeAsync();
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
    }
}
