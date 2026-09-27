using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using DocumentFormat.OpenXml.Validation;
using System.Text;
using System.Xml;

namespace HamCheckin.Native.Core.Export;

public sealed record ExcelExportResult(string Path, int RowCount, string SheetName);

/// <summary>
/// 使用 Open XML SDK 生成标准 .xlsx。Excel 不在现场录入热路径中，
/// 未识别内容只保存在 SQLite 和编辑审计中。
/// </summary>
public sealed class ExcelExportService
{
    public static readonly string[] Headers =
    {
        "序号", "时间", "呼号", "QTH", "设备", "天线", "功率", "信号", "来源"
    };

    public async Task<ExcelExportResult> ExportAsync(
        SessionInfo session,
        IReadOnlyList<CheckinEntry> rows,
        string outputPath,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(outputPath))
        {
            throw new ArgumentException("导出路径不能为空。", nameof(outputPath));
        }

        var fullPath = Path.GetFullPath(outputPath);
        var directory = Path.GetDirectoryName(fullPath)
            ?? throw new InvalidOperationException("无法确定导出目录。");
        Directory.CreateDirectory(directory);
        var sheetName = SafeSheetName(session.Name);
        var temporaryPath = Path.Combine(
            directory,
            "." + Path.GetFileName(fullPath) + ".tmp-" + Guid.NewGuid().ToString("N"));

        try
        {
            await Task.Run(
                () => WriteAndValidateWorkbook(
                    temporaryPath, session, rows, sheetName, cancellationToken),
                cancellationToken).ConfigureAwait(false);

            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                File.Move(temporaryPath, fullPath, true);
            }
            catch (IOException exception)
            {
                throw new IOException(
                    $"无法替换 Excel 文件“{fullPath}”。如果同名文件正在 Excel 中打开，请先关闭它后重试。",
                    exception);
            }

