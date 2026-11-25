using System.Net;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace HamCheckin.Native.LanServer;

public sealed record LanServerOptions
{
    public string PcName { get; init; } = Environment.MachineName;
}

/// <summary>
/// 局域网收件服务宿主。默认不启动；只有显式调用 StartAsync 才绑定
/// 一个具体地址。绝不使用 IPAddress.Any / 通配前缀，也不发起任何外部连接。
/// </summary>
public sealed class LanServerHost : IAsyncDisposable
{
    private static readonly TimeSpan ExpiryScanInterval = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan ShutdownTimeout = TimeSpan.FromSeconds(2);

    private readonly LanServerOptions _options;
    private readonly LanPendingQueue _queue;
    private readonly LanAuthStore _authStore;
    private readonly ILanSessionSource _sessions;
    private readonly InputParser _parser;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private WebApplication? _app;
    private CancellationTokenSource? _expiryScanCancellation;
    private Task? _expiryScanTask;

    public LanServerHost(
        LanServerOptions options,
        LanPendingQueue queue,
        LanAuthStore authStore,
        ILanSessionSource sessions,
        InputParser parser)
    {
        ArgumentNullException.ThrowIfNull(options);
        _options = options with
        {
            PcName = string.IsNullOrWhiteSpace(options.PcName)
                ? Environment.MachineName
                : options.PcName.Trim()
        };
        _queue = queue ?? throw new ArgumentNullException(nameof(queue));
        _authStore = authStore ?? throw new ArgumentNullException(nameof(authStore));
        _sessions = sessions ?? throw new ArgumentNullException(nameof(sessions));
        _parser = parser ?? throw new ArgumentNullException(nameof(parser));
    }

    public bool IsRunning => _app is not null;

    /// <summary>实际绑定端口；端口传 0 时由 Kestrel 分配后回读。</summary>
    public int? Port { get; private set; }

    /// <summary>供 PC 页面显示的 URL，例如 http://192.168.1.23:8731。</summary>
    public string? BaseUrl { get; private set; }

    public async Task StartAsync(
        IPAddress address,
        int port,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(address);
        if (address.Equals(IPAddress.Any) || address.Equals(IPAddress.IPv6Any))
        {
            throw new ArgumentException("只能绑定具体地址，不能使用通配地址。", nameof(address));
        }
        if (!IPAddress.IsLoopback(address) && !LanBindingResolver.IsPrivateIpv4(address))
        {
            throw new ArgumentException(
                "只能绑定回环或 RFC1918 私网 IPv4 地址。", nameof(address));
        }
        if (port is < 0 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(port), "端口必须在 0 到 65535 之间。");
        }

        // 启动/停止串行化：避免并发 Start 双重绑定，或 Stop 与 Start 交错泄漏 Kestrel。
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_app is not null)
            {
                throw new InvalidOperationException("收件服务已经在运行。");
            }

            // 每次启动重新生成 PIN，旧令牌随之全部失效（设计文档 3.1 / 3.3）。
            _authStore.RotatePin();

            var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions
            {
                ContentRootPath = AppContext.BaseDirectory,
                EnvironmentName = Environments.Production
            });
            builder.Logging.ClearProviders();
            builder.WebHost.UseSetting(WebHostDefaults.PreventHostingStartupKey, "true");
            builder.WebHost.UseSetting(WebHostDefaults.ServerUrlsKey, string.Empty);
            builder.WebHost.ConfigureKestrel(kestrel =>
            {
                kestrel.AddServerHeader = false;
                kestrel.Limits.MaxRequestBodySize = LanEndpoints.MaxBodyBytes;
                kestrel.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(10);
                kestrel.Listen(address, port);
            });

            var app = builder.Build();
            LanEndpoints.Map(app, _options, _queue, _authStore, _sessions, _parser);
            try
            {
                await app.StartAsync(cancellationToken).ConfigureAwait(false);
                var boundPort = ResolveBoundPort(app, port);
                var scanCancellation = new CancellationTokenSource();
                var scanTask = ScanExpiredAsync(scanCancellation.Token);
                _app = app;
                Port = boundPort;
                BaseUrl = BuildBaseUrl(address, boundPort);
                _expiryScanCancellation = scanCancellation;
                _expiryScanTask = scanTask;
            }
            catch
            {
                await app.DisposeAsync().ConfigureAwait(false);
                throw;
            }
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    /// <summary>
    /// 先关闭监听（手机立刻得到连接拒绝），再丢弃队列、吊销全部令牌。
    /// </summary>
    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var app = _app;
            if (app is null)
            {
                return;
            }

            _app = null;
            if (_expiryScanCancellation is not null)
            {
                _expiryScanCancellation.Cancel();
                if (_expiryScanTask is not null)
                {
                    await _expiryScanTask.ConfigureAwait(false);
                }

                _expiryScanCancellation.Dispose();
                _expiryScanCancellation = null;
                _expiryScanTask = null;
            }

            using var timeout = new CancellationTokenSource(ShutdownTimeout);
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken, timeout.Token);
            try
            {
                await app.StopAsync(linked.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // 2 秒上限到点即继续清理，绝不让关窗等待。
            }
            finally
            {
                await app.DisposeAsync().ConfigureAwait(false);
                _queue.Clear();
                _authStore.RevokeAll();
                Port = null;
                BaseUrl = null;
            }
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    public async ValueTask DisposeAsync() => await StopAsync().ConfigureAwait(false);

    private async Task ScanExpiredAsync(CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(ExpiryScanInterval);
        try
        {
            while (await timer.WaitForNextTickAsync(cancellationToken).ConfigureAwait(false))
            {
                _queue.ExpireOverdue();
            }
        }
        catch (OperationCanceledException)
        {
            // 正常停止路径。
        }
    }

    private static int ResolveBoundPort(WebApplication app, int requestedPort)
    {
        var feature = app.Services.GetRequiredService<IServer>()
            .Features.Get<IServerAddressesFeature>();
        foreach (var address in feature?.Addresses ?? Array.Empty<string>())
        {
            if (Uri.TryCreate(address, UriKind.Absolute, out var uri) && uri.Port > 0)
            {
                return uri.Port;
            }
        }

        if (requestedPort > 0)
        {
            return requestedPort;
        }

        throw new InvalidOperationException("无法读取 Kestrel 实际绑定端口。");
    }

    private static string BuildBaseUrl(IPAddress address, int port) =>
        new UriBuilder(Uri.UriSchemeHttp, address.ToString(), port)
            .Uri.GetLeftPart(UriPartial.Authority);
}
