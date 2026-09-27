using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.Core.Catalogs;

public sealed class CatalogSnapshot
{
    private readonly IReadOnlyDictionary<string, DeviceCandidate> _deviceAliases;
    private readonly IReadOnlyDictionary<string, DeviceCandidate> _miitModels;
    private readonly IReadOnlyDictionary<string, string> _antennaAliases;
    private readonly IReadOnlyDictionary<string, string> _powerAliases;
    private readonly IReadOnlyDictionary<string, IReadOnlyList<QthCandidate>> _qthAliases;

    internal CatalogSnapshot(
        IReadOnlyDictionary<string, DeviceCandidate> deviceAliases,
        IReadOnlyDictionary<string, DeviceCandidate> miitModels,
        IReadOnlyDictionary<string, string> antennaAliases,
        IReadOnlyDictionary<string, string> powerAliases,
        IReadOnlyDictionary<string, IReadOnlyList<QthCandidate>> qthAliases,
        int qthPlaceCount = 0)
    {
        _deviceAliases = deviceAliases;
        _miitModels = miitModels;
        _antennaAliases = antennaAliases;
        _powerAliases = powerAliases;
        _qthAliases = qthAliases;
        QthPlaceCount = qthPlaceCount;
    }

    public int DeviceAliasCount => _deviceAliases.Count;
    public int MiitModelCount => _miitModels.Count;
    public int QthAliasCount => _qthAliases.Count;
    public int QthPlaceCount { get; }

    public DeviceCandidate? ResolveDevice(string token)
    {
        var key = TextNormalizer.NormalizeKey(token);
        if (key.Length == 0)
        {
            return null;
        }

        if (_deviceAliases.TryGetValue(key, out var local))
        {
            return local;
        }

        if (_miitModels.TryGetValue(key, out var miit))
        {
            return miit;
        }

        // Excel 中经常已经保存了“品牌 + 完整型号”，例如“泉盛 UV-K6”。
        // 这个值不是别名键，但它可能正好等于本地别名或工信部记录的标准名称。
        // 先做标准名称完全匹配，再进入模糊候选，避免完整标准名被误报为未收录。
        return _deviceAliases.Values
            .Concat(_miitModels.Values)
            .Where(item => string.Equals(
                TextNormalizer.NormalizeKey(item.StandardName), key,
                StringComparison.Ordinal))
            .OrderByDescending(static item => DeviceSourcePriority(item.Source))
            .ThenBy(static item => item.StandardName.Length)
            .FirstOrDefault();
    }

    public string? ResolveAntenna(string token)
    {
        var key = TextNormalizer.NormalizeKey(token);
        return _antennaAliases.TryGetValue(key, out var value) ? value : null;
    }

    public string? ResolvePower(string token)
    {
        var key = TextNormalizer.NormalizeKey(token);
        if (_powerAliases.TryGetValue(key, out var value))
        {
            return value;
        }

        return TextNormalizer.IsPowerWithUnit(token)
            ? TextNormalizer.NormalizePower(token)
            : null;
    }

    public IReadOnlyList<QthCandidate> ResolveQthCandidates(string token)
    {
        var key = TextNormalizer.NormalizeKey(token);
        return _qthAliases.TryGetValue(key, out var values)
            ? values
            : Array.Empty<QthCandidate>();
    }

    public QthCandidate? ResolveQth(string token)
    {
        var candidates = ResolveQthCandidates(token);
        if (candidates.Count == 0)
        {
            return null;
        }

        var ranked = candidates
            .OrderByDescending(static item => item.Priority)
            .ThenBy(static item => item.Depth)
            .ThenBy(static item => item.Canonical.Length)
            .ToArray();

        if (ranked.Length == 1)
        {
            return ranked[0];
        }

        var first = ranked[0];
        var second = ranked[1];
        return first.Priority > second.Priority || first.Depth < second.Depth
            ? first
            : string.Equals(first.Canonical, second.Canonical, StringComparison.Ordinal)
                ? first
                : null;
    }

