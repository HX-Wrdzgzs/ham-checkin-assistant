using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace HamCheckin.Native.App.Infrastructure;

internal static class WindowsBackdrop
{
    private const int ImmersiveDarkMode = 20;
    private const int WindowCornerPreference = 33;
    private const int SystemBackdropType = 38;

    public static void Apply(Window window)
    {
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000))
        {
            return;
        }

        try
        {
            var handle = new WindowInteropHelper(window).Handle;
            var dark = 0;
            var rounded = 2;
            var mica = 2;
            _ = DwmSetWindowAttribute(handle, ImmersiveDarkMode, ref dark, sizeof(int));
            _ = DwmSetWindowAttribute(handle, WindowCornerPreference, ref rounded, sizeof(int));
            _ = DwmSetWindowAttribute(handle, SystemBackdropType, ref mica, sizeof(int));
        }
        catch (DllNotFoundException)
        {
            // Older or stripped Windows editions simply keep the normal WPF background.
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
