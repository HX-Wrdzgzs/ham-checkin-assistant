using System.Diagnostics;
using System.Text.Encodings.Web;
using System.Text.Json;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;

var total = Stopwatch.StartNew();
var catalogService = new CatalogService();
var parser = new InputParser(catalogService);
var startup = Stopwatch.StartNew();
_ = parser.Parse("ba4rll qyt6900 5w yz yz");
startup.Stop();

var samples = new[]
{
    "ba4rll qyt6900 5w yz yz",
    "ba4aaa njxw pd780 4.2m 5w",
    "bh4abc r6 771 h 南京玄武",
    "bd4xyz uvk6 y 1w yz"
};
var timings = new double[20_000];
for (var index = 0; index < timings.Length; index++)
{
    var started = Stopwatch.GetTimestamp();
    _ = parser.Parse(samples[index % samples.Length]);
    timings[index] = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
}
Array.Sort(timings);

CatalogLoadReport? catalogReport = null;
double[]? externalTimings = null;
if (Directory.Exists(CatalogLoader.DefaultDataRoot))
{
    catalogReport = await catalogService.ReloadExistingDataAsync();
    externalTimings = new double[5_000];
    for (var index = 0; index < externalTimings.Length; index++)
    {
        var started = Stopwatch.GetTimestamp();
        _ = parser.Parse(samples[index % samples.Length]);
        externalTimings[index] = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
    }
    Array.Sort(externalTimings);
}

#pragma warning disable CA1861 // Created once per benchmark process, then enumerated once.
var recognitionCases = new[]
{
    "BA4RLL QYT6900 5W YZ YZ",
    "BA4AAA NJXW PD780 4.2M 5W",
    "BA4AAA R6 Y H NJXW",
    "BA4AAA UVK6 771 1W YZ",
    "BA4AAA XZ-991 5W MYSTERY"
}.Select(input =>
{
    var result = parser.Parse(input);
    return new
    {
        input,
        callsign = result.Callsign.Value,
        qth = result.Qth.Value,
        device = result.Device.Value,
        antenna = result.Antenna.Value,
        power = result.Power.Value,
        unmatched = result.UnmatchedText
    };
}).ToArray();
#pragma warning restore CA1861

var tempRoot = Path.Combine(Path.GetTempPath(), $"ham-native-bench-{Guid.NewGuid():N}");
var store = new NativeStore(Path.Combine(tempRoot, "bench.db"));
var storeInit = Stopwatch.StartNew();
await store.InitializeAsync();
var session = await store.GetOrCreateFirstSessionAsync(DateOnly.FromDateTime(DateTime.Today));
storeInit.Stop();

var commit = Stopwatch.StartNew();
for (var index = 0; index < 150; index++)
{
    var result = parser.Parse($"BA4A{index % 10}A qyt6900 5w yz yz");
    await store.AddCheckinAsync(session, result);
}
commit.Stop();
var quickCheck = await store.QuickCheckAsync();
await store.DisposeAsync();
Directory.Delete(tempRoot, true);
total.Stop();

var output = new
{
    runtime = Environment.Version.ToString(),
    os = Environment.OSVersion.ToString(),
    builtin_first_parse_ms = Math.Round(startup.Elapsed.TotalMilliseconds, 3),
    parser_iterations = timings.Length,
    parser_p50_ms = Math.Round(timings[(int)(timings.Length * 0.50)], 4),
    parser_p95_ms = Math.Round(timings[(int)(timings.Length * 0.95)], 4),
    parser_p99_ms = Math.Round(timings[(int)(timings.Length * 0.99)], 4),
    external_catalog = catalogReport is null ? null : new
    {
        load_ms = catalogReport.ElapsedMilliseconds,
        catalogReport.QthPlaceCount,
        catalogReport.QthAliasCount,
        catalogReport.DeviceAliasCount,
        catalogReport.MiitModelCount,
        parser_p50_ms = Math.Round(externalTimings![(int)(externalTimings.Length * 0.50)], 4),
        parser_p95_ms = Math.Round(externalTimings[(int)(externalTimings.Length * 0.95)], 4),
        parser_p99_ms = Math.Round(externalTimings[(int)(externalTimings.Length * 0.99)], 4)
    },
    recognition_cases = recognitionCases,
    sqlite_init_ms = Math.Round(storeInit.Elapsed.TotalMilliseconds, 3),
    sqlite_commits = 150,
    sqlite_commit_total_ms = Math.Round(commit.Elapsed.TotalMilliseconds, 3),
    sqlite_commit_avg_ms = Math.Round(commit.Elapsed.TotalMilliseconds / 150, 3),
    sqlite_quick_check = quickCheck,
    total_ms = Math.Round(total.Elapsed.TotalMilliseconds, 3)
};
#pragma warning disable CA1869 // One serialization at process exit; reuse has no benefit.
var jsonOptions = new JsonSerializerOptions
{
    WriteIndented = true,
    Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
};
#pragma warning restore CA1869
var json = JsonSerializer.Serialize(output, jsonOptions);
Console.WriteLine(json);
var outputIndex = Array.FindIndex(args,
    static value => string.Equals(value, "--output", StringComparison.OrdinalIgnoreCase));
if (outputIndex >= 0 && outputIndex + 1 < args.Length)
{
    var outputPath = Path.GetFullPath(args[outputIndex + 1]);
    Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
    File.WriteAllText(outputPath, json + Environment.NewLine);
}
