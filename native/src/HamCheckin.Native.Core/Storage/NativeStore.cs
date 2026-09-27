using System.Data;
using System.Globalization;
using HamCheckin.Native.Core.Parsing;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Storage;

/// <summary>
/// 原生版热路径存储。SQLite 是现场提交的唯一同步边界；Excel、资料库和
/// 地点包都不持有这里的连接，也不会让它们阻塞一条签到。
/// </summary>
public sealed class NativeStore : IAsyncDisposable
{
    private const int SchemaVersion = 3;
    private readonly string _databasePath;
    private readonly string _connectionString;
    private readonly int _storeDelayMilliseconds;
    private readonly SemaphoreSlim _writeGate = new(1, 1);

    public NativeStore(string? databasePath = null, int? storeDelayMilliseconds = null)
    {
        _databasePath = databasePath ?? AppPaths.NativeDatabasePath;
        _storeDelayMilliseconds = storeDelayMilliseconds ?? RuntimeOptions.StoreDelayMilliseconds;
        if (_storeDelayMilliseconds is < 0 or > 60_000)
        {
            throw new ArgumentOutOfRangeException(
                nameof(storeDelayMilliseconds),
                "SQLite 测试延迟必须在 0 到 60000 毫秒之间。");
        }

        _connectionString = new SqliteConnectionStringBuilder
        {
            DataSource = _databasePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
            Pooling = true
        }.ToString();
    }

