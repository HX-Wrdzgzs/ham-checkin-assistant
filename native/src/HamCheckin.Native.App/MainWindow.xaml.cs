using System.Windows;
using System.Windows.Input;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.ViewModels;

namespace HamCheckin.Native.App;

public partial class MainWindow : Window, IDisposable
{
    private readonly GlobalHotkeyService _globalHotkey = new();
    private MainViewModel? _viewModel;
    private bool _sourceReady;

    public MainWindow()
    {
        InitializeComponent();
        DataContextChanged += MainWindow_DataContextChanged;
        SourceInitialized += (_, _) => WindowsBackdrop.Apply(this);
        SourceInitialized += MainWindow_SourceInitialized;
        Closed += (_, _) =>
        {
            ContentView.Dispose();
            _globalHotkey.Dispose();
        };
    }

    public void Dispose()
    {
        ContentView.Dispose();
        _globalHotkey.Dispose();
        GC.SuppressFinalize(this);
    }

    private void MainWindow_SourceInitialized(object? sender, EventArgs e)
    {
        _sourceReady = true;
        RegisterConfiguredGlobalHotkey();
    }

    private void MainWindow_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.ShortcutsChanged -= ViewModel_ShortcutsChanged;
        }
        _viewModel = e.NewValue as MainViewModel;
        if (_viewModel is not null)
        {
            _viewModel.ShortcutsChanged += ViewModel_ShortcutsChanged;
            if (_sourceReady)
            {
                RegisterConfiguredGlobalHotkey();
            }
        }
    }

    private void ViewModel_ShortcutsChanged(object? sender, ShortcutChangedEventArgs e)
    {
        if (e.ActionKey != "*" && e.ActionKey != "quick-window")
        {
            return;
        }

        if (RegisterConfiguredGlobalHotkey())
        {
            _viewModel?.SetShortcutStatus($"全局小窗热键已生效：{_viewModel.GetShortcut("quick-window")?.Gesture}");
            return;
        }

        if (!string.IsNullOrWhiteSpace(e.PreviousGesture))
        {
            _viewModel?.RestoreShortcut("quick-window", e.PreviousGesture);
            RegisterConfiguredGlobalHotkey();
            _viewModel?.SetShortcutStatus($"全局热键注册失败，已恢复：{e.PreviousGesture}");
        }
    }

    private bool RegisterConfiguredGlobalHotkey()
    {
        if (_viewModel is null)
        {
            return false;
        }

        var gesture = _viewModel.GetShortcut("quick-window")?.Gesture;
        if (gesture is null || !ShortcutGesture.TryParse(gesture, out var modifiers, out var key))
        {
            _globalHotkey.Unregister();
            _viewModel.SetShortcutStatus("全局小窗热键格式无效；软件内快捷键仍可用");
            return false;
        }

        var registered = _globalHotkey.TryRegister(this, modifiers, key,
            ContentView.ToggleQuickWindowFromHotkey);
        if (!registered)
        {
            _viewModel.SetShortcutStatus($"{gesture} 无法注册为全局热键；软件内快捷键仍可用");
        }
        return registered;
    }
}
