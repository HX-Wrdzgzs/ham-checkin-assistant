using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.App.Views;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Catalogs;
using HamCheckin.Native.Core.Lan;
using HamCheckin.Native.Core.Parsing;
using HamCheckin.Native.Core.Storage;
using Microsoft.Data.Sqlite;
using Xunit;

namespace HamCheckin.Native.UiTests;

/// <summary>
/// S3 手机收件面板验收：显式启停（仅回环）、配对/提交/待确认零写入、
/// 批准后 source=lan 且幂等、Busy/WriteCommitted/场次结束不显示“已确认”，
/// 以及 MainView 的导航、横幅、按钮与收起布局。仅使用临时 SQLite 与 127.0.0.1。
/// </summary>
[Collection("Native WPF application")]
public sealed class LanPanelUiTests
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private static readonly TimeSpan Waited = TimeSpan.FromSeconds(15);

    private readonly WpfDispatcherFixture _fixture;

    public LanPanelUiTests(WpfDispatcherFixture fixture) => _fixture = fixture;

    [Fact]
    public void PanelConstructionDoesNotStartListeningAndLoopbackFlowWritesOnlyAfterApproval()
    {
        RunOnUiThread(async () =>
        {
            var root = NewRoot("lan-panel-flow");
            NativeStore? store = null;
            LanPanelViewModel? panel = null;
            try
            {
                store = new NativeStore(Path.Combine(root, "data", "ham_checkin_native.db"));
                await store.InitializeAsync();
                var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 25));
                var snapshot = new LanSessionSnapshot(session.Id, session.Name, session.Date, session.Status);
                panel = new LanPanelViewModel(CreateParser(), store, () => snapshot);

                // 构造只读取地址候选，绝不监听或启动服务。
                Assert.False(panel.IsRunning);
                Assert.Equal(string.Empty, panel.Url);
                Assert.Equal("未启动", panel.UrlDisplay);
                Assert.Equal(string.Empty, panel.Pin);
                Assert.True(panel.CanStart);
                Assert.False(panel.CanStop);
                Assert.Empty(panel.PendingItems);
                Assert.False(panel.HasPending);

                await panel.StartForTestingAsync(IPAddress.Loopback, 0);

                Assert.True(panel.IsRunning, Describe(panel));
                Assert.False(panel.CanStart);
                Assert.True(panel.CanStop);
                Assert.Matches(@"^http://127\.0\.0\.1:\d+$", panel.Url);
                var port = new Uri(panel.Url).Port;
                Assert.InRange(port, 1, 65535);
                Assert.Matches(@"^\d{6}$", panel.Pin);
                Assert.Equal(panel.Pin, panel.PinDisplay);

                using var http = new HttpClient
                {
                    BaseAddress = new Uri(panel.Url),
                    Timeout = TimeSpan.FromSeconds(15)
                };

                string token;
                using (var pairResponse = await PostJsonAsync(
                    http, "/api/pair", new LanPairRequest(panel.Pin, "回环测试手机")))
                {
                    Assert.Equal(HttpStatusCode.OK, pairResponse.StatusCode);
                    var pair = await pairResponse.Content.ReadFromJsonAsync<LanPairResponse>(JsonOptions);
                    Assert.NotNull(pair);
                    Assert.False(string.IsNullOrWhiteSpace(pair!.Token));
                    token = pair.Token;
                }

                const string clientSubmissionId = "ui-lan-flow-1";
                const string rawText = "ba4rll njxw pd780 4.2m 5w";
                using (var accepted = await PostJsonAsync(
                    http,
                    "/api/submissions",
                    new LanSubmissionRequest(clientSubmissionId, rawText),
                    token))
                {
                    Assert.Equal(HttpStatusCode.Created, accepted.StatusCode);
                }

                await WaitUntilAsync(
                    () => panel.PendingItems.Count == 1,
                    Waited,
                    "手机提交后 PC 待确认列表没有出现条目。");
                var row = panel.PendingItems[0];
                Assert.Equal(clientSubmissionId, row.ClientSubmissionId);
                Assert.Equal(rawText, row.RawText);
                Assert.Equal(1, panel.PendingCount);
                Assert.True(panel.HasPending);

                // 批准之前 SQLite 没有任何记录。
                Assert.Empty(await store.LoadAllForExportAsync(session.Id));

                await panel.ApproveAsync(row);

                var rows = await store.LoadAllForExportAsync(session.Id);
                var saved = Assert.Single(rows);
                Assert.Equal(LanSources.Lan, saved.Source);
                Assert.Equal(session.Id, saved.SessionId);
                Assert.Equal(rawText, saved.RawInput);
                Assert.Equal(1, saved.SequenceNo);
                Assert.Equal(0, panel.PendingCount);
                Assert.Contains("已确认", panel.StatusMessage);

                // 第二次批准不得重复写入，也不得再次显示“已确认”。
                await panel.ApproveAsync(row);
                Assert.Single(await store.LoadAllForExportAsync(session.Id));
                Assert.DoesNotContain("已确认", panel.StatusMessage);
                Assert.Contains("已被处理", panel.StatusMessage);

                await panel.StopAsync();
                Assert.False(panel.IsRunning);
                Assert.Equal(string.Empty, panel.Url);
                Assert.Equal("未启动", panel.UrlDisplay);
                Assert.False(panel.CanStop);
                Assert.Equal(0, panel.PendingCount);
                await WaitForConnectionRefusedAsync(port, TimeSpan.FromSeconds(8));
            }
            finally
            {
                if (panel is not null)
                {
                    await panel.DisposeAsync();
                }

                await CleanupStoreAsync(store, root);
            }
        });
    }

    [Fact]
    public void BusyEndedSessionAndRejectNeverWriteOrReportApproved()
    {
        RunOnUiThread(async () =>
        {
            var root = NewRoot("lan-panel-statuses");
            NativeStore? store = null;
            LanPanelViewModel? panel = null;
            try
            {
                store = new NativeStore(Path.Combine(root, "data", "ham_checkin_native.db"));
                await store.InitializeAsync();
                var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 25));
                var snapshot = new LanSessionSnapshot(session.Id, session.Name, session.Date, session.Status);
                panel = new LanPanelViewModel(CreateParser(), store, () => snapshot);
                await panel.StartForTestingAsync(IPAddress.Loopback, 0);

                using var http = new HttpClient
                {
                    BaseAddress = new Uri(panel.Url),
                    Timeout = TimeSpan.FromSeconds(15)
                };
                var token = await PairAsync(http, panel.Pin);
                const string clientSubmissionId = "ui-lan-statuses-1";
                using (var accepted = await PostJsonAsync(
                    http,
                    "/api/submissions",
                    new LanSubmissionRequest(clientSubmissionId, "ba4rll njxw pd780 4.2m 5w"),
                    token))
                {
                    Assert.Equal(HttpStatusCode.Created, accepted.StatusCode);
                }

                await WaitUntilAsync(
                    () => panel.PendingItems.Count == 1,
                    Waited,
                    "待确认条目未出现在面板。");
                var row = panel.PendingItems[0];

                // 模拟另一次批准仍持有租约：Busy 不写库、不报“已确认”。
                var queue = QueueOf(panel);
                Assert.True(queue.TryBeginApproval(clientSubmissionId, out var lease));
                try
                {
                    await panel.ApproveAsync(row);
                    Assert.Equal("该条正在被处理，请稍候。", panel.StatusMessage);
                    Assert.Equal(string.Empty, panel.ErrorMessage);
                    Assert.False(row.IsBusy);
                    Assert.Empty(await store.LoadAllForExportAsync(session.Id));
                }
                finally
                {
                    queue.ReleaseApproval(clientSubmissionId, lease);
                }

                // 场次结束后：不写库，只提示未写入；条目保持待确认。
                await store.SetSessionStatusAsync(session.Id, "ended");
                await panel.ApproveAsync(row);
                Assert.Contains("场次已结束", panel.ErrorMessage);
                Assert.DoesNotContain("已确认", panel.StatusMessage);
                Assert.Empty(await store.LoadAllForExportAsync(session.Id));
                Assert.Equal(1, panel.PendingCount);

                // 拒绝只改内存队列，不产生 SQLite 行。
                panel.Reject(row);
                Assert.Equal(0, panel.PendingCount);
                Assert.Empty(panel.PendingItems);
                Assert.Equal(0, queue.PendingCount);
                Assert.Empty(await store.LoadAllForExportAsync(session.Id));
            }
            finally
            {
                if (panel is not null)
                {
                    await panel.DisposeAsync();
                }

                await CleanupStoreAsync(store, root);
            }
        });
    }

    [Fact]
    public void WriteCommittedStatusIsNotReportedAsApproved()
    {
        RunOnUiThread(async () =>
        {
            var root = NewRoot("lan-panel-write-committed");
            NativeStore? store = null;
            LanPanelViewModel? panel = null;
            try
            {
                store = new NativeStore(
                    Path.Combine(root, "data", "ham_checkin_native.db"),
                    storeDelayMilliseconds: 3000);
                await store.InitializeAsync();
                var session = await store.GetOrCreateFirstSessionAsync(new DateOnly(2026, 11, 25));
                var snapshot = new LanSessionSnapshot(session.Id, session.Name, session.Date, session.Status);
                panel = new LanPanelViewModel(CreateParser(), store, () => snapshot);
                await panel.StartForTestingAsync(IPAddress.Loopback, 0);

                using var http = new HttpClient
                {
                    BaseAddress = new Uri(panel.Url),
                    Timeout = TimeSpan.FromSeconds(15)
                };
                var token = await PairAsync(http, panel.Pin);
                const string clientSubmissionId = "ui-lan-write-committed";
                using (var accepted = await PostJsonAsync(
                    http,
                    "/api/submissions",
                    new LanSubmissionRequest(clientSubmissionId, "ba4rll njxw pd780 4.2m 5w"),
                    token))
                {
                    Assert.Equal(HttpStatusCode.Created, accepted.StatusCode);
                }

                await WaitUntilAsync(
                    () => panel.PendingItems.Count == 1,
                    Waited,
                    "待确认条目未出现在面板。");
                var row = panel.PendingItems[0];

                var approveTask = panel.ApproveAsync(row);
                var queue = QueueOf(panel);
                await WaitUntilAsync(
                    () => HasApprovalLease(queue, clientSubmissionId),
                    Waited,
                    "批准未取得队列租约，无法模拟写库后服务停止。");

                // 写库仍在延迟中时停止服务：队列被清空，TryApprove 必然失败。
                await panel.StopAsync();
                await approveTask;

                Assert.False(panel.IsRunning);
                Assert.Contains("记录已写入", panel.ErrorMessage);
                Assert.Contains("未能更新", panel.ErrorMessage);
                Assert.DoesNotContain("已确认", panel.StatusMessage);
                Assert.Equal(0, panel.PendingCount);
                // 设计如此：SQLite 已提交的行不回滚，但绝不对操作员报告“已确认”。
                var saved = Assert.Single(await store.LoadAllForExportAsync(session.Id));
                Assert.Equal(LanSources.Lan, saved.Source);
            }
            finally
            {
                if (panel is not null)
                {
                    await panel.DisposeAsync();
                }

                await CleanupStoreAsync(store, root);
            }
        });
    }

    [Fact]
    public void LanNavigationPageAndIdleBannerExistWithoutAutoStart()
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

            try
            {
                window.Show();
                window.UpdateLayout();
                view.UpdateLayout();

                var navigation = (StackPanel)view.FindName("NavigationPanel")!;
                var lanNav = navigation.Children.OfType<RadioButton>()
                    .Single(radio => string.Equals(radio.Tag as string, "Lan", StringComparison.Ordinal));
                Assert.Equal("nav-lan", AutomationProperties.GetAutomationId(lanNav));
                Assert.True(lanNav.IsChecked == false);

                var lanPage = (Grid)view.FindName("LanPage")!;
                Assert.Equal(Visibility.Collapsed, lanPage.Visibility);
                var banner = FindByAutomationId<Button>(view, "lan-pending-banner");
                Assert.Equal(Visibility.Collapsed, banner.Visibility);
                Assert.False(viewModel.LanPanel.IsRunning);
                Assert.Equal(string.Empty, viewModel.LanPanel.Url);

                view.ShowPage("Lan");
                window.UpdateLayout();
                view.UpdateLayout();

                Assert.Equal(Visibility.Visible, lanPage.Visibility);
                Assert.True(lanNav.IsChecked);
                Assert.Equal("Lan", viewModel.CurrentPage);

                var start = FindByAutomationId<Button>(lanPage, "lan-start");
                Assert.False(start.IsEnabled);
                Assert.False(viewModel.LanPanel.CanStart);

                var addressBox = FindByAutomationId<ComboBox>(lanPage, "lan-address");
                Assert.Equal(viewModel.LanPanel.AddressOptions.Count, addressBox.Items.Count);
                if (viewModel.LanPanel.AddressOptions.Count > 0)
                {
                    Assert.Same(viewModel.LanPanel.SelectedAddress, addressBox.SelectedItem);
                }

                // 只是打开页面不会自动启动监听。
                Assert.False(viewModel.LanPanel.IsRunning);
                Assert.Equal(string.Empty, viewModel.LanPanel.Url);
            }
            finally
            {
                view.Dispose();
                window.Close();
            }
        });
    }

    [Fact]
    public void PendingBannerAppearsWithoutFocusStealAndApproveIsNotDefault()
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

            try
            {
                window.Show();
                window.UpdateLayout();
                view.UpdateLayout();

                var input = (TextBox)view.FindName("InputBox")!;
                input.Focus();
                var focusBefore = Keyboard.FocusedElement;

                var parsed = CreateParser().Parse("ba4rll njxw pd780 4.2m 5w");
                Assert.True(parsed.CanSubmit);
                Assert.Equal(
                    LanEnqueueStatus.Created,
                    QueueOf(viewModel.LanPanel).Enqueue("ui-lan-pending-1", parsed).Status);
                InvokeRefreshPendingRows(viewModel.LanPanel);
                window.UpdateLayout();
                view.UpdateLayout();

                Assert.True(viewModel.LanPanel.HasPending);
                Assert.Equal(1, viewModel.LanPanel.PendingCount);
                var banner = FindByAutomationId<Button>(view, "lan-pending-banner");
                Assert.Equal(Visibility.Visible, banner.Visibility);
                Assert.False(banner.Focusable);
                Assert.Same(focusBefore, Keyboard.FocusedElement);

                view.ShowPage("Lan");
                window.UpdateLayout();
                view.UpdateLayout();
                var lanPage = (Grid)view.FindName("LanPage")!;

                var approve = FindByAutomationId<Button>(lanPage, "lan-approve");
                Assert.False(approve.IsDefault);
                Assert.True(approve.IsEnabled);
                Assert.Equal("确认入册", approve.Content);
                var reject = FindByAutomationId<Button>(lanPage, "lan-reject");
                Assert.False(reject.IsDefault);
                Assert.True(reject.IsEnabled);

                // 只有显式点击“确认入册”才进入批准路径；预览模式无写入并明确报错。
                Assert.Equal(string.Empty, viewModel.LanPanel.ErrorMessage);
                approve.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
                Assert.Contains("预览模式不能确认手机记录", viewModel.LanPanel.ErrorMessage);
                Assert.Equal(1, viewModel.LanPanel.PendingCount);
            }
            finally
            {
                view.Dispose();
                window.Close();
            }
        });
    }

    [Fact]
    public void NarrowSidebarCollapsesLanLabelAndDirectSwitchStillWorks()
    {
        _fixture.Run(() =>
        {
            var viewModel = MainViewModel.CreatePreview();
            var view = new MainView { DataContext = viewModel };
            var window = new Window
            {
                Width = 800,
                Height = 600,
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false,
                Content = view
            };

            try
            {
                window.Show();
                window.UpdateLayout();
                view.UpdateLayout();

                var lanLabel = (TextBlock)view.FindName("LanNavLabel")!;
                Assert.Equal(Visibility.Collapsed, lanLabel.Visibility);

                var navigation = (StackPanel)view.FindName("NavigationPanel")!;
                var lanNav = navigation.Children.OfType<RadioButton>()
                    .Single(radio => string.Equals(radio.Tag as string, "Lan", StringComparison.Ordinal));
                Assert.True(lanNav.IsVisible);
                Assert.Equal("nav-lan", AutomationProperties.GetAutomationId(lanNav));

                view.ShowPage("Lan");
                window.UpdateLayout();
                view.UpdateLayout();
                Assert.Equal(Visibility.Visible, ((Grid)view.FindName("LanPage")!).Visibility);
                Assert.True(lanNav.IsChecked);

                window.Width = 1_440;
                window.UpdateLayout();
                view.UpdateLayout();
                Assert.Equal(Visibility.Visible, lanLabel.Visibility);
            }
            finally
            {
                view.Dispose();
                window.Close();
            }
        });
    }

    private void RunOnUiThread(Func<Task> body)
    {
        ExceptionDispatchInfo? failure = null;
        try
        {
            _fixture.Run(() =>
            {
                var dispatcher = Dispatcher.CurrentDispatcher;
                var previous = SynchronizationContext.Current;
                SynchronizationContext.SetSynchronizationContext(
                    new DispatcherSynchronizationContext(dispatcher));
                try
                {
                    var task = body();
                    PumpUntil(() => task.IsCompleted, TimeSpan.FromSeconds(60), dispatcher);
                    task.GetAwaiter().GetResult();
                }
                catch (Exception exception)
                {
                    // 断言失败必须回到 xUnit 线程：让异常逃出 Dispatcher 会终止测试宿主。
                    failure = ExceptionDispatchInfo.Capture(exception);
                }
                finally
                {
                    SynchronizationContext.SetSynchronizationContext(previous);
                }
            });
        }
        catch (Exception exception) when (failure is null)
        {
            throw new InvalidOperationException("WPF 调度器无法执行测试主体。", exception);
        }

        failure?.Throw();
    }

    private static string Describe(LanPanelViewModel panel) =>
        $"IsRunning={panel.IsRunning}; IsAvailable={panel.IsAvailable}; IsBusy={panel.IsBusy}; " +
        $"Url='{panel.Url}'; Status='{panel.StatusMessage}'; Error='{panel.ErrorMessage}'";

    private static void PumpUntil(Func<bool> completed, TimeSpan timeout, Dispatcher dispatcher)
    {
        var stopwatch = Stopwatch.StartNew();
        while (!completed())
        {
            if (stopwatch.Elapsed > timeout)
            {
                throw new TimeoutException($"WPF 调度器等待超过 {timeout.TotalSeconds:0} 秒。");
            }

            var frame = new DispatcherFrame();
            var timer = new DispatcherTimer(DispatcherPriority.Send, dispatcher)
            {
                Interval = TimeSpan.FromMilliseconds(20)
            };
            timer.Tick += (_, _) =>
            {
                if (completed() || stopwatch.Elapsed > timeout)
                {
                    timer.Stop();
                    frame.Continue = false;
                }
            };
            timer.Start();
            try
            {
                Dispatcher.PushFrame(frame);
            }
            finally
            {
                timer.Stop();
            }
        }
    }

    private static async Task WaitUntilAsync(Func<bool> predicate, TimeSpan timeout, string message)
    {
        var stopwatch = Stopwatch.StartNew();
        while (!predicate())
        {
            if (stopwatch.Elapsed > timeout)
            {
                Assert.Fail(message);
            }

            await Task.Delay(25);
        }
    }

    private static async Task WaitForConnectionRefusedAsync(int port, TimeSpan timeout)
    {
        var stopwatch = Stopwatch.StartNew();
        while (true)
        {
            using var client = new TcpClient();
            try
            {
                await client.ConnectAsync(IPAddress.Loopback, port);
            }
            catch (SocketException)
            {
                return;
            }

            if (stopwatch.Elapsed > timeout)
            {
                Assert.Fail($"停止服务后 127.0.0.1:{port} 仍在接受连接。");
            }

            await Task.Delay(50);
        }
    }

    private static InputParser CreateParser() => new(CatalogLoader.CreateBuiltIn());

    private static string NewRoot(string name)
    {
        var root = Path.Combine(
            Path.GetTempPath(), "HAMCheckin.Native.UiTests", $"{name}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private static async Task CleanupStoreAsync(NativeStore? store, string root)
    {
        if (store is not null)
        {
            await store.DisposeAsync();
        }

        SqliteConnection.ClearAllPools();
        if (Directory.Exists(root))
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task<string> PairAsync(HttpClient http, string pin)
    {
        using var response = await PostJsonAsync(
            http, "/api/pair", new LanPairRequest(pin, "回环测试手机"));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var pair = await response.Content.ReadFromJsonAsync<LanPairResponse>(JsonOptions);
        Assert.NotNull(pair);
        return pair!.Token;
    }

    private static Task<HttpResponseMessage> PostJsonAsync<T>(
        HttpClient client,
        string path,
        T payload,
        string? token = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = JsonContent.Create(payload, options: JsonOptions)
        };
        if (!string.IsNullOrEmpty(token))
        {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue(
                "Bearer", token);
        }

        return client.SendAsync(request);
    }

    private static LanPendingQueue QueueOf(LanPanelViewModel panel) =>
        (LanPendingQueue)typeof(LanPanelViewModel)
            .GetField("_queue", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(panel)!;

    private static void InvokeRefreshPendingRows(LanPanelViewModel panel) =>
        typeof(LanPanelViewModel)
            .GetMethod("RefreshPendingRows", BindingFlags.NonPublic | BindingFlags.Instance)!
            .Invoke(panel, null);

    private static bool HasApprovalLease(LanPendingQueue queue, string clientSubmissionId)
    {
        var leases = typeof(LanPendingQueue)
            .GetField("_leases", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(queue)!;
        return ((IDictionary)leases).Contains(clientSubmissionId);
    }

    private static T FindByAutomationId<T>(DependencyObject root, string automationId)
        where T : DependencyObject
    {
        foreach (var descendant in Descendants(root))
        {
            if (descendant is T typed
                && string.Equals(
                    AutomationProperties.GetAutomationId(descendant),
                    automationId,
                    StringComparison.Ordinal))
            {
                return typed;
            }
        }

        throw new InvalidOperationException($"未找到 AutomationId={automationId} 的 {typeof(T).Name}。");
    }

    private static IEnumerable<DependencyObject> Descendants(DependencyObject root)
    {
        var count = VisualTreeHelper.GetChildrenCount(root);
        for (var index = 0; index < count; index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            yield return child;
            foreach (var descendant in Descendants(child))
            {
                yield return descendant;
            }
        }
    }
}
