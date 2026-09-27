using System.Diagnostics;
using System.IO;
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
        ReleaseNotesText.Text = "当前未读取云端更新说明。\n\n检查更新只在点击按钮后运行，不进入启动和录入热路径。";
        Closed += (_, _) => Dispose();
    }

    public void SetPreviewState()
    {
        StatusText.Text = "云端最新版本：1.0.0（当前已是最新）";
        ReleaseNotesText.Text = "稳定版\n\n· Native WPF / .NET 10\n· SQLite 现场提交\n· Excel 后台导出\n· 本地资料库和 SHA-256 更新校验";
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
            ReleaseNotesText.Text = string.IsNullOrWhiteSpace(release.ReleaseNotes)
                ? "该 Release 没有附带更新说明。"
                : release.ReleaseNotes;
            if (_availableRelease is null)
            {
                StatusText.Text = $"云端最新版本：{release.TagName}（当前已是最新）";
            }
            else
            {
                StatusText.Text = $"发现新版本：{_availableRelease.TagName}，已通过下载地址和 SHA-256 合同检查。";
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

    private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();

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
