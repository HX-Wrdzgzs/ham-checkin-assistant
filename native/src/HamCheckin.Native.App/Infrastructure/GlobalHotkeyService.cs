using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Input;

namespace HamCheckin.Native.App.Infrastructure;

/// <summary>
/// 只负责默认的全局快速小窗热键。注册失败时不吞掉错误，调用方会把状态
/// 写入设置页；软件内快捷键仍然继续工作。
/// </summary>
internal sealed class GlobalHotkeyService : IDisposable
{
    private const int WmHotkey = 0x0312;
    private const int HotkeyId = 0x48414D;
    private HwndSource? _source;
    private IntPtr _handle;
    private Action? _onPressed;

    public bool TryRegister(Window window, ModifierKeys modifiers, Key key, Action onPressed)
    {
        Unregister();
        _handle = new WindowInteropHelper(window).Handle;
        if (_handle == IntPtr.Zero)
        {
            return false;
        }

        _source = HwndSource.FromHwnd(_handle);
        if (_source is null)
        {
            _handle = IntPtr.Zero;
            return false;
        }

        _source?.AddHook(WndProc);
        _onPressed = onPressed;
        var nativeModifiers = ToNativeModifiers(modifiers);
        var virtualKey = (uint)KeyInterop.VirtualKeyFromKey(key);
        if (!RegisterHotKey(_handle, HotkeyId, nativeModifiers, virtualKey))
        {
            _source?.RemoveHook(WndProc);
            _source = null;
            _onPressed = null;
            return false;
        }
        return true;
    }

    private IntPtr WndProc(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (message == WmHotkey && wParam.ToInt32() == HotkeyId)
        {
            _onPressed?.Invoke();
            handled = true;
        }
        return IntPtr.Zero;
    }

    public void Unregister()
    {
        if (_handle != IntPtr.Zero)
        {
            _ = UnregisterHotKey(_handle, HotkeyId);
        }
        _source?.RemoveHook(WndProc);
        _source = null;
        _onPressed = null;
        _handle = IntPtr.Zero;
    }

    public void Dispose() => Unregister();

    private static uint ToNativeModifiers(ModifierKeys modifiers)
    {
        var result = 0u;
        if (modifiers.HasFlag(ModifierKeys.Alt)) result |= 0x0001;
        if (modifiers.HasFlag(ModifierKeys.Control)) result |= 0x0002;
        if (modifiers.HasFlag(ModifierKeys.Shift)) result |= 0x0004;
        if (modifiers.HasFlag(ModifierKeys.Windows)) result |= 0x0008;
        return result;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
}
