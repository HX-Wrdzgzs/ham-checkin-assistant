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
    public async Task GroupsInstalledPlacesByProvinceAndCity()
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

        var tree = await new QthPackageService().LoadInstalledTreeAsync(_root);

        Assert.Equal(2, tree.Count);
        var jiangsu = Assert.Single(tree, node => node.Name == "江苏省");
        Assert.Equal("3 条本地点", jiangsu.Detail);
        Assert.Equal(2, jiangsu.Children?.Count);
        Assert.Contains(jiangsu.Children!, node => node.Name == "南京市" && node.Detail == "2 条本地点");
        Assert.Contains(jiangsu.Children!, node => node.Name == "扬州市" && node.Detail == "1 条本地点");
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
