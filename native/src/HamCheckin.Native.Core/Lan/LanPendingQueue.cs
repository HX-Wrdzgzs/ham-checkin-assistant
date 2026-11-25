namespace HamCheckin.Native.Core.Lan;

public enum LanEnqueueStatus
{
    Created,
    Existing,
    Full
}

public sealed record LanEnqueueResult(LanEnqueueStatus Status, LanPendingItem? Item, int Position);

/// <summary>
/// 进程内待确认队列：单锁保护的字典 + 不可变记录。设计文档 4.1/4.2。
/// 任何 SQLite 写入都发生在批准之后，队列本身不落盘。
/// </summary>
public sealed class LanPendingQueue
{
    public const int PendingCapacity = 50;
    public const int DecidedRetentionCount = 200;
    public static readonly TimeSpan PendingLifetime = TimeSpan.FromMinutes(10);

    /// <summary>批准租约有效期；数据库写入远快于此，超时视为放弃。</summary>
    public static readonly TimeSpan ApprovalLeaseLifetime = TimeSpan.FromSeconds(30);

    private sealed record ApprovalLease(string Token, DateTimeOffset ExpiresAt);

    private readonly object _gate = new();
    private readonly Dictionary<string, LanPendingItem> _items = new(StringComparer.Ordinal);
    private readonly Dictionary<string, ApprovalLease> _leases = new(StringComparer.Ordinal);
    private readonly Func<DateTimeOffset> _clock;
    private readonly TimeSpan _pendingLifetime;
    private readonly int _decidedRetentionCount;
    private long _nextArrivalSeq;

    public LanPendingQueue()
        : this(() => RuntimeOptions.Now)
    {
    }

