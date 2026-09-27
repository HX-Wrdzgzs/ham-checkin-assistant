using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Storage;

public static class LegacyProfileReader
{
    public static Task<IReadOnlyList<ProfileValue>> ReadAsync(
        string callsign,
        string? databasePath = null,
        CancellationToken cancellationToken = default) => Task.Run<IReadOnlyList<ProfileValue>>(() =>
    {
        var path = databasePath ?? AppPaths.LegacyDatabasePath;
        if (string.IsNullOrWhiteSpace(callsign) || !File.Exists(path))
        {
            return Array.Empty<ProfileValue>();
        }

        var connectionString = new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Shared,
            Pooling = true
        }.ToString();
        using var connection = new SqliteConnection(connectionString);
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT qth_standard, device_standard, antenna_standard, power_standard,
                   COALESCE(updated_at, created_at, '')
            FROM checkins
            WHERE callsign = $callsign AND is_deleted = 0
            ORDER BY id DESC
            LIMIT 300
            """;
        command.Parameters.AddWithValue("$callsign", callsign);
        using var reader = command.ExecuteReader();
        var rows = new List<(string Qth, string Device, string Antenna, string Power, string At)>();
        while (reader.Read())
        {
            cancellationToken.ThrowIfCancellationRequested();
            rows.Add((
                reader.IsDBNull(0) ? "" : reader.GetString(0),
                reader.IsDBNull(1) ? "" : reader.GetString(1),
                reader.IsDBNull(2) ? "" : reader.GetString(2),
                reader.IsDBNull(3) ? "" : reader.GetString(3),
                reader.IsDBNull(4) ? "" : reader.GetString(4)));
        }
        return ProfileAggregator.Aggregate(rows);
    }, cancellationToken);
}
