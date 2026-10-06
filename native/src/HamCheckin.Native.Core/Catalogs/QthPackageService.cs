using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Catalogs;

/// <summary>
/// 读取地点库的省/市安装状态。地点包是 QTH 索引，不是地图瓦片；读取和搜索
/// 只依赖本地 SQLite，不会因为输入一个地点而联网。
/// </summary>
public sealed class QthPackageService
{
    public static async Task<IReadOnlyList<QthPackageNode>> LoadInstalledTreeAsync(
        string? dataRoot = null,
        CancellationToken cancellationToken = default)
    {
        var root = dataRoot ?? AppPaths.DataRoot;
        var path = File.Exists(Path.Combine(root, "qth_admin.db"))
            ? Path.Combine(root, "qth_admin.db")
            : Path.Combine(root, "qth_places.db");
        if (!File.Exists(path))
        {
            // The administrative snapshot is part of the application and must
            // remain visible even before a detailed place package is installed.
            // Returning an empty tree made the UI look as if only the few
            // downloaded provinces existed.
            return BuildNationwideTree(new Dictionary<(string Province, string City), int>());
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
            var counts = new Dictionary<(string Province, string City), int>();
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
                counts[(province, city)] = count;
            }

            return BuildNationwideTree(counts);
        }, cancellationToken).ConfigureAwait(false);
    }

    private static QthPackageNode[] BuildNationwideTree(
        IReadOnlyDictionary<(string Province, string City), int> installedCounts)
    {
        var provinceCities = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);

        foreach (var entry in NationwideAdminCatalog.Entries.Where(static item =>
                     string.Equals(item.Kind, "admin_region", StringComparison.Ordinal)
                     && !string.IsNullOrWhiteSpace(item.Province)))
        {
            // Municipalities have no separate City column in the source
            // snapshot. Showing the municipality as its own child keeps the
            // province/city tree usable and consistent with other provinces.
            var city = string.IsNullOrWhiteSpace(entry.City)
                ? entry.Province
                : entry.City;
            if (!provinceCities.TryGetValue(entry.Province, out var cities))
            {
                cities = new HashSet<string>(StringComparer.Ordinal);
                provinceCities[entry.Province] = cities;
            }
            cities.Add(city);
        }

        // Preserve a package that contains a newly added or custom province
        // even if it is not in the embedded administrative snapshot yet.
        foreach (var key in installedCounts.Keys)
        {
            if (!provinceCities.TryGetValue(key.Province, out var cities))
            {
                cities = new HashSet<string>(StringComparer.Ordinal);
                provinceCities[key.Province] = cities;
            }
            cities.Add(string.IsNullOrWhiteSpace(key.City) ? key.Province : key.City);
        }

        return provinceCities
            .OrderBy(static item => item.Key, StringComparer.Ordinal)
            .Select(item =>
            {
                var children = item.Value
                    .OrderBy(static city => city, StringComparer.Ordinal)
                    .Select(city =>
                    {
                        var count = installedCounts.GetValueOrDefault((item.Key, city))
                            + (city == item.Key
                                ? installedCounts.GetValueOrDefault((item.Key, ""))
                                : 0);
                        return new QthPackageNode(
                            city,
                            "城市",
                            count > 0 ? "已安装" : "未下载",
                            count > 0 ? $"{count:N0} 条本地点" : "可下载城市包",
                            count > 0,
                            false);
                    })
                    .ToArray();
                var provinceCount = children
                    .Where(static child => child.IsInstalled)
                    .Sum(static child => ParseCount(child.Detail));
                var allInstalled = children.Length > 0 && children.All(static child => child.IsInstalled);
                var anyInstalled = children.Any(static child => child.IsInstalled);
                return new QthPackageNode(
                    item.Key,
                    "省",
                    allInstalled ? "已安装" : anyInstalled ? "部分安装" : "未下载",
                    provinceCount > 0
                        ? $"{provinceCount:N0} 条本地点 · 可展开选择城市"
                        : "可选择城市或下载全省",
                    anyInstalled,
                    false,
                    children);
            })
            .ToArray();
    }

    private static int ParseCount(string detail)
    {
        var number = new string(detail.TakeWhile(static character =>
            char.IsDigit(character) || character == ',').ToArray());
        return int.TryParse(number, System.Globalization.NumberStyles.AllowThousands,
            System.Globalization.CultureInfo.InvariantCulture, out var value)
            ? value
            : 0;
    }
}
