using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace HamCheckin.Native.App.Media;

/// <summary>
/// Captures the WPF application's client area. The target is the application
/// window handle, never a monitor, so other desktop windows are not selected.
/// </summary>
internal static class ScreenCapture
{
    private const uint PrintWindowRenderFullContent = 0x00000002;

    public static RecordingTarget CreateTarget(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        var handle = new WindowInteropHelper(window).Handle;
        if (handle == nint.Zero)
        {
            throw new InvalidOperationException("HAM 点名助手窗口尚未创建，暂时不能开始录屏。");
        }

        if (!GetClientRect(handle, out var clientRect))
        {
            throw new InvalidOperationException("无法读取 HAM 点名助手窗口尺寸。");
        }

        var width = MakeEven(clientRect.Right - clientRect.Left);
        var height = MakeEven(clientRect.Bottom - clientRect.Top);
        if (width < 2 || height < 2)
        {
            throw new InvalidOperationException("HAM 点名助手窗口尺寸太小，无法开始录屏。");
        }

        return new RecordingTarget(handle, "HAM 点名助手窗口", width, height);
    }

    /// <summary>Returns BGRX pixels for Media Foundation's RGB32 input type.</summary>
    public static byte[] CaptureFrame(RecordingTarget target)
    {
        if (target.WindowHandle == nint.Zero || !IsWindow(target.WindowHandle))
        {
            throw new InvalidOperationException("HAM 点名助手窗口已关闭，无法继续录屏。");
        }

        using var bitmap = new Bitmap(target.Width, target.Height, PixelFormat.Format32bppRgb);
        using var graphics = Graphics.FromImage(bitmap);
        var deviceContext = graphics.GetHdc();
        try
        {
            var captured = PrintWindow(target.WindowHandle, deviceContext, PrintWindowRenderFullContent);
            if (!captured)
            {
                // Never fall back to a desktop DC: doing so could capture an
                // unrelated window when the HAM window is covered.  A failed
                // PrintWindow is a hard recording error instead.
                throw new InvalidOperationException("Windows 无法只渲染 HAM 点名助手窗口画面。");
            }
        }
        finally
        {
            graphics.ReleaseHdc(deviceContext);
        }

        var rectangle = new Rectangle(0, 0, target.Width, target.Height);
        var data = bitmap.LockBits(rectangle, ImageLockMode.ReadOnly, PixelFormat.Format32bppRgb);
        try
        {
            var stride = Math.Abs(data.Stride);
            var bytes = new byte[stride * target.Height];
            Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
            return bytes;
        }
        finally
        {
            bitmap.UnlockBits(data);
        }
    }

    private static int MakeEven(int value) => Math.Max(2, value & ~1);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetClientRect(nint hWnd, out Rect rect);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool IsWindow(nint hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PrintWindow(nint hWnd, nint hdcBlt, uint flags);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

}
