using HamCheckin.Native.LanServer;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 手机页静态契约（无 JS 测试运行器）：待确认原文在拒绝、过期与 401 重新
/// 配对路径上必须保留并回填，不能在终态页面丢失草稿。
/// </summary>
public sealed class LanMobileScriptContractTests
{
    [Fact]
    public void PendingRawIsPreservedOnRejectedExpiredAndTokenInvalidPaths()
    {
        var script = ReadAsset("HamCheckin.Native.LanServer.Assets.app.js");

        Assert.Contains("state.pendingRaw = rawText;", script, StringComparison.Ordinal);
        Assert.Equal(
            2,
            CountOccurrences(script, "dom.rejectedRaw.textContent = state.pendingRaw;"));
        Assert.Contains("if (error.code === 'token_invalid')", script, StringComparison.Ordinal);
        Assert.Contains("if (state.pendingRaw) {", script, StringComparison.Ordinal);
        Assert.Contains("dom.draft.value = state.pendingRaw;", script, StringComparison.Ordinal);
    }

    private static string ReadAsset(string resourceName)
    {
        using var stream = typeof(LanServerHost).Assembly.GetManifestResourceStream(resourceName);
        Assert.NotNull(stream);
        using var reader = new StreamReader(stream!);
        return reader.ReadToEnd();
    }

    private static int CountOccurrences(string text, string value)
    {
        var count = 0;
        var index = 0;
        while ((index = text.IndexOf(value, index, StringComparison.Ordinal)) >= 0)
        {
            count++;
            index += value.Length;
        }

        return count;
    }
}
