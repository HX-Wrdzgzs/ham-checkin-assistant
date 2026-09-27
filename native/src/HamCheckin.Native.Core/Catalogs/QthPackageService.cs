using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Catalogs;

/// <summary>
/// 读取地点库的省/市安装状态。地点包是 QTH 索引，不是地图瓦片；读取和搜索
/// 只依赖本地 SQLite，不会因为输入一个地点而联网。
/// </summary>
public sealed class QthPackageService
{
    public async Task<IReadOnlyList<QthPackageNode>> LoadInstalledTreeAsync(
        string? dataRoot = null,
        CancellationToken cancellationToken = default)
    {
        var root = dataRoot ?? AppPaths.DataRoot;
        var path = File.Exists(Path.Combine(root, "qth_admin.db"))
            ? Path.Combine(root, "qth_admin.db")
            : Path.Combine(root, "qth_places.db");
        if (!File.Exists(path))
        {
            return Array.Empty<QthPackageNode>();
        }

        return await Task.Run(async () =>
        {
            await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
            {
                DataSource = path,
                Mode = SqliteOpenMode.ReadOnly,
                Cache = SqliteCacheMode.Shared,
                Pooling = true
            }.ToString());
            await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var command = connection.CreateCommand();
            command.CommandText = """
                SELECT COALESCE(province, ''), COALESCE(city, ''), COUNT(*)
                FROM qth_places
                GROUP BY province, city
                ORDER BY province, city
                """;
            await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
            var provinces = new Dictionary<string, List<QthPackageNode>>(StringComparer.Ordinal);
            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
            {
                var province = reader.GetString(0);
                var city = reader.GetString(1);
                // SQLite COUNT(*) is an Int64 even when the practical result fits Int32.
                var count = checked((int)reader.GetInt64(2));
                if (province.Length == 0)
                {
                    continue;
                }
                if (!provinces.TryGetValue(province, out var children))
                {
                    children = new List<QthPackageNode>();
                    provinces[province] = children;
                }
                counts[province] = counts.GetValueOrDefault(province) + count;
                if (city.Length > 0)
                {
                    children.Add(new QthPackageNode(
                        city, "城市", "已安装", $"{count:N0} 条本地点", true, false));
                }
            }

            return (IReadOnlyList<QthPackageNode>)provinces
                .OrderBy(item => item.Key, StringComparer.Ordinal)
                .Select(item => new QthPackageNode(
                    item.Key, "省", "已安装", $"{counts[item.Key]:N0} 条本地点",
                    true, false, item.Value))
                .ToArray();
        }, cancellationToken).ConfigureAwait(false);
    }
}
