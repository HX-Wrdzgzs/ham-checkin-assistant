using System.Diagnostics.CodeAnalysis;
using System.IO;
using System.Threading;
using System.Windows;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.App.Views;

namespace HamCheckin.Native.App;

[SuppressMessage("Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "WPF Application releases the mutex and async view model from OnExit.")]
public partial class App : Application
{
    private Mutex? _singleInstance;
    private MainViewModel? _viewModel;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
            ConfigureTestOptions(e.Args);
        }
        catch (Exception exception) when (exception is ArgumentException or FormatException or OverflowException)
        {
            MessageBox.Show(exception.Message, "HAM 点名助手",
                MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(2);
            return;
        }

        var dataRootIndex = Array.FindIndex(e.Args,
            static argument => string.Equals(argument, "--data-root", StringComparison.OrdinalIgnoreCase));
        if (dataRootIndex >= 0)
        {
            if (dataRootIndex + 1 >= e.Args.Length || string.IsNullOrWhiteSpace(e.Args[dataRootIndex + 1]))
            {
                MessageBox.Show("--data-root 后必须提供隔离数据目录。", "HAM 点名助手",
                    MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown(2);
                return;
            }

            try
            {
                AppPaths.ConfigureDataRoot(e.Args[dataRootIndex + 1]);
            }
            catch (Exception exception) when (exception is ArgumentException or NotSupportedException)
            {
                MessageBox.Show($"隔离数据目录无效：{exception.Message}", "HAM 点名助手",
                    MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown(2);
                return;
            }
        }

        var setIndex = Array.FindIndex(e.Args,
            static argument => string.Equals(argument, "--render-ui-set", StringComparison.OrdinalIgnoreCase));
        if (setIndex >= 0)
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var outputDirectory = setIndex + 1 < e.Args.Length
                ? Path.GetFullPath(e.Args[setIndex + 1])
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "HAM点名助手-UI效果图");
            PreviewRenderer.RenderSet(outputDirectory);
            Shutdown(0);
            return;
        }

        var previewIndex = Array.FindIndex(e.Args,
            static argument => string.Equals(argument, "--render-ui", StringComparison.OrdinalIgnoreCase)
                || string.Equals(argument, "--render-preview", StringComparison.OrdinalIgnoreCase));
        if (previewIndex >= 0)
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var output = previewIndex + 1 < e.Args.Length
                ? Path.GetFullPath(e.Args[previewIndex + 1])
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "HAM点名助手-UI效果图", "01-快速点名-1440x900.png");
            var width = previewIndex + 2 < e.Args.Length
                && int.TryParse(e.Args[previewIndex + 2], out var parsedWidth)
                ? Math.Clamp(parsedWidth, 420, 3840)
                : 1440;
            var height = previewIndex + 3 < e.Args.Length
                && int.TryParse(e.Args[previewIndex + 3], out var parsedHeight)
                ? Math.Clamp(parsedHeight, 190, 2160)
                : 900;
            PreviewRenderer.Render(output, width, height);
            Shutdown(0);
            return;
        }

        _singleInstance = new Mutex(true, "Local\\HAMCheckinAssistant_Native", out var created);
        if (!created)
        {
            MessageBox.Show("HAM 点名助手已经在运行。", "HAM 点名助手",
                MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown(0);
            return;
        }

        _viewModel = new MainViewModel();
        var window = new MainWindow { DataContext = _viewModel };
        MainWindow = window;
        window.Show();
        try
        {
            await _viewModel.InitializeAsync();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"原生版初始化失败，未修改旧版数据。\n\n{exception.Message}",
                "HAM 点名助手", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        _singleInstance?.ReleaseMutex();
        _singleInstance?.Dispose();
        base.OnExit(e);
    }

    private static void ConfigureTestOptions(string[] args)
    {
        var fixedNow = ReadOptionalDateTimeOffset(args, "--test-clock");
        var delay = ReadOptionalInt(args, "--test-store-delay", 0, 60_000);
        var disableNetwork = args.Any(static argument =>
            string.Equals(argument, "--disable-network", StringComparison.OrdinalIgnoreCase));
        RuntimeOptions.Configure(fixedNow, delay, disableNetwork);
    }

    private static DateTimeOffset? ReadOptionalDateTimeOffset(string[] args, string option)
    {
        var index = Array.FindIndex(args,
            argument => string.Equals(argument, option, StringComparison.OrdinalIgnoreCase));
        if (index < 0)
        {
            return null;
        }

        if (index + 1 >= args.Length ||
            !DateTimeOffset.TryParse(args[index + 1], out var parsed))
        {
            throw new FormatException($"{option} 后必须是有效的日期时间，例如 2026-09-26T21:00:00+08:00。");
        }

        return parsed;
    }

    private static int ReadOptionalInt(string[] args, string option, int minimum, int maximum)
    {
        var index = Array.FindIndex(args,
            argument => string.Equals(argument, option, StringComparison.OrdinalIgnoreCase));
        if (index < 0)
        {
            return 0;
        }

        if (index + 1 >= args.Length || !int.TryParse(args[index + 1], out var parsed) ||
            parsed < minimum || parsed > maximum)
        {
            throw new ArgumentOutOfRangeException(
                option,
                $"{option} 后必须是 {minimum} 到 {maximum} 之间的整数。");
        }

        return parsed;
    }
}
