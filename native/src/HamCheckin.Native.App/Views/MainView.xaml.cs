using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.App.Views;

public partial class MainView : UserControl
{
    private const string InputOrigin = "main-input";
    private MainViewModel? _viewModel;
    private QuickWindow? _quickWindow;
    private bool _synchronizingInput;
    private bool _imeComposing;
    private long _appliedInputRevision;

    public MainView()
    {
        InitializeComponent();
        TextCompositionManager.AddPreviewTextInputStartHandler(InputBox, InputBox_TextInputStart);
        TextCompositionManager.AddPreviewTextInputUpdateHandler(InputBox, InputBox_TextInputUpdate);
        TextCompositionManager.AddTextInputHandler(InputBox, InputBox_TextInput);
    }

    private void Root_Loaded(object sender, RoutedEventArgs e)
    {
        if (!System.ComponentModel.DesignerProperties.GetIsInDesignMode(this))
        {
            SyncInputBox(_viewModel?.InputDraft, moveCaretToEnd: false);
            InputBox.Focus();
            Keyboard.Focus(InputBox);
        }
    }

    private void Root_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.ParseUpdated -= ViewModel_ParseUpdated;
            _viewModel.SubmissionSucceeded -= ViewModel_SubmissionSucceeded;
            _viewModel.QuickWindowRequested -= ViewModel_QuickWindowRequested;
            _viewModel.InputDraftChanged -= ViewModel_InputDraftChanged;
        }
        _viewModel = e.NewValue as MainViewModel;
        if (_viewModel is not null)
        {
            _viewModel.ParseUpdated += ViewModel_ParseUpdated;
            _viewModel.SubmissionSucceeded += ViewModel_SubmissionSucceeded;
            _viewModel.QuickWindowRequested += ViewModel_QuickWindowRequested;
            _viewModel.InputDraftChanged += ViewModel_InputDraftChanged;
            SyncInputBox(_viewModel.InputDraft, moveCaretToEnd: false);
        }
    }

    private void InputBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_synchronizingInput || _viewModel is null)
        {
            return;
        }

        var snapshot = _viewModel.ApplyInputEdit(
            InputOrigin,
            _appliedInputRevision,
            InputBox.Text,
            _imeComposing);
        if (snapshot.Revision != _appliedInputRevision
            || !string.Equals(snapshot.Text, InputBox.Text, StringComparison.Ordinal))
        {
            SyncInputBox(snapshot, moveCaretToEnd: false);
        }
    }

    private void InputBox_GotKeyboardFocus(object sender, KeyboardFocusChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            SyncInputBox(_viewModel.InputDraft, moveCaretToEnd: false);
        }
    }

    private void InputBox_TextInputStart(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(true);

    private void InputBox_TextInputUpdate(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(true);

    private void InputBox_TextInput(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(false);

    private void SetImeComposition(bool composing)
    {
        _imeComposing = composing;
        _viewModel?.SetImeCompositionState(InputOrigin, composing);
    }

    private void ViewModel_InputDraftChanged(object? sender, QuickInputDraftChangedEventArgs e)
    {
        _appliedInputRevision = e.Snapshot.Revision;
        if (e.Snapshot.OriginId == InputOrigin && InputBox.IsKeyboardFocusWithin)
        {
            return;
        }

        SyncInputBox(e.Snapshot, moveCaretToEnd: true);
    }

    private void SyncInputBox(QuickInputDraftSnapshot? snapshot, bool moveCaretToEnd)
    {
        if (snapshot is null)
        {
            return;
        }

        _appliedInputRevision = snapshot.Revision;
        if (string.Equals(InputBox.Text, snapshot.Text, StringComparison.Ordinal))
        {
            if (moveCaretToEnd && !InputBox.IsKeyboardFocusWithin)
            {
                InputBox.CaretIndex = InputBox.Text.Length;
            }
            return;
        }

        _synchronizingInput = true;
        try
        {
            InputBox.Text = snapshot.Text;
            if (moveCaretToEnd)
            {
                InputBox.CaretIndex = InputBox.Text.Length;
            }
        }
        finally
        {
            _synchronizingInput = false;
        }
    }

    private void InputBox_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        if (MatchesShortcut(e, "submit"))
        {
            if (_viewModel.SubmitCommand.CanExecute(null))
            {
                _viewModel.SubmitCommand.Execute(null);
            }
            e.Handled = true;
        }
        else if (MatchesShortcut(e, "clear"))
        {
            _viewModel.ClearCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void Root_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        if (MatchesShortcut(e, "quick-window"))
        {
            ToggleQuickWindow(); e.Handled = true; return;
        }
        if (MatchesShortcut(e, "focus-input"))
        {
            QuickNav.IsChecked = true; InputBox.Focus(); InputBox.SelectAll(); e.Handled = true; return;
        }
        if (MatchesShortcut(e, "export"))
        {
            _viewModel.ExportCommand.Execute(null); e.Handled = true; return;
        }
        if (MatchesShortcut(e, "accept-suggestion") && InputBox.IsKeyboardFocusWithin)
        {
            ApplySuggestion_Click(this, new RoutedEventArgs()); e.Handled = true; return;
        }
        if (MatchesShortcut(e, "submit") && InputBox.IsKeyboardFocusWithin)
        {
            if (_viewModel.SubmitCommand.CanExecute(null)) _viewModel.SubmitCommand.Execute(null);
            e.Handled = true; return;
        }
        if (MatchesShortcut(e, "clear") && InputBox.IsKeyboardFocusWithin)
        {
            _viewModel.ClearCommand.Execute(null); e.Handled = true; return;
        }
        if (MatchesShortcut(e, "nav-quick")) { QuickNav.IsChecked = true; e.Handled = true; return; }
        if (MatchesShortcut(e, "nav-records")) { SelectNav("Records"); e.Handled = true; return; }
        if (MatchesShortcut(e, "nav-catalog")) { SelectNav("Catalog"); e.Handled = true; return; }
        if (MatchesShortcut(e, "nav-settings")) { SelectNav("Settings"); e.Handled = true; return; }
    }

    private void Nav_Checked(object sender, RoutedEventArgs e)
    {
        if (sender is RadioButton { Tag: string pageName } && QuickPage is not null)
        {
            ShowPage(pageName);
        }
    }

    public void ShowPage(string pageName)
    {
        var pages = new[] { QuickPage, RecordsPage, CatalogPage, SettingsPage };
        foreach (var page in pages)
        {
            page.Visibility = string.Equals(page.Tag as string, pageName, StringComparison.Ordinal)
                ? Visibility.Visible : Visibility.Collapsed;
        }
        if (_viewModel is not null)
        {
            _viewModel.CurrentPage = pageName;
        }
        var selected = pages.FirstOrDefault(page => page.Visibility == Visibility.Visible);
        if (selected is not null)
        {
            AnimatePage(selected);
        }
    }

    internal void SetPreviewInputText()
    {
        if (_viewModel is null)
        {
            return;
        }
        InputBox.ApplyTemplate();
        SyncInputBox(_viewModel.InputDraft, moveCaretToEnd: true);
        InputBox.UpdateLayout();
        Keyboard.Focus(InputBox);
    }

    private void SelectNav(string page)
    {
        if (page == "Quick") QuickNav.IsChecked = true;
        else ShowPage(page);
    }

    private void ViewModel_ParseUpdated(object? sender, EventArgs e)
    {
        if (!ShouldAnimate()) return;
        ParseStrip.BeginAnimation(OpacityProperty, new DoubleAnimation(0.72, 1.0, TimeSpan.FromMilliseconds(80)));
    }

    private void ViewModel_SubmissionSucceeded(object? sender, EventArgs e)
    {
        if (!ShouldAnimate()) return;
        SuccessFlash.BeginAnimation(OpacityProperty, new DoubleAnimation
        {
            From = 0.4, To = 0, Duration = TimeSpan.FromMilliseconds(220),
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }
        });
    }

    private void ViewModel_QuickWindowRequested(object? sender, EventArgs e) => ToggleQuickWindow();

    private void RecordsGrid_PreviewMouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (_viewModel is null || sender is not DataGrid grid)
        {
            return;
        }
        var cell = FindParent<DataGridCell>(e.OriginalSource as DependencyObject);
        if (cell?.DataContext is CheckinEntry row)
        {
            var field = FieldFromColumn(cell.Column?.DisplayIndex ?? -1, grid == RecentGrid);
            if (field is not null)
            {
                _ = OpenFieldEditorAsync(row, field.Value);
                e.Handled = true;
            }
        }
    }

    private void RecordsGrid_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (_viewModel is null || sender is not DataGrid grid || grid.SelectedItem is not CheckinEntry row)
        {
            return;
        }
        if (e.Key is not (Key.Enter or Key.F2))
        {
            return;
        }
        var index = grid.SelectedCells.Count > 0 ? grid.SelectedCells[0].Column.DisplayIndex : -1;
        var field = FieldFromColumn(index, grid == RecentGrid);
        if (field is not null)
        {
            _ = OpenFieldEditorAsync(row, field.Value);
            e.Handled = true;
        }
    }

    private async Task OpenFieldEditorAsync(CheckinEntry row, FieldKind field)
    {
        if (_viewModel is null)
        {
            return;
        }
        try
        {
            var request = await _viewModel.CreateFieldEditRequestAsync(row, field);
            if (request is null)
            {
                return;
            }
            var window = new FieldEditWindow(_viewModel, request)
            {
                Owner = Window.GetWindow(this)
            };
            if (window.ShowDialog() == true && window.Commit is not null)
            {
                await _viewModel.ApplyFieldEditAsync(window.Commit);
            }
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "字段修改未保存", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void OpenQuickWindow_Click(object sender, RoutedEventArgs e) => ToggleQuickWindow();

    private void OpenAbout_Click(object sender, RoutedEventArgs e)
    {
        var window = new AboutWindow { Owner = Window.GetWindow(this) };
        window.ShowDialog();
    }

    private void ToggleQuickWindow()
    {
        if (_viewModel is null) return;
        if (_quickWindow is null)
        {
            _quickWindow = new QuickWindow
            {
                DataContext = _viewModel,
                Owner = Window.GetWindow(this)
            };
            _quickWindow.Closed += (_, _) => _quickWindow = null;
        }
        if (_quickWindow.IsVisible)
        {
            _quickWindow.Hide();
        }
        else
        {
            _quickWindow.Show();
            _quickWindow.Activate();
        }
    }

    internal void ToggleQuickWindowFromHotkey() => ToggleQuickWindow();

    private void CaptureShortcut_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not Button { Tag: string actionKey }) return;
        var capture = new ShortcutCaptureWindow { Owner = Window.GetWindow(this) };
        if (capture.ShowDialog() == true)
        {
            _viewModel.UpdateShortcut(actionKey, capture.GestureText);
        }
    }

    private void ResetShortcuts_Click(object sender, RoutedEventArgs e) => _viewModel?.ResetShortcuts();

    private bool MatchesShortcut(KeyEventArgs e, string actionKey)
    {
        var gesture = _viewModel?.GetShortcut(actionKey)?.Gesture;
        return gesture is not null && ShortcutGesture.Matches(gesture, e);
    }

    private void ApplySuggestion_Click(object sender, RoutedEventArgs e)
    {
        _viewModel?.SetInputText("BA4RLL QYT6900 5W YZ YZ");
        InputBox.Focus();
        InputBox.CaretIndex = InputBox.Text.Length;
    }

    private async void DownloadProvince_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null)
        {
            await _viewModel.RefreshQthPackagesAsync(
                "已刷新本地地点包省市树；详细地点下载源尚未配置，不会阻塞快速录入");
        }
    }

    private async void UpdatePlaces_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null)
        {
            await _viewModel.RefreshQthPackagesAsync(
                "已检查本地地点包；远程省市包源需配置后才会联网更新");
        }
    }

    private async void NewSession_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        var dialog = new SessionEditorWindow(null) { Owner = Window.GetWindow(this) };
        if (dialog.ShowDialog() == true && dialog.Result is { } result)
        {
            try
            {
                await _viewModel.CreateSessionAsync(result.Name, result.Date, result.OperatorCallsign,
                    result.RepeaterName, result.WorkbookPath, result.SheetName);
            }
            catch (Exception exception)
            {
                MessageBox.Show(exception.Message, "场次创建失败", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }
    }

    private async void SelectSession_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        try
        {
            var sessions = await _viewModel.ListSessionsAsync();
            var dialog = new SessionPickerWindow(sessions) { Owner = Window.GetWindow(this) };
            if (dialog.ShowDialog() == true && dialog.SelectedSession is { } selected)
            {
                await _viewModel.SelectSessionAsync(selected.Id);
            }
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "场次切换失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private async void EditSession_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        try
        {
            var session = await _viewModel.GetSessionAsync();
            if (session is null)
            {
                return;
            }
            var dialog = new SessionEditorWindow(session) { Owner = Window.GetWindow(this) };
            if (dialog.ShowDialog() == true && dialog.Result is { } result)
            {
                await _viewModel.UpdateCurrentSessionInfoAsync(result.OperatorCallsign,
                    result.RepeaterName, result.WorkbookPath, result.SheetName);
            }
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "场次信息未保存", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private async void ToggleSessionStatus_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        var reopen = string.Equals(_viewModel.SessionStatus, "已结束", StringComparison.Ordinal);
        if (!reopen)
        {
            var answer = MessageBox.Show(
                "结束当前场次后将停止继续录入，但记录仍可查看和导出；之后可以再次点击此按钮重新打开。",
                "结束本场？", MessageBoxButton.OKCancel, MessageBoxImage.Question);
            if (answer != MessageBoxResult.OK)
            {
                return;
            }
        }

        try
        {
            await _viewModel.SetCurrentSessionStatusAsync(reopen);
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "场次状态未保存", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void AnimatePage(FrameworkElement page)
    {
        if (!ShouldAnimate()) { page.Opacity = 1; page.RenderTransform = Transform.Identity; return; }
        var translate = new TranslateTransform(8, 0);
        page.RenderTransform = translate; page.Opacity = 0;
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        page.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(140)) { EasingFunction = ease });
        translate.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(8, 0, TimeSpan.FromMilliseconds(150)) { EasingFunction = ease });
    }

    private bool ShouldAnimate() => SystemParameters.ClientAreaAnimation && (_viewModel?.AnimationsEnabled ?? true);

    private static FieldKind? FieldFromColumn(int column, bool quickGrid) => column switch
    {
        1 => FieldKind.Time,
        2 => FieldKind.Callsign,
        3 => FieldKind.Qth,
        4 => FieldKind.Device,
        5 => FieldKind.Antenna,
        6 => FieldKind.Power,
        7 when !quickGrid => FieldKind.Signal,
        _ => null
    };

    private static T? FindParent<T>(DependencyObject? value) where T : DependencyObject
    {
        while (value is not null)
        {
            if (value is T result) return result;
            value = VisualTreeHelper.GetParent(value);
        }
        return null;
    }
}

