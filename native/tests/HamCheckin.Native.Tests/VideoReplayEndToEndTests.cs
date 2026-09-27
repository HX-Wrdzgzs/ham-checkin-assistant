using System.IO.Compression;
using System.Text;
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
/// Replays the values that are readable in the supplied desktop recordings.
/// The recordings are evidence only; this test never opens, edits, or writes
/// the original videos or the user's production database.
/// </summary>
public sealed class VideoReplayEndToEndTests
{
    private static readonly VideoCase[] Cases =
    {
        new(
            "21:57:30",
            "ba4szj mtm8268 5w 车载苗子",
            "BA4SZJ", "", "摩托罗拉 M8268", "车载苗子", "5W", "", ""),
        new(
            "22:15:00",
            "ba4vuu njjy ct1300 高 yz",
            "BA4VUU", "江苏省南京市建邺区", "摩托罗拉 CT1300", "原装天线", "高", "", ""),
        new(
            "22:20:00",
            "ba4vjd bfuv5r 771",
            "BA4VJD", "", "宝峰 UV-5R", "SRH-771", "", "", ""),
        new(
            "22:30:00",
            "ba4vnn isvcxs bfuv5r yz 高",
            "BA4VNN", "江苏省扬州市", "宝峰 UV-5R", "", "高", "", "isvcxs"),
        new(
            "22:34:43",
            "bd4wye shks8600 4单元八木 秦淮区大光路 5w",
            "BD4WYE", "江苏省南京市秦淮区大光路", "森海克斯 8600", "4单元八木", "5W", "", ""),
        new(
            "23:05:15",
            "ba4vei njgl uvk6 5w",
            "BA4VEI", "江苏省南京市鼓楼区", "泉盛 UV-K6", "", "5W", "", ""),
        new(
            "23:07:35",
            "bd1ekh njqx uvk6 srh518 满",
            "BD1EKH", "江苏省南京市栖霞区", "泉盛 UV-K6", "SRH-518", "满", "", ""),
    };