    /// <summary>
    /// 解析“行政区缩写 + 中文道路/地标”的现场写法，例如
    /// njgl中山路169号 -> 江苏省南京市鼓楼区中山路169号。
    /// 只有前缀唯一命中时才会采用，避免把普通中文误猜成地点。
    /// </summary>
    public QthCandidate? ResolveQthInput(string token)
    {
        var direct = ResolveQth(token);
        if (direct is not null)
        {
            return direct;
        }

        var normalized = token?.Trim() ?? string.Empty;
        if (normalized.Length < 3)
        {
            return null;
        }

        var prefix = new string(normalized.TakeWhile(static character =>
            (character >= 'a' && character <= 'z') ||
            (character >= 'A' && character <= 'Z')).ToArray());
        for (var length = prefix.Length; length >= 2 && length < normalized.Length; length--)
        {
            var key = TextNormalizer.NormalizeKey(prefix[..length]);
            if (!_qthAliases.TryGetValue(key, out var candidates) || candidates.Count != 1)
            {
                continue;
            }

            var candidate = candidates[0];
            var suffix = normalized[length..].Trim();
            if (suffix.Length == 0)
            {
                return candidate;
            }

            return candidate with
            {
                Canonical = candidate.Canonical + suffix,
                Kind = "place_suffix",
                Priority = candidate.Priority - 1
            };
        }

        return ResolveChineseQthInput(normalized);
    }

    public IReadOnlyList<DeviceCandidate> SearchDevices(string query, int limit = 8)
    {
        var key = TextNormalizer.NormalizeKey(query);
        if (key.Length == 0)
        {
            return Array.Empty<DeviceCandidate>();
        }

        return _deviceAliases
            .Concat(_miitModels)
            .Where(pair => pair.Key.Contains(key, StringComparison.Ordinal)
                || TextNormalizer.NormalizeKey(pair.Value.StandardName)
                    .Contains(key, StringComparison.Ordinal))
            .OrderByDescending(pair => pair.Key == key)
            .ThenByDescending(pair => TextNormalizer.NormalizeKey(pair.Value.StandardName) == key)
            .ThenByDescending(pair => pair.Key.StartsWith(key, StringComparison.Ordinal))
            .ThenBy(pair => pair.Key.Length)
            .Select(static pair => pair.Value)
            .DistinctBy(static item => item.StandardName, StringComparer.OrdinalIgnoreCase)
            .Take(Math.Max(1, limit))
            .ToArray();
    }

    internal IReadOnlyDictionary<string, DeviceCandidate> DeviceAliases => _deviceAliases;
    internal IReadOnlyDictionary<string, DeviceCandidate> MiitModels => _miitModels;
    internal IReadOnlyDictionary<string, string> AntennaAliases => _antennaAliases;
    internal IReadOnlyDictionary<string, string> PowerAliases => _powerAliases;
    internal IReadOnlyDictionary<string, IReadOnlyList<QthCandidate>> QthAliases => _qthAliases;