    public string DatabasePath => _databasePath;

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        var directory = Path.GetDirectoryName(_databasePath)
            ?? throw new InvalidOperationException("无法确定数据库目录。");
        Directory.CreateDirectory(directory);

        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = $$"""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA foreign_keys = ON;
            PRAGMA busy_timeout = 2500;
            PRAGMA wal_autocheckpoint = 1000;

            CREATE TABLE IF NOT EXISTS native_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'ended')),
                operator_callsign TEXT NOT NULL DEFAULT '',
                repeater_name TEXT NOT NULL DEFAULT '',
                workbook_path TEXT NOT NULL DEFAULT '',
                sheet_name TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_date_name
                ON sessions(date, name);

            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL UNIQUE,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
                sequence_no INTEGER NOT NULL,
                checkin_time TEXT NOT NULL,
                callsign TEXT NOT NULL,
                qth_raw TEXT NOT NULL DEFAULT '',
                qth_standard TEXT NOT NULL DEFAULT '',
                device_raw TEXT NOT NULL DEFAULT '',
                device_standard TEXT NOT NULL DEFAULT '',
                antenna_raw TEXT NOT NULL DEFAULT '',
                antenna_standard TEXT NOT NULL DEFAULT '',
                power_raw TEXT NOT NULL DEFAULT '',
                power_standard TEXT NOT NULL DEFAULT '',
                signal TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'local',
                raw_input TEXT NOT NULL,
                unmatched TEXT NOT NULL DEFAULT '',
                is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1)),
                excel_sync_status TEXT NOT NULL DEFAULT 'deferred',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_checkins_session_seq
                ON checkins(session_id, sequence_no) WHERE is_deleted = 0;
            CREATE INDEX IF NOT EXISTS idx_checkins_session
                ON checkins(session_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_checkins_callsign
                ON checkins(callsign, id DESC);

            CREATE TABLE IF NOT EXISTS field_edit_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkin_id INTEGER NOT NULL REFERENCES checkins(id) ON DELETE CASCADE,
                field TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                old_unmatched TEXT NOT NULL,
                new_unmatched TEXT NOT NULL,
                consumed_tokens TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '人工编辑',
                applied_at TEXT NOT NULL,
                is_undo INTEGER NOT NULL DEFAULT 0
            );

            INSERT INTO native_meta(key, value) VALUES('schema_version', '{{SchemaVersion}}')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """;
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);

        // 从早期 Native Preview 数据库升级时保留既有内容；正式版数据目录
        // 与旧 Python 数据库分开，因此不会触碰用户原有 ham_checkin.db。
        await EnsureColumnAsync(connection, "sessions", "operator_callsign", "TEXT NOT NULL DEFAULT ''", cancellationToken);
        await EnsureColumnAsync(connection, "sessions", "repeater_name", "TEXT NOT NULL DEFAULT ''", cancellationToken);
        await EnsureColumnAsync(connection, "sessions", "workbook_path", "TEXT NOT NULL DEFAULT ''", cancellationToken);
        await EnsureColumnAsync(connection, "sessions", "sheet_name", "TEXT NOT NULL DEFAULT ''", cancellationToken);
    }

    public async Task<SessionInfo> GetOrCreateFirstSessionAsync(
        DateOnly date,
        CancellationToken cancellationToken = default)
    {
        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var transaction = await connection.BeginTransactionAsync(
                IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false);

            var active = await ReadSessionAsync(connection, (SqliteTransaction)transaction,
                "WHERE s.status = 'active'", Array.Empty<(string Name, object Value)>(),
                cancellationToken).ConfigureAwait(false);
            if (active is not null)
            {
                await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
                return active;
            }

            var dateText = date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            var sessionName = await NextSessionNameAsync(
                connection, (SqliteTransaction)transaction, dateText, cancellationToken).ConfigureAwait(false);
            var now = RuntimeOptions.Now.ToString("O", CultureInfo.InvariantCulture);
            await using (var insert = connection.CreateCommand())
            {
                insert.Transaction = (SqliteTransaction)transaction;
                insert.CommandText = """
                    INSERT INTO sessions(name, date, status, started_at, created_at, updated_at)
                    VALUES($name, $date, 'active', $now, $now, $now)
                    ON CONFLICT(date, name) DO NOTHING
                    """;
                AddParameter(insert, "$name", sessionName);
                AddParameter(insert, "$date", dateText);
                AddParameter(insert, "$now", now);
                await insert.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            var session = await ReadSessionAsync(connection, (SqliteTransaction)transaction,
                "WHERE s.date = $date AND s.name = $name",
                new[] { ("$date", (object)dateText), ("$name", (object)sessionName) },
                cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("创建默认场次失败。");
            await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
            return session;
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<SessionInfo?> GetSessionAsync(long sessionId,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        return await ReadSessionAsync(connection, null, "WHERE s.id = $id",
            new[] { ("$id", (object)sessionId) }, cancellationToken).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<SessionInfo>> ListSessionsAsync(
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT s.id, s.name, s.date, s.status,
                   COALESCE(MAX(c.sequence_no), 0) + 1,
                   COALESCE(s.operator_callsign, ''), COALESCE(s.repeater_name, ''),
                   COALESCE(s.workbook_path, ''), COALESCE(s.sheet_name, '')
            FROM sessions s LEFT JOIN checkins c
              ON c.session_id = s.id AND c.is_deleted = 0
            GROUP BY s.id, s.name, s.date, s.status,
                     s.operator_callsign, s.repeater_name, s.workbook_path, s.sheet_name
            ORDER BY s.date, s.id
            """;
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var sessions = new List<SessionInfo>();
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            sessions.Add(ReadSessionRow(reader));
        }
        return sessions;
    }

    public async Task<SessionInfo> CreateSessionAsync(
        string name,
        string date,
        string operatorCallsign = "",
        string repeaterName = "",
        string workbookPath = "",
        string sheetName = "",
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(date))
        {
            throw new ArgumentException("场次名称和日期不能为空。");
        }

        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var transaction = await connection.BeginTransactionAsync(
                IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false);
            await using var command = connection.CreateCommand();
            command.Transaction = (SqliteTransaction)transaction;
            command.CommandText = """
                INSERT INTO sessions(
                    name, date, status, operator_callsign, repeater_name,
                    workbook_path, sheet_name, started_at, created_at, updated_at)
                VALUES($name, $date, 'active', $operator, $repeater,
                       $workbook, $sheet, $now, $now, $now);
                SELECT last_insert_rowid();
                """;
            AddParameter(command, "$name", name.Trim());
            AddParameter(command, "$date", date.Trim());
            AddParameter(command, "$operator", operatorCallsign.Trim());
            AddParameter(command, "$repeater", repeaterName.Trim());
            AddParameter(command, "$workbook", workbookPath.Trim());
            AddParameter(command, "$sheet", sheetName.Trim());
            AddParameter(command, "$now", RuntimeOptions.Now.ToString("O", CultureInfo.InvariantCulture));
            var id = Convert.ToInt64(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false), CultureInfo.InvariantCulture);
            await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
            return await GetSessionAsync(id, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("创建场次后无法读取。");
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<SessionInfo> SetSessionStatusAsync(
        long sessionId,
        string status,
        CancellationToken cancellationToken = default)
    {
        if (status is not ("active" or "ended"))
        {
            throw new ArgumentOutOfRangeException(nameof(status), status, "场次状态无效。");
        }

        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var command = connection.CreateCommand();
            command.CommandText = """
                UPDATE sessions
                SET status = $status,
                    ended_at = CASE WHEN $status = 'ended' THEN $now ELSE '' END,
                    updated_at = $now
                WHERE id = $id
                """;
            AddParameter(command, "$status", status);
            AddParameter(command, "$now", RuntimeOptions.Now.ToString("O", CultureInfo.InvariantCulture));
            AddParameter(command, "$id", sessionId);
            if (await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false) != 1)
            {
                throw new InvalidOperationException("场次不存在。");
            }
            return await GetSessionAsync(sessionId, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("场次状态更新后无法读取。");
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<SessionInfo> UpdateSessionInfoAsync(
        SessionInfo session,
        string? operatorCallsign = null,
        string? repeaterName = null,
        string? workbookPath = null,
        string? sheetName = null,
        CancellationToken cancellationToken = default)
    {
        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var command = connection.CreateCommand();
            command.CommandText = """
                UPDATE sessions
                SET operator_callsign = $operator,
                    repeater_name = $repeater,
                    workbook_path = $workbook,
                    sheet_name = $sheet,
                    updated_at = $now
                WHERE id = $id
                """;
            AddParameter(command, "$operator", operatorCallsign ?? session.OperatorCallsign);
            AddParameter(command, "$repeater", repeaterName ?? session.RepeaterName);
            AddParameter(command, "$workbook", workbookPath ?? session.WorkbookPath);
            AddParameter(command, "$sheet", sheetName ?? session.SheetName);
            AddParameter(command, "$now", RuntimeOptions.Now.ToString("O", CultureInfo.InvariantCulture));
            AddParameter(command, "$id", session.Id);
            await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            return await GetSessionAsync(session.Id, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("场次更新后无法读取。");
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<CheckinEntry> AddCheckinAsync(
        SessionInfo session,
        ParseResult result,
        string? submissionId = null,
        CancellationToken cancellationToken = default)
    {
        if (!result.CanSubmit)
        {
            throw new ArgumentException("必须先识别出有效呼号。", nameof(result));
        }

        submissionId ??= Guid.NewGuid().ToString("N");
        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_storeDelayMilliseconds > 0)
            {
                await Task.Delay(_storeDelayMilliseconds, cancellationToken)
                    .ConfigureAwait(false);
            }

            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var transaction = await connection.BeginTransactionAsync(
                IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false);
            var sqliteTransaction = (SqliteTransaction)transaction;
            var sequence = await NextSequenceAsync(connection, sqliteTransaction,
                session.Id, cancellationToken).ConfigureAwait(false);
            var now = RuntimeOptions.Now;
            var checkinTime = now.ToString("HH:mm:ss", CultureInfo.InvariantCulture);

            await using var command = connection.CreateCommand();
            command.Transaction = sqliteTransaction;
            command.CommandText = """
                INSERT INTO checkins(
                    submission_id, session_id, sequence_no, checkin_time, callsign,
                    qth_raw, qth_standard, device_raw, device_standard,
                    antenna_raw, antenna_standard, power_raw, power_standard,
                    signal, source, raw_input, unmatched, created_at, updated_at)
                VALUES(
                    $submission, $session, $sequence, $time, $callsign,
                    $qthRaw, $qth, $deviceRaw, $device,
                    $antennaRaw, $antenna, $powerRaw, $power,
                    $signal, 'local', $raw, $unmatched, $now, $now);
                SELECT last_insert_rowid();
                """;
            AddParameter(command, "$submission", submissionId);
            AddParameter(command, "$session", session.Id);
            AddParameter(command, "$sequence", sequence);
            AddParameter(command, "$time", checkinTime);
            AddParameter(command, "$callsign", result.Callsign.Value);
            AddParameter(command, "$qthRaw", result.Qth.Raw);
            AddParameter(command, "$qth", result.Qth.Value);
            AddParameter(command, "$deviceRaw", result.Device.Raw);
            AddParameter(command, "$device", result.Device.Value);
            AddParameter(command, "$antennaRaw", result.Antenna.Raw);
            AddParameter(command, "$antenna", result.Antenna.Value);
            AddParameter(command, "$powerRaw", result.Power.Raw);
            AddParameter(command, "$power", result.Power.Value);
            AddParameter(command, "$signal", result.Signal.Value);
            AddParameter(command, "$raw", result.RawText);
            AddParameter(command, "$unmatched", result.UnmatchedText);
            AddParameter(command, "$now", now.ToString("O", CultureInfo.InvariantCulture));
            var scalar = await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false);
            var id = Convert.ToInt64(scalar, CultureInfo.InvariantCulture);

            await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
            return new CheckinEntry(
                id, session.Id, sequence, checkinTime, result.Callsign.Value,
                result.Qth.Value, result.Device.Value, result.Antenna.Value,
                result.Power.Value, result.Signal.Value, "local", result.RawText,
                result.UnmatchedText, now.ToString("O", CultureInfo.InvariantCulture));
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<IReadOnlyList<CheckinEntry>> LoadRecentAsync(
        long sessionId,
        int limit = 200,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, session_id, sequence_no, checkin_time, callsign,
                   qth_standard, device_standard, antenna_standard, power_standard,
                   signal, source, raw_input, unmatched, updated_at
            FROM checkins
            WHERE session_id = $session AND is_deleted = 0
            ORDER BY sequence_no DESC LIMIT $limit
            """;
        AddParameter(command, "$session", sessionId);
        AddParameter(command, "$limit", Math.Clamp(limit, 1, 5000));
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var values = new List<CheckinEntry>();
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            values.Add(ReadCheckin(reader));
        }
        return values;
    }

    public Task<IReadOnlyList<CheckinEntry>> LoadAllForExportAsync(
        long sessionId,
        CancellationToken cancellationToken = default) => LoadRecentAsync(sessionId, 500000, cancellationToken);

    public async Task<FieldEditRequest?> CreateFieldEditRequestAsync(
        long checkinId,
        FieldKind field,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, session_id, sequence_no, callsign, raw_input, unmatched,
                   updated_at, checkin_time, qth_standard, device_standard,
                   antenna_standard, power_standard, signal
            FROM checkins WHERE id = $id AND is_deleted = 0 LIMIT 1
            """;
        AddParameter(command, "$id", checkinId);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        if (!await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            return null;
        }

        var current = field switch
        {
            FieldKind.Time => reader.GetString(7),
            FieldKind.Callsign => reader.GetString(3),
            FieldKind.Qth => reader.GetString(8),
            FieldKind.Device => reader.GetString(9),
            FieldKind.Antenna => reader.GetString(10),
            FieldKind.Power => reader.GetString(11),
            FieldKind.Signal => reader.GetString(12),
            _ => string.Empty
        };
        return new FieldEditRequest(reader.GetInt64(0), field, current,
            reader.GetString(4), reader.GetString(5), reader.GetInt64(1),
            reader.GetInt32(2), reader.GetString(3), reader.GetString(6));
    }

    public async Task<CheckinEntry> ApplyFieldEditAsync(
        FieldEditCommit commit,
        CancellationToken cancellationToken = default)
    {
        await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
            await using var transaction = await connection.BeginTransactionAsync(
                IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false);
            var sqliteTransaction = (SqliteTransaction)transaction;
            var current = await ReadCheckinByIdAsync(connection, sqliteTransaction,
                commit.CheckinId, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("记录不存在或已被删除。");
            if (!string.IsNullOrWhiteSpace(commit.ExpectedUpdatedAt)
                && !string.Equals(current.UpdatedAt, commit.ExpectedUpdatedAt, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("这条记录在编辑期间已经发生变化，请重新打开编辑器。");
            }

            var newUnmatched = commit.RemoveConsumedTokens
                ? ConsumeTokens(current.Unmatched, commit.ConsumedTokens, commit.ConsumedTokenIndexes)
                : current.Unmatched;
            var now = RuntimeOptions.Now.ToString("O", CultureInfo.InvariantCulture);
            var (valueColumn, rawColumn) = ColumnsFor(commit.Field);
            await using (var update = connection.CreateCommand())
            {
                update.Transaction = sqliteTransaction;
                update.CommandText = $"""
                    UPDATE checkins
                    SET {valueColumn} = $value,
                        {(rawColumn is null ? "" : rawColumn + " = $raw,")}
                        unmatched = $unmatched,
                        excel_sync_status = 'pending',
                        updated_at = $now
                    WHERE id = $id
                    """;
                AddParameter(update, "$value", commit.NewValue);
                if (rawColumn is not null)
                {
                    AddParameter(update, "$raw", commit.RawEditText);
                }
                AddParameter(update, "$unmatched", newUnmatched);
                AddParameter(update, "$now", now);
                AddParameter(update, "$id", commit.CheckinId);
                await update.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            await using (var audit = connection.CreateCommand())
            {
                audit.Transaction = sqliteTransaction;
                audit.CommandText = """
                    INSERT INTO field_edit_audit(
                        checkin_id, field, old_value, new_value, old_unmatched,
                        new_unmatched, consumed_tokens, source, applied_at)
                    VALUES($id, $field, $old, $new, $oldUnmatched, $newUnmatched,
                           $consumed, $source, $at)
                    """;
                AddParameter(audit, "$id", commit.CheckinId);
                AddParameter(audit, "$field", commit.Field.ToString());
                AddParameter(audit, "$old", commit.OldValue);
                AddParameter(audit, "$new", commit.NewValue);
                AddParameter(audit, "$oldUnmatched", current.Unmatched);
                AddParameter(audit, "$newUnmatched", newUnmatched);
                AddParameter(audit, "$consumed", string.Join(" ", commit.ConsumedTokens));
                AddParameter(audit, "$source", commit.Source);
                AddParameter(audit, "$at", now);
                await audit.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            }

            var updated = await ReadCheckinByIdAsync(connection, sqliteTransaction,
                commit.CheckinId, cancellationToken).ConfigureAwait(false)
                ?? throw new InvalidOperationException("字段修改后无法读取记录。");
            await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
            return updated;
        }
        finally
        {
            _writeGate.Release();
        }
    }

    public async Task<string> QuickCheckAsync(CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA quick_check";
        return Convert.ToString(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false),
            CultureInfo.InvariantCulture) ?? "unknown";
    }

    private async Task<CheckinEntry?> ReadCheckinByIdAsync(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        long id,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            SELECT id, session_id, sequence_no, checkin_time, callsign,
                   qth_standard, device_standard, antenna_standard, power_standard,
                   signal, source, raw_input, unmatched, updated_at
            FROM checkins WHERE id = $id AND is_deleted = 0 LIMIT 1
            """;
        AddParameter(command, "$id", id);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        return await reader.ReadAsync(cancellationToken).ConfigureAwait(false)
            ? ReadCheckin(reader)
            : null;
    }

    private async Task<SessionInfo?> ReadSessionAsync(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        string filter,
        IReadOnlyList<(string Name, object Value)> parameters,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = $"""
            SELECT s.id, s.name, s.date, s.status,
                   COALESCE(MAX(c.sequence_no), 0) + 1,
                   COALESCE(s.operator_callsign, ''), COALESCE(s.repeater_name, ''),
                   COALESCE(s.workbook_path, ''), COALESCE(s.sheet_name, '')
            FROM sessions s LEFT JOIN checkins c
              ON c.session_id = s.id AND c.is_deleted = 0
            {filter}
            GROUP BY s.id, s.name, s.date, s.status,
                     s.operator_callsign, s.repeater_name, s.workbook_path, s.sheet_name
            ORDER BY s.date, s.id
            LIMIT 1
            """;
        foreach (var parameter in parameters)
        {
            AddParameter(command, parameter.Name, parameter.Value);
        }
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        if (!await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            return null;
        }
        return ReadSessionRow(reader);
    }

    private static SessionInfo ReadSessionRow(SqliteDataReader reader) => new(
        reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3),
        reader.GetInt32(4), reader.GetString(5), reader.GetString(6), reader.GetString(7),
        reader.GetString(8));

    private static async Task<string> NextSessionNameAsync(
        SqliteConnection connection,
        SqliteTransaction transaction,
        string date,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "SELECT name FROM sessions WHERE date = $date ORDER BY id";
        AddParameter(command, "$date", date);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        var used = new HashSet<int>();
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            var name = reader.GetString(0);
            if (name.StartsWith("第", StringComparison.Ordinal)
                && name.EndsWith("场点名", StringComparison.Ordinal)
                && int.TryParse(name[1..^3], NumberStyles.Integer, CultureInfo.InvariantCulture, out var number))
            {
                used.Add(number);
            }
        }

        var next = 1;
        while (used.Contains(next))
        {
            next++;
        }
        return $"第{next}场点名";
    }

    private static async Task<int> NextSequenceAsync(
        SqliteConnection connection,
        SqliteTransaction transaction,
        long sessionId,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM checkins WHERE session_id = $session AND is_deleted = 0";
        AddParameter(command, "$session", sessionId);
        return Convert.ToInt32(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false), CultureInfo.InvariantCulture);
    }

    private static (string ValueColumn, string? RawColumn) ColumnsFor(FieldKind field) => field switch
    {
        FieldKind.Time => ("checkin_time", null),
        FieldKind.Callsign => ("callsign", null),
        FieldKind.Qth => ("qth_standard", "qth_raw"),
        FieldKind.Device => ("device_standard", "device_raw"),
        FieldKind.Antenna => ("antenna_standard", "antenna_raw"),
        FieldKind.Power => ("power_standard", "power_raw"),
        FieldKind.Signal => ("signal", null),
        _ => throw new ArgumentOutOfRangeException(nameof(field), field, "不支持的字段")
    };

    private static string ConsumeTokens(
        string unmatched,
        IReadOnlyList<string> consumed,
        IReadOnlyList<int>? consumedIndexes = null)
    {
        var remaining = unmatched.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        if (consumedIndexes is { Count: > 0 })
        {
            var indexes = consumedIndexes.ToHashSet();
            return string.Join(' ', remaining.Where((_, index) => !indexes.Contains(index)));
        }

        foreach (var token in consumed)
        {
            var index = remaining.FindIndex(value => string.Equals(value, token, StringComparison.Ordinal));
            if (index >= 0)
            {
                remaining.RemoveAt(index);
            }
        }
        return string.Join(' ', remaining);
    }

    private static CheckinEntry ReadCheckin(SqliteDataReader reader) => new(
        reader.GetInt64(0), reader.GetInt64(1), reader.GetInt32(2), reader.GetString(3),
        reader.GetString(4), reader.GetString(5), reader.GetString(6), reader.GetString(7),
        reader.GetString(8), reader.GetString(9), reader.GetString(10), reader.GetString(11),
        reader.GetString(12), reader.GetString(13));

    private static async Task EnsureColumnAsync(SqliteConnection connection, string table,
        string column, string definition, CancellationToken cancellationToken)
    {
        await using var check = connection.CreateCommand();
        check.CommandText = $"PRAGMA table_info({table})";
        await using var reader = await check.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        while (await reader.ReadAsync(cancellationToken).ConfigureAwait(false))
        {
            if (string.Equals(reader.GetString(1), column, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
        }
        await reader.DisposeAsync().ConfigureAwait(false);
        await using var alter = connection.CreateCommand();
        alter.CommandText = $"ALTER TABLE {table} ADD COLUMN {column} {definition}";
        await alter.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private async Task<SqliteConnection> OpenAsync(CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(_connectionString);
        await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
        await using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 2500;";
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
        return connection;
    }

    private static void AddParameter(SqliteCommand command, string name, object? value) =>
        command.Parameters.AddWithValue(name, value ?? string.Empty);

    public ValueTask DisposeAsync()
    {
        _writeGate.Dispose();
        SqliteConnection.ClearAllPools();
        return ValueTask.CompletedTask;
    }
}
