using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.LanServer;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 宿主生命周期（设计 3.1）：只绑回环、端口 0 回读、停止关闭监听并清空
/// 队列/令牌、重启后旧令牌被拒。测试只使用 127.0.0.1，不监听私网地址。
/// </summary>
public sealed class LanServerHostLifecycleTests
{
    [Fact]
    public async Task StartBindsLoopbackAndStopClosesListener()
    {
        await using var host = CreateHost(out _, out _);
        await host.StartAsync(IPAddress.Loopback, 0);
        try
        {
            Assert.True(host.IsRunning);
            Assert.NotNull(host.Port);
            Assert.InRange(host.Port!.Value, 1, 65535);
            Assert.StartsWith("http://127.0.0.1:", host.BaseUrl, StringComparison.Ordinal);

            using var client = new HttpClient
            {
                BaseAddress = new Uri(host.BaseUrl!),
                Timeout = TimeSpan.FromSeconds(5)
            };
            using var response = await client.GetAsync("/");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);

            var port = host.Port.Value;
            await host.StopAsync();

            Assert.False(host.IsRunning);
            Assert.Null(host.Port);
            Assert.Null(host.BaseUrl);

            using var probe = new TcpClient();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            await Assert.ThrowsAnyAsync<SocketException>(async () =>
                await probe.ConnectAsync(IPAddress.Loopback, port, timeout.Token));
        }
        finally
        {
            await host.StopAsync();
        }
    }

    [Fact]
    public async Task StopClearsQueueAndRevokesIssuedTokens()
    {
        await using var host = CreateHost(out var queue, out var auth);
        await host.StartAsync(IPAddress.Loopback, 0);
        try
        {
            var token = auth.IssueToken("测试手机").Token;
            queue.Enqueue("client-1", LanTestData.Parsed());
            Assert.Equal(1, queue.PendingCount);
            Assert.NotNull(auth.Validate(token));

            await host.StopAsync();

            Assert.Equal(0, queue.PendingCount);
            Assert.Null(queue.Get("client-1"));
            Assert.Null(auth.Validate(token));
        }
        finally
        {
            await host.StopAsync();
        }
    }

    [Fact]
    public async Task StartTwiceIsRejectedUntilStopped()
    {
        await using var host = CreateHost(out _, out _);
        await host.StartAsync(IPAddress.Loopback, 0);
        try
        {
            await Assert.ThrowsAsync<InvalidOperationException>(
                () => host.StartAsync(IPAddress.Loopback, 0));
            Assert.True(host.IsRunning);
        }
        finally
        {
            await host.StopAsync();
        }
    }

    [Fact]
    public async Task RestartRejectsTokenIssuedByPreviousRun()
    {
        await using var host = CreateHost(out _, out var auth);
        await host.StartAsync(IPAddress.Loopback, 0);
        var oldToken = auth.IssueToken("测试手机").Token;
        await host.StopAsync();

        await host.StartAsync(IPAddress.Loopback, 0);
        try
        {
            Assert.Null(auth.Validate(oldToken));

            using var client = new HttpClient
            {
                BaseAddress = new Uri(host.BaseUrl!),
                Timeout = TimeSpan.FromSeconds(5)
            };
            using var request = new HttpRequestMessage(HttpMethod.Get, "/api/health");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", oldToken);
            using var response = await client.SendAsync(request);

            Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
            var error = await LanTestJson.ReadAsync<LanErrorResponse>(response);
            Assert.Equal(LanErrorCodes.TokenInvalid, error!.Error);

            using var fresh = await client.GetAsync("/");
            Assert.Equal(HttpStatusCode.OK, fresh.StatusCode);
        }
        finally
        {
            await host.StopAsync();
        }
    }

    [Fact]
    public async Task StartRejectsPublicDocumentationAddressWithoutBinding()
    {
        await using var host = CreateHost(out _, out _);

        await Assert.ThrowsAsync<ArgumentException>(
            () => host.StartAsync(IPAddress.Parse("203.0.113.10"), 0));

        Assert.False(host.IsRunning);
        Assert.Null(host.Port);
        Assert.Null(host.BaseUrl);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(65536)]
    public async Task OutOfRangePortIsRejectedWithoutListening(int port)
    {
        await using var host = CreateHost(out _, out _);

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => host.StartAsync(IPAddress.Loopback, port));
        Assert.False(host.IsRunning);
        Assert.Null(host.Port);
    }

    [Theory]
    [InlineData("203.0.113.10")]
    [InlineData("8.8.8.8")]
    public async Task PublicIpIsRejectedWithoutBinding(string address)
    {
        await using var host = CreateHost(out _, out _);

        await Assert.ThrowsAsync<ArgumentException>(
            () => host.StartAsync(IPAddress.Parse(address), 0));
        Assert.False(host.IsRunning);
        Assert.Null(host.Port);
        Assert.Null(host.BaseUrl);
    }

    private static LanServerHost CreateHost(
        out LanPendingQueue queue,
        out LanAuthStore auth)
    {
        queue = new LanPendingQueue();
        auth = new LanAuthStore();
        var sessions = new MutableLanSessionSource(
            new LanSessionSnapshot(7, "测试场次", "2026-11-25", "active"));
        var parser = new InputParser(CatalogLoader.CreateBuiltIn());
        return new LanServerHost(
            new LanServerOptions { PcName = "HOST-TEST" },
            queue,
            auth,
            sessions,
            parser);
    }
}
