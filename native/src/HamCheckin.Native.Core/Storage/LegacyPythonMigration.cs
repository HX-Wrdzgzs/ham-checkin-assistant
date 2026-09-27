using System.Globalization;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Storage;

public sealed record LegacyImportResult(
    bool FoundLegacyDatabase,
    bool Imported,
    int ImportedSessions,
    int ImportedCheckins,
    int SkippedCheckins,
    string BackupPath,
    string Message);

/// <summary>
/// Native 1.0.0 首次运行时把旧 Python 数据库复制到 Native 数据库。
/// 旧文件只读，导入前生成独立备份；导入失败不会改写旧库，也不会把半成品
/// 标记成已完成。后续启动通过 native_meta 标记避免重复导入。
/// </summary>
public static class LegacyPythonMigration
{
    private const string MigrationKey = "legacy_python_import";

    public static async Task<LegacyImportResult> TryImportAsync(
        string nativeDatabasePath,
        string legacyDatabasePath,
        string backupRoot,
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(legacyDatabasePath))
        {
            return new(false, false, 0, 0, 0, "", "没有发现旧版 Python 数据库。");
        }

        var nativeDirectory = Path.GetDirectoryName(nativeDatabasePath)
            ?? throw new InvalidOperationException("无法确定原生数据库目录。");
        Directory.CreateDirectory(nativeDirectory);
        Directory.CreateDirectory(backupRoot);

        await using var native = await OpenAsync(nativeDatabasePath, SqliteOpenMode.ReadWriteCreate,
            cancellationToken).ConfigureAwait(false);
        if (await HasCompletedMarkerAsync(native, cancellationToken).ConfigureAwait(false))
        {
            return new(true, false, 0, 0, 0, "", "旧版数据库已经完成过迁移。");
        }

