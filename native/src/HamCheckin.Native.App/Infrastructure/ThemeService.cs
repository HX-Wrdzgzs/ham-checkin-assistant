using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Security;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using Microsoft.Win32;

namespace HamCheckin.Native.App.Infrastructure;

public enum ThemePreference
{
    FollowSystem,
    Light,
    Dark
}

public enum EffectiveTheme
{
    Light,
    Dark,
    HighContrast
}

public sealed class ThemeService : IDisposable
{
    private const string PersonalizeKey = @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";
    private Application? _application;
    private ResourceDictionary? _themeDictionary;
    private bool _initialized;
    private bool _appsUseLightTheme = true;

    public ThemePreference Preference { get; private set; } = ThemePreference.FollowSystem;
    public EffectiveTheme CurrentTheme { get; private set; } = EffectiveTheme.Light;

    public void Initialize()
    {
        if (_initialized)
        {
            return;
        }

        _application = Application.Current
            ?? throw new InvalidOperationException("WPF application must be created before initializing themes.");
        Preference = AppSettingsStore.LoadThemePreference();
        _appsUseLightTheme = ReadAppsUseLightTheme(fallback: true);
        _initialized = true;

        try
        {
            SystemEvents.UserPreferenceChanged += SystemEvents_UserPreferenceChanged;
            SystemParameters.StaticPropertyChanged += SystemParameters_StaticPropertyChanged;
            ApplyEffectiveTheme(Resolve(Preference, _appsUseLightTheme, SystemParameters.HighContrast));
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    public bool TrySetPreference(ThemePreference preference, out string? error)
    {
        error = null;
        if (!_initialized)
        {
            error = "主题服务尚未初始化。";
            return false;
        }

        if (!Enum.IsDefined(typeof(ThemePreference), preference))
        {
            error = "主题选项无效。";
            return false;
        }

        if (!AppSettingsStore.TrySaveThemePreference(preference, out error))
        {
            return false;
        }

        Preference = preference;
        ApplyEffectiveTheme(Resolve(Preference, _appsUseLightTheme, SystemParameters.HighContrast));
        return true;
    }

    public EffectiveTheme Resolve(
        ThemePreference preference,
        bool appsUseLightTheme,
        bool highContrast)
    {
        if (highContrast)
        {
            return EffectiveTheme.HighContrast;
        }

        return preference switch
        {
            ThemePreference.Light => EffectiveTheme.Light,
            ThemePreference.Dark => EffectiveTheme.Dark,
            _ => appsUseLightTheme ? EffectiveTheme.Light : EffectiveTheme.Dark
        };
    }

    internal void ApplyEffectiveTheme(EffectiveTheme theme)
    {
        var application = _application ??= Application.Current
            ?? throw new InvalidOperationException("WPF application must be created before applying themes.");
        var nextDictionary = CreateThemeDictionary(theme);
        if (_themeDictionary is null)
        {
            application.Resources.MergedDictionaries.Insert(0, nextDictionary);
        }
        else
        {
            var index = application.Resources.MergedDictionaries.IndexOf(_themeDictionary);
            if (index >= 0)
            {
                application.Resources.MergedDictionaries[index] = nextDictionary;
            }
            else
            {
                application.Resources.MergedDictionaries.Insert(0, nextDictionary);
            }
        }

        _themeDictionary = nextDictionary;
        CurrentTheme = theme;
        foreach (Window window in application.Windows)
        {
            if (window.IsLoaded)
            {
                WindowsBackdrop.Apply(window, theme);
            }
        }
    }

    internal static ResourceDictionary CreateThemeDictionary(EffectiveTheme theme)
    {
        var resources = new ResourceDictionary();
        void Add(string key, Brush value) => resources.Add(key, value);

        if (theme == EffectiveTheme.HighContrast)
        {
            var window = SystemColors.WindowBrush;
            var windowText = SystemColors.WindowTextBrush;
            var control = SystemColors.ControlBrush;
            var controlText = SystemColors.ControlTextBrush;
            var highlight = SystemColors.HighlightBrush;
            var highlightText = SystemColors.HighlightTextBrush;
            var grayText = SystemColors.GrayTextBrush;

            Add("AppBackgroundBrush", window);
            Add("SurfaceBrush", window);
            Add("SurfaceAltBrush", window);
            Add("FieldBackgroundBrush", window);
            Add("SidebarBrush", window);
            Add("HeaderBrush", window);
            Add("BorderBrush", windowText);
            Add("TextBrush", windowText);
            Add("MutedBrush", windowText);
            Add("AccentBrush", highlight);
            Add("AccentSoftBrush", highlight);
            Add("AccentTextBrush", highlightText);
            Add("SuccessBrush", windowText);
            Add("SuccessSoftBrush", window);
            Add("WarningSoftBrush", window);
            Add("WarningTextBrush", windowText);
            Add("ErrorBrush", windowText);
            Add("FocusBrush", highlight);
            Add("SelectionBrush", highlight);
            Add("SelectionTextBrush", highlightText);
            Add("TableGridBrush", windowText);
            Add("TableHeaderBrush", control);
            Add("ButtonHoverBrush", highlight);
            Add("ButtonPressedBrush", highlight);
            Add("DisabledTextBrush", grayText);
            Add("DisabledBackgroundBrush", control);
            Add("EmptyBrush", windowText);
            SetSystemColorResources(resources, window, windowText, control, controlText, highlight, highlightText, grayText);
            return resources;
        }

        var light = theme == EffectiveTheme.Light;
        var appBackground = light ? CreateBrush(245, 247, 250) : CreateBrush(18, 25, 34);
        var surface = light ? CreateBrush(255, 255, 255) : CreateBrush(27, 36, 48);
        var surfaceAlt = light ? CreateBrush(247, 249, 252) : CreateBrush(34, 45, 58);
        var text = light ? CreateBrush(25, 37, 53) : CreateBrush(232, 238, 246);
        var muted = light ? CreateBrush(84, 100, 119) : CreateBrush(164, 178, 195);
        var accent = light ? CreateBrush(23, 105, 224) : CreateBrush(126, 176, 255);
        var accentText = light ? CreateBrush(255, 255, 255) : CreateBrush(15, 31, 50);
        var accentSoft = light ? CreateBrush(232, 241, 255) : CreateBrush(38, 59, 83);
        var success = light ? CreateBrush(13, 126, 87) : CreateBrush(112, 214, 173);
        var successSoft = light ? CreateBrush(232, 247, 240) : CreateBrush(31, 59, 48);
        var warningSoft = light ? CreateBrush(255, 247, 224) : CreateBrush(67, 54, 27);
        var warningText = light ? CreateBrush(125, 77, 0) : CreateBrush(255, 226, 158);
        var error = light ? CreateBrush(172, 42, 54) : CreateBrush(255, 143, 153);
        var border = light ? CreateBrush(215, 224, 235) : CreateBrush(54, 68, 84);
        var focus = light ? CreateBrush(22, 93, 206) : CreateBrush(156, 195, 255);
        var selection = light ? CreateBrush(218, 233, 255) : CreateBrush(48, 68, 94);
        var selectionText = light ? CreateBrush(25, 43, 67) : CreateBrush(242, 247, 253);
        var tableGrid = light ? CreateBrush(231, 236, 243) : CreateBrush(46, 58, 73);
        var tableHeader = light ? CreateBrush(244, 247, 251) : CreateBrush(32, 43, 57);
        var buttonHover = light ? CreateBrush(239, 243, 249) : CreateBrush(39, 53, 69);
        var buttonPressed = light ? CreateBrush(225, 233, 243) : CreateBrush(50, 66, 84);
        var disabledText = light ? CreateBrush(102, 116, 133) : CreateBrush(142, 153, 167);
        var disabledBackground = light ? CreateBrush(241, 244, 248) : CreateBrush(38, 47, 59);

        Add("AppBackgroundBrush", appBackground);
        Add("SurfaceBrush", surface);
        Add("SurfaceAltBrush", surfaceAlt);
        Add("FieldBackgroundBrush", surface);
        Add("SidebarBrush", surface);
        Add("HeaderBrush", surface);
        Add("BorderBrush", border);
        Add("TextBrush", text);
        Add("MutedBrush", muted);
        Add("AccentBrush", accent);
        Add("AccentSoftBrush", accentSoft);
        Add("AccentTextBrush", accentText);
        Add("SuccessBrush", success);
        Add("SuccessSoftBrush", successSoft);
        Add("WarningSoftBrush", warningSoft);
        Add("WarningTextBrush", warningText);
        Add("ErrorBrush", error);
        Add("FocusBrush", focus);
        Add("SelectionBrush", selection);
        Add("SelectionTextBrush", selectionText);
        Add("TableGridBrush", tableGrid);
        Add("TableHeaderBrush", tableHeader);
        Add("ButtonHoverBrush", buttonHover);
        Add("ButtonPressedBrush", buttonPressed);
        Add("DisabledTextBrush", disabledText);
        Add("DisabledBackgroundBrush", disabledBackground);
        Add("EmptyBrush", muted);
        SetSystemColorResources(resources, surface, text, surface, text, selection, selectionText, disabledText);
        return resources;
    }

    public void Dispose()
    {
        if (_initialized)
        {
            SystemEvents.UserPreferenceChanged -= SystemEvents_UserPreferenceChanged;
            SystemParameters.StaticPropertyChanged -= SystemParameters_StaticPropertyChanged;
        }
        _initialized = false;

        if (_application is not null && _themeDictionary is not null)
        {
            var index = _application.Resources.MergedDictionaries.IndexOf(_themeDictionary);
            if (index >= 0)
            {
                _application.Resources.MergedDictionaries.RemoveAt(index);
            }
        }

        _themeDictionary = null;
        _application = null;
        GC.SuppressFinalize(this);
    }

    private void SystemEvents_UserPreferenceChanged(object? sender, UserPreferenceChangedEventArgs e)
    {
        // A generic notification is only a refresh opportunity; no registry-key mapping is assumed.
        QueueSystemRefresh();
    }

    private void SystemParameters_StaticPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (string.IsNullOrEmpty(e.PropertyName)
            || string.Equals(e.PropertyName, nameof(SystemParameters.HighContrast), StringComparison.Ordinal))
        {
            QueueSystemRefresh();
        }
    }

    private void QueueSystemRefresh()
    {
        var dispatcher = _application?.Dispatcher;
        if (!_initialized || dispatcher is null || dispatcher.HasShutdownStarted || dispatcher.HasShutdownFinished)
        {
            return;
        }

        if (dispatcher.CheckAccess())
        {
            RefreshFromSystem();
        }
        else
        {
            _ = dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(RefreshFromSystem));
        }
    }

