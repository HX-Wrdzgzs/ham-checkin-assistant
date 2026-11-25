using HamCheckin.Native.Core.Lan;

namespace HamCheckin.Native.Tests;

/// <summary>
/// 配对与令牌契约（设计 3.3）：6 位 PIN、内存只存令牌摘要、12 小时空闲失效、
/// 单令牌撤销、全部撤销与 PIN 轮换。时钟注入，不等待真实时间。
/// </summary>
public sealed class LanAuthStoreTests
{
    private static readonly DateTimeOffset Start =
        new(2026, 11, 25, 9, 30, 0, TimeSpan.FromHours(8));

    [Fact]
    public void PinIsSixDigitsAndVerificationRejectsWrongOrMalformedValues()
    {
        var auth = new LanAuthStore(() => Start);

        Assert.Matches("^[0-9]{6}$", auth.Pin);
        Assert.True(auth.VerifyPin(auth.Pin));
        Assert.True(auth.VerifyPin($" {auth.Pin} "));
        Assert.False(auth.VerifyPin(WrongPin(auth.Pin)));
        Assert.False(auth.VerifyPin("12345"));
        Assert.False(auth.VerifyPin("abcdef"));
        Assert.False(auth.VerifyPin(""));
        Assert.False(auth.VerifyPin(null));
    }

