using System.Globalization;
using System.Net;
using System.Text.Json;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace HamCheckin.Native.LanServer;

/// <summary>
/// 7 个 HTTP 端点、Bearer 鉴权、限流与安全头（设计文档 6.1–6.4）。
/// 手机端不解析：预览与提交共用宿主注入的 InputParser。
/// </summary>
public static class LanEndpoints
{
    public const int MaxBodyBytes = 8 * 1024;

    private const int PairAttempts = 5;
    private const int PreviewPerMinute = 20;
    private const int SubmissionsPerMinute = 5;
    private const int PollsPerMinute = 90;
    private const int MaxClientSubmissionIdLength = 64;
    private const string ContentSecurityPolicy =
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
        "connect-src 'self'; frame-ancestors 'none'";

    private static readonly TimeSpan PairWindow = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan OneMinute = TimeSpan.FromMinutes(1);

    public static void Map(
        WebApplication app,
        LanServerOptions options,
        LanPendingQueue queue,
        LanAuthStore authStore,
        ILanSessionSource sessions,
        InputParser parser)
    {
        ArgumentNullException.ThrowIfNull(app);
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(queue);
        ArgumentNullException.ThrowIfNull(authStore);
        ArgumentNullException.ThrowIfNull(sessions);
        ArgumentNullException.ThrowIfNull(parser);

        var limiter = new LanRateLimiter();

        app.Use(async (context, next) =>
        {
            ApplySecurityHeaders(context);
            if (!IsHostAllowed(context))
            {
                // DNS 重绑定防护：Host 必须是本机实际绑定的地址与端口。
                await WriteErrorAsync(
                    context,
                    StatusCodes.Status403Forbidden,
                    LanErrorCodes.ForbiddenHost,
                    "请求的主机名不被接受。").ConfigureAwait(false);
                return;
            }

            if (IsCrossOrigin(context))
            {
                await WriteErrorAsync(
                    context,
                    StatusCodes.Status403Forbidden,
                    LanErrorCodes.ForbiddenOrigin,
                    "跨源请求已被拒绝。").ConfigureAwait(false);
                return;
            }

            try
            {
                await next().ConfigureAwait(false);
            }
            catch (BadHttpRequestException exception)
            {
                if (context.Response.HasStarted)
                {
                    throw;
                }

                var payloadTooLarge = exception.StatusCode == StatusCodes.Status413PayloadTooLarge;
                await WriteErrorAsync(
                    context,
                    payloadTooLarge
                        ? StatusCodes.Status413PayloadTooLarge
                        : StatusCodes.Status400BadRequest,
                    payloadTooLarge ? LanErrorCodes.PayloadTooLarge : LanErrorCodes.BadRequest,
                    payloadTooLarge ? "请求内容超过 8 KiB。" : "请求格式不正确。").ConfigureAwait(false);
            }
        });

        app.MapGet("/", async (HttpContext context) =>
        {
            await WriteAssetAsync(context, Assets.Html, "text/html; charset=utf-8").ConfigureAwait(false);
        });

        app.MapGet("/app.js", async (HttpContext context) =>
        {
            await WriteAssetAsync(context, Assets.Script, "text/javascript; charset=utf-8").ConfigureAwait(false);
        });

        app.MapGet("/app.css", async (HttpContext context) =>
        {
            await WriteAssetAsync(context, Assets.Style, "text/css; charset=utf-8").ConfigureAwait(false);
        });

        app.MapPost("/api/pair", async (HttpContext context) =>
        {
            var remoteIp = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
            if (!limiter.TryAcquire("pair:" + remoteIp, PairAttempts, PairWindow, out var retryAfter))
            {
                await WriteRateLimitedAsync(context, retryAfter).ConfigureAwait(false);
                return;
            }

            var (ok, request) = await TryReadJsonAsync<LanPairRequest>(context).ConfigureAwait(false);
            if (!ok || request is null)
            {
                await WriteErrorAsync(context, StatusCodes.Status400BadRequest,
                    LanErrorCodes.BadRequest, "请求格式不正确。").ConfigureAwait(false);
                return;
            }

            if (!authStore.VerifyPin(request.Pin))
            {
                await WriteErrorAsync(context, StatusCodes.Status401Unauthorized,
                    LanErrorCodes.BadPin, "PIN 不正确。").ConfigureAwait(false);
                return;
            }

            var issue = authStore.IssueToken(request.DeviceLabel);
            var current = sessions.CurrentSession;
            await WriteJsonAsync(context, StatusCodes.Status200OK, new LanPairResponse(
                issue.Token,
                issue.Session.PhoneId,
                options.PcName,
                current?.Name ?? string.Empty)).ConfigureAwait(false);
        });

        app.MapGet("/api/health", async (HttpContext context) =>
        {
            if (Authenticate(context, authStore) is null)
            {
                await WriteTokenInvalidAsync(context).ConfigureAwait(false);
                return;
            }

            var current = sessions.CurrentSession;
            await WriteJsonAsync(context, StatusCodes.Status200OK, new LanHealthResponse(
                options.PcName,
                current?.Name ?? string.Empty,
                current?.Status ?? "none",
                current?.Date ?? string.Empty,
                RuntimeOptions.Now)).ConfigureAwait(false);
        });

        app.MapPost("/api/preview", async (HttpContext context) =>
        {
            var session = Authenticate(context, authStore);
            if (session is null)
            {
                await WriteTokenInvalidAsync(context).ConfigureAwait(false);
                return;
            }

            if (!limiter.TryAcquire("preview:" + session.PhoneId, PreviewPerMinute, OneMinute, out var retryAfter))
            {
                await WriteRateLimitedAsync(context, retryAfter).ConfigureAwait(false);
                return;
            }

            var (ok, request) = await TryReadJsonAsync<LanPreviewRequest>(context).ConfigureAwait(false);
            if (!ok || request is null || string.IsNullOrWhiteSpace(request.Text))
            {
                await WriteErrorAsync(context, StatusCodes.Status400BadRequest,
                    LanErrorCodes.BadRequest, "请输入点名原文。").ConfigureAwait(false);
                return;
            }

            var parsed = parser.Parse(request.Text);
            await WriteJsonAsync(context, StatusCodes.Status200OK, new LanPreviewResponse(
                parsed.Callsign.Value,
                parsed.Qth.Value,
                parsed.Device.Value,
                parsed.Antenna.Value,
                parsed.Power.Value,
                parsed.Signal.Value,
                parsed.Unmatched,
                parsed.CanSubmit)).ConfigureAwait(false);
        });

        app.MapPost("/api/submissions", async (HttpContext context) =>
        {
            var session = Authenticate(context, authStore);
            if (session is null)
            {
                await WriteTokenInvalidAsync(context).ConfigureAwait(false);
                return;
            }

            if (!limiter.TryAcquire("submit:" + session.PhoneId, SubmissionsPerMinute, OneMinute, out var retryAfter))
            {
                await WriteRateLimitedAsync(context, retryAfter).ConfigureAwait(false);
                return;
            }

            var (ok, request) = await TryReadJsonAsync<LanSubmissionRequest>(context).ConfigureAwait(false);
            if (!ok || request is null)
            {
                await WriteErrorAsync(context, StatusCodes.Status400BadRequest,
                    LanErrorCodes.BadRequest, "请求格式不正确。").ConfigureAwait(false);
                return;
            }

            var clientSubmissionId = request.ClientSubmissionId?.Trim() ?? string.Empty;
            if (clientSubmissionId.Length is 0 or > MaxClientSubmissionIdLength)
            {
                await WriteErrorAsync(context, StatusCodes.Status400BadRequest,
                    LanErrorCodes.BadRequest, "提交编号无效。").ConfigureAwait(false);
                return;
            }

            var parsed = parser.Parse(request.RawText);
            if (!parsed.CanSubmit)
            {
                await WriteErrorAsync(context, StatusCodes.Status400BadRequest,
                    LanErrorCodes.NoCallsign, "没识别到呼号，请补充。").ConfigureAwait(false);
                return;
            }

            var current = sessions.CurrentSession;
            if (current is null || !current.IsActive)
            {
                await WriteErrorAsync(context, StatusCodes.Status409Conflict,
                    LanErrorCodes.SessionEnded, "本场已结束，请找主持人。").ConfigureAwait(false);
                return;
            }

            var enqueued = queue.Enqueue(clientSubmissionId, parsed);
            switch (enqueued.Status)
            {
                case LanEnqueueStatus.Full:
                    await WriteErrorAsync(context, StatusCodes.Status503ServiceUnavailable,
                        LanErrorCodes.QueueFull, "队列已满，请主持人先处理待确认条目。").ConfigureAwait(false);
                    return;
                case LanEnqueueStatus.Existing when enqueued.Item is not null:
                    await WriteStatusAsync(context, StatusCodes.Status200OK, enqueued.Item).ConfigureAwait(false);
                    return;
                case LanEnqueueStatus.Created when enqueued.Item is not null:
                    await WriteJsonAsync(context, StatusCodes.Status201Created, new LanSubmissionAcceptedResponse(
                        enqueued.Item.ClientSubmissionId,
                        enqueued.Item.State.ToWireName(),
                        enqueued.Item.ArrivalSeq,
                        enqueued.Position)).ConfigureAwait(false);
                    return;
                default:
                    throw new InvalidOperationException("待确认队列返回了未知结果。");
            }
        });

        app.MapGet("/api/submissions/{clientSubmissionId}", async (HttpContext context, string clientSubmissionId) =>
        {
            var session = Authenticate(context, authStore);
            if (session is null)
            {
                await WriteTokenInvalidAsync(context).ConfigureAwait(false);
                return;
            }

            if (!limiter.TryAcquire("poll:" + session.PhoneId, PollsPerMinute, OneMinute, out var retryAfter))
            {
                await WriteRateLimitedAsync(context, retryAfter).ConfigureAwait(false);
                return;
            }

            // 路由值可能为空/超长，先按与提交端点相同的长度约束过滤，避免 500。
            var submissionId = clientSubmissionId?.Trim() ?? string.Empty;
            if (submissionId.Length is 0 or > MaxClientSubmissionIdLength)
            {
                await WriteErrorAsync(context, StatusCodes.Status404NotFound,
                    LanErrorCodes.Unknown, "没有找到这条提交。").ConfigureAwait(false);
                return;
            }

            var item = queue.Get(submissionId);
            if (item is null)
            {
                await WriteErrorAsync(context, StatusCodes.Status404NotFound,
                    LanErrorCodes.Unknown, "没有找到这条提交。").ConfigureAwait(false);
                return;
            }

            await WriteStatusAsync(context, StatusCodes.Status200OK, item).ConfigureAwait(false);
        });
    }

