namespace HamCheckin.Native.Core.Lan;

/// <summary>
/// 进程内令牌桶限流（设计文档 3.4）。调用方用容量 + 窗口表达策略，
/// 键由调用方拼上策略前缀，避免不同端点互相占用配额。
/// </summary>
public sealed class LanRateLimiter
{
    private static readonly TimeSpan IdleRetention = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan SweepInterval = TimeSpan.FromMinutes(1);

    private sealed class Bucket
    {
        public double Tokens { get; set; }
        public DateTimeOffset UpdatedAt { get; set; }
    }

    private readonly object _gate = new();
    private readonly Dictionary<string, Bucket> _buckets = new(StringComparer.Ordinal);
    private readonly Func<DateTimeOffset> _clock;
    private DateTimeOffset _lastSweep;

    public LanRateLimiter()
        : this(() => DateTimeOffset.Now)
    {
    }

    internal LanRateLimiter(Func<DateTimeOffset> clock)
    {
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _lastSweep = _clock();
    }

    /// <summary>
    /// 尝试取一个令牌；失败时通过 retryAfter 告诉调用方 Retry-After 的等待时长。
    /// </summary>
    public bool TryAcquire(string bucketKey, int capacity, TimeSpan window, out TimeSpan retryAfter)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(bucketKey);
        if (capacity < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity), "限流容量必须大于零。");
        }
        if (window <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(window), "限流窗口必须大于零。");
        }

        var refillPerSecond = capacity / window.TotalSeconds;
        lock (_gate)
        {
            var now = _clock();
            SweepLocked(now);
            if (!_buckets.TryGetValue(bucketKey, out var bucket))
            {
                bucket = new Bucket { Tokens = capacity, UpdatedAt = now };
                _buckets[bucketKey] = bucket;
            }
            else
            {
                var elapsedSeconds = (now - bucket.UpdatedAt).TotalSeconds;
                if (elapsedSeconds > 0)
                {
                    bucket.Tokens = Math.Min(capacity, bucket.Tokens + elapsedSeconds * refillPerSecond);
                    bucket.UpdatedAt = now;
                }
            }

            if (bucket.Tokens >= 1)
            {
                bucket.Tokens -= 1;
                retryAfter = TimeSpan.Zero;
                return true;
            }

            var waitSeconds = (1 - bucket.Tokens) / refillPerSecond;
            retryAfter = TimeSpan.FromSeconds(Math.Max(1, Math.Ceiling(waitSeconds)));
            return false;
        }
    }

    private void SweepLocked(DateTimeOffset now)
    {
        if (now - _lastSweep < SweepInterval)
        {
            return;
        }

        var idle = _buckets
            .Where(pair => now - pair.Value.UpdatedAt >= IdleRetention)
            .Select(static pair => pair.Key)
            .ToArray();
        foreach (var key in idle)
        {
            _buckets.Remove(key);
        }

        _lastSweep = now;
    }
}
