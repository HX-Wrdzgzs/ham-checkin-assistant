using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using HamCheckin.Native.Core.Storage;
using HamCheckin.Native.Core.Updates;

namespace HamCheckin.Native.App.Views;

public partial class AboutWindow : Window, IDisposable
{
    private readonly NativeUpdateService _updates;
    private NativeReleaseInfo? _availableRelease;
    private CancellationTokenSource? _operationCancellation;

    public AboutWindow(NativeUpdateService? updates = null)
    {
        InitializeComponent();
        _updates = updates ?? new NativeUpdateService();
        CurrentVersionText.Text = NativeVersion.Current;
        DataPathText.Text = $"数据目录：{AppPaths.Root}";
        ReleaseNotesText.Text = "当前未读取云端更新说明。\n\n程序进入可录入状态后会在后台检查更新；按钮可以立即重试。更新检查不进入录入热路径。";
        Closed += (_, _) => Dispose();
    }

    public void SetPreviewState()
    {
        StatusText.Text = $"云端版本：{NativeVersion.Current}（当前已是最新）";
        ReleaseNotesText.Text = "1.0.18 本地候选版更新内容\n\n"
            + "· 修复主窗口和快捷小窗在前部/中部修改时覆盖后缀的问题\n"
            + "· 解析结果只显示预览，不回写正在输入的原文\n"
            + "· 扩展全国省、市、区县缩写；未知尾缀单独保留待修正，不擅自猜测\n"
            + "· 增加视频样例回归：7900、jsycxs、bh8、山东qcd、广东省汕头市m507\n"
            + "· 启动后后台检查更新，输入热路径不连接 Excel 或联网资料库\n"
            + "· 保持 C# / WPF / .NET 10 自包含发布和 MP4 软件窗口录屏能力";
        CheckButton.IsEnabled = true;
        DownloadButton.IsEnabled = false;
    }

    private async void CheckButton_Click(object sender, RoutedEventArgs e)
    {
        if (_operationCancellation is not null)
        {
            return;
        }

        using var operation = new CancellationTokenSource();
        _operationCancellation = operation;
        CheckButton.IsEnabled = false;
        DownloadButton.IsEnabled = false;
        StatusText.Text = "正在读取 GitHub Release 信息…";
        try
        {
            var release = await _updates.FetchLatestAsync(operation.Token);
            _availableRelease = NativeUpdateService.IsNewer(release.Version, NativeVersion.Current)
                ? release
                : null;
            if (_availableRelease is null)
            {
                if (NativeUpdateService.IsNewer(NativeVersion.Current, release.Version))
                {
                    StatusText.Text = $"本地版本 {NativeVersion.Current} 高于云端公开版本 {release.TagName}，没有可用更新。";
                    ReleaseNotesText.Text = $"云端公开清单仍是旧版本 {release.TagName}。\n\n"
                        + $"本地版本：{NativeVersion.Current}\n"
                        + $"云端版本：{release.Version}\n\n"
                        + "旧版本更新说明已隐藏，避免把旧版 Markdown 内容误显示成当前版本说明。";
                }
                else
                {
                    StatusText.Text = $"云端版本：{release.TagName}（当前已是最新）";
                    ReleaseNotesText.Text = FormatReleaseNotes(release.ReleaseNotes);
                }
            }
            else
            {
                StatusText.Text = $"发现新版本：{_availableRelease.TagName}，已通过下载地址和 SHA-256 合同检查。";
                ReleaseNotesText.Text = FormatReleaseNotes(release.ReleaseNotes);
                DownloadButton.IsEnabled = true;
            }
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "版本检查已取消。";
        }
        catch (Exception exception)
        {
            StatusText.Text = $"检查更新失败：{exception.Message}";
            ReleaseNotesText.Text = "未修改本地数据，也没有下载或替换程序。\n\n可以稍后重试。";
        }
        finally
        {
            if (ReferenceEquals(_operationCancellation, operation))
            {
                _operationCancellation = null;
            }
            CheckButton.IsEnabled = true;
        }
    }

