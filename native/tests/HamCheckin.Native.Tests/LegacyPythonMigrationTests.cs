using System.Globalization;
using System.Text.Json;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;
using Xunit;

namespace HamCheckin.Native.Tests;

public sealed class LegacyPythonMigrationTests
{
    [Fact]
    public async Task ImportsEveryAvailableFieldAndPreservesReadableLegacyCopyAndBackup()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT, operator_callsign TEXT,
                    repeater_name TEXT, started_at TEXT, ended_at TEXT, excel_path TEXT,
                    excel_sheet_name TEXT, status TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    checkin_time TEXT, callsign TEXT, qth_raw TEXT, qth_standard TEXT,
                    device_raw TEXT, device_standard TEXT, antenna_raw TEXT,
                    antenna_standard TEXT, power_raw TEXT, power_standard TEXT,
                    signal TEXT, source TEXT, raw_input TEXT, unmatched TEXT,
                    is_deleted INTEGER, created_at TEXT, updated_at TEXT);
                INSERT INTO sessions VALUES(17, '第17场点名', '2026-09-12', 'BA4OLD',
                    '旧中继台', '2026-09-12T20:00:00+08:00', '2026-09-12T22:00:00+08:00',
                    'legacy.xlsx', 'sheet-7', 'ended', '2026-09-12T19:00:00+08:00',
                    '2026-09-12T22:01:00+08:00');
                INSERT INTO checkins VALUES(91, 17, 4, '21:04', 'BA4TEST', 'qth raw',
                    '江苏省南京市玄武区', 'device raw', '设备标准名', 'antenna raw', '天线标准名',
                    'power raw', '功率标准值', '59+', 'fixture-source', '完整原始输入',
                    '未识别内容', 0, '2026-09-12T21:04:00+08:00',
                    '2026-09-12T21:05:00+08:00');
                """);
            var sourceBefore = await ReadLegacySnapshotAsync(legacyPath);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.True(result.Imported);
            Assert.Equal(1, result.ImportedSessions);
            Assert.Equal(1, result.ImportedCheckins);
            Assert.Equal(0, result.SkippedCheckins);
            Assert.True(File.Exists(result.BackupPath));
            Assert.True(File.Exists(legacyPath));

            var session = await ReadSingleRowAsync(nativePath, """
                SELECT id, name, date, status, operator_callsign, repeater_name,
                       workbook_path, sheet_name, started_at, ended_at, created_at, updated_at
                FROM sessions
                """);
            Assert.NotEqual("17", session[0]);
            Assert.Equal(new[]
            {
                "第17场点名", "2026-09-12", "ended", "BA4OLD", "旧中继台", "legacy.xlsx",
                "sheet-7", "2026-09-12T20:00:00+08:00", "2026-09-12T22:00:00+08:00",
                "2026-09-12T19:00:00+08:00", "2026-09-12T22:01:00+08:00"
            }, session.Skip(1));

            var checkin = await ReadSingleRowAsync(nativePath, """
                SELECT id, submission_id, session_id, sequence_no, checkin_time, callsign,
                       qth_raw, qth_standard, device_raw, device_standard, antenna_raw,
                       antenna_standard, power_raw, power_standard, signal, source, raw_input,
                       unmatched, is_deleted, excel_sync_status, created_at, updated_at
                FROM checkins
                """);
            Assert.NotEqual("91", checkin[0]);
            Assert.Equal(new[]
            {
                "legacy-python:91", session[0], "4", "21:04", "BA4TEST", "qth raw",
                "江苏省南京市玄武区", "device raw", "设备标准名", "antenna raw", "天线标准名",
                "power raw", "功率标准值", "59+", "fixture-source", "完整原始输入",
                "未识别内容", "0", "deferred", "2026-09-12T21:04:00+08:00",
                "2026-09-12T21:05:00+08:00"
            }, checkin.Skip(1));

            Assert.Equal(sourceBefore, await ReadLegacySnapshotAsync(legacyPath));
            Assert.Equal(sourceBefore, await ReadLegacySnapshotAsync(result.BackupPath));
            var mappingRow = await ReadSingleRowAsync(nativePath,
                "SELECT value FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'");
            using (var mapping = JsonDocument.Parse(mappingRow[0]))
            {
                Assert.Equal("none", mapping.RootElement.GetProperty("IdentityType").GetString());
                Assert.Equal("created", mapping.RootElement.GetProperty("Decision").GetString());
                Assert.Equal("17", mapping.RootElement.GetProperty("OldSessionId").GetInt64().ToString());
                Assert.Equal(session[0], mapping.RootElement.GetProperty("NativeSessionId").GetInt64().ToString());
                Assert.Equal(result.BackupPath, mapping.RootElement.GetProperty("BackupPath").GetString());
            }
            using (var marker = JsonDocument.Parse(await ReadMigrationMarkerAsync(nativePath)))
            {
                Assert.Equal(1, marker.RootElement.GetProperty("mappingVersion").GetInt32());
                Assert.Equal(1, marker.RootElement.GetProperty("mappedSessions").GetInt32());
            }
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadOnly))
            await using (var foreignKeyCheck = connection.CreateCommand())
            {
                foreignKeyCheck.CommandText = "PRAGMA foreign_key_check";
                await using var reader = await foreignKeyCheck.ExecuteReaderAsync();
                Assert.False(await reader.ReadAsync());
            }
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData("{")]
    [InlineData(null)]
    public async Task ExistingInvalidSessionMappingFailsClosed(string? mappingValue)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions VALUES(1, '映射拒绝场次', '2026-11-15');
                INSERT INTO checkins VALUES(10, 1, 1, 'BA4TEST', 'fixture', 0);
                """);
            await CreateDatabaseAsync(nativePath, """
                CREATE TABLE native_meta(key TEXT PRIMARY KEY, value TEXT);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var first = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.True(first.Imported, first.Message);

            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = """
                    DELETE FROM native_meta WHERE key = 'legacy_python_import';
                    UPDATE native_meta SET value = $value
                    WHERE key LIKE 'legacy_python_session_map:%';
                    """;
                command.Parameters.AddWithValue("$value", (object?)mappingValue ?? DBNull.Value);
                await command.ExecuteNonQueryAsync();
            }

            await Assert.ThrowsAsync<InvalidDataException>(async () =>
                await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot));

            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM checkins"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("1", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task AppliesDefaultsForNullAndMissingLegacyColumnsAndIds()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(
                    name TEXT, date TEXT, started_at TEXT, ended_at TEXT,
                    created_at TEXT, updated_at TEXT);
                CREATE TABLE checkins(
                    checkin_time TEXT, callsign TEXT, source TEXT,
                    created_at TEXT, updated_at TEXT);
                INSERT INTO sessions VALUES(NULL, NULL, NULL, NULL, '', NULL);
                INSERT INTO checkins VALUES(NULL, NULL, NULL, NULL, NULL);
                INSERT INTO checkins VALUES(NULL, NULL, NULL, NULL, NULL);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            var earliest = DateTimeOffset.UtcNow.AddMinutes(-1);

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            var latest = DateTimeOffset.UtcNow.AddMinutes(1);
            Assert.True(result.Imported);
            Assert.Equal(1, result.ImportedSessions);
            Assert.Equal(1, result.ImportedCheckins);
            Assert.Equal(1, result.SkippedCheckins);

            var session = await ReadSingleRowAsync(nativePath, """
                SELECT id, name, date, status, operator_callsign, repeater_name,
                       workbook_path, sheet_name, started_at, ended_at, created_at, updated_at
                FROM sessions
                """);
            Assert.Equal(new[] { "旧版场次", "1970-01-01", "active", "", "", "", "" },
                session.Skip(1).Take(7));
            AssertCurrentUtc(session[8], earliest, latest);
            Assert.Equal("", session[9]);
            AssertCurrentUtc(session[10], earliest, latest);
            AssertCurrentUtc(session[11], earliest, latest);

            var checkin = await ReadSingleRowAsync(nativePath, """
                SELECT id, submission_id, session_id, sequence_no, checkin_time, callsign,
                       qth_raw, qth_standard, device_raw, device_standard, antenna_raw,
                       antenna_standard, power_raw, power_standard, signal, source, raw_input,
                       unmatched, is_deleted, excel_sync_status, created_at, updated_at
                FROM checkins
                """);
            Assert.Equal("legacy-python:0", checkin[1]);
            Assert.Equal(session[0], checkin[2]);
            Assert.Equal("1", checkin[3]);
            Assert.All(checkin.Skip(4).Take(11), value => Assert.Equal("", value));
            Assert.Equal("legacy-python", checkin[15]);
            Assert.Equal("", checkin[16]);
            Assert.Equal("", checkin[17]);
            Assert.Equal("0", checkin[18]);
            Assert.Equal("deferred", checkin[19]);
            AssertCurrentUtc(checkin[20], earliest, latest);
            AssertCurrentUtc(checkin[21], earliest, latest);
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task ImportsNewSessionSkipsIneligibleRowsRepairsSequencesAndDoesNotRepeat()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT,
                    operator_callsign TEXT, repeater_name TEXT, status TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions VALUES(80, '复用场次', '2026-10-03',
                    '旧操作员', '旧中继', 'ended');
                INSERT INTO checkins VALUES(404, 80, 7, 'BA4DUP', 'duplicate', 0);
                INSERT INTO checkins VALUES(405, 80, 8, 'BA4DEL', 'deleted', 1);
                INSERT INTO checkins VALUES(406, 999, 9, 'BA4MISS', 'unmapped', 0);
                INSERT INTO checkins VALUES(407, 80, 0, 'BA4FIRST', 'invalid sequence', 0);
                INSERT INTO checkins VALUES(408, 80, 1, 'BA4NEXT', 'sequence conflict', 0);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            var existingSession = await nativeStore.CreateSessionAsync(
                "其他原生场次", "2026-10-02", "N0CALL", "现有中继", "existing.xlsx", "existing-sheet");
            await InsertNativeCheckinAsync(nativePath, existingSession.Id,
                "legacy-python:404", 55, isDeleted: true);

            var first = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.True(first.Imported);
            Assert.Equal(1, first.ImportedSessions);
            Assert.Equal(2, first.ImportedCheckins);
            Assert.Equal(3, first.SkippedCheckins);
            var sessions = await nativeStore.ListSessionsAsync();
            var importedSession = Assert.Single(sessions.Where(session => session.Name == "复用场次"));
            Assert.Equal("ended", importedSession.Status);
            Assert.Equal("旧操作员", importedSession.OperatorCallsign);
            Assert.Equal("旧中继", importedSession.RepeaterName);
            var unchangedSession = Assert.Single(sessions.Where(session => session.Id == existingSession.Id));
            Assert.Equal("N0CALL", unchangedSession.OperatorCallsign);
            Assert.Equal("existing.xlsx", unchangedSession.WorkbookPath);
            Assert.Equal("existing-sheet", unchangedSession.SheetName);

            var rows = await nativeStore.LoadRecentAsync(importedSession.Id, 20);
            Assert.Equal(new[] { 1, 2 }, rows.OrderBy(row => row.SequenceNo).Select(row => row.SequenceNo));
            Assert.Equal(new[] { "BA4FIRST", "BA4NEXT" }, rows.OrderBy(row => row.SequenceNo).Select(row => row.Callsign));
            using (var marker = JsonDocument.Parse(await ReadMigrationMarkerAsync(nativePath)))
            {
                Assert.Equal("completed", marker.RootElement.GetProperty("status").GetString());
                Assert.Equal(1, marker.RootElement.GetProperty("sessions").GetInt32());
                Assert.Equal(2, marker.RootElement.GetProperty("checkins").GetInt32());
                Assert.Equal(3, marker.RootElement.GetProperty("skipped").GetInt32());
            }

            var second = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.False(second.Imported);
            Assert.Contains("已经完成过迁移", second.Message);
            Assert.Equal(2, (await nativeStore.LoadRecentAsync(importedSession.Id, 20)).Count);
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData("completed")]
    [InlineData("skipped-native-data-exists")]
    public async Task LegacyMarkersRemainTerminalAndReportUntraceableMappings(string markerStatus)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER, callsign TEXT);
                INSERT INTO sessions VALUES(9, '未导入场次', '2026-10-04');
                INSERT INTO checkins VALUES(10, 9, 'BA4LEGACY');
                """);
            var sourceBefore = await ReadLegacySnapshotAsync(legacyPath);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            var existingSession = await nativeStore.CreateSessionAsync("现有场次", "2026-10-05");
            await InsertNativeCheckinAsync(nativePath, existingSession.Id,
                "native-existing", 1, isDeleted: false);
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var markerCommand = connection.CreateCommand())
            {
                markerCommand.CommandText = "INSERT INTO native_meta(key, value) VALUES('legacy_python_import', $value)";
                markerCommand.Parameters.AddWithValue("$value", JsonSerializer.Serialize(new { status = markerStatus }));
                await markerCommand.ExecuteNonQueryAsync();
            }

            var first = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.False(first.Imported);
            Assert.Equal(0, first.ImportedSessions);
            Assert.Equal(0, first.ImportedCheckins);
            Assert.Contains("已经完成过迁移", first.Message);
            Assert.Contains("不可追溯", first.Message);
            using (var marker = JsonDocument.Parse(await ReadMigrationMarkerAsync(nativePath)))
            {
                Assert.Equal(markerStatus, marker.RootElement.GetProperty("status").GetString());
            }
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));

            var second = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.False(second.Imported);
            Assert.Contains("已经完成过迁移", second.Message);
            Assert.Contains("不可追溯", second.Message);
            Assert.False(Directory.Exists(backupRoot));
            Assert.Equal(sourceBefore, await ReadLegacySnapshotAsync(legacyPath));
            Assert.Single(await nativeStore.LoadRecentAsync(existingSession.Id, 20));
            Assert.Single(await nativeStore.ListSessionsAsync());
            File.Delete(legacyPath);
            var withoutSource = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.False(withoutSource.Imported);
            Assert.Contains("不可追溯", withoutSource.Message);
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData("{")]
    [InlineData("{\"status\":\"pending\"}")]
    [InlineData(null)]
    public async Task ExistingInvalidMigrationMarkerFailsClosed(string? markerValue)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER);
                INSERT INTO sessions VALUES(1, '标记拒绝场次', '2026-11-15');
                """);
            await CreateDatabaseAsync(nativePath, """
                CREATE TABLE native_meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE sessions(id INTEGER PRIMARY KEY);
                """);
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "INSERT INTO native_meta(key, value) VALUES('legacy_python_import', $value)";
                command.Parameters.AddWithValue("$value", (object?)markerValue ?? DBNull.Value);
                await command.ExecuteNonQueryAsync();
            }

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.False(result.Imported);
            Assert.Contains("迁移标记状态无法识别", result.Message);
            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("1", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.False(Directory.Exists(backupRoot));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData(1, false, false)]
    [InlineData(5, false, false)]
    [InlineData(6, true, false)]
    [InlineData(10, true, false)]
    [InlineData(6, true, true)]
    public async Task SupportsVerifiedVersionsAndPersistsSessionIdentity(
        int version, bool hasIdentityColumns, bool blankIdentity)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            var columns = hasIdentityColumns ? ", external_source, external_uid, external_key" : "";
            var definitions = hasIdentityColumns
                ? ", external_source TEXT, external_uid TEXT, external_key TEXT" : "";
            var values = !hasIdentityColumns ? "" : blankIdentity ? ", NULL, '', '  '" : ", 'feed', 'uid-1', 'key-1'";
            await CreateDatabaseAsync(legacyPath, $"""
                PRAGMA user_version = {version};
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT,
                    operator_callsign TEXT, repeater_name TEXT{definitions});
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions(id, name, date, operator_callsign, repeater_name{columns})
                    VALUES(1, '版本场次', '2026-11-15', 'operator', 'repeater'{values});
                INSERT INTO checkins VALUES(10, 1, 1, 'BA4TEST', 'fixture', 0);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.True(result.Imported, result.Message);
            Assert.Equal(1, result.ImportedSessions);
            Assert.Equal(1, result.ImportedCheckins);
            var mappingRow = await ReadSingleRowAsync(nativePath,
                "SELECT value FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'");
            using (var mapping = JsonDocument.Parse(mappingRow[0]))
            {
                var expectedIdentityType = hasIdentityColumns && !blankIdentity ? "external-triple" : "none";
                Assert.Equal(expectedIdentityType, mapping.RootElement.GetProperty("IdentityType").GetString());
                Assert.Equal(hasIdentityColumns && !blankIdentity ? "feed" : "",
                    mapping.RootElement.GetProperty("ExternalSource").GetString() ?? "");
                Assert.Equal("created", mapping.RootElement.GetProperty("Decision").GetString());
                Assert.False(string.IsNullOrWhiteSpace(mapping.RootElement.GetProperty("Reason").GetString()));
            }
            using (var marker = JsonDocument.Parse(await ReadMigrationMarkerAsync(nativePath)))
            {
                Assert.Equal(1, marker.RootElement.GetProperty("mappingVersion").GetInt32());
                Assert.Equal(1, marker.RootElement.GetProperty("mappedSessions").GetInt32());
            }
            await using var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadOnly);
            await using var command = connection.CreateCommand();
            command.CommandText = "PRAGMA foreign_key_check";
            await using var reader = await command.ExecuteReaderAsync();
            Assert.False(await reader.ReadAsync());
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData(0, 0)]
    [InlineData(11, 0)]
    [InlineData(6, 0)]
    [InlineData(1, 3)]
    [InlineData(6, 1)]
    [InlineData(10, 2)]
    public async Task UnsupportedVersionOrIdentityColumnsFailTheWholeBatch(int version, int columnCount)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            var names = new[] { "external_source", "external_uid", "external_key" };
            var definitions = string.Join(", ", names.Take(columnCount).Select(name => $"{name} TEXT"));
            var columns = columnCount == 0 ? "" : ", " + string.Join(", ", names.Take(columnCount));
            var values = columnCount == 0 ? "" : ", " + string.Join(", ", Enumerable.Repeat("'value'", columnCount));
            await CreateDatabaseAsync(legacyPath, $"""
                PRAGMA user_version = {version};
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT{(columnCount == 0 ? "" : ", " + definitions)});
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER);
                INSERT INTO sessions(id, name, date{columns})
                    VALUES(1, '不匹配场次', '2026-11-15'{values});
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.False(result.Imported);
            Assert.Contains("已拒绝整批导入", result.Message);
            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
            Assert.False(Directory.Exists(backupRoot));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Theory]
    [InlineData("partial")]
    [InlineData("duplicate-identity")]
    [InlineData("duplicate-date-name")]
    [InlineData("duplicate-session-id")]
    public async Task PartialOrDuplicateIdentityAndSessionKeysFailTheWholeBatch(string failureCase)
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            var rows = failureCase switch
            {
                "partial" => "(1, '有效场次', '2026-11-01', 'feed', 'uid-1', 'key-1'), " +
                    "(2, '部分空场次', '2026-11-02', 'feed', '', 'key-2')",
                "duplicate-identity" => "(1, '首场', '2026-11-01', 'feed', 'uid-1', 'same-key'), " +
                    "(2, '次场', '2026-11-02', 'feed', 'uid-1', 'same-key')",
                "duplicate-session-id" => "(1, '首场', '2026-11-01', 'feed', 'uid-1', 'key-1'), " +
                    "(1, '次场', '2026-11-02', 'feed', 'uid-2', 'key-2')",
                _ => "(1, '同名场次', '2026-11-01', 'feed', 'uid-1', 'key-1'), " +
                    "(2, '同名场次', '2026-11-01', 'feed', 'uid-2', 'key-2')"
            };
            await CreateDatabaseAsync(legacyPath, $"""
                PRAGMA user_version = 6;
                CREATE TABLE sessions(
                    id INTEGER, name TEXT, date TEXT,
                    external_source TEXT, external_uid TEXT, external_key TEXT);
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER);
                INSERT INTO sessions VALUES {rows};
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.False(result.Imported);
            Assert.Contains("已拒绝整批导入", result.Message);
            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
            Assert.False(Directory.Exists(backupRoot));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task ExactPersistedMappingAllowsReplayWithoutCreatingAnotherSessionOrCheckin()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 6;
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT,
                    operator_callsign TEXT, repeater_name TEXT,
                    external_source TEXT, external_uid TEXT, external_key TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions VALUES(42, '映射重放', '2026-11-12', 'operator', 'repeater',
                    'catalog', 'uid-42', 'session-42');
                INSERT INTO checkins VALUES(90, 42, 1, 'BA4REPLAY', 'once', 0);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            var first = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.True(first.Imported, first.Message);
            Assert.Equal(1, first.ImportedSessions);
            Assert.Equal(1, first.ImportedCheckins);
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "DELETE FROM native_meta WHERE key = 'legacy_python_import'";
                await command.ExecuteNonQueryAsync();
            }

            var replay = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.True(replay.Imported, replay.Message);
            Assert.Equal(0, replay.ImportedSessions);
            Assert.Equal(0, replay.ImportedCheckins);
            Assert.Equal(1, replay.SkippedCheckins);
            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM checkins"));
            Assert.Equal("1", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
            var mappingRow = await ReadSingleRowAsync(nativePath,
                "SELECT value FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'");
            using var mapping = JsonDocument.Parse(mappingRow[0]);
            Assert.Equal("reused-exact-map", mapping.RootElement.GetProperty("Decision").GetString());
            Assert.Equal("exact-persisted-old-to-native-session-mapping",
                mapping.RootElement.GetProperty("Reason").GetString());
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "DELETE FROM native_meta WHERE key = 'legacy_python_import'";
                await command.ExecuteNonQueryAsync();
            }
            await using (var connection = await OpenConnectionAsync(legacyPath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "UPDATE sessions SET external_key = 'changed-key' WHERE id = 42";
                await command.ExecuteNonQueryAsync();
            }
            var changedIdentity = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);
            Assert.False(changedIdentity.Imported);
            Assert.Contains("映射与源记录不一致", changedIdentity.Message);
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("1", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM checkins"));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task PersistsSeparateMappingsAndCheckinsForEachLegacySession()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 6;
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT,
                    external_source TEXT, external_uid TEXT, external_key TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions VALUES(11, '第一场', '2026-11-10', 'feed', 'uid-11', 'key-11');
                INSERT INTO sessions VALUES(22, '第二场', '2026-11-11', 'feed', 'uid-22', 'key-22');
                INSERT INTO checkins VALUES(101, 11, 1, 'BA4FIRST', 'first', 0);
                INSERT INTO checkins VALUES(202, 22, 1, 'BA4SECOND', 'second', 0);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.True(result.Imported, result.Message);
            Assert.Equal(2, result.ImportedSessions);
            Assert.Equal(2, result.ImportedCheckins);
            var nativeIdsByOldId = new Dictionary<long, long>();
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadOnly))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "SELECT value FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'";
                await using var reader = await command.ExecuteReaderAsync();
                while (await reader.ReadAsync())
                {
                    using var mapping = JsonDocument.Parse(reader.GetString(0));
                    nativeIdsByOldId.Add(
                        mapping.RootElement.GetProperty("OldSessionId").GetInt64(),
                        mapping.RootElement.GetProperty("NativeSessionId").GetInt64());
                }
            }
            Assert.Equal(2, nativeIdsByOldId.Count);
            Assert.NotEqual(nativeIdsByOldId[11], nativeIdsByOldId[22]);
            using (var marker = JsonDocument.Parse(await ReadMigrationMarkerAsync(nativePath)))
            {
                Assert.Equal(2, marker.RootElement.GetProperty("mappedSessions").GetInt32());
            }
            Assert.Equal(nativeIdsByOldId[11].ToString(CultureInfo.InvariantCulture),
                (await ReadSingleRowAsync(nativePath,
                    "SELECT session_id FROM checkins WHERE submission_id = 'legacy-python:101'"))[0]);
            Assert.Equal(nativeIdsByOldId[22].ToString(CultureInfo.InvariantCulture),
                (await ReadSingleRowAsync(nativePath,
                    "SELECT session_id FROM checkins WHERE submission_id = 'legacy-python:202'"))[0]);
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task ExistingSameNameSessionConflictsEvenWhenOperatorAndRepeaterMatch()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 6;
                CREATE TABLE sessions(
                    id INTEGER PRIMARY KEY, name TEXT, date TEXT,
                    operator_callsign TEXT, repeater_name TEXT,
                    external_source TEXT, external_uid TEXT, external_key TEXT);
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER);
                INSERT INTO sessions VALUES(7, '精确冲突', '2026-11-14', 'BA4SAME', '同一中继',
                    'catalog', 'uid-7', 'session-7');
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            var existing = await nativeStore.CreateSessionAsync(
                "精确冲突", "2026-11-14", "BA4SAME", "同一中继");

            var result = await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot);

            Assert.False(result.Imported);
            Assert.Contains("没有精确且已持久化", result.Message);
            Assert.Equal(existing.Id.ToString(CultureInfo.InvariantCulture),
                (await ReadSingleRowAsync(nativePath, "SELECT id FROM sessions"))[0]);
            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM checkins"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
            Assert.False(Directory.Exists(backupRoot));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task CheckinFailureRollsBackSessionMappingAndCompletionMarker()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY, session_id INTEGER, sequence_no INTEGER,
                    callsign TEXT, raw_input TEXT, is_deleted INTEGER);
                INSERT INTO sessions VALUES(8, '回滚场次', '2026-11-13');
                INSERT INTO checkins VALUES(80, 8, 1, 'BA4ROLLBACK', 'failure', 0);
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            await using (var connection = await OpenConnectionAsync(nativePath, SqliteOpenMode.ReadWrite))
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = """
                    CREATE TRIGGER reject_legacy_checkin BEFORE INSERT ON checkins
                    WHEN NEW.submission_id LIKE 'legacy-python:%'
                    BEGIN SELECT RAISE(ABORT, 'injected test failure'); END;
                    """;
                await command.ExecuteNonQueryAsync();
            }

            await Assert.ThrowsAsync<SqliteException>(async () =>
                await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot));

            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM checkins"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    [Fact]
    public async Task CancellationDoesNotWriteMappingsOrCompletionMarker()
    {
        var root = CreateTestRoot();
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            await CreateDatabaseAsync(legacyPath, """
                PRAGMA user_version = 1;
                CREATE TABLE sessions(id INTEGER PRIMARY KEY, name TEXT, date TEXT);
                CREATE TABLE checkins(id INTEGER PRIMARY KEY, session_id INTEGER);
                INSERT INTO sessions VALUES(9, '取消场次', '2026-11-12');
                """);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();
            using var cancellation = new CancellationTokenSource();
            cancellation.Cancel();

            await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
                await LegacyPythonMigration.TryImportAsync(nativePath, legacyPath, backupRoot, cancellation.Token));

            Assert.Equal("0", await ReadScalarAsync(nativePath, "SELECT COUNT(*) FROM sessions"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key = 'legacy_python_import'"));
            Assert.Equal("0", await ReadScalarAsync(nativePath,
                "SELECT COUNT(*) FROM native_meta WHERE key LIKE 'legacy_python_session_map:%'"));
        }
        finally
        {
            DeleteTestRoot(root);
        }
    }

    private static string CreateTestRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "ham-native-migration", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    private static void DeleteTestRoot(string root)
    {
        try
        {
            Directory.Delete(root, recursive: true);
        }
        catch (IOException)
        {
        }
    }

    private static async Task CreateDatabaseAsync(string path, string commandText)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadWriteCreate);
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<SqliteConnection> OpenConnectionAsync(string path, SqliteOpenMode mode)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = mode,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        return connection;
    }

    private static async Task<string[]> ReadSingleRowAsync(string path, string commandText)
    {
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadOnly);
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        await using var reader = await command.ExecuteReaderAsync();
        Assert.True(await reader.ReadAsync());
        var values = new string[reader.FieldCount];
        for (var i = 0; i < values.Length; i++)
        {
            values[i] = Convert.ToString(reader.GetValue(i), CultureInfo.InvariantCulture) ?? "";
        }
        Assert.False(await reader.ReadAsync());
        return values;
    }

    private static async Task<LegacyDatabaseSnapshot> ReadLegacySnapshotAsync(string path)
    {
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadOnly);
        var schema = await ReadRowsAsJsonAsync(connection, """
            SELECT name, sql FROM sqlite_master
            WHERE type = 'table' AND name IN ('sessions', 'checkins')
            ORDER BY name
            """);
        var sessions = await ReadRowsAsJsonAsync(connection, "SELECT * FROM sessions ORDER BY rowid");
        var checkins = await ReadRowsAsJsonAsync(connection, "SELECT * FROM checkins ORDER BY rowid");
        return new LegacyDatabaseSnapshot(schema, sessions, checkins);
    }

    private static async Task<string> ReadRowsAsJsonAsync(SqliteConnection connection, string commandText)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        await using var reader = await command.ExecuteReaderAsync();
        var rows = new List<string?[]>();
        while (await reader.ReadAsync())
        {
            var row = new string?[reader.FieldCount];
            for (var i = 0; i < row.Length; i++)
            {
                row[i] = reader.IsDBNull(i)
                    ? null
                    : Convert.ToString(reader.GetValue(i), CultureInfo.InvariantCulture);
            }
            rows.Add(row);
        }
        return JsonSerializer.Serialize(rows);
    }

    private static async Task InsertNativeCheckinAsync(
        string path, long sessionId, string submissionId, int sequenceNo, bool isDeleted)
    {
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadWrite);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO checkins(
                submission_id, session_id, sequence_no, checkin_time, callsign, raw_input,
                is_deleted, created_at, updated_at)
            VALUES($submission, $session, $sequence, '20:00', 'BA4SEED', 'seed row',
                   $deleted, '2026-10-03T20:00:00Z', '2026-10-03T20:00:00Z')
            """;
        command.Parameters.AddWithValue("$submission", submissionId);
        command.Parameters.AddWithValue("$session", sessionId);
        command.Parameters.AddWithValue("$sequence", sequenceNo);
        command.Parameters.AddWithValue("$deleted", isDeleted ? 1 : 0);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<string> ReadScalarAsync(string path, string commandText)
    {
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadOnly);
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        return Convert.ToString(await command.ExecuteScalarAsync(), CultureInfo.InvariantCulture) ?? "";
    }

    private static async Task<string> ReadMigrationMarkerAsync(string path)
    {
        await using var connection = await OpenConnectionAsync(path, SqliteOpenMode.ReadOnly);
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM native_meta WHERE key = 'legacy_python_import'";
        return Convert.ToString(await command.ExecuteScalarAsync(), CultureInfo.InvariantCulture)
            ?? throw new InvalidOperationException("迁移标记缺失。");
    }

    private static void AssertCurrentUtc(string value, DateTimeOffset earliest, DateTimeOffset latest)
    {
        Assert.True(DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture,
            DateTimeStyles.RoundtripKind, out var timestamp));
        Assert.Equal(TimeSpan.Zero, timestamp.Offset);
        Assert.InRange(timestamp, earliest, latest);
    }

    private sealed record LegacyDatabaseSnapshot(string Schema, string Sessions, string Checkins);
}
