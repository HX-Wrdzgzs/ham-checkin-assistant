using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Windows.Input;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Export;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.Core.Updates;

namespace HamCheckin.Native.App.ViewModels;

public sealed class MainViewModel : ObservableObject, IAsyncDisposable
{
    private readonly CatalogService _catalogService;
    private readonly InputParser _parser;
    private readonly FieldParser _fieldParser;
    private readonly NativeStore? _store;
    private readonly MiitCatalogSyncService _miitSyncService;
    private readonly string? _catalogDataRoot;
    private readonly ExcelExportService _exporter = new();
    private readonly QuickInputDraftService _draftService = new();
    private readonly NativeUpdateService _updates;
    private CancellationTokenSource? _catalogCancellation;
    private CancellationTokenSource? _updateCancellation;
    private SessionInfo? _session;
    private ParseResult _parseResult = ParseResult.Empty;
    private string _callsign = string.Empty;
    private string _qth = string.Empty;
    private string _device = string.Empty;
    private string _antenna = string.Empty;
    private string _power = string.Empty;
    private string _signal = string.Empty;
    private string _unmatched = string.Empty;
    private string _sessionTitle = "第1场点名";
    private string _sessionDate = RuntimeOptions.Today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    private string _operatorCallsign = string.Empty;
    private string _repeaterName = "江苏省中继";
    private string _sessionStatus = "进行中";
    private string _statusMessage = "正在准备本地录入…";
    private string _taskSummary = "无后台任务";
    private string _catalogSummary = "内置现场词典可立即使用；资料库在后台加载";
    private string _catalogQuery = string.Empty;
    private string _miitStatus = "尚未下载工信部电台型号库";
    private string _locationStatus = "全国行政区基础索引；详细地点按省市包管理";
    private string _updateStatus = $"启动后后台检查更新 · 当前 {NativeVersion.Current}";
    private string _databasePath = AppPaths.NativeDatabasePath;
    private string _currentPage = "Quick";
    private bool _isReady;
    private bool _initializationComplete;
    private bool _animationsEnabled = true;
    private bool _isCatalogBusy;
    private int _nextSequence = 1;
    private long _parsedInputRevision = -1;
    private long _selectedQthRevision = -1;
    private string _selectedQthRaw = string.Empty;
    private string _selectedQthCanonical = string.Empty;
    private long _lastParseMicroseconds;

    public MainViewModel()
        : this(new CatalogService(), new NativeStore())
    {
    }

    internal MainViewModel(
        CatalogService catalogService,
        NativeStore? store,
        NativeUpdateService? updates = null,
        string? catalogDataRoot = null,
        bool importLegacyDatabase = true)
    {
        _catalogService = catalogService;
        _parser = new InputParser(catalogService);
        _fieldParser = new FieldParser(catalogService);
        _store = store;
        _updates = updates ?? new NativeUpdateService();
        _catalogDataRoot = catalogDataRoot;
        ImportLegacyDatabase = importLegacyDatabase;
        _miitSyncService = new MiitCatalogSyncService();
        _draftService.Changed += DraftService_Changed;
        SubmitCommand = new AsyncRelayCommand(
            SubmitAsync,
            () => IsReady && _parseResult.CanSubmit && _session?.Status == "active",
            SetFailure);
        SearchCatalogCommand = new RelayCommand(SearchCatalog);
        ClearCommand = new RelayCommand(() => SetInputText(string.Empty));
        ExportCommand = new AsyncRelayCommand(() => ExportCurrentAsync(), null, SetFailure);
        RefreshCatalogCommand = new AsyncRelayCommand(() => RefreshCatalogAsync(false), null, SetFailure);
        FirstMiitDownloadCommand = new AsyncRelayCommand(() => RefreshCatalogAsync(true), null, SetFailure);
        FullMiitDownloadCommand = new AsyncRelayCommand(() => RefreshCatalogAsync(true), null, SetFailure);
        ResumeMiitCommand = new AsyncRelayCommand(ResumeMiitAsync, null, SetFailure);
        CancelMiitCommand = new RelayCommand(CancelCatalog);
        ResetShortcuts();
    }

    public event EventHandler? ParseUpdated;
    public event EventHandler? SubmissionSucceeded;
    public event EventHandler? CheckinsChanged;
    public event EventHandler? QuickWindowRequested;
    public event EventHandler<ShortcutChangedEventArgs>? ShortcutsChanged;
    public event EventHandler<QuickInputDraftChangedEventArgs>? InputDraftChanged;

    /// <summary>
    /// Exposed only to isolated UI tests so the test can await the launch
    /// check without sleeping or relying on a real GitHub request.
    /// </summary>
    internal Task? StartupUpdateCheckTask { get; private set; }

    private bool ImportLegacyDatabase { get; }

    public ObservableCollection<CheckinEntry> Checkins { get; } = new();
    public IEnumerable<CheckinEntry> RecentCheckins => Checkins.Take(3);
    public ObservableCollection<DeviceCandidate> CatalogResults { get; } = new();
    public ObservableCollection<ShortcutBinding> ShortcutBindings { get; } = new();
    public ObservableCollection<QthPackageNode> QthPackages { get; } = new();
    public ObservableCollection<string> QthCandidates { get; } = new();

    public ICommand SubmitCommand { get; }
    public ICommand SearchCatalogCommand { get; }
    public ICommand ClearCommand { get; }
    public ICommand ExportCommand { get; }
    public ICommand RefreshCatalogCommand { get; }
    public ICommand FirstMiitDownloadCommand { get; }
    public ICommand FullMiitDownloadCommand { get; }
    public ICommand ResumeMiitCommand { get; }
    public ICommand CancelMiitCommand { get; }

    public string InputText => _draftService.Current.Text;
    public long InputRevision => _draftService.Current.Revision;
    public QuickInputDraftSnapshot InputDraft => _draftService.Current;

    public void SetInputText(string? text) => _draftService.SetProgrammatic(text);

