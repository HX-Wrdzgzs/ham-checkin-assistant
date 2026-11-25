namespace HamCheckin.Native.Core.Lan;

/// <summary>
/// 待确认条目的状态。状态迁移只发生在 LanPendingQueue 内（比较并设置）。
/// </summary>
public enum LanSubmissionState
{
    Pending,
    Approved,
    Rejected,
    Expired
}

public static class LanSubmissionStates
{
    public static string ToWireName(this LanSubmissionState state) => state switch
    {
        LanSubmissionState.Pending => "pending",
        LanSubmissionState.Approved => "approved",
        LanSubmissionState.Rejected => "rejected",
        LanSubmissionState.Expired => "expired",
        _ => throw new ArgumentOutOfRangeException(nameof(state), state, "未知的待确认状态。")
    };
}

/// <summary>
/// checkins.source 的取值（R10：集中定义，避免自由文本漂移）。
/// </summary>
public static class LanSources
{
    public const string Local = "local";
    public const string Lan = "lan";
}

/// <summary>
/// 手机页与 API 的错误码，与设计文档 6.4 一一对应。
/// </summary>
public static class LanErrorCodes
{
    public const string BadPin = "bad_pin";
    public const string TokenInvalid = "token_invalid";
    public const string NoCallsign = "no_callsign";
    public const string SessionEnded = "session_ended";
    public const string QueueFull = "queue_full";
    public const string RateLimited = "rate_limited";
    public const string BadRequest = "bad_request";
    public const string PayloadTooLarge = "payload_too_large";
    public const string Unknown = "unknown";
    public const string ForbiddenOrigin = "forbidden_origin";
    public const string ForbiddenHost = "forbidden_host";
}

/// <summary>
/// 当前场次的最小快照。WPF 侧在 S3 用一个适配器实现它，Core/Lan 不引用 WPF。
/// </summary>
public sealed record LanSessionSnapshot(long Id, string Name, string Date, string Status)
{
    public bool IsActive => string.Equals(Status, "active", StringComparison.Ordinal);
}

/// <summary>
/// 场次快照来源。批准路径必须在「点击时」读一次，而不是在等待 SQLite 之后再读。
/// </summary>
public interface ILanSessionSource
{
    LanSessionSnapshot? CurrentSession { get; }
}

/// <summary>
/// 队列中的一条待确认记录；不可变，状态迁移通过 with 生成新实例。
/// </summary>
public sealed record LanPendingItem(
    string ClientSubmissionId,
    long ArrivalSeq,
    string RawText,
    ParseResult Parsed,
    DateTimeOffset ReceivedAt,
    LanSubmissionState State,
    int? SequenceNo,
    string Reason,
    DateTimeOffset? DecidedAt);

public sealed record LanPairRequest(string? Pin, string? DeviceLabel);

public sealed record LanPairResponse(
    string Token,
    string PhoneId,
    string PcName,
    string SessionName);

public sealed record LanHealthResponse(
    string PcName,
    string SessionName,
    string SessionStatus,
    string SessionDate,
    DateTimeOffset ServerTime);

public sealed record LanPreviewRequest(string? Text);

public sealed record LanPreviewResponse(
    string Callsign,
    string Qth,
    string Device,
    string Antenna,
    string Power,
    string Signal,
    IReadOnlyList<string> Unmatched,
    bool CanSubmit);

public sealed record LanSubmissionRequest(string? ClientSubmissionId, string? RawText);

public sealed record LanSubmissionAcceptedResponse(
    string SubmissionId,
    string State,
    long ArrivalSeq,
    int Position);

public sealed record LanSubmissionStatusResponse(
    string State,
    int? SequenceNo,
    string? Reason,
    DateTimeOffset? DecidedAt);

public sealed record LanErrorResponse(string Error, string Message);
