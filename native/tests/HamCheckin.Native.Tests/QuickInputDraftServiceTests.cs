using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.Tests;

public sealed class QuickInputDraftServiceTests
{
    [Theory]
    [InlineData("BA4VXR QYT6900 5W YZ YZ", "前部替换")]
    [InlineData("BA4RLL PD780 5W YZ YZ", "中部替换")]
    [InlineData("BA4RLL QYT6900 5W YZ YZ ", "尾部插入")]
    public void EditingOneRangeNeverRewritesTheRemainingDraft(
        string editedText,
        string _)
    {
        var service = new QuickInputDraftService();
        var original = service.ApplyUserEdit(
            "main-input", 0, "BA4RLL QYT6900 5W YZ YZ");

        var edited = service.ApplyUserEdit(
            "main-input", original.Revision, editedText);

        Assert.Equal(editedText, edited.Text);
        Assert.Equal(editedText, service.Current.Text);
        Assert.True(edited.Revision > original.Revision);
    }

    [Fact]
    public void CompositionStateChangesDoNotReplaceText()
    {
        var service = new QuickInputDraftService();
        var text = service.ApplyUserEdit("main-input", 0, "BA4RLL PD780 5W");

        var composing = service.SetImeCompositionState("main-input", true);
        var finished = service.SetImeCompositionState("main-input", false);

        Assert.Equal(text.Text, composing.Text);
        Assert.Equal(text.Text, finished.Text);
        Assert.False(finished.IsImeComposing);
    }

    [Fact]
    public void UserEditKeepsTheLatestRevisionAndRejectsStaleEcho()
    {
        var service = new QuickInputDraftService();
        var first = service.ApplyUserEdit(
            "main-input", 0, "BA4RLL QYT6900 5W YZ YZ");

        var stale = service.ApplyUserEdit("quick-window-input", 0, "BA4VXR");

        Assert.Equal("BA4RLL QYT6900 5W YZ YZ", first.Text);
        Assert.Equal(first.Revision, stale.Revision);
        Assert.Equal(first.Text, stale.Text);
        Assert.Equal(first.Revision, service.Current.Revision);
    }

    [Fact]
    public void ClearOnlyClearsTheDraftThatWasActuallySubmitted()
    {
        var service = new QuickInputDraftService();
        var submitted = service.ApplyUserEdit("main-input", 0, "BA4RLL PD780 5W");

        var newer = service.ApplyUserEdit(
            "main-input", submitted.Revision, "BA4RLL PD780 5W NJXW");

        Assert.False(service.TryClear(submitted.Revision));
        Assert.Equal(newer.Text, service.Current.Text);
        Assert.True(service.TryClear(newer.Revision));
        Assert.Equal(string.Empty, service.Current.Text);
    }

    [Fact]
    public void ProgrammaticClearNotifiesBothInputSurfacesWithoutChangingRawContentEarly()
    {
        var service = new QuickInputDraftService();
        var events = new List<QuickInputDraftChangedEventArgs>();
        service.Changed += (_, args) => events.Add(args);

        var populated = service.ApplyUserEdit("main-input", 0, "BA4RLL R6 NJXW");
        service.TryClear(populated.Revision);

        Assert.Equal(2, events.Count);
        Assert.True(events[0].IsUserEdit);
        Assert.False(events[1].IsUserEdit);
        Assert.Equal("programmatic", events[1].Snapshot.OriginId);
        Assert.Equal(string.Empty, events[1].Snapshot.Text);
    }
}