    public QuickInputDraftSnapshot ApplyInputEdit(
        string originId,
        long baseRevision,
        string text,
        bool isImeComposing = false,
        bool isActiveEditor = true) =>
        _draftService.ApplyUserEdit(originId, baseRevision, text, isImeComposing, isActiveEditor);

    public QuickInputDraftSnapshot SetImeCompositionState(string originId, bool isComposing) =>
        _draftService.SetImeCompositionState(originId, isComposing);

    public string Callsign { get => _callsign; private set => SetProperty(ref _callsign, value); }
    public string Qth { get => _qth; private set => SetProperty(ref _qth, value); }
    public string Device { get => _device; private set => SetProperty(ref _device, value); }
    public string Antenna { get => _antenna; private set => SetProperty(ref _antenna, value); }
    public string Power { get => _power; private set => SetProperty(ref _power, value); }
    public string Signal { get => _signal; private set => SetProperty(ref _signal, value); }
    public string Unmatched { get => _unmatched; private set => SetProperty(ref _unmatched, value); }
    public string SessionTitle { get => _sessionTitle; private set => SetProperty(ref _sessionTitle, value); }
    public string SessionDate { get => _sessionDate; private set => SetProperty(ref _sessionDate, value); }
    public string OperatorCallsign { get => _operatorCallsign; set => SetProperty(ref _operatorCallsign, value); }
    public string RepeaterName { get => _repeaterName; set => SetProperty(ref _repeaterName, value); }
    public string SessionStatus { get => _sessionStatus; private set => SetProperty(ref _sessionStatus, value); }
    public string StatusMessage { get => _statusMessage; private set => SetProperty(ref _statusMessage, value); }
    public string TaskSummary { get => _taskSummary; private set => SetProperty(ref _taskSummary, value); }
    public string CatalogSummary { get => _catalogSummary; private set => SetProperty(ref _catalogSummary, value); }
    public string MiitStatus { get => _miitStatus; private set => SetProperty(ref _miitStatus, value); }
    public string LocationStatus { get => _locationStatus; private set => SetProperty(ref _locationStatus, value); }
    public string UpdateStatus { get => _updateStatus; private set => SetProperty(ref _updateStatus, value); }
    public string DatabasePath { get => _databasePath; private set => SetProperty(ref _databasePath, value); }
    public string CurrentPage { get => _currentPage; set => SetProperty(ref _currentPage, value); }
    public long LastParseMicroseconds { get => _lastParseMicroseconds; private set => SetProperty(ref _lastParseMicroseconds, value); }
    public int NextSequence { get => _nextSequence; private set => SetProperty(ref _nextSequence, value); }
    public bool IsCatalogBusy { get => _isCatalogBusy; private set => SetProperty(ref _isCatalogBusy, value); }

    public string SessionMeta =>
        $"{SessionDate} · 主控 {Display(OperatorCallsign, "未设置")} · 中继 {Display(RepeaterName, "未设置")} · 下一序号 {NextSequence}";

    public string CurrentUnmatchedDisplay => string.IsNullOrWhiteSpace(Unmatched) ? "无" : Unmatched;
    public bool HasQthCandidates => QthCandidates.Count > 0;

    /// <summary>
    /// Explicitly accepts one displayed QTH candidate without replacing the
    /// raw input.  The selected result is kept in the parsed snapshot so the
    /// subsequent submit cannot silently re-parse the ambiguous abbreviation.
    /// </summary>
    public void SelectQthCandidate(string canonical)
    {
        if (string.IsNullOrWhiteSpace(canonical)
            || _parseResult.Qth.Candidates is not { } candidates
            || !candidates.Contains(canonical, StringComparer.Ordinal))
        {
            return;
        }

        _selectedQthRevision = _draftService.Current.Revision;
        _selectedQthRaw = _parseResult.RawText;
        _selectedQthCanonical = canonical;
        _parseResult = ApplySelectedQthCandidate(_parseResult, canonical);
        Qth = canonical;
        Unmatched = _parseResult.UnmatchedText;
        QthCandidates.Clear();
        OnPropertyChanged(nameof(HasQthCandidates));
        OnPropertyChanged(nameof(CurrentUnmatchedDisplay));
        StatusMessage = $"已选择 QTH：{canonical}；原始输入未改写";
        if (SubmitCommand is AsyncRelayCommand command)
        {
            command.RaiseCanExecuteChanged();
        }
        ParseUpdated?.Invoke(this, EventArgs.Empty);
    }

    public string ShortcutStatus { get; private set; } = "快捷键已使用默认配置";

    public void SetShortcutStatus(string status)
    {
        ShortcutStatus = status;
        OnPropertyChanged(nameof(ShortcutStatus));
    }

    public ShortcutBinding? GetShortcut(string actionKey) =>
        ShortcutBindings.FirstOrDefault(item => item.ActionKey == actionKey);

    public string CatalogQuery
    {
        get => _catalogQuery;
        set => SetProperty(ref _catalogQuery, value);
    }

    public bool IsReady
    {
        get => _isReady;
        private set
        {
            if (SetProperty(ref _isReady, value))
            {
                OnPropertyChanged(nameof(IsSessionWritable));
                OnPropertyChanged(nameof(IsQuickInputAvailable));
                if (SubmitCommand is AsyncRelayCommand command)
                {
                    command.RaiseCanExecuteChanged();
                }
            }
        }
    }

    /// <summary>
    /// A closed session is a read-only view.  Keep this as a separate state
    /// instead of relying only on SubmitCommand.CanExecute: otherwise the
    /// user could still edit a TextBox or open a field editor and discover
    /// the read-only rule only after typing.
    /// </summary>
    public bool IsSessionWritable => IsReady && _session?.Status == "active";

    /// <summary>
    /// The editor may accept a draft while SQLite/session bootstrap is still
    /// running.  SubmitCommand remains disabled until IsReady is true, so a
    /// fast first keystroke cannot be lost and cannot be written without a
    /// resolved session.
    /// </summary>
    public bool IsQuickInputAvailable => _store is null || !_initializationComplete || IsSessionWritable;

