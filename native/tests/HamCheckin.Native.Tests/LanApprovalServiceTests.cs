using System.Diagnostics.CodeAnalysis;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.LanServer;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 批准服务的租约语义（设计 4.2）：同一条提交只能有一个批准在途；数据库
/// 已提交但队列 CAS 失败时必须返回 WriteCommitted，绝不伪报 Approved。
/// </summary>
[SuppressMessage("Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "xUnit invokes IAsyncLifetime.DisposeAsync after every test instance.")]
public sealed class LanApprovalServiceTests : IAsyncLifetime
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(), $"ham-lan-approval-{Guid.NewGuid():N}");

    private NativeStore _store = null!;
    private NativeStore _delayedStore = null!;
    private SessionInfo _session = null!;
    private SessionInfo _delayedSession = null!;

    public async Task InitializeAsync()
    {
        var dataDirectory = Path.Combine(_root, "data");
        Directory.CreateDirectory(dataDirectory);
        _store = new NativeStore(Path.Combine(dataDirectory, "ham_checkin_native.db"));
        await _store.InitializeAsync();
        _session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 25));

        var delayedDirectory = Path.Combine(_root, "delayed-data");
        Directory.CreateDirectory(delayedDirectory);
        _delayedStore = new NativeStore(
            Path.Combine(delayedDirectory, "ham_checkin_native.db"),
            storeDelayMilliseconds: 4000);
        await _delayedStore.InitializeAsync();
        _delayedSession = await _delayedStore.GetOrCreateFirstSessionAsync(
            new DateOnly(2026, 11, 25));
    }

    public async Task DisposeAsync()
    {
        await _store.DisposeAsync();
        await _delayedStore.DisposeAsync();
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    [Fact]
    public async Task BusyWhenAnotherApprovalHoldsTheLease()
    {
        var queue = new LanPendingQueue();
        var sessions = new MutableLanSessionSource(Snapshot(_session));
        Assert.Equal(
            LanEnqueueStatus.Created,
            queue.Enqueue("client-busy", LanTestData.Parsed()).Status);
        var service = new LanApprovalService(_store, queue, sessions);

        Assert.True(queue.TryBeginApproval("client-busy", out var lease));
        try
        {
            var result = await service.ApproveAsync("client-busy");

            Assert.Equal(LanApprovalStatus.Busy, result.Status);
            Assert.Null(result.Checkin);
            Assert.Equal(LanSubmissionState.Pending, result.Item!.State);
            Assert.Equal(0L, await CountAsync(_store));
        }
        finally
        {
            queue.ReleaseApproval("client-busy", lease);
        }

        var retried = await service.ApproveAsync("client-busy");

        Assert.Equal(LanApprovalStatus.Approved, retried.Status);
        Assert.NotNull(retried.Checkin);
        Assert.Equal(LanSources.Lan, retried.Checkin!.Source);
        Assert.Equal(1L, await CountAsync(_store));
    }

    [Fact]
    public async Task WriteCommittedWhenQueueIsClearedDuringTheDatabaseWrite()
    {
        var queue = new LanPendingQueue();
        var sessions = new MutableLanSessionSource(Snapshot(_delayedSession));
        Assert.Equal(
            LanEnqueueStatus.Created,
            queue.Enqueue("client-slow", LanTestData.Parsed()).Status);
        var service = new LanApprovalService(_delayedStore, queue, sessions);

        // 存储延迟 4s；等待 1.5s 足以让服务取得租约并进入写入，再清空队列。
        // 清空后 TryApprove 的 CAS 必然失败，但 SQLite 事务已经提交。
        var approval = service.ApproveAsync("client-slow");
        await Task.Delay(TimeSpan.FromMilliseconds(1500));
        queue.Clear();
        var result = await approval;

        Assert.Equal(LanApprovalStatus.WriteCommitted, result.Status);
        Assert.NotNull(result.Checkin);
        Assert.Equal(LanSubmissionState.Pending, result.Item!.State);
        Assert.Null(queue.Get("client-slow"));

        var readback = await _delayedStore.GetCheckinBySubmissionIdAsync(
            $"lan-{_delayedSession.Id}-client-slow");
        Assert.NotNull(readback);
        Assert.Equal(result.Checkin!.Id, readback!.Id);
    }

    private static LanSessionSnapshot Snapshot(SessionInfo session) =>
        new(session.Id, session.Name, session.Date, session.Status);

    private static async Task<long> CountAsync(NativeStore store)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = store.DatabasePath,
            Mode = SqliteOpenMode.ReadWrite
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM checkins;";
        var scalar = await command.ExecuteScalarAsync();
        return Convert.ToInt64(scalar, System.Globalization.CultureInfo.InvariantCulture);
    }
}
