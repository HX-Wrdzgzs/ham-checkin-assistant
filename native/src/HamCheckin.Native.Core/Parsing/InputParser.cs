using HamCheckin.Native.Core.Catalogs;

namespace HamCheckin.Native.Core.Parsing;

public sealed class InputParser
{
    private static readonly HashSet<string> KnownBrandTokens = new(StringComparer.Ordinal)
    {
        "泉盛", "宝锋", "海能达", "摩托罗拉", "八重洲", "建武", "威诺",
        "全易通", "森海克斯", "即时通", "宝峰", "icom", "yaesu", "motorola", "hytera"
    };

    private readonly Func<CatalogSnapshot> _catalogAccessor;

    public InputParser(CatalogService service)
    {
        ArgumentNullException.ThrowIfNull(service);
        _catalogAccessor = () => service.Current;
    }

    public InputParser(CatalogSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        _catalogAccessor = () => snapshot;
    }

    public ParseResult Parse(string? input)
    {
        var rawText = input?.Trim() ?? string.Empty;
        var tokens = TextNormalizer.Tokenize(rawText);
        if (tokens.Count == 0)
        {
            return ParseResult.Empty with { RawText = rawText };
        }

        var catalog = _catalogAccessor();
        var consumed = new bool[tokens.Count];
        var callsign = ParseField.Empty;
        var qth = ParseField.Empty;
        var device = ParseField.Empty;
        var antenna = ParseField.Empty;
        var power = ParseField.Empty;
        var signal = ParseField.Empty;
        var ambiguous = new List<int>();
        var ambiguousQthTokens = new List<string>();
        var deferredAntenna = new List<(int Index, string Value)>();
        var qthSuggestions = new List<string>();

        for (var index = 0; index < tokens.Count; index++)
        {
            if (!TextNormalizer.IsCallsign(tokens[index]))
            {
                continue;
            }

            var value = TextNormalizer.NormalizeCallsign(tokens[index]);
            callsign = new ParseField(value, "输入", 1.0, tokens[index]);
            consumed[index] = true;
            break;
        }

        // 先识别由空格拆开的品牌/型号或型号组合，例如 “QYT 6900”。
        for (var length = Math.Min(3, tokens.Count); length >= 2 && device.Value.Length == 0; length--)
        {
            for (var start = 0; start + length <= tokens.Count; start++)
            {
                if (Enumerable.Range(start, length).Any(index => consumed[index]))
                {
                    continue;
                }

                var joined = string.Concat(tokens.Skip(start).Take(length));
                var resolved = catalog.ResolveDevice(joined);
                if (resolved is null)
                {
                    continue;
                }

                device = DeviceField(resolved, string.Join(' ', tokens.Skip(start).Take(length)));
                for (var index = start; index < start + length; index++)
                {
                    consumed[index] = true;
                }
                break;
            }
        }

        for (var index = 0; index < tokens.Count; index++)
        {
            if (consumed[index])
            {
                continue;
            }

            var token = tokens[index];
            if (catalog.TryResolveDeviceAndQth(token, out var gluedDevice, out var gluedQth))
            {
                if (device.Value.Length == 0)
                {
                    device = DeviceField(gluedDevice, token);
                }
                if (qth.Value.Length == 0)
                {
                    qth = new ParseField(gluedQth.Canonical, "全国地点库", 1.0, token);
                }
                consumed[index] = true;
                continue;
            }

            var qthCandidates = catalog.ResolveQthCandidates(token);
            var qthResolved = catalog.ResolveQthInput(token);
            var antennaResolved = catalog.ResolveAntenna(token);

            if (qthCandidates.Count > 0 && qthResolved is null)
            {
                qthSuggestions.AddRange(qthCandidates.Select(static item => item.Canonical));
                ambiguousQthTokens.Add(token);
                continue;
            }

            if (qthResolved is not null && antennaResolved is not null)
            {
                ambiguous.Add(index);
                continue;
            }

            var resolvedDevice = catalog.ResolveDevice(token);
            if (resolvedDevice is not null && device.Value.Length == 0)
            {
                device = DeviceField(resolvedDevice, token);
                consumed[index] = true;
                ConsumeAdjacentBrand(tokens, consumed, index, resolvedDevice.StandardName);
                continue;
            }

            var resolvedPower = catalog.ResolvePower(token);
            if (resolvedPower is not null && power.Value.Length == 0)
            {
                power = new ParseField(resolvedPower, "输入规范化", 1.0, token);
                consumed[index] = true;
                continue;
            }

            if (TextNormalizer.IsSignal(token) && signal.Value.Length == 0)
            {
                signal = new ParseField(token, "输入", 0.98, token);
                consumed[index] = true;
                continue;
            }

            if (antennaResolved is not null && antenna.Value.Length == 0)
            {
                // Short alphanumeric strings such as sgm507/xz50 can be
                // either a model or an antenna.  Do not steal an otherwise
                // unknown model when it appears before any context; defer
                // the decision until a device or QTH has been recognized.
                if (device.Value.Length > 0 || qth.Value.Length > 0
                    || IsStandaloneAntennaToken(token))
                {
                    antenna = new ParseField(NormalizeAntenna(antennaResolved), "天线别名", 1.0, token);
                    consumed[index] = true;
                }
                else
                {
                    deferredAntenna.Add((index, NormalizeAntenna(antennaResolved)));
                }
                continue;
            }

            if (qthResolved is not null && qth.Value.Length == 0)
            {
                qth = new ParseField(qthResolved.Canonical, "全国地点库", 1.0, token);
                consumed[index] = true;
            }
        }

        // 先保留明确的中文地点原文，避免 “yz 湖北” 被错误解析为扬州。
        for (var index = 0; index < tokens.Count && qth.Value.Length == 0; index++)
        {
            var token = tokens[index];
            if (consumed[index] || ambiguous.Contains(index)
                || ambiguousQthTokens.Contains(token, StringComparer.Ordinal))
            {
                continue;
            }

            var key = TextNormalizer.NormalizeKey(token);
            if (token.Any(IsCjk) && token.Length >= 2
                && !TextNormalizer.IsMixedModelAndCjk(token)
                && !KnownBrandTokens.Contains(key))
            {
                qth = new ParseField(token, "原文保留", 0.62, token);
                consumed[index] = true;
            }
        }

        foreach (var index in ambiguous)
        {
            var token = tokens[index];
            if (qth.Value.Length == 0)
            {
                var resolved = catalog.ResolveQth(token);
                if (resolved is not null)
                {
                    qth = new ParseField(resolved.Canonical, "全国地点库", 1.0, token);
                    consumed[index] = true;
                    continue;
                }
            }

            if (antenna.Value.Length == 0)
            {
                var resolved = catalog.ResolveAntenna(token);
                if (resolved is not null)
                {
                    antenna = new ParseField(NormalizeAntenna(resolved), "天线别名", 1.0, token);
                    consumed[index] = true;
                }
            }
        }

        // Revisit an ambiguous alphanumeric antenna after the rest of the
        // line has provided context.  If no context appears, the normal
        // unknown-model fallback below preserves it as device raw text.
        if (antenna.Value.Length == 0 && (device.Value.Length > 0 || qth.Value.Length > 0))
        {
            foreach (var (index, value) in deferredAntenna)
            {
                if (consumed[index])
                {
                    continue;
                }

                antenna = new ParseField(value, "天线别名", 1.0, tokens[index]);
                consumed[index] = true;
                break;
            }
        }

        // 未命中的字母数字组合仍保留到设备列，绝不因资料库缺失而丢数据。
        for (var index = 0; index < tokens.Count && device.Value.Length == 0; index++)
        {
            if (consumed[index] || !TextNormalizer.LooksLikeDevice(tokens[index])
                || (index == 0 && callsign.Value.Length == 0
                    && TextNormalizer.LooksLikeIncompleteCallsign(tokens[index])))
            {
                continue;
            }

            device = new ParseField(tokens[index], "未收录型号原文", 0.45, tokens[index]);
            consumed[index] = true;
        }

        var unmatched = tokens
            .Where((_, index) => !consumed[index])
            .ToArray();

        if (qth.Value.Length == 0 && qthSuggestions.Count > 0)
        {
            qth = new ParseField(
                "", "需要选择", 0,
                string.Join(' ', ambiguousQthTokens.Distinct(StringComparer.Ordinal)),
                qthSuggestions.Distinct(StringComparer.Ordinal).Take(5).ToArray());
        }

        return new ParseResult(
            rawText,
            tokens,
            callsign,
            qth,
            device,
            antenna,
            power,
            signal,
            unmatched);
    }

