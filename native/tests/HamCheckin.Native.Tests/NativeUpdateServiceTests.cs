using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using HamCheckin.Native.Core.Updates;
using Xunit;

namespace HamCheckin.Native.Tests;

public sealed class NativeUpdateServiceTests
{
    [Fact]
    public async Task CheckReadsReleaseAndChecksumAndComparesNativeVersion()
    {
        var exe = Encoding.UTF8.GetBytes("native-1.0.1-exe");
        var sha = Convert.ToHexString(SHA256.HashData(exe)).ToLowerInvariant();
        var apiPayload = "{\"tag_name\":\"v1.0.1\",\"html_url\":\"https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v1.0.1\",\"body\":\"Native 更新\",\"assets\":[{\"name\":\"HAM.exe\",\"browser_download_url\":\"https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/HAM.exe\"},{\"name\":\"SHA256SUMS.txt\",\"browser_download_url\":\"https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/SHA256SUMS.txt\"}]}";
        var handler = new FixtureHandler(request => request.RequestUri!.AbsoluteUri switch
        {
            NativeVersion.StableApiUrl => Json(apiPayload),
            "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/SHA256SUMS.txt" => Text($"{sha}  HAM.exe\n"),
            "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/HAM.exe" => Bytes(exe),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound)
        });
        using var client = new HttpClient(handler);
        var service = new NativeUpdateService(client);

        var release = await service.CheckAsync("1.0.0");

        Assert.NotNull(release);
        Assert.Equal("1.0.1", release!.Version);
        Assert.Equal(2, handler.Requests.Count);
        Assert.Equal(sha, release.ExpectedSha256);
    }

    [Fact]
    public async Task ManifestFallbackIsUsedWhenApiIsUnavailable()
    {
        var sha = new string('a', 64);
        var handler = new FixtureHandler(request => request.RequestUri!.AbsoluteUri switch
        {
            NativeVersion.StableApiUrl => new HttpResponseMessage(HttpStatusCode.Forbidden),
            NativeVersion.StableManifestUrl => Json($"{{\"version\":\"1.0.0\",\"tag_name\":\"v1.0.0\",\"download_url\":\"https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.0/HAM.exe\",\"sha256\":\"{sha}\",\"release_notes\":\"稳定版\"}}"),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound)
        });
        using var client = new HttpClient(handler);
        var service = new NativeUpdateService(client);

        var release = await service.FetchLatestAsync();

        Assert.Equal("1.0.0", release.Version);
        Assert.Equal("v1.0.0", release.TagName);
        Assert.Equal(2, handler.Requests.Count);
    }

    [Fact]
    public async Task DownloadReturnsOnlySha256VerifiedArtifact()
    {
        var exe = Encoding.UTF8.GetBytes("verified-native-exe");
        var sha = Convert.ToHexString(SHA256.HashData(exe)).ToLowerInvariant();
        var downloadUrl = "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/HAM.exe";
        var handler = new FixtureHandler(request => request.RequestUri!.AbsoluteUri == downloadUrl
            ? Bytes(exe)
            : new HttpResponseMessage(HttpStatusCode.NotFound));
        using var client = new HttpClient(handler);
        var service = new NativeUpdateService(client);
        var release = new NativeReleaseInfo("1.0.1", "v1.0.1", "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v1.0.1", downloadUrl, sha);

        var artifact = await service.DownloadAsync(release);

        try
        {
            Assert.Equal(exe, await File.ReadAllBytesAsync(artifact.Path));
            Assert.Equal(sha, artifact.Sha256);
            Assert.Equal(exe.Length, artifact.Length);
        }
        finally
        {
            File.Delete(artifact.Path);
        }
    }

    [Fact]
    public async Task DownloadRejectsWrongChecksumAndDoesNotReturnArtifact()
    {
        var handler = new FixtureHandler(request => request.RequestUri!.AbsoluteUri.EndsWith("/HAM.exe", StringComparison.Ordinal)
            ? Bytes(Encoding.UTF8.GetBytes("tampered"))
            : new HttpResponseMessage(HttpStatusCode.NotFound));
        using var client = new HttpClient(handler);
        var service = new NativeUpdateService(client);
        var release = new NativeReleaseInfo(
            "1.0.1", "v1.0.1", "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v1.0.1",
            "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.1/HAM.exe",
            new string('0', 64));

        var exception = await Assert.ThrowsAsync<NativeUpdateException>(() => service.DownloadAsync(release));

        Assert.Contains("SHA-256", exception.Message);
    }

    private static HttpResponseMessage Bytes(byte[] payload)
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(payload)
        };
        response.Content.Headers.ContentLength = payload.Length;
        return response;
    }

    private static HttpResponseMessage Text(string payload) => Bytes(Encoding.UTF8.GetBytes(payload));

    private static HttpResponseMessage Json(string payload)
    {
        var response = Text(payload);
        response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
        return response;
    }

    private sealed class FixtureHandler(Func<HttpRequestMessage, HttpResponseMessage> responder)
        : HttpMessageHandler
    {
        public List<string> Requests { get; } = new();

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Requests.Add(request.RequestUri!.AbsoluteUri);
            return Task.FromResult(responder(request));
        }
    }
}
