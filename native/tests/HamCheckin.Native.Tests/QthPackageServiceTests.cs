using HamCheckin.Native.Core.Catalogs;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

public sealed class QthPackageServiceTests : IAsyncLifetime
{
    private string _root = string.Empty;

    public Task InitializeAsync()
    {
        _root = Path.Combine(Path.GetTempPath(), $"ham-native-qth-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_root);
        return Task.CompletedTask;
    }

    [Fact]
    public async Task ShowsNationwideAdministrativeTreeAndMergesInstalledPlaces()
    {
        var path = Path.Combine(_root, "qth_places.db");
        await using (var connection = new SqliteConnection($"Data Source={path}"))
        {
            await connection.OpenAsync();
            await using var command = connection.CreateCommand();
            command.CommandText = """
                CREATE TABLE qth_places (
                    province TEXT NOT NULL,
                    city TEXT NOT NULL
                );
                INSERT INTO qth_places(province, city) VALUES
                    ('江苏省', '南京市'), ('江苏省', '南京市'),
                    ('江苏省', '扬州市'), ('安徽省', '芜湖市');
                """;
            await command.ExecuteNonQueryAsync();
        }

        var tree = await QthPackageService.LoadInstalledTreeAsync(_root);

        // The tree is intentionally nationwide even when only a few detailed
        // place rows are installed.  “未下载” is a real state, not an absent
        // province.
        Assert.True(tree.Count >= 31);
        var jiangsu = Assert.Single(tree, node => node.Name == "江苏省");
        Assert.Equal("部分安装", jiangsu.Status);
        Assert.StartsWith("3 条本地点", jiangsu.Detail, StringComparison.Ordinal);
        Assert.True(jiangsu.Children!.Count >= 13);
        Assert.Contains(jiangsu.Children!, node => node.Name == "南京市" && node.Detail == "2 条本地点");
        Assert.Contains(jiangsu.Children!, node => node.Name == "扬州市" && node.Detail == "1 条本地点");

        var anhui = Assert.Single(tree, node => node.Name == "安徽省");
        Assert.Equal("部分安装", anhui.Status);
        Assert.Contains(anhui.Children!, node => node.Name == "芜湖市" && node.Detail == "1 条本地点");

        var guangdong = Assert.Single(tree, node => node.Name == "广东省");
        Assert.Equal("未下载", guangdong.Status);
        Assert.Contains(guangdong.Children!, node => node.Name == "广州市" && node.Status == "未下载");
    }

    [Fact]
    public async Task ShowsNationwideTreeBeforeAnyDetailedPackageIsInstalled()
    {
        var tree = await QthPackageService.LoadInstalledTreeAsync(_root);

        Assert.True(tree.Count >= 31);
        Assert.All(tree, province =>
        {
            Assert.Equal("未下载", province.Status);
            Assert.NotEmpty(province.Children!);
        });
        Assert.Contains(tree, node => node.Name == "广东省");
        Assert.Contains(tree, node => node.Name == "新疆维吾尔自治区");
        Assert.Contains(tree.Single(node => node.Name == "广东省").Children!,
            node => node.Name == "深圳市" && node.Status == "未下载");
    }

    public Task DisposeAsync()
    {
        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
        return Task.CompletedTask;
    }
}
