using System.Buffers.Text;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace HamCheckin.Native.Core.Lan;

public sealed record LanTokenSession(
    string PhoneId,
    string DeviceLabel,
    DateTimeOffset IssuedAt,
    DateTimeOffset LastSeenAt);

public sealed record LanTokenIssue(string Token, LanTokenSession Session);

/// <summary>
/// PIN 与令牌的唯一持有者。PIN 用 RandomNumberGenerator 生成，令牌只在内存
/// 保存 SHA-256；服务停止或 PIN 轮换时全部失效（设计文档 3.3）。
/// </summary>
public sealed class LanAuthStore
{
    public const int PinLength = 6;
    public const int TokenByteLength = 32;
    public const int MaxActiveSessions = 16;
    public static readonly TimeSpan IdleLifetime = TimeSpan.FromHours(12);

    private readonly object _gate = new();
    private readonly Dictionary<string, LanTokenSession> _sessions = new(StringComparer.Ordinal);
    private readonly Func<DateTimeOffset> _clock;
    private readonly TimeSpan _idleLifetime;
    private string _pin;

    public LanAuthStore()
        : this(() => RuntimeOptions.Now)
    {
    }

    internal LanAuthStore(Func<DateTimeOffset> clock, TimeSpan? idleLifetime = null)
    {
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _idleLifetime = idleLifetime ?? IdleLifetime;
        if (_idleLifetime <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(idleLifetime), "空闲有效期必须大于零。");
        }

        _pin = GeneratePin();
    }

    public string Pin
    {
        get
        {
            lock (_gate)
            {
                return _pin;
            }
        }
    }

    /// <summary>
    /// 恒定时间比较：先按公开的 6 位格式过滤，再对 SHA-256 摘要做 FixedTimeEquals，
    /// 避免用比较耗时泄漏 PIN 内容。
    /// </summary>
    public bool VerifyPin(string? pin)
    {
        var supplied = pin?.Trim() ?? string.Empty;
        if (supplied.Length != PinLength || !supplied.All(char.IsAsciiDigit))
        {
            return false;
        }

        var expected = Pin;
        var expectedHash = SHA256.HashData(Encoding.UTF8.GetBytes(expected));
        var suppliedHash = SHA256.HashData(Encoding.UTF8.GetBytes(supplied));
        return CryptographicOperations.FixedTimeEquals(expectedHash, suppliedHash);
    }

    public LanTokenIssue IssueToken(string? deviceLabel)
    {
        var token = Base64Url.EncodeToString(
            RandomNumberGenerator.GetBytes(TokenByteLength));
        var now = _clock();
        var session = new LanTokenSession(
            NewPhoneId(),
            NormalizeDeviceLabel(deviceLabel),
            now,
            now);
        var hash = HashToken(token);
        lock (_gate)
        {
            // 内存会话有上限：先清过期，再从最久未活动的开始淘汰，避免无限增长。
            PruneExpiredLocked(now);
            while (_sessions.Count >= MaxActiveSessions)
            {
                var oldest = _sessions
                    .OrderBy(static pair => pair.Value.LastSeenAt)
                    .ThenBy(static pair => pair.Value.IssuedAt)
                    .First();
                _sessions.Remove(oldest.Key);
            }

            _sessions[hash] = session;
        }

        return new LanTokenIssue(token, session);
    }

    /// <summary>当前有效（未空闲过期）的手机会话数，供 S3 的「手机收件」页显示。</summary>
    public int ConnectedCount
    {
        get
        {
            lock (_gate)
            {
                PruneExpiredLocked(_clock());
                return _sessions.Count;
            }
        }
    }

    /// <summary>
    /// 当前有效会话快照，按最近活动倒序；只暴露 phoneId / deviceLabel / lastSeen，
    /// 不含令牌或令牌摘要。
    /// </summary>
    public IReadOnlyList<LanTokenSession> GetActiveSessions()
    {
        lock (_gate)
        {
            PruneExpiredLocked(_clock());
            return _sessions.Values
                .OrderByDescending(static session => session.LastSeenAt)
                .ThenBy(static session => session.PhoneId, StringComparer.Ordinal)
                .ToArray();
        }
    }

    /// <summary>按手机标识吊销其全部令牌；返回移除的会话数。</summary>
    public int RevokeByPhoneId(string phoneId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(phoneId);

        lock (_gate)
        {
            var targets = _sessions
                .Where(pair => string.Equals(
                    pair.Value.PhoneId, phoneId, StringComparison.Ordinal))
                .Select(static pair => pair.Key)
                .ToArray();
            foreach (var key in targets)
            {
                _sessions.Remove(key);
            }

            return targets.Length;
        }
    }

    /// <summary>
    /// 校验令牌；命中时刷新 LastSeenAt。空闲超过 12 小时即吊销并返回 null。
    /// </summary>
    public LanTokenSession? Validate(string? token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return null;
        }

        var hash = HashToken(token);
        lock (_gate)
        {
            if (!_sessions.TryGetValue(hash, out var session))
            {
                return null;
            }

            var now = _clock();
            if (now - session.LastSeenAt >= _idleLifetime)
            {
                _sessions.Remove(hash);
                return null;
            }

            var updated = session with { LastSeenAt = now };
            _sessions[hash] = updated;
            return updated;
        }
    }

    public void Revoke(string? token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        lock (_gate)
        {
            _sessions.Remove(HashToken(token));
        }
    }

    public void RevokeAll()
    {
        lock (_gate)
        {
            _sessions.Clear();
        }
    }

    /// <summary>
    /// 每次启动服务重新生成 PIN，并让旧令牌全部失效。
    /// </summary>
    public void RotatePin()
    {
        lock (_gate)
        {
            _pin = GeneratePin();
            _sessions.Clear();
        }
    }

    private void PruneExpiredLocked(DateTimeOffset now)
    {
        var expired = _sessions
            .Where(pair => now - pair.Value.LastSeenAt >= _idleLifetime)
            .Select(static pair => pair.Key)
            .ToArray();
        foreach (var key in expired)
        {
            _sessions.Remove(key);
        }
    }

    private static string GeneratePin() =>
        RandomNumberGenerator.GetInt32(0, 1_000_000)
            .ToString("D6", CultureInfo.InvariantCulture);

    private static string NewPhoneId() =>
        "phone-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(6)).ToLowerInvariant();

    private static string NormalizeDeviceLabel(string? deviceLabel)
    {
        var label = deviceLabel?.Trim() ?? string.Empty;
        return label.Length <= 40 ? label : label[..40];
    }

    private static string HashToken(string token) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
}
