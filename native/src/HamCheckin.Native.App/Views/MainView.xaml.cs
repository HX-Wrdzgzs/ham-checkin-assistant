using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.Media;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Updates;
using Microsoft.Win32;

namespace HamCheckin.Native.App.Views;

public partial class MainView : UserControl, IDisposable
{
    private const string InputOrigin = "main-input";
    private MainViewModel? _viewModel;
    private QuickWindow? _quickWindow;
    private bool _synchronizingInput;
    private bool _imeComposing;
    private long _appliedInputRevision;
    private string? _lastShownPage;
    private readonly ScreenRecordingService _recordingService = new();
    private readonly DispatcherTimer _recordingTimer;
    private MicrophoneCapture? _microphoneTest;
    private bool _recordingDevicesLoaded;

    public MainView()
    {
        InitializeComponent();
        TextCompositionManager.AddPreviewTextInputStartHandler(InputBox, InputBox_TextInputStart);
        TextCompositionManager.AddPreviewTextInputUpdateHandler(InputBox, InputBox_TextInputUpdate);
        TextCompositionManager.AddTextInputHandler(InputBox, InputBox_TextInput);
        _recordingTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
        _recordingTimer.Tick += RecordingTimer_Tick;
        _recordingService.StateChanged += RecordingService_StateChanged;
        _recordingService.LevelChanged += RecordingService_LevelChanged;
    }

    private void Root_Loaded(object sender, RoutedEventArgs e)
    {
        if (!System.ComponentModel.DesignerProperties.GetIsInDesignMode(this))
        {
            SyncInputBox(_viewModel?.InputDraft, moveCaretToEnd: false);
            if (!_recordingDevicesLoaded)
            {
                RefreshRecordingDevices();
                _recordingDevicesLoaded = true;
            }
            InputBox.Focus();
            Keyboard.Focus(InputBox);
        }
    }

    private void Root_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (SidebarColumn is null || BrandTextPanel is null)
        {
            return;
        }

        // Keep the navigation inside the client area when the user narrows
        // the window.  The icon rail preserves every destination while the
        // content area gets the space that the fixed-width labels used to
        // consume.
        var compact = ActualWidth < 1_080;
        SidebarColumn.Width = new GridLength(compact ? 72 : 190);
        BrandTextPanel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        WorkspaceLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        QuickNavLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        RecordsNavLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CatalogNavLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        RecordingNavLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        SettingsNavLabel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        LocalStatusTitle.Text = compact ? "●" : "●  本地录入";
        LocalStatusCard.Padding = compact ? new Thickness(8, 10, 8, 10) : new Thickness(11);
        foreach (var radio in NavigationPanel.Children.OfType<RadioButton>())
        {
            radio.Padding = compact ? new Thickness(8, 11, 8, 11) : new Thickness(14, 11, 14, 11);
            radio.Margin = compact ? new Thickness(3, 2, 3, 2) : new Thickness(8, 2, 8, 2);
            radio.HorizontalContentAlignment = compact
                ? HorizontalAlignment.Center
                : HorizontalAlignment.Left;
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
            _imeComposing,
            InputBox.IsKeyboardFocusWithin);
        _appliedInputRevision = snapshot.Revision;
        if (!string.Equals(snapshot.Text, InputBox.Text, StringComparison.Ordinal)
            && !InputBox.IsKeyboardFocusWithin)
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

