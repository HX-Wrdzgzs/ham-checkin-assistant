namespace HamCheckin.Native.Core.Parsing;

/// <summary>
/// 两个快捷输入窗口共享的草稿快照。
/// Text 是用户原文，解析器和候选查询不得反向改写它。
/// </summary>
public sealed record QuickInputDraftSnapshot(
    string Text,
    long Revision,
    string OriginId,
    bool IsImeComposing,
    DateTimeOffset UpdatedAt)
{
    public static QuickInputDraftSnapshot Empty { get; } = new(
        string.Empty,
        0,
        "initial",
        false,
        DateTimeOffset.UtcNow);
}

public sealed class QuickInputDraftChangedEventArgs(
    QuickInputDraftSnapshot snapshot,
    bool isUserEdit) : EventArgs
{
    public QuickInputDraftSnapshot Snapshot { get; } = snapshot;
    public bool IsUserEdit { get; } = isUserEdit;
}

/// <summary>
/// 为主窗口和置顶快速小窗提供带修订号的输入草稿。
/// 外部控件必须带上自己最后应用的 Revision，旧事件不能覆盖新草稿。
/// </summary>
public sealed class QuickInputDraftService
{
    private readonly object _gate = new();
    private QuickInputDraftSnapshot _current = QuickInputDraftSnapshot.Empty;

    public event EventHandler<QuickInputDraftChangedEventArgs>? Changed;

    public QuickInputDraftSnapshot Current
    {
        get
        {
            lock (_gate)
            {
                return _current;
            }
        }
    }

    public QuickInputDraftSnapshot ApplyUserEdit(
        string originId,
        long baseRevision,
        string? text,
        bool isImeComposing = false)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(originId);
        QuickInputDraftSnapshot snapshot;
        lock (_gate)
        {
            if (baseRevision != _current.Revision)
            {
                return _current;
            }

            var value = text ?? string.Empty;
            if (string.Equals(value, _current.Text, StringComparison.Ordinal)
                && isImeComposing == _current.IsImeComposing)
            {
                return _current;
            }

            snapshot = Next(value, originId, isImeComposing);
            _current = snapshot;
        }

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, true));
        return snapshot;
    }

    public QuickInputDraftSnapshot SetProgrammatic(
        string? text,
        string originId = "programmatic",
        bool isImeComposing = false)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(originId);
        QuickInputDraftSnapshot snapshot;
        lock (_gate)
        {
            var value = text ?? string.Empty;
            if (string.Equals(value, _current.Text, StringComparison.Ordinal)
                && isImeComposing == _current.IsImeComposing)
            {
                return _current;
            }

            snapshot = Next(value, originId, isImeComposing);
            _current = snapshot;
        }

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, false));
        return snapshot;
    }

    public bool TryClear(long submittedRevision)
    {
        QuickInputDraftSnapshot snapshot;
        lock (_gate)
        {
            if (_current.Revision != submittedRevision)
            {
                return false;
            }

            snapshot = Next(string.Empty, "programmatic", false);
            _current = snapshot;
        }

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, false));
        return true;
    }

    public QuickInputDraftSnapshot SetImeCompositionState(string originId, bool isComposing)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(originId);
        QuickInputDraftSnapshot snapshot;
        lock (_gate)
        {
            if (_current.IsImeComposing == isComposing)
            {
                return _current;
            }

            snapshot = Next(_current.Text, originId, isComposing);
            _current = snapshot;
        }

        // 组合状态变化不是用户文本提交，不触发候选消费；界面仍可刷新状态。
        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, false));
        return snapshot;
    }

    private QuickInputDraftSnapshot Next(string text, string originId, bool isImeComposing) =>
        new(text, _current.Revision + 1, originId, isImeComposing, DateTimeOffset.UtcNow);
}