    private QthCandidate? ResolveChineseQthInput(string normalized)
    {
        var candidates = _qthAliases.Values
            .SelectMany(static values => values)
            .DistinctBy(static item => item.Canonical, StringComparer.Ordinal)
            .ToArray();

        // 输入已经带完整行政区前缀时，只补齐缺失的分隔符或保留地点后缀。
        foreach (var candidate in candidates
                     .OrderByDescending(static item => TextNormalizer.NormalizeKey(item.Canonical).Length))
        {
            var canonicalKey = TextNormalizer.NormalizeKey(candidate.Canonical);
            if (canonicalKey.Length == 0 || !normalized.StartsWith(canonicalKey, StringComparison.Ordinal)
                || normalized.Length <= canonicalKey.Length)
            {
                continue;
            }

            var suffix = normalized[canonicalKey.Length..];
            return candidate with
            {
                Canonical = candidate.Canonical + suffix,
                Kind = "place_suffix",
                Priority = candidate.Priority - 1
            };
        }

        // 中文现场输入常省略“省、市、区”字样，例如“南京鼓楼”“南京市鼓楼中山路”。
        // 优先要求城市同时出现；同名区县在多个城市存在时不会猜测。
        var administrativeDistrictCandidates = candidates
            .Where(static item => !string.IsNullOrWhiteSpace(item.District)
                && IsAdministrativeRegion(item))
            .ToArray();
        var districtCandidates = administrativeDistrictCandidates.Length > 0
            ? administrativeDistrictCandidates
            : candidates.Where(static item => !string.IsNullOrWhiteSpace(item.District)).ToArray();

        var districtMatches = new List<(QthCandidate Candidate, string Key, int Index, int Score)>();
        foreach (var candidate in districtCandidates)
        {
            var district = FindRegionMatch(normalized, RegionKeys(candidate.District));
            if (district is null)
            {
                continue;
            }

            var cityMatch = ContainsRegion(normalized, candidate.City);
            var provinceMatch = ContainsRegion(normalized, candidate.Province);
            var completeDistrict = string.Equals(
                TextNormalizer.NormalizeKey(candidate.District),
                district.Value.Key,
                StringComparison.Ordinal);
            // 没有城市前缀时，只接受完整的“江宁区/江北新区”这类行政区名称。
            // “丰台南路”这类普通道路不能仅凭“丰台”两个字被猜成北京，
            // 否则“宁夏银川”“南京马群”等输入会被其他同名区县截断误配。
            if (!cityMatch && !completeDistrict)
            {
                continue;
            }

            var sameDistrictCount = districtCandidates.Count(other =>
                RegionKeys(other.District).Contains(district.Value.Key, StringComparer.Ordinal));
            if (!cityMatch && sameDistrictCount > 1)
            {
                continue;
            }

            var score = (cityMatch ? 200 : 0)
                + (provinceMatch ? 50 : 0)
                + district.Value.Key.Length
                + candidate.Priority;
            districtMatches.Add((candidate, district.Value.Key, district.Value.Index, score));
        }

        var bestDistrict = districtMatches
            .OrderByDescending(static item => item.Score)
            .ThenByDescending(static item => item.Key.Length)
            .FirstOrDefault();
        if (bestDistrict.Candidate is not null)
        {
            var suffix = normalized[(bestDistrict.Index + bestDistrict.Key.Length)..];
            return bestDistrict.Candidate with
            {
                Canonical = bestDistrict.Candidate.Canonical + suffix,
                Kind = suffix.Length == 0 ? bestDistrict.Candidate.Kind : "place_suffix",
                Priority = suffix.Length == 0
                    ? bestDistrict.Candidate.Priority
                    : bestDistrict.Candidate.Priority - 1
            };
        }

        // “省/自治区 + 城市”的常用简写，例如“宁夏银川”“山西晋中”。
        // 省和城市都必须命中同一条行政区记录，不能只看到一个地名就补全。
        var provinceCityMatches = candidates
            .Where(static item => string.IsNullOrWhiteSpace(item.District)
                && IsAdministrativeRegion(item))
            .Select(candidate => (
                Candidate: candidate,
                Province: FindRegionMatch(normalized, candidate.Province),
                City: FindRegionMatch(normalized, candidate.City)))
            .Where(static item => item.Province is not null
                && item.City is not null
                && item.Province.Value.Index < item.City.Value.Index)
            .OrderByDescending(static item => item.Province!.Value.Key.Length
                + item.City!.Value.Key.Length)
            .ThenByDescending(static item => item.Candidate.Priority)
            .ToArray();
        if (provinceCityMatches.Length > 0)
        {
            var bestProvinceCity = provinceCityMatches[0];
            var suffix = normalized[(bestProvinceCity.City!.Value.Index
                + bestProvinceCity.City.Value.Key.Length)..];
            return bestProvinceCity.Candidate with
            {
                Canonical = bestProvinceCity.Candidate.Canonical + suffix,
                Kind = suffix.Length == 0 ? bestProvinceCity.Candidate.Kind : "place_suffix",
                Priority = suffix.Length == 0
                    ? bestProvinceCity.Candidate.Priority
                    : bestProvinceCity.Candidate.Priority - 1
            };
        }

        // 只有城市前缀时也补出省、市，但要求城市名称位于输入开头，
        // 避免把普通句子中间出现的城市名误当作 QTH。
        var administrativeCityCandidates = candidates
            .Where(static item => string.IsNullOrWhiteSpace(item.District)
                && IsAdministrativeRegion(item))
            .ToArray();
        var cityCandidates = administrativeCityCandidates.Length > 0
            ? administrativeCityCandidates
            : candidates.Where(static item => string.IsNullOrWhiteSpace(item.District)).ToArray();
        var cityMatches = cityCandidates
            .Select(candidate => (Candidate: candidate, Match: FindRegionMatch(normalized, candidate.City)))
            .Where(static item => item.Match is not null && item.Match.Value.Index == 0)
            .OrderByDescending(static item => item.Match!.Value.Key.Length)
            .ThenByDescending(static item => item.Candidate.Priority)
            .ToArray();
        if (cityMatches.Length > 0)
        {
            var bestCity = cityMatches[0];
            var suffix = normalized[bestCity.Match!.Value.Key.Length..];
            return bestCity.Candidate with
            {
                Canonical = bestCity.Candidate.Canonical + suffix,
                Kind = suffix.Length == 0 ? bestCity.Candidate.Kind : "place_suffix",
                Priority = suffix.Length == 0
                    ? bestCity.Candidate.Priority
                    : bestCity.Candidate.Priority - 1
            };
        }

        return null;
    }

