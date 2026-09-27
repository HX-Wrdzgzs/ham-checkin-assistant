using System.IO.Compression;
using System.Text;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using DocumentFormat.OpenXml.Validation;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Export;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

/// <summary>
/// A single isolated end-to-end flow. This intentionally crosses the same
/// boundaries used by the app: parser -> SQLite -> field edit/audit state ->
/// restart -> Open XML export. It never touches the user's production store
/// or an open Excel process.
/// </summary>
public sealed class NativeEndToEndTests
{
    [Fact]
    public async Task IsolatedCheckinEditRaceRestartAndExcelFlowRemainsConsistent()
    {
        var root = Path.Combine(Path.GetTempPath(), $"ham-native-e2e-{Guid.NewGuid():N}");
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var exportPath = Path.Combine(root, "exports", "第1场点名_2026-09-26.xlsx");
        Directory.CreateDirectory(root);

        try
        {
            var parser = new InputParser(CatalogLoader.CreateBuiltIn());
            var session = await CreateAndFillStoreAsync(
                databasePath, exportPath, parser);

            await using (var raceStore = new NativeStore(databasePath, storeDelayMilliseconds: 150))
            {
                await raceStore.InitializeAsync();
                var draftService = new QuickInputDraftService();
                var submitted = draftService.ApplyUserEdit(
                    "main-input", 0, "BA4A500 NJXW PD780 5W");
                var saveTask = raceStore.AddCheckinAsync(
                    session,
                    parser.Parse(submitted.Text),
                    submissionId: "end-to-end-race-a");

                var newer = draftService.ApplyUserEdit(
                    "main-input", submitted.Revision, "BA4A500 NJXW R6 5W");
                await saveTask;

                Assert.False(draftService.TryClear(submitted.Revision));
                Assert.Equal(newer.Text, draftService.Current.Text);
                Assert.Equal("BA4A500 NJXW R6 5W", draftService.Current.Text);
            }

            await using var reopened = new NativeStore(databasePath);
            await reopened.InitializeAsync();
            var reopenedSession = await reopened.GetSessionAsync(session.Id);
            Assert.NotNull(reopenedSession);
            Assert.Equal("第1场点名", reopenedSession!.Name);
            Assert.Equal("2026-09-26", reopenedSession.Date);
            Assert.Equal("BA4THG", reopenedSession.OperatorCallsign);
            Assert.Equal("江苏省中继", reopenedSession.RepeaterName);

            var rows = await reopened.LoadRecentAsync(session.Id, 1000);
            Assert.Equal(501, rows.Count);
            Assert.Equal(
                Enumerable.Range(1, 501).Reverse(),
                rows.Select(static row => row.SequenceNo));
            Assert.Equal("ok", await reopened.QuickCheckAsync());

            await new ExcelExportService().ExportAsync(reopenedSession, rows, exportPath);
            Assert.True(File.Exists(exportPath));
            AssertExcelWorkbook(exportPath, reopenedSession, rows.Count);
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static async Task<SessionInfo> CreateAndFillStoreAsync(
        string databasePath,
        string exportPath,
        InputParser parser)
    {
        await using var store = new NativeStore(databasePath);
        await store.InitializeAsync();
        var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 9, 26));
        session = await store.UpdateSessionInfoAsync(
            session,
            "BA4THG",
            "江苏省中继",
            exportPath,
            "第1场点名");

        var first = parser.Parse("BA4A000 NJXW PD780 4.2M 5W extra1 extra2");
        Assert.Equal("BA4A000", first.Callsign.Value);
        Assert.Equal("江苏省南京市玄武区", first.Qth.Value);
        Assert.Equal("海能达 PD-780", first.Device.Value);
        Assert.Equal("4.2米玻璃钢", first.Antenna.Value);
        Assert.Equal("5W", first.Power.Value);
        Assert.Contains("extra1", first.Unmatched);
        Assert.Contains("extra2", first.Unmatched);

        var firstRow = await store.AddCheckinAsync(session, first, "end-to-end-first");
        for (var index = 1; index < 500; index++)
        {
            var callsign = $"BA4A{index:D3}";
            var result = parser.Parse($"{callsign} NJXW R6 5W");
            Assert.True(result.CanSubmit, callsign);
            await store.AddCheckinAsync(session, result, $"end-to-end-{index:D3}");
        }

        var qthRequest = await store.CreateFieldEditRequestAsync(firstRow.Id, FieldKind.Qth);
        Assert.NotNull(qthRequest);
        var editedQth = await store.ApplyFieldEditAsync(new FieldEditCommit(
            firstRow.Id,
            FieldKind.Qth,
            qthRequest!.CurrentValue,
            "江苏省南京市鼓楼区",
            "njgl",
            new[] { "extra1" },
            RemoveConsumedTokens: true,
            qthRequest.ExpectedUpdatedAt,
            "QTH 行政区库",
            new[] { 0 }));
        Assert.Equal("江苏省南京市鼓楼区", editedQth.Qth);
        Assert.Equal("海能达 PD-780", editedQth.Device);
        Assert.Equal("4.2米玻璃钢", editedQth.Antenna);
        Assert.Equal("extra2", editedQth.Unmatched);

        var deviceRequest = await store.CreateFieldEditRequestAsync(firstRow.Id, FieldKind.Device);
        Assert.NotNull(deviceRequest);
        var editedDevice = await store.ApplyFieldEditAsync(new FieldEditCommit(
            firstRow.Id,
            FieldKind.Device,
            deviceRequest!.CurrentValue,
            "摩托罗拉 R6",
            "r6",
            Array.Empty<string>(),
            RemoveConsumedTokens: false,
            deviceRequest.ExpectedUpdatedAt,
            "现场设备词典"));
        Assert.Equal("摩托罗拉 R6", editedDevice.Device);
        Assert.Equal(editedQth.Qth, editedDevice.Qth);
        Assert.Equal(editedQth.Antenna, editedDevice.Antenna);
        Assert.Equal("extra2", editedDevice.Unmatched);

        var antennaRequest = await store.CreateFieldEditRequestAsync(firstRow.Id, FieldKind.Antenna);
        Assert.NotNull(antennaRequest);
        var editedAntenna = await store.ApplyFieldEditAsync(new FieldEditCommit(
            firstRow.Id,
            FieldKind.Antenna,
            antennaRequest!.CurrentValue,
            "1.8米玻璃钢",
            "1.8m",
            new[] { "extra2" },
            RemoveConsumedTokens: true,
            antennaRequest.ExpectedUpdatedAt,
            "天线别名",
            new[] { 0 }));
        Assert.Equal("1.8米玻璃钢", editedAntenna.Antenna);
        Assert.Equal("摩托罗拉 R6", editedAntenna.Device);
        Assert.Equal("江苏省南京市鼓楼区", editedAntenna.Qth);
        Assert.Empty(editedAntenna.Unmatched);

        return session;
    }

