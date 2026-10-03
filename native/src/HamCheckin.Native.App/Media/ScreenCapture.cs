using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using FormsScreen = System.Windows.Forms.Screen;

namespace HamCheckin.Native.App.Media;

internal static class ScreenCapture
{
    public static IReadOnlyList<ScreenDevice> EnumerateScreens()
    {
        var screens = FormsScreen.AllScreens;
        return screens.Select((screen, index) => new ScreenDevice(
                index,
                string.IsNullOrWhiteSpace(screen.DeviceName) ? $"显示器 {index + 1}" : screen.DeviceName,
                screen.Bounds.Left,
                screen.Bounds.Top,
                screen.Bounds.Width,
                screen.Bounds.Height,
                screen.Primary))
            .ToArray();
    }

    public static byte[] CaptureJpeg(ScreenDevice device, int quality)
    {
        var screens = FormsScreen.AllScreens;
        if (device.Index < 0 || device.Index >= screens.Length)
        {
            throw new InvalidOperationException("录制目标显示器已断开或显示器列表已变化，请刷新后重试。");
        }

        var bounds = screens[device.Index].Bounds;
        using var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.CompositingMode = CompositingMode.SourceCopy;
            graphics.CopyFromScreen(
                bounds.Left,
                bounds.Top,
                0,
                0,
                new Size(bounds.Width, bounds.Height),
                CopyPixelOperation.SourceCopy);
        }

        using var stream = new MemoryStream();
        var codec = ImageCodecInfo.GetImageEncoders()
            .FirstOrDefault(item => item.FormatID == ImageFormat.Jpeg.Guid)
            ?? throw new InvalidOperationException("Windows JPEG 编码器不可用，无法生成录屏帧。");
        using var parameters = new EncoderParameters(1);
        parameters.Param[0] = new EncoderParameter(
            System.Drawing.Imaging.Encoder.Quality,
            Math.Clamp(quality, 40, 95));
        bitmap.Save(stream, codec, parameters);
        return stream.ToArray();
    }
}