    public bool AnimationsEnabled
    {
        get => _animationsEnabled;
        set => SetProperty(ref _animationsEnabled, value);
    }

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        if (_store is null)
        {
            _initializationComplete = true;
            OnPropertyChanged(nameof(IsQuickInputAvailable));
            IsReady = true;
            return;
        }

        // Start the check for every real application launch before the
        // database/catalog work.  It is intentionally fire-and-forget and
        // isolated from the input path, so a slow/offline GitHub request can
        // never delay the first keystroke or SQLite submission.
        _updateCancellation?.Cancel();
        _updateCancellation?.Dispose();
        _updateCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        UpdateStatus = RuntimeOptions.DisableNetwork
            ? "测试模式：已跳过启动更新检查"
            : $"正在检查更新… 当前 {NativeVersion.Current}";
        StartupUpdateCheckTask = CheckForUpdatesInBackgroundAsync(_updateCancellation.Token);

        var timer = Stopwatch.StartNew();
        DatabasePath = _store.DatabasePath;
        // SQLite bootstrap and legacy inspection are deliberately moved off
        // the WPF dispatcher.  The TextBox can accept a draft immediately;
        // only the submit command waits for the session to become ready.
        var bootstrap = await Task.Run(async () =>
        {
            await _store.InitializeAsync(cancellationToken).ConfigureAwait(false);
            var legacyImport = ImportLegacyDatabase
                ? await LegacyPythonMigration.TryImportAsync(
                    _store.DatabasePath, AppPaths.LegacyDatabasePath, AppPaths.BackupRoot,
                    cancellationToken).ConfigureAwait(false)
                : new LegacyImportResult(false, false, 0, 0, 0, "", "测试已跳过旧版数据库迁移。");
            var session = await _store.GetOrCreateFirstSessionAsync(
                RuntimeOptions.Today, cancellationToken).ConfigureAwait(false);
            var rows = await _store.LoadRecentAsync(session.Id, 300, cancellationToken)
                .ConfigureAwait(false);
            return (LegacyImport: legacyImport, Session: session, Rows: rows);
        }, cancellationToken).ConfigureAwait(true);

        ApplySession(bootstrap.Session);
        Checkins.Clear();
        foreach (var row in bootstrap.Rows)
        {
            Checkins.Add(row);
        }
        OnPropertyChanged(nameof(RecentCheckins));

