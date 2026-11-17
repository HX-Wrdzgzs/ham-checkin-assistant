using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

public sealed class CatalogLoaderTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"ham-native-catalog-{Guid.NewGuid():N}");

    [Fact]
    public async Task LocalAliasBeatsSameNamedMiitModel()
    {
        Directory.CreateDirectory(_root);
        CreateLegacyAliases();
        CreateMiitCatalog();
        CreateQthCatalog();

        var service = new CatalogService();
        var report = await service.ReloadExistingDataAsync(_root);

        Assert.True(report.Succeeded);
        Assert.True(report.Published);
        Assert.Equal(1, report.Generation);
        Assert.Equal("摩托罗拉 R6", service.Current.ResolveDevice("r6")?.StandardName);
        Assert.Equal("测试省测试市测试区", service.Current.ResolveQth("testqth")?.Canonical);
        Assert.Equal(1, report.QthPlaceCount);
        Assert.Equal(1, report.MiitModelCount);
        AssertReportMatchesCurrent(report, service.Current);
    }

    [Fact]
    public async Task ReloadRebuildsOverlayAndRemovesDeletedOrDisabledAliases()
    {
        Directory.CreateDirectory(_root);
        CreateLegacyAliases();

        var service = new CatalogService();
        var builtIn = service.Current;
        var initial = await service.ReloadExistingDataAsync(_root);
        Assert.True(initial.Published);

        using var connection = OpenCreate(Path.Combine(_root, "ham_checkin.db"));
        Execute(connection, "UPDATE device_aliases SET standard_value = '已修改' WHERE alias = 'r6';");
        var changed = await service.ReloadExistingDataAsync(_root);
        Assert.True(changed.Published);
        Assert.Equal("已修改", service.Current.ResolveDevice("r6")?.StandardName);
        AssertReportMatchesCurrent(changed, service.Current);

        Execute(connection, "DELETE FROM device_aliases WHERE alias = 'r6';");
        var deleted = await service.ReloadExistingDataAsync(_root);
        Assert.True(deleted.Published);
        Assert.Equal(builtIn.ResolveDevice("r6")?.StandardName, service.Current.ResolveDevice("r6")?.StandardName);
        AssertReportMatchesCurrent(deleted, service.Current);

        Execute(connection, "INSERT INTO device_aliases VALUES(2, 'disableme', '启用时', 100, 1, 'user');");
        var enabled = await service.ReloadExistingDataAsync(_root);
        Assert.True(enabled.Published);
        Assert.Equal("启用时", service.Current.ResolveDevice("disableme")?.StandardName);
        Execute(connection, "UPDATE device_aliases SET enabled = 0, standard_value = '禁用后' WHERE alias = 'disableme';");
        var disabled = await service.ReloadExistingDataAsync(_root);
        Assert.True(disabled.Published);
        Assert.Equal(builtIn.ResolveDevice("disableme")?.StandardName, service.Current.ResolveDevice("disableme")?.StandardName);
        Assert.Equal(builtIn.ResolveDevice("k1")?.StandardName, service.Current.ResolveDevice("k1")?.StandardName);
        AssertReportMatchesCurrent(disabled, service.Current);
    }

    [Fact]
    public async Task DeviceAliasCollisionPrefersUserAndHigherPriorityAndIgnoresDisabledRow()
    {
        Directory.CreateDirectory(_root);
        CreateLegacyAliases();
        using var connection = OpenCreate(Path.Combine(_root, "ham_checkin.db"));
        Execute(connection, """
            INSERT INTO device_aliases VALUES
                (2, 'uv-5r', 'Default high priority', 1000, 1, 'default'),
                (3, 'uv5r', 'User lower priority', 10, 1, 'user'),
                (4, 'uv-5r', 'User higher priority', 20, 1, 'user'),
                (5, 'uv5r', 'Disabled user higher priority', 10000, 0, 'user');
            """);

        var builtIn = CatalogLoader.CreateBuiltIn();
        var service = new CatalogService();
        var report = await service.ReloadExistingDataAsync(_root);

        Assert.True(report.Succeeded);
        Assert.True(report.Published);
        Assert.Equal("User higher priority", service.Current.ResolveDevice("uv-5r")?.StandardName);
        Assert.Equal("User higher priority", service.Current.ResolveDevice("uv5r")?.StandardName);
        Assert.Equal("用户别名", service.Current.ResolveDevice("uv5r")?.Source);
        Assert.Equal(builtIn.ResolveDevice("k1")?.StandardName, service.Current.ResolveDevice("k1")?.StandardName);
        AssertReportMatchesCurrent(report, service.Current);
    }

    [Fact]
    public async Task SwitchingDataRootDropsPreviousRootOverlayAndRetainsBuiltIns()
    {
        var rootA = Path.Combine(_root, "A");
        var rootB = Path.Combine(_root, "B");
        CreateLegacyAliases(rootA, "roota", "根目录 A");
        CreateLegacyAliases(rootB, "rootb", "根目录 B");
        var service = new CatalogService();
        var builtInDevice = service.Current.ResolveDevice("k1")?.StandardName;

        var first = await service.ReloadExistingDataAsync(rootA);
        Assert.True(first.Published);
        Assert.Equal("根目录 A", service.Current.ResolveDevice("roota")?.StandardName);

        var second = await service.ReloadExistingDataAsync(rootB);
        Assert.True(second.Published);
        Assert.Null(service.Current.ResolveDevice("roota"));
        Assert.Equal("根目录 B", service.Current.ResolveDevice("rootb")?.StandardName);
        Assert.Equal(builtInDevice, service.Current.ResolveDevice("k1")?.StandardName);
        AssertReportMatchesCurrent(second, service.Current);
    }

    [Fact]
    public async Task SameQthAliasKeepsDifferentCanonicalCandidatesAmbiguous()
    {
        Directory.CreateDirectory(_root);
        CreateQthCatalog();
        using (var connection = OpenCreate(Path.Combine(_root, "qth_places.db")))
        {
            Execute(connection, "INSERT INTO qth_places VALUES('另一测试区', 'testqth', '其他省', '其他市', '另一测试区', '其他省其他市另一测试区', 'admin_region');");
        }

        var service = new CatalogService();
        var report = await service.ReloadExistingDataAsync(_root);

        Assert.True(report.Published);
        Assert.Equal(2, service.Current.ResolveQthCandidates("testqth").Count);
        Assert.Null(service.Current.ResolveQth("testqth"));
        AssertReportMatchesCurrent(report, service.Current);
    }

    [Fact]
    public async Task MissingOverlayFilesPublishBuiltInSnapshotSuccessfully()
    {
        Directory.CreateDirectory(_root);
        var service = new CatalogService();

        var report = await service.ReloadExistingDataAsync(_root);

        Assert.True(report.Succeeded);
        Assert.True(report.Published);
        AssertReportMatchesCurrent(report, service.Current);
    }

    [Fact]
    public async Task SourceReadFailureDoesNotPublishPartialSnapshot()
    {
        Directory.CreateDirectory(_root);
        using (var connection = OpenCreate(Path.Combine(_root, "miit_radio_catalog.db")))
        {
            Execute(connection, "CREATE TABLE unexpected_schema(value TEXT);");
        }

        var service = new CatalogService();
        var previous = service.Current;
        var report = await service.ReloadExistingDataAsync(_root);

        Assert.False(report.Succeeded);
        Assert.False(report.Published);
        Assert.Equal(1, report.Generation);
        Assert.Same(previous, service.Current);
        Assert.Contains("工信部库未载入", report.Message);
    }

    [Fact]
    public async Task QthCatalogReadFailureKeepsLastPublishedSnapshot()
    {
        Directory.CreateDirectory(_root);
        CreateQthCatalog();
        var service = new CatalogService();
        Assert.True((await service.ReloadExistingDataAsync(_root)).Published);
        var previous = service.Current;
        var previousQth = previous.ResolveQth("testqth")?.Canonical;

        SqliteConnection.ClearAllPools();
        var qthPath = Path.Combine(_root, "qth_places.db");
        File.Delete(qthPath);
        Directory.CreateDirectory(qthPath);

        var report = await service.ReloadExistingDataAsync(_root);

        Assert.False(report.Succeeded);
        Assert.False(report.Published);
        Assert.Same(previous, service.Current);
        Assert.Equal(previousQth, service.Current.ResolveQth("testqth")?.Canonical);
        Assert.Contains("地点库未载入", report.Message);
    }

    [Fact]
    public async Task LegacyAliasReadFailureKeepsLastPublishedSnapshot()
    {
        Directory.CreateDirectory(_root);
        CreateLegacyAliases();
        var service = new CatalogService();
        Assert.True((await service.ReloadExistingDataAsync(_root)).Published);
        var previous = service.Current;
        var previousDevice = previous.ResolveDevice("r6")?.StandardName;

        SqliteConnection.ClearAllPools();
        var legacyPath = Path.Combine(_root, "ham_checkin.db");
        File.Delete(legacyPath);
        Directory.CreateDirectory(legacyPath);

        var report = await service.ReloadExistingDataAsync(_root);

        Assert.False(report.Succeeded);
        Assert.False(report.Published);
        Assert.Same(previous, service.Current);
        Assert.Equal(previousDevice, service.Current.ResolveDevice("r6")?.StandardName);
        Assert.Contains("旧别名未载入", report.Message);
    }

    [Fact]
    public void CatalogLoadReportEqualityIgnoresNonPositionalPublicationMetadata()
    {
        var original = new CatalogLoadReport("root", 1, 2, 3, 4, 5, "message");
        var decorated = original with { Generation = 7, Succeeded = false, Published = true };

        Assert.Equal(original, decorated);
        Assert.Equal(original.GetHashCode(), decorated.GetHashCode());
        Assert.True(original == decorated);
    }

    [Fact]
    public async Task NewerSuccessfulGenerationPublishesAndRejectsOlderCompletion()
    {
        var olderLoad = NewLoadCompletion();
        var newerLoad = NewLoadCompletion();
        var service = new CatalogService((_, root, _) => root == "older" ? olderLoad.Task : newerLoad.Task);

        var olderTask = service.ReloadExistingDataAsync("older");
        var newerTask = service.ReloadExistingDataAsync("newer");
        var newerSnapshot = CatalogLoader.CreateBuiltIn();
        newerLoad.SetResult((newerSnapshot, CreateReport(newerSnapshot, "newer")));
        var newerReport = await newerTask;

        Assert.Equal(2, newerReport.Generation);
        Assert.True(newerReport.Published);
        Assert.Same(newerSnapshot, service.Current);

        var olderSnapshot = CatalogLoader.CreateBuiltIn();
        olderLoad.SetResult((olderSnapshot, CreateReport(olderSnapshot, "older")));
        var olderReport = await olderTask;

        Assert.Equal(1, olderReport.Generation);
        Assert.True(olderReport.Succeeded);
        Assert.False(olderReport.Published);
        Assert.Same(newerSnapshot, service.Current);
    }

    [Fact]
    public async Task LatestFailureKeepsLastPublishedSnapshotAndRejectsOlderSuccess()
    {
        var loads = new Dictionary<string, TaskCompletionSource<(CatalogSnapshot Snapshot, CatalogLoadReport Report)>>
        {
            ["initial"] = NewLoadCompletion(),
            ["older"] = NewLoadCompletion(),
            ["failure"] = NewLoadCompletion()
        };
        var service = new CatalogService((_, root, _) => loads[root!].Task);

        var initialTask = service.ReloadExistingDataAsync("initial");
        var lastValidSnapshot = CatalogLoader.CreateBuiltIn();
        loads["initial"].SetResult((lastValidSnapshot, CreateReport(lastValidSnapshot, "initial")));
        Assert.True((await initialTask).Published);

        var olderTask = service.ReloadExistingDataAsync("older");
        var failedTask = service.ReloadExistingDataAsync("failure");
        var failedSnapshot = CatalogLoader.CreateBuiltIn();
        loads["failure"].SetResult((failedSnapshot, CreateReport(failedSnapshot, "failure", succeeded: false)));
        var failedReport = await failedTask;

        Assert.Equal(3, failedReport.Generation);
        Assert.False(failedReport.Succeeded);
        Assert.False(failedReport.Published);
        Assert.Same(lastValidSnapshot, service.Current);

        var olderSnapshot = CatalogLoader.CreateBuiltIn();
        loads["older"].SetResult((olderSnapshot, CreateReport(olderSnapshot, "older")));
        var olderReport = await olderTask;
        Assert.False(olderReport.Published);
        Assert.Same(lastValidSnapshot, service.Current);
    }

    [Fact]
    public async Task LatestCancellationKeepsLastPublishedSnapshotAndRejectsOlderSuccess()
    {
        var olderLoad = NewLoadCompletion();
        var cancelledLoad = NewLoadCompletion();
        var initialSnapshot = CatalogLoader.CreateBuiltIn();
        var initialLoad = NewLoadCompletion();
        var initializedService = new CatalogService((_, root, cancellationToken) =>
            root == "cancelled" ? cancelledLoad.Task.WaitAsync(cancellationToken)
                : root == "older" ? olderLoad.Task : initialLoad.Task);
        var initialTask = initializedService.ReloadExistingDataAsync("initial");
        initialLoad.SetResult((initialSnapshot, CreateReport(initialSnapshot, "initial")));
        Assert.True((await initialTask).Published);

        var olderTask = initializedService.ReloadExistingDataAsync("older");
        using var cancellation = new CancellationTokenSource();
        var cancelledTask = initializedService.ReloadExistingDataAsync("cancelled", cancellation.Token);
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => cancelledTask);
        Assert.Same(initialSnapshot, initializedService.Current);

        var olderSnapshot = CatalogLoader.CreateBuiltIn();
        olderLoad.SetResult((olderSnapshot, CreateReport(olderSnapshot, "older")));
        var olderReport = await olderTask;
        Assert.Equal(2, olderReport.Generation);
        Assert.False(olderReport.Published);
        Assert.Same(initialSnapshot, initializedService.Current);
    }

    [Fact]
    public async Task UnknownModelSearchReturnsNearbyCandidatesWithoutAutoMapping()
    {
        Directory.CreateDirectory(_root);
        CreateLegacyAliases();
        CreateMiitCatalog(includeUnknownModelVariants: true);
        CreateQthCatalog();

        var service = new CatalogService();
        await service.ReloadExistingDataAsync(_root);

        var candidates = service.Current.SearchDevices("pd660pro", 8);
        Assert.Contains(candidates, item => item.StandardName == "海能达 PD660 VHF");
        Assert.Contains(candidates, item => item.StandardName == "海能达 PD660 Um");

        var fieldResult = new FieldParser(service).Parse(FieldKind.Device, "pd660pro");
        Assert.Equal("pd660pro", fieldResult.CanonicalValue);
        Assert.True(fieldResult.RequiresConfirmation);
        Assert.Contains("海能达 PD660 VHF", fieldResult.Candidates);
    }

    [Fact]
    public void ShortDeviceSearchDoesNotSuggestAnEmbeddedUnrelatedAlias()
    {
        var catalog = CatalogLoader.CreateBuiltIn();

        var candidates = catalog.SearchDevices("k1", 8);

        Assert.Contains(candidates, item => item.StandardName == "泉盛 UV-K1");
        Assert.DoesNotContain(candidates, item => item.StandardName == "泉盛 TK11");
    }

    [Fact]
    public void DefaultDataRootFollowsConfiguredAppPaths()
    {
        AppPaths.ConfigureDataRoot(_root);
        try
        {
            Assert.Equal(Path.Combine(Path.GetFullPath(_root), "data"), CatalogLoader.DefaultDataRoot);
        }
        finally
        {
            AppPaths.ConfigureDataRoot(null);
        }
    }

    private void CreateLegacyAliases(
        string? dataRoot = null,
        string deviceAlias = "r6",
        string standardValue = "摩托罗拉 R6")
    {
        dataRoot ??= _root;
        Directory.CreateDirectory(dataRoot);
        using var connection = OpenCreate(Path.Combine(dataRoot, "ham_checkin.db"));
        Execute(connection, """
            CREATE TABLE device_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE antenna_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE power_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE qth_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                province TEXT, city TEXT, district TEXT, priority INTEGER, enabled INTEGER, source TEXT);
            INSERT INTO qth_aliases VALUES(
                1, 'testqth', '测试市测试区', '测试省', '测试市', '测试区', 100, 1, 'default');
            """);
        Execute(connection, $"INSERT INTO device_aliases VALUES(1, '{deviceAlias}', '{standardValue}', 100, 1, 'user');");
    }

    private void CreateMiitCatalog(bool includeUnknownModelVariants = false)
    {
        using var connection = OpenCreate(Path.Combine(_root, "miit_radio_catalog.db"));
        Execute(connection, """
            CREATE TABLE miit_radio_devices(normalized_model TEXT, standard_name TEXT,
                model TEXT, device_name TEXT, applicant TEXT, brand TEXT, approved_at TEXT);
            INSERT INTO miit_radio_devices VALUES(
                'r6', 'R6', 'R6', '调频手持台', '其他公司', '', '2026-01-01');
            """);

        if (includeUnknownModelVariants)
        {
            Execute(connection, """
                INSERT INTO miit_radio_devices VALUES(
                    'pd660um', '海能达 PD660 Um', 'PD660 Um', '数字对讲机系统手持台', '海能达通信股份有限公司', '海能达', '2026-01-02');
                INSERT INTO miit_radio_devices VALUES(
                    'pd660vhf', '海能达 PD660 VHF', 'PD660 VHF', '数字对讲机手持台', '海能达通信股份有限公司', '海能达', '2026-01-03');
                """);
        }
    }

    private void CreateQthCatalog()
    {
        using var connection = OpenCreate(Path.Combine(_root, "qth_places.db"));
        Execute(connection, """
            CREATE TABLE qth_places(name TEXT, aliases TEXT, province TEXT, city TEXT,
                district TEXT, canonical_qth TEXT, kind TEXT);
            INSERT INTO qth_places VALUES(
                '测试区', '测试区|testqth', '测试省', '测试市', '测试区',
                '测试省测试市测试区', 'admin_region');
            """);
    }

    private static TaskCompletionSource<(CatalogSnapshot Snapshot, CatalogLoadReport Report)> NewLoadCompletion() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private static CatalogLoadReport CreateReport(CatalogSnapshot snapshot, string dataRoot, bool succeeded = true) => new(
        dataRoot,
        snapshot.DeviceAliasCount,
        snapshot.QthAliasCount,
        snapshot.QthPlaceCount,
        snapshot.MiitModelCount,
        0,
        "controlled test load")
    {
        Succeeded = succeeded
    };

    private static void AssertReportMatchesCurrent(CatalogLoadReport report, CatalogSnapshot current)
    {
        Assert.Equal(current.DeviceAliasCount, report.DeviceAliasCount);
        Assert.Equal(current.QthAliasCount, report.QthAliasCount);
        Assert.Equal(current.QthPlaceCount, report.QthPlaceCount);
        Assert.Equal(current.MiitModelCount, report.MiitModelCount);
    }

    private static SqliteConnection OpenCreate(string path)
    {
        var connection = new SqliteConnection($"Data Source={path}");
        connection.Open();
        return connection;
    }

    private static void Execute(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
    }
}
