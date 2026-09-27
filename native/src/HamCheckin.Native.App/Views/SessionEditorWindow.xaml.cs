using System.Globalization;
using System.Windows;
using HamCheckin.Native.Core;

namespace HamCheckin.Native.App.Views;

public sealed record SessionEditorResult(
    string Name,
    string Date,
    string OperatorCallsign,
    string RepeaterName,
    string WorkbookPath,
    string SheetName);

public partial class SessionEditorWindow : Window
{
    private readonly bool _isNew;
    public SessionEditorResult? Result { get; private set; }

    public SessionEditorWindow(SessionInfo? session)
    {
        _isNew = session is null;
        InitializeComponent();
        TitleText.Text = _isNew ? "新建场次" : "编辑场次信息";
        NameBox.Text = session?.Name ?? "第1场点名";
        DateBox.Text = session?.Date ?? DateTime.Today.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        OperatorBox.Text = session?.OperatorCallsign ?? string.Empty;
        RepeaterBox.Text = session?.RepeaterName ?? string.Empty;
        WorkbookBox.Text = session?.WorkbookPath ?? string.Empty;
        if (!_isNew)
        {
            NameBox.IsReadOnly = true;
            DateBox.IsReadOnly = true;
            NameBox.ToolTip = "已有场次的名称和日期不可变，避免破坏导出和审计引用。";
            DateBox.ToolTip = NameBox.ToolTip;
        }
        PreviewKeyDown += Window_PreviewKeyDown;
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        var name = NameBox.Text.Trim();
        var date = DateBox.Text.Trim();
        if (name.Length == 0 || !DateOnly.TryParseExact(
                date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
        {
            MessageBox.Show("场次名称不能为空，日期请填写 yyyy-MM-dd。", "无法保存",
                MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        Result = new SessionEditorResult(
            name,
            date,
            OperatorBox.Text.Trim().ToUpperInvariant(),
            RepeaterBox.Text.Trim(),
            WorkbookBox.Text.Trim(),
            name);
        DialogResult = true;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;

    private void Window_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == System.Windows.Input.Key.Escape)
        {
            DialogResult = false;
            e.Handled = true;
        }
        else if (e.Key == System.Windows.Input.Key.Enter
                 && System.Windows.Input.Keyboard.Modifiers == System.Windows.Input.ModifierKeys.Control)
        {
            Save_Click(sender, e);
            e.Handled = true;
        }
    }
}