    [Fact]
    public void IssuedTokenIsOpaqueAndValidatesWithRefreshedLastSeen()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));

        var issue = auth.IssueToken("  测试手机  ");
        Assert.Equal(43, issue.Token.Length);
        Assert.StartsWith("phone-", issue.Session.PhoneId);
        Assert.Equal("测试手机", issue.Session.DeviceLabel);

        var validated = auth.Validate(issue.Token);
        Assert.NotNull(validated);
        Assert.Equal(issue.Session.PhoneId, validated!.PhoneId);

        now = Start.AddHours(11);
        Assert.NotNull(auth.Validate(issue.Token));
        now = Start.AddHours(22).AddMinutes(59);
        var refreshed = auth.Validate(issue.Token);
        Assert.NotNull(refreshed);
        Assert.Equal(now, refreshed!.LastSeenAt);
    }

    [Fact]
    public void TokenExpiresAfterTwelveIdleHoursAndCannotBeReused()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));
        var token = auth.IssueToken("手机").Token;

        now = Start.AddHours(12);

        Assert.Null(auth.Validate(token));
        Assert.Null(auth.Validate(token));
    }

    [Fact]
    public void RevokeAndRevokeAllInvalidateOnlyTheTargetedTokens()
    {
        var auth = new LanAuthStore(() => Start);
        var first = auth.IssueToken("手机一").Token;
        var second = auth.IssueToken("手机二").Token;

        auth.Revoke(first);

        Assert.Null(auth.Validate(first));
        Assert.NotNull(auth.Validate(second));

        auth.Revoke(null);
        auth.Revoke("   ");
        auth.RevokeAll();

        Assert.Null(auth.Validate(second));
    }

    [Fact]
    public void RotatePinInvalidatesEveryExistingToken()
    {
        var auth = new LanAuthStore(() => Start);
        var oldPin = auth.Pin;
        var token = auth.IssueToken("手机").Token;

        auth.RotatePin();

        Assert.Null(auth.Validate(token));
        Assert.Matches("^[0-9]{6}$", auth.Pin);
        Assert.True(auth.VerifyPin(auth.Pin));
        Assert.Equal(oldPin == auth.Pin, auth.VerifyPin(oldPin));
    }

    [Fact]
    public void ConnectedSessionsListByActivityAndRevokeByPhoneId()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));
        var first = auth.IssueToken("手机一");
        now = Start.AddMinutes(1);
        var second = auth.IssueToken("手机二");

        Assert.Equal(2, auth.ConnectedCount);
        var sessions = auth.GetActiveSessions();
        Assert.Equal(2, sessions.Count);
        Assert.Equal(second.Session.PhoneId, sessions[0].PhoneId);
        Assert.Equal(first.Session.PhoneId, sessions[1].PhoneId);
        Assert.Equal("手机二", sessions[0].DeviceLabel);
        Assert.Equal("手机一", sessions[1].DeviceLabel);

        now = Start.AddMinutes(2);
        Assert.NotNull(auth.Validate(first.Token));
        Assert.Equal(first.Session.PhoneId, auth.GetActiveSessions()[0].PhoneId);

        Assert.Equal(1, auth.RevokeByPhoneId(first.Session.PhoneId));
        Assert.Null(auth.Validate(first.Token));
        Assert.NotNull(auth.Validate(second.Token));
        Assert.Equal(1, auth.ConnectedCount);
        Assert.Equal(0, auth.RevokeByPhoneId("phone-does-not-exist"));
        Assert.Throws<ArgumentException>(() => auth.RevokeByPhoneId(" "));
    }

    [Fact]
    public void SessionCapEvictsLeastRecentlyActiveToken()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));
        var issued = new List<LanTokenIssue>();
        for (var index = 0; index < LanAuthStore.MaxActiveSessions; index++)
        {
            now = Start.AddMinutes(index);
            issued.Add(auth.IssueToken($"手机-{index}"));
        }

        Assert.Equal(LanAuthStore.MaxActiveSessions, auth.ConnectedCount);
        now = Start.AddMinutes(LanAuthStore.MaxActiveSessions);
        var overflow = auth.IssueToken("溢出手机");

        Assert.Equal(LanAuthStore.MaxActiveSessions, auth.ConnectedCount);
        Assert.Null(auth.Validate(issued[0].Token));
        Assert.NotNull(auth.Validate(issued[1].Token));
        Assert.Contains(
            auth.GetActiveSessions(),
            session => session.PhoneId == overflow.Session.PhoneId);
    }

    [Fact]
    public void ConnectedCountAndActiveSessionsPruneIdleExpiredTokens()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));
        auth.IssueToken("手机");

        now = Start.AddHours(12);

        Assert.Equal(0, auth.ConnectedCount);
        Assert.Empty(auth.GetActiveSessions());
    }

    [Fact]
    public void DeviceLabelIsTrimmedToFortyCharacters()
    {
        var auth = new LanAuthStore(() => Start);

        Assert.Equal(string.Empty, auth.IssueToken(null).Session.DeviceLabel);
        Assert.Equal("  手机  ".Trim(), auth.IssueToken("  手机  ").Session.DeviceLabel);
        Assert.Equal(40, auth.IssueToken(new string('x', 50)).Session.DeviceLabel.Length);
    }

    [Fact]
    public void ConnectedCountAndActiveSessionsExposeOnlyLiveSessions()
    {
        var now = Start;
        var auth = new LanAuthStore(() => now, TimeSpan.FromHours(12));
        var first = auth.IssueToken("手机一");
        var second = auth.IssueToken("手机二");

        Assert.Equal(2, auth.ConnectedCount);
        var sessions = auth.GetActiveSessions();
        Assert.Equal(2, sessions.Count);
        Assert.Contains(sessions, session =>
            session.PhoneId == first.Session.PhoneId && session.DeviceLabel == "手机一");
        Assert.Contains(sessions, session =>
            session.PhoneId == second.Session.PhoneId && session.DeviceLabel == "手机二");

        now = Start.AddHours(12);
        Assert.Equal(0, auth.ConnectedCount);
        Assert.Empty(auth.GetActiveSessions());
    }

    [Fact]
    public void RevokeByPhoneIdRemovesOnlyThatPhonesSessions()
    {
        var auth = new LanAuthStore(() => Start);
        var first = auth.IssueToken("手机一");
        var second = auth.IssueToken("手机二");

        Assert.Equal(1, auth.RevokeByPhoneId(first.Session.PhoneId));
        Assert.Null(auth.Validate(first.Token));
        Assert.NotNull(auth.Validate(second.Token));
        Assert.Equal(1, auth.ConnectedCount);

        Assert.Equal(0, auth.RevokeByPhoneId("phone-missing"));
        Assert.ThrowsAny<ArgumentException>(() => auth.RevokeByPhoneId(" "));
    }

    private static string WrongPin(string pin) =>
        pin == "000000" ? "000001" : "000000";
}
