using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Input;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;

namespace HamCheckin.Native.App.Views;

public partial class FieldEditWindow : Window, INotifyPropertyChanged
{
    private readonly MainViewModel _mainViewModel;
    private readonly FieldEditRequest _request;
    private readonly HashSet<string> _consumedTokens = new(StringComparer.Ordinal);
    private readonly HashSet<int> _consumedTokenIndexes = new();
    private FieldParseResult _parseResult;

    public FieldEditWindow(MainViewModel mainViewModel, FieldEditRequest request)
    {
        _mainViewModel = mainViewModel;
        _request = request;
        _parseResult = mainViewModel.ParseField(request.Field, request.CurrentValue);
        InitializeComponent();
        DataContext = this;
        EditText = request.CurrentValue;
        UnmatchedTokens = new ObservableCollection<UnmatchedTokenView>(
            request.UnmatchedCurrent
                .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .Select((value, index) => new UnmatchedTokenView(index, value)));
        RefreshParse();
        Loaded += (_, _) =>
        {
            EditBox.Focus();
            EditBox.SelectAll();
        };
    }

    public string DialogTitle => $"修改 {FieldName(_request.Field)}";
    public string SessionLine => $"第 {_request.SequenceNo} 条 · {_request.Callsign} · 当前只修改 {FieldName(_request.Field)}";
    public string CurrentValueDisplay => string.IsNullOrWhiteSpace(_request.CurrentValue) ? "（空）" : _request.CurrentValue;
    public string RawInputDisplay => $"原始录入：{_request.RawInput}";

    private string _editText = string.Empty;
    private string _previewLine = "规范结果：—";
    private string _sourceLine = string.Empty;
    private bool _removeConsumedTokens = true;
    private string? _selectedCandidate;

    public string EditText { get => _editText; set { if (_editText != value) { _editText = value; OnPropertyChanged(); } } }
    public string PreviewLine { get => _previewLine; private set { _previewLine = value; OnPropertyChanged(); } }
    public string SourceLine { get => _sourceLine; private set { _sourceLine = value; OnPropertyChanged(); } }
    public bool RemoveConsumedTokens { get => _removeConsumedTokens; set { _removeConsumedTokens = value; OnPropertyChanged(); } }
    public ObservableCollection<string> Candidates { get; } = new();
    public ObservableCollection<UnmatchedTokenView> UnmatchedTokens { get; } = new();
    public string? SelectedCandidate { get => _selectedCandidate; set { _selectedCandidate = value; OnPropertyChanged(); } }
    public FieldEditCommit? Commit { get; private set; }

    internal void EditBoxForPreview(string text)
    {
        EditBox.ApplyTemplate();
        EditText = text;
        EditBox.Text = text;
        EditBox.CaretIndex = text.Length;
        RefreshParse();
    }

    private void EditBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
    {
        if (!IsInitialized)
        {
            return;
        }
        RefreshParse();
    }

    private void RefreshParse()
    {
        _parseResult = _mainViewModel.ParseField(_request.Field, EditText);
        PreviewLine = $"规范结果：{(string.IsNullOrWhiteSpace(_parseResult.CanonicalValue) ? "—" : _parseResult.CanonicalValue)}";
        SourceLine = $"来源：{_parseResult.Source} · 置信度 {_parseResult.Confidence:0.00}";
        Candidates.Clear();
        foreach (var item in _parseResult.Candidates)
        {
            Candidates.Add(item);
        }
    }

    private void Candidates_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
    {
        if (SelectedCandidate is not null && SelectedCandidate.Length > 0)
        {
            EditText = SelectedCandidate;
            EditBox.Text = SelectedCandidate;
            EditBox.CaretIndex = EditBox.Text.Length;
            RefreshParse();
        }
    }

    private void FillToken_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { Tag: UnmatchedTokenView token })
        {
            return;
        }
        EditText = token.Value;
        EditBox.Text = token.Value;
        EditBox.CaretIndex = token.Length;
        _consumedTokens.Add(token.Value);
        _consumedTokenIndexes.Add(token.Index);
        RefreshParse();
        EditBox.Focus();
    }

    private void CopyAll_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_request.UnmatchedCurrent))
        {
            Clipboard.SetText(_request.UnmatchedCurrent);
        }
    }

    private void CopyOne_Click(object sender, RoutedEventArgs e)
    {
        if (UnmatchedTokens.Count > 0)
        {
            Clipboard.SetText(UnmatchedTokens[0].Value);
        }
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        Commit = new FieldEditCommit(_request.CheckinId, _request.Field, _request.CurrentValue,
            _parseResult.CanonicalValue, EditText, _consumedTokens.ToArray(),
            RemoveConsumedTokens, _request.ExpectedUpdatedAt, _parseResult.Source,
            _consumedTokenIndexes.OrderBy(index => index).ToArray());
        DialogResult = true;
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void EditBox_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && Keyboard.Modifiers == ModifierKeys.None)
        {
            Save_Click(sender, e);
            e.Handled = true;
        }
        else if (e.Key == Key.Escape && Keyboard.Modifiers == ModifierKeys.None)
        {
            Cancel_Click(sender, e);
            e.Handled = true;
        }
        else if (e.Key == Key.C && Keyboard.Modifiers == (ModifierKeys.Control | ModifierKeys.Shift))
        {
            CopyAll_Click(sender, e);
            e.Handled = true;
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    private static string FieldName(FieldKind field) => field switch
    {
        FieldKind.Time => "时间", FieldKind.Callsign => "呼号", FieldKind.Qth => "QTH",
        FieldKind.Device => "设备", FieldKind.Antenna => "天线", FieldKind.Power => "功率",
        FieldKind.Signal => "信号", _ => field.ToString()
    };
}

public sealed record UnmatchedTokenView(int Index, string Value)
{
    public int Length => Value.Length;
}
