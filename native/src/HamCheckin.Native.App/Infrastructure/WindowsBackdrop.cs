using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace HamCheckin.Native.App.Infrastructure;

internal static class WindowsBackdrop
{
    private const int ImmersiveDarkMode = 20;
    private const int WindowCornerPreference = 33;
    private const int SystemBackdropType = 38;
    private const int SystemBackdropNone = 1;
    private const int SystemBackdropMainWindow = 2;

    public static void Apply(Window window)
    {
        var theme = Application.Current is HamCheckin.Native.App.App app
            ? app.Themes?.CurrentTheme ?? EffectiveTheme.Light
            : EffectiveTheme.Light;
        Apply(window, theme);
    }

    public static void Apply(Window window, EffectiveTheme theme)
    {
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000))
        {
            return;
        }

        try
        {
            var handle = new WindowInteropHelper(window).Handle;
            if (handle == IntPtr.Zero)
            {
                return;
            }

            var dark = theme == EffectiveTheme.Dark ? 1 : 0;
            _ = DwmSetWindowAttribute(handle, ImmersiveDarkMode, ref dark, sizeof(int));

            var rounded = 2;
            var backdrop = theme == EffectiveTheme.HighContrast
                ? SystemBackdropNone
                : SystemBackdropMainWindow;
            _ = DwmSetWindowAttribute(handle, WindowCornerPreference, ref rounded, sizeof(int));
            _ = DwmSetWindowAttribute(handle, SystemBackdropType, ref backdrop, sizeof(int));
        }
        catch (DllNotFoundException)
        {
            // Older or stripped Windows editions keep the normal WPF background.
        }
        catch (EntryPointNotFoundException)
        {
        }
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(
        IntPtr hwnd,
        int attribute,
        ref int value,
        int valueSize);
}
