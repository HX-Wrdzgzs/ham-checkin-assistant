using System.IO.Compression;
using System.Reflection;
using System.Text;

namespace HamCheckin.Native.Core.Catalogs;

/// <summary>
/// 内置的全国省、市、区县行政区快照。
/// 详细道路/地标仍由地点包提供；这个快照只保证软件刚启动、地点库仍在后台
/// 加载时，常用行政区中文名和拼音首字母也能立即解析。
/// </summary>
internal static class NationwideAdminCatalog
{
    private const string ResourceName =
        "HamCheckin.Native.Core.Catalogs.nationwide-admin.tsv.gz.b64";

    private static readonly Lazy<IReadOnlyList<Entry>> Cached = new(Load);

    public static IReadOnlyList<Entry> Entries => Cached.Value;

    public static IEnumerable<string> GetAliases(Entry entry)
    {
        foreach (var alias in entry.Aliases.Split('|', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            yield return alias;
            var normalized = alias.Trim().ToLowerInvariant();
            if (normalized.Length is < 2 or > 8
                || !normalized.All(static character => character is >= 'a' and <= 'z'))
            {
                continue;
            }

            // The source snapshot stores many city/district codes as hz/wh/cs.
            // Prefixing the province code makes them deterministic across China:
            // zjhz, sdwh, hncs, and so on. A few provinces have two common
            // abbreviations in radio logs. Generate only the combined form;
            // never add a bare alternate province code, because short values
            // such as bj/gz/hn can legitimately refer to more than one place.
            foreach (var provinceCode in ProvinceCodes(entry.Province))
            {
                if (provinceCode.Length > 0
                    && !normalized.StartsWith(provinceCode, StringComparison.Ordinal))
                {
                    yield return provinceCode + normalized;
                }
            }
        }
    }

    private static string[] ProvinceCodes(string province) => province switch
    {
        "内蒙古自治区" => new[] { "nmg", "nm" },
        "黑龙江省" => new[] { "hlj", "hl" },
        "河南省" => new[] { "ha", "hn" },
        "海南省" => new[] { "hi", "hn" },
        "陕西省" => new[] { "sn", "sx" },
        _ => new[]
        {
            province switch
            {
                "北京市" => "bj",
                "天津市" => "tj",
                "河北省" => "he",
                "山西省" => "sx",
                "辽宁省" => "ln",
                "吉林省" => "jl",
                "上海市" => "sh",
                "江苏省" => "js",
                "浙江省" => "zj",
                "安徽省" => "ah",
                "福建省" => "fj",
                "江西省" => "jx",
                "山东省" => "sd",
                "湖北省" => "hb",
                "湖南省" => "hn",
                "广东省" => "gd",
                "广西壮族自治区" => "gx",
                "重庆市" => "cq",
                "四川省" => "sc",
                "贵州省" => "gz",
                "云南省" => "yn",
                "西藏自治区" => "xz",
                "甘肃省" => "gs",
                "青海省" => "qh",
                "宁夏回族自治区" => "nx",
                "新疆维吾尔自治区" => "xj",
                "台湾省" => "tw",
                "香港特别行政区" => "hk",
                "澳门特别行政区" => "mo",
                _ => string.Empty
            }
        }
    };

    private static IReadOnlyList<Entry> Load()
    {
        var assembly = typeof(NationwideAdminCatalog).GetTypeInfo().Assembly;
        using var resource = assembly.GetManifestResourceStream(ResourceName);
        if (resource is null)
        {
            return Array.Empty<Entry>();
        }

        using var encodedReader = new StreamReader(resource, Encoding.UTF8);
        var encoded = encodedReader.ReadToEnd();
        var compressed = Convert.FromBase64String(encoded);
        using var compressedStream = new MemoryStream(compressed, writable: false);
        using var gzip = new GZipStream(compressedStream, CompressionMode.Decompress);
        using var reader = new StreamReader(gzip, Encoding.UTF8);
        var entries = new List<Entry>();
        while (reader.ReadLine() is { } line)
        {
            if (line.Length == 0)
            {
                continue;
            }

            var fields = line.Split('\t');
            if (fields.Length < 7 || fields[5].Length == 0)
            {
                continue;
            }

            entries.Add(new Entry(
                fields[0],
                fields[1],
                fields[2],
                fields[3],
                fields[4],
                fields[5],
                fields[6]));
        }

        return entries;
    }

    internal readonly record struct Entry(
        string Name,
        string Aliases,
        string Province,
        string City,
        string District,
        string Canonical,
        string Kind);
}