    private static void ApplySecurityHeaders(HttpContext context)
    {
        var headers = context.Response.Headers;
        headers["X-Content-Type-Options"] = "nosniff";
        headers["Referrer-Policy"] = "no-referrer";
        headers["Content-Security-Policy"] = ContentSecurityPolicy;
        // API 响应绝不缓存；静态页面每次回源校验，避免手机端留住旧脚本。
        headers["Cache-Control"] = context.Request.Path.StartsWithSegments("/api")
            ? "no-store"
            : "no-cache";
    }

    /// <summary>
    /// DNS 重绑定防护：请求 Host 必须与本连接实际命中的本地地址和端口一致。
    /// 回环测试与私网绑定都按数值地址访问，因此不接受域名或任意端口。
    /// </summary>
    private static bool IsHostAllowed(HttpContext context)
    {
        var localAddress = context.Connection.LocalIpAddress;
        if (localAddress is null)
        {
            return false;
        }

        var host = context.Request.Host;
        if (string.IsNullOrEmpty(host.Host))
        {
            return false;
        }

        var hostText = host.Host;
        if (hostText.Length > 2 && hostText[0] == '[' && hostText[^1] == ']')
        {
            hostText = hostText[1..^1];
        }
        if (!IPAddress.TryParse(hostText, out var requestedAddress))
        {
            return false;
        }

        var requestedPort = host.Port ?? (context.Request.IsHttps ? 443 : 80);
        return requestedPort == context.Connection.LocalPort
            && NormalizeAddress(requestedAddress).Equals(
                NormalizeAddress(localAddress));
    }

