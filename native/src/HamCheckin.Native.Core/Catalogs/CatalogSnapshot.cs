using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.Core.Catalogs;

public sealed class CatalogSnapshot
{
    private readonly IReadOnlyDictionary<string, DeviceCandidate> _deviceAliases;
    private readonly IReadOnlyDictionary<string, DeviceCandidate> _miitModels;
    private readonly IReadOnlyDictionary<string, string> _antennaAliases;
    private readonly IReadOnlyDictionary<string, string> _powerAliases;
    private readonly IReadOnlyDictionary<string, IReadOnlyList<QthCandidate>> _qthAliases;
    private readonly IReadOnlyList<KeyValuePair<string, DeviceCandidate>> _devicePrefixes;
    private readonly IReadOnlyList<QthCandidate> _allQthCandidates;

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
        _devicePrefixes = _deviceAliases
            .Concat(_miitModels)
            .OrderByDescending(static pair => pair.Key.Length)
            .ThenByDescending(pair => DeviceSourcePriority(pair.Value.Source))
            .ToArray();
        _allQthCandidates = _qthAliases.Values
            .SelectMany(static values => values)
            .DistinctBy(static item => item.Canonical, StringComparer.Ordinal)
            .ToArray();
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
            ? values.Select(NormalizeCandidate)
                .DistinctBy(static item => item.Canonical, StringComparer.Ordinal)
                .ToArray()
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
            return NormalizeCandidate(ranked[0]);
        }

        var first = ranked[0];
        var second = ranked[1];
        // 不用行政层级深浅替不同地点做决定。
        // 例如 bj 同时可能是北京市、贵州省毕节市或陕西省宝鸡市；
        // “省级/市级更浅”不是现场语义证据，必须交给用户明确选择。
        return first.Priority > second.Priority
            ? NormalizeCandidate(first)
            : string.Equals(first.Canonical, second.Canonical, StringComparison.Ordinal)
                ? NormalizeCandidate(first)
                : null;
    }

    /// <summary>
    /// 处理现场常见的无空格粘连：pd780南通。只有设备别名是完整前缀，
    /// 且剩余部分能独立命中 QTH 时才拆分，避免把 sgm507 或 bh8
    /// 拆成错误的行政区加尾巴。
    /// </summary>
    public bool TryResolveDeviceAndQth(
        string token,
        out DeviceCandidate device,
        out QthCandidate qth)
    {
        device = null!;
        qth = null!;
        var normalized = TextNormalizer.NormalizeKey(token);
        if (normalized.Length < 4 || !TextNormalizer.ContainsCjk(normalized))
        {
            return false;
        }

        foreach (var pair in _devicePrefixes)
        {
            if (!normalized.StartsWith(pair.Key, StringComparison.Ordinal)
                || normalized.Length <= pair.Key.Length)
            {
                continue;
            }

            var suffix = normalized[pair.Key.Length..];
            if (suffix.Length < 2 || !TextNormalizer.ContainsCjk(suffix))
            {
                continue;
            }

            var resolvedQth = ResolveQthInput(suffix);
            if (resolvedQth is null)
            {
                continue;
            }

            device = pair.Value;
            qth = resolvedQth;
            return true;
        }

        return false;
    }

    /// <summary>
    /// 解析“行政区缩写 + 中文道路/地标”的现场写法，例如
    /// njgl中山路169号 -> 江苏省南京市鼓楼区中山路169号。
    /// 只有前缀唯一命中时才会采用，避免把普通中文误猜成地点。
    /// </summary>
    public QthCandidate? ResolveQthInput(string token)
    {
        var normalized = token?.Trim() ?? string.Empty;
        // A three-character prefix such as “BH8” is an incomplete callsign,
        // not a location alias. Keep this guard in the catalog layer rather
        // than relying only on InputParser so field editors, suggestions and
        // future callers cannot turn it into “广西壮族自治区北海市”.
        if (TextNormalizer.LooksLikeIncompleteCallsign(normalized))
        {
            return null;
        }

        var direct = ResolveQth(normalized);
        if (direct is not null)
        {
            return direct;
        }

        // Exact same-name administrative entries must remain a choice. Do not
        // continue into the Chinese prefix heuristics, which could otherwise
        // select one of the same-name districts merely because it happens to
        // match the city/district scoring order.
        if (ResolveQthCandidates(normalized).Count > 1)
        {
            return null;
        }

        if (normalized.Length < 3)
        {
            return null;
        }

        var mixedCityPlace = ResolveAsciiCityWithChineseSuffix(normalized);
        if (mixedCityPlace is not null)
        {
            return mixedCityPlace;
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
                return NormalizeCandidate(candidate);
            }

            if (!IsSafePlaceSuffix(suffix))
            {
                continue;
            }

            return AppendSuffix(candidate, suffix);
        }

        // Pure ASCII tokens have already had their exact/unique administrative
        // aliases checked above.  Scanning the nationwide Chinese candidate
        // list for every callsign, model, antenna, and power token would make
        // the normal hot path scale with the entire catalog.
        if (!TextNormalizer.ContainsCjk(normalized))
        {
            return null;
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

        var minimumFuzzyPrefix = key.Length >= 5 ? 5 : int.MaxValue;
        return _deviceAliases
            .Concat(_miitModels)
            .Select(pair =>
            {
                var standardKey = TextNormalizer.NormalizeKey(pair.Value.StandardName);
                var prefix = CommonPrefixLength(pair.Key, key);
                var exact = string.Equals(pair.Key, key, StringComparison.Ordinal);
                var standardExact = string.Equals(standardKey, key, StringComparison.Ordinal);
                // Do not treat a short alias embedded in an unknown longer
                // model as a candidate.  For example, TK11 contains the
                // K1 alias, but it is not a UV-K1.  Candidates may still be
                // found when the catalog alias or standard name contains
                // the user's query, or through the explicit long-prefix
                // search below.
                var contains = pair.Key.Contains(key, StringComparison.Ordinal)
                    || standardKey.Contains(key, StringComparison.Ordinal);
                if (key.Length < 4
                    && !pair.Key.StartsWith(key, StringComparison.Ordinal)
                    && !standardKey.StartsWith(key, StringComparison.Ordinal))
                {
                    // A short query must not match the middle of another
                    // model alias: “k1” is not evidence for “TK11”. Exact
                    // aliases still resolve before this suggestion path.
                    contains = false;
                }
                var fuzzy = prefix >= minimumFuzzyPrefix;
                return new
                {
                    Pair = pair,
                    Prefix = prefix,
                    Exact = exact,
                    StandardExact = standardExact,
                    Contains = contains,
                    IsMatch = contains || fuzzy
                };
            })
            .Where(item => item.IsMatch)
            .OrderByDescending(item => item.Exact)
            .ThenByDescending(item => item.StandardExact)
            .ThenByDescending(item => item.Contains)
            .ThenByDescending(item => item.Prefix)
            .ThenByDescending(item => DeviceSourcePriority(item.Pair.Value.Source))
            .ThenBy(item => item.Pair.Key.Length)
            .Select(static item => item.Pair.Value)
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
        var mixedProvinceCity = ResolveMixedProvinceCityInput(normalized);
        if (mixedProvinceCity is not null)
        {
            return mixedProvinceCity;
        }

        var candidates = _allQthCandidates;

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
            // 只有中文地点后缀才属于 QTH。字母/数字尾巴可能是天线、
            // 设备或用户尚未收录的现场缩写；不能把它静默拼进 QTH。
            if (IsSafePlaceSuffix(suffix))
            {
                return candidate with
                {
                    Canonical = candidate.Canonical + suffix,
                    Kind = "place_suffix",
                    Priority = candidate.Priority - 1
                };
            }
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
            // 没有城市前缀时，接受完整行政区名称，或接受“省份 + 唯一
            // 区县/县级市”的写法，例如 江苏张家港、江苏盐城响水。
            // 普通道路没有省份/完整行政区证据时仍不能仅凭两个字猜测。
            if (!cityMatch && !completeDistrict && !provinceMatch)
            {
                continue;
            }

            var sameDistrictCount = districtCandidates.Count(other =>
                RegionKeys(other.District).Contains(district.Value.Key, StringComparer.Ordinal));
            if (!cityMatch && sameDistrictCount > 1)
            {
                continue;
            }

            // Some cities and their county-level districts share the same
            // root name, for example 长沙市 / 长沙县.  The short input
            // “湖南长沙” contains the city root but no district evidence;
            // do not promote it to the county merely because RegionKeys
            // also permits suffix-less matching.  Explicit “长沙县” still
            // keeps the full district key and is accepted below.
            if (cityMatch
                && RegionKeys(candidate.City).Contains(district.Value.Key, StringComparer.Ordinal)
                && !string.Equals(
                    TextNormalizer.NormalizeKey(candidate.District),
                    district.Value.Key,
                    StringComparison.Ordinal))
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
            if (suffix.Length == 0)
            {
                return NormalizeCandidate(bestDistrict.Candidate);
            }

            if (IsSafePlaceSuffix(suffix))
            {
                return AppendSuffix(bestDistrict.Candidate, suffix);
            }
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
            if (suffix.Length == 0)
            {
                return NormalizeCandidate(bestProvinceCity.Candidate);
            }

            if (IsSafePlaceSuffix(suffix))
            {
                return AppendSuffix(bestProvinceCity.Candidate, suffix);
            }
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
            if (suffix.Length == 0)
            {
                return NormalizeCandidate(bestCity.Candidate);
            }

            if (IsSafePlaceSuffix(suffix))
            {
                return AppendSuffix(bestCity.Candidate, suffix);
            }
        }

        return null;
    }

    /// <summary>
    /// Splits a Chinese administrative prefix followed by an unknown ASCII
    /// suffix, for example “山东qcd” or “广东省汕头市m507”. The prefix is
    /// returned as the most specific administrative value that is proven by
    /// the local catalog; the suffix remains a separate token so the parser
    /// can expose it as pending correction or recognize it as an antenna or
    /// device alias. Unknown text is never silently folded into QTH.
    /// </summary>
    public bool TrySplitAdministrativePrefix(
        string token,
        out QthCandidate candidate,
        out string suffix)
    {
        candidate = null!;
        suffix = string.Empty;

        var normalized = TextNormalizer.NormalizeKey(token);
        if (normalized.Length < 3)
        {
            return false;
        }

        var prefixLength = 0;
        while (prefixLength < normalized.Length
            && normalized[prefixLength] is >= '\u3400' and <= '\u9fff')
        {
            prefixLength++;
        }

        if (prefixLength < 2 || prefixLength == normalized.Length)
        {
            return false;
        }

        var prefix = normalized[..prefixLength];
        var asciiSuffix = normalized[prefixLength..];
        if (asciiSuffix.Length == 0
            || asciiSuffix.Any(static character => !char.IsAsciiLetterOrDigit(character)))
        {
            return false;
        }

        // A complete local alias wins over prefix splitting. This keeps a
        // future user-defined alias such as “山东qcd” authoritative.
        if (ResolveQthInput(normalized) is not null)
        {
            return false;
        }

        var exactPrefixCandidates = _allQthCandidates
            .Where(static item => IsAdministrativeRegion(item))
            .Where(item => RegionKeys(item.Canonical)
                .Contains(prefix, StringComparer.Ordinal))
            .Select(NormalizeCandidate)
            .DistinctBy(static item => item.Canonical, StringComparer.Ordinal)
            .ToArray();

        if (exactPrefixCandidates.Length == 1)
        {
            candidate = exactPrefixCandidates[0];
            suffix = asciiSuffix;
            return true;
        }

        // The built-in national snapshot may have district rows but no
        // standalone province row. In that case a unique province prefix is
        // still known, while its city is not. Keep that useful fact without
        // inventing a city.
        var provinceNames = _allQthCandidates
            .Where(static item => IsAdministrativeRegion(item))
            .Select(static item => item.Province)
            .Where(static province => !string.IsNullOrWhiteSpace(province))
            .Distinct(StringComparer.Ordinal)
            .Where(province => RegionKeys(province)
                .Contains(prefix, StringComparer.Ordinal))
            .ToArray();

        if (provinceNames.Length != 1)
        {
            return false;
        }

        candidate = new QthCandidate(
            provinceNames[0],
            provinceNames[0],
            string.Empty,
            string.Empty,
            "admin_prefix_partial",
            600);
        suffix = asciiSuffix;
        return true;
    }

    /// <summary>
    /// Resolves a city abbreviation followed by a Chinese place suffix,
    /// such as “nj师范大学仙林校区”.  The suffix is matched against the
    /// installed detailed place snapshot when possible; otherwise it is
    /// retained after the full administrative city so the original place
    /// text is never dropped.
    /// </summary>
    private QthCandidate? ResolveAsciiCityWithChineseSuffix(string normalized)
    {
        var asciiPrefix = new string(normalized.TakeWhile(static character =>
            character is >= 'a' and <= 'z').ToArray());
        if (asciiPrefix.Length < 2 || asciiPrefix.Length >= normalized.Length)
        {
            return null;
        }

        var suffix = normalized[asciiPrefix.Length..].Trim();
        if (!IsSafePlaceSuffix(suffix))
        {
            return null;
        }

        if (!_qthAliases.TryGetValue(asciiPrefix, out var prefixCandidates))
        {
            return null;
        }

        var cityCandidates = prefixCandidates
            .Where(static item => string.IsNullOrWhiteSpace(item.District)
                && IsAdministrativeRegion(item))
            .DistinctBy(static item => item.Canonical, StringComparer.Ordinal)
            .ToArray();
        if (cityCandidates.Length == 0)
        {
            return null;
        }

        var detailed = cityCandidates
            .SelectMany(cityCandidate =>
            {
                var city = NormalizeCandidate(cityCandidate);
                var cityKey = TextNormalizer.NormalizeKey(city.Canonical);
                var cityNameKey = TextNormalizer.NormalizeKey(city.City);
                if (cityNameKey.EndsWith('市'))
                {
                    cityNameKey = cityNameKey[..^1];
                }
                return _allQthCandidates
                    .Where(candidate => string.Equals(candidate.Province, city.Province, StringComparison.Ordinal)
                        && string.Equals(candidate.City, city.City, StringComparison.Ordinal)
                        && !string.Equals(candidate.Canonical, city.Canonical, StringComparison.Ordinal))
                    .Select(candidate => (City: city, Candidate: candidate,
                        CityKey: cityKey, CityNameKey: cityNameKey));
            })
            .Select(item =>
            {
                var cityKey = item.CityKey;
                var cityNameKey = item.CityNameKey;
                var candidate = item.Candidate;
                var canonicalKey = TextNormalizer.NormalizeKey(candidate.Canonical);
                var remainder = canonicalKey.StartsWith(cityKey, StringComparison.Ordinal)
                    ? canonicalKey[cityKey.Length..]
                    : canonicalKey;
                var expandedSuffix = cityNameKey + suffix;
                var matches = remainder.StartsWith(suffix, StringComparison.Ordinal)
                    || remainder.StartsWith(expandedSuffix, StringComparison.Ordinal);
                return (item.City, Candidate: candidate, Matches: matches,
                    ExactLength: matches ? canonicalKey.Length : 0);
            })
            .Where(static item => item.Matches)
            .OrderByDescending(static item => item.Candidate.Priority)
            .ThenByDescending(static item => item.ExactLength)
            .ToArray();
        if (detailed.Length > 0)
        {
            var best = detailed[0];
            var equallyRanked = detailed
                .Where(item => item.Candidate.Priority == best.Candidate.Priority
                    && item.ExactLength == best.ExactLength)
                .Select(static item => item.Candidate.Canonical)
                .Distinct(StringComparer.Ordinal)
                .Take(2)
                .ToArray();
            return equallyRanked.Length == 1
                ? NormalizeCandidate(best.Candidate)
                : null;
        }

        if (cityCandidates.Length != 1)
        {
            return null;
        }

        var city = NormalizeCandidate(cityCandidates[0]);
        return AppendSuffix(city, suffix);
    }

    /// <summary>
    /// 处理现场常见的“中文省份 + 城市拼音缩写”，例如“山东qd”、
    /// “安徽mas”。纯字母的省市组合由内置别名直接处理；这里专门处理
    /// 中英文粘连，且只接受同一条行政记录，避免把任意设备型号拆成 QTH。
    /// </summary>
    private QthCandidate? ResolveMixedProvinceCityInput(string normalized)
    {
        var provinceText = new string(normalized.TakeWhile(static character =>
            character is >= '\u3400' and <= '\u9fff').ToArray());
        if (provinceText.Length < 2 || provinceText.Length >= normalized.Length)
        {
            return null;
        }

        var cityText = normalized[provinceText.Length..];
        if (cityText.Length is < 2 or > 8
            || !cityText.All(static character => character is >= 'a' and <= 'z'))
        {
            return null;
        }

        var provinceKey = TextNormalizer.NormalizeKey(provinceText);
        var cityKey = TextNormalizer.NormalizeKey(cityText);
        if (provinceKey.Length == 0 || cityKey.Length == 0)
        {
            return null;
        }

        var candidates = new List<QthCandidate>();
        foreach (var key in new[] { cityKey, provinceKey + cityKey })
        {
            if (_qthAliases.TryGetValue(key, out var matches))
            {
                candidates.AddRange(matches);
            }
        }

        var matchesForProvince = candidates
            .Where(candidate => string.IsNullOrWhiteSpace(candidate.District)
                && IsAdministrativeRegion(candidate)
                && RegionKeys(candidate.Province).Contains(provinceKey, StringComparer.Ordinal))
            .DistinctBy(static candidate => candidate.Canonical, StringComparer.Ordinal)
            .ToArray();

        return matchesForProvince.Length == 1
            ? NormalizeCandidate(matchesForProvince[0])
            : null;
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

    private static int CommonPrefixLength(string left, string right)
    {
        var length = Math.Min(left.Length, right.Length);
        var index = 0;
        while (index < length && left[index] == right[index])
        {
            index++;
        }

        return index;
    }

    private static bool IsAdministrativeRegion(QthCandidate candidate) =>
        candidate.Kind.Contains("admin", StringComparison.OrdinalIgnoreCase)
        || candidate.Kind.Contains("行政", StringComparison.Ordinal);

    private static bool IsSafePlaceSuffix(string suffix) =>
        suffix.Length > 0
        && TextNormalizer.ContainsCjk(suffix)
        && suffix[0] is >= '\u3400' and <= '\u9fff'
        // Numeric address tails such as “中山路169号” are valid. ASCII
        // letters are deliberately excluded so “汕头市m507” is split and
        // the unknown model/antenna token remains visible for correction.
        && suffix.All(static character =>
            character is >= '\u3400' and <= '\u9fff' || char.IsAsciiDigit(character));

    private static QthCandidate AppendSuffix(QthCandidate candidate, string suffix)
    {
        var canonical = NormalizeCandidate(candidate).Canonical;
        if (canonical.EndsWith('区') && suffix.StartsWith('县'))
        {
            canonical = canonical[..^1] + "县";
            suffix = suffix[1..];
        }

        return new QthCandidate(
            canonical + suffix,
            candidate.Province,
            candidate.City,
            candidate.District,
            "place_suffix",
            Math.Max(0, candidate.Priority - 1));
    }

    private static QthCandidate NormalizeCandidate(QthCandidate candidate)
    {
        var canonical = candidate.Canonical switch
        {
            "江苏省盐城市响水区" => "江苏省盐城市响水县",
            "江苏省盐城市滨海区" => "江苏省盐城市滨海县",
            _ => candidate.Canonical
        };

        // Some prefecture-level entries in the bundled snapshot use the
        // prefecture name again as a district (for example
        // “甘肃省临夏市临夏市”). That is a data-shape artifact, not a
        // useful QTH. Collapse only the exact Province + City + same District
        // form, leaving genuine districts untouched.
        var cityKey = TextNormalizer.NormalizeKey(candidate.City);
        var districtKey = TextNormalizer.NormalizeKey(candidate.District);
        var duplicateAdministrativeLevel = cityKey.Length > 0
            && string.Equals(cityKey, districtKey, StringComparison.Ordinal)
            && string.Equals(
                TextNormalizer.NormalizeKey(canonical),
                TextNormalizer.NormalizeKey(candidate.Province + candidate.City + candidate.District),
                StringComparison.Ordinal);

        return duplicateAdministrativeLevel
            ? candidate with { Canonical = candidate.Province + candidate.City, District = string.Empty }
            : candidate with { Canonical = canonical };
    }
}
