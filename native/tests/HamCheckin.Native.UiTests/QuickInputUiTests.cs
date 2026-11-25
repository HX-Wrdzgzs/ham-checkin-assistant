using System.Net;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using NativeApplication = HamCheckin.Native.App.App;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.Media;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.App.Views;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Export;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.Core.Updates;
using Microsoft.Data.Sqlite;
using Xunit;

namespace HamCheckin.Native.UiTests;

[CollectionDefinition("Native WPF application", DisableParallelization = true)]
public sealed class NativeWpfApplicationFixtureGroup : ICollectionFixture<WpfDispatcherFixture>
{
}

[Collection("Native WPF application")]
public sealed class QuickInputUiTests
{
    private static readonly TimeSpan HardwareProbeTimeout = TimeSpan.FromSeconds(10);
    private const string Original = "BA4RLL QYT6900 5W YZ YZ";
    private static readonly string[] HeaderActionNames =
    {
        "NewSessionButton",
        "SelectSessionButton",
        "EditSessionButton",
        "ToggleSessionButton",
        "OpenQuickWindowButton"
    };
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
    public void InputEditStaysStableAndAnimationSettingDisablesPageTransition()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.AnimationsEnabled = false;
            viewModel.SetInputText(Original);
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1_440,
                Height = 900,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };

            window.Show();
            window.UpdateLayout();
            view.UpdateLayout();

            var input = (TextBox)view.FindName("InputBox")!;
            var parseStrip = (FrameworkElement)view.FindName("ParseStrip")!;
            var successFlash = (FrameworkElement)view.FindName("SuccessFlash")!;
            Assert.Equal(1d, parseStrip.Opacity);
            Assert.Equal(0d, successFlash.Opacity);

            input.Focus();
            input.Select("BA4RLL ".Length, "QYT6900".Length);
            input.SelectedText = "PD780";
            view.UpdateLayout();

            // A live edit must not animate or replace the preview surface.
            // The text and its suffix are the only state that changes here.
            Assert.Equal("BA4RLL PD780 5W YZ YZ", input.Text);
            Assert.Equal(1d, parseStrip.Opacity);
            Assert.Equal(0d, successFlash.Opacity);

            view.ShowPage("Records");
            view.UpdateLayout();
            var recordsPage = (FrameworkElement)view.FindName("RecordsPage")!;
            Assert.Equal(1d, recordsPage.Opacity);
            Assert.True(
                recordsPage.RenderTransform is null
                || recordsPage.RenderTransform.Value == Matrix.Identity);

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void PageEntranceAnimatesThenSettlesAtRestWhenMotionIsEnabled()
    {
        RequireClientAreaAnimation();

        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            Assert.True(viewModel.AnimationsEnabled);
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1_440,
                Height = 900,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };
            try
            {
                window.Show();
                window.UpdateLayout();
                PumpDispatcherUntil(() => view.IsLoaded, TimeSpan.FromSeconds(5));
                Assert.True(view.IsLoaded, "MainView 未在 5 秒内完成加载，无法验证页面过渡。");

                view.ShowPage("Records");
                var recordsPage = (FrameworkElement)view.FindName("RecordsPage")!;
                Assert.Equal(Visibility.Visible, recordsPage.Visibility);
                // WPF 在第一次合成帧之前只报告基础值，因此“已开始”的确定信号是动画时钟已挂载；
                // 实际插值在下方持续泵送期间采样验证。
                Assert.True(
                    recordsPage.HasAnimatedProperties,
                    "页面过渡没有挂载动画时钟：ShowPage 未启动 RecordsPage 入场动画。");

                var sample = SamplePageMotion(recordsPage, TimeSpan.FromMilliseconds(300));
                Assert.True(sample.MinOpacity < 1d, $"页面过渡期间不透明度没有低于 1：min={sample.MinOpacity}");
                Assert.True(sample.MaxOffset > 0d, $"页面过渡期间没有横向位移：max={sample.MaxOffset}");

                var rest = SamplePageMotion(recordsPage, TimeSpan.FromMilliseconds(150));
                Assert.Equal(1d, rest.MinOpacity);
                Assert.Equal(0d, rest.MaxOffset);
                Assert.Equal(1d, recordsPage.Opacity);
                Assert.Equal(0d, PageOffset(recordsPage).X);
                Assert.Equal(0d, PageOffset(recordsPage).Y);
            }
            finally
            {
                view.Dispose();
                window.Close();
            }
        });
    }

    [Fact]
    public void RapidPageSwitchesCancelAndSettleAtRestWhenMotionIsEnabled()
    {
        RequireClientAreaAnimation();

        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            Assert.True(viewModel.AnimationsEnabled);
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1_440,
                Height = 900,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };
            try
            {
                window.Show();
                window.UpdateLayout();
                PumpDispatcherUntil(() => view.IsLoaded, TimeSpan.FromSeconds(5));
                Assert.True(view.IsLoaded, "MainView 未在 5 秒内完成加载，无法验证页面过渡。");

                var recordsPage = (FrameworkElement)view.FindName("RecordsPage")!;
                var catalogPage = (FrameworkElement)view.FindName("CatalogPage")!;

                view.ShowPage("Records");
                Assert.True(recordsPage.HasAnimatedProperties, "第一次页面过渡没有挂载动画时钟。");

                view.ShowPage("Catalog");
                Assert.True(catalogPage.HasAnimatedProperties, "快速切换后的目标页过渡没有挂载动画时钟。");

                view.ShowPage("Records");
                Assert.True(recordsPage.HasAnimatedProperties, "返回已访问页面时过渡没有重新挂载动画时钟。");

                var sample = SamplePageMotion(recordsPage, TimeSpan.FromMilliseconds(300));
                Assert.True(sample.MinOpacity < 1d, $"快速切换后不透明度没有低于 1：min={sample.MinOpacity}");
                Assert.True(sample.MaxOffset > 0d, $"快速切换后没有横向位移：max={sample.MaxOffset}");

                var rest = SamplePageMotion(recordsPage, TimeSpan.FromMilliseconds(150));
                Assert.Equal(1d, rest.MinOpacity);
                Assert.Equal(0d, rest.MaxOffset);

                Assert.Equal(Visibility.Visible, recordsPage.Visibility);
                Assert.Equal(Visibility.Collapsed, catalogPage.Visibility);
                Assert.Equal(1d, recordsPage.Opacity);
                Assert.Equal(0d, PageOffset(recordsPage).X);
                Assert.Equal(0d, PageOffset(recordsPage).Y);
                Assert.Equal(1d, catalogPage.Opacity);
                Assert.Equal(0d, PageOffset(catalogPage).X);
                Assert.Equal(0d, PageOffset(catalogPage).Y);
            }
            finally
            {
                view.Dispose();
                window.Close();
            }
        });
    }

    [Fact]
    public async Task QuickInputDraftIsAvailableBeforeBootstrapAndSurvivesInitialization()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        var draft = "BA4AAA NJXW PD780 5W";
        MainViewModel? viewModel = null;
        try
        {
            RuntimeOptions.Configure(
                fixedNow: new DateTimeOffset(2026, 10, 6, 21, 0, 0, TimeSpan.FromHours(8)),
                disableNetwork: true);
            viewModel = new MainViewModel(
                new CatalogService(),
                new NativeStore(databasePath),
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);

            Assert.True(viewModel.IsQuickInputAvailable);
            viewModel.SetInputText(draft);
            var initializeTask = viewModel.InitializeAsync();
            Assert.True(viewModel.IsQuickInputAvailable);
            await initializeTask;

            Assert.True(viewModel.IsReady);
            Assert.True(viewModel.IsQuickInputAvailable);
            Assert.Equal(draft, viewModel.InputText);
            Assert.Equal("江苏省南京市玄武区", viewModel.Qth);
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            RuntimeOptions.Configure(
                fixedNow: null,
                storeDelayMilliseconds: 0,
                disableNetwork: previousNetworkMode);
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public async Task ExportUsesCapturedSessionAfterSwitching()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        MainViewModel? viewModel = null;
        NativeStore? store = null;
        try
        {
            RuntimeOptions.Configure(
                fixedNow: new DateTimeOffset(2026, 10, 6, 21, 0, 0, TimeSpan.FromHours(8)),
                disableNetwork: true);
            store = new NativeStore(databasePath);
            await store.InitializeAsync();
            viewModel = new MainViewModel(
                new CatalogService(), store,
                catalogDataRoot: Path.Combine(root, "data"), importLegacyDatabase: false);
            await viewModel.InitializeAsync();
            var captured = await viewModel.GetSessionAsync()
                ?? throw new InvalidOperationException("Initial session was not loaded.");
            var other = await store.CreateSessionAsync("切换后的场次", "2026-10-07");
            var parser = new InputParser(CatalogLoader.CreateBuiltIn());
            await store.AddCheckinAsync(captured, parser.Parse("BA4AAA NJXW R6 5W"), "export-captured-row");
            await store.AddCheckinAsync(other, parser.Parse("BA4AAB NJXW R6 5W"), "export-other-row");
            SessionInfo? requested = null;
            viewModel.ExportRequested += snapshot => requested = snapshot;
            viewModel.ExportCommand.Execute(null);
            Assert.Equal(captured.Id, requested?.Id);
            await viewModel.SelectSessionAsync(other.Id);
            Assert.Equal("切换后的场次", viewModel.SessionTitle);
            var exportDirectory = Path.Combine(root, "exports");
            Directory.CreateDirectory(exportDirectory);
            var exportFileName = "captured-session.xlsx";
            await viewModel.ExportSnapshotAsync(
                requested ?? throw new InvalidOperationException("Export request was not captured."),
                new ExcelExportTarget(exportDirectory, exportFileName, false));
            Assert.True(File.Exists(Path.Combine(exportDirectory, exportFileName)));
            var firstRows = await store.LoadAllForExportAsync(captured.Id);
            var secondRows = await store.LoadAllForExportAsync(other.Id);
            Assert.Single(firstRows);
            Assert.Single(secondRows);
            Assert.Equal(captured.Id, firstRows[0].SessionId);
            Assert.Equal(other.Id, secondRows[0].SessionId);
            Assert.Equal("切换后的场次", viewModel.SessionTitle);
            var exportPath = Path.Combine(exportDirectory, exportFileName);
            using var archive = ZipFile.OpenRead(exportPath);
            using var sheetReader = new StreamReader(archive.GetEntry("xl/worksheets/sheet1.xml")!.Open(), Encoding.UTF8);
            var sheetXml = await sheetReader.ReadToEndAsync();
            Assert.Contains(captured.Name, sheetXml);
            Assert.Contains(captured.Date, sheetXml);
            Assert.Contains("BA4AAA", sheetXml);
            Assert.DoesNotContain("BA4AAB", sheetXml);
            Assert.DoesNotContain(other.Name, sheetXml);
            using var coreReader = new StreamReader(archive.GetEntry("docProps/core.xml")!.Open(), Encoding.UTF8);
            Assert.Contains($"<dc:subject>{captured.Name}</dc:subject>", await coreReader.ReadToEndAsync());
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            else if (store is not null)
            {
                await store.DisposeAsync();
            }
            RuntimeOptions.Configure(fixedNow: null, storeDelayMilliseconds: 0, disableNetwork: previousNetworkMode);
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
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
    public void QuickWindowKeepsSuffixWhenImeMetadataIsStaleDuringMiddleEdit()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText(Original);
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

            var input = (TextBox)quick.FindName("QuickInputBox")!;
            input.Focus();
            // Simulate an IME composition notification that arrives before
            // the real WPF TextChanged event. It must not advance the text
            // revision or cause the old full string to be written back.
            viewModel.SetImeCompositionState("quick-window-input", true);
            input.Select("BA4RLL ".Length, "QYT6900".Length);
            input.SelectedText = "PD780";
            viewModel.SetImeCompositionState("quick-window-input", false);

            Assert.Equal("BA4RLL PD780 5W YZ YZ", input.Text);
            Assert.Equal(input.Text, viewModel.InputText);
            Assert.Equal("5W YZ YZ", input.Text[("BA4RLL PD780 ").Length..]);

            quick.Close();
        });
    }

    [Fact]
    public void PreviewStillParsesWhenImeMetadataArrivesBeforeTextChange()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1_440,
                Height = 900,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };
            window.Show();
            window.UpdateLayout();

            var input = (TextBox)view.FindName("InputBox")!;
            input.Focus();
            viewModel.SetImeCompositionState("main-input", true);
            input.Text = "BA4AAA NJXW PD780 4.2M 5W";

            Assert.Equal("江苏省南京市玄武区", viewModel.Qth);
            Assert.Equal("海能达 PD-780", viewModel.Device);
            Assert.Equal("4.2米玻璃钢", viewModel.Antenna);
            Assert.Equal("5W", viewModel.Power);
            Assert.Empty(viewModel.Unmatched);

            viewModel.SetImeCompositionState("main-input", false);
            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void QuickWindowKeepsSuffixWhenEditingTheFrontOfTheLine()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText(Original);
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

            var input = (TextBox)quick.FindName("QuickInputBox")!;
            input.Focus();
            input.Select(0, "BA4RLL".Length);
            input.SelectedText = "BA4VXR";

            Assert.Equal("BA4VXR QYT6900 5W YZ YZ", input.Text);
            Assert.Equal(" QYT6900 5W YZ YZ", input.Text["BA4VXR".Length..]);
            Assert.Equal(input.Text, viewModel.InputDraft.Text);

            quick.Close();
        });
    }

    [Fact]
    public void QuickWindowPreservesUneditedRegionsForInsertDeleteAndTailEdit()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText(Original);
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

            var input = (TextBox)quick.FindName("QuickInputBox")!;
            input.Focus();

            // Insertion at the beginning must not rebuild the line from an old
            // snapshot and lose the existing suffix.
            input.CaretIndex = 0;
            input.SelectedText = "X";
            Assert.Equal("X" + Original, input.Text);
            Assert.Equal(input.Text, viewModel.InputDraft.Text);

            // Reset through the explicit programmatic path, then delete one
            // character in the middle.  The fields after the edit must remain
            // byte-for-byte unchanged.
            viewModel.SetInputText(Original);
            input.Focus();
            var middleIndex = "BA4RLL QY".Length;
            input.Select(middleIndex, 1);
            input.SelectedText = string.Empty;
            Assert.Equal("BA4RLL QY6900 5W YZ YZ", input.Text);
            Assert.EndsWith(" 5W YZ YZ", input.Text, StringComparison.Ordinal);
            Assert.Equal(input.Text, viewModel.InputText);

            // A tail insertion is also a real TextBox edit, not a parser or
            // mirror update.  It must reach the shared draft unchanged.
            viewModel.SetInputText(Original);
            input.Focus();
            input.CaretIndex = input.Text.Length;
            input.SelectedText = " END";
            Assert.Equal(Original + " END", input.Text);
            Assert.Equal(input.Text, viewModel.InputDraft.Text);

            quick.Close();
        });
    }

    [Fact]
    public void QuickWindowShowsRecentRecordsWithoutTakingInputFocus()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
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

            var input = (TextBox)quick.FindName("QuickInputBox")!;
            var recent = (ItemsControl)quick.FindName("QuickRecentItems")!;
            Assert.Equal(3, recent.Items.Count);
            input.Focus();
            input.Select(0, 0);
            Assert.True(input.IsKeyboardFocusWithin);
            Assert.Equal("BA4VWI", ((CheckinEntry)recent.Items[2]).Callsign);

            quick.Close();
        });
    }

    [Fact]
    public void QuickWindowMinimumSizeCollapsesRecentRowsButKeepsEntryControlsUsable()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText(Original);
            var quick = new QuickWindow
            {
                Width = 420,
                Height = 190,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                DataContext = viewModel
            };
            quick.Show();
            quick.UpdateLayout();

            var input = (TextBox)quick.FindName("QuickInputBox")!;
            var submit = (Button)quick.FindName("QuickSubmitButton")!;
            var recent = (Border)quick.FindName("RecentCheckinsCard")!;
            var content = (ScrollViewer)quick.FindName("QuickContentScrollViewer")!;
            var footer = (Grid)quick.FindName("QuickFooterGrid")!;

            Assert.True(quick.ActualWidth >= quick.MinWidth);
            Assert.True(quick.ActualHeight >= quick.MinHeight);
            Assert.Equal(Visibility.Collapsed, recent.Visibility);
            Assert.True(input.IsVisible);
            Assert.True(input.ActualWidth >= 180);
            Assert.True(input.ActualHeight >= 30);
            Assert.True(submit.IsVisible);
            Assert.True(submit.ActualWidth >= 60);
            Assert.Equal(Original, input.Text);

            var inputBottom = input.TranslatePoint(new Point(0, input.ActualHeight), quick).Y;
            var contentTop = content.TranslatePoint(new Point(0, 0), quick).Y;
            var contentBottom = contentTop + content.ActualHeight;
            var footerTop = footer.TranslatePoint(new Point(0, 0), quick).Y;
            Assert.True(inputBottom <= contentTop + 0.5, $"输入框与解析区重叠：{inputBottom}/{contentTop}");
            Assert.True(contentBottom <= footerTop + 0.5, $"解析区越过底部状态栏：{contentBottom}/{footerTop}");

            quick.Height = 280;
            quick.UpdateLayout();
            Assert.Equal(Visibility.Visible, recent.Visibility);
            Assert.Equal(3, ((ItemsControl)quick.FindName("QuickRecentItems")!).Items.Count);

            quick.Close();
        });
    }

    [Fact]
    public void AmbiguousQthCandidateIsVisibleAndSelectionKeepsRawInput()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText("ba4aaa bj");
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1100,
                Height = 700,
                Content = view,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.UpdateLayout();

            var panel = (StackPanel)view.FindName("QthCandidatePanel")!;
            var input = (TextBox)view.FindName("InputBox")!;
            Assert.Equal(Visibility.Visible, panel.Visibility);
            Assert.NotEmpty(viewModel.QthCandidates);
            Assert.Equal("ba4aaa bj", input.Text);

            var selected = viewModel.QthCandidates.First(candidate => candidate == "北京市");
            viewModel.SelectQthCandidate(selected);

            Assert.Equal("北京市", viewModel.Qth);
            Assert.Equal("ba4aaa bj", input.Text);
            Assert.Empty(viewModel.QthCandidates);
            Assert.DoesNotContain("bj", viewModel.Unmatched, StringComparison.OrdinalIgnoreCase);

            window.Close();
        });
    }

    [Fact]
    public void SelectedQthCandidateSurvivesBackgroundCatalogReparseForTheSameDraft()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            viewModel.SetInputText("ba4aaa bj");

            viewModel.SelectQthCandidate("北京市");
            Assert.Equal("北京市", viewModel.Qth);
            Assert.Empty(viewModel.Unmatched);

            // A catalog refresh reparses the current draft.  It must not
            // erase an explicit choice made for this same revision.
            viewModel.ReparseCurrentInputForTesting();

            Assert.Equal("北京市", viewModel.Qth);
            Assert.Equal("ba4aaa bj", viewModel.InputText);
            Assert.Empty(viewModel.Unmatched);
            Assert.Empty(viewModel.QthCandidates);
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
    public async Task SubmissionFinishingAfterSessionSwitchDoesNotPolluteTheNewSessionView()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        RuntimeOptions.Configure(
            fixedNow: new DateTimeOffset(2026, 10, 5, 21, 0, 0, TimeSpan.FromHours(8)),
            disableNetwork: true);

        NativeStore? store = null;
        MainViewModel? viewModel = null;
        try
        {
            store = new NativeStore(databasePath, storeDelayMilliseconds: 250);
            await store.InitializeAsync();
            viewModel = new MainViewModel(
                new CatalogService(),
                store,
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);
            await viewModel.InitializeAsync();

            var first = await store.GetOrCreateFirstSessionAsync(RuntimeOptions.Today);
            var second = await store.CreateSessionAsync("第2场点名", "2026-10-05");
            viewModel.SetInputText("BA4AAA NJXW PD780 5W");

            var submitTask = viewModel.SubmitForTestingAsync();
            await Task.Delay(35);
            await viewModel.SelectSessionAsync(second.Id);
            await submitTask;

            var firstRows = await store.LoadAllForExportAsync(first.Id);
            var secondRows = await store.LoadAllForExportAsync(second.Id);
            Assert.Single(firstRows);
            Assert.Empty(secondRows);
            Assert.Equal("第2场点名", viewModel.SessionTitle);
            Assert.Empty(viewModel.Checkins);
            Assert.Equal(1, viewModel.NextSequence);
            Assert.Empty(viewModel.InputText);
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            else if (store is not null)
            {
                await store.DisposeAsync();
            }
            RuntimeOptions.Configure(
                fixedNow: null,
                storeDelayMilliseconds: 0,
                disableNetwork: previousNetworkMode);
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public async Task EndedSessionDisablesQuickInputAndKeepsTheViewReadOnly()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        RuntimeOptions.Configure(
            fixedNow: new DateTimeOffset(2026, 10, 5, 21, 0, 0, TimeSpan.FromHours(8)),
            disableNetwork: true);

        MainViewModel? viewModel = null;
        try
        {
            viewModel = new MainViewModel(
                new CatalogService(),
                new NativeStore(databasePath),
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);
            await viewModel.InitializeAsync();
            await viewModel.SetCurrentSessionStatusAsync(reopen: false);

            Assert.False(viewModel.IsSessionWritable);
            Assert.False(viewModel.SubmitCommand.CanExecute(null));

            _fixture.Run(() =>
            {
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
                var quickSubmit = (Button)quick.FindName("QuickSubmitButton")!;

                Assert.False(mainInput.IsEnabled);
                Assert.False(quickInput.IsEnabled);
                Assert.False(quickSubmit.IsEnabled);

                quick.Close();
                main.Close();
            });
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            RuntimeOptions.Configure(
                fixedNow: null,
                storeDelayMilliseconds: 0,
                disableNetwork: previousNetworkMode);
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
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
            var notes = (TextBox)window.FindName("ReleaseNotesText")!;
            var check = (Button)window.FindName("CheckButton")!;
            var sponsor = (Button)window.FindName("SponsorButton")!;

            Assert.Equal("1.0.20", version.Text);
            Assert.Equal("开发者：BA4THG（HX-Wrdzgzs）", developer.Text);
            Assert.Contains("当前已是最新", status.Text);
            Assert.Contains("本地候选版", notes.Text);
            Assert.Contains("未知尾缀保留待修正", notes.Text);
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
    public async Task EachRealInitializationStartsAnIsolatedBackgroundUpdateCheck()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var handler = new UpdateProbeHandler();
        using var client = new HttpClient(handler);
        var updateService = new NativeUpdateService(client);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        RuntimeOptions.Configure(disableNetwork: false);

        try
        {
            for (var index = 0; index < 2; index++)
            {
                var dataRoot = Path.Combine(root, $"run-{index}");
                var databasePath = Path.Combine(dataRoot, "data", "ham_checkin_native.db");
                var store = new NativeStore(databasePath);
                var viewModel = new MainViewModel(
                    new CatalogService(),
                    store,
                    updateService,
                    catalogDataRoot: Path.Combine(dataRoot, "data"),
                    importLegacyDatabase: false);

                await viewModel.InitializeAsync();
                Assert.NotNull(viewModel.StartupUpdateCheckTask);
                await viewModel.StartupUpdateCheckTask!;

                Assert.Contains("已检查更新", viewModel.UpdateStatus);
                await viewModel.DisposeAsync();
            }

            // The API is intentionally unavailable in the fixture, so each
            // launch must fall back to the stable manifest independently.
            Assert.Equal(4, handler.Requests.Count);
            Assert.Equal(2, handler.Requests.Count(url => url == NativeVersion.StableApiUrl));
            Assert.Equal(2, handler.Requests.Count(url => url == NativeVersion.StableManifestUrl));
        }
        finally
        {
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
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
            var recordingTarget = ScreenCapture.CreateTarget(window);
            var frame = ScreenCapture.CaptureFrame(recordingTarget);
            Assert.Equal(recordingTarget.Width * recordingTarget.Height * 4, frame.Length);

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
    public void RecordingDefaultsToApplicationWindowOnlyUntilMicrophoneIsOptedIn()
    {
        _fixture.Run(() =>
        {
            var view = new MainView { DataContext = MainViewModel.CreatePreview() };
            var window = new Window
            {
                Width = 1_180,
                Height = 760,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };

            window.Show();
            window.UpdateLayout();
            view.ShowPage("Recording");
            view.UpdateLayout();

            var microphoneCheckBox = (CheckBox)view.FindName("IncludeMicrophoneCheckBox")!;
            var target = (TextBlock)view.FindName("RecordingTargetText")!;
            var output = (TextBox)view.FindName("RecordingPathBox")!;
            Assert.False(microphoneCheckBox.IsChecked == true);
            Assert.Contains("仅录制软件窗口", target.Text);
            Assert.EndsWith(".mp4", output.Text, StringComparison.OrdinalIgnoreCase);

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
            var navigation = (StackPanel)view.FindName("NavigationPanel")!;
            Assert.Equal(72, sidebarColumn.ActualWidth);
            Assert.Equal(Visibility.Collapsed, ((TextBlock)view.FindName("QuickNavLabel")!).Visibility);
            Assert.True(sidebar.ActualWidth <= view.ActualWidth);
            Assert.True(view.ActualWidth - sidebar.ActualWidth > 0);
            Assert.All(
                navigation.Children.OfType<RadioButton>(),
                radio => Assert.True(radio.ActualWidth <= sidebar.ActualWidth + 0.1));

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void DirectPageSelectionKeepsSidebarSelectionInSync()
    {
        _fixture.Run(() =>
        {
            var view = new MainView { DataContext = MainViewModel.CreatePreview() };
            var window = new Window
            {
                Width = 1_180,
                Height = 760,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };

            window.Show();
            window.UpdateLayout();

            view.ShowPage("Settings");
            view.UpdateLayout();
            var navigation = ((StackPanel)view.FindName("NavigationPanel")!).Children
                .OfType<RadioButton>()
                .ToDictionary(radio => (string)radio.Tag!, radio => radio);
            Assert.True(navigation["Settings"].IsChecked);
            Assert.False(navigation["Quick"].IsChecked);
            Assert.Equal(Visibility.Visible, ((Grid)view.FindName("SettingsPage")!).Visibility);

            view.ShowPage("Quick");
            view.UpdateLayout();
            Assert.True(navigation["Quick"].IsChecked);
            Assert.False(navigation["Settings"].IsChecked);
            Assert.Equal(Visibility.Visible, ((Grid)view.FindName("QuickPage")!).Visibility);

            view.Dispose();
            window.Close();
        });
    }

    [Fact]
    public void HeaderActionsStayInsideClientBoundsAcrossSupportedWindowWidths()
    {
        _fixture.Run(() =>
        {
            foreach (var (width, height) in new[]
            {
                (1_440d, 900d),
                (1_280d, 720d),
                (1_024d, 768d),
                (800d, 600d)
            })
            {
                var view = new MainView { DataContext = MainViewModel.CreatePreview() };
                var window = new Window
                {
                    Width = width,
                    Height = height,
                    WindowStyle = WindowStyle.None,
                    ShowInTaskbar = false,
                    Content = view
                };

                window.Show();
                window.UpdateLayout();
                view.UpdateLayout();

                var actions = (FrameworkElement)view.FindName("HeaderActionsPanel")!;
                Assert.True(actions.ActualWidth > 0, $"{width}x{height} 顶部场次按钮没有布局宽度。");
                if (width < 1_100)
                {
                    Assert.Equal(1, Grid.GetRow(actions));
                    Assert.Equal(2, Grid.GetColumnSpan(actions));
                    Assert.Equal(HorizontalAlignment.Left, actions.HorizontalAlignment);
                }
                else
                {
                    Assert.Equal(0, Grid.GetRow(actions));
                    Assert.Equal(1, Grid.GetColumn(actions));
                }
                foreach (var name in HeaderActionNames)
                {
                    var button = (Button)view.FindName(name)!;
                    var origin = button.TranslatePoint(new Point(0, 0), view);
                    Assert.True(origin.X >= -0.5 && origin.Y >= -0.5,
                        $"{width}x{height} {name} 左上角越过客户区：{origin}");
                    Assert.True(origin.X + button.ActualWidth <= view.ActualWidth + 0.5,
                        $"{width}x{height} {name} 横向越界：{origin.X + button.ActualWidth}/{view.ActualWidth}");
                    Assert.True(origin.Y + button.ActualHeight <= view.ActualHeight + 0.5,
                        $"{width}x{height} {name} 纵向越界：{origin.Y + button.ActualHeight}/{view.ActualHeight}");
                }

                view.Dispose();
                window.Close();
            }
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

    [Trait("Category", "Hardware")]
    [Fact]
    public async Task MicrophoneEnumerationReturnsAUsableSnapshot()
    {
        RequireHardwareAuthorization();
        var devices = await EnumerateMicrophonesAsync();
        if (devices.Count == 0)
        {
            throw Xunit.Sdk.SkipException.ForSkip("No microphone is available; hardware enumeration assertions were skipped.");
        }

        Assert.NotNull(devices);
        Assert.All(devices, device => Assert.False(string.IsNullOrWhiteSpace(device.Name)));
    }

    [Trait("Category", "Hardware")]
    [Fact]
    public async Task FirstMicrophoneCanOpenAndReturnPcmForDebugging()
    {
        RequireHardwareAuthorization();
        var devices = await EnumerateMicrophonesAsync();
        if (devices.Count == 0)
        {
            throw Xunit.Sdk.SkipException.ForSkip("当前 Windows 会话没有可用麦克风；屏幕录制仍可在关闭麦克风后使用。");
        }

        var bytes = 0;
        var firstPcm = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var capture = new MicrophoneCapture(devices[0].Id);
        capture.AudioData += data =>
        {
            Interlocked.Add(ref bytes, data.Length);
            if (!data.IsEmpty) firstPcm.TrySetResult(true);
        };
        capture.Start();
        try
        {
            await firstPcm.Task.WaitAsync(HardwareProbeTimeout);
        }
        finally
        {
            capture.Stop();
        }

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
    public void ApplicationRecordingNeverFallsBackToACoveringDesktopWindow()
    {
        _fixture.Run(() =>
        {
            var target = new Window
            {
                Width = 640,
                Height = 480,
                Left = 120,
                Top = 120,
                WindowStyle = WindowStyle.None,
                ResizeMode = ResizeMode.NoResize,
                ShowInTaskbar = false,
                Background = new SolidColorBrush(Color.FromRgb(26, 180, 112)),
                Content = new Border
                {
                    Background = new SolidColorBrush(Color.FromRgb(26, 180, 112))
                }
            };
            var coveringWindow = new Window
            {
                Width = target.Width,
                Height = target.Height,
                Left = target.Left,
                Top = target.Top,
                WindowStyle = WindowStyle.None,
                ResizeMode = ResizeMode.NoResize,
                ShowInTaskbar = false,
                Topmost = true,
                Background = new SolidColorBrush(Color.FromRgb(220, 38, 38)),
                Content = new Border
                {
                    Background = new SolidColorBrush(Color.FromRgb(220, 38, 38))
                }
            };

            try
            {
                target.Show();
                target.UpdateLayout();
                coveringWindow.Show();
                coveringWindow.UpdateLayout();

                var recordingTarget = ScreenCapture.CreateTarget(target);
                var frame = ScreenCapture.CaptureFrame(recordingTarget);
                var width = recordingTarget.Width;
                var height = recordingTarget.Height;
                var greenPixels = 0;
                var redPixels = 0;
                foreach (var y in new[] { height / 4, height / 2, (height * 3) / 4 })
                {
                    foreach (var x in new[] { width / 4, width / 2, (width * 3) / 4 })
                    {
                        var offset = ((y * width) + x) * 4;
                        var blue = frame[offset];
                        var green = frame[offset + 1];
                        var red = frame[offset + 2];
                        if (Math.Abs(red - 26) <= 3 && Math.Abs(green - 180) <= 3 && Math.Abs(blue - 112) <= 3)
                        {
                            greenPixels++;
                        }

                        if (Math.Abs(red - 220) <= 3 && Math.Abs(green - 38) <= 3 && Math.Abs(blue - 38) <= 3)
                        {
                            redPixels++;
                        }
                    }
                }

                Assert.True(greenPixels >= 7,
                    $"窗口被覆盖时没有稳定捕获 HAM 目标窗口内容；绿色采样={greenPixels}，红色覆盖采样={redPixels}。" );
                Assert.Equal(0, redPixels);
            }
            finally
            {
                coveringWindow.Close();
                target.Close();
            }
        });
    }

    [Trait("Category", "Hardware")]
    [Fact]
    public async Task ApplicationAndMicrophoneRecordingWritesVideoAndAacStreams()
    {
        RequireHardwareAuthorization();
        var microphones = await EnumerateMicrophonesAsync();
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
                Assert.True(
                    SpinWait.SpinUntil(() => service.AudioBytes > 0, HardwareProbeTimeout),
                    "Timed out waiting for microphone audio to reach the AAC writer.");
                var result = service.StopAsync().WaitAsync(HardwareProbeTimeout).GetAwaiter().GetResult();

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

    [Fact]
    public void RecordingNeverOverwritesAnExistingMp4()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "existing.mp4");
        const string original = "keep this recording";
        File.WriteAllText(path, original, Encoding.UTF8);
        try
        {
            using var service = new ScreenRecordingService();
            var target = new RecordingTarget(nint.Zero, "HAM 点名助手窗口", 320, 240);

            var exception = Assert.Throws<IOException>(() => service.Start(
                new RecordingOptions(target, path, IncludeMicrophone: false, MicrophoneId: null)));

            Assert.Contains("输出文件已存在", exception.Message);
            Assert.Equal(original, File.ReadAllText(path, Encoding.UTF8));
            Assert.Empty(Directory.EnumerateFiles(directory, "*.partial.mp4"));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void ConcurrentStopRequestsShareOneCompletedResult()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "concurrent-stop.mp4");
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
                service.Start(new RecordingOptions(target, path, IncludeMicrophone: false, MicrophoneId: null,
                    FramesPerSecond: 5));
                Assert.True(WaitForVideoFrame(service, TimeSpan.FromSeconds(5)));

                var firstStop = service.StopAsync();
                var secondStop = service.StopAsync();
                RecordingResult?[]? results = null;
                Exception? stopFailure = null;
                var stopFrame = new DispatcherFrame();
                var dispatcher = Dispatcher.CurrentDispatcher;
                var stopCompleted = false;
                _ = Task.WhenAll(firstStop, secondStop).ContinueWith(completed =>
                {
                    dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() =>
                    {
                        if (completed.IsFaulted)
                        {
                            stopFailure = completed.Exception;
                        }
                        else
                        {
                            results = completed.Result;
                        }

                        stopCompleted = true;
                        stopFrame.Continue = false;
                    }));
                }, TaskScheduler.Default);
                var stopTimeout = new DispatcherTimer(
                    TimeSpan.FromSeconds(20),
                    DispatcherPriority.Background,
                    (_, _) => stopFrame.Continue = false,
                    dispatcher);
                stopTimeout.Start();
                Dispatcher.PushFrame(stopFrame);
                stopTimeout.Stop();
                Assert.True(stopCompleted, "Timed out waiting for concurrent recording stop requests.");
                if (stopFailure is not null)
                {
                    throw stopFailure;
                }

                Assert.NotNull(results);

                Assert.NotNull(results![0]);
                Assert.NotNull(results[1]);
                Assert.Equal(results[0]!.OutputPath, results[1]!.OutputPath);
                Assert.Equal(RecordingState.Completed, service.State);
                Assert.True(File.Exists(path));
                window.Close();
            });
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public async Task FailedWindowCaptureDoesNotReportCompletedOrLeavePartialMp4()
    {
        var directory = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "failed.mp4");
        try
        {
            using var service = new ScreenRecordingService();
            var invalidTarget = new RecordingTarget(new nint(1), "HAM 点名助手窗口", 320, 240);
            service.Start(new RecordingOptions(
                invalidTarget,
                path,
                IncludeMicrophone: false,
                MicrophoneId: null,
                FramesPerSecond: 5));

            Assert.True(
                SpinWait.SpinUntil(() => service.State == RecordingState.Failed, TimeSpan.FromSeconds(5)),
                $"窗口采集失败没有被报告：state={service.State}, frames={service.VideoFrames}");
            Assert.True(service.IsActive, "失败录屏在清理前必须阻止开始第二个录屏任务。");
            Assert.Throws<InvalidOperationException>(() => service.Start(new RecordingOptions(
                invalidTarget,
                Path.Combine(directory, "retry.mp4"),
                IncludeMicrophone: false,
                MicrophoneId: null)));

            var result = await service.StopAsync();
            Assert.Null(result);
            Assert.Equal(RecordingState.Failed, service.State);
            Assert.False(service.IsActive);
            Assert.False(File.Exists(path));
            Assert.Empty(Directory.EnumerateFiles(directory, "*.partial.mp4"));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    private void RequireClientAreaAnimation()
    {
        var enabled = false;
        _fixture.Run(() => enabled = WindowMotion.IsMotionEnabled(true));
        if (!enabled)
        {
            throw Xunit.Sdk.SkipException.ForSkip(
                "当前 Windows 会话关闭了客户端区域动画（SystemParameters.ClientAreaAnimation=false），跳过启用态过渡断言。");
        }
    }

    private static (double MinOpacity, double MaxOffset) SamplePageMotion(
        FrameworkElement page, TimeSpan duration)
    {
        var dispatcher = Dispatcher.CurrentDispatcher;
        var frame = new DispatcherFrame();
        var deadline = DateTime.UtcNow + duration;
        var minOpacity = page.Opacity;
        var maxOffset = PageOffset(page).X;
        var timer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(5),
            DispatcherPriority.Background,
            (_, _) =>
            {
                minOpacity = Math.Min(minOpacity, page.Opacity);
                maxOffset = Math.Max(maxOffset, PageOffset(page).X);
                if (DateTime.UtcNow >= deadline)
                {
                    frame.Continue = false;
                }
            },
            dispatcher);

        timer.Start();
        Dispatcher.PushFrame(frame);
        timer.Stop();
        return (minOpacity, maxOffset);
    }

    [Fact]
    public async Task CallsignMemoryHintsAppearAfterDebounceWithoutTouchingInputOrRevision()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        MainViewModel? viewModel = null;
        try
        {
            RuntimeOptions.Configure(disableNetwork: true);
            var store = new NativeStore(databasePath);
            await store.InitializeAsync();
            var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 22));
            await SeedCallsignHistoryAsync(store, session);

            viewModel = new MainViewModel(
                new CatalogService(),
                store,
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);
            await viewModel.InitializeAsync();
            if (viewModel.StartupUpdateCheckTask is not null)
            {
                await viewModel.StartupUpdateCheckTask;
            }

            viewModel.SetInputText("BA4RLL");
            var revision = viewModel.InputRevision;

            await WaitUntilAsync(() => viewModel.IsCallsignHintRowVisible, TimeSpan.FromSeconds(5));

            Assert.Equal("BA4RLL", viewModel.Callsign);
            Assert.NotEmpty(viewModel.CallsignHints);
            Assert.StartsWith("上次", viewModel.CallsignMemoryLastTimeDisplay);
            Assert.All(viewModel.CallsignHints, static chip => Assert.Contains(
                chip.Field,
                new[] { FieldKind.Qth, FieldKind.Device, FieldKind.Antenna, FieldKind.Power }));
            Assert.All(viewModel.CallsignHints, static chip => Assert.True(chip.UseCount > 0));

            // 去抖查询只读：输入原文与草稿修订都不变。
            Assert.Equal("BA4RLL", viewModel.InputText);
            Assert.Equal(revision, viewModel.InputRevision);
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            SqliteConnection.ClearAllPools();
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public async Task ApplyingCallsignHintChangesOnlyThatParsedFieldAndUndoRestoresIt()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        MainViewModel? viewModel = null;
        try
        {
            RuntimeOptions.Configure(disableNetwork: true);
            var store = new NativeStore(databasePath);
            await store.InitializeAsync();
            var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 22));
            await SeedCallsignHistoryAsync(store, session);

            viewModel = new MainViewModel(
                new CatalogService(),
                store,
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);
            await viewModel.InitializeAsync();
            if (viewModel.StartupUpdateCheckTask is not null)
            {
                await viewModel.StartupUpdateCheckTask;
            }

            viewModel.SetInputText("BA4RLL");
            await WaitUntilAsync(
                () => viewModel.CallsignHints.Any(static chip => chip.Field == FieldKind.Device),
                TimeSpan.FromSeconds(5));

            var revision = viewModel.InputRevision;
            var chip = viewModel.CallsignHints.First(static item => item.Field == FieldKind.Device);
            Assert.Equal("海能达 PD-780", chip.Value);
            var before = ParsedField(viewModel, FieldKind.Device);
            var untouchedQth = viewModel.Qth;
            var untouchedAntenna = viewModel.Antenna;
            var untouchedPower = viewModel.Power;
            var rowsBefore = await store.LoadRecentAsync(session.Id, 100);

            viewModel.ApplyCallsignHint(chip);

            var applied = ParsedField(viewModel, FieldKind.Device);
            Assert.Equal(chip.Value, applied.Value);
            Assert.Equal("呼号记忆", applied.Source);
            Assert.Equal(chip.Value, viewModel.Device);
            Assert.Equal(untouchedQth, viewModel.Qth);
            Assert.Equal(untouchedAntenna, viewModel.Antenna);
            Assert.Equal(untouchedPower, viewModel.Power);
            Assert.Equal("BA4RLL", viewModel.InputText);
            Assert.Equal(revision, viewModel.InputRevision);
            Assert.True(viewModel.CanUndoCallsignHint);
            Assert.True(viewModel.IsCallsignHintRowVisible);
            Assert.Contains("呼号记忆", viewModel.StatusMessage, StringComparison.Ordinal);

            // 应用提示不得写入新记录。
            var rowsAfter = await store.LoadRecentAsync(session.Id, 100);
            Assert.Equal(rowsBefore.Count, rowsAfter.Count);

            viewModel.UndoCallsignHint();

            var restored = ParsedField(viewModel, FieldKind.Device);
            Assert.Equal(before.Value, restored.Value);
            Assert.Equal(before.Source, restored.Source);
            Assert.False(viewModel.CanUndoCallsignHint);
            Assert.Equal("BA4RLL", viewModel.InputText);
            Assert.Equal(revision, viewModel.InputRevision);
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            SqliteConnection.ClearAllPools();
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public async Task ChangingInputRevisionClearsAppliedCallsignHintOverride()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        var databasePath = Path.Combine(root, "data", "ham_checkin_native.db");
        Directory.CreateDirectory(root);
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        MainViewModel? viewModel = null;
        try
        {
            RuntimeOptions.Configure(disableNetwork: true);
            var store = new NativeStore(databasePath);
            await store.InitializeAsync();
            var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 22));
            await SeedCallsignHistoryAsync(store, session);

            viewModel = new MainViewModel(
                new CatalogService(),
                store,
                catalogDataRoot: Path.Combine(root, "data"),
                importLegacyDatabase: false);
            await viewModel.InitializeAsync();
            if (viewModel.StartupUpdateCheckTask is not null)
            {
                await viewModel.StartupUpdateCheckTask;
            }

            viewModel.SetInputText("BA4RLL");
            await WaitUntilAsync(
                () => viewModel.CallsignHints.Any(static chip => chip.Field == FieldKind.Device),
                TimeSpan.FromSeconds(5));

            var chip = viewModel.CallsignHints.First(static item => item.Field == FieldKind.Device);
            viewModel.ApplyCallsignHint(chip);
            Assert.True(viewModel.CanUndoCallsignHint);
            Assert.Equal("呼号记忆", ParsedField(viewModel, FieldKind.Device).Source);

            viewModel.SetInputText("BA4RLL 5W");

            Assert.True(viewModel.InputRevision > 0);
            Assert.Equal("BA4RLL 5W", viewModel.InputText);
            Assert.False(viewModel.CanUndoCallsignHint);
            Assert.NotEqual("呼号记忆", ParsedField(viewModel, FieldKind.Device).Source);
            Assert.NotEqual(chip.Value, ParsedField(viewModel, FieldKind.Device).Value);
        }
        finally
        {
            if (viewModel is not null)
            {
                await viewModel.DisposeAsync();
            }
            SqliteConnection.ClearAllPools();
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [Fact]
    public void CallsignMemoryStripExistsInVisualTreeAtReducedOpacity()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 1_440,
                Height = 900,
                Content = view,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false
            };
            window.Show();
            window.UpdateLayout();
            view.UpdateLayout();

            var strip = view.FindName("CallsignMemoryStrip") as Grid;
            Assert.NotNull(strip);
            Assert.Equal(0.62, strip!.Opacity, 3);
            Assert.False(viewModel.IsCallsignHintRowVisible);
            Assert.Equal(Visibility.Collapsed, strip.Visibility);

            window.Close();
        });
    }

    [Fact]
    public void QuickWindowCompactHeightHidesMemoryRowAndKeepsInputAndSubmitVisible()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var window = new QuickWindow
            {
                Width = 560,
                Height = 190,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                DataContext = viewModel
            };
            window.Show();
            window.UpdateLayout();

            var host = (FrameworkElement)window.FindName("CallsignMemoryHost")!;
            var input = (TextBox)window.FindName("QuickInputBox")!;
            var submit = (Button)window.FindName("QuickSubmitButton")!;

            Assert.Equal(Visibility.Collapsed, host.Visibility);
            Assert.True(input.IsVisible);
            Assert.True(input.ActualHeight > 0);
            Assert.True(submit.IsVisible);
            Assert.True(submit.ActualHeight > 0);
            var submitBottom = submit.TranslatePoint(new Point(0, submit.ActualHeight), window).Y;
            Assert.True(
                submitBottom <= window.ActualHeight + 0.5,
                $"提交按钮底边 {submitBottom} 超出快捷窗口高度 {window.ActualHeight}");

            window.Close();
        });
    }

    [Fact]
    public void AboutXamlNoLongerContainsTheRemovedSubtitleLine()
    {
        var path = LocateRepoFile(Path.Combine(
            "native", "src", "HamCheckin.Native.App", "Views", "AboutWindow.xaml"));
        var xaml = File.ReadAllText(path);

        Assert.Contains("about-developer", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("快速、离线、键盘优先", xaml, StringComparison.Ordinal);
        Assert.DoesNotContain("Windows 原生版 ·", xaml, StringComparison.Ordinal);
    }

    [Fact]
    public void AboutWindowRendersWithoutTheRemovedSubtitleLine()
    {
        _fixture.Run(() =>
        {
            var window = new AboutWindow();
            window.Show();
            window.UpdateLayout();

            var texts = VisualDescendants(window)
                .OfType<TextBlock>()
                .Select(static block => block.Text)
                .ToArray();
            Assert.Contains(texts, static text => text.Contains("开发者", StringComparison.Ordinal));
            Assert.DoesNotContain(texts, static text => text.Contains("键盘优先", StringComparison.Ordinal));
            Assert.DoesNotContain(texts, static text => text.Contains("快速、离线", StringComparison.Ordinal));

            window.Close();
        });
    }

    [Fact]
    public async Task QthMemoryHintUndoRestoresSelectedCandidateMarkerAcrossReparse()
    {
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        QthMemoryHarness? harness = null;
        try
        {
            RuntimeOptions.Configure(disableNetwork: true);
            harness = await CreateQthMemoryHarnessAsync();
            var viewModel = harness.ViewModel;

            viewModel.SetInputText("ba4rll bj");
            await WaitUntilAsync(
                () => viewModel.CallsignHints.Any(static chip => chip.Field == FieldKind.Qth),
                TimeSpan.FromSeconds(5));
            viewModel.SelectQthCandidate("北京市");
            var revision = viewModel.InputRevision;
            Assert.Equal("用户选择", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal("北京市", viewModel.Qth);

            var chip = viewModel.CallsignHints.First(static item => item.Field == FieldKind.Qth);
            Assert.NotEqual("北京市", chip.Value);
            viewModel.ApplyCallsignHint(chip);
            Assert.Equal("呼号记忆", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal(chip.Value, viewModel.Qth);
            Assert.Equal("ba4rll bj", viewModel.InputText);

            viewModel.UndoCallsignHint();
            Assert.False(viewModel.CanUndoCallsignHint);
            Assert.Equal("用户选择", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal("北京市", viewModel.Qth);

            // 同一修订的后台重解析必须保住撤销后的显式选择，而不是丢回自动解析值。
            viewModel.ReparseCurrentInputForTesting();
            Assert.Equal(revision, viewModel.InputRevision);
            Assert.Equal("ba4rll bj", viewModel.InputText);
            Assert.Equal("用户选择", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal("北京市", viewModel.Qth);
        }
        finally
        {
            if (harness is not null)
            {
                await harness.DisposeAsync();
            }
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
        }
    }

    [Fact]
    public async Task TwoQthMemoryHintsUndoRestoresOriginalCandidateMarkerAcrossReparse()
    {
        var previousNetworkMode = RuntimeOptions.DisableNetwork;
        QthMemoryHarness? harness = null;
        try
        {
            RuntimeOptions.Configure(disableNetwork: true);
            harness = await CreateQthMemoryHarnessAsync();
            var viewModel = harness.ViewModel;

            viewModel.SetInputText("ba4rll bj");
            await WaitUntilAsync(
                () => viewModel.CallsignHints.Any(static chip => chip.Field == FieldKind.Qth),
                TimeSpan.FromSeconds(5));
            viewModel.SelectQthCandidate("北京市");
            var revision = viewModel.InputRevision;

            var first = viewModel.CallsignHints.First(static item => item.Field == FieldKind.Qth);
            viewModel.ApplyCallsignHint(first);
            Assert.Equal("呼号记忆", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal(first.Value, viewModel.Qth);

            var second = viewModel.CallsignHints.Single(static item => item.Field == FieldKind.Qth);
            Assert.NotEqual(first.Value, second.Value);
            viewModel.ApplyCallsignHint(second);
            Assert.Equal("呼号记忆", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal(second.Value, viewModel.Qth);
            Assert.True(viewModel.CanUndoCallsignHint);

            // 两次 QTH 覆盖合成一条撤销：回到最初的“用户选择”而不是第一次覆盖值。
            viewModel.UndoCallsignHint();
            Assert.False(viewModel.CanUndoCallsignHint);
            Assert.Equal("用户选择", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal("北京市", viewModel.Qth);
            Assert.Equal("ba4rll bj", viewModel.InputText);
            Assert.Equal(revision, viewModel.InputRevision);

            viewModel.ReparseCurrentInputForTesting();
            Assert.Equal("用户选择", ParsedField(viewModel, FieldKind.Qth).Source);
            Assert.Equal("北京市", viewModel.Qth);
        }
        finally
        {
            if (harness is not null)
            {
                await harness.DisposeAsync();
            }
            RuntimeOptions.Configure(disableNetwork: previousNetworkMode);
        }
    }

    private static async Task<QthMemoryHarness> CreateQthMemoryHarnessAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "HAMCheckin.Native.UiTests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var store = new NativeStore(Path.Combine(root, "data", "ham_checkin_native.db"));
        await store.InitializeAsync();
        var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 22));
        await SeedCallsignHistoryAsync(store, session);
        var viewModel = new MainViewModel(
            new CatalogService(),
            store,
            catalogDataRoot: Path.Combine(root, "data"),
            importLegacyDatabase: false);
        await viewModel.InitializeAsync();
        if (viewModel.StartupUpdateCheckTask is not null)
        {
            await viewModel.StartupUpdateCheckTask;
        }

        return new QthMemoryHarness(root, viewModel);
    }

    private sealed class QthMemoryHarness(string root, MainViewModel viewModel) : IAsyncDisposable
    {
        public MainViewModel ViewModel { get; } = viewModel;

        public async ValueTask DisposeAsync()
        {
            await ViewModel.DisposeAsync();
            SqliteConnection.ClearAllPools();
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static async Task SeedCallsignHistoryAsync(NativeStore store, SessionInfo session)
    {
        await store.AddCheckinAsync(session,
            MemoryParse("BA4RLL", "江苏省南京市玄武区", "海能达 PD-780", "4.2米玻璃钢", "5W"));
        await store.AddCheckinAsync(session,
            MemoryParse("BA4RLL", "江苏省南京市玄武区", "海能达 PD-780", "4.2米玻璃钢", "5W"));
        await store.AddCheckinAsync(session,
            MemoryParse("BA4RLL", "江苏省苏州市姑苏区", "宝锋 UV-5RH", "原装天线", "8W"));
    }

    private static ParseResult MemoryParse(
        string callsign,
        string qth,
        string device,
        string antenna,
        string power) => new(
        $"{callsign} {qth} {device} {antenna} {power}".Trim(),
        new[] { callsign },
        MemoryField(callsign),
        MemoryField(qth),
        MemoryField(device),
        MemoryField(antenna),
        MemoryField(power),
        ParseField.Empty,
        Array.Empty<string>());

    private static ParseField MemoryField(string value) =>
        string.IsNullOrWhiteSpace(value)
            ? ParseField.Empty
            : new ParseField(value, "测试", 1.0, value);

    /// <summary>
    /// 读取 MainViewModel 已发布的私有解析快照，验证字段来源。仅测试侧只读反射，
    /// 不向产品代码添加任何测试钩子。
    /// </summary>
    private static ParseField ParsedField(MainViewModel viewModel, FieldKind field)
    {
        var parsed = typeof(MainViewModel)
            .GetField("_parseResult", BindingFlags.Instance | BindingFlags.NonPublic)
            ?.GetValue(viewModel) as ParseResult
            ?? throw new InvalidOperationException("MainViewModel 未持有解析快照。");

        return field switch
        {
            FieldKind.Qth => parsed.Qth,
            FieldKind.Device => parsed.Device,
            FieldKind.Antenna => parsed.Antenna,
            FieldKind.Power => parsed.Power,
            _ => throw new ArgumentOutOfRangeException(nameof(field), field, "呼号记忆只覆盖 QTH/设备/天线/功率")
        };
    }

    private static async Task WaitUntilAsync(Func<bool> condition, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (!condition() && DateTime.UtcNow < deadline)
        {
            await Task.Delay(20);
        }

        Assert.True(condition(), $"条件在 {timeout} 内未满足。");
    }

    private static string LocateRepoFile(string relativePath)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, relativePath);
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new FileNotFoundException("找不到仓库文件。", relativePath);
    }

    private static IEnumerable<DependencyObject> VisualDescendants(DependencyObject root)
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            yield return child;
            foreach (var descendant in VisualDescendants(child))
            {
                yield return descendant;
            }
        }
    }

    private static void PumpDispatcherUntil(Func<bool> condition, TimeSpan timeout)
    {
        var dispatcher = Dispatcher.CurrentDispatcher;
        var frame = new DispatcherFrame();
        var deadline = DateTime.UtcNow + timeout;
        var timer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(10),
            DispatcherPriority.Background,
            (_, _) =>
            {
                if (condition() || DateTime.UtcNow >= deadline)
                {
                    frame.Continue = false;
                }
            },
            dispatcher);

        timer.Start();
        Dispatcher.PushFrame(frame);
        timer.Stop();
    }

    private static Vector PageOffset(FrameworkElement page)
    {
        if (page.RenderTransform is null)
        {
            return default;
        }

        if (page.RenderTransform is TranslateTransform translate)
        {
            return new Vector(translate.X, translate.Y);
        }

        var point = page.RenderTransform.Transform(default(Point));
        return new Vector(point.X, point.Y);
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

    private static void RequireHardwareAuthorization()
    {
        if (!string.Equals(
                Environment.GetEnvironmentVariable("HAM_CHECKIN_NATIVE_HARDWARE_TEST"),
                "1",
                StringComparison.Ordinal))
        {
            throw Xunit.Sdk.SkipException.ForSkip(
                "Hardware tests require explicit local authorization with HAM_CHECKIN_NATIVE_HARDWARE_TEST=1.");
        }
    }

    private static async Task<IReadOnlyList<MicrophoneDevice>> EnumerateMicrophonesAsync()
    {
        var enumeration = Task.Run(MicrophoneCapture.EnumerateDevices);
        try
        {
            return await enumeration.WaitAsync(HardwareProbeTimeout);
        }
        catch (TimeoutException exception)
        {
            throw new TimeoutException(
                "Microphone enumeration exceeded 10 seconds; the native device probe cannot be canceled.",
                exception);
        }
    }
}

public sealed class WpfDispatcherFixture : IDisposable
{
    private static readonly TimeSpan ReadyTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan InvokeTimeout = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan ShutdownTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan JoinTimeout = TimeSpan.FromSeconds(10);
    private readonly Thread _thread;
    private readonly ManualResetEventSlim _ready = new();
    private volatile Dispatcher? _dispatcher;
    private NativeApplication? _app;
    private ThemeService? _themeService;
    private Exception? _startupFailure;
    private int _startupAbandoned;

    public WpfDispatcherFixture()
    {
        _thread = new Thread(() =>
        {
            try
            {
                _app = new NativeApplication
                {
                    ShutdownMode = ShutdownMode.OnExplicitShutdown
                };
                _app.InitializeComponent();
                _themeService = new ThemeService();
                _themeService.ApplyEffectiveTheme(EffectiveTheme.Light);
            }
            catch (Exception exception)
            {
                _startupFailure = exception;
                _ready.Set();
                return;
            }

            _dispatcher = Dispatcher.CurrentDispatcher;
            _ready.Set();
            if (Volatile.Read(ref _startupAbandoned) != 0)
            {
                _app.Shutdown();
                return;
            }

            Dispatcher.Run();
        });
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.IsBackground = true;
        _thread.Start();
        if (!_ready.Wait(ReadyTimeout))
        {
            Interlocked.Exchange(ref _startupAbandoned, 1);
            _dispatcher?.BeginInvokeShutdown(DispatcherPriority.Normal);
            if (_thread.Join(JoinTimeout)) _ready.Dispose();
            throw new TimeoutException("WPF Dispatcher did not become ready within 10 seconds.");
        }

        if (_startupFailure is not null)
        {
            if (!_thread.Join(JoinTimeout))
            {
                throw new TimeoutException("WPF Dispatcher startup failed but its thread did not stop within 10 seconds.", _startupFailure);
            }

            _ready.Dispose();
            throw new InvalidOperationException("WPF Dispatcher startup failed.", _startupFailure);
        }
    }

    public void Run(Action action)
    {
        if (_dispatcher is null)
        {
            throw new InvalidOperationException("WPF Dispatcher 未启动。");
        }
        var operation = _dispatcher.BeginInvoke(DispatcherPriority.Normal, action);
        WaitForOperation(operation, InvokeTimeout, "invoke");
    }

    public void Dispose()
    {
        try
        {
            var dispatcher = _dispatcher;
            if (dispatcher is not null)
            {
                var shutdown = dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() =>
                {
                    _themeService?.Dispose();
                    _themeService = null;
                    _app?.Shutdown();
                    dispatcher.BeginInvokeShutdown(DispatcherPriority.Normal);
                }));
                WaitForOperation(shutdown, ShutdownTimeout, "shutdown");
            }

            if (!_thread.Join(JoinTimeout))
            {
                throw new TimeoutException("WPF Dispatcher thread did not stop within 10 seconds.");
            }
        }
        finally
        {
            _ready.Dispose();
        }
    }

    private static void WaitForOperation(DispatcherOperation operation, TimeSpan timeout, string operationName)
    {
        try
        {
            operation.Task.WaitAsync(timeout).GetAwaiter().GetResult();
        }
        catch (TimeoutException) when (!operation.Task.IsCompleted)
        {
            operation.Abort();
            throw new TimeoutException($"WPF Dispatcher {operationName} timed out after {timeout.TotalSeconds:0} seconds.");
        }
    }
}

internal sealed class UpdateProbeHandler : HttpMessageHandler
{
    private const string ManifestDownload =
        "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.17/HAM.exe";

    public List<string> Requests { get; } = new();

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var url = request.RequestUri?.AbsoluteUri ?? string.Empty;
        Requests.Add(url);
        if (url == NativeVersion.StableApiUrl)
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }

        if (url == NativeVersion.StableManifestUrl)
        {
            var json = $"{{\"version\":\"1.0.17\",\"tag_name\":\"v1.0.17\",\"download_url\":\"{ManifestDownload}\",\"sha256\":\"{new string('a', 64)}\"}}";
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json")
            });
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
    }
}