    private void RefreshFromSystem()
    {
        if (!_initialized)
        {
            return;
        }

        if (Preference == ThemePreference.FollowSystem)
        {
            _appsUseLightTheme = ReadAppsUseLightTheme(_appsUseLightTheme);
        }

        ApplyEffectiveTheme(Resolve(Preference, _appsUseLightTheme, SystemParameters.HighContrast));
    }

    private static bool ReadAppsUseLightTheme(bool fallback)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(PersonalizeKey, writable: false);
            return key?.GetValue("AppsUseLightTheme") switch
            {
                int value => value != 0,
                long value => value != 0,
                _ => fallback
            };
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException
            or SecurityException)
        {
            Trace.TraceWarning("Unable to read the Windows app theme preference: {0}", exception.Message);
            return fallback;
        }
    }

    private static void SetSystemColorResources(
        ResourceDictionary resources,
        Brush window,
        Brush windowText,
        Brush control,
        Brush controlText,
        Brush highlight,
        Brush highlightText,
        Brush grayText)
    {
        resources[SystemColors.WindowBrushKey] = window;
        resources[SystemColors.WindowTextBrushKey] = windowText;
        resources[SystemColors.ControlBrushKey] = control;
        resources[SystemColors.ControlTextBrushKey] = controlText;
        resources[SystemColors.HighlightBrushKey] = highlight;
        resources[SystemColors.HighlightTextBrushKey] = highlightText;
        resources[SystemColors.GrayTextBrushKey] = grayText;
        resources[SystemColors.MenuBrushKey] = window;
        resources[SystemColors.MenuTextBrushKey] = windowText;
        resources[SystemColors.InfoBrushKey] = window;
        resources[SystemColors.InfoTextBrushKey] = windowText;
    }

    private static SolidColorBrush CreateBrush(byte red, byte green, byte blue)
    {
        var brush = new SolidColorBrush(Color.FromRgb(red, green, blue));
        brush.Freeze();
        return brush;
    }
}
