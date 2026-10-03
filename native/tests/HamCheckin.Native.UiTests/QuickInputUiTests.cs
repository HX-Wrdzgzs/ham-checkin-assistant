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
            viewModel.SetInputText(Original);
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
            viewModel.SetInputText(Original);
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
            var sponsor = (Button)window.FindName("SponsorButton")!;

            Assert.Equal("1.0.2", version.Text);
            Assert.Equal("开发者：BA4THG（HX-Wrdzgzs）", developer.Text);
            Assert.Contains("当前已是最新", status.Text);
            Assert.True(check.IsEnabled);
            Assert.Equal("赞助开发", sponsor.Content);

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
    public void RecordingPageExposesApplicationWindowTargetAndMicrophoneControls()
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

            Assert.Null(view.FindName("ScreenComboBox"));
            Assert.Contains("仅录制软件窗口", ((TextBlock)view.FindName("RecordingTargetText")!).Text);
            Assert.NotNull(view.FindName("MicrophoneComboBox"));
            Assert.NotNull(view.FindName("TestMicrophoneButton"));
            Assert.NotNull(view.FindName("StartRecordingButton"));
            Assert.Equal("已准备", ((TextBlock)view.FindName("RecordingStatusText")!).Text);
            Assert.Contains("MP4", ((TextBlock)view.FindName("RecordingStatsText")!).Text);

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void NarrowWindowCollapsesSidebarLabelsInsideClientBounds()
    {
        _fixture.Run(() =>
        {
            var view = new MainView { DataContext = MainViewModel.CreatePreview() };
            var window = new Window
            {
                Width = 800,
                Height = 600,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };

            window.Show();
            window.UpdateLayout();
            view.UpdateLayout();

            var sidebarColumn = (ColumnDefinition)view.FindName("SidebarColumn")!;
            var sidebar = (Border)view.FindName("SidebarPanel")!;
            Assert.Equal(72, sidebarColumn.ActualWidth);
            Assert.Equal(Visibility.Collapsed, ((TextBlock)view.FindName("QuickNavLabel")!).Visibility);
            Assert.True(sidebar.ActualWidth <= view.ActualWidth);
            Assert.True(view.ActualWidth - sidebar.ActualWidth > 0);

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void Mp4WriterCreatesAnMp4ContainerWithH264Video()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "capture.mp4");
        try
        {
            using (var writer = new Mp4FileWriter(path, 320, 240, 10, 44_100, includeAudio: false))
            {
                writer.WriteVideoFrame(new byte[320 * 240 * 4]);
                writer.Complete();
            }

            var bytes = File.ReadAllBytes(path);
            Assert.True(bytes.Length > 1_000);
            Assert.True(CountFourCc(bytes, "ftyp") >= 1);
            Assert.True(CountFourCc(bytes, "moov") >= 1);
            Assert.True(CountFourCc(bytes, "mdat") >= 1);
            Assert.True(CountFourCc(bytes, "avc1") >= 1 || CountFourCc(bytes, "avcC") >= 1);
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
    public void ApplicationOnlyRecordingCapturesFramesAndClosesAsValidMp4()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "app-only.mp4");
        try
        {
            _fixture.Run(() =>
            {
                var window = new Window
                {
                    Width = 640,
                    Height = 480,
                    WindowStyle = WindowStyle.None,
                    ShowInTaskbar = false,
                    Content = new MainView { DataContext = MainViewModel.CreatePreview() }
                };
                window.Show();
                window.UpdateLayout();
                var target = ScreenCapture.CreateTarget(window);
                Assert.Equal("HAM 点名助手窗口", target.Name);

                using var service = new ScreenRecordingService();
                var stateMessage = string.Empty;
                service.StateChanged += (_, state) => stateMessage = state.Message;
                service.Start(new RecordingOptions(target, path, IncludeMicrophone: false, MicrophoneId: null,
                    FramesPerSecond: 5));
                Assert.True(
                    WaitForVideoFrame(service, TimeSpan.FromSeconds(5)),
                    $"等待窗口录制器生成第一帧超时；状态={service.State}，视频帧={service.VideoFrames}，文件={service.OutputPath}" );
                var result = service.StopAsync().GetAwaiter().GetResult();

                Assert.True(result is not null, stateMessage);
                Assert.True(result!.VideoFrames > 0);
                Assert.True(File.Exists(path));
                var bytes = File.ReadAllBytes(path);
                Assert.True(CountFourCc(bytes, "ftyp") >= 1);
                Assert.True(CountFourCc(bytes, "moov") >= 1);
                Assert.True(CountFourCc(bytes, "mdat") >= 1);
                window.Close();
            });
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void ApplicationAndMicrophoneRecordingWritesVideoAndAacStreams()
    {
        var microphones = MicrophoneCapture.EnumerateDevices();
        if (microphones.Count == 0)
        {
            throw Xunit.Sdk.SkipException.ForSkip("当前 Windows 会话没有可用麦克风，未执行双流录制测试。");
        }

        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "app-and-microphone.mp4");
        try
        {
            _fixture.Run(() =>
            {
                var window = new Window
                {
                    Width = 640,
                    Height = 480,
                    WindowStyle = WindowStyle.None,
                    ShowInTaskbar = false,
                    Content = new MainView { DataContext = MainViewModel.CreatePreview() }
                };
                window.Show();
                window.UpdateLayout();
                var target = ScreenCapture.CreateTarget(window);
                using var service = new ScreenRecordingService();
                var stateMessage = string.Empty;
                service.StateChanged += (_, state) => stateMessage = state.Message;
                service.Start(new RecordingOptions(target, path, IncludeMicrophone: true,
                    MicrophoneId: microphones[0].Id, FramesPerSecond: 5));
                Assert.True(
                    WaitForVideoFrame(service, TimeSpan.FromSeconds(5)),
                    $"等待窗口录制器生成第一帧超时；状态={service.State}，视频帧={service.VideoFrames}，文件={service.OutputPath}" );
                var result = service.StopAsync().GetAwaiter().GetResult();

                Assert.True(result is not null, stateMessage);
                Assert.True(result!.VideoFrames > 0);
                Assert.True(result.AudioBytes > 0);
                var bytes = File.ReadAllBytes(path);
                Assert.True(CountFourCc(bytes, "ftyp") >= 1);
                Assert.True(CountFourCc(bytes, "moov") >= 1);
                Assert.True(CountFourCc(bytes, "mdat") >= 1);
                Assert.True(CountFourCc(bytes, "mp4a") >= 1 || CountFourCc(bytes, "esds") >= 1);
                window.Close();
            });
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    private static bool WaitForVideoFrame(ScreenRecordingService service, TimeSpan timeout)
    {
        var dispatcher = Dispatcher.CurrentDispatcher;
        var nestedFrame = new DispatcherFrame();
        var deadline = DateTime.UtcNow + timeout;
        var timer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(10),
            DispatcherPriority.Background,
            (_, _) =>
            {
                if (service.VideoFrames > 0 || DateTime.UtcNow >= deadline)
                {
                    nestedFrame.Continue = false;
                }
            },
            dispatcher);

        timer.Start();
        Dispatcher.PushFrame(nestedFrame);
        timer.Stop();
        return service.VideoFrames > 0;
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