            return new ExcelExportResult(fullPath, rows.Count, sheetName);
        }
        finally
        {
            TryDelete(temporaryPath);
        }
    }

    private static void WriteAndValidateWorkbook(
        string path,
        SessionInfo session,
        IReadOnlyList<CheckinEntry> rows,
        string sheetName,
        CancellationToken cancellationToken)
    {
        using (var document = SpreadsheetDocument.Create(
                   path, SpreadsheetDocumentType.Workbook, true))
        {
            var workbookPart = document.AddWorkbookPart();
            workbookPart.Workbook = new Workbook();

            var stylesPart = workbookPart.AddNewPart<WorkbookStylesPart>();
            stylesPart.Stylesheet = CreateStylesheet();
            stylesPart.Stylesheet.Save();

            var worksheetPart = workbookPart.AddNewPart<WorksheetPart>();
            worksheetPart.Worksheet = CreateWorksheet(session, rows, cancellationToken);
            worksheetPart.Worksheet.Save();

            var sheets = workbookPart.Workbook.AppendChild(new Sheets());
            sheets.Append(new Sheet
            {
                Name = sheetName,
                SheetId = 1U,
                Id = workbookPart.GetIdOfPart(worksheetPart)
            });

            document.PackageProperties.Creator = "HX-Wrdzgzs";
            document.PackageProperties.Title = "HAM 点名助手";
            document.PackageProperties.Subject = session.Name;
            document.PackageProperties.Description =
                $"{session.RepeaterName} · {session.Name} · {session.Date}";
            WriteCoreProperties(document, session);
            workbookPart.Workbook.Save();
        }

        ValidateWorkbook(path, session, rows.Count, sheetName);
    }

    private static Worksheet CreateWorksheet(
        SessionInfo session,
        IReadOnlyList<CheckinEntry> rows,
        CancellationToken cancellationToken)
    {
        var worksheet = new Worksheet();
        worksheet.Append(new SheetDimension
        {
            Reference = $"A1:I{Math.Max(rows.Count + 4, 4)}"
        });

        var sheetViews = new SheetViews();
        var sheetView = new SheetView { WorkbookViewId = 0U };
        sheetView.Append(new Pane
        {
            VerticalSplit = 4D,
            TopLeftCell = "A5",
            ActivePane = PaneValues.BottomLeft,
            State = PaneStateValues.Frozen
        });
        sheetViews.Append(sheetView);
        worksheet.Append(sheetViews);

        worksheet.Append(new SheetFormatProperties
        {
            DefaultRowHeight = 18D,
            BaseColumnWidth = 10U
        });

        var columns = new Columns();
        var widths = new[] { 8D, 12D, 14D, 32D, 28D, 20D, 10D, 10D, 12D };
        for (var index = 0; index < widths.Length; index++)
        {
            columns.Append(new Column
            {
                Min = (uint)(index + 1),
                Max = (uint)(index + 1),
                Width = widths[index],
                CustomWidth = true
            });
        }
        worksheet.Append(columns);

        var sheetData = new SheetData();
        sheetData.Append(CreateRow(
            1,
            new[] { $"{session.RepeaterName} · {session.Name} · {session.Date}" },
            2U));
        sheetData.Append(CreateRow(
            2,
            new[]
            {
                $"主控：{session.OperatorCallsign}" +
                (string.IsNullOrWhiteSpace(session.RepeaterName)
                    ? string.Empty
                    : $"    中继：{session.RepeaterName}")
            },
            2U));
        sheetData.Append(new Row { RowIndex = 3U });
        sheetData.Append(CreateRow(4, Headers, 1U));

        var rowNumber = 5U;
        foreach (var row in rows.OrderBy(item => item.SequenceNo))
        {
            cancellationToken.ThrowIfCancellationRequested();
            sheetData.Append(CreateRow(
                rowNumber++,
                new[]
                {
                    row.SequenceNo.ToString(),
                    row.CheckinTime,
                    row.Callsign,
                    row.Qth,
                    row.Device,
                    row.Antenna,
                    row.Power,
                    row.Signal,
                    row.Source
                },
                0U));
        }
        worksheet.Append(sheetData);

        var mergeCells = new MergeCells { Count = 2U };
        mergeCells.Append(new MergeCell { Reference = "A1:I1" });
        mergeCells.Append(new MergeCell { Reference = "A2:I2" });
        worksheet.Append(mergeCells);
        return worksheet;
    }

    private static Row CreateRow(
        uint rowNumber,
        IReadOnlyList<string> values,
        uint styleIndex)
    {
        var row = new Row { RowIndex = rowNumber };
        for (var index = 0; index < values.Count; index++)
        {
            var text = values[index] ?? string.Empty;
            row.Append(new Cell
            {
                CellReference = CellReference(index, rowNumber),
                DataType = CellValues.InlineString,
                StyleIndex = styleIndex,
                InlineString = new InlineString(new Text(text))
            });
        }
        return row;
    }

    private static Stylesheet CreateStylesheet()
    {
        var fonts = new Fonts { Count = 2U };
        fonts.Append(new Font());
        fonts.Append(new Font(new Bold()));

        var fills = new Fills { Count = 3U };
        fills.Append(new Fill(new PatternFill { PatternType = PatternValues.None }));
        fills.Append(new Fill(new PatternFill { PatternType = PatternValues.Gray125 }));
        fills.Append(new Fill(new PatternFill
        {
            PatternType = PatternValues.Solid,
            ForegroundColor = new ForegroundColor { Rgb = "FFD9EAF7" }
        }));

        var borders = new Borders { Count = 1U };
        borders.Append(new Border());

        var cellStyleFormats = new CellStyleFormats { Count = 1U };
        cellStyleFormats.Append(new CellFormat
        {
            NumberFormatId = 0U,
            FontId = 0U,
            FillId = 0U,
            BorderId = 0U
        });

        var cellFormats = new CellFormats { Count = 3U };
        cellFormats.Append(new CellFormat
        {
            NumberFormatId = 0U,
            FontId = 0U,
            FillId = 0U,
            BorderId = 0U,
            FormatId = 0U
        });
        cellFormats.Append(new CellFormat
        {
            NumberFormatId = 0U,
            FontId = 1U,
            FillId = 2U,
            BorderId = 0U,
            FormatId = 0U,
            ApplyFont = true,
            ApplyFill = true,
            Alignment = new Alignment { Horizontal = HorizontalAlignmentValues.Center }
        });
        cellFormats.Append(new CellFormat
        {
            NumberFormatId = 0U,
            FontId = 1U,
            FillId = 0U,
            BorderId = 0U,
            FormatId = 0U,
            ApplyFont = true
        });

        var cellStyles = new CellStyles { Count = 1U };
        cellStyles.Append(new CellStyle
        {
            Name = "Normal",
            FormatId = 0U,
            BuiltinId = 0U
        });

        var tableStyles = new TableStyles
        {
            Count = 0U,
            DefaultTableStyle = "TableStyleMedium2",
            DefaultPivotStyle = "PivotStyleLight16"
        };

        return new Stylesheet(
            fonts,
            fills,
            borders,
            cellStyleFormats,
            cellFormats,
            cellStyles,
            tableStyles);
    }

    private static void ValidateWorkbook(
        string path,
        SessionInfo session,
        int expectedRowCount,
        string expectedSheetName)
    {
        using var document = SpreadsheetDocument.Open(path, false);
        var errors = new OpenXmlValidator(FileFormatVersions.Office2019)
            .Validate(document)
            .ToArray();
        if (errors.Length > 0)
        {
            var message = string.Join(
                Environment.NewLine,
                errors.Take(10).Select(error => error.Description));
            throw new InvalidDataException($"导出的 Excel 未通过 Open XML 校验：{message}");
        }

        var workbook = document.WorkbookPart?.Workbook
            ?? throw new InvalidDataException("导出的 Excel 缺少工作簿。");
        var sheets = workbook.Sheets?.Elements<Sheet>().ToArray()
            ?? Array.Empty<Sheet>();
        if (sheets.Length != 1 || sheets[0].Name?.Value != expectedSheetName)
        {
            throw new InvalidDataException("导出的 Excel 工作表数量或名称不正确。");
        }

        var sheetId = sheets[0].Id?.Value
            ?? throw new InvalidDataException("导出的 Excel 工作表缺少关系 ID。");
        var worksheetPart = (WorksheetPart?)document.WorkbookPart!
            .GetPartById(sheetId);
        var sheetData = worksheetPart?.Worksheet.GetFirstChild<SheetData>()
            ?? throw new InvalidDataException("导出的 Excel 缺少数据区域。");
        var header = sheetData.Elements<Row>()
            .SingleOrDefault(row => row.RowIndex?.Value == 4U)
            ?? throw new InvalidDataException("导出的 Excel 缺少九列表头。");
        var actualHeaders = header.Elements<Cell>()
            .Select(ReadCellText)
            .ToArray();
        if (!Headers.SequenceEqual(actualHeaders, StringComparer.Ordinal))
        {
            throw new InvalidDataException("导出的 Excel 九列表头不正确。");
        }

        var recordRows = sheetData.Elements<Row>()
            .Count(row => row.RowIndex?.Value >= 5U);
        if (recordRows != expectedRowCount)
        {
            throw new InvalidDataException("导出的 Excel 记录数量与 SQLite 不一致。");
        }

        var title = sheetData.Elements<Row>()
            .SingleOrDefault(row => row.RowIndex?.Value == 1U);
        var titleCell = title?.Elements<Cell>().FirstOrDefault();
        if (titleCell is null)
        {
            throw new InvalidDataException("导出的 Excel 缺少标题。");
        }
        var titleText = ReadCellText(titleCell);
        if (!titleText.Contains(session.Name, StringComparison.Ordinal) ||
            !titleText.Contains(session.Date, StringComparison.Ordinal))
        {
            throw new InvalidDataException("导出的 Excel 缺少场次名称或场次日期。");
        }
    }

    private static void WriteCoreProperties(
        SpreadsheetDocument document,
        SessionInfo session)
    {
        var corePart = document.AddCoreFilePropertiesPart();
        using var stream = corePart.GetStream(FileMode.Create, FileAccess.Write);
        using var writer = XmlWriter.Create(stream, new XmlWriterSettings
        {
            Encoding = new UTF8Encoding(false),
            OmitXmlDeclaration = false
        });
        const string coreNamespace =
            "http://schemas.openxmlformats.org/package/2006/metadata/core-properties";
        const string dcNamespace = "http://purl.org/dc/elements/1.1/";
        writer.WriteStartElement("cp", "coreProperties", coreNamespace);
        writer.WriteAttributeString("xmlns", "dc", null, dcNamespace);
        writer.WriteElementString("dc", "creator", dcNamespace, "HX-Wrdzgzs");
        writer.WriteElementString("dc", "title", dcNamespace, "HAM 点名助手");
        writer.WriteElementString("dc", "subject", dcNamespace, session.Name);
        writer.WriteEndElement();
    }

    private static string ReadCellText(Cell cell)
    {
        return cell.InlineString?.Text?.Text
            ?? cell.CellValue?.Text
            ?? string.Empty;
    }

    private static string CellReference(int column, uint row)
    {
        var result = string.Empty;
        var value = column + 1;
        while (value > 0)
        {
            var remainder = (value - 1) % 26;
            result = (char)('A' + remainder) + result;
            value = (value - 1) / 26;
        }
        return result + row;
    }

    private static string SafeSheetName(string name)
    {
        var invalid = new[] { ':', '\\', '/', '?', '*', '[', ']' };
        var value = new string(
            (name ?? "点名").Where(character => !invalid.Contains(character)).ToArray()).Trim();
        return string.IsNullOrWhiteSpace(value)
            ? "点名"
            : value[..Math.Min(31, value.Length)];
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 临时文件清理失败不覆盖导出/校验的原始错误。
        }
    }
}