    private async void DownloadButton_Click(object sender, RoutedEventArgs e)
    {
        if (_availableRelease is null || _operationCancellation is not null)
        {
            return;
        }

        using var operation = new CancellationTokenSource();
        _operationCancellation = operation;
        CheckButton.IsEnabled = false;
        DownloadButton.IsEnabled = false;
        DownloadProgress.Visibility = Visibility.Visible;
        DownloadProgress.Value = 0;
        StatusText.Text = $"正在下载 {_availableRelease.TagName} 并校验 SHA-256…";
        try
        {
            var artifact = await _updates.DownloadAsync(
                _availableRelease,
                new Progress<double>(value => DownloadProgress.Value = value),
                operation.Token);
            var script = NativeUpdateInstaller.Schedule(artifact.Path);
            StatusText.Text = "校验通过。程序将在关闭后替换并重新启动。";
            ReleaseNotesText.Text = $"已下载 {artifact.Length:N0} bytes\nSHA-256：{artifact.Sha256}\n\n更新脚本已准备：{script}";
            await Task.Delay(450);
            Application.Current.Shutdown(0);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "下载已取消；当前程序未修改。";
        }
        catch (Exception exception)
        {
            StatusText.Text = $"下载或安装失败：{exception.Message}";
            DownloadButton.IsEnabled = true;
        }
        finally
        {
            DownloadProgress.Visibility = Visibility.Collapsed;
            if (ReferenceEquals(_operationCancellation, operation))
            {
                _operationCancellation = null;
            }
            CheckButton.IsEnabled = true;
        }
    }

    private void OpenReleaseButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var url = _availableRelease?.HtmlUrl
                ?? $"https://github.com/{NativeVersion.Repository}/releases";
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        }
        catch (Exception exception)
        {
            StatusText.Text = $"无法打开 Release 页面：{exception.Message}";
        }
    }

    private void OpenSponsorButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo(NativeVersion.SponsorUrl) { UseShellExecute = true });
        }
        catch (Exception exception)
        {
            StatusText.Text = $"无法打开赞助页面：{exception.Message}";
        }
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();

    public static string FormatReleaseNotes(string? markdown)
    {
        if (string.IsNullOrWhiteSpace(markdown))
        {
            return "该 Release 没有附带更新说明。";
        }

        var builder = new StringBuilder();
        foreach (var rawLine in markdown.Replace("\r\n", "\n").Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.Length == 0)
            {
                if (builder.Length > 0 && !builder.ToString().EndsWith("\n\n", StringComparison.Ordinal))
                {
                    builder.AppendLine();
                }
                continue;
            }

            line = Regex.Replace(line, @"^#{1,6}\s*", string.Empty);
            line = Regex.Replace(line, @"\[([^\]]+)\]\([^\)]+\)", "$1");
            line = line.Replace("**", string.Empty).Replace("__", string.Empty).Replace("`", string.Empty);
            line = Regex.Replace(line, @"^[-*+]\s+", "· ");
            builder.AppendLine(line);
        }

        return builder.ToString().Trim();
    }

    public void Dispose()
    {
        _operationCancellation?.Cancel();
        _operationCancellation?.Dispose();
        _operationCancellation = null;
        GC.SuppressFinalize(this);
    }
}

internal static class NativeUpdateInstaller
{
    private const string Script = """
        @echo off
        setlocal EnableExtensions
        set "SRC=%~1"
        set "DST=%~2"
        set "PID=%~3"
        :wait_for_app
        tasklist /FI "PID eq %PID%" 2>nul | findstr /R /C:" %PID% " >nul
        if not errorlevel 1 (
          timeout /t 1 /nobreak >nul
          goto wait_for_app
        )
        copy /Y "%SRC%" "%DST%.new" >nul
        if errorlevel 1 exit /b 1
        move /Y "%DST%.new" "%DST%" >nul
        if errorlevel 1 exit /b 1
        start "" "%DST%"
        del /Q "%SRC%" >nul 2>&1
        del /Q "%~f0" >nul 2>&1
        """;

    public static string Schedule(string downloadedPath)
    {
        var target = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(target) || !File.Exists(downloadedPath))
        {
            throw new InvalidOperationException("当前程序路径或下载文件无效，未执行替换。");
        }
        if (!string.Equals(Path.GetExtension(target), ".exe", StringComparison.OrdinalIgnoreCase)
            || string.Equals(Path.GetFileName(target), "dotnet.exe", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("当前是开发运行环境，不能自动替换 dotnet 进程；请在发布版 HAM.exe 中执行更新。");
        }

        var scriptPath = Path.Combine(
            Path.GetTempPath(), $"ham-checkin-native-update-{Environment.ProcessId}-{Guid.NewGuid():N}.cmd");
        File.WriteAllText(scriptPath, Script, System.Text.Encoding.ASCII);
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
                Arguments = $"/d /c \"{scriptPath}\" \"{downloadedPath}\" \"{target}\" {Environment.ProcessId}",
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            });
            return scriptPath;
        }
        catch
        {
            File.Delete(scriptPath);
            throw;
        }
    }
}
