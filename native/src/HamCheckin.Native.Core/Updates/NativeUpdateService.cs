using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace HamCheckin.Native.Core.Updates;

public static class NativeVersion
{
    public const string Current = "1.0.19";
    public const string Repository = "HX-Wrdzgzs/ham-checkin-assistant";
    public const string SponsorUrl =
        "https://www.ifdian.net/a/wrdzgzs?utm_source=copylink&utm_medium=link";
    public const string StableApiUrl =
        "https://api.github.com/repos/HX-Wrdzgzs/ham-checkin-assistant/releases/latest";
    public const string StableManifestUrl =
        "https://raw.githubusercontent.com/HX-Wrdzgzs/ham-checkin-assistant/main/updates/latest.json";
    public const string LegacyManifestUrl =
        "https://raw.githubusercontent.com/HX-Wrdzgzs/ham-checkin-assistant/codex/ham-checkin-release/updates/latest.json";
    public const string UpdateAssetName = "HAM.exe";
    public const string ChecksumAssetName = "SHA256SUMS.txt";
}

public sealed record NativeReleaseInfo(
    string Version,
    string TagName,
    string HtmlUrl,
    string DownloadUrl,
    string ExpectedSha256,
    string ReleaseNotes = "",
    string PublishedAt = "");

public sealed record NativeUpdateArtifact(string Path, long Length, string Sha256);

public sealed class NativeUpdateException(string message, Exception? inner = null)
    : InvalidOperationException(message, inner);

/// <summary>
/// Native 版的在线更新协议：只接受本项目 GitHub Release 下载地址，先下载到
/// 临时文件并校验 SHA-256，校验失败绝不返回可安装文件。
/// </summary>
public sealed class NativeUpdateService
{
    private const long MaxUpdateBytes = 250L * 1024 * 1024;
    private const int DownloadAttempts = 3;
    private static readonly Regex VersionPattern = new(
        @"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", RegexOptions.Compiled);
    private readonly HttpClient _http;