        _initializationComplete = true;
        OnPropertyChanged(nameof(IsQuickInputAvailable));
        IsReady = true;
        timer.Stop();
        StatusMessage = bootstrap.LegacyImport.Imported
            ? $"{bootstrap.LegacyImport.Message} 本地录入已就绪"
            : "本地录入已就绪";
        TaskSummary = "资料库后台加载中 · 可继续点名";
        _catalogCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _ = LoadCatalogInBackgroundAsync(_catalogCancellation.Token);
    }

    private async Task CheckForUpdatesInBackgroundAsync(CancellationToken cancellationToken)
    {
        if (RuntimeOptions.DisableNetwork)
        {
            UpdateStatus = "测试模式：已跳过启动更新检查";
            return;
        }

        try
        {
            var release = await _updates.FetchLatestAsync(cancellationToken).ConfigureAwait(true);
            UpdateStatus = NativeUpdateService.IsNewer(release.Version, NativeVersion.Current)
                ? $"发现新版本 {release.TagName} · 可在“关于 / 检查更新”下载"
                : $"已检查更新 · 当前 {NativeVersion.Current} 为最新";
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Closing the application or an isolated test cancels the check;
            // this is not an input or data failure.
        }
        catch (Exception exception)
        {
            UpdateStatus = $"启动更新检查失败（不影响点名）：{exception.Message}";
        }
    }

    public async Task<SessionInfo?> GetSessionAsync(CancellationToken cancellationToken = default) =>
        _session is null || _store is null ? _session : await _store.GetSessionAsync(_session.Id, cancellationToken).ConfigureAwait(false);

    public async Task<IReadOnlyList<SessionInfo>> ListSessionsAsync(
        CancellationToken cancellationToken = default) =>
        _store is null ? Array.Empty<SessionInfo>() : await _store.ListSessionsAsync(cancellationToken).ConfigureAwait(false);

    public async Task SelectSessionAsync(long sessionId, CancellationToken cancellationToken = default)
    {
        if (_store is null)
        {
            return;
        }

        var session = await _store.GetSessionAsync(sessionId, cancellationToken).ConfigureAwait(true)
            ?? throw new InvalidOperationException("选择的场次不存在。");
        _session = session;
        ApplySession(session);
        var rows = await _store.LoadRecentAsync(session.Id, 300, cancellationToken).ConfigureAwait(true);
        Checkins.Clear();
        foreach (var row in rows)
        {
            Checkins.Add(row);
        }
        OnPropertyChanged(nameof(RecentCheckins));
        SetInputText(string.Empty);
        CurrentPage = "Quick";
        StatusMessage = session.Status == "ended"
            ? "已打开已结束场次，只读查看；点击重新打开后才能继续录入"
            : $"已切换到 {session.Name}，继续序号 {session.NextSequence}";
        CheckinsChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task CreateSessionAsync(
        string name,
        string date,
        string operatorCallsign,
        string repeaterName,
        string workbookPath,
        string sheetName,
        CancellationToken cancellationToken = default)
    {
        if (_store is null)
        {
            return;
        }

        var session = await _store.CreateSessionAsync(name, date, operatorCallsign,
            repeaterName, workbookPath, sheetName, cancellationToken).ConfigureAwait(true);
        await SelectSessionAsync(session.Id, cancellationToken).ConfigureAwait(true);
        StatusMessage = $"已创建并切换到 {session.Name}；Excel 仍未连接";
    }

    public async Task UpdateCurrentSessionInfoAsync(
        string operatorCallsign,
        string repeaterName,
        string workbookPath,
        string sheetName,
        CancellationToken cancellationToken = default)
    {
        if (_store is null || _session is null)
        {
            return;
        }

        var session = await _store.UpdateSessionInfoAsync(_session, operatorCallsign,
            repeaterName, workbookPath, sheetName, cancellationToken).ConfigureAwait(true);
        ApplySession(session);
        StatusMessage = "场次信息已保存；导出时使用本场日期、主控和中继信息";
    }

    public async Task SetCurrentSessionStatusAsync(
        bool reopen,
        CancellationToken cancellationToken = default)
    {
        if (_store is null || _session is null)
        {
            return;
        }

        var session = await _store.SetSessionStatusAsync(
            _session.Id, reopen ? "active" : "ended", cancellationToken).ConfigureAwait(true);
        ApplySession(session);
        if (!reopen)
        {
            SetInputText(string.Empty);
        }
        StatusMessage = reopen ? "场次已重新打开，可以继续录入" : "本场已结束；记录仍可查看和导出";
    }

    public FieldParseResult ParseField(FieldKind field, string text) => _fieldParser.Parse(field, text);

    public Task<FieldEditRequest?> CreateFieldEditRequestAsync(CheckinEntry row, FieldKind field,
        CancellationToken cancellationToken = default) => _store is null
        ? Task.FromResult<FieldEditRequest?>(new FieldEditRequest(row.Id, field, CurrentValue(row, field),
            row.RawInput, row.Unmatched, row.SessionId, row.SequenceNo, row.Callsign, row.UpdatedAt))
        : _store.CreateFieldEditRequestAsync(row.Id, field, cancellationToken);

    public async Task ApplyFieldEditAsync(FieldEditCommit commit, CancellationToken cancellationToken = default)
    {
        if (_session is not null && _session.Status != "active")
        {
            throw new InvalidOperationException("当前场次已结束，只能查看和导出；请先点击“结束/重开”后再修改。");
        }

        CheckinEntry updated;
        if (_store is null)
        {
            var current = Checkins.FirstOrDefault(item => item.Id == commit.CheckinId)
                ?? throw new InvalidOperationException("预览记录不存在。");
            updated = ApplyInMemory(current, commit);
        }
        else
        {
            updated = await _store.ApplyFieldEditAsync(commit, cancellationToken).ConfigureAwait(true);
        }

        var index = Checkins.ToList().FindIndex(item => item.Id == updated.Id);
        if (index >= 0)
        {
            Checkins[index] = updated;
        }
        OnPropertyChanged(nameof(RecentCheckins));
        StatusMessage = $"第 {updated.SequenceNo} 条已保存，仅修改 {FieldName(commit.Field)}；未识别其余内容保留";
        CheckinsChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task ExportCurrentAsync(string? requestedPath = null)
    {
        if (_session is null || _store is null)
        {
            StatusMessage = "效果图模式不执行文件导出";
            return;
        }

        var path = requestedPath;
        if (string.IsNullOrWhiteSpace(path))
        {
            var downloads = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
            path = Path.Combine(downloads, $"{_session.Name}_{_session.Date}.xlsx");
        }
        StatusMessage = "正在后台生成 Excel，不会阻塞现场录入…";
        TaskSummary = "Excel 导出进行中 · SQLite 仍可继续提交";
        try
        {
            var rows = await _store.LoadAllForExportAsync(_session.Id).ConfigureAwait(true);
            var result = await _exporter.ExportAsync(_session, rows, path).ConfigureAwait(true);
            StatusMessage = $"已导出 {result.RowCount} 条；Excel 不包含未识别列：{result.Path}";
        }
        catch (OperationCanceledException)
        {
            StatusMessage = "Excel 导出已取消；SQLite 现场记录仍然保留";
        }
        catch (IOException exception)
        {
            StatusMessage = $"Excel 导出失败：{exception.Message}";
        }
        catch (Exception exception)
        {
            StatusMessage = $"Excel 导出失败：{exception.Message}";
        }
        finally
        {
            TaskSummary = "无后台任务";
        }
    }

    public void RequestQuickWindow() => QuickWindowRequested?.Invoke(this, EventArgs.Empty);

    public bool UpdateShortcut(string actionKey, string gesture)
    {
        var current = ShortcutBindings.FirstOrDefault(item => item.ActionKey == actionKey);
        if (current is null || string.IsNullOrWhiteSpace(gesture))
        {
            return false;
        }
        var conflict = ShortcutBindings.FirstOrDefault(item => item.ActionKey != actionKey
            && item.Scope == current.Scope
            && string.Equals(item.Gesture, gesture, StringComparison.OrdinalIgnoreCase));
        if (conflict is not null)
        {
            ShortcutStatus = $"冲突：{gesture} 已分配给“{conflict.DisplayName}”，未保存";
            OnPropertyChanged(nameof(ShortcutStatus));
            return false;
        }
        var index = ShortcutBindings.IndexOf(current);
        ShortcutBindings[index] = current with { Gesture = gesture };
        ShortcutStatus = $"已更新“{current.DisplayName}”：{gesture}";
        OnPropertyChanged(nameof(ShortcutStatus));
        ShortcutsChanged?.Invoke(this, new ShortcutChangedEventArgs(
            actionKey, current.Gesture, gesture, false));
        return true;
    }

    public void RestoreShortcut(string actionKey, string gesture)
    {
        var current = ShortcutBindings.FirstOrDefault(item => item.ActionKey == actionKey);
        if (current is null)
        {
            return;
        }

        var index = ShortcutBindings.IndexOf(current);
        ShortcutBindings[index] = current with { Gesture = gesture };
        ShortcutStatus = $"已恢复“{current.DisplayName}”：{gesture}";
        OnPropertyChanged(nameof(ShortcutStatus));
    }

    public void ResetShortcuts()
    {
        var previousGlobal = GetShortcut("quick-window")?.Gesture;
        ShortcutBindings.Clear();
        ShortcutBindings.Add(new("quick-window", "呼出/隐藏快速小窗", "Ctrl+Space", "全局", "主窗口、小窗共享当前场次", true));
        ShortcutBindings.Add(new("focus-input", "聚焦快速输入框", "Ctrl+L", "软件内", "选中当前输入", false));
        ShortcutBindings.Add(new("submit", "提交当前录入", "Enter", "快速输入", "保存 SQLite 后清空并聚焦", false));
        ShortcutBindings.Add(new("clear", "清空当前输入", "Esc", "快速输入", "失败时不自动清空", false));
        ShortcutBindings.Add(new("undo", "撤销上一条记录", "Ctrl+Shift+Z", "软件内", "撤销最近一次安全操作", false));
        ShortcutBindings.Add(new("edit-cell", "打开所选单元格编辑器", "F2", "本场记录", "Enter 也可打开", false));
        ShortcutBindings.Add(new("copy-unmatched", "复制全部未识别内容", "Ctrl+Shift+C", "字段编辑器", "只复制，不消费片段", false));
        ShortcutBindings.Add(new("export", "导出本场", "Ctrl+E", "软件内", "九列 Excel，不含未识别", false));
        ShortcutBindings.Add(new("nav-quick", "打开快速点名", "Ctrl+1", "软件内", "", false));
        ShortcutBindings.Add(new("nav-records", "打开本场记录", "Ctrl+2", "软件内", "", false));
        ShortcutBindings.Add(new("nav-catalog", "打开资料库", "Ctrl+3", "软件内", "", false));
        ShortcutBindings.Add(new("nav-settings", "打开设置", "Ctrl+4", "软件内", "", false));
        ShortcutStatus = "快捷键已恢复默认配置";
        OnPropertyChanged(nameof(ShortcutStatus));
        ShortcutsChanged?.Invoke(this, new ShortcutChangedEventArgs(
            "*", previousGlobal, GetShortcut("quick-window")?.Gesture ?? string.Empty, true));
    }

    public async Task RefreshCatalogAsync(bool firstDownload)
    {
        if (IsCatalogBusy)
        {
            return;
        }
        IsCatalogBusy = true;
        _catalogCancellation?.Cancel();
        _catalogCancellation?.Dispose();
        _catalogCancellation = new CancellationTokenSource();
        try
        {
            MiitStatus = firstDownload ? "正在连接工信部并准备完整同步…" : "正在检查工信部最新页面…";
            TaskSummary = "工信部资料库同步进行中 · 录入不受阻";
            var progress = new Progress<MiitSyncProgress>(UpdateMiitProgress);
            var syncReport = await _miitSyncService.StartAsync(
                full: firstDownload,
                progress,
                _catalogCancellation.Token).ConfigureAwait(true);
            var report = await _catalogService.ReloadExistingDataAsync(_catalogDataRoot).ConfigureAwait(true);
            CatalogSummary = $"本地别名 {report.DeviceAliasCount:N0} 个；行政地点别名 {report.QthAliasCount:N0} 个；地点记录 {report.QthPlaceCount:N0} 条；工信部 {report.MiitModelCount:N0} 个";
            MiitStatus = $"{(firstDownload ? "完整同步" : "检查更新")}完成 · 扫描 {syncReport.ScannedCount:N0} · 保留 {syncReport.RetainedCount:N0} · 排除 {syncReport.ExcludedCount:N0}";
            LocationStatus = report.QthPlaceCount > 0
                ? $"全国行政区已载入；详细地点 {report.QthPlaceCount:N0} 条；省市包可独立更新"
                : "全国省市行政区已载入；尚未安装道路/地标地点包";
            StatusMessage = "资料库刷新完成；快速输入仍只查本地";
            ReparseCurrentInput();
        }
        catch (OperationCanceledException)
        {
            MiitStatus = "已取消；上一份完整资料库继续使用，断点已保留";
            StatusMessage = "工信部同步已取消，快速录入不受影响";
        }
        catch (Exception exception)
        {
            MiitStatus = "同步失败；上一份完整资料库继续使用";
            StatusMessage = $"工信部同步失败：{exception.Message}";
        }
        finally
        {
            IsCatalogBusy = false;
            TaskSummary = "无后台任务 · 快速录入只查本地资料";
        }
    }

    public async Task ResumeMiitAsync()
    {
        if (IsCatalogBusy)
        {
            return;
        }

        IsCatalogBusy = true;
        _catalogCancellation?.Cancel();
        _catalogCancellation?.Dispose();
        _catalogCancellation = new CancellationTokenSource();
        try
        {
            MiitStatus = "正在从上次成功页继续同步…";
            TaskSummary = "工信部断点续传进行中 · 录入不受阻";
            var progress = new Progress<MiitSyncProgress>(UpdateMiitProgress);
            var syncReport = await _miitSyncService.ResumeAsync(progress, _catalogCancellation.Token).ConfigureAwait(true);
            var report = await _catalogService.ReloadExistingDataAsync(_catalogDataRoot).ConfigureAwait(true);
            CatalogSummary = $"本地别名 {report.DeviceAliasCount:N0} 个；行政地点 {report.QthPlaceCount:N0} 条；工信部 {report.MiitModelCount:N0} 个";
            MiitStatus = $"断点续传完成 · 扫描 {syncReport.ScannedCount:N0} · 保留 {syncReport.RetainedCount:N0}";
            ReparseCurrentInput();
        }
        catch (OperationCanceledException)
        {
            MiitStatus = "已取消；可继续上次断点";
        }
        catch (Exception exception)
        {
            MiitStatus = "没有可用断点或同步失败：" + exception.Message;
        }
        finally
        {
            IsCatalogBusy = false;
            TaskSummary = "无后台任务 · 快速录入只查本地资料";
        }
    }

    private void UpdateMiitProgress(MiitSyncProgress progress)
    {
        var total = progress.TotalPages > 0 ? $"{progress.CurrentPage}/{progress.TotalPages} 页" : $"第 {progress.CurrentPage} 页";
        MiitStatus = $"{total} · 扫描 {progress.ScannedCount:N0}/{progress.TotalCount:N0} · 保留 {progress.RetainedCount:N0}";
        TaskSummary = $"工信部同步 · {progress.Message}";
    }

    public void CancelCatalog()
    {
        _catalogCancellation?.Cancel();
        IsCatalogBusy = false;
        TaskSummary = "资料库任务已请求取消 · 上一份完整数据继续可用";
        MiitStatus = "已取消，未替换上一份本地资料库";
    }

    public async Task RefreshQthPackagesAsync(string? message = null,
        CancellationToken cancellationToken = default)
    {
        var tree = await QthPackageService.LoadInstalledTreeAsync(_catalogDataRoot, cancellationToken).ConfigureAwait(true);
        QthPackages.Clear();
        foreach (var node in tree)
        {
            QthPackages.Add(node);
        }
        var installedProvinces = tree.Count(static node => node.IsInstalled);
        LocationStatus = tree.Count > 0
            ? $"全国省市树 {tree.Count} 个省级节点；已安装 {installedProvinces} 个省级地点包"
            : "全国行政区基础索引仍可用";
        if (!string.IsNullOrWhiteSpace(message))
        {
            StatusMessage = message;
        }
    }

    private async Task LoadCatalogInBackgroundAsync(CancellationToken cancellationToken)
    {
        try
        {
            var report = await _catalogService.ReloadExistingDataAsync(_catalogDataRoot, cancellationToken).ConfigureAwait(true);
            CatalogSummary = $"本地别名 {report.DeviceAliasCount:N0} 个；行政地点 {report.QthPlaceCount:N0} 条；工信部 {report.MiitModelCount:N0} 个";
            MiitStatus = report.MiitModelCount > 0 ? $"本地工信部电台型号 {report.MiitModelCount:N0} 个" : "工信部电台型号库尚未下载";
            LocationStatus = report.QthPlaceCount > 0
                ? $"全国行政区基础索引可用；详细地点 {report.QthPlaceCount:N0} 条已载入"
                : "全国行政区基础索引可用；详细地点包尚未安装";
            await RefreshQthPackagesAsync(cancellationToken: cancellationToken).ConfigureAwait(true);
            TaskSummary = "无后台任务 · 本地资料库已就绪";
            ReparseCurrentInput();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception exception)
        {
            CatalogSummary = "内置现场词典继续可用；资料库加载失败：" + exception.Message;
            StatusMessage = "资料库加载失败，但 SQLite 录入仍可用";
            TaskSummary = "资料库任务失败 · 可重试";
        }
    }

    private void DraftService_Changed(object? sender, QuickInputDraftChangedEventArgs e)
    {
        OnPropertyChanged(nameof(InputText));
        OnPropertyChanged(nameof(InputRevision));
        OnPropertyChanged(nameof(InputDraft));
        // The parser only updates the preview and never writes back to the
        // focused TextBox.  Parsing every text revision is therefore safe and
        // important for native Unicode/IME paths where WPF can report a
        // TextChanged event before a matching TextInput completion event.  If
        // we suppress parsing while IsImeComposing is true and that completion
        // notification is absent, the raw text visibly changes while the
        // parsed fields stay stale/empty and submission remains disabled.
        ParseInput(e.Snapshot.Text, e.Snapshot.Revision);
        InputDraftChanged?.Invoke(this, e);
    }

    private void ReparseCurrentInput()
    {
        var snapshot = _draftService.Current;
        ParseInput(snapshot.Text, snapshot.Revision);
    }

    /// <summary>
    /// Isolated UI tests use the same reparse operation that a background
    /// catalog refresh uses, without reaching the network or production data.
    /// </summary>
    internal void ReparseCurrentInputForTesting() => ReparseCurrentInput();

    private void ParseInput(string value, long revision = -1)
    {
        var started = Stopwatch.GetTimestamp();
        var parsed = _parser.Parse(value);
        if (revision >= 0
            && revision == _selectedQthRevision
            && string.Equals(parsed.RawText, _selectedQthRaw, StringComparison.Ordinal)
            && !string.IsNullOrWhiteSpace(_selectedQthCanonical))
        {
            parsed = ApplySelectedQthCandidate(parsed, _selectedQthCanonical);
        }
        else if (revision != _selectedQthRevision
                 || !string.Equals(parsed.RawText, _selectedQthRaw, StringComparison.Ordinal))
        {
            ClearSelectedQthCandidate();
        }

        _parseResult = parsed;
        _parsedInputRevision = revision >= 0 ? revision : _draftService.Current.Revision;
        LastParseMicroseconds = (long)(Stopwatch.GetElapsedTime(started).TotalMilliseconds * 1000);
        Callsign = _parseResult.Callsign.Value;
        Qth = _parseResult.Qth.Value;
        Device = _parseResult.Device.Value;
        Antenna = _parseResult.Antenna.Value;
        Power = _parseResult.Power.Value;
        Signal = _parseResult.Signal.Value;
        Unmatched = _parseResult.UnmatchedText;
        QthCandidates.Clear();
        if (!string.Equals(_parseResult.Qth.Source, "用户选择", StringComparison.Ordinal))
        {
            foreach (var candidate in _parseResult.Qth.Candidates ?? Array.Empty<string>())
            {
                QthCandidates.Add(candidate);
            }
        }
        OnPropertyChanged(nameof(HasQthCandidates));
        OnPropertyChanged(nameof(CurrentUnmatchedDisplay));
        if (SubmitCommand is AsyncRelayCommand command)
        {
            command.RaiseCanExecuteChanged();
        }
        ParseUpdated?.Invoke(this, EventArgs.Empty);
    }

    private void ClearSelectedQthCandidate()
    {
        _selectedQthRevision = -1;
        _selectedQthRaw = string.Empty;
        _selectedQthCanonical = string.Empty;
    }

    private static ParseResult ApplySelectedQthCandidate(ParseResult parsed, string canonical)
    {
        var token = TextNormalizer.Tokenize(parsed.Qth.Raw).FirstOrDefault();
        var unmatched = parsed.Unmatched.ToList();
        if (!string.IsNullOrWhiteSpace(token))
        {
            var tokenIndex = unmatched.FindIndex(item =>
                string.Equals(TextNormalizer.NormalizeKey(item),
                    TextNormalizer.NormalizeKey(token), StringComparison.Ordinal));
            if (tokenIndex >= 0)
            {
                unmatched.RemoveAt(tokenIndex);
            }
        }

        return parsed with
        {
            Qth = new ParseField(
                canonical,
                "用户选择",
                1.0,
                token ?? canonical,
                parsed.Qth.Candidates),
            Unmatched = unmatched
        };
    }

    private async Task SubmitAsync()
    {
        if (_store is null || _session is null)
        {
            return;
        }

        // Capture the session before the first await.  A user may switch
        // sessions while SQLite is committing; the completed row must stay in
        // the captured session and must not be appended to the newly selected
        // session's ObservableCollection.
        var submissionSession = _session;
        var draft = _draftService.Current;
        var raw = draft.Text;
        var parsed = _parsedInputRevision == draft.Revision
            && string.Equals(_parseResult.RawText, raw, StringComparison.Ordinal)
            ? _parseResult
            : _parser.Parse(raw);
        if (!parsed.CanSubmit)
        {
            StatusMessage = "未识别到有效呼号，原文仍保留在输入框";
            return;
        }

        var row = await _store.AddCheckinAsync(
            submissionSession,
            parsed,
            Guid.NewGuid().ToString("N")).ConfigureAwait(true);
        var isCurrentSession = _session?.Id == submissionSession.Id;

        // Clearing is guarded by the draft revision even when the user has
        // moved to another session.  A newer draft is never removed by an
        // older SQLite completion.
        var cleared = _draftService.TryClear(draft.Revision);
        if (!isCurrentSession)
        {
            TaskSummary = $"后台已保存 {submissionSession.Name} 第 {row.SequenceNo} 条";
            return;
        }

        if (Checkins.All(checkin => checkin.Id != row.Id))
        {
            Checkins.Insert(0, row);
        }
        OnPropertyChanged(nameof(RecentCheckins));
        _session = submissionSession with { NextSequence = row.SequenceNo + 1 };
        NextSequence = row.SequenceNo + 1;
        OnPropertyChanged(nameof(SessionMeta));
        StatusMessage = cleared
            ? $"第 {row.SequenceNo} 条已保存；Excel 延后批量同步"
            : $"第 {row.SequenceNo} 条已保存；当前输入在保存期间有修改，已保留原文";
        TaskSummary = "SQLite 已保存 · 可继续录入";
        CheckinsChanged?.Invoke(this, EventArgs.Empty);
        SubmissionSucceeded?.Invoke(this, EventArgs.Empty);
    }

    // The UI command is intentionally async-void through ICommand.  Keep a
    // narrow awaitable seam for isolated integration tests so submission
    // races can be exercised without driving the user's desktop.
    internal Task SubmitForTestingAsync() => SubmitAsync();

    private void SearchCatalog()
    {
        CatalogResults.Clear();
        foreach (var result in _catalogService.Current.SearchDevices(CatalogQuery, 30))
        {
            CatalogResults.Add(result);
        }
    }

    private void ApplySession(SessionInfo session)
    {
        _session = session;
        SessionTitle = session.Name;
        SessionDate = session.Date;
        OperatorCallsign = session.OperatorCallsign;
        RepeaterName = session.RepeaterName;
        SessionStatus = session.Status == "ended" ? "已结束" : "进行中";
        NextSequence = session.NextSequence;
        OnPropertyChanged(nameof(SessionMeta));
        OnPropertyChanged(nameof(IsSessionWritable));
        OnPropertyChanged(nameof(IsQuickInputAvailable));
        if (SubmitCommand is AsyncRelayCommand command)
        {
            command.RaiseCanExecuteChanged();
        }
    }

    private void SetFailure(Exception exception) =>
        StatusMessage = $"操作失败，现场数据未删除：{exception.Message}";

    private static string Display(string value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value;

    private static string CurrentValue(CheckinEntry row, FieldKind field) => field switch
    {
        FieldKind.Time => row.CheckinTime,
        FieldKind.Callsign => row.Callsign,
        FieldKind.Qth => row.Qth,
        FieldKind.Device => row.Device,
        FieldKind.Antenna => row.Antenna,
        FieldKind.Power => row.Power,
        FieldKind.Signal => row.Signal,
        _ => string.Empty
    };

    private static string FieldName(FieldKind field) => field switch
    {
        FieldKind.Time => "时间", FieldKind.Callsign => "呼号", FieldKind.Qth => "QTH",
        FieldKind.Device => "设备", FieldKind.Antenna => "天线", FieldKind.Power => "功率",
        FieldKind.Signal => "信号", _ => field.ToString()
    };

    private static CheckinEntry ApplyInMemory(CheckinEntry row, FieldEditCommit commit)
    {
        if (commit.ConsumedTokenIndexes is { Count: > 0 })
        {
            var indexes = commit.ConsumedTokenIndexes.ToHashSet();
            var indexedTokens = row.UnmatchedTokens
                .Select((token, index) => (token, index))
                .Where(item => !indexes.Contains(item.index))
                .Select(item => item.token);
            var indexedUnmatched = string.Join(' ', indexedTokens);
            return commit.Field switch
            {
                FieldKind.Time => row with { CheckinTime = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Callsign => row with { Callsign = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Qth => row with { Qth = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Device => row with { Device = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Antenna => row with { Antenna = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Power => row with { Power = commit.NewValue, Unmatched = indexedUnmatched },
                FieldKind.Signal => row with { Signal = commit.NewValue, Unmatched = indexedUnmatched },
                _ => row
            };
        }

        var toRemove = commit.ConsumedTokens.ToList();
        var remaining = new List<string>();
        foreach (var token in row.UnmatchedTokens)
        {
            var index = toRemove.FindIndex(item => string.Equals(item, token, StringComparison.Ordinal));
            if (index >= 0)
            {
                toRemove.RemoveAt(index);
            }
            else
            {
                remaining.Add(token);
            }
        }
        var unmatched = string.Join(' ', remaining);
        return commit.Field switch
        {
            FieldKind.Time => row with { CheckinTime = commit.NewValue, Unmatched = unmatched },
            FieldKind.Callsign => row with { Callsign = commit.NewValue, Unmatched = unmatched },
            FieldKind.Qth => row with { Qth = commit.NewValue, Unmatched = unmatched },
            FieldKind.Device => row with { Device = commit.NewValue, Unmatched = unmatched },
            FieldKind.Antenna => row with { Antenna = commit.NewValue, Unmatched = unmatched },
            FieldKind.Power => row with { Power = commit.NewValue, Unmatched = unmatched },
            FieldKind.Signal => row with { Signal = commit.NewValue, Unmatched = unmatched },
            _ => row
        };
    }

    public static MainViewModel CreatePreview()
    {
        var viewModel = new MainViewModel(new CatalogService(), null)
        {
            _sessionTitle = "第1场点名",
            _sessionDate = "2026-09-25",
            _operatorCallsign = "BA4THG",
            _repeaterName = "江苏省中继",
            _statusMessage = "已保存第 37 条 · 后台资料库可继续更新",
            _taskSummary = "无后台任务",
            _catalogSummary = "全国地点 2,521 条 · 工信部电台型号 7,704 个 · 本地别名优先",
            _miitStatus = "已安装快照 · 可检查更新 / 继续 / 取消 / 完整重下",
            _locationStatus = "全国省市树已载入 · 已安装江苏/安徽示例包 · 其余省市可选",
            _databasePath = Path.Combine(AppPaths.DataRoot, "ham_checkin_native.db"),
            _isReady = true,
            _nextSequence = 38,
            _lastParseMicroseconds = 37
        };
        viewModel.QthPackages.Add(new("江苏省", "省", "部分安装", "3 条本地点 · 可展开选择城市", true, true,
            new[] { new QthPackageNode("南京市", "城市", "已安装", "18.2 万条", true, false), new QthPackageNode("扬州市", "城市", "已安装", "7.4 万条", true, false), new QthPackageNode("苏州市", "城市", "有更新", "待更新", true, true) }));
        viewModel.QthPackages.Add(new("安徽省", "省", "未下载", "可选择城市或下载全省", false, false,
            new[] { new QthPackageNode("合肥市", "城市", "未下载", "", false, false), new QthPackageNode("芜湖市", "城市", "未下载", "", false, false) }));
        viewModel.QthPackages.Add(new("广东省", "省", "未下载", "可选择城市或下载全省", false, false,
            new[] { new QthPackageNode("广州市", "城市", "未下载", "可下载城市包", false, false), new QthPackageNode("深圳市", "城市", "未下载", "可下载城市包", false, false) }));
        viewModel.QthPackages.Add(new("新疆维吾尔自治区", "省", "未下载", "可选择城市或下载全省", false, false,
            new[] { new QthPackageNode("乌鲁木齐市", "城市", "未下载", "可下载城市包", false, false), new QthPackageNode("和田市", "城市", "未下载", "可下载城市包", false, false) }));
        viewModel._session = new SessionInfo(1, "第1场点名", "2026-09-25", "active", 38,
            "BA4THG", "江苏省中继");
        viewModel.Checkins.Add(new(37, 1, 37, "21:59", "BH6ERY", "安徽省芜湖市鸠江区", "泉盛 UV-K1", "1.8米GP", "低", "", "local", "BH6ERY K1 1.8MGP L AHWHWZ", "", "2026-09-25T21:59:00+08:00"));
        viewModel.Checkins.Add(new(36, 1, 36, "21:58", "BI4VLG", "龙蟠中路338号", "海能达 PD-780G", "橡胶天线", "4W", "", "local", "BI4VLG PD780G 4W 龙蟠中路338号", "hnd", "2026-09-25T21:58:00+08:00"));
        viewModel.Checkins.Add(new(35, 1, 35, "21:54", "BA4VWI", "南京市鼓楼区", "宝锋 UV-5RH", "原装天线", "8W", "", "local", "BA4VWI 5RH Y 8W NJGL", "", "2026-09-25T21:54:00+08:00"));
        viewModel.Checkins.Add(new(34, 1, 34, "21:50", "BA4VXR", "江苏省南京市江宁区", "摩托罗拉 R6", "原装天线", "5W", "", "local", "BA4VXR R6 Y 5W NJJN", "njbbxq", "2026-09-25T21:50:00+08:00"));
        viewModel.SearchCatalog();
        return viewModel;
    }

    public async ValueTask DisposeAsync()
    {
        _draftService.Changed -= DraftService_Changed;
        _catalogCancellation?.Cancel();
        _catalogCancellation?.Dispose();
        _updateCancellation?.Cancel();
        _updateCancellation?.Dispose();
        if (_store is not null)
        {
            await _store.DisposeAsync();
        }
        await _miitSyncService.DisposeAsync();
    }
}

public sealed class ShortcutChangedEventArgs(
    string actionKey,
    string? previousGesture,
    string currentGesture,
    bool isReset) : EventArgs
{
    public string ActionKey { get; } = actionKey;
    public string? PreviousGesture { get; } = previousGesture;
    public string CurrentGesture { get; } = currentGesture;
    public bool IsReset { get; } = isReset;
}
