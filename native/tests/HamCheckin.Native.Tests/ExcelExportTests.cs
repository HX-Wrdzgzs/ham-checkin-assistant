using System.IO.Compression;
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

        var result = await new ExcelExportService().ExportAsync(session, rows, path);

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

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, true);
        }
    }
}