    private static ParseField DeviceField(DeviceCandidate device, string raw) => new(
        device.StandardName,
        device.Source,
        device.Confidence,
        raw);

    private static string NormalizeAntenna(string value) => value == "原" ? "原装天线" : value;

    private static bool IsStandaloneAntennaToken(string token)
    {
        var key = TextNormalizer.NormalizeKey(token);
        return TextNormalizer.ContainsCjk(token)
            || token.Contains('.', StringComparison.Ordinal)
            || key.All(static character => character is >= '0' and <= '9')
            || key is "771" or "770" or "770h" or "770s";
    }

    private static void ConsumeAdjacentBrand(
        IReadOnlyList<string> tokens,
        IList<bool> consumed,
        int deviceIndex,
        string standardName)
    {
        foreach (var adjacent in new[] { deviceIndex - 1, deviceIndex + 1 })
        {
            if (adjacent < 0 || adjacent >= tokens.Count || consumed[adjacent])
            {
                continue;
            }

            var key = TextNormalizer.NormalizeKey(tokens[adjacent]);
            if (KnownBrandTokens.Contains(key)
                && TextNormalizer.NormalizeKey(standardName).Contains(key, StringComparison.Ordinal))
            {
                consumed[adjacent] = true;
            }
        }
    }

    private static bool IsCjk(char character) => character is >= '\u3400' and <= '\u9fff';
}
