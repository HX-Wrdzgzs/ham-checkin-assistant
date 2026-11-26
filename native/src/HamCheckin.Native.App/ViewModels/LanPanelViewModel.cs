using System.Collections.ObjectModel;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Windows.Threading;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.LanServer;

namespace HamCheckin.Native.App.ViewModels;

/// <summary>监听地址的显示包装；地址本身仍由 LanBindingResolver 决定。</summary>
public sealed record LanAddressOption(IPAddress Address, string Display);

/// <summary>
/// 「手机收件」页的 WPF 侧唯一实例：持有配对存储、内存待确认队列与服务宿主。
/// 服务只在操作员显式点击启动后绑定私网地址；所有状态变更都回到创建本对象的 Dispatcher。
/// </summary>
public sealed class LanPanelViewModel : ObservableObject, IAsyncDisposable
{
    private readonly NativeStore? _store;
    private readonly LanAuthStore _authStore = new();
    private readonly LanPendingQueue _queue = new();
    private readonly LanServerHost _serverHost;
    private readonly LanApprovalService? _approvalService;
    private readonly Func<LanApprovalResult, Task>? _recordChanged;
    private readonly Dispatcher _dispatcher;
    private readonly DispatcherTimer _refreshTimer;
    private readonly Dictionary<string, LanPendingRowViewModel> _pendingRows = new(StringComparer.Ordinal);
    private readonly Dictionary<string, LanPhoneRowViewModel> _phoneRows = new(StringComparer.Ordinal);
    private bool _isRunning;
    private bool _isBusy;
    private bool _hasError;
    private int _pendingCount;
    private string _url = string.Empty;
    private string _pin = string.Empty;
    private string _statusMessage = "手机收件未启动";
    private string _errorMessage = string.Empty;
    private string _phoneSummary = "没有已连接手机";
    private LanAddressOption? _selectedAddress;

    public LanPanelViewModel(
        InputParser parser,
        NativeStore? store,
        Func<LanSessionSnapshot?> sessionSnapshot,
        Func<LanApprovalResult, Task>? recordChanged = null)
    {
        ArgumentNullException.ThrowIfNull(parser);
        ArgumentNullException.ThrowIfNull(sessionSnapshot);
        _store = store;
        _recordChanged = recordChanged;
        _dispatcher = Dispatcher.CurrentDispatcher;
        var sessions = new SessionSource(sessionSnapshot);
        _serverHost = new LanServerHost(new LanServerOptions(), _queue, _authStore, sessions, parser);
        if (store is not null)
        {
            _approvalService = new LanApprovalService(store, _queue, sessions);
        }

        _refreshTimer = new DispatcherTimer(DispatcherPriority.Background, _dispatcher)
        {
            Interval = TimeSpan.FromSeconds(1)
        };
        _refreshTimer.Tick += RefreshTimer_Tick;
        LoadAddressOptions();
        if (store is null)
        {
            _statusMessage = "预览模式：手机收件不可用";
        }
    }

    public ObservableCollection<LanAddressOption> AddressOptions { get; } = new();
    public ObservableCollection<LanPendingRowViewModel> PendingItems { get; } = new();
    public ObservableCollection<LanPhoneRowViewModel> ConnectedPhones { get; } = new();

