namespace HamCheckin.Native.Core.Storage;

internal static class ProfileAggregator
{
    public static IReadOnlyList<ProfileValue> Aggregate(
        IReadOnlyList<(string Qth, string Device, string Antenna, string Power, string At)> rows)
    {
        var result = new List<ProfileValue>(4);
        Add(result, "QTH", rows.Select(static row => (row.Qth, row.At)));
        Add(result, "设备", rows.Select(static row => (row.Device, row.At)));
        Add(result, "天线", rows.Select(static row => (row.Antenna, row.At)));
        Add(result, "功率", rows.Select(static row => (row.Power, row.At)));
        return result;
    }

    private static void Add(
        List<ProfileValue> destination,
        string field,
        IEnumerable<(string Value, string At)> values)
    {
        var top = values
            .Where(static item => !string.IsNullOrWhiteSpace(item.Value))
            .GroupBy(static item => item.Value, StringComparer.OrdinalIgnoreCase)
            .Select(group => new
            {
                Value = group.Key,
                Count = group.Count(),
                Last = group.Max(static item => item.At)
            })
            .OrderByDescending(static item => item.Count)
            .ThenByDescending(static item => item.Last)
            .FirstOrDefault();
        if (top is not null)
        {
            destination.Add(new ProfileValue(field, top.Value, top.Count, top.Last ?? string.Empty));
        }
    }
}
