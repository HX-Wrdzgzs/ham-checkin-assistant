using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.LanServer;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Tests;

/// <summary>
/// S2 回环集成测试（设计 6/8.2）：真实 Kestrel 绑定 127.0.0.1:0，HttpClient
/// 走真实管道验证 7 个端点、Bearer、CSP/安全头、8 KiB 上限、跨源拒绝、
/// 待确认零写入、批准幂等与场次结束。只使用临时 SQLite 根目录。
/// </summary>
[SuppressMessage("Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "xUnit invokes IAsyncLifetime.DisposeAsync after every test instance.")]
public sealed class LanServerIntegrationTests : IAsyncLifetime
{
    private const string ExpectedCsp =
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
        "connect-src 'self'; frame-ancestors 'none'";

    private readonly string _root = Path.Combine(
        Path.GetTempPath(), $"ham-lan-server-{Guid.NewGuid():N}");

    private NativeStore _store = null!;
    private SessionInfo _session = null!;
    private LanPendingQueue _queue = null!;
    private LanAuthStore _auth = null!;
    private MutableLanSessionSource _sessions = null!;
    private InputParser _parser = null!;
    private LanServerHost _host = null!;
    private HttpClient _http = null!;

    public async Task InitializeAsync()
    {
        var dataDirectory = Path.Combine(_root, "data");
        Directory.CreateDirectory(dataDirectory);
        _store = new NativeStore(Path.Combine(dataDirectory, "ham_checkin_native.db"));
        await _store.InitializeAsync();
        _session = await _store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 25));

        _queue = new LanPendingQueue();
        _auth = new LanAuthStore();
        _sessions = new MutableLanSessionSource(new LanSessionSnapshot(
            _session.Id, _session.Name, _session.Date, _session.Status));
        _parser = new InputParser(CatalogLoader.CreateBuiltIn());
        _host = new LanServerHost(
            new LanServerOptions { PcName = "LAN-TEST-PC" },
            _queue,
            _auth,
            _sessions,
            _parser);

        await _host.StartAsync(IPAddress.Loopback, 0);
        _http = new HttpClient
        {
            BaseAddress = new Uri(_host.BaseUrl!),
            Timeout = TimeSpan.FromSeconds(15)
        };
    }

    public async Task DisposeAsync()
    {
        _http?.Dispose();
        if (_host is not null)
        {
            await _host.DisposeAsync();
        }

        if (_store is not null)
        {
            await _store.DisposeAsync();
        }

        SqliteConnection.ClearAllPools();
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    [Fact]
    public async Task PairRequiresPinAndHealthRequiresBearerToken()
    {
        var wrongPin = _auth.Pin == "000000" ? "000001" : "000000";
        using (var wrong = await LanTestJson.PostAsync(
            _http, "/api/pair", new LanPairRequest(wrongPin, "测试手机")))
        {
            Assert.Equal(HttpStatusCode.Unauthorized, wrong.StatusCode);
            Assert.Equal("Bearer", wrong.Headers.WwwAuthenticate.ToString());
            var error = await LanTestJson.ReadAsync<LanErrorResponse>(wrong);
            Assert.Equal(LanErrorCodes.BadPin, error!.Error);
        }

        using var paired = await LanTestJson.PostAsync(
            _http, "/api/pair", new LanPairRequest(_auth.Pin, "测试手机"));
        Assert.Equal(HttpStatusCode.OK, paired.StatusCode);
        var pair = await LanTestJson.ReadAsync<LanPairResponse>(paired);
        Assert.NotNull(pair);
        Assert.False(string.IsNullOrWhiteSpace(pair!.Token));
        Assert.StartsWith("phone-", pair.PhoneId, StringComparison.Ordinal);
        Assert.Equal("LAN-TEST-PC", pair.PcName);
        Assert.Equal(_session.Name, pair.SessionName);

        using (var missing = await _http.GetAsync("/api/health"))
        {
            Assert.Equal(HttpStatusCode.Unauthorized, missing.StatusCode);
            Assert.Equal(
                LanErrorCodes.TokenInvalid,
                (await LanTestJson.ReadAsync<LanErrorResponse>(missing))!.Error);
        }

        using (var invalidRequest = new HttpRequestMessage(HttpMethod.Get, "/api/health"))
        {
            invalidRequest.Headers.Authorization =
                new AuthenticationHeaderValue("Bearer", "not-a-real-token");
            using var invalid = await _http.SendAsync(invalidRequest);
            Assert.Equal(HttpStatusCode.Unauthorized, invalid.StatusCode);
            Assert.Equal(
                LanErrorCodes.TokenInvalid,
                (await LanTestJson.ReadAsync<LanErrorResponse>(invalid))!.Error);
        }

        using var healthRequest = new HttpRequestMessage(HttpMethod.Get, "/api/health");
        healthRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", pair.Token);
        using var health = await _http.SendAsync(healthRequest);
        Assert.Equal(HttpStatusCode.OK, health.StatusCode);
        var payload = await LanTestJson.ReadAsync<LanHealthResponse>(health);
        Assert.NotNull(payload);
        Assert.Equal("LAN-TEST-PC", payload!.PcName);
        Assert.Equal(_session.Name, payload.SessionName);
        Assert.Equal("active", payload.SessionStatus);
        Assert.Equal(_session.Date, payload.SessionDate);
    }

    [Fact]
    public async Task PairAttemptsAreRateLimitedAfterFiveFailures()
    {
        var wrongPin = _auth.Pin == "000000" ? "000001" : "000000";
        for (var attempt = 0; attempt < 5; attempt++)
        {
            using var failed = await LanTestJson.PostAsync(
                _http, "/api/pair", new LanPairRequest(wrongPin, "测试手机"));
            Assert.Equal(HttpStatusCode.Unauthorized, failed.StatusCode);
        }

        using var blocked = await LanTestJson.PostAsync(
            _http, "/api/pair", new LanPairRequest(_auth.Pin, "测试手机"));

        Assert.Equal(HttpStatusCode.TooManyRequests, blocked.StatusCode);
        Assert.True(blocked.Headers.Contains("Retry-After"));
        Assert.Equal(
            LanErrorCodes.RateLimited,
            (await LanTestJson.ReadAsync<LanErrorResponse>(blocked))!.Error);
    }

    [Fact]
    public async Task PreviewReturnsServerSideFieldsAndHandlesBlankOrMissingCallsign()
    {
        var token = await PairAsync();

        using var valid = await LanTestJson.PostAsync(
            _http,
            "/api/preview",
            new LanPreviewRequest("ba4rll njxw pd780 4.2m 5w"),
            token);
        Assert.Equal(HttpStatusCode.OK, valid.StatusCode);
        var preview = await LanTestJson.ReadAsync<LanPreviewResponse>(valid);
        Assert.NotNull(preview);
        Assert.Equal("BA4RLL", preview!.Callsign);
        Assert.Equal("江苏省南京市玄武区", preview.Qth);
        Assert.Equal("海能达 PD-780", preview.Device);
        Assert.Equal("4.2米玻璃钢", preview.Antenna);
        Assert.Equal("5W", preview.Power);
        Assert.True(preview.CanSubmit);
        Assert.Empty(preview.Unmatched);

        using var noCallsign = await LanTestJson.PostAsync(
            _http, "/api/preview", new LanPreviewRequest("无呼号测试"), token);
        Assert.Equal(HttpStatusCode.OK, noCallsign.StatusCode);
        var noCallsignPayload = await LanTestJson.ReadAsync<LanPreviewResponse>(noCallsign);
        Assert.False(noCallsignPayload!.CanSubmit);
        Assert.True(string.IsNullOrEmpty(noCallsignPayload.Callsign));

        using var blank = await LanTestJson.PostAsync(
            _http, "/api/preview", new LanPreviewRequest("   "), token);
        Assert.Equal(HttpStatusCode.BadRequest, blank.StatusCode);
        Assert.Equal(
            LanErrorCodes.BadRequest,
            (await LanTestJson.ReadAsync<LanErrorResponse>(blank))!.Error);
    }

    [Fact]
    public async Task PreviewRejectsBodyLargerThanEightKilobytesWith413()
    {
        var token = await PairAsync();

        using var response = await LanTestJson.PostAsync(
            _http,
            "/api/preview",
            new LanPreviewRequest(new string('a', 9000)),
            token);

        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
        var error = await LanTestJson.ReadAsync<LanErrorResponse>(response);
        Assert.Equal(LanErrorCodes.PayloadTooLarge, error!.Error);
    }

    [Fact]
    public async Task NonJsonContentTypeIsRejectedWith400BadRequest()
    {
        var token = await PairAsync();
        using var request = new HttpRequestMessage(HttpMethod.Post, "/api/preview")
        {
            Content = new StringContent("{\"text\":\"ba4rll\"}", Encoding.UTF8, "text/plain")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);

        using var response = await _http.SendAsync(request);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(
            LanErrorCodes.BadRequest,
            (await LanTestJson.ReadAsync<LanErrorResponse>(response))!.Error);
    }

    [Fact]
    public async Task ForeignHostHeaderIsRejectedWith403ForbiddenHost()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/api/health");
        request.Headers.Host = "evil.example";

        using var response = await _http.SendAsync(request);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal(
            LanErrorCodes.ForbiddenHost,
            (await LanTestJson.ReadAsync<LanErrorResponse>(response))!.Error);
    }

    [Fact]
    public async Task BlankOrOversizedStatusIdReturns404()
    {
        var token = await PairAsync();

        using (var blank = await GetWithTokenAsync("/api/submissions/%20", token))
        {
            Assert.Equal(HttpStatusCode.NotFound, blank.StatusCode);
            Assert.Equal(
                LanErrorCodes.Unknown,
                (await LanTestJson.ReadAsync<LanErrorResponse>(blank))!.Error);
        }

        var oversized = new string('x', 65);
        using var tooLong = await GetWithTokenAsync("/api/submissions/" + oversized, token);
        Assert.Equal(HttpStatusCode.NotFound, tooLong.StatusCode);
        Assert.Equal(
            LanErrorCodes.Unknown,
            (await LanTestJson.ReadAsync<LanErrorResponse>(tooLong))!.Error);
    }

    [Fact]
    public async Task CrossOriginRequestIsForbiddenBeforeAuthentication()
    {
        var token = await PairAsync();
        var selfOrigin = $"http://127.0.0.1:{_host.Port!.Value}";

        using (var sameOriginRequest = LanTestJson.JsonRequest(
            HttpMethod.Post, "/api/preview", new LanPreviewRequest("ba4rll"), token))
        {
            sameOriginRequest.Headers.Add("Origin", selfOrigin);
            using var sameOrigin = await _http.SendAsync(sameOriginRequest);
            Assert.Equal(HttpStatusCode.OK, sameOrigin.StatusCode);
        }

        using var foreignRequest = LanTestJson.JsonRequest(
            HttpMethod.Post, "/api/preview", new LanPreviewRequest("ba4rll"), token);
        foreignRequest.Headers.Add("Origin", "http://evil.example");
        using var foreign = await _http.SendAsync(foreignRequest);

        Assert.Equal(HttpStatusCode.Forbidden, foreign.StatusCode);
        Assert.Equal(
            LanErrorCodes.ForbiddenOrigin,
            (await LanTestJson.ReadAsync<LanErrorResponse>(foreign))!.Error);
    }

    [Fact]
    public async Task SubmissionStaysPendingUntilApprovedAndIsIdempotent()
    {
        var token = await PairAsync();
        var request = new LanSubmissionRequest(
            "client-abc-1", "ba4rll njxw pd780 4.2m 5w");

        using var created = await LanTestJson.PostAsync(
            _http, "/api/submissions", request, token);
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        var accepted = await LanTestJson.ReadAsync<LanSubmissionAcceptedResponse>(created);
        Assert.NotNull(accepted);
        Assert.Equal("client-abc-1", accepted!.SubmissionId);
        Assert.Equal("pending", accepted.State);
        Assert.Equal(1, accepted.ArrivalSeq);
        Assert.Equal(1, accepted.Position);
        Assert.Equal(0L, await CountCheckinsAsync());
        Assert.Equal(1, _queue.PendingCount);

        for (var retry = 0; retry < 2; retry++)
        {
            using var repeated = await LanTestJson.PostAsync(
                _http, "/api/submissions", request, token);
            Assert.Equal(HttpStatusCode.OK, repeated.StatusCode);
            var repeatedPayload = await LanTestJson.ReadAsync<LanSubmissionStatusResponse>(repeated);
            Assert.Equal("pending", repeatedPayload!.State);
            Assert.Equal(accepted.ArrivalSeq, _queue.Get("client-abc-1")!.ArrivalSeq);
            Assert.Equal(1, _queue.PendingCount);
            Assert.Equal(0L, await CountCheckinsAsync());
        }

        var approvals = new LanApprovalService(_store, _queue, _sessions);
        var approval = await approvals.ApproveAsync("client-abc-1");
        Assert.Equal(LanApprovalStatus.Approved, approval.Status);
        Assert.NotNull(approval.Checkin);
        Assert.Equal(LanSources.Lan, approval.Checkin!.Source);
        Assert.Equal(_session.NextSequence, approval.Checkin.SequenceNo);
        Assert.Equal(1L, await CountCheckinsAsync());

        var readback = await _store.GetCheckinBySubmissionIdAsync(
            $"lan-{_session.Id}-client-abc-1");
        Assert.NotNull(readback);
        Assert.Equal(approval.Checkin.Id, readback!.Id);

        var second = await approvals.ApproveAsync("client-abc-1");
        Assert.Equal(LanApprovalStatus.NotPending, second.Status);
        Assert.Null(second.Checkin);
        Assert.Equal(1L, await CountCheckinsAsync());

        using var status = await GetWithTokenAsync("/api/submissions/client-abc-1", token);
        Assert.Equal(HttpStatusCode.OK, status.StatusCode);
        var statusPayload = await LanTestJson.ReadAsync<LanSubmissionStatusResponse>(status);
        Assert.Equal("approved", statusPayload!.State);
        Assert.Equal(approval.Checkin.SequenceNo, statusPayload.SequenceNo);
        Assert.NotNull(statusPayload.DecidedAt);
        Assert.Null(statusPayload.Reason);

        using var unknown = await GetWithTokenAsync("/api/submissions/does-not-exist", token);
        Assert.Equal(HttpStatusCode.NotFound, unknown.StatusCode);
        Assert.Equal(
            LanErrorCodes.Unknown,
            (await LanTestJson.ReadAsync<LanErrorResponse>(unknown))!.Error);
    }

    [Fact]
    public async Task ApprovalWhileLeaseHeldReturnsBusyAndWritesNothing()
    {
        Assert.Equal(
            LanEnqueueStatus.Created,
            _queue.Enqueue("client-busy", LanTestData.Parsed()).Status);
        Assert.True(_queue.TryBeginApproval("client-busy", out var lease));
        var approvals = new LanApprovalService(_store, _queue, _sessions);
        try
        {
            var busy = await approvals.ApproveAsync("client-busy");

            Assert.Equal(LanApprovalStatus.Busy, busy.Status);
            Assert.Null(busy.Checkin);
            Assert.Equal(0L, await CountCheckinsAsync());
            Assert.Equal(LanSubmissionState.Pending, _queue.Get("client-busy")!.State);
        }
        finally
        {
            Assert.True(_queue.ReleaseApproval("client-busy", lease));
        }

        var retried = await approvals.ApproveAsync("client-busy");
        Assert.Equal(LanApprovalStatus.Approved, retried.Status);
        Assert.Equal(1L, await CountCheckinsAsync());
    }

    [Fact]
    public async Task ApprovalRetryAfterWriteCommittedReusesExistingRow()
    {
        var start = DateTimeOffset.UtcNow;
        var clockCalls = 0;
        // 第 3 次读时钟（TryApprove）时让 30 秒批准租约正好过期，模拟写库成功但
        // 队列终态未标记；下一次批准应读回同一行而不是重复插入。
        var queue = new LanPendingQueue(
            () => clockCalls++ < 2 ? start : start.AddSeconds(31));
        Assert.Equal(
            LanEnqueueStatus.Created,
            queue.Enqueue("client-write-committed", LanTestData.Parsed()).Status);
        var approvals = new LanApprovalService(_store, queue, _sessions);

        var result = await approvals.ApproveAsync("client-write-committed");

        Assert.Equal(LanApprovalStatus.WriteCommitted, result.Status);
        Assert.NotNull(result.Checkin);
        Assert.Equal(1L, await CountCheckinsAsync());
        Assert.Equal(
            LanSubmissionState.Pending,
            queue.Get("client-write-committed")!.State);

        var retried = await approvals.ApproveAsync("client-write-committed");
        Assert.Equal(LanApprovalStatus.Approved, retried.Status);
        Assert.Equal(result.Checkin!.Id, retried.Checkin!.Id);
        Assert.Equal(1L, await CountCheckinsAsync());
    }

    [Fact]
    public async Task SubmissionAndApprovalAfterSessionEndedReturnConflictAndWriteNothing()
    {
        var token = await PairAsync();
        Assert.Equal(
            LanEnqueueStatus.Created,
            _queue.Enqueue("pending-before-end", LanTestData.Parsed()).Status);

        await _store.SetSessionStatusAsync(_session.Id, "ended");
        _sessions.CurrentSession = _sessions.CurrentSession! with { Status = "ended" };

        using var submit = await LanTestJson.PostAsync(
            _http,
            "/api/submissions",
            new LanSubmissionRequest("client-after-end", "ba4rll"),
            token);
        Assert.Equal(HttpStatusCode.Conflict, submit.StatusCode);
        Assert.Equal(
            LanErrorCodes.SessionEnded,
            (await LanTestJson.ReadAsync<LanErrorResponse>(submit))!.Error);
        Assert.Equal(0L, await CountCheckinsAsync());
        Assert.Equal(1, _queue.PendingCount);

        var approval = await new LanApprovalService(_store, _queue, _sessions)
            .ApproveAsync("pending-before-end");
        Assert.Equal(LanApprovalStatus.SessionEnded, approval.Status);
        Assert.Null(approval.Checkin);
        Assert.Equal(
            LanSubmissionState.Pending,
            _queue.Get("pending-before-end")!.State);
        Assert.Equal(0L, await CountCheckinsAsync());
    }

    [Fact]
    public async Task QueueFullReturns503WithoutWriting()
    {
        var token = await PairAsync();
        var parsed = LanTestData.Parsed();
        for (var index = 0; index < LanPendingQueue.PendingCapacity; index++)
        {
            Assert.Equal(
                LanEnqueueStatus.Created,
                _queue.Enqueue($"fill-{index}", parsed).Status);
        }

        using var response = await LanTestJson.PostAsync(
            _http,
            "/api/submissions",
            new LanSubmissionRequest("client-overflow", "ba4rll"),
            token);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Equal(
            LanErrorCodes.QueueFull,
            (await LanTestJson.ReadAsync<LanErrorResponse>(response))!.Error);
        Assert.Equal(50, _queue.PendingCount);
        Assert.Equal(0L, await CountCheckinsAsync());
    }

    [Fact]
    public async Task StaticAssetsAndApiCarrySecurityHeadersWithoutCorsOrServer()
    {
        using (var root = await _http.GetAsync("/"))
        {
            Assert.Equal(HttpStatusCode.OK, root.StatusCode);
            Assert.Equal("text/html", root.Content.Headers.ContentType?.MediaType);
            Assert.Equal("utf-8", root.Content.Headers.ContentType?.CharSet);
            AssertSecurityHeaders(root);
            Assert.Equal("no-cache", root.Headers.GetValues("Cache-Control").Single());
            Assert.False(root.Headers.Contains("Access-Control-Allow-Origin"));
            Assert.False(root.Headers.Contains("Server"));
            var html = await root.Content.ReadAsStringAsync();
            Assert.Contains("<html", html, StringComparison.OrdinalIgnoreCase);
        }

        foreach (var (path, mediaType) in new[]
        {
            ("/app.js", "text/javascript"),
            ("/app.css", "text/css")
        })
        {
            using var asset = await _http.GetAsync(path);
            Assert.Equal(HttpStatusCode.OK, asset.StatusCode);
            Assert.Equal(mediaType, asset.Content.Headers.ContentType?.MediaType);
            Assert.Equal("no-cache", asset.Headers.GetValues("Cache-Control").Single());
            Assert.False(asset.Headers.Contains("Server"));
        }

        using (var unauthorized = await _http.GetAsync("/api/health"))
        {
            Assert.Equal(HttpStatusCode.Unauthorized, unauthorized.StatusCode);
            Assert.Contains("no-store", unauthorized.Headers.GetValues("Cache-Control"));
            AssertSecurityHeaders(unauthorized);
            Assert.False(unauthorized.Headers.Contains("Access-Control-Allow-Origin"));
        }

        var token = await PairAsync();
        using var health = await GetWithTokenAsync("/api/health", token);
        Assert.Equal(HttpStatusCode.OK, health.StatusCode);
        Assert.Contains("no-store", health.Headers.GetValues("Cache-Control"));
        AssertSecurityHeaders(health);
        Assert.False(health.Headers.Contains("Access-Control-Allow-Origin"));
        Assert.False(health.Headers.Contains("Server"));
    }

    private async Task<string> PairAsync()
    {
        using var response = await LanTestJson.PostAsync(
            _http, "/api/pair", new LanPairRequest(_auth.Pin, "测试手机"));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var payload = await LanTestJson.ReadAsync<LanPairResponse>(response);
        Assert.NotNull(payload);
        Assert.False(string.IsNullOrWhiteSpace(payload!.Token));
        return payload.Token;
    }

    private async Task<HttpResponseMessage> GetWithTokenAsync(string path, string token)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return await _http.SendAsync(request);
    }

    private async Task<long> CountCheckinsAsync()
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = _store.DatabasePath,
            Mode = SqliteOpenMode.ReadWrite
        }.ToString());
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM checkins;";
        var scalar = await command.ExecuteScalarAsync();
        return Convert.ToInt64(scalar, CultureInfo.InvariantCulture);
    }

    private static void AssertSecurityHeaders(HttpResponseMessage response)
    {
        Assert.Equal(
            "nosniff",
            response.Headers.GetValues("X-Content-Type-Options").Single());
        Assert.Equal(
            "no-referrer",
            response.Headers.GetValues("Referrer-Policy").Single());
        Assert.Equal(
            ExpectedCsp,
            response.Headers.GetValues("Content-Security-Policy").Single());
    }
}
