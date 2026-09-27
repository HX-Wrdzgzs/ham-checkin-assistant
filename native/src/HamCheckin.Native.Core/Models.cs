namespace HamCheckin.Native.Core;

public sealed record ParseField(
    string Value = "",
    string Source = "",
    double Confidence = 0,
    string Raw = "",
    IReadOnlyList<string>? Candidates = null)
{
    public static ParseField Empty { get; } = new();
}

public sealed record ParseResult(
    string RawText,
    IReadOnlyList<string> Tokens,
    ParseField Callsign,
    ParseField Qth,
    ParseField Device,
    ParseField Antenna,
    ParseField Power,
    ParseField Signal,
    IReadOnlyList<string> Unmatched)
{
    public static ParseResult Empty { get; } = new(
        "", Array.Empty<string>(), ParseField.Empty, ParseField.Empty,
        ParseField.Empty, ParseField.Empty, ParseField.Empty, ParseField.Empty,
        Array.Empty<string>());

    public bool CanSubmit => !string.IsNullOrWhiteSpace(Callsign.Value);
    public string UnmatchedText => string.Join(' ', Unmatched);
}

public sealed record SessionInfo(
    long Id,
    string Name,
    string Date,
    string Status,
    int NextSequence,
    string OperatorCallsign = "",
    string RepeaterName = "",
    string WorkbookPath = "",
    string SheetName = "");

public sealed record CheckinEntry(
    long Id,
    long SessionId,
    int SequenceNo,
    string CheckinTime,
    string Callsign,
    string Qth,
    string Device,
    string Antenna,
    string Power,
    string Signal,
    string Source,
    string RawInput,
    string Unmatched,
    string UpdatedAt = "")
{
    public IReadOnlyList<string> UnmatchedTokens => Unmatched
        .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    public int UnmatchedCount => UnmatchedTokens.Count;
}

public sealed record ProfileValue(string Field, string Value, int UseCount, string LastUsed);

public sealed record QthCandidate(
    string Canonical,
    string Province,
    string City,
    string District,
    string Kind,
    int Priority = 100)
{
    public int Depth => !string.IsNullOrWhiteSpace(District) ? 3
        : !string.IsNullOrWhiteSpace(City) ? 2 : 1;
}

public sealed record DeviceCandidate(
    string StandardName,
    string Model,
    string DeviceClass,
    string Applicant,
    string Brand,
    string Source,
    double Confidence = 1.0);

public sealed record CatalogLoadReport(
    string DataRoot,
    int DeviceAliasCount,
    int QthAliasCount,
    int QthPlaceCount,
    int MiitModelCount,
    long ElapsedMilliseconds,
    string Message);

public enum FieldKind
{
    Time,
    Callsign,
    Qth,
    Device,
    Antenna,
    Power,
    Signal
}

public sealed record FieldEditRequest(
    long CheckinId,
    FieldKind Field,
    string CurrentValue,
    string RawInput,
    string UnmatchedCurrent,
    long SessionId,
    int SequenceNo,
    string Callsign,
    string ExpectedUpdatedAt);

public sealed record FieldParseResult(
    FieldKind Field,
    string RawEditText,
    string CanonicalValue,
    IReadOnlyList<string> Candidates,
    string Source,
    double Confidence,
    IReadOnlyList<string> ConsumedTokens,
    bool RequiresConfirmation = false)
{
    public bool HasValue => !string.IsNullOrWhiteSpace(CanonicalValue);
}

public sealed record FieldEditCommit(
    long CheckinId,
    FieldKind Field,
    string OldValue,
    string NewValue,
    string RawEditText,
    IReadOnlyList<string> ConsumedTokens,
    bool RemoveConsumedTokens,
    string ExpectedUpdatedAt,
    string Source = "人工编辑",
    IReadOnlyList<int>? ConsumedTokenIndexes = null);

public sealed record FieldEditAudit(
    long Id,
    long CheckinId,
    FieldKind Field,
    string OldValue,
    string NewValue,
    string OldUnmatched,
    string NewUnmatched,
    string ConsumedTokens,
    string Source,
    string AppliedAt);

public sealed record QthPackageNode(
    string Name,
    string Kind,
    string Status,
    string Detail,
    bool IsInstalled,
    bool HasUpdate,
    IReadOnlyList<QthPackageNode>? Children = null);

public sealed record ShortcutBinding(
    string ActionKey,
    string DisplayName,
    string Gesture,
    string Scope,
    string Description,
    bool IsGlobal = false);
