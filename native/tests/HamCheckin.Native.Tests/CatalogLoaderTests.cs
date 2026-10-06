using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;
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

        Assert.Equal("摩托罗拉 R6", service.Current.ResolveDevice("r6")?.StandardName);
        Assert.Equal("测试省测试市测试区", service.Current.ResolveQth("testqth")?.Canonical);
        Assert.Equal(1, report.QthPlaceCount);
        Assert.Equal(1, report.MiitModelCount);
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

    private void CreateLegacyAliases()
    {
        using var connection = OpenCreate(Path.Combine(_root, "ham_checkin.db"));
        Execute(connection, """
            CREATE TABLE device_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE antenna_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE power_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                priority INTEGER, enabled INTEGER, source TEXT);
            CREATE TABLE qth_aliases(id INTEGER PRIMARY KEY, alias TEXT, standard_value TEXT,
                province TEXT, city TEXT, district TEXT, priority INTEGER, enabled INTEGER, source TEXT);
            INSERT INTO device_aliases VALUES(1, 'r6', '摩托罗拉 R6', 100, 1, 'user');
            INSERT INTO qth_aliases VALUES(
                1, 'testqth', '测试市测试区', '测试省', '测试市', '测试区', 100, 1, 'default');
            """);
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
