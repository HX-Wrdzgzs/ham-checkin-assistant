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
    bool isUserEdit,
    bool forceApplyToEditors = false) : EventArgs
{
    public QuickInputDraftSnapshot Snapshot { get; } = snapshot;
    public bool IsUserEdit { get; } = isUserEdit;

    /// <summary>
    /// Indicates an explicit application operation, such as a successful
    /// submission clearing the draft or a deliberate session switch.  Only
    /// these operations may replace the text of a focused editor.  Parser,
    /// IME metadata, candidate, and cross-window notifications must leave the
    /// focused TextBox's complete raw text, caret, selection, and undo stack
    /// untouched.
    /// </summary>
    public bool ForceApplyToEditors { get; } = forceApplyToEditors;
}

/// <summary>
/// 为主窗口和置顶快速小窗提供带修订号的输入草稿。
/// baseRevision 仅用于事件追踪。当前获得键盘焦点的 TextBox 拥有完整
/// 原文，因此旧 Revision 的用户编辑也必须被接受，不能把旧快照写回控件。
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
        bool isImeComposing = false,
        bool isActiveEditor = true)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(originId);
        QuickInputDraftSnapshot snapshot;
        var isTextEdit = false;
        lock (_gate)
        {
            var value = text ?? string.Empty;
            // Only the editor that currently owns keyboard focus may submit a
            // stale revision as authoritative text.  A non-focused editor can
            // have a queued TextChanged notification from before the other
            // window was edited; accepting that old full string would replace
            // the active draft and recreate the suffix-loss bug.  The focused
            // editor remains authoritative even when WPF/IME metadata makes
            // its base revision look old.
            if (!isActiveEditor && baseRevision < _current.Revision)
            {
                return _current;
            }

            // A TextBox edit is authoritative for the control that currently owns
            // keyboard focus.  A stale revision can happen when IME composition,
            // the other input window, or a queued WPF notification runs between
            // TextChanged events.  Rejecting that edit makes the caller write the
            // old full string back into the TextBox, which is exactly how a suffix
            // disappears while editing the beginning of a line.
            _ = baseRevision;
            if (string.Equals(value, _current.Text, StringComparison.Ordinal))
            {
                if (isImeComposing == _current.IsImeComposing
                    && string.Equals(originId, _current.OriginId, StringComparison.Ordinal))
                {
                    return _current;
                }

                snapshot = _current with
                {
                    OriginId = originId,
                    IsImeComposing = isImeComposing,
                    UpdatedAt = DateTimeOffset.UtcNow
                };
                _current = snapshot;
            }
            else
            {
                snapshot = Next(value, originId, isImeComposing);
                _current = snapshot;
                isTextEdit = true;
            }
        }

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, isTextEdit));
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

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(
            snapshot, false, forceApplyToEditors: true));
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

        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(
            snapshot, false, forceApplyToEditors: true));
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

            // IME state is metadata, not a text edit.  It must not advance the
            // text revision: otherwise a composition notification can make the
            // next real TextChanged event look stale.
            snapshot = _current with
            {
                OriginId = originId,
                IsImeComposing = isComposing,
                UpdatedAt = DateTimeOffset.UtcNow
            };
            _current = snapshot;
        }

        // 组合状态变化不是用户文本提交，不触发候选消费；界面仍可刷新状态。
        Changed?.Invoke(this, new QuickInputDraftChangedEventArgs(snapshot, false));
        return snapshot;
    }

    private QuickInputDraftSnapshot Next(string text, string originId, bool isImeComposing) =>
        new(text, _current.Revision + 1, originId, isImeComposing, DateTimeOffset.UtcNow);
}
