namespace HamCheckin.Native.Core.Memory;

/// <summary>
/// 一条历史签到记录的只读投影，只包含呼号记忆需要的列。
/// </summary>
public sealed record CallsignHistoryRow(
    long Id,
    string CheckinTime,
    string Qth,
    string Device,
    string Antenna,
    string Power);

/// <summary>
/// 某呼号某个字段的历史取值。UseCount 是最近 <see cref="CallsignMemoryService.HistoryLimit"/>
/// 条记录内的出现次数。
/// </summary>
public sealed record CallsignFieldHint(
    FieldKind Field,
    string Value,
    int UseCount);

/// <summary>
/// 按呼号聚合出的记忆快照。全部派生自 checkins，没有独立表或缓存。
/// </summary>
public sealed record CallsignMemorySnapshot(
    string Callsign,
    IReadOnlyList<CallsignFieldHint> Fields,
    string LastCheckinTime)
{
    public static CallsignMemorySnapshot Empty { get; } = new(
        string.Empty,
        Array.Empty<CallsignFieldHint>(),
        string.Empty);
}
