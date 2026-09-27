using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using NativeApplication = HamCheckin.Native.App.App;
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
            var status = (TextBlock)window.FindName("StatusText")!;
            var check = (Button)window.FindName("CheckButton")!;

            Assert.Equal("1.0.0", version.Text);
            Assert.Contains("当前已是最新", status.Text);
            Assert.True(check.IsEnabled);

            window.Close();
        });
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
