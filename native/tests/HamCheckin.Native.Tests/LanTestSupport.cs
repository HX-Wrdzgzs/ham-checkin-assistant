using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Lan;

namespace HamCheckin.Native.Tests;

/// <summary>
/// S2 LAN 测试共用夹具：可变的当前场次快照、JSON 请求帮助方法与合成解析结果。
/// 全部测试只在回环地址上运行，不接触私网、生产库或真实设备。
/// </summary>
internal sealed class MutableLanSessionSource : ILanSessionSource
{
    public MutableLanSessionSource(LanSessionSnapshot? currentSession) =>
        CurrentSession = currentSession;

    public LanSessionSnapshot? CurrentSession { get; set; }
}

internal static class LanTestJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    public static HttpRequestMessage JsonRequest<T>(
        HttpMethod method,
        string path,
        T payload,
        string? token = null)
    {
        var request = new HttpRequestMessage(method, path)
        {
            Content = JsonContent.Create(payload, options: Options)
        };
        if (!string.IsNullOrEmpty(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return request;
    }

    public static Task<HttpResponseMessage> PostAsync<T>(
        HttpClient client,
        string path,
        T payload,
        string? token = null) =>
        client.SendAsync(JsonRequest(HttpMethod.Post, path, payload, token));

    public static async Task<T?> ReadAsync<T>(HttpResponseMessage response) =>
        await response.Content.ReadFromJsonAsync<T>(Options);
}

internal static class LanTestData
{
    public static ParseResult Parsed(string callsign = "BA4RLL") => new(
        $"{callsign} njxw",
        new[] { callsign },
        Field(callsign),
        Field("南京玄武"),
        ParseField.Empty,
        ParseField.Empty,
        ParseField.Empty,
        ParseField.Empty,
        Array.Empty<string>());

    private static ParseField Field(string value) => new(value, "测试", 1.0, value);
}
