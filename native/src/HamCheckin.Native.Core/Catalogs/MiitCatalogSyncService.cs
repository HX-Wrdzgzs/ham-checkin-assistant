using System.Globalization;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Catalogs;

public sealed record MiitSyncProgress(
    string SyncId,
    string Status,
    int CurrentPage,
    int TotalPages,
    int ScannedCount,
    int TotalCount,
    int RetainedCount,
    int ExcludedCount,
    int UnknownCount,
    int RetryCount,
    string Message);

public sealed record MiitSyncReport(
    string SyncId,
    string Status,
    int TotalCount,
    int ScannedCount,
    int RetainedCount,
    int ExcludedCount,
    int UnknownCount,
    int TotalPages,
    int CompletedPages,
    int RetryCount,
    string DatabasePath,
    string Message);

/// <summary>
/// 工信部“无线电发射设备型号核准”资料库同步器。
///
/// 网络请求、分类和资料库写入都在显式任务中执行，快速录入只读取上一次
/// 完整的正式快照。完整同步写入同目录 partial 数据库，成功后才替换正式库；
/// 取消或断网时保留断点，旧库继续可用。
/// </summary>
public sealed class MiitCatalogSyncService : IAsyncDisposable
{
    private const string GatewayUrl = "https://ythzxfw.miit.gov.cn/api-gateway/jpaas-jags-server/interface/gateway";
    private const string SourceUrl = "https://ythzxfw.miit.gov.cn/jgcx/index.html";
    private const string CategoryId = "352";
    private const string RuleVersion = "radio-v2";
    private static readonly int[] PageSizeFallbacks = { 1000, 500, 200, 100, 50, 20, 5 };
    private readonly string _catalogPath;
    private readonly string _partialPath;
    private readonly HttpClient _httpClient;