        var nativeCheckinCount = await ScalarIntAsync(native,
            "SELECT COUNT(*) FROM checkins WHERE is_deleted = 0", cancellationToken).ConfigureAwait(false);
        if (nativeCheckinCount > 0)
        {
            await WriteMarkerAsync(native, new
            {
                status = "skipped-native-data-exists",
                source = legacyDatabasePath,
                at = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture)
            }, cancellationToken).ConfigureAwait(false);
            return new(true, false, 0, 0, 0, "", "原生数据库已有签到记录，未自动合并旧库；旧库保持不变。");
        }

        var backupPath = await CreateBackupAsync(legacyDatabasePath, backupRoot, cancellationToken)
            .ConfigureAwait(false);
        var legacy = await ReadLegacyAsync(legacyDatabasePath, cancellationToken).ConfigureAwait(false);
        if (!legacy.HasRequiredTables)
        {
            return new(true, false, 0, 0, 0, backupPath, "旧版数据库缺少 sessions/checkins 表，未导入。");
        }

        await using var transaction = await native.BeginTransactionAsync(
            System.Data.IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false);
        var sqliteTransaction = (SqliteTransaction)transaction;
        var sessionMap = new Dictionary<long, long>();
        var importedSessions = 0;
        var importedCheckins = 0;
        var skippedCheckins = 0;

        foreach (var oldSession in legacy.Sessions)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var date = string.IsNullOrWhiteSpace(oldSession.Date) ? "1970-01-01" : oldSession.Date;
            var name = string.IsNullOrWhiteSpace(oldSession.Name) ? "旧版场次" : oldSession.Name;
            var existing = await FindSessionAsync(native, sqliteTransaction, date, name, cancellationToken)
                .ConfigureAwait(false);
            if (existing is null)
            {
                await using var insert = native.CreateCommand();
                insert.Transaction = sqliteTransaction;
                insert.CommandText = """
                    INSERT INTO sessions(
                        name, date, status, operator_callsign, repeater_name,
                        workbook_path, sheet_name, started_at, ended_at, created_at, updated_at)
                    VALUES($name, $date, $status, $operator, $repeater,
                           $workbook, $sheet, $started, $ended, $created, $updated)
                    """;
                Add(insert, "$name", name);
                Add(insert, "$date", date);
                Add(insert, "$status", NormalizeStatus(oldSession.Status));
                Add(insert, "$operator", oldSession.OperatorCallsign);
                Add(insert, "$repeater", oldSession.RepeaterName);
                Add(insert, "$workbook", oldSession.ExcelPath);
                Add(insert, "$sheet", oldSession.ExcelSheetName);
                Add(insert, "$started", FallbackNow(oldSession.StartedAt));
                Add(insert, "$ended", oldSession.EndedAt);
                Add(insert, "$created", FallbackNow(oldSession.CreatedAt));
                Add(insert, "$updated", FallbackNow(oldSession.UpdatedAt));
                await insert.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
                importedSessions++;
                existing = await FindSessionAsync(native, sqliteTransaction, date, name, cancellationToken)
                    .ConfigureAwait(false);
            }

            if (existing is not null)
            {
                sessionMap[oldSession.Id] = existing.Value;
            }
        }

        foreach (var oldCheckin in legacy.Checkins)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (oldCheckin.IsDeleted != 0 || !sessionMap.TryGetValue(oldCheckin.SessionId, out var sessionId))
            {
                skippedCheckins++;
                continue;
            }

            var submissionId = $"legacy-python:{oldCheckin.Id}";
            if (await ExistsAsync(native, sqliteTransaction,
                    "SELECT 1 FROM checkins WHERE submission_id = $submission LIMIT 1",
                    new[] { ("$submission", (object)submissionId) }, cancellationToken)
                .ConfigureAwait(false))
            {
                skippedCheckins++;
                continue;
            }

            var sequence = oldCheckin.SequenceNo > 0
                ? oldCheckin.SequenceNo
                : 1;
            while (await ExistsAsync(native, sqliteTransaction,
                       "SELECT 1 FROM checkins WHERE session_id = $session AND sequence_no = $sequence AND is_deleted = 0 LIMIT 1",
                       new[] { ("$session", (object)sessionId), ("$sequence", (object)sequence) },
                       cancellationToken).ConfigureAwait(false))
            {
                sequence++;
            }

            await using var insertCheckin = native.CreateCommand();
            insertCheckin.Transaction = sqliteTransaction;
            insertCheckin.CommandText = """
                INSERT INTO checkins(
                    submission_id, session_id, sequence_no, checkin_time, callsign,
                    qth_raw, qth_standard, device_raw, device_standard,
                    antenna_raw, antenna_standard, power_raw, power_standard,
                    signal, source, raw_input, unmatched, is_deleted,
                    excel_sync_status, created_at, updated_at)
                VALUES($submission, $session, $sequence, $time, $callsign,
                       $qthRaw, $qth, $deviceRaw, $device,
                       $antennaRaw, $antenna, $powerRaw, $power,
                       $signal, $source, $raw, $unmatched, 0,
                       'deferred', $created, $updated)
                """;
            Add(insertCheckin, "$submission", submissionId);
            Add(insertCheckin, "$session", sessionId);
            Add(insertCheckin, "$sequence", sequence);
            Add(insertCheckin, "$time", oldCheckin.CheckinTime);
            Add(insertCheckin, "$callsign", oldCheckin.Callsign);
            Add(insertCheckin, "$qthRaw", oldCheckin.QthRaw);
            Add(insertCheckin, "$qth", oldCheckin.QthStandard);
            Add(insertCheckin, "$deviceRaw", oldCheckin.DeviceRaw);
            Add(insertCheckin, "$device", oldCheckin.DeviceStandard);
            Add(insertCheckin, "$antennaRaw", oldCheckin.AntennaRaw);
            Add(insertCheckin, "$antenna", oldCheckin.AntennaStandard);
            Add(insertCheckin, "$powerRaw", oldCheckin.PowerRaw);
            Add(insertCheckin, "$power", oldCheckin.PowerStandard);
            Add(insertCheckin, "$signal", oldCheckin.Signal);
            Add(insertCheckin, "$source", string.IsNullOrWhiteSpace(oldCheckin.Source)
                ? "legacy-python" : oldCheckin.Source);
            Add(insertCheckin, "$raw", oldCheckin.RawInput);
            Add(insertCheckin, "$unmatched", oldCheckin.Unmatched);
            Add(insertCheckin, "$created", FallbackNow(oldCheckin.CreatedAt));
            Add(insertCheckin, "$updated", FallbackNow(oldCheckin.UpdatedAt));
            await insertCheckin.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            importedCheckins++;
        }

        await WriteMarkerAsync(native, new
        {
            status = "completed",
            source = legacyDatabasePath,
            backup = backupPath,
            sessions = importedSessions,
            checkins = importedCheckins,
            skipped = skippedCheckins,
            at = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture)
        }, cancellationToken, sqliteTransaction).ConfigureAwait(false);
        await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);

        return new(true, true, importedSessions, importedCheckins, skippedCheckins, backupPath,
            $"已从旧版数据库导入 {importedSessions} 个场次、{importedCheckins} 条签到；旧库已备份。");
    }

    private static async Task<LegacySnapshot> ReadLegacyAsync(
        string path, CancellationToken cancellationToken)
    {
        await using var connection = await OpenAsync(path, SqliteOpenMode.ReadOnly, cancellationToken)
            .ConfigureAwait(false);
        if (!await TableExistsAsync(connection, "sessions", cancellationToken).ConfigureAwait(false)
            || !await TableExistsAsync(connection, "checkins", cancellationToken).ConfigureAwait(false))
        {
            return new(false, Array.Empty<LegacySession>(), Array.Empty<LegacyCheckin>());
        }

        var sessionColumns = await ColumnsAsync(connection, "sessions", cancellationToken).ConfigureAwait(false);
        var checkinColumns = await ColumnsAsync(connection, "checkins", cancellationToken).ConfigureAwait(false);
        var sessions = await ReadSessionsAsync(connection, sessionColumns, cancellationToken).ConfigureAwait(false);
        var checkins = await ReadCheckinsAsync(connection, checkinColumns, cancellationToken).ConfigureAwait(false);
        return new(true, sessions, checkins);
    }

    private static async Task<IReadOnlyList<LegacySession>> ReadSessionsAsync(
        SqliteConnection connection, IReadOnlySet<string> columns, CancellationToken cancellationToken)
    {
        var sql = $"""
            SELECT {Expr(columns, "id", "0")} AS id,
                   {Expr(columns, "name")} AS name,
                   {Expr(columns, "date")} AS date,
                   {Expr(columns, "operator_callsign")} AS operator_callsign,
                   {Expr(columns, "repeater_name")} AS repeater_name,
                   {Expr(columns, "started_at")} AS started_at,
                   {Expr(columns, "ended_at")} AS ended_at,
                   {Expr(columns, "excel_path")} AS excel_path,
                   {Expr(columns, "status", "'active'")} AS status,
                   {Expr(columns, "created_at")} AS created_at,
                   {Expr(columns, "updated_at")} AS updated_at,
                   {Expr(columns, "excel_sheet_name")} AS excel_sheet_name
            FROM sessions ORDER BY id
            """;
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var rows = new List<LegacySession>();
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            rows.Add(new(
                GetLong(reader, 0), GetText(reader, 1), GetText(reader, 2), GetText(reader, 3),
                GetText(reader, 4), GetText(reader, 5), GetText(reader, 6), GetText(reader, 7),
                GetText(reader, 8), GetText(reader, 9), GetText(reader, 10), GetText(reader, 11)));
        }
        return rows;
    }

    private static async Task<IReadOnlyList<LegacyCheckin>> ReadCheckinsAsync(
        SqliteConnection connection, IReadOnlySet<string> columns, CancellationToken cancellationToken)
    {
        var sql = $"""
            SELECT {Expr(columns, "id", "0")} AS id,
                   {Expr(columns, "session_id", "0")} AS session_id,
                   {Expr(columns, "sequence_no", "0")} AS sequence_no,
                   {Expr(columns, "checkin_time")} AS checkin_time,
                   {Expr(columns, "callsign")} AS callsign,
                   {Expr(columns, "qth_raw")} AS qth_raw,
                   {Expr(columns, "qth_standard")} AS qth_standard,
                   {Expr(columns, "device_raw")} AS device_raw,
                   {Expr(columns, "device_standard")} AS device_standard,
                   {Expr(columns, "antenna_raw")} AS antenna_raw,
                   {Expr(columns, "antenna_standard")} AS antenna_standard,
                   {Expr(columns, "power_raw")} AS power_raw,
                   {Expr(columns, "power_standard")} AS power_standard,
                   {Expr(columns, "signal")} AS signal,
                   {Expr(columns, "source")} AS source,
                   {Expr(columns, "raw_input")} AS raw_input,
                   {Expr(columns, "unmatched")} AS unmatched,
                   {Expr(columns, "is_deleted", "0")} AS is_deleted,
                   {Expr(columns, "created_at")} AS created_at,
                   {Expr(columns, "updated_at")} AS updated_at
            FROM checkins ORDER BY session_id, sequence_no, id
            """;
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var rows = new List<LegacyCheckin>();
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            rows.Add(new(
                GetLong(reader, 0), GetLong(reader, 1), GetInt(reader, 2), GetText(reader, 3),
                GetText(reader, 4), GetText(reader, 5), GetText(reader, 6), GetText(reader, 7),
                GetText(reader, 8), GetText(reader, 9), GetText(reader, 10), GetText(reader, 11),
                GetText(reader, 12), GetText(reader, 13), GetText(reader, 14), GetText(reader, 15),
                GetText(reader, 16), GetInt(reader, 17), GetText(reader, 18), GetText(reader, 19)));
        }
        return rows;
    }

    private static string Expr(IReadOnlySet<string> columns, string column, string fallback = "''") =>
        columns.Contains(column) ? $"COALESCE(\"{column}\", {fallback})" : fallback;

    private static async Task<string> CreateBackupAsync(
        string source, string backupRoot, CancellationToken cancellationToken)
    {
        var fileName = $"legacy-python-{DateTimeOffset.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}.db";
        var target = Path.Combine(backupRoot, fileName);
        await using var sourceConnection = await OpenAsync(source, SqliteOpenMode.ReadOnly, cancellationToken)
            .ConfigureAwait(false);
        try
        {
            await using var vacuum = sourceConnection.CreateCommand();
            vacuum.CommandText = "VACUUM INTO $target";
            Add(vacuum, "$target", target);
            await vacuum.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (SqliteException)
        {
            if (File.Exists(target))
            {
                File.Delete(target);
            }
            File.Copy(source, target, overwrite: false);
            foreach (var suffix in new[] { "-wal", "-shm" })
            {
                var sidecar = source + suffix;
                if (File.Exists(sidecar))
                {
                    File.Copy(sidecar, target + suffix, overwrite: false);
                }
            }
        }
        return target;
    }

    private static async Task<SqliteConnection> OpenAsync(
        string path, SqliteOpenMode mode, CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = mode,
            Cache = SqliteCacheMode.Shared,
            Pooling = false
        }.ToString());
        await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA busy_timeout = 2500; PRAGMA foreign_keys = ON;";
        await pragma.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
        return connection;
    }

    private static async Task<bool> TableExistsAsync(
        SqliteConnection connection, string table, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = $name LIMIT 1";
        Add(command, "$name", table);
        return await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false) is not null;
    }

    private static async Task<HashSet<string>> ColumnsAsync(
        SqliteConnection connection, string table, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = $"PRAGMA table_info(\"{table}\")";
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var columns = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            columns.Add(reader.GetString(1));
        }
        return columns;
    }

    private static async Task<bool> HasCompletedMarkerAsync(
        SqliteConnection connection, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM native_meta WHERE key = $key LIMIT 1";
        Add(command, "$key", MigrationKey);
        var value = Convert.ToString(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false),
            CultureInfo.InvariantCulture);
        return value?.Contains("\"status\":\"completed\"", StringComparison.Ordinal) == true
            || value?.Contains("\"status\":\"skipped-native-data-exists\"", StringComparison.Ordinal) == true;
    }

    private static async Task WriteMarkerAsync(
        SqliteConnection connection, object marker, CancellationToken cancellationToken,
        SqliteTransaction? transaction = null)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            INSERT INTO native_meta(key, value) VALUES($key, $value)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """;
        Add(command, "$key", MigrationKey);
        Add(command, "$value", JsonSerializer.Serialize(marker));
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task<long?> FindSessionAsync(
        SqliteConnection connection, SqliteTransaction transaction,
        string date, string name, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "SELECT id FROM sessions WHERE date = $date AND name = $name LIMIT 1";
        Add(command, "$date", date);
        Add(command, "$name", name);
        var value = await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false);
        return value is null ? null : Convert.ToInt64(value, CultureInfo.InvariantCulture);
    }

    private static async Task<bool> ExistsAsync(
        SqliteConnection connection, SqliteTransaction transaction, string sql,
        IReadOnlyList<(string Name, object Value)> parameters, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = sql;
        foreach (var parameter in parameters)
        {
            Add(command, parameter.Name, parameter.Value);
        }
        return await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false) is not null;
    }

    private static async Task<int> ScalarIntAsync(
        SqliteConnection connection, string sql, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        return Convert.ToInt32(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false),
            CultureInfo.InvariantCulture);
    }

    private static string NormalizeStatus(string value) =>
        string.Equals(value, "ended", StringComparison.OrdinalIgnoreCase) ? "ended" : "active";

    private static string FallbackNow(string value) => string.IsNullOrWhiteSpace(value)
        ? DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture)
        : value;

    private static string GetText(SqliteDataReader reader, int ordinal) =>
        reader.IsDBNull(ordinal) ? "" : Convert.ToString(reader.GetValue(ordinal), CultureInfo.InvariantCulture) ?? "";

    private static long GetLong(SqliteDataReader reader, int ordinal) =>
        long.TryParse(GetText(reader, ordinal), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
            ? value : 0;

    private static int GetInt(SqliteDataReader reader, int ordinal) =>
        int.TryParse(GetText(reader, ordinal), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
            ? value : 0;

    private static void Add(SqliteCommand command, string name, object value) =>
        command.Parameters.AddWithValue(name, value);

    private sealed record LegacySnapshot(
        bool HasRequiredTables,
        IReadOnlyList<LegacySession> Sessions,
        IReadOnlyList<LegacyCheckin> Checkins);

    private sealed record LegacySession(
        long Id, string Name, string Date, string OperatorCallsign, string RepeaterName,
        string StartedAt, string EndedAt, string ExcelPath, string Status,
        string CreatedAt, string UpdatedAt, string ExcelSheetName);

    private sealed record LegacyCheckin(
        long Id, long SessionId, int SequenceNo, string CheckinTime, string Callsign,
        string QthRaw, string QthStandard, string DeviceRaw, string DeviceStandard,
        string AntennaRaw, string AntennaStandard, string PowerRaw, string PowerStandard,
        string Signal, string Source, string RawInput, string Unmatched, int IsDeleted,
        string CreatedAt, string UpdatedAt);
}
