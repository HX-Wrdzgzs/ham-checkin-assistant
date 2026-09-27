using System.Net;
using System.Net.Http;
using System.Text;
using HamCheckin.Native.Core.Catalogs;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

public sealed class MiitCatalogSyncTests : IAsyncDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"ham-native-miit-{Guid.NewGuid():N}");
    private readonly MiitCatalogSyncService _service;

    public MiitCatalogSyncTests()
    {
        Directory.CreateDirectory(_root);
        var handler = new FixtureHandler();
        _service = new MiitCatalogSyncService(
            Path.Combine(_root, "miit_radio_catalog.db"),
            new HttpClient(handler));
    }

    [Fact]
    public void Sm3MatchesOfficialKnownVector()
    {
        Assert.Equal(
            "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0",
            Sm3.HashHex("abc"));
    }

    [Fact]
    public async Task FullSyncKeepsRadioRowsAndExcludesNonRadioRows()
    {
        var report = await _service.StartAsync(full: true);

        Assert.Equal("completed", report.Status);
        Assert.Equal(2, report.ScannedCount);
        Assert.Equal(1, report.RetainedCount);
        Assert.Equal(1, report.ExcludedCount);
        Assert.Equal(0, report.UnknownCount);

        await using var connection = new SqliteConnection($"Data Source={report.DatabasePath};Mode=ReadOnly");
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT standard_name, device_class FROM miit_radio_devices";
        await using var reader = await command.ExecuteReaderAsync();
        Assert.True(await reader.ReadAsync());
        Assert.Equal("泉盛 UV-K6", reader.GetString(0));
        Assert.Equal("手持台", reader.GetString(1));
        Assert.False(await reader.ReadAsync());
    }

    public async ValueTask DisposeAsync()
    {
        await _service.DisposeAsync();
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
    }

    private sealed class FixtureHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            const string payload = """
                {"success":true,"data":"{\"success\":true,\"data\":{\"tbAppArticle\":{\"total\":2,\"list\":[{\"articleId\":\"radio-1\",\"articleField02\":\"调频手持台\",\"articleField03\":\"UV-K6\",\"articleField04\":\"泉盛电子\",\"articleField12\":\"2026-01-01\"},{\"articleId\":\"phone-1\",\"articleField02\":\"蓝牙设备\",\"articleField03\":\"K6\",\"articleField04\":\"测试单位\"}]}}}"}
                """;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json")
            });
        }
    }
}
