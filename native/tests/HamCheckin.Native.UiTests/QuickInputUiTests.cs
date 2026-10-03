using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using System.IO;
using System.Text;
using NativeApplication = HamCheckin.Native.App.App;
using HamCheckin.Native.App.Media;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.App.Views;
using Xunit;

namespace HamCheckin.Native.UiTests;

public sealed class QuickInputUiTests : IClassFixture<WpfDispatcherFixture>
{
    private const string Original = "BA4RLL QYT6900 5W YZ YZ";
    private readonly WpfDispatcherFixture _fixture;

    public QuickInputUiTests(WpfDispatcherFixture fixture) => _fixture = fixture;

    [Fact]
    public void MainTextBoxKeepsSuffixWhenEditingFrontAndMiddle()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var window = new Window
            {
                Width = 1440,
                Height = 900,
                Content = new MainView { DataContext = viewModel },
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.UpdateLayout();

            var input = (TextBox)((MainView)window.Content).FindName("InputBox")!;
            Assert.Equal(Original, input.Text);

            input.Focus();
            input.Select(0, "BA4RLL".Length);
            input.SelectedText = "BA4VXR";
            Assert.Equal("BA4VXR QYT6900 5W YZ YZ", input.Text);
            Assert.Equal(input.Text, viewModel.InputText);

            input.Select("BA4VXR ".Length, "QYT6900".Length);
            input.SelectedText = "PD780";
            Assert.Equal("BA4VXR PD780 5W YZ YZ", input.Text);
            Assert.Equal(input.Text, viewModel.InputText);
            Assert.Equal("BA4VXR PD780 5W YZ YZ", viewModel.InputDraft.Text);

            window.Close();
        });
    }

    [Fact]
    public void MainAndQuickWindowMirrorWithoutReplacingActiveText()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var main = new Window
            {
                Width = 1100,
                Height = 700,
                Content = new MainView { DataContext = viewModel },
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            main.Show();
            main.UpdateLayout();

            var quick = new QuickWindow
            {
                Width = 560,
                Height = 280,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                DataContext = viewModel
            };
            quick.Show();
            quick.UpdateLayout();

            var mainInput = (TextBox)((MainView)main.Content).FindName("InputBox")!;
            var quickInput = (TextBox)quick.FindName("QuickInputBox")!;
            mainInput.Focus();
            mainInput.Select(0, "BA4RLL".Length);
            mainInput.SelectedText = "BA4VXR";
            Assert.Equal("BA4VXR QYT6900 5W YZ YZ", mainInput.Text);
            Assert.Equal(mainInput.Text, quickInput.Text);

            quickInput.Focus();
            quickInput.Select("BA4VXR ".Length, "QYT6900".Length);
            quickInput.SelectedText = "PD780";
            Assert.Equal("BA4VXR PD780 5W YZ YZ", quickInput.Text);
            Assert.Equal(quickInput.Text, mainInput.Text);
            Assert.Equal(quickInput.Text, viewModel.InputText);

            quick.Close();
            main.Close();
        });
    }

    [Fact]
    public void VideoInputsKeepTheirSuffixWhenTheModelIsEditedInPlace()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var window = new Window
            {
                Width = 1100,
                Height = 700,
                Content = new MainView { DataContext = viewModel },
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.UpdateLayout();

            var input = (TextBox)((MainView)window.Content).FindName("InputBox")!;
            viewModel.SetInputText("bd4wye shks8600 4单元八木 秦淮区大光路 5w");
            Assert.Equal("bd4wye shks8600 4单元八木 秦淮区大光路 5w", input.Text);
            input.Focus();
            input.Select("bd4wye ".Length, "shks8600".Length);
            input.SelectedText = "森海克斯 8600";
            Assert.Equal(
                "bd4wye 森海克斯 8600 4单元八木 秦淮区大光路 5w",
                input.Text);

            viewModel.SetInputText("ba4szj mtm8268 5w 车载苗子");
            Assert.Equal("ba4szj mtm8268 5w 车载苗子", input.Text);
            input.Focus();
            input.Select("ba4szj ".Length, "mtm8268".Length);
            input.SelectedText = "m8268";
            Assert.Equal("ba4szj m8268 5w 车载苗子", input.Text);
            Assert.Equal(input.Text, viewModel.InputText);

            window.Close();
        });
    }

    [Fact]
    public void AboutWindowShowsNativeVersionAndUpdateChannel()
    {
        _fixture.Run(() =>
        {
            var window = new AboutWindow
            {
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.SetPreviewState();
            window.UpdateLayout();

            var version = (TextBlock)window.FindName("CurrentVersionText")!;
            var developer = (TextBlock)window.FindName("DeveloperText")!;
            var status = (TextBlock)window.FindName("StatusText")!;
            var check = (Button)window.FindName("CheckButton")!;

            Assert.Equal("1.0.0", version.Text);
            Assert.Equal("开发者：BA4THG（HX-Wrdzgzs）", developer.Text);
            Assert.Contains("当前已是最新", status.Text);
            Assert.True(check.IsEnabled);

            window.Close();
        });
    }

    [Fact]
    public void AboutReleaseNotesAreReadablePlainText()
    {
        var formatted = AboutWindow.FormatReleaseNotes(
            "## What's Changed\n* **修复输入** by [HX-Wrdzgzs](https://github.com/HX-Wrdzgzs)\n\n**Full Changelog**: [v0.9.3...v0.9.4](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/compare/v0.9.3...v0.9.4)");

        Assert.Contains("What's Changed", formatted);
        Assert.Contains("· 修复输入 by HX-Wrdzgzs", formatted);
        Assert.DoesNotContain("##", formatted);
        Assert.DoesNotContain("**", formatted);
        Assert.DoesNotContain("https://", formatted);
    }

    [Fact]
    public void SessionEditorFieldsKeepTextInsideTheirBounds()
    {
        _fixture.Run(() =>
        {
            var window = new SessionEditorWindow(null)
            {
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.UpdateLayout();

            var name = (TextBox)window.FindName("NameBox")!;
            var date = (TextBox)window.FindName("DateBox")!;
            Assert.Equal("第1场点名", name.Text);
            Assert.Matches(@"^\d{4}-\d{2}-\d{2}$", date.Text);
            Assert.Equal(14, name.FontSize);
            Assert.Equal(14, date.FontSize);
            Assert.True(name.ActualHeight >= 38);
            Assert.True(date.ActualHeight >= 38);
            Assert.Equal(VerticalAlignment.Center, name.VerticalContentAlignment);

            window.Close();
        });
    }

    [Fact]
    public void RecordingPageExposesScreenMicrophoneAndControls()
    {
        _fixture.Run(() =>
        {
            var view = new MainView { DataContext = MainViewModel.CreatePreview() };
            var window = new Window
            {
                Width = 1180,
                Height = 760,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };
            window.Show();
            window.UpdateLayout();
            view.ShowPage("Recording");
            view.SetPreviewRecordingData();
            window.UpdateLayout();

            Assert.NotNull(view.FindName("ScreenComboBox"));
            Assert.NotNull(view.FindName("MicrophoneComboBox"));
            Assert.NotNull(view.FindName("TestMicrophoneButton"));
            Assert.NotNull(view.FindName("StartRecordingButton"));
            Assert.Equal("已准备", ((TextBlock)view.FindName("RecordingStatusText")!).Text);
            Assert.Contains("1920×1080", ((TextBlock)view.FindName("RecordingStatsText")!).Text);

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void AviWriterCreatesTwoStreamFormatsAndAnIndex()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "capture.avi");
        try
        {
            using (var writer = new AviFileWriter(path, 320, 240, 10, 44_100))
            {
                writer.WriteVideoFrame(new byte[] { 0xFF, 0xD8, 0xFF, 0xD9 });
                writer.WriteAudio(new byte[8]);
                writer.Complete();
            }

            var bytes = File.ReadAllBytes(path);
            Assert.True(bytes.Length > 200);
            Assert.Equal("RIFF", Encoding.ASCII.GetString(bytes, 0, 4));
            Assert.Equal("AVI ", Encoding.ASCII.GetString(bytes, 8, 4));
            Assert.Equal(2, CountFourCc(bytes, "strf"));
            Assert.Equal(1, CountFourCc(bytes, "idx1"));
            Assert.True(CountFourCc(bytes, "movi") >= 1);
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void MicrophoneEnumerationReturnsAUsableSnapshot()
    {
        var devices = MicrophoneCapture.EnumerateDevices();
        Assert.NotNull(devices);
        Assert.All(devices, device => Assert.False(string.IsNullOrWhiteSpace(device.Name)));
    }

    [Fact]
    public async Task FirstMicrophoneCanOpenAndReturnPcmForDebugging()
    {
        var devices = MicrophoneCapture.EnumerateDevices();
        if (devices.Count == 0)
        {
            throw Xunit.Sdk.SkipException.ForSkip("当前 Windows 会话没有可用麦克风；屏幕录制仍可在关闭麦克风后使用。");
        }

        var bytes = 0;
        using var capture = new MicrophoneCapture(devices[0].Id);
        capture.AudioData += data => Interlocked.Add(ref bytes, data.Length);
        capture.Start();
        await Task.Delay(700);
        capture.Stop();

        Assert.True(bytes > 0, "麦克风已打开但在测试窗口内没有返回 PCM 数据。");
    }

    [Fact]
    public async Task ScreenOnlyRecordingCapturesFramesAndClosesAsAValidAvi()
    {
        var screens = ScreenCapture.EnumerateScreens();
        Assert.NotEmpty(screens);
        var screen = screens[0];
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "screen-only.avi");
        try
        {
            using var service = new ScreenRecordingService();
            service.Start(new RecordingOptions(screen!, path, IncludeMicrophone: false, MicrophoneId: null,
                FramesPerSecond: 5, JpegQuality: 55));
            await Task.Delay(700);
            var result = await service.StopAsync();

            Assert.NotNull(result);
            Assert.True(result!.VideoFrames > 0);
            Assert.True(File.Exists(path));
            var bytes = File.ReadAllBytes(path);
            Assert.Equal("RIFF", Encoding.ASCII.GetString(bytes, 0, 4));
            Assert.True(CountFourCc(bytes, "00dc") >= 1);
            Assert.Equal(1, CountFourCc(bytes, "idx1"));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public async Task ScreenAndMicrophoneRecordingWritesVideoAndPcmStreams()
    {
        var screens = ScreenCapture.EnumerateScreens();
        var microphones = MicrophoneCapture.EnumerateDevices();
        if (screens.Count == 0 || microphones.Count == 0)
        {
            throw Xunit.Sdk.SkipException.ForSkip("当前 Windows 会话缺少显示器或麦克风，未执行双流录制测试。");
        }

        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "screen-and-microphone.avi");
        try
        {
            using var service = new ScreenRecordingService();
            service.Start(new RecordingOptions(screens[0], path, IncludeMicrophone: true,
                MicrophoneId: microphones[0].Id, FramesPerSecond: 5, JpegQuality: 55));
            await Task.Delay(900);
            var result = await service.StopAsync();

            Assert.NotNull(result);
            Assert.True(result!.VideoFrames > 0);
            Assert.True(result.AudioBytes > 0);
            var bytes = File.ReadAllBytes(path);
            Assert.True(CountFourCc(bytes, "00dc") >= 1);
            Assert.True(CountFourCc(bytes, "01wb") >= 1);
            Assert.Equal(1, CountFourCc(bytes, "idx1"));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    private static int CountFourCc(byte[] bytes, string value)
    {
        var needle = Encoding.ASCII.GetBytes(value);
        var count = 0;
        for (var index = 0; index <= bytes.Length - needle.Length; index++)
        {
            if (bytes.AsSpan(index, needle.Length).SequenceEqual(needle)) count++;
        }
        return count;
    }

}

public sealed class WpfDispatcherFixture : IDisposable
{
    private readonly Thread _thread;
    private readonly ManualResetEventSlim _ready = new();
    private Dispatcher? _dispatcher;
    private NativeApplication? _app;

    public WpfDispatcherFixture()
    {
        _thread = new Thread(() =>
        {
            _app = new NativeApplication
            {
                ShutdownMode = ShutdownMode.OnExplicitShutdown
            };
            _app.InitializeComponent();
            _dispatcher = Dispatcher.CurrentDispatcher;
            _ready.Set();
            Dispatcher.Run();
        });
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.Start();
        _ready.Wait();
    }

    public void Run(Action action)
    {
        if (_dispatcher is null)
        {
            throw new InvalidOperationException("WPF Dispatcher 未启动。");
        }
        _dispatcher.Invoke(action);
    }

    public void Dispose()
    {
        if (_dispatcher is not null)
        {
            _dispatcher.Invoke(() =>
            {
                _app?.Shutdown();
                _dispatcher.BeginInvokeShutdown(DispatcherPriority.Normal);
            });
        }
        _thread.Join();
        _ready.Dispose();
    }
}