    private static bool ContainsRegion(string input, string region) =>
        RegionKeys(region).Any(key => input.Contains(key, StringComparison.Ordinal));

    private static (string Key, int Index)? FindRegionMatch(
        string input,
        string region) => FindRegionMatch(input, RegionKeys(region));

    private static (string Key, int Index)? FindRegionMatch(
        string input,
        IReadOnlyList<string> keys)
    {
        foreach (var key in keys.OrderByDescending(static value => value.Length))
        {
            var index = input.IndexOf(key, StringComparison.Ordinal);
            if (index >= 0)
            {
                return (key, index);
            }
        }

        return null;
    }

    private static IReadOnlyList<string> RegionKeys(string value)
    {
        var key = TextNormalizer.NormalizeKey(value);
        if (key.Length == 0)
        {
            return Array.Empty<string>();
        }

        var keys = new List<string> { key };
        void AddKey(string value)
        {
            if (value.Length >= 2 && !keys.Contains(value, StringComparer.Ordinal))
            {
                keys.Add(value);
            }
        }

        foreach (var suffix in new[] { "维吾尔自治区", "回族自治区", "壮族自治区", "自治区" })
        {
            if (key.EndsWith(suffix, StringComparison.Ordinal))
            {
                AddKey(key[..^suffix.Length]);
                break;
            }
        }

        // “新区”是完整地名的一部分，不能把最后的“区”直接截掉。
        if (!key.EndsWith("新区", StringComparison.Ordinal)
            && key.Length > 1
            && "省市区县旗".Contains(key[^1]))
        {
            AddKey(key[..^1]);
        }

        return keys;
    }

    private static int DeviceSourcePriority(string source) => source switch
    {
        "用户别名" => 400,
        "本地别名" => 300,
        "内置别名" => 200,
        "工信部型号库" => 100,
        _ => 0
    };

    private static bool IsAdministrativeRegion(QthCandidate candidate) =>
        candidate.Kind.Contains("admin", StringComparison.OrdinalIgnoreCase)
        || candidate.Kind.Contains("行政", StringComparison.Ordinal);
}
