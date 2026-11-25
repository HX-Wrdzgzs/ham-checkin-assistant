using System.Globalization;
using HamCheckin.Native.Core.Storage;

namespace HamCheckin.Native.Core.Lan;

public enum LanApprovalStatus
{
    Approved,
    NotFound,
    NotPending,
    SessionUnavailable,
    SessionEnded,
    /// <summary>同一提交已有一次批准在途（租约未释放），本次点击未执行。</summary>
    Busy,
    /// <summary>SQLite 已提交，但队列终态未能标记为 Approved（例如服务停止清空队列）。</summary>
    WriteCommitted
}

public sealed record LanApprovalResult(
    LanApprovalStatus Status,
    LanPendingItem? Item,
    CheckinEntry? Checkin);

/// <summary>
/// PC 端「确认入册」的唯一入口：先取得队列租约，再取当前场次快照并读回/写入既有
/// NativeStore 写点，最后用租约做比较并设置（设计文档 2 / 4.1 / 4.2）。
/// </summary>
public sealed class LanApprovalService
{
    private readonly NativeStore _store;
    private readonly LanPendingQueue _queue;
    private readonly ILanSessionSource _sessions;

    public LanApprovalService(
        NativeStore store,
        LanPendingQueue queue,
        ILanSessionSource sessions)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _queue = queue ?? throw new ArgumentNullException(nameof(queue));
        _sessions = sessions ?? throw new ArgumentNullException(nameof(sessions));
    }

    public async Task<LanApprovalResult> ApproveAsync(
        string clientSubmissionId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(clientSubmissionId);

        var item = _queue.Get(clientSubmissionId);
        if (item is null)
        {
            return new LanApprovalResult(LanApprovalStatus.NotFound, null, null);
        }
        if (item.State != LanSubmissionState.Pending)
        {
            return new LanApprovalResult(LanApprovalStatus.NotPending, item, null);
        }

        // 点击时的场次快照；场次已被结束则保持 Pending，把原因交回 UI。
        var snapshot = _sessions.CurrentSession;
        if (snapshot is null)
        {
            return new LanApprovalResult(LanApprovalStatus.SessionUnavailable, item, null);
        }

        var session = await _store.GetSessionAsync(snapshot.Id, cancellationToken)
            .ConfigureAwait(false);
        if (session is null)
        {
            return new LanApprovalResult(LanApprovalStatus.SessionUnavailable, item, null);
        }
        if (!string.Equals(session.Status, "active", StringComparison.Ordinal))
        {
            return new LanApprovalResult(LanApprovalStatus.SessionEnded, item, null);
        }

        // 先占租约再写库：同一条提交同时只允许一个批准在途，过期扫描和拒绝也会让路。
        if (!_queue.TryBeginApproval(item.ClientSubmissionId, out var leaseToken))
        {
            var current = _queue.Get(item.ClientSubmissionId);
            if (current is null)
            {
                return new LanApprovalResult(LanApprovalStatus.NotFound, null, null);
            }
            return current.State == LanSubmissionState.Pending
                ? new LanApprovalResult(LanApprovalStatus.Busy, current, null)
                : new LanApprovalResult(LanApprovalStatus.NotPending, current, null);
        }

        var submissionId = string.Concat(
            "lan-",
            session.Id.ToString(CultureInfo.InvariantCulture),
            "-",
            item.ClientSubmissionId);
        try
        {
            // 场次级提交键幂等：重试（写库成功但上次答复丢失）时读回已有行，不再插入。
            var existing = await _store.GetCheckinBySubmissionIdAsync(
                submissionId, cancellationToken).ConfigureAwait(false);
            var checkin = existing ?? await _store.AddCheckinAsync(
                session,
                item.Parsed,
                submissionId,
                LanSources.Lan,
                cancellationToken).ConfigureAwait(false);

            if (!_queue.TryApprove(item.ClientSubmissionId, checkin.SequenceNo, leaseToken))
            {
                // 数据库已提交但队列没能标记批准（例如服务恰在此时停止并清空队列）：
                // 记录保留，但绝不对操作员报告「已确认」。
                return new LanApprovalResult(
                    LanApprovalStatus.WriteCommitted,
                    _queue.Get(item.ClientSubmissionId) ?? item,
                    checkin);
            }

            return new LanApprovalResult(
                LanApprovalStatus.Approved,
                _queue.Get(item.ClientSubmissionId) ?? item,
                checkin);
        }
        finally
        {
            // 成功路径 TryApprove 已移除租约，这里是幂等兜底；异常路径必须释放租约。
            _queue.ReleaseApproval(item.ClientSubmissionId, leaseToken);
        }
    }
}
