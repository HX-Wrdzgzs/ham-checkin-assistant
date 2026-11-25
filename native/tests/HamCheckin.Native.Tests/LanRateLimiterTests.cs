using HamCheckin.Native.Core.Lan;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 令牌桶限流（设计 3.4）：容量、按窗口匀速回填、Retry-After 计算、
/// 不同桶互相独立。时钟注入，不 sleep。
/// </summary>
public sealed class LanRateLimiterTests
{
    private static readonly DateTimeOffset Start =
        new(2026, 11, 25, 9, 30, 0, TimeSpan.FromHours(8));

    [Fact]
    public void RefillsAtConfiguredRateAndRejectsBeyondCapacity()
    {
        var now = Start;
        var limiter = new LanRateLimiter(() => now);
        var window = TimeSpan.FromMinutes(1);

        Assert.True(limiter.TryAcquire("submit:phone", 2, window, out var retryAfter));
        Assert.Equal(TimeSpan.Zero, retryAfter);
        Assert.True(limiter.TryAcquire("submit:phone", 2, window, out _));

        Assert.False(limiter.TryAcquire("submit:phone", 2, window, out retryAfter));
        Assert.Equal(TimeSpan.FromSeconds(30), retryAfter);

        now = Start.AddSeconds(30);
        Assert.True(limiter.TryAcquire("submit:phone", 2, window, out _));
        Assert.False(limiter.TryAcquire("submit:phone", 2, window, out _));

        now = Start.AddHours(1);
        Assert.True(limiter.TryAcquire("submit:phone", 2, window, out _));
        Assert.True(limiter.TryAcquire("submit:phone", 2, window, out _));
        Assert.False(limiter.TryAcquire("submit:phone", 2, window, out _));
    }

    [Fact]
    public void BucketsAreIndependentPerKey()
    {
        var limiter = new LanRateLimiter(() => Start);

        Assert.True(limiter.TryAcquire("preview:phone-a", 1, TimeSpan.FromMinutes(1), out _));
        Assert.False(limiter.TryAcquire("preview:phone-a", 1, TimeSpan.FromMinutes(1), out _));
        Assert.True(limiter.TryAcquire("preview:phone-b", 1, TimeSpan.FromMinutes(1), out _));
        Assert.True(limiter.TryAcquire("submit:phone-a", 1, TimeSpan.FromMinutes(1), out _));
    }

    [Theory]
    [InlineData("", 1)]
    [InlineData("   ", 1)]
    [InlineData("key", 0)]
    public void InvalidArgumentsAreRejected(string key, int capacity)
    {
        var limiter = new LanRateLimiter(() => Start);

        Assert.ThrowsAny<ArgumentException>(
            () => limiter.TryAcquire(key, capacity, TimeSpan.FromMinutes(1), out _));
    }

    [Fact]
    public void NonPositiveWindowIsRejected()
    {
        var limiter = new LanRateLimiter(() => Start);

        Assert.Throws<ArgumentOutOfRangeException>(
            () => limiter.TryAcquire("key", 1, TimeSpan.Zero, out _));
    }
}