internal sealed class ShortcutCaptureWindow : Window
{
    private readonly TextBlock _display;
    public string GestureText { get; private set; } = string.Empty;

    public ShortcutCaptureWindow()
    {
        Title = "设置快捷键"; Width = 360; Height = 150; ResizeMode = ResizeMode.NoResize;
        WindowStartupLocation = WindowStartupLocation.CenterOwner; Background = Brushes.White;
        var panel = new StackPanel { Margin = new Thickness(18) };
        panel.Children.Add(new TextBlock { Text = "请直接按下新的快捷键组合（Esc 取消）", Margin = new Thickness(0, 0, 0, 12) });
        _display = new TextBlock { Text = "等待按键…", FontSize = 22, FontWeight = FontWeights.SemiBold, Foreground = Brushes.DodgerBlue, HorizontalAlignment = HorizontalAlignment.Center };
        panel.Children.Add(_display);
        Content = panel;
        PreviewKeyDown += CaptureKeyDown;
        Loaded += (_, _) => Focus();
    }

    private void CaptureKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape) { DialogResult = false; return; }
        var key = e.Key == Key.System ? e.SystemKey : e.Key;
        if (key is Key.LeftCtrl or Key.RightCtrl or Key.LeftShift or Key.RightShift or Key.LeftAlt or Key.RightAlt or Key.LWin or Key.RWin) return;
        var pieces = new List<string>();
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) pieces.Add("Ctrl");
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)) pieces.Add("Shift");
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Alt)) pieces.Add("Alt");
        pieces.Add(key switch
        {
            Key.Add => "Add",
            Key.Subtract => "Subtract",
            Key.OemPlus => "OemPlus",
            Key.OemMinus => "OemMinus",
            Key.Space => "Space",
            _ => key.ToString()
        });
        GestureText = string.Join("+", pieces);
        _display.Text = GestureText;
        DialogResult = true;
        e.Handled = true;
    }
}