    internal LanPendingQueue(
        Func<DateTimeOffset> clock,
        TimeSpan? pendingLifetime = null,
        int? decidedRetentionCount = null)
    {
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        _pendingLifetime = pendingLifetime ?? PendingLifetime;
        _decidedRetentionCount = decidedRetentionCount ?? DecidedRetentionCount;
        if (_pendingLifetime <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(pendingLifetime), "待确认有效期必须大于零。");
        }
        if (_decidedRetentionCount < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(decidedRetentionCount), "已决保留条数不能为负数。");
        }
    }

    public int PendingCount
    {
        get
        {
            lock (_gate)
            {
                return CountPendingLocked();
            }
        }
    }

    /// <summary>
    /// 按到达顺序返回 Pending 快照；PC 页面按 ArrivalSeq 升序展示。
    /// </summary>
    public IReadOnlyList<LanPendingItem> GetPendingSnapshot()
    {
        lock (_gate)
        {
            return _items.Values
                .Where(static item => item.State == LanSubmissionState.Pending)
                .OrderBy(static item => item.ArrivalSeq)
                .ToArray();
        }
    }

    public LanPendingItem? Get(string clientSubmissionId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        lock (_gate)
        {
            return _items.TryGetValue(clientSubmissionId, out var item) ? item : null;
        }
    }

    /// <summary>
    /// 同 clientSubmissionId 直接返回既有条目（含已决），不新建、不重复计数。
    /// </summary>
    public LanEnqueueResult Enqueue(
        string clientSubmissionId,
        ParseResult parsed)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        ArgumentNullException.ThrowIfNull(parsed);

        lock (_gate)
        {
            var now = _clock();
            ExpireOverdueLocked(now);
            PruneDecidedLocked(now);

            if (_items.TryGetValue(clientSubmissionId, out var existing))
            {
                return new LanEnqueueResult(
                    LanEnqueueStatus.Existing, existing, PositionLocked(existing));
            }

            var pendingCount = CountPendingLocked();
            if (pendingCount >= PendingCapacity)
            {
                return new LanEnqueueResult(LanEnqueueStatus.Full, null, 0);
            }

            var item = new LanPendingItem(
                clientSubmissionId,
                Interlocked.Increment(ref _nextArrivalSeq),
                parsed.RawText,
                parsed,
                now,
                LanSubmissionState.Pending,
                null,
                string.Empty,
                null);
            _items.Add(clientSubmissionId, item);
            return new LanEnqueueResult(LanEnqueueStatus.Created, item, pendingCount + 1);
        }
    }

    /// <summary>
    /// 为一次「确认入册」取得租约：只有 Pending 且没有有效租约的条目才能成功。
    /// 租约有效期间，过期扫描与 TryReject 都不会改变条目；租约由 TryApprove
    /// 成功或 ReleaseApproval 显式释放。
    /// </summary>
    public bool TryBeginApproval(string clientSubmissionId, out string leaseToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        leaseToken = string.Empty;

        lock (_gate)
        {
            var now = _clock();
            ExpireOverdueLocked(now);
            if (!_items.TryGetValue(clientSubmissionId, out var item)
                || item.State != LanSubmissionState.Pending)
            {
                return false;
            }
            if (TryGetActiveLeaseLocked(clientSubmissionId, now, out _))
            {
                return false;
            }

            leaseToken = Guid.NewGuid().ToString("N");
            _leases[clientSubmissionId] = new ApprovalLease(
                leaseToken, now + ApprovalLeaseLifetime);
            return true;
        }
    }

    /// <summary>
    /// 比较并设置：必须持有匹配的有效租约且条目仍为 Pending；成功时移除租约。
    /// 无租约、租约不匹配或重复批准都返回 false，条目保持不变。
    /// </summary>
    public bool TryApprove(string clientSubmissionId, int sequenceNo, string leaseToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(leaseToken);
        if (sequenceNo < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(sequenceNo), "记录序号必须从 1 开始。");
        }

        lock (_gate)
        {
            var now = _clock();
            if (!TryGetActiveLeaseLocked(clientSubmissionId, now, out var lease)
                || !string.Equals(lease!.Token, leaseToken, StringComparison.Ordinal))
            {
                return false;
            }
            if (!_items.TryGetValue(clientSubmissionId, out var item)
                || item.State != LanSubmissionState.Pending)
            {
                _leases.Remove(clientSubmissionId);
                return false;
            }

            _items[clientSubmissionId] = item with
            {
                State = LanSubmissionState.Approved,
                SequenceNo = sequenceNo,
                Reason = string.Empty,
                DecidedAt = now
            };
            _leases.Remove(clientSubmissionId);
            PruneDecidedLocked(now);
            return true;
        }
    }

    /// <summary>
    /// 释放仍由本次批准持有的租约；租约已被 TryApprove 移除或已换人时返回 false。
    /// 批准路径必须在 finally 中调用，异常时让条目回到可重试状态。
    /// </summary>
    public bool ReleaseApproval(string clientSubmissionId, string leaseToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(leaseToken);

        lock (_gate)
        {
            if (!_leases.TryGetValue(clientSubmissionId, out var lease)
                || !string.Equals(lease.Token, leaseToken, StringComparison.Ordinal))
            {
                return false;
            }

            _leases.Remove(clientSubmissionId);
            return true;
        }
    }

    /// <summary>
    /// 拒绝只对无有效租约的 Pending 条目生效；批准进行中时返回 false，避免
    /// 手机端与 PC 端同时看到互相矛盾的终态。
    /// </summary>
    public bool TryReject(string clientSubmissionId, string reason)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(reason);

        lock (_gate)
        {
            if (!_items.TryGetValue(clientSubmissionId, out var item)
                || item.State != LanSubmissionState.Pending)
            {
                return false;
            }

            var now = _clock();
            if (TryGetActiveLeaseLocked(clientSubmissionId, now, out _))
            {
                return false;
            }

            _items[clientSubmissionId] = item with
            {
                State = LanSubmissionState.Rejected,
                SequenceNo = null,
                Reason = reason,
                DecidedAt = now
            };
            PruneDecidedLocked(now);
            return true;
        }
    }

    /// <summary>
    /// 由宿主 30 秒扫描器调用；返回本次过期的条数。
    /// </summary>
    public int ExpireOverdue()
    {
        lock (_gate)
        {
            var now = _clock();
            var expired = ExpireOverdueLocked(now);
            PruneDecidedLocked(now);
            return expired;
        }
    }

    /// <summary>
    /// 服务停止时丢弃全部待确认、已决条目和租约。若此时仍有批准在途，
    /// 其 TryApprove 必然失败，调用方必须返回非 Approved 状态；但已经提交到
    /// SQLite 的记录不回滚，也不会丢。
    /// </summary>
    public void Clear()
    {
        lock (_gate)
        {
            _items.Clear();
            _leases.Clear();
        }
    }

    private int ExpireOverdueLocked(DateTimeOffset now)
    {
        var overdue = new List<string>();
        foreach (var item in _items.Values)
        {
            if (item.State != LanSubmissionState.Pending)
            {
                continue;
            }

            // 批准进行中的条目由租约保护，过期扫描不得改写它。
            if (TryGetActiveLeaseLocked(item.ClientSubmissionId, now, out _))
            {
                continue;
            }
            if (now - item.ReceivedAt >= _pendingLifetime)
            {
                overdue.Add(item.ClientSubmissionId);
            }
        }

        foreach (var id in overdue)
        {
            _items[id] = _items[id] with
            {
                State = LanSubmissionState.Expired,
                DecidedAt = now
            };
            _leases.Remove(id);
        }

        return overdue.Count;
    }

    private void PruneDecidedLocked(DateTimeOffset now)
    {
        var decided = _items.Values
            .Where(static item => item.State != LanSubmissionState.Pending)
            .OrderBy(static item => item.DecidedAt ?? DateTimeOffset.MinValue)
            .ToArray();

        var expired = decided
            .Where(item => item.DecidedAt is { } at && now - at >= _pendingLifetime)
            .ToArray();
        foreach (var item in expired)
        {
            _items.Remove(item.ClientSubmissionId);
            _leases.Remove(item.ClientSubmissionId);
        }

        // 两份保留上限同时生效：10 分钟内且最多 200 条。
        var expiredIds = expired
            .Select(static item => item.ClientSubmissionId)
            .ToHashSet(StringComparer.Ordinal);
        var remaining = decided
            .Where(item => !expiredIds.Contains(item.ClientSubmissionId))
            .ToArray();
        var overflow = remaining.Length - _decidedRetentionCount;
        for (var index = 0; index < overflow; index++)
        {
            _items.Remove(remaining[index].ClientSubmissionId);
            _leases.Remove(remaining[index].ClientSubmissionId);
        }
    }

    private bool TryGetActiveLeaseLocked(
        string clientSubmissionId,
        DateTimeOffset now,
        out ApprovalLease? lease)
    {
        if (_leases.TryGetValue(clientSubmissionId, out lease))
        {
            if (now < lease.ExpiresAt)
            {
                return true;
            }

            _leases.Remove(clientSubmissionId);
        }

        lease = null;
        return false;
    }

    private int CountPendingLocked() => _items.Values.Count(
        static item => item.State == LanSubmissionState.Pending);

    private int PositionLocked(LanPendingItem item)
    {
        if (item.State != LanSubmissionState.Pending)
        {
            return 0;
        }

        var position = 0;
        foreach (var value in _items.Values
            .Where(static value => value.State == LanSubmissionState.Pending)
            .OrderBy(static value => value.ArrivalSeq))
        {
            position++;
            if (string.Equals(value.ClientSubmissionId, item.ClientSubmissionId, StringComparison.Ordinal))
            {
                return position;
            }
        }

        return 0;
    }
}
