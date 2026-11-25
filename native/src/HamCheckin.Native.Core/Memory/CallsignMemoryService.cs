using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;

namespace HamCheckin.Native.Core.Memory;

/// <summary>
/// 按呼号读取历史并聚合出字段级记忆提示。数据全部派生自 checkins：
/// 保存与字段编辑都落在同一张表，因此无需写路径，下一次查询自然生效。
/// 不缓存——S1 只靠既有的 idx_checkins_callsign 索引和 LIMIT 约束。
/// </summary>
public sealed class CallsignMemoryService(NativeStore store)
{
    public const int HistoryLimit = 50;
    private const int MaxHintsPerField = 3;

    private static readonly FieldKind[] MemoryFields =
    [
        FieldKind.Qth,
        FieldKind.Device,
        FieldKind.Antenna,
        FieldKind.Power
    ];

    public async Task<CallsignMemorySnapshot> LoadAsync(
        string? callsign,
        CancellationToken cancellationToken = default)
    {
        var key = TextNormalizer.NormalizeCallsign(callsign);
        if (key.Length == 0)
        {
            return CallsignMemorySnapshot.Empty;
        }

        var rows = await store
            .LoadCallsignHistoryAsync(key, HistoryLimit, cancellationToken)
            .ConfigureAwait(false);
        return Build(key, rows);
    }

    private static CallsignMemorySnapshot Build(
        string callsign,
        IReadOnlyList<CallsignHistoryRow> rows)
    {
        var hints = new List<CallsignFieldHint>(MemoryFields.Length * MaxHintsPerField);
        foreach (var field in MemoryFields)
        {
            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            var latestIds = new Dictionary<string, long>(StringComparer.Ordinal);
            foreach (var row in rows)
            {
                var value = ReadValue(row, field);
                if (value.Length == 0)
                {
                    continue;
                }

                counts[value] = counts.TryGetValue(value, out var count) ? count + 1 : 1;
                // 查询按 id 倒序，某个值首次出现的行就是它最近一次使用。
                latestIds.TryAdd(value, row.Id);
            }

            hints.AddRange(counts
                .OrderByDescending(pair => pair.Value)
                .ThenByDescending(pair => latestIds[pair.Key])
                .Take(MaxHintsPerField)
                .Select(pair => new CallsignFieldHint(field, pair.Key, pair.Value)));
        }

        var lastTime = rows.Count == 0 ? string.Empty : rows[0].CheckinTime;
        return new CallsignMemorySnapshot(callsign, hints, lastTime);
    }

    private static string ReadValue(CallsignHistoryRow row, FieldKind field) => field switch
    {
        FieldKind.Qth => row.Qth.Trim(),
        FieldKind.Device => row.Device.Trim(),
        FieldKind.Antenna => row.Antenna.Trim(),
        FieldKind.Power => row.Power.Trim(),
        _ => throw new ArgumentOutOfRangeException(nameof(field), field, "呼号记忆只覆盖 QTH/设备/天线/功率")
    };
}
