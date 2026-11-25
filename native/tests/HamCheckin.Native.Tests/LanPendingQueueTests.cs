using HamCheckin.Native.Core.Lan;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 队列契约（设计 4.1/4.2）：50 条上限、按到达顺序定位、同键幂等、
/// CAS 终态、10 分钟过期与已决保留。时钟注入，不等待真实时间。
/// </summary>
public sealed class LanPendingQueueTests
{
    private static readonly DateTimeOffset Start =
        new(2026, 11, 25, 9, 30, 0, TimeSpan.FromHours(8));

    [Fact]
    public void EnqueueStopsAtFiftyPendingAndAcceptsAfterApproval()
    {
        var queue = new LanPendingQueue(() => Start);

        for (var index = 0; index < LanPendingQueue.PendingCapacity; index++)
        {
            var result = queue.Enqueue($"client-{index}", LanTestData.Parsed());
            Assert.Equal(LanEnqueueStatus.Created, result.Status);
            Assert.Equal(index + 1, result.Position);
        }

        Assert.Equal(50, queue.PendingCount);
        var full = queue.Enqueue("client-overflow", LanTestData.Parsed());
        Assert.Equal(LanEnqueueStatus.Full, full.Status);
        Assert.Null(full.Item);
        Assert.Equal(50, queue.PendingCount);

        Assert.True(queue.TryBeginApproval("client-0", out var lease));
        Assert.True(queue.TryApprove("client-0", 1, lease));
        var accepted = queue.Enqueue("client-new", LanTestData.Parsed());
        Assert.Equal(LanEnqueueStatus.Created, accepted.Status);
        Assert.Equal(50, queue.PendingCount);
    }

    [Fact]
    public void RepeatedClientSubmissionIdReturnsExistingItemWithoutDuplicating()
    {
        var queue = new LanPendingQueue(() => Start);
        var first = queue.Enqueue("same-id", LanTestData.Parsed("BA4RLL"));

        var repeated = queue.Enqueue("same-id", LanTestData.Parsed("BG4TKI"));

        Assert.Equal(LanEnqueueStatus.Existing, repeated.Status);
        Assert.Equal(first.Item!.ArrivalSeq, repeated.Item!.ArrivalSeq);
        Assert.Equal(1, repeated.Position);
        Assert.Equal(1, queue.PendingCount);
        Assert.Equal(LanSubmissionState.Pending, repeated.Item.State);

        Assert.True(queue.TryBeginApproval("same-id", out var lease));
        Assert.True(queue.TryApprove("same-id", 3, lease));
        var afterApproval = queue.Enqueue("same-id", LanTestData.Parsed());
        Assert.Equal(LanEnqueueStatus.Existing, afterApproval.Status);
        Assert.Equal(LanSubmissionState.Approved, afterApproval.Item!.State);
        Assert.Equal(0, afterApproval.Position);
    }

    [Fact]
    public void PendingItemsExpireAtExactlyTenMinutes()
    {
        var now = Start;
        var queue = new LanPendingQueue(() => now, TimeSpan.FromMinutes(10));
        queue.Enqueue("old", LanTestData.Parsed());

        now = Start.AddMinutes(9);
        Assert.Equal(0, queue.ExpireOverdue());
        Assert.Equal(LanSubmissionState.Pending, queue.Get("old")!.State);

        now = Start.AddMinutes(10);
        Assert.Equal(1, queue.ExpireOverdue());
        var expired = queue.Get("old")!;
        Assert.Equal(LanSubmissionState.Expired, expired.State);
        Assert.Equal(now, expired.DecidedAt);
        Assert.Equal(0, queue.PendingCount);
    }

    [Fact]
    public void EnqueueExpiresOverduePendingItemsBeforeCheckingCapacity()
    {
        var now = Start;
        var queue = new LanPendingQueue(() => now, TimeSpan.FromMinutes(10));
        for (var index = 0; index < LanPendingQueue.PendingCapacity; index++)
        {
            queue.Enqueue($"old-{index}", LanTestData.Parsed());
        }

        now = Start.AddMinutes(11);
        var result = queue.Enqueue("new", LanTestData.Parsed());

        Assert.Equal(LanEnqueueStatus.Created, result.Status);
        Assert.Equal(LanSubmissionState.Expired, queue.Get("old-0")!.State);
        Assert.Equal(1, queue.PendingCount);
    }

    [Fact]
    public void ApprovalIsCompareAndSetAndSecondApprovalReturnsFalse()
    {
        var queue = new LanPendingQueue(() => Start);
        queue.Enqueue("id", LanTestData.Parsed());

        Assert.False(queue.TryApprove("id", 9, "no-such-lease"));
        Assert.Equal(LanSubmissionState.Pending, queue.Get("id")!.State);

        Assert.True(queue.TryBeginApproval("id", out var lease));
        Assert.False(queue.TryBeginApproval("id", out _));
        Assert.False(queue.TryApprove("id", 7, "no-such-lease"));
        Assert.True(queue.TryApprove("id", 7, lease));
        var approved = queue.Get("id")!;
        Assert.Equal(LanSubmissionState.Approved, approved.State);
        Assert.Equal(7, approved.SequenceNo);
        Assert.Equal(Start, approved.DecidedAt);

        Assert.False(queue.TryApprove("id", 8, lease));
        Assert.False(queue.TryReject("id", "重复"));
        Assert.Equal(7, queue.Get("id")!.SequenceNo);
        Assert.False(queue.TryBeginApproval("missing", out _));
    }