    private static void AssertExcelWorkbook(
        string path,
        SessionInfo session,
        int expectedRowCount)
    {
        using (var document = SpreadsheetDocument.Open(path, false))
        {
            var errors = new OpenXmlValidator(FileFormatVersions.Office2019)
                .Validate(document)
                .ToArray();
            Assert.Empty(errors);
            Assert.Single(document.WorkbookPart!.Workbook.Sheets!.Elements<Sheet>());
            var sheet = document.WorkbookPart.WorksheetParts.Single().Worksheet;
            Assert.Equal("A5", sheet.SheetViews!.Elements<SheetView>().Single()
                .Elements<Pane>().Single().TopLeftCell?.Value);
            Assert.Equal(
                expectedRowCount + 4,
                sheet.Elements<SheetData>().Single().Elements<Row>().Count());
        }

        using var archive = ZipFile.OpenRead(path);
        var sheetEntry = archive.GetEntry("xl/worksheets/sheet1.xml");
        Assert.NotNull(sheetEntry);
        using var reader = new StreamReader(sheetEntry!.Open(), Encoding.UTF8);
        var xml = reader.ReadToEnd();
        Assert.Contains(session.Name, xml);
        Assert.Contains(session.Date, xml);
        Assert.Contains(session.OperatorCallsign, xml);
        Assert.Contains(session.RepeaterName, xml);
        Assert.DoesNotContain("未识别", xml);
        foreach (var header in ExcelExportService.Headers)
        {
            Assert.Contains(header, xml);
        }

    }
}