    private void QthCandidate_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not Button { Tag: string candidate })
        {
            return;
        }

        _viewModel.SelectQthCandidate(candidate);
        InputBox.Focus();
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
        // The focused TextBox owns its complete raw string, caret and undo
        // stack.  Never assign Text while it has focus unless this is an
        // explicit operation such as a successful submit clearing the draft.
        // IME metadata and cross-window notifications are deliberately not
        // allowed to replace the complete string between TextChanged events.
        if (InputBox.IsKeyboardFocusWithin && !e.ForceApplyToEditors)
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
        var pageChanged = !string.Equals(_lastShownPage, pageName, StringComparison.Ordinal);
        _lastShownPage = pageName;
        var pages = new[] { QuickPage, RecordsPage, CatalogPage, RecordingPage, SettingsPage };
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
        if (selected is not null && pageChanged)
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

    internal void SetPreviewRecordingData()
    {
        RecordingTargetText.Text = "HAM 点名助手窗口 · 1180×760 · 仅录制软件窗口";
        MicrophoneComboBox.ItemsSource = new[]
        {
            new MicrophoneDevice(0, "麦克风阵列（预览设备）"),
            new MicrophoneDevice(1, "USB 无线电台麦克风（预览设备）")
        };
        MicrophoneComboBox.SelectedIndex = 0;
        RecordingPathBox.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Downloads", "HAM点名助手录屏", "点名现场_20260925_213000.mp4");
        MicrophoneLevelBar.Value = 0.42;
        MicrophoneStatusText.Text = "测试中 · 峰值 42% · 预览数据";
        RecordingStatusText.Text = "已准备";
        RecordingStatsText.Text = "软件窗口 1180×760 · 10 FPS · 麦克风已选择 · MP4";
        StartRecordingButton.IsEnabled = true;
        PauseRecordingButton.IsEnabled = false;
        StopRecordingButton.IsEnabled = false;
    }

    private void SelectNav(string page)
    {
        if (page == "Quick") QuickNav.IsChecked = true;
        else ShowPage(page);
    }

    private void RefreshRecordingDevices_Click(object sender, RoutedEventArgs e) => RefreshRecordingDevices();

    private void RefreshRecordingDevices()
    {
        if (_recordingService.IsActive)
        {
            return;
        }

        try
        {
            var window = Window.GetWindow(this);
            if (window is null)
            {
                throw new InvalidOperationException("HAM 点名助手主窗口尚未创建。");
            }

            var target = ScreenCapture.CreateTarget(window);
            RecordingTargetText.Text = target.DisplayName;

            var microphones = MicrophoneCapture.EnumerateDevices();
            MicrophoneComboBox.ItemsSource = microphones;
            if (MicrophoneComboBox.SelectedIndex < 0)
            {
                MicrophoneComboBox.SelectedIndex = 0;
            }

            MicrophoneStatusText.Text = microphones.Count == 0
                ? "未发现 Windows 麦克风设备；可以关闭麦克风后录制屏幕。"
                : $"已发现 {microphones.Count} 个输入设备；点击“测试麦克风”查看峰值。";
        }
        catch (Exception exception)
        {
            MicrophoneStatusText.Text = $"设备枚举失败：{exception.Message}";
        }

        if (string.IsNullOrWhiteSpace(RecordingPathBox.Text))
        {
            RecordingPathBox.Text = GetDefaultRecordingPath();
        }
    }

    private void IncludeMicrophoneChanged(object sender, RoutedEventArgs e)
    {
        if (MicrophoneComboBox is not null)
        {
            MicrophoneComboBox.IsEnabled = IncludeMicrophoneCheckBox.IsChecked == true && !_recordingService.IsActive;
        }
    }

    private void TestMicrophone_Click(object sender, RoutedEventArgs e)
    {
        if (_microphoneTest is not null)
        {
            StopMicrophoneTest();
            return;
        }

        if (MicrophoneComboBox.SelectedItem is not MicrophoneDevice microphone)
        {
            MicrophoneStatusText.Text = "请先选择一个麦克风输入设备。";
            return;
        }

        try
        {
            _microphoneTest = new MicrophoneCapture(microphone.Id);
            _microphoneTest.LevelChanged += MicrophoneTest_LevelChanged;
            _microphoneTest.Start();
            TestMicrophoneButton.Content = "停止测试";
            MicrophoneStatusText.Text = $"测试中：{microphone.Name} · 请对着麦克风说话或轻敲设备。";
        }
        catch (Exception exception)
        {
            StopMicrophoneTest();
            MicrophoneStatusText.Text = $"麦克风测试失败：{exception.Message}";
        }
    }

    private void MicrophoneTest_LevelChanged(object? sender, MicrophoneLevelEventArgs e)
    {
        Dispatcher.BeginInvoke(DispatcherPriority.DataBind, new Action(() =>
        {
            MicrophoneLevelBar.Value = e.Level;
            MicrophoneStatusText.Text = $"测试中 · 峰值 {(int)(e.Level * 100)}%";
        }));
    }

    private void StopMicrophoneTest()
    {
        if (_microphoneTest is null)
        {
            return;
        }

        try
        {
            _microphoneTest.LevelChanged -= MicrophoneTest_LevelChanged;
            _microphoneTest.Dispose();
        }
        catch (Exception exception)
        {
            MicrophoneStatusText.Text = $"麦克风已停止，但清理时出现提示：{exception.Message}";
        }
        finally
        {
            _microphoneTest = null;
            TestMicrophoneButton.Content = "测试麦克风";
            MicrophoneLevelBar.Value = 0;
        }
    }

    private void BrowseRecordingPath_Click(object sender, RoutedEventArgs e)
    {
        if (_recordingService.IsActive)
        {
            return;
        }

        var dialog = new SaveFileDialog
        {
            Title = "选择录屏输出文件",
            Filter = "MP4 录屏文件 (*.mp4)|*.mp4|所有文件 (*.*)|*.*",
            DefaultExt = ".mp4",
            AddExtension = true,
            FileName = Path.GetFileName(string.IsNullOrWhiteSpace(RecordingPathBox.Text)
                ? GetDefaultRecordingPath()
                : RecordingPathBox.Text)
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true)
        {
            RecordingPathBox.Text = dialog.FileName;
        }
    }

    private void StartRecording_Click(object sender, RoutedEventArgs e)
    {
        RecordingTarget target;
        try
        {
            target = ScreenCapture.CreateTarget(Window.GetWindow(this)
                ?? throw new InvalidOperationException("HAM 点名助手主窗口尚未创建。"));
            RecordingTargetText.Text = target.DisplayName;
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "无法开始录制", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        StopMicrophoneTest();
        var outputPath = string.IsNullOrWhiteSpace(RecordingPathBox.Text)
            ? GetDefaultRecordingPath()
            : RecordingPathBox.Text.Trim();
        if (outputPath.EndsWith(".avi", StringComparison.OrdinalIgnoreCase))
        {
            outputPath = Path.ChangeExtension(outputPath, ".mp4");
        }
        else if (!outputPath.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase))
        {
            outputPath += ".mp4";
        }

        var includeMicrophone = IncludeMicrophoneCheckBox.IsChecked == true;
        var microphoneId = (MicrophoneComboBox.SelectedItem as MicrophoneDevice)?.Id;
        try
        {
            _recordingService.Start(new RecordingOptions(
                target, outputPath, includeMicrophone, microphoneId));
            RecordingPathBox.Text = outputPath;
            _recordingTimer.Start();
            UpdateRecordingControls();
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "无法开始录屏", MessageBoxButton.OK, MessageBoxImage.Warning);
            UpdateRecordingControls();
        }
    }

    private void PauseRecording_Click(object sender, RoutedEventArgs e)
    {
        _recordingService.TogglePause();
        UpdateRecordingControls();
    }

    private async void StopRecording_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await _recordingService.StopAsync();
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "录屏收尾失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _recordingTimer.Stop();
            UpdateRecordingControls();
        }
    }

    private void RecordingService_StateChanged(object? sender, RecordingStateChangedEventArgs e)
    {
        void Apply()
        {
            RecordingStatusText.Text = e.Message;
            if (e.Result is not null)
            {
                RecordingPathBox.Text = e.Result.OutputPath;
                RecordingStatsText.Text = $"时长 {e.Result.Duration:hh\\:mm\\:ss} · 视频帧 {e.Result.VideoFrames} · 音频 {e.Result.AudioBytes / 1024d:0.0} KB";
            }
            UpdateRecordingControls();
            if (e.State is RecordingState.Completed or RecordingState.Failed)
            {
                _recordingTimer.Stop();
            }
        }

        if (Dispatcher.CheckAccess()) Apply();
        else Dispatcher.BeginInvoke(DispatcherPriority.DataBind, new Action(Apply));
    }

    private void RecordingService_LevelChanged(object? sender, MicrophoneLevelEventArgs e)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(DispatcherPriority.DataBind, new Action(() => RecordingService_LevelChanged(sender, e)));
            return;
        }

        MicrophoneLevelBar.Value = e.Level;
        MicrophoneStatusText.Text = $"录制中 · 峰值 {(int)(e.Level * 100)}%";
    }

    private void RecordingTimer_Tick(object? sender, EventArgs e)
    {
        if (!_recordingService.IsActive)
        {
            return;
        }

        RecordingStatsText.Text = $"时长 {_recordingService.Elapsed:hh\\:mm\\:ss} · 视频帧 {_recordingService.VideoFrames} · 音频 {_recordingService.AudioBytes / 1024d:0.0} KB";
    }

    private void UpdateRecordingControls()
    {
        var active = _recordingService.IsActive;
        var paused = _recordingService.State == RecordingState.Paused;
        StartRecordingButton.IsEnabled = !active;
        PauseRecordingButton.IsEnabled = active && _recordingService.State is RecordingState.Recording or RecordingState.Paused;
        StopRecordingButton.IsEnabled = active;
        PauseRecordingButton.Content = paused ? "继续" : "暂停";
        IncludeMicrophoneCheckBox.IsEnabled = !active;
        MicrophoneComboBox.IsEnabled = IncludeMicrophoneCheckBox.IsChecked == true && !active;
        TestMicrophoneButton.IsEnabled = !active;
    }

    private static string GetDefaultRecordingPath() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        "Downloads", "HAM点名助手录屏", $"点名现场_{DateTime.Now:yyyyMMdd_HHmmss}.mp4");

    public void Dispose()
    {
        StopMicrophoneTest();
        _recordingTimer.Stop();
        _recordingService.StateChanged -= RecordingService_StateChanged;
        _recordingService.LevelChanged -= RecordingService_LevelChanged;
        _recordingService.Dispose();
        GC.SuppressFinalize(this);
    }

    private void ViewModel_ParseUpdated(object? sender, EventArgs e)
    {
        // Parsing runs for every keystroke.  Animating this strip used to
        // repaint/fade the live input feedback on every TextChanged event and
        // made the editor feel delayed.  The preview is now a stable binding;
        // only page transitions and successful saves get a subtle transition.
    }

    private void ViewModel_SubmissionSucceeded(object? sender, EventArgs e)
    {
        if (!ShouldAnimate()) return;
        SuccessFlash.BeginAnimation(OpacityProperty, new DoubleAnimation
        {
            From = 0.16, To = 0, Duration = TimeSpan.FromMilliseconds(110),
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }
        });
    }

    private void ViewModel_QuickWindowRequested(object? sender, EventArgs e) => ToggleQuickWindow();

    private void RecordsGrid_PreviewMouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (_viewModel is null || !_viewModel.IsSessionWritable || sender is not DataGrid grid)
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
        if (_viewModel is null || !_viewModel.IsSessionWritable || sender is not DataGrid grid || grid.SelectedItem is not CheckinEntry row)
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

    private void OpenSponsor_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo(NativeVersion.SponsorUrl) { UseShellExecute = true });
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"无法打开赞助页面：{exception.Message}",
                "赞助开发",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
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
        var translate = new TranslateTransform(4, 0);
        page.RenderTransform = translate; page.Opacity = 0;
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        page.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(90)) { EasingFunction = ease });
        translate.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(4, 0, TimeSpan.FromMilliseconds(95)) { EasingFunction = ease });
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
