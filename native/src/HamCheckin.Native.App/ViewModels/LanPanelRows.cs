using System.Globalization;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.Core.Lan;

namespace HamCheckin.Native.App.ViewModels;

/// <summary>待确认列表中的一条手机提交；原文与解析值在入队后不再变化。</summary>
public sealed class LanPendingRowViewModel : ObservableObject
{
    private bool _isBusy;
    private int _position;

    public LanPendingRowViewModel(LanPendingItem item, int position)
    {
        ArgumentNullException.ThrowIfNull(item);
        ClientSubmissionId = item.ClientSubmissionId;
        RawText = item.RawText;
        _position = position;
        ReceivedText = item.ReceivedAt.ToLocalTime()
            .ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        Callsign = ValueOrDash(item.Parsed.Callsign.Value);
        ParsedLineOne = $"呼号 {Callsign} · QTH {ValueOrDash(item.Parsed.Qth.Value)} · 设备 {ValueOrDash(item.Parsed.Device.Value)}";
        ParsedLineTwo = $"天线 {ValueOrDash(item.Parsed.Antenna.Value)} · 功率 {ValueOrDash(item.Parsed.Power.Value)} · 信号 {ValueOrDash(item.Parsed.Signal.Value)}";
        UnmatchedText = string.IsNullOrWhiteSpace(item.Parsed.UnmatchedText)
            ? "未识别内容：无"
            : $"未识别内容：{item.Parsed.UnmatchedText}";
    }

    public string ClientSubmissionId { get; }
    public string RawText { get; }
    public string ReceivedText { get; }
    public string Callsign { get; }
    public string ParsedLineOne { get; }
    public string ParsedLineTwo { get; }
    public string UnmatchedText { get; }

    public int Position
    {
        get => _position;
        private set
        {
            if (SetProperty(ref _position, value))
            {
                OnPropertyChanged(nameof(HeaderText));
            }
        }
    }

    public string HeaderText => $"第 {Position} 位 · {ReceivedText} 收到";

    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            if (SetProperty(ref _isBusy, value))
            {
                OnPropertyChanged(nameof(CanDecide));
                OnPropertyChanged(nameof(ApproveButtonText));
            }
        }
    }

    public bool CanDecide => !IsBusy;
    public string ApproveButtonText => IsBusy ? "处理中…" : "确认入册";

    public void UpdatePosition(int position) => Position = position;

    private static string ValueOrDash(string value) =>
        string.IsNullOrWhiteSpace(value) ? "—" : value;
}

/// <summary>已连接手机的一行；只显示配对时登记的标签与最近活动时间。</summary>
public sealed class LanPhoneRowViewModel : ObservableObject
{
    private string _displayLabel = string.Empty;
    private string _detailText = string.Empty;

    public LanPhoneRowViewModel(string phoneId) => PhoneId = phoneId;

    public string PhoneId { get; }

    public string DisplayLabel
    {
        get => _displayLabel;
        private set => SetProperty(ref _displayLabel, value);
    }

    public string DetailText
    {
        get => _detailText;
        private set => SetProperty(ref _detailText, value);
    }

    public void Update(LanTokenSession session)
    {
        DisplayLabel = string.IsNullOrWhiteSpace(session.DeviceLabel)
            ? "未命名手机"
            : session.DeviceLabel;
        var lastSeen = session.LastSeenAt.ToLocalTime()
            .ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        DetailText = $"{PhoneId} · {lastSeen} 最近活动";
    }
}
