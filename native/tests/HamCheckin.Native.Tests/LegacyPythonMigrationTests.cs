using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;
using Xunit;

namespace HamCheckin.Native.Tests;

public sealed class LegacyPythonMigrationTests
{
    [Fact]
    public async Task ImportsLegacyRowsWithBackupAndDoesNotRepeat()
    {
        var root = Path.Combine(Path.GetTempPath(), "ham-native-migration", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var nativePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var legacyPath = Path.Combine(root, "data", "ham_checkin.db");
        var backupRoot = Path.Combine(root, "backup");
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(legacyPath)!);
            await CreateLegacyDatabaseAsync(legacyPath);
            await using var nativeStore = new NativeStore(nativePath);
            await nativeStore.InitializeAsync();

            var first = await LegacyPythonMigration.TryImportAsync(
                nativePath, legacyPath, backupRoot);

            Assert.True(first.Imported);
            Assert.Equal(1, first.ImportedSessions);
            Assert.Equal(2, first.ImportedCheckins);
            Assert.True(File.Exists(first.BackupPath));
            Assert.True(File.Exists(legacyPath));

            var sessions = await nativeStore.ListSessionsAsync();
            Assert.Single(sessions);
            Assert.Equal("第2场点名", sessions[0].Name);
            var rows = await nativeStore.LoadRecentAsync(sessions[0].Id, 20);
            Assert.Equal(2, rows.Count);
            Assert.Contains(rows, row => row.Callsign == "BA4RLL" && row.RawInput.Contains("pd780"));
            Assert.Contains(rows, row => row.Unmatched == "车载苗子");

            var second = await LegacyPythonMigration.TryImportAsync(
                nativePath, legacyPath, backupRoot);

            Assert.False(second.Imported);
            Assert.Contains("已经完成过迁移", second.Message);
            Assert.Equal(2, (await nativeStore.LoadRecentAsync(sessions[0].Id, 20)).Count);
            Assert.Equal(2, await CountLegacyRowsAsync(legacyPath));
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch (IOException) { }
        }
    }

    private static async Task CreateLegacyDatabaseAsync(string path)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE sessions(
                id INTEGER PRIMARY KEY,
                name TEXT,
                date TEXT,
                operator_callsign TEXT,
                repeater_name TEXT,
                started_at TEXT,
                ended_at TEXT,
                excel_path TEXT,
                excel_sheet_name TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT);
            CREATE TABLE checkins(
                id INTEGER PRIMARY KEY,
                session_id INTEGER,
                sequence_no INTEGER,
                checkin_time TEXT,
                callsign TEXT,
                qth_raw TEXT,
                qth_standard TEXT,
                device_raw TEXT,
                device_standard TEXT,
                antenna_raw TEXT,
                antenna_standard TEXT,
                power_raw TEXT,
                power_standard TEXT,
                signal TEXT,
                source TEXT,
                raw_input TEXT,
                unmatched TEXT,
                is_deleted INTEGER,
                created_at TEXT,
                updated_at TEXT);
            INSERT INTO sessions VALUES(7,'第2场点名','2026-08-28','BA4THG','江苏省中继',
                '2026-08-28T20:00:00+08:00','','C:/old.xlsx','第2场点名','ended',
                '2026-08-28T20:00:00+08:00','2026-08-28T22:00:00+08:00');
            INSERT INTO checkins VALUES(101,7,1,'21:00','BA4RLL','njxw','江苏省南京市玄武区',
                'pd780','海能达 PD-780','4.2m','4.2米玻璃钢','5w','5W','59','local',
                'BA4RLL njxw pd780 4.2m 5w','',0,'2026-08-28T21:00:00+08:00','2026-08-28T21:00:00+08:00');
            INSERT INTO checkins VALUES(102,7,2,'21:01','BA4VXR','njgl','江苏省南京市鼓楼区',
                'm8268','摩托罗拉 M8268','车苗','车载苗子','25w','25W','59','local',
                'BA4VXR njgl m8268 车苗 25w','车载苗子',0,'2026-08-28T21:01:00+08:00','2026-08-28T21:01:00+08:00');
            """;
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<int> CountLegacyRowsAsync(string path)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadOnly,
            Pooling = false
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM checkins";
        return Convert.ToInt32(await command.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }
}
