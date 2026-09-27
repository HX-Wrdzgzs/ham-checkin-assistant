using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace HamCheckin.Native.Core.Parsing;

public static partial class TextNormalizer
{
    [GeneratedRegex(@"[^\p{L}\p{Nd}]+", RegexOptions.Compiled)]
    private static partial Regex NonWordRegex();

    [GeneratedRegex(@"[\s,，;；|]+", RegexOptions.Compiled)]
    private static partial Regex TokenSeparatorRegex();

    [GeneratedRegex(@"^[A-Z]{1,2}[0-9][A-Z0-9]{1,4}(?:/[A-Z0-9]{1,3})?$", RegexOptions.Compiled)]
    private static partial Regex CallsignRegex();

    [GeneratedRegex(@"^[0-9]+(?:\.[0-9]+)?(?:W|瓦)$", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex PowerWithUnitRegex();

    [GeneratedRegex(@"^[1-5][1-9](?:[1-9])?$", RegexOptions.Compiled)]
    private static partial Regex SignalRegex();

    public static string NormalizeKey(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var normalized = value.Normalize(NormalizationForm.FormKC).ToLowerInvariant();
        return NonWordRegex().Replace(normalized, string.Empty);
    }

    public static string NormalizeCallsign(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        return value.Normalize(NormalizationForm.FormKC)
            .Trim()
            .Replace(" ", string.Empty, StringComparison.Ordinal)
            .ToUpperInvariant();
    }

    public static bool IsCallsign(string? value) => CallsignRegex().IsMatch(NormalizeCallsign(value));

    public static IReadOnlyList<string> Tokenize(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return Array.Empty<string>();
        }

        return TokenSeparatorRegex()
            .Split(value.Normalize(NormalizationForm.FormKC).Trim())
            .Where(static token => token.Length > 0)
            .ToArray();
    }

    public static bool IsPowerWithUnit(string value) => PowerWithUnitRegex().IsMatch(value);
    public static bool IsSignal(string value) => SignalRegex().IsMatch(value);

    public static bool LooksLikeDevice(string value)
    {
        var hasLetter = value.Any(char.IsLetter);
        var hasDigit = value.Any(char.IsDigit);
        return hasLetter && hasDigit;
    }

    public static string NormalizePower(string value)
    {
        var normalized = value.Normalize(NormalizationForm.FormKC).Trim();
        if (normalized.EndsWith('瓦'))
        {
            normalized = normalized[..^1] + "W";
        }
        else if (normalized.EndsWith('w') || normalized.EndsWith('W'))
        {
            normalized = normalized[..^1] + "W";
        }

        if (double.TryParse(normalized.TrimEnd('W'), NumberStyles.Float,
                CultureInfo.InvariantCulture, out var numeric))
        {
            return $"{numeric:0.###}W";
        }

        return normalized;
    }
}