    [Fact]
    public async Task ReplaysVideoInputsThroughEditRestartAndExcelExport()
    {
        var root = Path.Combine(Path.GetTempPath(), $"ham-video-e2e-{Guid.NewGuid():N}");
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        var exportPath = Path.Combine(root, "exports", "第2场点名_2026-09-25.xlsx");
        Directory.CreateDirectory(root);

        try
        {
            var parser = new InputParser(CatalogLoader.CreateBuiltIn());
            await using (var store = new NativeStore(databasePath))
            {
            await store.InitializeAsync();
            var session = await store.CreateSessionAsync("第2场点名", "2026-09-25");

            var rows = new List<CheckinEntry>();
            foreach (var item in Cases)
            {
                var parsed = parser.Parse(item.RawInput);
                Assert.Equal(item.Callsign, parsed.Callsign.Value);
                Assert.Equal(item.Qth, parsed.Qth.Value);
                Assert.Equal(item.Device, parsed.Device.Value);
                Assert.Equal(item.Antenna, parsed.Antenna.Value);
                Assert.Equal(item.Power, parsed.Power.Value);
                Assert.Equal(item.Unmatched, parsed.UnmatchedText);
                rows.Add(await store.AddCheckinAsync(
                    session, parsed, $"video-{item.VideoTime.Replace(':', '-')}") );
            }

            // 这条来自视频中途的“ba”只是在输入框里的半条草稿，不能伪造为一次点名。
            var partial = parser.Parse("ba");
            Assert.False(partial.CanSubmit);
            Assert.Equal("ba", partial.RawText);

            // 复现视频里的设备字段修正：只改设备，QTH/天线/功率不能跟着被重解析。
            var deviceRequest = await store.CreateFieldEditRequestAsync(
                rows[4].Id, FieldKind.Device);
            Assert.NotNull(deviceRequest);
            var edited = await store.ApplyFieldEditAsync(new FieldEditCommit(
                rows[4].Id,
                FieldKind.Device,
                deviceRequest!.CurrentValue,
                "森海克斯 8600",
                "森海克斯 8600",
                Array.Empty<string>(),
                RemoveConsumedTokens: false,
                deviceRequest.ExpectedUpdatedAt,
                "现场设备词典"));
            Assert.Equal("森海克斯 8600", edited.Device);
            Assert.Equal("江苏省南京市秦淮区大光路", edited.Qth);
            Assert.Equal("4单元八木", edited.Antenna);
            Assert.Equal("5W", edited.Power);
            Assert.Equal(Cases[4].RawInput, edited.RawInput);

            // 未识别内容保留在数据库中，只有明确消费的 token 才能移除。
            var unmatchedRequest = await store.CreateFieldEditRequestAsync(
                rows[3].Id, FieldKind.Qth);
            Assert.NotNull(unmatchedRequest);
            var keptUnmatched = await store.ApplyFieldEditAsync(new FieldEditCommit(
                rows[3].Id,
                FieldKind.Qth,
                unmatchedRequest!.CurrentValue,
                "江苏省扬州市",
                "江苏省扬州市",
                Array.Empty<string>(),
                RemoveConsumedTokens: false,
                unmatchedRequest.ExpectedUpdatedAt,
                "QTH 行政区库"));
            Assert.Equal("江苏省扬州市", keptUnmatched.Qth);
            Assert.Equal("isvcxs", keptUnmatched.Unmatched);

            // 真实录入中的提交竞态：保存第一条期间开始输入下一条，下一条草稿必须保留。
            var delayedInput = new QuickInputDraftService();
            var firstDraft = delayedInput.ApplyUserEdit(
                "main-input", 0, "ba4tmt njqx gm338 5单元八木 25w");
            await using (var delayedStore = new NativeStore(databasePath, storeDelayMilliseconds: 120))
            {
                await delayedStore.InitializeAsync();
                var saveTask = delayedStore.AddCheckinAsync(
                    session, parser.Parse(firstDraft.Text), "video-race-first");
                var nextDraft = delayedInput.ApplyUserEdit(
                    "main-input", firstDraft.Revision,
                    "ba4rll njgl p8260 yz 高");
                await saveTask;
                Assert.False(delayedInput.TryClear(firstDraft.Revision));
                Assert.Equal(nextDraft.Text, delayedInput.Current.Text);
            }

                var check = await store.QuickCheckAsync();
                Assert.Equal("ok", check);

                var exportRows = await store.LoadAllForExportAsync(session.Id);
                await new ExcelExportService().ExportAsync(session, exportRows, exportPath);
                Assert.True(File.Exists(exportPath));
                AssertVideoWorkbook(exportPath, session, exportRows.Count);
            }

            // 模拟应用重启：关闭第一条连接后重新打开同一隔离库。
            await using (var reopened = new NativeStore(databasePath))
            {
                await reopened.InitializeAsync();
                var session = (await reopened.ListSessionsAsync()).Single();
                Assert.Equal("第2场点名", session.Name);
                Assert.Equal("2026-09-25", session.Date);
                Assert.Equal("active", session.Status);

                var rows = await reopened.LoadAllForExportAsync(session.Id);
                Assert.Equal(Cases.Length + 1, rows.Count);
                Assert.Equal(
                    Enumerable.Range(1, Cases.Length + 1).Reverse(),
                    rows.Select(static row => row.SequenceNo));
                Assert.Equal("森海克斯 8600", rows.Single(row => row.Callsign == "BD4WYE").Device);
                Assert.Equal("isvcxs", rows.Single(row => row.Callsign == "BA4VNN").Unmatched);
                Assert.Equal("ok", await reopened.QuickCheckAsync());
            }
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            if (Environment.GetEnvironmentVariable("HAM_VIDEO_E2E_KEEP") != "1"
                && Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
            else if (Directory.Exists(root))
            {
                Console.WriteLine($"HAM_VIDEO_E2E_ROOT={root}");
            }
        }

    }

    [Fact]
    public void VideoDeviceAndAntennaAliasesDoNotRegress()
    {
        var parser = new InputParser(CatalogLoader.CreateBuiltIn());

        var result = parser.Parse("ba4szj mtm8268 5w 车载苗子");
        Assert.Equal("摩托罗拉 M8268", result.Device.Value);
        Assert.Equal("车载苗子", result.Antenna.Value);
        Assert.Empty(result.Unmatched);

        result = parser.Parse("ba4vuu njjy ct1300 高 yz");
        Assert.Equal("摩托罗拉 CT1300", result.Device.Value);
        Assert.Equal("原装天线", result.Antenna.Value);

        result = parser.Parse("bd4wye shks8600 4单元八木 秦淮区大光路 5w");
        Assert.Equal("森海克斯 8600", result.Device.Value);
        Assert.Equal("江苏省南京市秦淮区大光路", result.Qth.Value);
        Assert.Equal("4单元八木", result.Antenna.Value);
    }

    private sealed record VideoCase(
        string VideoTime,
        string RawInput,
        string Callsign,
        string Qth,
        string Device,
        string Antenna,
        string Power,
        string Signal,
        string Unmatched);

    private static void AssertVideoWorkbook(string path, SessionInfo session, int expectedRowCount)
    {
        using (var document = SpreadsheetDocument.Open(path, false))
        {
            var errors = new OpenXmlValidator()
                .Validate(document)
                .ToArray();
            Assert.Empty(errors);
            Assert.Single(document.WorkbookPart!.Workbook.Sheets!.Elements<Sheet>());
            var sheet = document.WorkbookPart.WorksheetParts.Single().Worksheet;
            Assert.Equal("A5", sheet.SheetViews!.Elements<SheetView>().Single()
                .Elements<Pane>().Single().TopLeftCell?.Value);
            Assert.Equal(expectedRowCount + 4,
                sheet.Elements<SheetData>().Single().Elements<Row>().Count());
        }

        using var archive = ZipFile.OpenRead(path);
        var sheetEntry = archive.GetEntry("xl/worksheets/sheet1.xml");
        Assert.NotNull(sheetEntry);
        using var reader = new StreamReader(sheetEntry!.Open(), Encoding.UTF8);
        var xml = reader.ReadToEnd();
        Assert.Contains(session.Name, xml);
        Assert.Contains(session.Date, xml);
        Assert.Contains("主控：", xml);
        Assert.DoesNotContain("未识别", xml);
        foreach (var header in ExcelExportService.Headers)
        {
            Assert.Contains(header, xml);
        }
    }
}