    public bool IsAvailable => _store is not null;
    public bool IsRunning
    {
        get => _isRunning;
        private set
        {
            if (SetProperty(ref _isRunning, value))
            {
                NotifyActionAvailability();
            }
        }
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                NotifyActionAvailability();
            }
        }
    }

    public bool CanStart => IsAvailable && !IsRunning && !IsBusy;
    public bool CanStop => IsRunning && !IsBusy;
    public bool CanRotatePin => IsRunning && !IsBusy;

    public LanAddressOption? SelectedAddress
    {
        get => _selectedAddress;
        set => SetProperty(ref _selectedAddress, value);
    }

    public string Url
    {
        get => _url;
        private set
        {
            if (SetProperty(ref _url, value))
            {
                OnPropertyChanged(nameof(UrlDisplay));
            }
        }
    }

    public string UrlDisplay => string.IsNullOrEmpty(Url) ? "未启动" : Url;

    public string Pin
    {
        get => _pin;
        private set
        {
            if (SetProperty(ref _pin, value))
            {
                OnPropertyChanged(nameof(PinDisplay));
            }
        }
    }

    public string PinDisplay => string.IsNullOrEmpty(Pin) ? "—" : Pin;

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public string ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (SetProperty(ref _errorMessage, value))
            {
                HasError = !string.IsNullOrWhiteSpace(value);
            }
        }
    }

    public bool HasError
    {
        get => _hasError;
        private set => SetProperty(ref _hasError, value);
    }

    public bool HasPending => PendingItems.Count > 0;
    public int PendingCount => PendingItems.Count;

    public string PhoneSummary
    {
        get => _phoneSummary;
        private set => SetProperty(ref _phoneSummary, value);
    }

    /// <summary>
    /// 只启动私网候选地址，端口依次尝试 8731–8740；第一个成功监听的端口生效。
    /// </summary>
    public async Task StartAsync()
    {
        if (!IsAvailable)
        {
            ErrorMessage = "预览模式不能启动手机收件。";
            return;
        }
        if (IsRunning || IsBusy)
        {
            return;
        }

        var selected = SelectedAddress;
        if (selected is null)
        {
            ErrorMessage = "未发现可用的私有 IPv4 地址；请连接局域网后重试。";
            return;
        }

        await StartCoreAsync(selected.Address, LanBindingResolver.CandidatePorts);
    }

    /// <summary>
    /// 测试专用入口：只允许回环地址，避免测试绑定真实私网。
    /// 生产启动路径仍走 StartAsync 的私网候选。
    /// </summary>
    internal Task StartForTestingAsync(IPAddress address, int port)
    {
        ArgumentNullException.ThrowIfNull(address);
        if (!IPAddress.IsLoopback(address))
        {
            throw new ArgumentException("测试入口只允许回环地址。", nameof(address));
        }
        if (port is < 0 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(port));
        }

        return StartCoreAsync(address, new[] { port });
    }

    public async Task StopAsync()
    {
        if (!IsRunning || IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            _refreshTimer.Stop();
            await _serverHost.StopAsync();
            StatusMessage = "手机收件已停止；手机连接已断开，待确认队列已清空。";
        }
        catch (Exception exception)
        {
            ErrorMessage = $"停止手机收件时出错：{exception.Message}";
        }
        finally
        {
            IsRunning = _serverHost.IsRunning;
            IsBusy = false;
            RefreshFromStores();
        }
    }

    public void RotatePin()
    {
        if (!IsRunning)
        {
            return;
        }

        _authStore.RotatePin();
        Pin = _authStore.Pin;
        RefreshPhoneRows();
        StatusMessage = "PIN 已更换；已连接的手机需要重新配对。";
    }

    public void RevokePhone(LanPhoneRowViewModel phone)
    {
        ArgumentNullException.ThrowIfNull(phone);
        var removed = _authStore.RevokeByPhoneId(phone.PhoneId);
        StatusMessage = removed > 0
            ? $"已断开 {phone.DisplayLabel}。"
            : "该手机已离线。";
        RefreshPhoneRows();
    }

    public void Reject(LanPendingRowViewModel item)
    {
        ArgumentNullException.ThrowIfNull(item);
        try
        {
            StatusMessage = _queue.TryReject(item.ClientSubmissionId, "PC 端拒绝")
                ? $"已拒绝 {item.Callsign} 的提交。"
                : "该条正在处理中或已处理，未拒绝。";
        }
        catch (Exception exception)
        {
            ErrorMessage = $"拒绝失败：{exception.Message}";
        }

        RefreshPendingRows();
    }

    /// <summary>
    /// 点击时由 LanApprovalService 读取当前场次；写入 SQLite 只发生在这里。
    /// Busy / WriteCommitted / 场次不可用都不会向操作员报告「已确认」。
    /// </summary>
    public async Task ApproveAsync(LanPendingRowViewModel item)
    {
        ArgumentNullException.ThrowIfNull(item);
        if (item.IsBusy)
        {
            return;
        }
        if (_approvalService is null)
        {
            ErrorMessage = "预览模式不能确认手机记录。";
            return;
        }

        item.IsBusy = true;
        ErrorMessage = string.Empty;
        try
        {
            var result = await _approvalService.ApproveAsync(item.ClientSubmissionId);
            switch (result.Status)
            {
                case LanApprovalStatus.Approved:
                    StatusMessage = $"已确认 {item.Callsign}：第 {result.Checkin?.SequenceNo} 条已写入本场记录。";
                    break;
                case LanApprovalStatus.Busy:
                    StatusMessage = "该条正在被处理，请稍候。";
                    break;
                case LanApprovalStatus.NotPending:
                    StatusMessage = "该条已被处理或已过期，未写入。";
                    break;
                case LanApprovalStatus.NotFound:
                    StatusMessage = "该条已不在队列中，未写入。";
                    break;
                case LanApprovalStatus.SessionUnavailable:
                    ErrorMessage = "没有可写入的进行中场次，未写入；请先选择或新建场次。";
                    break;
                case LanApprovalStatus.SessionEnded:
                    ErrorMessage = "当前场次已结束，未写入；请重开场次后再确认。";
                    break;
                case LanApprovalStatus.WriteCommitted:
                    ErrorMessage = $"记录已写入（第 {result.Checkin?.SequenceNo} 条），但待确认状态未能更新；请在“本场记录”中核对，未核对前不要重复提交。";
                    break;
            }

            RefreshFromStores();
            if ((result.Status is LanApprovalStatus.Approved or LanApprovalStatus.WriteCommitted)
                && _recordChanged is not null)
            {
                try
                {
                    await _recordChanged(result);
                }
                catch (Exception exception)
                {
                    ErrorMessage = $"记录已写入，但刷新本场列表失败：{exception.Message}";
                }
            }
        }
        catch (Exception exception)
        {
            ErrorMessage = $"确认失败：{exception.Message}";
        }
        finally
        {
            item.IsBusy = false;
        }
    }

    public async ValueTask DisposeAsync()
    {
        _refreshTimer.Stop();
        _refreshTimer.Tick -= RefreshTimer_Tick;
        try
        {
            await _serverHost.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception)
        {
            // 退出路径不能再向已关闭的 UI 报错；服务停止超时或 Kestrel 关闭异常
            // 不允许阻止应用退出，记录已提交的 SQLite 行也不受影响。
        }
    }

    private async Task StartCoreAsync(IPAddress address, IReadOnlyList<int> ports)
    {
        if (IsRunning || IsBusy)
        {
            return;
        }

        IsBusy = true;
        ErrorMessage = string.Empty;
        Exception? lastError = null;
        try
        {
            foreach (var port in ports)
            {
                try
                {
                    await _serverHost.StartAsync(address, port);
                    lastError = null;
                    break;
                }
                catch (Exception exception) when (exception is IOException or SocketException)
                {
                    lastError = exception;
                }
            }

            if (!_serverHost.IsRunning)
            {
                StatusMessage = "手机收件未启动";
                ErrorMessage = lastError is null
                    ? "手机收件未能启动。"
                    : $"端口 {LanBindingResolver.FirstPort}–{LanBindingResolver.LastPort} 无法监听：{lastError.Message}";
                return;
            }

            IsRunning = true;
            Pin = _authStore.Pin;
            Url = _serverHost.BaseUrl ?? string.Empty;
            StatusMessage = $"手机收件已启动，正在监听 {address}。";
            _refreshTimer.Start();
        }
        catch (Exception exception)
        {
            StatusMessage = "手机收件未启动";
            ErrorMessage = $"手机收件启动失败：{exception.Message}";
        }
        finally
        {
            IsBusy = false;
            RefreshFromStores();
        }
    }

    private void LoadAddressOptions()
    {
        try
        {
            foreach (var candidate in LanBindingResolver.GetPrivateIpv4Candidates())
            {
                AddressOptions.Add(new LanAddressOption(
                    candidate.Address,
                    $"{candidate.Address} · {candidate.InterfaceName}"));
            }
        }
        catch (Exception exception)
        {
            ErrorMessage = $"读取本机网卡地址失败：{exception.Message}";
        }

        SelectedAddress = AddressOptions.FirstOrDefault();
    }

    private void RefreshTimer_Tick(object? sender, EventArgs e) => RefreshFromStores();

    private void RefreshFromStores()
    {
        if (!_dispatcher.CheckAccess())
        {
            _dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(RefreshFromStores));
            return;
        }

        Url = IsRunning ? _serverHost.BaseUrl ?? string.Empty : string.Empty;
        Pin = IsRunning ? _authStore.Pin : string.Empty;
        RefreshPendingRows();
        RefreshPhoneRows();
    }

    private void RefreshPendingRows()
    {
        var snapshot = _queue.GetPendingSnapshot();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        for (var index = 0; index < snapshot.Count; index++)
        {
            var item = snapshot[index];
            seen.Add(item.ClientSubmissionId);
            if (!_pendingRows.TryGetValue(item.ClientSubmissionId, out var row))
            {
                row = new LanPendingRowViewModel(item, index + 1);
                _pendingRows.Add(item.ClientSubmissionId, row);
                PendingItems.Add(row);
            }
            row.UpdatePosition(index + 1);
        }

        for (var index = PendingItems.Count - 1; index >= 0; index--)
        {
            var row = PendingItems[index];
            if (seen.Contains(row.ClientSubmissionId))
            {
                continue;
            }

            PendingItems.RemoveAt(index);
            _pendingRows.Remove(row.ClientSubmissionId);
        }

        if (PendingItems.Count == _pendingCount)
        {
            return;
        }

        _pendingCount = PendingItems.Count;
        OnPropertyChanged(nameof(PendingCount));
        OnPropertyChanged(nameof(HasPending));
    }

    private void RefreshPhoneRows()
    {
        var sessions = _authStore.GetActiveSessions();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var session in sessions)
        {
            seen.Add(session.PhoneId);
            if (!_phoneRows.TryGetValue(session.PhoneId, out var row))
            {
                row = new LanPhoneRowViewModel(session.PhoneId);
                _phoneRows.Add(session.PhoneId, row);
                ConnectedPhones.Add(row);
            }
            row.Update(session);
        }

        for (var index = ConnectedPhones.Count - 1; index >= 0; index--)
        {
            var row = ConnectedPhones[index];
            if (seen.Contains(row.PhoneId))
            {
                continue;
            }

            ConnectedPhones.RemoveAt(index);
            _phoneRows.Remove(row.PhoneId);
        }

        PhoneSummary = ConnectedPhones.Count == 0
            ? "没有已连接手机"
            : $"已连接 {ConnectedPhones.Count} 部手机";
    }

    private void NotifyActionAvailability()
    {
        OnPropertyChanged(nameof(CanStart));
        OnPropertyChanged(nameof(CanStop));
        OnPropertyChanged(nameof(CanRotatePin));
    }

    private sealed class SessionSource(Func<LanSessionSnapshot?> snapshot) : ILanSessionSource
    {
        public LanSessionSnapshot? CurrentSession => snapshot();
    }
}
