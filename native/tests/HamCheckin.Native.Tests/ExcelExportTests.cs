using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using DocumentFormat.OpenXml.Validation;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Export;

namespace HamCheckin.Native.Tests;

public sealed class ExcelExportTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"ham-native-export-{Guid.NewGuid():N}");

    [Fact]
    public async Task NewWorkbookHasSessionMetadataAndNineColumnsOnly()
    {
        Directory.CreateDirectory(_root);
        var path = Path.Combine(_root, "第5场点名_2026-09-04.xlsx");
        var session = new SessionInfo(5, "第5场点名", "2026-09-04", "active", 2,
            "BA4THG", "江苏省中继");
        var rows = new[]
        {
            new CheckinEntry(1, 5, 1, "21:01", "BA4VTI", "江苏省镇江市句容市",
                "威诺 VR-N76", "SRH-771", "5W", "", "local",
                "BA4VTI NJJR VRN76 5W", "仍待确认")
        };

        var result = await new ExcelExportService().ExportAsync(
            session, rows, new ExcelExportTarget(_root, Path.GetFileName(path), false));

        Assert.Equal(1, result.RowCount);
        Assert.Equal(9, ExcelExportService.Headers.Length);
        using (var spreadsheetDocument = SpreadsheetDocument.Open(path, false))
        {
            var errors = new OpenXmlValidator(FileFormatVersions.Office2019)
                .Validate(spreadsheetDocument)
                .ToArray();
            Assert.Empty(errors);
            Assert.Single(spreadsheetDocument.WorkbookPart!.Workbook.Sheets!.Elements<Sheet>());
        }
        using var archive = ZipFile.OpenRead(path);
        var sheet = archive.GetEntry("xl/worksheets/sheet1.xml");
        Assert.NotNull(sheet);
        using var reader = new StreamReader(sheet!.Open(), Encoding.UTF8);
        var xml = await reader.ReadToEndAsync();
        Assert.Contains("第5场点名", xml);
        Assert.Contains("2026-09-04", xml);
        Assert.Contains("主控：BA4THG", xml);
        Assert.Contains("江苏省中继", xml);
        Assert.DoesNotContain("未识别", xml);
        foreach (var header in ExcelExportService.Headers)
        {
            Assert.Contains(header, xml);
        }

        var core = archive.GetEntry("docProps/core.xml");
        Assert.NotNull(core);
        using var coreReader = new StreamReader(core!.Open(), Encoding.UTF8);
        var coreXml = await coreReader.ReadToEndAsync();
        Assert.Contains("<dc:subject>第5场点名</dc:subject>", coreXml);
        Assert.DoesNotContain("<cp:subject>", coreXml);

        var sheetDocument = XDocument.Parse(xml);
        var childNames = sheetDocument.Root!.Elements().Select(element => element.Name.LocalName).ToArray();
        Assert.True(Array.IndexOf(childNames, "cols") < Array.IndexOf(childNames, "sheetData"));
        Assert.Contains("dimension", childNames);
        Assert.Contains("sheetFormatPr", childNames);
    }

    [Fact]
    public async Task FormulaLikeUserContentRemainsInlineText()
    {
        Directory.CreateDirectory(_root);
        var path = Path.Combine(_root, "formula-safe.xlsx");
        const string formulaLikeQth = "=HYPERLINK(\"https://example.invalid\",\"not-a-formula\")";
        var session = new SessionInfo(1, "第1场点名", "2026-10-05", "active", 2,
            "BA4THG", "江苏省中继");
        var rows = new[]
        {
            new CheckinEntry(1, 1, 1, "21:01", "BA4AAA", formulaLikeQth,
                "海能达 PD-780", "原装天线", "5W", "", "local",
                formulaLikeQth, "")
        };

        await new ExcelExportService().ExportAsync(
            session, rows, new ExcelExportTarget(_root, Path.GetFileName(path), false));

        using var document = SpreadsheetDocument.Open(path, false);
        var cell = document.WorkbookPart!.WorksheetParts.Single().Worksheet
            .Descendants<Cell>()
            .Single(item => item.CellReference?.Value == "D5");
        Assert.Equal(CellValues.InlineString, cell.DataType?.Value);
        Assert.Equal(formulaLikeQth, cell.InlineString?.Text?.Text);
    }

    [Fact]
    public void DefaultFileNameSanitizesWindowsNamesAndFallsBackForEmptyData()
    {
        var session = new SessionInfo(17, "bad/name: title", "2026/11/14", "active", 1);
        Assert.Equal("bad_name_ title_2026_11_14.xlsx", ExcelExportService.CreateDefaultFileName(session));
        Assert.Equal("trailing.xlsx", ExcelExportService.CreateDefaultFileName(
            session with { Name = "trailing. ", Date = string.Empty }));
        Assert.Equal("_CON.xlsx", ExcelExportService.CreateDefaultFileName(
            session with { Name = "CON", Date = string.Empty }));
        Assert.Equal("session-17.xlsx", ExcelExportService.CreateDefaultFileName(
            session with { Name = "  ", Date = string.Empty }));
    }

    [Theory]
    [InlineData("../escape.xlsx")]
    [InlineData("sub/escape.xlsx")]
    [InlineData("sub\\escape.xlsx")]
    [InlineData(@"C:\escape.xlsx")]
    [InlineData("CON.xlsx")]
    public async Task ExportRejectsNonLeafAndReservedFileNames(string fileName)
    {
        Directory.CreateDirectory(_root);
        var selectedDirectory = Path.Combine(_root, "selected");
        Directory.CreateDirectory(selectedDirectory);
        var escapePath = Path.Combine(_root, "escape.xlsx");
        var escapeBytes = File.Exists(escapePath) ? await File.ReadAllBytesAsync(escapePath) : null;
        var session = new SessionInfo(1, "第1场点名", "2026-11-14", "active", 1);
        var target = new ExcelExportTarget(selectedDirectory, fileName, false);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            new ExcelExportService().ExportAsync(session, Array.Empty<CheckinEntry>(), target));
        Assert.Empty(Directory.EnumerateFiles(selectedDirectory));
        if (escapeBytes is null)
        {
            Assert.False(File.Exists(escapePath));
        }
        else
        {
            Assert.Equal(escapeBytes, await File.ReadAllBytesAsync(escapePath));
        }
    }

    [Fact]
    public async Task UnconfirmedExistingTargetPreservesOriginalBytes()
    {
        Directory.CreateDirectory(_root);
        var fileName = "existing.xlsx";
        var path = Path.Combine(_root, fileName);
        var original = Encoding.UTF8.GetBytes("original workbook bytes");
        await File.WriteAllBytesAsync(path, original);
        var originalHash = Sha256(original);
        var session = new SessionInfo(1, "第1场点名", "2026-11-14", "active", 1);

        await Assert.ThrowsAsync<IOException>(() => new ExcelExportService().ExportAsync(
            session, Array.Empty<CheckinEntry>(), new ExcelExportTarget(_root, fileName, false)));

        Assert.Equal(originalHash, Sha256(await File.ReadAllBytesAsync(path)));
        Assert.Empty(Directory.EnumerateFiles(_root, ".ham-export-*.tmp"));
    }

    [Fact]
    public async Task ConfirmedPathAllowsReplacingItsCurrentObjectAfterExternalChange()
    {
        Directory.CreateDirectory(_root);
        var fileName = "confirmed.xlsx";
        var path = Path.Combine(_root, fileName);
        await File.WriteAllBytesAsync(path, Encoding.UTF8.GetBytes("selected before confirmation"));
        var session = new SessionInfo(9, "捕获的场次", "2026-11-14", "active", 2, "BA4THG", "江苏中继");
        var rows = new[]
        {
            new CheckinEntry(1, session.Id, 1, "21:01", "BA4AAA", "南京", "R6", "天线", "5W", "",
                "local", "BA4AAA 南京 R6 5W", "")
        };
        var externalReplacement = Encoding.UTF8.GetBytes("another program replaced the selected path");
        // Path authorization intentionally applies to the object present at commit, not the earlier bytes.
        File.Delete(path);
        await File.WriteAllBytesAsync(path, externalReplacement);

        var result = await new ExcelExportService().ExportAsync(
            session, rows, new ExcelExportTarget(_root, fileName, true));

        Assert.Equal(path, result.Path);
        Assert.Equal(1, result.RowCount);
        Assert.NotEqual(Sha256(externalReplacement), Sha256(await File.ReadAllBytesAsync(path)));
        using var document = SpreadsheetDocument.Open(path, false);
        var sheet = document.WorkbookPart!.WorksheetParts.Single().Worksheet;
        Assert.Equal(5, sheet.Descendants<Row>().Count());
        using var archive = ZipFile.OpenRead(path);
        using var reader = new StreamReader(archive.GetEntry("docProps/core.xml")!.Open(), Encoding.UTF8);
        Assert.Contains("<dc:subject>捕获的场次</dc:subject>", await reader.ReadToEndAsync());
    }

    [Fact]
    public async Task LockedTargetAndMissingDirectoryFailWithoutChangingFiles()
    {
        Directory.CreateDirectory(_root);
        var fileName = "locked.xlsx";
        var path = Path.Combine(_root, fileName);
        var original = Encoding.UTF8.GetBytes("locked target bytes");
        await File.WriteAllBytesAsync(path, original);
        var originalHash = Sha256(original);
        var session = new SessionInfo(1, "第1场点名", "2026-11-14", "active", 1);
        using (new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        {
            await Assert.ThrowsAsync<IOException>(() => new ExcelExportService().ExportAsync(
                session, Array.Empty<CheckinEntry>(), new ExcelExportTarget(_root, fileName, true)));
        }
        Assert.Equal(originalHash, Sha256(await File.ReadAllBytesAsync(path)));
        Assert.Empty(Directory.EnumerateFiles(_root, ".ham-export-*.tmp"));

        var missingDirectory = Path.Combine(_root, "not-created");
        await Assert.ThrowsAsync<DirectoryNotFoundException>(() => new ExcelExportService().ExportAsync(
            session, Array.Empty<CheckinEntry>(), new ExcelExportTarget(missingDirectory, "new.xlsx", false)));
        Assert.False(Directory.Exists(missingDirectory));
    }

    [Fact]
    public async Task ConcurrentCreationOfAbsentTargetNeverOverwritesCompetitor()
    {
        Directory.CreateDirectory(_root);
        var session = new SessionInfo(3, "Race", "2026-11-14", "active", 1);
        var targetPath = Path.Combine(_root, "raced.xlsx");
        var competitor = Encoding.UTF8.GetBytes("created by another process");
        var competitorHash = Sha256(competitor);
        var created = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var watcher = new FileSystemWatcher(_root, ".ham-export-*.tmp")
        {
            NotifyFilter = NotifyFilters.FileName,
            EnableRaisingEvents = true
        };
        watcher.Created += (_, args) => created.TrySetResult(args.FullPath);
        var exportTask = new ExcelExportService().ExportAsync(
            session, CreateRows(session.Id, 25_000), new ExcelExportTarget(_root, "raced.xlsx", false));

        await created.Task.WaitAsync(TimeSpan.FromSeconds(30));
        await File.WriteAllBytesAsync(targetPath, competitor);
        await Assert.ThrowsAsync<IOException>(() => exportTask);

        Assert.Equal(competitorHash, Sha256(await File.ReadAllBytesAsync(targetPath)));
        Assert.Empty(Directory.EnumerateFiles(_root, ".ham-export-*.tmp"));
    }

    [Fact]
    public async Task CancellationBeforeCommitPreservesExistingTarget()
    {
        Directory.CreateDirectory(_root);
        var session = new SessionInfo(4, "Cancel", "2026-11-14", "active", 1);
        var fileName = "cancelled.xlsx";
        var targetPath = Path.Combine(_root, fileName);
        var original = Encoding.UTF8.GetBytes("original before cancellation");
        await File.WriteAllBytesAsync(targetPath, original);
        var originalHash = Sha256(original);
        var created = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var watcher = new FileSystemWatcher(_root, ".ham-export-*.tmp")
        {
            NotifyFilter = NotifyFilters.FileName,
            EnableRaisingEvents = true
        };
        watcher.Created += (_, args) => created.TrySetResult(args.FullPath);
        using var cancellation = new CancellationTokenSource();
        var exportTask = new ExcelExportService().ExportAsync(
            session, CreateRows(session.Id, 25_000),
            new ExcelExportTarget(_root, fileName, true), cancellation.Token);

        await created.Task.WaitAsync(TimeSpan.FromSeconds(30));
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => exportTask);

        Assert.Equal(originalHash, Sha256(await File.ReadAllBytesAsync(targetPath)));
        Assert.Empty(Directory.EnumerateFiles(_root, ".ham-export-*.tmp"));
    }

    private static string Sha256(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));

    private static CheckinEntry[] CreateRows(long sessionId, int count) =>
        Enumerable.Range(1, count)
            .Select(sequence => new CheckinEntry(
                sequence, sessionId, sequence, "21:01", $"BA4A{sequence:D5}", "南京", "R6", "天线", "5W", "",
                "local", "合成点名记录", ""))
            .ToArray();

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
    }
}