    private static IPAddress NormalizeAddress(IPAddress address) =>
        address.IsIPv4MappedToIPv6 ? address.MapToIPv4() : address;

    private static bool IsCrossOrigin(HttpContext context)
    {
        var origin = context.Request.Headers["Origin"].ToString();
        if (string.IsNullOrEmpty(origin))
        {
            return false;
        }

        var self = $"{context.Request.Scheme}://{context.Request.Host.Value}";
        return !string.Equals(origin.TrimEnd('/'), self.TrimEnd('/'), StringComparison.OrdinalIgnoreCase);
    }

    private static LanTokenSession? Authenticate(HttpContext context, LanAuthStore authStore)
    {
        const string prefix = "Bearer ";
        var header = context.Request.Headers["Authorization"].ToString();
        if (!header.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return authStore.Validate(header[prefix.Length..].Trim());
    }

    /// <summary>
    /// 只接受 application/json；缺少/错误内容类型、JSON 语法错误和读取中断都按
    /// 请求不合法处理，由调用方回 400 bad_request（不冒到 500）。请求体超限的 413 例外，
    /// 交由外层中间件回 payload_too_large。
    /// </summary>
    private static async Task<(bool Ok, T? Value)> TryReadJsonAsync<T>(HttpContext context)
        where T : class
    {
        if (!context.Request.HasJsonContentType())
        {
            return (false, null);
        }

        try
        {
            var value = await context.Request
                .ReadFromJsonAsync<T>(context.RequestAborted)
                .ConfigureAwait(false);
            return (value is not null, value);
        }
        catch (JsonException)
        {
            return (false, null);
        }
        catch (BadHttpRequestException)
        {
            // 派生自 IOException；请求体超限（413）必须冒到外层中间件，不能降级成 400。
            throw;
        }
        catch (IOException)
        {
            return (false, null);
        }
    }

    private static Task WriteTokenInvalidAsync(HttpContext context) =>
        WriteErrorAsync(context, StatusCodes.Status401Unauthorized,
            LanErrorCodes.TokenInvalid, "与电脑的连接已失效。");

    private static async Task WriteRateLimitedAsync(HttpContext context, TimeSpan retryAfter)
    {
        var seconds = Math.Max(1, (int)Math.Ceiling(retryAfter.TotalSeconds));
        context.Response.Headers["Retry-After"] =
            seconds.ToString(CultureInfo.InvariantCulture);
        await WriteErrorAsync(context, StatusCodes.Status429TooManyRequests,
            LanErrorCodes.RateLimited, "操作太快，请稍等。").ConfigureAwait(false);
    }

    private static async Task WriteErrorAsync(
        HttpContext context,
        int statusCode,
        string error,
        string message)
    {
        if (statusCode == StatusCodes.Status401Unauthorized)
        {
            context.Response.Headers["WWW-Authenticate"] = "Bearer";
        }

        await WriteJsonAsync(context, statusCode, new LanErrorResponse(error, message))
            .ConfigureAwait(false);
    }

    private static Task WriteStatusAsync(HttpContext context, int statusCode, LanPendingItem item) =>
        WriteJsonAsync(context, statusCode, new LanSubmissionStatusResponse(
            item.State.ToWireName(),
            item.SequenceNo,
            string.IsNullOrEmpty(item.Reason) ? null : item.Reason,
            item.DecidedAt));

    private static async Task WriteJsonAsync<T>(HttpContext context, int statusCode, T payload)
    {
        context.Response.StatusCode = statusCode;
        context.Response.ContentType = "application/json; charset=utf-8";
        await context.Response.WriteAsJsonAsync(payload, context.RequestAborted)
            .ConfigureAwait(false);
    }

    private static async Task WriteAssetAsync(HttpContext context, byte[] content, string contentType)
    {
        context.Response.ContentType = contentType;
        context.Response.ContentLength = content.Length;
        await context.Response.Body.WriteAsync(content, context.RequestAborted)
            .ConfigureAwait(false);
    }

    private static class Assets
    {
        public static byte[] Html { get; } = Load("mobile.html");
        public static byte[] Script { get; } = Load("app.js");
        public static byte[] Style { get; } = Load("app.css");

        private static byte[] Load(string name)
        {
            var resourceName = $"HamCheckin.Native.LanServer.Assets.{name}";
            using var stream = typeof(Assets).Assembly.GetManifestResourceStream(resourceName)
                ?? throw new InvalidOperationException($"缺少内嵌资源 {resourceName}。");
            using var buffer = new MemoryStream();
            stream.CopyTo(buffer);
            return buffer.ToArray();
        }
    }
}
