using System.Net;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.IO;
using System.Text;
using NativeApplication = HamCheckin.Native.App.App;
using HamCheckin.Native.App.Media;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.App.Views;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.Core.Updates;
using Microsoft.Data.Sqlite;
using Xunit;

namespace HamCheckin.Native.UiTests;

public sealed class QuickInputUiTests : IClassFixture<WpfDispatcherFixture>
{
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

            Assert.True(quick.ActualWidth >= quick.MinWidth);
            Assert.True(quick.ActualHeight >= quick.MinHeight);
            Assert.Equal(Visibility.Collapsed, recent.Visibility);
            Assert.True(input.IsVisible);
            Assert.True(input.ActualWidth >= 180);
            Assert.True(input.ActualHeight >= 30);
            Assert.True(submit.IsVisible);
            Assert.True(submit.ActualWidth >= 60);
            Assert.Equal(Original, input.Text);

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

            Assert.Equal("1.0.15", version.Text);
            Assert.Equal("开发者：BA4THG（HX-Wrdzgzs）", developer.Text);
            Assert.Contains("当前已是最新", status.Text);
            Assert.Contains("本地候选版", notes.Text);
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

                        stopFrame.Continue = false;
                    }));
                }, TaskScheduler.Default);
                Dispatcher.PushFrame(stopFrame);
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

internal sealed class UpdateProbeHandler : HttpMessageHandler
{
    private const string ManifestDownload =
        "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v1.0.15/HAM.exe";

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
            var json = $"{{\"version\":\"1.0.15\",\"tag_name\":\"v1.0.15\",\"download_url\":\"{ManifestDownload}\",\"sha256\":\"{new string('a', 64)}\"}}";
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json")
            });
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
    }
}