    public MiitCatalogSyncService(string? catalogPath = null, HttpClient? httpClient = null)
    {
        _catalogPath = catalogPath ?? AppPaths.MiitRadioCatalogPath;
        _partialPath = _catalogPath + ".partial.db";
        _httpClient = httpClient ?? new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(25)
        };
    }

    public string CatalogPath => _catalogPath;
    public string PartialPath => _partialPath;

    public Task<MiitSyncReport> StartAsync(
        bool full,
        IProgress<MiitSyncProgress>? progress = null,
        CancellationToken cancellationToken = default) =>
        SyncAsync(full, resume: false, progress, cancellationToken);

    public Task<MiitSyncReport> ResumeAsync(
        IProgress<MiitSyncProgress>? progress = null,
        CancellationToken cancellationToken = default) =>
        SyncAsync(full: true, resume: true, progress, cancellationToken);

    public async Task<MiitSyncReport> SyncAsync(
        bool full,
        bool resume,
        IProgress<MiitSyncProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (RuntimeOptions.DisableNetwork)
        {
            throw new InvalidOperationException("当前测试进程已禁用网络，未启动工信部同步。");
        }

        var directory = Path.GetDirectoryName(_catalogPath)
            ?? throw new InvalidOperationException("无法确定工信部资料库目录。");
        Directory.CreateDirectory(directory);

        if (!resume)
        {
            DeleteIfExists(_partialPath);
            DeleteIfExists(_partialPath + "-wal");
            DeleteIfExists(_partialPath + "-shm");
            if (!full && File.Exists(_catalogPath))
            {
                File.Copy(_catalogPath, _partialPath, true);
            }
        }
        else if (!File.Exists(_partialPath))
        {
            throw new InvalidOperationException("没有可继续的工信部同步断点。");
        }

        var syncId = $"miit-{DateTimeOffset.Now:yyyyMMddHHmmss}-{Guid.NewGuid():N}";
        var report = new SyncAccumulator(syncId, full ? "full" : "incremental");
        await using var connection = await OpenAsync(_partialPath, cancellationToken).ConfigureAwait(false);
        await EnsureSchemaAsync(connection, cancellationToken).ConfigureAwait(false);
        var checkpoint = resume ? await ReadCheckpointAsync(connection, cancellationToken).ConfigureAwait(false) : null;
        if (checkpoint is not null)
        {
            report = checkpoint.Accumulator with { SyncId = checkpoint.SyncId };
            syncId = report.SyncId;
        }
        else
        {
            await BeginRunAsync(connection, report, cancellationToken).ConfigureAwait(false);
        }

        var pageSize = checkpoint?.PageSize is > 0 and var savedPageSize ? savedPageSize : 1000;
        var logicalPage = checkpoint?.CurrentPage + 1 ?? 1;
        var requestPage = checkpoint?.RequestPage + 1 ?? 1;
        var firstPage = checkpoint is null;
        var maxPages = full ? int.MaxValue : 10;

        try
        {
            while (logicalPage <= maxPages)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var page = await FetchWithRetryAsync(requestPage, pageSize, firstPage, report,
                    cancellationToken).ConfigureAwait(false);
                firstPage = false;
                pageSize = page.PageSize;
                report.TotalCount = Math.Max(report.TotalCount, page.TotalCount);
                report.TotalPages = report.TotalCount == 0 ? 1 : Math.Max(1, (int)Math.Ceiling(report.TotalCount / (double)pageSize));
                if (page.Rows.Count == 0)
                {
                    if (full && report.TotalCount > report.ScannedCount)
                    {
                        throw new InvalidOperationException($"第 {logicalPage} 页为空，但官网总数为 {report.TotalCount}，分页不完整。");
                    }
                    break;
                }

                var pageIds = new HashSet<string>(StringComparer.Ordinal);
                await using (var transaction = await connection.BeginTransactionAsync(
                    System.Data.IsolationLevel.Serializable, cancellationToken).ConfigureAwait(false))
                {
                    foreach (var row in page.Rows)
                    {
                        var articleId = StableArticleId(row.RawJson, row.ArticleId);
                        if (!pageIds.Add(articleId))
                        {
                            throw new InvalidOperationException($"第 {logicalPage} 页返回重复记录 ID：{articleId}");
                        }
                        if (!await TryMarkSeenAsync(connection, (SqliteTransaction)transaction,
                                syncId, articleId, cancellationToken).ConfigureAwait(false))
                        {
                            continue;
                        }

                        report.ScannedCount++;
                        switch (row.Kind)
                        {
                            case MiitRowKind.Retained:
                                await UpsertDeviceAsync(connection, (SqliteTransaction)transaction,
                                    row.Device!, cancellationToken).ConfigureAwait(false);
                                report.RetainedCount++;
                                break;
                            case MiitRowKind.Excluded:
                                report.ExcludedCount++;
                                break;
                            default:
                                report.UnknownCount++;
                                await AddUnknownNameAsync(connection, (SqliteTransaction)transaction,
                                    syncId, row.DeviceName, cancellationToken).ConfigureAwait(false);
                                break;
                        }
                    }
                    report.CompletedPages = logicalPage;
                    await UpdateRunAndCheckpointAsync(connection, (SqliteTransaction)transaction,
                        report, pageSize, requestPage, cancellationToken).ConfigureAwait(false);
                    await transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
                }

                Report(progress, report, "running", $"已完成第 {logicalPage}/{Math.Max(1, report.TotalPages)} 页");
                if (full && report.TotalCount > 0 && report.ScannedCount >= report.TotalCount)
                {
                    break;
                }
                if (page.Rows.Count < pageSize && (!full || report.TotalCount == 0 || report.ScannedCount >= report.TotalCount))
                {
                    break;
                }
                logicalPage++;
                requestPage += Math.Max(1, pageSize / 5);
            }

            if (full && report.TotalCount > 0 && report.ScannedCount < report.TotalCount)
            {
                throw new InvalidOperationException($"同步结束但只扫描 {report.ScannedCount}/{report.TotalCount} 条，拒绝替换正式库。");
            }

            var quickCheck = await QuickCheckAsync(connection, cancellationToken).ConfigureAwait(false);
            if (!string.Equals(quickCheck, "ok", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException($"临时资料库 quick_check 失败：{quickCheck}");
            }
            await CompleteRunAsync(connection, report, cancellationToken).ConfigureAwait(false);
            await CheckpointWalAsync(connection, cancellationToken).ConfigureAwait(false);
            await connection.CloseAsync().ConfigureAwait(false);
            // CloseAsync 将连接状态置为 Closed，但 Windows 下 SQLite 的文件句柄
            // 仍可能由连接对象持有；原子替换前必须释放底层句柄。
            await connection.DisposeAsync().ConfigureAwait(false);
            await ReplaceFormalCatalogAsync().ConfigureAwait(false);
            var message = full
                ? "完整同步完成，已原子替换正式电台型号库"
                : "最新页面检查完成，已合并到正式电台型号库";
            Report(progress, report, "completed", message);
            return report.ToReport("completed", _catalogPath, message);
        }
        catch (OperationCanceledException)
        {
            if (connection.State == System.Data.ConnectionState.Open)
            {
                await MarkRunAsync(connection, report, "cancelled", "用户取消；断点已保留", CancellationToken.None).ConfigureAwait(false);
            }
            Report(progress, report, "cancelled", "已取消，上一份正式库继续可用；可点击继续");
            throw;
        }
        catch (Exception exception)
        {
            if (connection.State == System.Data.ConnectionState.Open)
            {
                try
                {
                    await MarkRunAsync(connection, report, "failed", exception.Message, CancellationToken.None).ConfigureAwait(false);
                }
                catch (Exception markException)
                {
                    exception = new AggregateException("同步失败，且无法写入失败状态。", exception, markException);
                }
            }
            Report(progress, report, "failed", exception.Message);
            throw;
        }
    }

    private async Task<PageResult> FetchWithRetryAsync(int requestPage, int requestedPageSize,
        bool firstPage, SyncAccumulator report, CancellationToken cancellationToken)
    {
        var sizes = firstPage ? PageSizeFallbacks : new[] { Math.Clamp(requestedPageSize, 5, 1000) };
        Exception? lastError = null;
        foreach (var size in sizes)
        {
            for (var attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    var result = await FetchPageAsync(requestPage, size, cancellationToken).ConfigureAwait(false);
                    return result with { PageSize = size };
                }
                catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException or InvalidOperationException)
                {
                    lastError = exception;
                    if (attempt < 2)
                    {
                        report.RetryCount++;
                        await Task.Delay(TimeSpan.FromMilliseconds(500 * (1 << attempt)), cancellationToken).ConfigureAwait(false);
                    }
                }
            }
        }
        throw new InvalidOperationException($"工信部第 {requestPage} 页读取失败：{lastError?.Message ?? "未知错误"}", lastError);
    }

    private async Task<PageResult> FetchPageAsync(int page, int pageSize, CancellationToken cancellationToken)
    {
        var biz = JsonSerializer.Serialize(new
        {
            notOnePage = "",
            categoryId = CategoryId,
            currentPage = page,
            pageSize,
            searchContent = ""
        });
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString(CultureInfo.InvariantCulture);
        var values = new List<KeyValuePair<string, string>>
        {
            new("app_id", "bjgxb"),
            new("biz_content", biz),
            new("charset", "UTF-8"),
            new("interface_id", "queryResultPublicity2"),
            new("origin", "0"),
            new("timestamp", timestamp),
            new("version", "1.0")
        };
        var signingPayload = string.Join('&', values.Select(static item => $"{item.Key}={item.Value}"));
        values.Add(new KeyValuePair<string, string>("sign", Sm3.HashHex(signingPayload)));
        using var content = new FormUrlEncodedContent(values);
        using var response = await _httpClient.PostAsync(GatewayUrl, content, cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var outer = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        var root = outer.RootElement;
        if (!root.TryGetProperty("success", out var success) || !success.GetBoolean()
            || !root.TryGetProperty("data", out var data))
        {
            throw new InvalidOperationException("工信部查询没有返回有效数据。");
        }
        using var inner = JsonDocument.Parse(data.GetString() ?? data.GetRawText());
        var pageData = inner.RootElement.GetProperty("data").GetProperty("tbAppArticle");
        var total = pageData.TryGetProperty("total", out var totalElement) && totalElement.TryGetInt32(out var totalValue)
            ? totalValue : 0;
        var listProperty = pageData.TryGetProperty("list", out var list) ? list : pageData.GetProperty("records");
        var rows = new List<MiitRow>();
        foreach (var item in listProperty.EnumerateArray())
        {
            rows.Add(ParseRow(item));
        }
        return new PageResult(total, rows, pageSize);
    }

    private static MiitRow ParseRow(JsonElement element)
    {
        var raw = element.GetRawText();
        var articleId = Clean(element, "articleId");
        var model = Clean(element, "articleField03");
        var deviceName = Clean(element, "articleField02");
        var applicant = Clean(element, "articleField04");
        var cleanName = deviceName.ToLowerInvariant();
        var includes = new (string Term, string Class)[]
        {
            ("调频手持台", "手持台"), ("业余手持台", "手持台"), ("调频手台", "手持台"),
            ("手持台", "手持台"), ("调频车载台", "车载台"), ("车载台", "车载台"),
            ("公众对讲机", "对讲机"), ("对讲机", "对讲机"), ("基地台", "基地台"),
            ("固定台", "固定台"), ("中继台", "中继台"), ("中转台", "中转台"),
            ("转发台", "转发台"), ("收发信机", "收发信机"), ("短波电台", "短波电台"),
            ("单边带电台", "单边带电台"), ("业余无线电设备", "业余无线电设备"),
            ("无线电台", "无线电台"), ("调频电台", "无线电台")
        };
        var match = includes.FirstOrDefault(item => cleanName.Contains(item.Term, StringComparison.OrdinalIgnoreCase));
        var excludes = new[] { "蓝牙", "bluetooth", "wlan", "wapi", "zigbee", "uwb", "nfc", "rfid", "lora", "nb-iot", "lte", "4g", "5g", "gsm", "模块", "模组", "芯片", "手机", "平板", "笔记本", "路由器", "网关", "遥控器", "无线钥匙", "标签", "读写器", "定位终端", "数据终端", "物联网终端", "无线充电", "雷达", "广播发射机", "电视发射机" };
        if (string.IsNullOrWhiteSpace(model))
        {
            return new MiitRow(articleId, deviceName, raw, null, MiitRowKind.Unknown);
        }
        if (string.IsNullOrWhiteSpace(match.Term))
        {
            return new MiitRow(articleId, deviceName, raw, null,
                excludes.Any(term => cleanName.Contains(term, StringComparison.OrdinalIgnoreCase)) ? MiitRowKind.Excluded : MiitRowKind.Unknown);
        }

        var brand = BrandFrom(applicant, model);
        var device = new MiitRadioDeviceRecord(
            StableArticleId(raw, articleId), CategoryId, $"{brand} {model}".Trim(), model,
            NormalizeModel(model), deviceName, match.Class, applicant, brand,
            Clean(element, "articleField01"), Clean(element, "articleField05"), Clean(element, "articleField06"),
            Clean(element, "articleField07"), Clean(element, "articleField08"), Clean(element, "articleField09"),
            Clean(element, "articleField10"), Clean(element, "articleField11"), Clean(element, "articleField12"),
            Clean(element, "articleField13"), Clean(element, "articleField14"), Clean(element, "articleField15"),
            Clean(element, "articleField16"), Clean(element, "createTime"), Clean(element, "delFlag"),
            Clean(element, "resultShowFlag"), SourceUrl,
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(raw))).ToLowerInvariant(),
            RuleVersion, raw, DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture));
        return new MiitRow(device.ArticleId, deviceName, raw, device, MiitRowKind.Retained);
    }

    private static string Clean(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value)) return string.Empty;
        var text = value.ValueKind == JsonValueKind.String ? value.GetString() ?? string.Empty : value.ToString();
        text = System.Net.WebUtility.HtmlDecode(text);
        return string.Join(' ', text.Replace('\u3000', ' ').Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    private static string NormalizeModel(string value) =>
        new string(value.Where(static character => char.IsLetterOrDigit(character) || (character >= '\u4e00' && character <= '\u9fff')).ToArray()).ToLowerInvariant();

    private static string StableArticleId(string rawJson, string articleId) =>
        string.IsNullOrWhiteSpace(articleId)
            ? "row-" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(rawJson))).ToLowerInvariant()
            : articleId;

    private static string BrandFrom(string applicant, string model)
    {
        var value = $"{applicant} {model}".ToLowerInvariant();
        foreach (var pair in new[] { ("泉盛", "泉盛"), ("全易通", "全易通"), ("motorola", "摩托罗拉"), ("摩托罗拉", "摩托罗拉"), ("hytera", "海能达"), ("海能达", "海能达"), ("icom", "ICOM"), ("八重洲", "YAESU"), ("yaesu", "YAESU"), ("宝锋", "宝锋"), ("baofeng", "宝锋"), ("建伍", "KENWOOD") })
        {
            if (value.Contains(pair.Item1, StringComparison.OrdinalIgnoreCase)) return pair.Item2;
        }
        return string.Empty;
    }

    private static async Task<SqliteConnection> OpenAsync(string path, CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
            // 同步结束后会原子替换这个临时数据库；不能把连接放回池中，
            // 否则 Windows 仍可能保留文件句柄并阻止 File.Move/File.Replace。
            Pooling = false
        }.ToString());
        await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
        return connection;
    }

    private static async Task EnsureSchemaAsync(SqliteConnection connection, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS miit_radio_devices(
                article_id TEXT PRIMARY KEY, category_id TEXT NOT NULL DEFAULT '', standard_name TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', normalized_model TEXT NOT NULL DEFAULT '', device_name TEXT NOT NULL DEFAULT '', device_class TEXT NOT NULL DEFAULT '', applicant TEXT NOT NULL DEFAULT '', brand TEXT NOT NULL DEFAULT '', certificate_no TEXT NOT NULL DEFAULT '', remarks TEXT NOT NULL DEFAULT '', valid_for TEXT NOT NULL DEFAULT '', frequency_tolerance TEXT NOT NULL DEFAULT '', frequency_range TEXT NOT NULL DEFAULT '', transmit_power TEXT NOT NULL DEFAULT '', bandwidth TEXT NOT NULL DEFAULT '', spurious_emission_limit TEXT NOT NULL DEFAULT '', approved_at TEXT NOT NULL DEFAULT '', approval_code TEXT NOT NULL DEFAULT '', cmiit_id TEXT NOT NULL DEFAULT '', modulation TEXT NOT NULL DEFAULT '', technical_system TEXT NOT NULL DEFAULT '', create_time TEXT NOT NULL DEFAULT '', deleted_flag TEXT NOT NULL DEFAULT '', display_flag TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT '', filter_rule_version TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL DEFAULT '', last_seen_at TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS idx_miit_radio_model ON miit_radio_devices(normalized_model);
            CREATE TABLE IF NOT EXISTS miit_sync_runs(sync_id TEXT PRIMARY KEY, sync_type TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, total_count INTEGER NOT NULL DEFAULT 0, scanned_count INTEGER NOT NULL DEFAULT 0, retained_count INTEGER NOT NULL DEFAULT 0, excluded_count INTEGER NOT NULL DEFAULT 0, unknown_count INTEGER NOT NULL DEFAULT 0, total_pages INTEGER NOT NULL DEFAULT 0, completed_pages INTEGER NOT NULL DEFAULT 0, retry_count INTEGER NOT NULL DEFAULT 0, page_size INTEGER NOT NULL DEFAULT 1000, last_error TEXT NOT NULL DEFAULT '', rule_version TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS miit_sync_checkpoint(singleton INTEGER PRIMARY KEY CHECK(singleton=1), sync_id TEXT NOT NULL, current_page INTEGER NOT NULL DEFAULT 0, request_page INTEGER NOT NULL DEFAULT 0, page_size INTEGER NOT NULL DEFAULT 1000, scanned_count INTEGER NOT NULL DEFAULT 0, total_count INTEGER NOT NULL DEFAULT 0, last_article_id TEXT NOT NULL DEFAULT '', staging_path TEXT NOT NULL DEFAULT '', last_success_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS miit_sync_seen_ids(sync_id TEXT NOT NULL, article_id TEXT NOT NULL, PRIMARY KEY(sync_id, article_id));
            CREATE TABLE IF NOT EXISTS miit_unknown_names(sync_id TEXT NOT NULL, device_name TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(sync_id, device_name));
            CREATE TABLE IF NOT EXISTS miit_radio_devices_fts(article_id TEXT, normalized_model TEXT, model TEXT, standard_name TEXT, device_name TEXT, applicant TEXT, brand TEXT, certificate_no TEXT, approval_code TEXT, cmiit_id TEXT);
            """;
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task BeginRunAsync(SqliteConnection connection, SyncAccumulator report, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "INSERT INTO miit_sync_runs(sync_id,sync_type,started_at,status,rule_version,updated_at) VALUES($id,$type,$now,'running',$rule,$now); DELETE FROM miit_sync_checkpoint; DELETE FROM miit_sync_seen_ids WHERE sync_id=$id;";
        Add(command, "$id", report.SyncId); Add(command, "$type", report.SyncType); Add(command, "$rule", RuleVersion);
        Add(command, "$now", DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture));
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task<Checkpoint?> ReadCheckpointAsync(SqliteConnection connection, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT sync_id,current_page,request_page,page_size,scanned_count,total_count FROM miit_sync_checkpoint WHERE singleton=1";
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        if (!await reader.ReadAsync(cancellationToken).ConfigureAwait(false)) return null;
        var syncId = reader.GetString(0);
        var currentPage = reader.GetInt32(1);
        var requestPage = reader.GetInt32(2);
        var pageSize = reader.GetInt32(3);
        await reader.DisposeAsync().ConfigureAwait(false);
        var run = await ReadAccumulatorAsync(connection, syncId, cancellationToken).ConfigureAwait(false);
        return new Checkpoint(syncId, currentPage, requestPage, pageSize, run);
    }

    private static async Task<SyncAccumulator> ReadAccumulatorAsync(SqliteConnection connection, string syncId, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT sync_type,total_count,scanned_count,retained_count,excluded_count,unknown_count,total_pages,completed_pages,retry_count FROM miit_sync_runs WHERE sync_id=$id";
        Add(command, "$id", syncId);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false);
        if (!await reader.ReadAsync(cancellationToken).ConfigureAwait(false)) throw new InvalidOperationException("找不到工信部同步断点记录。");
        return new SyncAccumulator(syncId, reader.GetString(0)) { TotalCount = reader.GetInt32(1), ScannedCount = reader.GetInt32(2), RetainedCount = reader.GetInt32(3), ExcludedCount = reader.GetInt32(4), UnknownCount = reader.GetInt32(5), TotalPages = reader.GetInt32(6), CompletedPages = reader.GetInt32(7), RetryCount = reader.GetInt32(8) };
    }

    private static async Task<bool> TryMarkSeenAsync(SqliteConnection connection, SqliteTransaction transaction, string syncId, string articleId, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "INSERT OR IGNORE INTO miit_sync_seen_ids(sync_id,article_id) VALUES($sync,$article); SELECT changes();";
        Add(command, "$sync", syncId); Add(command, "$article", articleId);
        return Convert.ToInt32(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false), CultureInfo.InvariantCulture) == 1;
    }

    private static async Task UpsertDeviceAsync(SqliteConnection connection, SqliteTransaction transaction, MiitRadioDeviceRecord device, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = """
            INSERT INTO miit_radio_devices(article_id,category_id,standard_name,model,normalized_model,device_name,device_class,applicant,brand,certificate_no,remarks,valid_for,frequency_tolerance,frequency_range,transmit_power,bandwidth,spurious_emission_limit,approved_at,approval_code,cmiit_id,modulation,technical_system,create_time,deleted_flag,display_flag,source_url,content_hash,filter_rule_version,raw_json,first_seen_at,last_seen_at)
            VALUES($article,$category,$standard,$model,$normalized,$name,$class,$applicant,$brand,$certificate,$remarks,$valid,$tolerance,$range,$power,$bandwidth,$spurious,$approved,$approval,$cmiit,$modulation,$technical,$create,$deleted,$display,$url,$hash,$rule,$raw,$first,$last)
            ON CONFLICT(article_id) DO UPDATE SET standard_name=excluded.standard_name,model=excluded.model,normalized_model=excluded.normalized_model,device_name=excluded.device_name,device_class=excluded.device_class,applicant=excluded.applicant,brand=excluded.brand,certificate_no=excluded.certificate_no,remarks=excluded.remarks,valid_for=excluded.valid_for,frequency_tolerance=excluded.frequency_tolerance,frequency_range=excluded.frequency_range,transmit_power=excluded.transmit_power,bandwidth=excluded.bandwidth,spurious_emission_limit=excluded.spurious_emission_limit,approved_at=excluded.approved_at,approval_code=excluded.approval_code,cmiit_id=excluded.cmiit_id,modulation=excluded.modulation,technical_system=excluded.technical_system,create_time=excluded.create_time,deleted_flag=excluded.deleted_flag,display_flag=excluded.display_flag,source_url=excluded.source_url,content_hash=excluded.content_hash,filter_rule_version=excluded.filter_rule_version,raw_json=excluded.raw_json,last_seen_at=excluded.last_seen_at;
            INSERT INTO miit_radio_devices_fts(article_id,normalized_model,model,standard_name,device_name,applicant,brand,certificate_no,approval_code,cmiit_id) VALUES($article,$normalized,$model,$standard,$name,$applicant,$brand,$certificate,$approval,$cmiit);
            """;
        var values = new[] { ("$article", device.ArticleId), ("$category", device.CategoryId), ("$standard", device.StandardName), ("$model", device.Model), ("$normalized", device.NormalizedModel), ("$name", device.DeviceName), ("$class", device.DeviceClass), ("$applicant", device.Applicant), ("$brand", device.Brand), ("$certificate", device.CertificateNo), ("$remarks", device.Remarks), ("$valid", device.ValidFor), ("$tolerance", device.FrequencyTolerance), ("$range", device.FrequencyRange), ("$power", device.TransmitPower), ("$bandwidth", device.Bandwidth), ("$spurious", device.SpuriousEmissionLimit), ("$approved", device.ApprovedAt), ("$approval", device.ApprovalCode), ("$cmiit", device.CmiitId), ("$modulation", device.Modulation), ("$technical", device.TechnicalSystem), ("$create", device.CreateTime), ("$deleted", device.DeletedFlag), ("$display", device.DisplayFlag), ("$url", device.SourceUrl), ("$hash", device.ContentHash), ("$rule", device.RuleVersion), ("$raw", device.RawJson), ("$first", device.FirstSeenAt), ("$last", device.FirstSeenAt) };
        foreach (var (name, value) in values) Add(command, name, value);
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task AddUnknownNameAsync(SqliteConnection connection, SqliteTransaction transaction, string syncId, string deviceName, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = "INSERT INTO miit_unknown_names(sync_id,device_name,count) VALUES($sync,$name,1) ON CONFLICT(sync_id,device_name) DO UPDATE SET count=count+1"; Add(command, "$sync", syncId); Add(command, "$name", string.IsNullOrWhiteSpace(deviceName) ? "（设备名称为空）" : deviceName); await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task UpdateRunAndCheckpointAsync(SqliteConnection connection, SqliteTransaction transaction, SyncAccumulator report, int pageSize, int requestPage, CancellationToken cancellationToken)
    {
        var now = DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture);
        await using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "UPDATE miit_sync_runs SET total_count=$total,scanned_count=$scanned,retained_count=$retained,excluded_count=$excluded,unknown_count=$unknown,total_pages=$pages,completed_pages=$completed,retry_count=$retries,page_size=$size,updated_at=$now WHERE sync_id=$id; INSERT INTO miit_sync_checkpoint(singleton,sync_id,current_page,request_page,page_size,scanned_count,total_count,last_article_id,staging_path,last_success_at) VALUES(1,$id,$completed,$request,$size,$scanned,$total,'',$path,$now) ON CONFLICT(singleton) DO UPDATE SET sync_id=excluded.sync_id,current_page=excluded.current_page,request_page=excluded.request_page,page_size=excluded.page_size,scanned_count=excluded.scanned_count,total_count=excluded.total_count,staging_path=excluded.staging_path,last_success_at=excluded.last_success_at";
        Add(command, "$id", report.SyncId); Add(command, "$total", report.TotalCount); Add(command, "$scanned", report.ScannedCount); Add(command, "$retained", report.RetainedCount); Add(command, "$excluded", report.ExcludedCount); Add(command, "$unknown", report.UnknownCount); Add(command, "$pages", report.TotalPages); Add(command, "$completed", report.CompletedPages); Add(command, "$retries", report.RetryCount); Add(command, "$size", pageSize); Add(command, "$request", requestPage); Add(command, "$path", ""); Add(command, "$now", now);
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task CompleteRunAsync(SqliteConnection connection, SyncAccumulator report, CancellationToken cancellationToken) => await MarkRunAsync(connection, report, "completed", "", cancellationToken).ConfigureAwait(false);

    private static async Task MarkRunAsync(SqliteConnection connection, SyncAccumulator report, string status, string error, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand(); command.CommandText = "UPDATE miit_sync_runs SET status=$status,last_error=$error,ended_at=$ended,updated_at=$ended WHERE sync_id=$id"; Add(command, "$status", status); Add(command, "$error", error); Add(command, "$id", report.SyncId); Add(command, "$ended", DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture)); await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task<string> QuickCheckAsync(SqliteConnection connection, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand(); command.CommandText = "PRAGMA quick_check"; return Convert.ToString(await command.ExecuteScalarAsync(cancellationToken).ConfigureAwait(false), CultureInfo.InvariantCulture) ?? "unknown";
    }

    private async Task ReplaceFormalCatalogAsync()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_catalogPath)!);
        DeleteIfExists(_catalogPath + "-wal");
        DeleteIfExists(_catalogPath + "-shm");
        if (File.Exists(_catalogPath))
        {
            var backup = _catalogPath + ".previous";
            DeleteIfExists(backup);
            File.Replace(_partialPath, _catalogPath, backup, true);
            DeleteIfExists(backup);
        }
        else
        {
            File.Move(_partialPath, _catalogPath, true);
        }
        await Task.CompletedTask.ConfigureAwait(false);
    }

    private static async Task CheckpointWalAsync(SqliteConnection connection, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA wal_checkpoint(TRUNCATE)";
        await command.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
    }

    private static void Report(IProgress<MiitSyncProgress>? progress, SyncAccumulator report, string status, string message) => progress?.Report(report.ToProgress(status, message));
    private static void Add(SqliteCommand command, string name, object value) => command.Parameters.AddWithValue(name, value ?? string.Empty);
    private static void DeleteIfExists(string path) { if (File.Exists(path)) File.Delete(path); }

    public ValueTask DisposeAsync() { _httpClient.Dispose(); return ValueTask.CompletedTask; }

    private sealed record PageResult(int TotalCount, IReadOnlyList<MiitRow> Rows, int PageSize);
    private sealed record MiitRow(string ArticleId, string DeviceName, string RawJson, MiitRadioDeviceRecord? Device, MiitRowKind Kind);
    private enum MiitRowKind { Retained, Excluded, Unknown }
    private sealed record Checkpoint(string SyncId, int CurrentPage, int RequestPage, int PageSize, SyncAccumulator Accumulator);

    private sealed record MiitRadioDeviceRecord(
        string ArticleId, string CategoryId, string StandardName, string Model, string NormalizedModel,
        string DeviceName, string DeviceClass, string Applicant, string Brand, string CertificateNo,
        string Remarks, string ValidFor, string FrequencyTolerance, string FrequencyRange, string TransmitPower,
        string Bandwidth, string SpuriousEmissionLimit, string ApprovedAt, string ApprovalCode, string CmiitId,
        string Modulation, string TechnicalSystem, string CreateTime, string DeletedFlag, string DisplayFlag,
        string SourceUrl, string ContentHash, string RuleVersion, string RawJson, string FirstSeenAt);

    private sealed record SyncAccumulator(string SyncId, string SyncType)
    {
        public int TotalCount { get; set; }
        public int ScannedCount { get; set; }
        public int RetainedCount { get; set; }
        public int ExcludedCount { get; set; }
        public int UnknownCount { get; set; }
        public int TotalPages { get; set; }
        public int CompletedPages { get; set; }
        public int RetryCount { get; set; }
        public MiitSyncProgress ToProgress(string status, string message) => new(SyncId, status, CompletedPages, TotalPages, ScannedCount, TotalCount, RetainedCount, ExcludedCount, UnknownCount, RetryCount, message);
        public MiitSyncReport ToReport(string status, string path, string message) => new(SyncId, status, TotalCount, ScannedCount, RetainedCount, ExcludedCount, UnknownCount, TotalPages, CompletedPages, RetryCount, path, message);
    }
}
