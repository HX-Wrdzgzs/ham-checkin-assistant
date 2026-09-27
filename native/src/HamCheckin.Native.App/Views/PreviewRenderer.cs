using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;

namespace HamCheckin.Native.App.Views;

/// <summary>
/// 使用真实 WPF Window/UserControl/TextBox/DataGrid 离屏渲染效果图。
/// 不再创建覆盖 TextBox 的硬编码文字层。
/// </summary>
internal static class PreviewRenderer
{
    public static void RenderSet(string outputDirectory)
    {
        Directory.CreateDirectory(outputDirectory);
        var viewModel = MainViewModel.CreatePreview();
        viewModel.AnimationsEnabled = false;
        RenderMain(Path.Combine(outputDirectory, "01-快速点名-1440x900.png"), viewModel, "Quick", 1440, 900);
        RenderMain(Path.Combine(outputDirectory, "02-快速点名-800x600.png"), viewModel, "Quick", 800, 600);
        RenderQuickWindow(Path.Combine(outputDirectory, "03-独立快速小窗.png"), viewModel);
        RenderFieldEditor(Path.Combine(outputDirectory, "04-QTH字段编辑-未识别修正.png"), viewModel);
        viewModel.CatalogQuery = "pd780";
        viewModel.SearchCatalogCommand.Execute(null);
        RenderMain(Path.Combine(outputDirectory, "05-设备资料库.png"), viewModel, "Catalog", 1180, 720);
        viewModel.CatalogQuery = string.Empty;
        viewModel.SearchCatalogCommand.Execute(null);
        RenderMain(Path.Combine(outputDirectory, "06-地点包省市树.png"), viewModel, "Catalog", 1180, 720);
        RenderMain(Path.Combine(outputDirectory, "07-快捷键设置.png"), viewModel, "Settings", 1180, 760);
        RenderAbout(Path.Combine(outputDirectory, "08-关于-版本-更新.png"));
    }

    public static void Render(string outputPath, int width = 1440, int height = 900)
    {
        var viewModel = MainViewModel.CreatePreview();
        viewModel.AnimationsEnabled = false;
        RenderMain(outputPath, viewModel, "Quick", width, height);
    }

    private static void RenderMain(string outputPath, MainViewModel viewModel,
        string page, int width, int height)
    {
        var view = new MainView { DataContext = viewModel, Width = width, Height = height };
        var host = CreateHost(view, width, height);
        host.Show();
        host.UpdateLayout();
        view.ShowPage(page);
        view.SetPreviewInputText();
        host.UpdateLayout();
        FlushRender(host);
        SaveVisual(outputPath, view, width, height);
        host.Close();
    }

    private static void RenderQuickWindow(string outputPath, MainViewModel viewModel)
    {
        var window = new QuickWindow { DataContext = viewModel, Width = 560, Height = 280 };
        window.Show();
        window.UpdateLayout();
        FlushRender(window);
        SaveWindowContent(outputPath, window, 560, 280);
        // QuickWindow 的真实关闭行为是隐藏，以便保留未提交文字；效果图渲染结束时也使用隐藏，避免 Closing 事件拦截后续渲染。
        window.Hide();
    }

    private static void RenderFieldEditor(string outputPath, MainViewModel viewModel)
    {
        var row = viewModel.Checkins.First(item => item.SequenceNo == 34);
        var request = viewModel.CreateFieldEditRequestAsync(row, FieldKind.Qth).GetAwaiter().GetResult()
            ?? new FieldEditRequest(row.Id, FieldKind.Qth, row.Qth, row.RawInput, "njxw 车苗", row.SessionId, row.SequenceNo, row.Callsign, row.UpdatedAt);
        var window = new FieldEditWindow(viewModel, request) { Width = 720, Height = 620 };
        window.Show();
        window.EditBoxForPreview("njxw");
        window.UpdateLayout();
        FlushRender(window);
        SaveWindowContent(outputPath, window, 720, 620);
        window.Close();
    }

    private static void RenderAbout(string outputPath)
    {
        var window = new AboutWindow { Width = 650, Height = 560 };
        window.Show();
        window.SetPreviewState();
        window.UpdateLayout();
        FlushRender(window);
        SaveWindowContent(outputPath, window, 650, 560);
        window.Close();
    }

    private static Window CreateHost(FrameworkElement content, int width, int height) => new()
    {
        Width = width,
        Height = height,
        WindowStyle = WindowStyle.None,
        ResizeMode = ResizeMode.NoResize,
        ShowInTaskbar = false,
        ShowActivated = false,
        Left = -30000,
        Top = -30000,
        Background = Brushes.White,
        Content = content
    };

    private static void SaveVisual(string outputPath, FrameworkElement visual, int width, int height)
    {
        visual.Measure(new Size(width, height));
        visual.Arrange(new Rect(0, 0, width, height));
        visual.UpdateLayout();
        var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(visual);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        var directory = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        using var stream = File.Create(outputPath);
        encoder.Save(stream);
    }

    private static void SaveWindowContent(string outputPath, Window window, int width, int height)
    {
        if (window.Content is not FrameworkElement content)
        {
            throw new InvalidOperationException("效果图窗口没有可渲染内容。");
        }

        // Window 的 ContentControl 对内容有默认对齐和非客户区，直接把 Window 交给
        // RenderTargetBitmap 会留下黑边。临时用与窗口相同的背景包住真实内容，仍然
        // 渲染原始 WPF 控件，不叠加任何伪造文字层。
        window.Content = null;
        var wrapper = new Grid
        {
            Width = width,
            Height = height,
            Background = (Brush)Application.Current.Resources["AppBackgroundBrush"],
            DataContext = window.DataContext
        };
        wrapper.Children.Add(content);
        SaveVisual(outputPath, wrapper, width, height);
        wrapper.Children.Remove(content);
        window.Content = content;
    }

    private static void FlushRender(DispatcherObject dispatcherObject)
    {
        dispatcherObject.Dispatcher.Invoke(DispatcherPriority.Render, new Action(static () => { }));
        dispatcherObject.Dispatcher.Invoke(DispatcherPriority.ApplicationIdle, new Action(static () => { }));
    }
}
