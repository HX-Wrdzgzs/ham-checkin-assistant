using HamCheckin.Native.Core.Catalogs;

namespace HamCheckin.Native.Core.Parsing;

/// <summary>
/// 单元格编辑器使用的字段限定解析器。它和快速录入共享同一份本地目录，
/// 但一次只返回一个字段，绝不把 QTH 编辑文本重新解释为设备或天线。
/// </summary>
public sealed class FieldParser
{
    private readonly Func<CatalogSnapshot> _catalogAccessor;

    public FieldParser(CatalogService service)
    {
        ArgumentNullException.ThrowIfNull(service);
        _catalogAccessor = () => service.Current;
    }

    public FieldParser(CatalogSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        _catalogAccessor = () => snapshot;
    }

    public FieldParseResult Parse(FieldKind field, string? rawText)
    {
        var raw = rawText?.Trim() ?? string.Empty;
        var catalog = _catalogAccessor();
        if (raw.Length == 0)
        {
            return new(field, raw, string.Empty, Array.Empty<string>(), "空值", 1.0,
                Array.Empty<string>(), false);
        }

        return field switch
        {
            FieldKind.Callsign => ParseCallsign(raw),
            FieldKind.Qth => ParseQth(catalog, raw),
            FieldKind.Device => ParseDevice(catalog, raw),
            FieldKind.Antenna => ParseAntenna(catalog, raw),
            FieldKind.Power => ParsePower(catalog, raw),
            FieldKind.Signal => ParseSignal(raw),
            FieldKind.Time => ParseTime(raw),
            _ => new(field, raw, raw, Array.Empty<string>(), "人工输入", 0.5,
                Array.Empty<string>(), false)
        };
    }

    private static FieldParseResult ParseCallsign(string raw) =>
        TextNormalizer.IsCallsign(raw)
            ? new(FieldKind.Callsign, raw, TextNormalizer.NormalizeCallsign(raw),
                Array.Empty<string>(), "呼号规范化", 1.0, new[] { raw })
            : new(FieldKind.Callsign, raw, raw.ToUpperInvariant(), Array.Empty<string>(),
                "人工输入（格式待确认）", 0.5, Array.Empty<string>(), true);

    private static FieldParseResult ParseQth(CatalogSnapshot catalog, string raw)
    {
        var resolved = catalog.ResolveQthInput(raw);
        if (resolved is not null)
        {
            var source = resolved.Kind switch
            {
                "place_suffix" => "行政区 + 地点库",
                "place" => "地点库",
                _ => "全国行政区库"
            };
            return new(FieldKind.Qth, raw, resolved.Canonical, Array.Empty<string>(),
                source,
                resolved.Priority >= 1000 ? 1.0 : 0.9, new[] { raw });
        }

        var candidates = catalog.ResolveQthCandidates(raw)
            .Select(static item => item.Canonical)
            .Distinct(StringComparer.Ordinal)
            .Take(8)
            .ToArray();
        return new(FieldKind.Qth, raw, candidates.Length == 1 ? candidates[0] : raw,
            candidates, candidates.Length == 1 ? "地点候选" : "人工输入（待确认）",
            candidates.Length == 1 ? 0.9 : 0.45, candidates.Length == 1 ? new[] { raw } : Array.Empty<string>(),
            candidates.Length > 1);
    }

    private static FieldParseResult ParseDevice(CatalogSnapshot catalog, string raw)
    {
        var resolved = catalog.ResolveDevice(raw);
        if (resolved is not null)
        {
            return new(FieldKind.Device, raw, resolved.StandardName, Array.Empty<string>(),
                resolved.Source, resolved.Confidence, new[] { raw });
        }

        var candidates = catalog.SearchDevices(raw, 8)
            .Select(static item => item.StandardName)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return new(FieldKind.Device, raw, candidates.Length == 1 ? candidates[0] : raw,
            candidates, candidates.Length == 1 ? "本地候选" : "人工输入（未收录）",
            candidates.Length == 1 ? 0.75 : 0.45,
            candidates.Length == 1 ? new[] { raw } : Array.Empty<string>(), candidates.Length > 1);
    }

    private static FieldParseResult ParseAntenna(CatalogSnapshot catalog, string raw)
    {
        var resolved = catalog.ResolveAntenna(raw);
        return resolved is null
            ? new(FieldKind.Antenna, raw, raw, Array.Empty<string>(), "人工输入", 0.5, Array.Empty<string>())
            : new(FieldKind.Antenna, raw, resolved, Array.Empty<string>(), "天线别名", 1.0, new[] { raw });
    }

    private static FieldParseResult ParsePower(CatalogSnapshot catalog, string raw)
    {
        var resolved = catalog.ResolvePower(raw);
        return resolved is null
            ? new(FieldKind.Power, raw, raw, Array.Empty<string>(), "人工输入", 0.5, Array.Empty<string>())
            : new(FieldKind.Power, raw, resolved, Array.Empty<string>(), "功率规范化", 1.0, new[] { raw });
    }

    private static FieldParseResult ParseSignal(string raw) =>
        TextNormalizer.IsSignal(raw)
            ? new(FieldKind.Signal, raw, raw, Array.Empty<string>(), "信号规范化", 1.0, new[] { raw })
            : new(FieldKind.Signal, raw, raw, Array.Empty<string>(), "人工输入", 0.5, Array.Empty<string>());

    private static FieldParseResult ParseTime(string raw) =>
        TimeOnly.TryParse(raw, out var time)
            ? new(FieldKind.Time, raw, time.ToString("HH:mm:ss"), Array.Empty<string>(), "时间规范化", 1.0, new[] { raw })
            : new(FieldKind.Time, raw, raw, Array.Empty<string>(), "人工输入", 0.5, Array.Empty<string>(), true);
}
