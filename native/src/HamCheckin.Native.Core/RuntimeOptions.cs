namespace HamCheckin.Native.Core;

/// <summary>
/// Process-local options used by isolated UI/integration runs. Production
/// startup leaves every override unset, so normal clock, network and storage
/// behavior are unchanged.
/// </summary>
public static class RuntimeOptions
{
    private static readonly object Gate = new();
    private static DateTimeOffset? _fixedNow;
    private static int _storeDelayMilliseconds;
    private static bool _disableNetwork;

    public static DateTimeOffset Now
    {
        get
        {
            lock (Gate)
            {
                return _fixedNow ?? DateTimeOffset.Now;
            }
        }
    }

    public static DateOnly Today => DateOnly.FromDateTime(Now.LocalDateTime);

    public static int StoreDelayMilliseconds
    {
        get
        {
            lock (Gate)
            {
                return _storeDelayMilliseconds;
            }
        }
    }

    public static bool DisableNetwork
    {
        get
        {
            lock (Gate)
            {
                return _disableNetwork;
            }
        }
    }

    public static void Configure(
        DateTimeOffset? fixedNow = null,
        int storeDelayMilliseconds = 0,
        bool disableNetwork = false)
    {
        if (storeDelayMilliseconds is < 0 or > 60_000)
        {
            throw new ArgumentOutOfRangeException(
                nameof(storeDelayMilliseconds),
                "SQLite 测试延迟必须在 0 到 60000 毫秒之间。");
        }

        lock (Gate)
        {
            _fixedNow = fixedNow;
            _storeDelayMilliseconds = storeDelayMilliseconds;
            _disableNetwork = disableNetwork;
        }
    }
}
