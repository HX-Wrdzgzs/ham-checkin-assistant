using System.IO;
using Xunit;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.UiTests;

[CollectionDefinition(nameof(CatalogPublicationViewModelStateCollection), DisableParallelization = true)]
public sealed class CatalogPublicationViewModelStateCollection
{
}

[Collection(nameof(CatalogPublicationViewModelStateCollection))]
public sealed class CatalogPublicationViewModelTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"ham-native-viewmodel-{Guid.NewGuid():N}");

    public CatalogPublicationViewModelTests() => Directory.CreateDirectory(_root);

    [Fact]
    public async Task PublishedLoadUpdatesCatalogCountsAndReparsesInput()
    {
        var service = new CatalogService((baseline, _, _) =>
            Task.FromResult((baseline, CreateReport(baseline))));
        await using var viewModel = CreateViewModel(service);
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("待重新解析的隔离输入");
        var previousParseUpdates = parseUpdates;

        await viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);

        var report = CreateReport(service.Current);
        Assert.Equal(
            $"本地别名 {report.DeviceAliasCount:N0} 个；行政地点 {report.QthPlaceCount:N0} 条；工信部 {report.MiitModelCount:N0} 个",
            viewModel.CatalogSummary);
        Assert.Equal("无后台任务 · 本地资料库已就绪", viewModel.TaskSummary);
        Assert.Equal(previousParseUpdates + 1, parseUpdates);
        Assert.DoesNotContain("加载失败", viewModel.StatusMessage);
    }

    [Fact]
    public async Task UnpublishedSuccessfulLoadDoesNotUpdateViewModelState()
    {
        var olderLoad = NewLoadCompletion();
        var newerLoad = NewLoadCompletion();
        var request = 0;
        var service = new CatalogService((_, _, _) =>
            Interlocked.Increment(ref request) == 1 ? olderLoad.Task : newerLoad.Task);
        var baseline = service.Current;
        await using var viewModel = CreateViewModel(service);
        var initialSummary = viewModel.CatalogSummary;
        var initialStatus = viewModel.StatusMessage;
        var initialTask = viewModel.TaskSummary;
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("未发布结果不重解析");
        var previousParseUpdates = parseUpdates;

        var viewModelLoad = viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);
        var newerServiceLoad = service.ReloadExistingDataAsync("newer");
        newerLoad.SetResult((baseline, CreateReport(baseline)));
        Assert.True((await newerServiceLoad).Published);
        olderLoad.SetResult((baseline, CreateReport(baseline)));
        await viewModelLoad;

        Assert.Equal(initialSummary, viewModel.CatalogSummary);
        Assert.Equal(initialStatus, viewModel.StatusMessage);
        Assert.Equal(initialTask, viewModel.TaskSummary);
        Assert.Equal(previousParseUpdates, parseUpdates);
    }

    [Fact]
    public async Task LatestFailureIsVisibleWithoutReplacingOrReparsingCurrentCatalog()
    {
        var service = new CatalogService((baseline, _, _) =>
            Task.FromResult((baseline, CreateReport(baseline, succeeded: false))));
        var previous = service.Current;
        await using var viewModel = CreateViewModel(service);
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("失败结果不重解析");
        var previousParseUpdates = parseUpdates;

        await viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);

        Assert.Same(previous, service.Current);
        Assert.Contains("资料库加载失败", viewModel.CatalogSummary);
        Assert.Equal("资料库加载失败，但 SQLite 录入仍可用", viewModel.StatusMessage);
        Assert.Equal("资料库任务失败 · 可重试", viewModel.TaskSummary);
        Assert.Equal(previousParseUpdates, parseUpdates);
    }

    [Fact]
    public async Task CancelledLoadDoesNotBecomeFailureOrReparseInput()
    {
        var pending = NewLoadCompletion();
        var service = new CatalogService((_, _, cancellationToken) => pending.Task.WaitAsync(cancellationToken));
        var previous = service.Current;
        await using var viewModel = CreateViewModel(service);
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("取消结果不重解析");
        var previousParseUpdates = parseUpdates;
        using var cancellation = new CancellationTokenSource();

        var load = viewModel.LoadCatalogInBackgroundAsync(cancellation.Token);
        cancellation.Cancel();
        await load;
        pending.SetResult((previous, CreateReport(previous)));

        Assert.Same(previous, service.Current);
        Assert.DoesNotContain("加载失败", viewModel.CatalogSummary);
        Assert.DoesNotContain("加载失败", viewModel.StatusMessage);
        Assert.Equal(previousParseUpdates, parseUpdates);
    }

    [Fact]
    public async Task StaleFailureCannotOverwriteNewerPublishedViewModelState()
    {
        var olderLoad = NewLoadCompletion();
        var newerLoad = NewLoadCompletion();
        var request = 0;
        var service = new CatalogService((_, _, _) =>
            Interlocked.Increment(ref request) == 1 ? olderLoad.Task : newerLoad.Task);
        var baseline = service.Current;
        await using var viewModel = CreateViewModel(service);
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("过期失败不重解析");
        var previousParseUpdates = parseUpdates;

        var olderOperation = viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);
        var newerOperation = viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);
        newerLoad.SetResult((baseline, CreateReport(baseline)));
        await newerOperation;
        var publishedSummary = viewModel.CatalogSummary;
        var publishedStatus = viewModel.StatusMessage;
        var publishedTask = viewModel.TaskSummary;
        Assert.Equal(previousParseUpdates + 1, parseUpdates);

        olderLoad.SetResult((baseline, CreateReport(baseline, succeeded: false)));
        await olderOperation;

        Assert.Equal(publishedSummary, viewModel.CatalogSummary);
        Assert.Equal(publishedStatus, viewModel.StatusMessage);
        Assert.Equal(publishedTask, viewModel.TaskSummary);
        Assert.Equal(previousParseUpdates + 1, parseUpdates);
        Assert.DoesNotContain("加载失败", viewModel.CatalogSummary);
    }

    [Fact]
    public async Task PublishedCatalogIsReparsedBeforeQthTreeFailureCompletes()
    {
        const string previousDevice = "旧测试型号";
        const string publishedDevice = "新测试型号";
        var previousSnapshot = CreateSnapshot(previousDevice);
        var publishedSnapshot = CreateSnapshot(publishedDevice);
        var service = await CreateCatalogServiceWithSnapshotsAsync(previousSnapshot, publishedSnapshot);
        await using var viewModel = CreateViewModel(service);
        var parseUpdates = 0;
        viewModel.ParseUpdated += (_, _) => parseUpdates++;
        viewModel.SetInputText("BA4THG testalias");
        Assert.Equal(previousDevice, viewModel.Device);
        var previousParseUpdates = parseUpdates;

        var treeRefreshStarted = NewSignalCompletion();
        var treeRefresh = NewLoadCompletion();
        viewModel.QthPackageTreeRefreshForTesting = _ =>
        {
            treeRefreshStarted.TrySetResult(true);
            return treeRefresh.Task;
        };

        var load = viewModel.LoadCatalogInBackgroundAsync(CancellationToken.None);
        await treeRefreshStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));

        Assert.Same(publishedSnapshot, service.Current);
        Assert.Equal(publishedDevice, viewModel.Device);
        Assert.NotEqual(previousDevice, viewModel.Device);
        Assert.Equal(previousParseUpdates + 1, parseUpdates);
        Assert.Contains("正在刷新地点包树", viewModel.TaskSummary);

        treeRefresh.SetException(new IOException("isolated tree failure"));
        await load;

        Assert.Equal(publishedDevice, viewModel.Device);
        Assert.Contains("地点包树刷新失败", viewModel.LocationStatus);
        Assert.Contains("地点包树刷新失败", viewModel.StatusMessage);
        Assert.Contains("地点包树刷新失败", viewModel.TaskSummary);
        Assert.DoesNotContain("资料库加载失败", viewModel.CatalogSummary);
        Assert.DoesNotContain("资料库加载失败", viewModel.StatusMessage);
    }

    [Fact]
    public async Task CancelledQthTreeRefreshKeepsPublishedCatalogAndReparsedInput()
    {
        const string previousDevice = "旧测试型号";
        const string publishedDevice = "新测试型号";
        var previousSnapshot = CreateSnapshot(previousDevice);
        var publishedSnapshot = CreateSnapshot(publishedDevice);
        var service = await CreateCatalogServiceWithSnapshotsAsync(previousSnapshot, publishedSnapshot);
        await using var viewModel = CreateViewModel(service);
        viewModel.SetInputText("BA4THG testalias");
        Assert.Equal(previousDevice, viewModel.Device);

        var treeRefreshStarted = NewSignalCompletion();
        var treeRefresh = NewLoadCompletion();
        viewModel.QthPackageTreeRefreshForTesting = cancellationToken =>
        {
            treeRefreshStarted.TrySetResult(true);
            return treeRefresh.Task.WaitAsync(cancellationToken);
        };
        using var cancellation = new CancellationTokenSource();

        var load = viewModel.LoadCatalogInBackgroundAsync(cancellation.Token);
        await treeRefreshStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Same(publishedSnapshot, service.Current);
        Assert.Equal(publishedDevice, viewModel.Device);

        cancellation.Cancel();
        await load;

        Assert.Equal(publishedDevice, viewModel.Device);
        Assert.Equal("全国行政区基础索引可用；地点包树刷新已取消", viewModel.LocationStatus);
        Assert.Equal("资料库已更新；地点包树刷新已取消", viewModel.StatusMessage);
        Assert.Equal("地点包树刷新已取消 · 本地资料库已就绪", viewModel.TaskSummary);
        Assert.DoesNotContain("资料库加载失败", viewModel.CatalogSummary);
        Assert.DoesNotContain("资料库加载失败", viewModel.StatusMessage);
    }

    [Fact]
    public async Task StartupDisplaysLegacyImportMessageAgainFromCompletedMarker()
    {
        var previousDataRootWasOverridden = AppPaths.IsOverridden;
        var previousDataRoot = AppPaths.Root;
        var previousRuntimeOptions = RuntimeOptions.CaptureSnapshot();
        MainViewModel? viewModel = null;
        try
        {
            AppPaths.ConfigureDataRoot(_root);
            RuntimeOptions.Configure(disableNetwork: true);
            await CreateLegacyDatabaseAsync(AppPaths.LegacyDatabasePath);

            viewModel = CreateStartupViewModel();
            await viewModel.InitializeAsync();

            Assert.Contains("已从旧版数据库导入 1 个场次、1 条签到", viewModel.StatusMessage);
            Assert.Contains("本地录入已就绪", viewModel.StatusMessage);
            Assert.True(viewModel.IsQuickInputAvailable);
            Assert.NotNull(await viewModel.GetSessionAsync());
            var marker = await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT value FROM native_meta WHERE key = 'legacy_python_import'");
            Assert.Equal("1", await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT COUNT(*) FROM checkins WHERE submission_id LIKE 'legacy-python:%'"));

            await viewModel.DisposeAsync();
            viewModel = null;
            viewModel = CreateStartupViewModel();
            await viewModel.InitializeAsync();

            Assert.Contains("旧版数据库已经完成过迁移", viewModel.StatusMessage);
            Assert.Contains("本地录入已就绪", viewModel.StatusMessage);
            Assert.True(viewModel.IsQuickInputAvailable);
            Assert.NotNull(await viewModel.GetSessionAsync());
            Assert.Equal(marker, await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT value FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("1", await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT COUNT(*) FROM checkins WHERE submission_id LIKE 'legacy-python:%'"));
        }
        finally
        {
            try
            {
                if (viewModel is not null)
                {
                    await viewModel.DisposeAsync();
                }
            }
            finally
            {
                AppPaths.ConfigureDataRoot(previousDataRootWasOverridden ? previousDataRoot : null);
                RuntimeOptions.RestoreSnapshot(previousRuntimeOptions);
                Assert.Equal(previousRuntimeOptions, RuntimeOptions.CaptureSnapshot());
                SqliteConnection.ClearAllPools();
            }
        }
    }

    [Theory]
    [InlineData("completed")]
    [InlineData("skipped-native-data-exists")]
    public async Task StartupDisplaysMessageForExistingLegacyMarkers(string markerStatus)
    {
        var previousDataRootWasOverridden = AppPaths.IsOverridden;
        var previousDataRoot = AppPaths.Root;
        var previousRuntimeOptions = RuntimeOptions.CaptureSnapshot();
        MainViewModel? viewModel = null;
        try
        {
            AppPaths.ConfigureDataRoot(_root);
            RuntimeOptions.Configure(disableNetwork: true);
            await CreateLegacyDatabaseAsync(AppPaths.LegacyDatabasePath);
            await using (var store = new NativeStore())
            {
                await store.InitializeAsync();
                await store.CreateSessionAsync("本地已有场次", "2026-11-15");
            }

            var marker = $"{{\"status\":\"{markerStatus}\"}}";
            await WriteMigrationMarkerAsync(AppPaths.NativeDatabasePath, marker);
            viewModel = CreateStartupViewModel();
            await viewModel.InitializeAsync();

            if (markerStatus == "skipped-native-data-exists")
            {
                Assert.Contains("原生数据库已有数据，未导入旧版数据库", viewModel.StatusMessage);
                Assert.Contains("该标记不能证明旧版数据库已经完成过迁移", viewModel.StatusMessage);
            }
            else
            {
                Assert.Contains("旧版数据库已经完成过迁移", viewModel.StatusMessage);
            }
            Assert.Contains("历史映射不可追溯", viewModel.StatusMessage);
            Assert.Contains("本地录入已就绪", viewModel.StatusMessage);
            Assert.True(viewModel.IsQuickInputAvailable);
            Assert.Equal("本地已有场次", viewModel.SessionTitle);
            Assert.True(File.Exists(AppPaths.LegacyDatabasePath));
            Assert.Equal(marker, await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT value FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("1", await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("0", await ReadScalarAsync(AppPaths.NativeDatabasePath,
                "SELECT COUNT(*) FROM checkins WHERE submission_id LIKE 'legacy-python:%'"));
        }
        finally
        {
            try
            {
                if (viewModel is not null)
                {
                    await viewModel.DisposeAsync();
                }
            }
            finally
            {
                AppPaths.ConfigureDataRoot(previousDataRootWasOverridden ? previousDataRoot : null);
                RuntimeOptions.RestoreSnapshot(previousRuntimeOptions);
                Assert.Equal(previousRuntimeOptions, RuntimeOptions.CaptureSnapshot());
                SqliteConnection.ClearAllPools();
            }
        }
    }

    [Fact]
    public async Task StartupWithoutLegacyDatabaseKeepsPlainReadyMessage()
    {
        var previousDataRootWasOverridden = AppPaths.IsOverridden;
        var previousDataRoot = AppPaths.Root;
        var previousRuntimeOptions = RuntimeOptions.CaptureSnapshot();
        MainViewModel? viewModel = null;
        try
        {
            AppPaths.ConfigureDataRoot(_root);
            RuntimeOptions.Configure(disableNetwork: true);
            viewModel = CreateStartupViewModel();
            await viewModel.InitializeAsync();

            Assert.False(File.Exists(AppPaths.LegacyDatabasePath));
            Assert.Equal("本地录入已就绪", viewModel.StatusMessage);
            Assert.True(viewModel.IsQuickInputAvailable);
            Assert.NotNull(await viewModel.GetSessionAsync());
        }
        finally
        {
            try
            {
                if (viewModel is not null)
                {
                    await viewModel.DisposeAsync();
                }
            }
            finally
            {
                AppPaths.ConfigureDataRoot(previousDataRootWasOverridden ? previousDataRoot : null);
                RuntimeOptions.RestoreSnapshot(previousRuntimeOptions);
                Assert.Equal(previousRuntimeOptions, RuntimeOptions.CaptureSnapshot());
                SqliteConnection.ClearAllPools();
            }
        }
    }

    private MainViewModel CreateViewModel(CatalogService service) =>
        new(service, null, catalogDataRoot: _root);

    private MainViewModel CreateStartupViewModel()
    {
        var viewModel = new MainViewModel(
            new CatalogService((baseline, _, _) =>
                Task.FromResult((baseline, CreateReport(baseline)))),
            new NativeStore(),
            catalogDataRoot: AppPaths.DataRoot);
        viewModel.QthPackageTreeRefreshForTesting = _ => Task.CompletedTask;
        return viewModel;
    }

    private static async Task CreateLegacyDatabaseAsync(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = """
            PRAGMA user_version = 1;
            CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
            CREATE TABLE checkins(
                id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                callsign TEXT, raw_input TEXT, is_deleted INTEGER);
            INSERT INTO sessions VALUES(17, '旧版隔离场次', '2026-10-03');
            INSERT INTO checkins VALUES(91, 17, 1, 'BA4TEST', 'fixture legacy row', 0);
            """;
        await command.ExecuteNonQueryAsync();
    }

    private static async Task WriteMigrationMarkerAsync(string path, string marker)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWrite,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "INSERT INTO native_meta(key, value) VALUES('legacy_python_import', $marker)";
        command.Parameters.AddWithValue("$marker", marker);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<string> ReadScalarAsync(string path, string commandText)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadOnly,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        return (await command.ExecuteScalarAsync())?.ToString() ?? "";
    }

    private static async Task<CatalogService> CreateCatalogServiceWithSnapshotsAsync(
        CatalogSnapshot initial,
        CatalogSnapshot published)
    {
        var loadCount = 0;
        var service = new CatalogService((_, _, _) =>
        {
            var snapshot = Interlocked.Increment(ref loadCount) == 1 ? initial : published;
            return Task.FromResult((snapshot, CreateReport(snapshot)));
        });
        Assert.True((await service.ReloadExistingDataAsync()).Published);
        return service;
    }

    private static CatalogSnapshot CreateSnapshot(string deviceName) => new(
        new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal)
        {
            ["testalias"] = new(deviceName, "testalias", "", "", "", "isolated test")
        },
        new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal),
        new Dictionary<string, string>(StringComparer.Ordinal),
        new Dictionary<string, string>(StringComparer.Ordinal),
        new Dictionary<string, IReadOnlyList<QthCandidate>>(StringComparer.Ordinal));

    private static TaskCompletionSource<bool> NewSignalCompletion() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static TaskCompletionSource<(CatalogSnapshot Snapshot, CatalogLoadReport Report)> NewLoadCompletion() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static CatalogLoadReport CreateReport(CatalogSnapshot snapshot, bool succeeded = true) => new(
        "isolated test root",
        snapshot.DeviceAliasCount,
        snapshot.QthAliasCount,
        snapshot.QthPlaceCount,
        snapshot.MiitModelCount,
        0,
        "controlled test load")
    {
        Succeeded = succeeded
    };

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }
}