    public NativeUpdateService(HttpClient? httpClient = null)
    {
        _http = httpClient ?? new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(15)
        };
        if (_http.DefaultRequestHeaders.UserAgent.Count == 0)
        {
            _http.DefaultRequestHeaders.UserAgent.Add(
                new ProductInfoHeaderValue("ham-checkin-assistant", NativeVersion.Current));
        }
    }

    public async Task<NativeReleaseInfo?> CheckAsync(
        string? currentVersion = null,
        CancellationToken cancellationToken = default)
    {
        var release = await FetchLatestAsync(cancellationToken).ConfigureAwait(false);
        return IsNewer(release.Version, currentVersion ?? NativeVersion.Current)
            ? release
            : null;
    }

    public static bool IsNewer(string remoteVersion, string currentVersion) =>
        CompareVersion(remoteVersion, currentVersion) > 0;

    public async Task<NativeReleaseInfo> FetchLatestAsync(
        CancellationToken cancellationToken = default)
    {
        Exception? apiError = null;
        try
        {
            var payload = await GetBytesAsync(NativeVersion.StableApiUrl, cancellationToken)
                .ConfigureAwait(false);
            return await ParseApiPayloadAsync(payload, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException
                                           or JsonException or NativeUpdateException
                                           or TaskCanceledException)
        {
            apiError = exception;
        }

        Exception? mainManifestError = null;
        try
        {
            var payload = await GetBytesAsync(NativeVersion.StableManifestUrl, cancellationToken)
                .ConfigureAwait(false);
            return ParseManifest(payload);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException
                                           or JsonException or NativeUpdateException
                                           or TaskCanceledException)
        {
            mainManifestError = exception;
        }

        try
        {
            var payload = await GetBytesAsync(NativeVersion.LegacyManifestUrl, cancellationToken)
                .ConfigureAwait(false);
            return ParseManifest(payload);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException
                                           or JsonException or NativeUpdateException
                                           or TaskCanceledException)
        {
            throw new NativeUpdateException(
                $"更新检查失败：GitHub API、main 清单和兼容清单均不可用。API：{apiError?.Message}；main：{mainManifestError?.Message}；兼容：{exception.Message}",
                exception);
        }
    }

    public async Task<NativeUpdateArtifact> DownloadAsync(
        NativeReleaseInfo release,
        IProgress<double>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ValidateRelease(release);
        var expected = release.ExpectedSha256.ToLowerInvariant();
        var lastError = "下载到的更新文件为空";

        for (var attempt = 0; attempt < DownloadAttempts; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var target = Path.Combine(
                Path.GetTempPath(),
                $"ham-checkin-native-update-{Environment.ProcessId}-{Guid.NewGuid():N}.exe");
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, release.DownloadUrl);
                request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue(
                    "application/octet-stream"));
                using var response = await _http.SendAsync(
                    request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
                    .ConfigureAwait(false);
                response.EnsureSuccessStatusCode();
                if (response.Content.Headers.ContentLength is > MaxUpdateBytes)
                {
                    throw new NativeUpdateException("更新文件超过 250 MB 安全限制。");
                }

                await using var input = await response.Content.ReadAsStreamAsync(cancellationToken)
                    .ConfigureAwait(false);
                await using var output = new FileStream(
                    target, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                    1024 * 1024, FileOptions.SequentialScan | FileOptions.Asynchronous);
                using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                var buffer = new byte[1024 * 1024];
                long total = 0;
                int read;
                while ((read = await input.ReadAsync(buffer, cancellationToken).ConfigureAwait(false)) > 0)
                {
                    total += read;
                    if (total > MaxUpdateBytes)
                    {
                        throw new NativeUpdateException("更新文件超过 250 MB 安全限制。");
                    }
                    await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken)
                        .ConfigureAwait(false);
                    hash.AppendData(buffer, 0, read);
                    if (response.Content.Headers.ContentLength is > 0)
                    {
                        progress?.Report(Math.Clamp((double)total /
                            response.Content.Headers.ContentLength.Value, 0, 1));
                    }
                }

                await output.FlushAsync(cancellationToken).ConfigureAwait(false);
                var actual = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
                if (total == 0)
                {
                    throw new NativeUpdateException("下载到的更新文件为空。");
                }
                if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
                {
                    throw new NativeUpdateException(
                        $"更新文件 SHA-256 校验失败：期望 {expected}，实际 {actual}。");
                }

                progress?.Report(1);
                return new NativeUpdateArtifact(target, total, actual);
            }
            catch (OperationCanceledException)
            {
                TryDelete(target);
                throw;
            }
            catch (Exception exception) when (exception is HttpRequestException or IOException
                                               or NativeUpdateException or InvalidOperationException)
            {
                TryDelete(target);
                lastError = exception.Message;
                if (attempt + 1 < DownloadAttempts)
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(250 * (attempt + 1)),
                        cancellationToken).ConfigureAwait(false);
                }
            }
        }

        throw new NativeUpdateException(
            $"{lastError}；已重试 {DownloadAttempts} 次，原程序未修改。");
    }

    private async Task<NativeReleaseInfo> ParseApiPayloadAsync(
        byte[] bytes, CancellationToken cancellationToken)
    {
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement;
        var tag = RequiredString(root, "tag_name");
        var version = NumericVersion(tag);
        var html = OptionalString(root, "html_url")
            ?? $"https://github.com/{NativeVersion.Repository}/releases/tag/{tag}";
        var assets = root.TryGetProperty("assets", out var assetElement)
            && assetElement.ValueKind == JsonValueKind.Array
            ? assetElement.EnumerateArray().ToArray()
            : Array.Empty<JsonElement>();
        var download = FindAssetUrl(assets, NativeVersion.UpdateAssetName, "HAM点名助手.exe")
            ?? throw new NativeUpdateException("Release 缺少 HAM.exe 更新附件。");
        var checksumUrl = FindAssetUrl(assets, NativeVersion.ChecksumAssetName);
        if (checksumUrl is null)
        {
            throw new NativeUpdateException("Release 缺少 SHA256SUMS.txt 校验附件。");
        }
        var checksum = await GetBytesAsync(checksumUrl, cancellationToken).ConfigureAwait(false);
        var expected = ParseChecksum(checksum, NativeVersion.UpdateAssetName, "HAM点名助手.exe")
            ?? throw new NativeUpdateException("SHA256SUMS.txt 中没有 HAM.exe 的有效校验值。");
        return new NativeReleaseInfo(
            version, tag, html, download, expected,
            OptionalString(root, "body") ?? "", OptionalString(root, "published_at") ?? "");
    }

    private static NativeReleaseInfo ParseManifest(byte[] bytes)
    {
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement;
        var tag = OptionalString(root, "tag_name") ?? "";
        var version = NumericVersion(OptionalString(root, "version") ?? tag);
        tag = string.IsNullOrWhiteSpace(tag) ? $"v{version}" : tag;
        var download = RequiredString(root, "download_url");
        EnsureAllowedUrl(download);
        var sha = RequiredString(root, "sha256").ToLowerInvariant();
        if (!Regex.IsMatch(sha, "^[0-9a-f]{64}$", RegexOptions.IgnoreCase))
        {
            throw new NativeUpdateException("更新清单的 SHA-256 格式无效。");
        }
        var html = OptionalString(root, "html_url")
            ?? $"https://github.com/{NativeVersion.Repository}/releases/tag/{tag}";
        return new NativeReleaseInfo(
            version, tag, html, download, sha,
            OptionalString(root, "release_notes") ?? OptionalString(root, "body") ?? "",
            OptionalString(root, "published_at") ?? "");
    }

    private async Task<byte[]> GetBytesAsync(string url, CancellationToken cancellationToken)
    {
        using var response = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
    }

    private static void ValidateRelease(NativeReleaseInfo release)
    {
        EnsureAllowedUrl(release.DownloadUrl);
        if (!Regex.IsMatch(release.ExpectedSha256 ?? "", "^[0-9a-f]{64}$",
            RegexOptions.IgnoreCase))
        {
            throw new NativeUpdateException("更新信息缺少有效 SHA-256。");
        }
    }

    private static void EnsureAllowedUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || uri.Scheme != Uri.UriSchemeHttps
            || !string.Equals(uri.Host, "github.com", StringComparison.OrdinalIgnoreCase)
            || !uri.AbsolutePath.StartsWith(
                $"/{NativeVersion.Repository}/releases/download/",
                StringComparison.OrdinalIgnoreCase))
        {
            throw new NativeUpdateException("更新下载地址不是受信任的 GitHub Release 地址。");
        }
    }

    private static string? FindAssetUrl(
        IEnumerable<JsonElement> assets, params string[] acceptedNames)
    {
        foreach (var asset in assets)
        {
            var name = OptionalString(asset, "name");
            var label = OptionalString(asset, "label");
            if (!acceptedNames.Any(value => string.Equals(value, name, StringComparison.Ordinal)
                                            || string.Equals(value, label, StringComparison.Ordinal)))
            {
                continue;
            }
            var url = OptionalString(asset, "browser_download_url");
            if (!string.IsNullOrWhiteSpace(url))
            {
                EnsureAllowedUrl(url);
                return url;
            }
        }
        return null;
    }

    private static string? ParseChecksum(byte[] bytes, params string[] acceptedNames)
    {
        var text = System.Text.Encoding.UTF8.GetString(bytes);
        foreach (var line in text.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = line.Trim().Split((char[]?)null, 2,
                StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 2 || !Regex.IsMatch(parts[0], "^[0-9a-f]{64}$",
                RegexOptions.IgnoreCase))
            {
                continue;
            }
            var filename = parts[1].Trim().TrimStart('*');
            if (acceptedNames.Any(value => string.Equals(value, filename,
                StringComparison.Ordinal)))
            {
                return parts[0].ToLowerInvariant();
            }
        }
        return null;
    }

    private static string NumericVersion(string value)
    {
        var match = VersionPattern.Match(value ?? "");
        if (!match.Success)
        {
            throw new NativeUpdateException($"无法识别更新版本号：{value}");
        }
        return $"{int.Parse(match.Groups[1].Value)}.{int.Parse(match.Groups[2].Value)}.{int.Parse(match.Groups[3].Value)}";
    }

    private static int CompareVersion(string left, string right)
    {
        var a = new Version(NumericVersion(left));
        var b = new Version(NumericVersion(right));
        return a.CompareTo(b);
    }

    private static string RequiredString(JsonElement root, string property)
    {
        var value = OptionalString(root, property);
        return !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new NativeUpdateException($"更新响应缺少字段：{property}");
    }

    private static string? OptionalString(JsonElement root, string property) =>
        root.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { }
    }
}