    [Fact]
    public void RejectMovesPendingToTerminalStateWithReason()
    {
        var queue = new LanPendingQueue(() => Start);
        queue.Enqueue("id", LanTestData.Parsed());

        Assert.True(queue.TryReject("id", "重复呼号"));
        var rejected = queue.Get("id")!;
        Assert.Equal(LanSubmissionState.Rejected, rejected.State);
        Assert.Equal("重复呼号", rejected.Reason);
        Assert.Null(rejected.SequenceNo);
        Assert.False(queue.TryReject("id", "再次拒绝"));
        Assert.Equal(0, queue.PendingCount);
    }

    [Fact]
    public void DecidedEntriesKeepOnlyTheNewestTwo()
    {
        var now = Start;
        var queue = new LanPendingQueue(
            () => now,
            TimeSpan.FromMinutes(10),
            decidedRetentionCount: 2);

        for (var index = 0; index < 3; index++)
        {
            queue.Enqueue($"id-{index}", LanTestData.Parsed());
            now = Start.AddMinutes(index + 1);
            Assert.True(queue.TryBeginApproval($"id-{index}", out var lease));
            Assert.True(queue.TryApprove($"id-{index}", index + 1, lease));
        }

        Assert.Null(queue.Get("id-0"));
        Assert.NotNull(queue.Get("id-1"));
        Assert.NotNull(queue.Get("id-2"));
    }

    [Fact]
    public void DecidedEntriesArePrunedAfterTheRetentionLifetime()
    {
        var now = Start;
        var queue = new LanPendingQueue(() => now, TimeSpan.FromMinutes(10));
        queue.Enqueue("approved", LanTestData.Parsed());
        queue.Enqueue("rejected", LanTestData.Parsed());
        Assert.True(queue.TryBeginApproval("approved", out var lease));
        Assert.True(queue.TryApprove("approved", 1, lease));
        Assert.True(queue.TryReject("rejected", "重复"));

        now = Start.AddMinutes(10);
        queue.ExpireOverdue();

        Assert.Null(queue.Get("approved"));
        Assert.Null(queue.Get("rejected"));
    }

    [Fact]
    public void ClearDropsPendingAndDecidedEntries()
    {
        var queue = new LanPendingQueue(() => Start);
        queue.Enqueue("pending", LanTestData.Parsed());
        queue.Enqueue("approved", LanTestData.Parsed());
        Assert.True(queue.TryBeginApproval("pending", out var pendingLease));
        Assert.True(queue.TryBeginApproval("approved", out var approvedLease));
        Assert.True(queue.TryApprove("approved", 1, approvedLease));

        queue.Clear();

        Assert.Equal(0, queue.PendingCount);
        Assert.Null(queue.Get("pending"));
        Assert.Null(queue.Get("approved"));
        Assert.False(queue.TryApprove("pending", 2, pendingLease));
        Assert.False(queue.TryReject("pending", "已清空"));
    }

    [Fact]
    public void ActiveLeaseBlocksExpiryScanAndRejectUntilReleased()
    {
        var now = Start;
        var queue = new LanPendingQueue(() => now, TimeSpan.FromMinutes(10));
        queue.Enqueue("id", LanTestData.Parsed());

        // 租约只有 30s：必须在 10 分钟到期前的最后窗口取得，才能覆盖到期点。
        now = Start.AddMinutes(9).AddSeconds(45);
        Assert.True(queue.TryBeginApproval("id", out var lease));

        now = Start.AddMinutes(10).AddSeconds(1);
        Assert.Equal(0, queue.ExpireOverdue());
        Assert.Equal(LanSubmissionState.Pending, queue.Get("id")!.State);
        Assert.False(queue.TryReject("id", "批准进行中"));

        Assert.True(queue.ReleaseApproval("id", lease));
        Assert.False(queue.ReleaseApproval("id", lease));
        Assert.Equal(1, queue.ExpireOverdue());
        Assert.Equal(LanSubmissionState.Expired, queue.Get("id")!.State);
    }

    [Fact]
    public void ReleaseApprovalAllowsANewLeaseAndRejectsWrongToken()
    {
        var queue = new LanPendingQueue(() => Start);
        queue.Enqueue("id", LanTestData.Parsed());
        Assert.True(queue.TryBeginApproval("id", out var first));

        Assert.False(queue.ReleaseApproval("id", "wrong-token"));
        Assert.False(queue.TryBeginApproval("id", out _));

        Assert.True(queue.ReleaseApproval("id", first));
        Assert.True(queue.TryBeginApproval("id", out var second));
        Assert.NotEqual(first, second);
        Assert.True(queue.TryApprove("id", 1, second));
        Assert.False(queue.ReleaseApproval("id", second));
    }

    [Fact]
    public void ExpiredApprovalLeaseCannotApproveAndCanBeRenewed()
    {
        var now = Start;
        var queue = new LanPendingQueue(() => now);
        queue.Enqueue("id", LanTestData.Parsed());
        Assert.True(queue.TryBeginApproval("id", out var staleLease));

        now = Start.Add(LanPendingQueue.ApprovalLeaseLifetime).AddSeconds(1);

        Assert.False(queue.TryApprove("id", 1, staleLease));
        Assert.Equal(LanSubmissionState.Pending, queue.Get("id")!.State);
        Assert.True(queue.TryBeginApproval("id", out var renewedLease));
        Assert.True(queue.TryApprove("id", 1, renewedLease));
        Assert.Equal(LanSubmissionState.Approved, queue.Get("id")!.State);
    }
}
