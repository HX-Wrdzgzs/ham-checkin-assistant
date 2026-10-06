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
    public void StaleUserEditIsAcceptedAsTheFocusedTextBoxAuthoritativeText()
    {
        var service = new QuickInputDraftService();
        var first = service.ApplyUserEdit(
            "main-input", 0, "BA4RLL QYT6900 5W YZ YZ");

        // The quick-window edit deliberately carries the old revision. The
        // focused WPF TextBox still owns its complete string, so rejecting it
        // would make the UI write the old suffix back over the user's edit.
        var edited = service.ApplyUserEdit(
            "quick-window-input", 0, "BA4VXR QYT6900 5W YZ YZ",
            isActiveEditor: true);

        Assert.Equal("BA4RLL QYT6900 5W YZ YZ", first.Text);
        Assert.Equal("BA4VXR QYT6900 5W YZ YZ", edited.Text);
        Assert.True(edited.Revision > first.Revision);
        Assert.Equal(edited.Text, service.Current.Text);
        Assert.Equal(edited.Revision, service.Current.Revision);
    }

    [Fact]
    public void StaleMirrorEditFromInactiveSurfaceCannotOverwriteFocusedDraft()
    {
        var service = new QuickInputDraftService();
        var first = service.ApplyUserEdit(
            "main-input", 0, "BA4RLL QYT6900 5W YZ YZ");
        var activeEdit = service.ApplyUserEdit(
            "main-input", first.Revision, "BA4VXR QYT6900 5W YZ YZ",
            isActiveEditor: true);

        // Simulate a delayed notification from the other TextBox.  It still
        // carries the old revision and is not keyboard-active, so it cannot
        // overwrite the text the focused editor just committed.
        var staleMirror = service.ApplyUserEdit(
            "quick-window-input", first.Revision, first.Text,
            isActiveEditor: false);

        Assert.Equal(activeEdit.Text, staleMirror.Text);
        Assert.Equal(activeEdit.Revision, service.Current.Revision);
        Assert.Equal("BA4VXR QYT6900 5W YZ YZ", service.Current.Text);
    }

    [Fact]
    public void ImeMetadataDoesNotAdvanceTextRevisionOrEraseSuffix()
    {
        var service = new QuickInputDraftService();
        var original = service.ApplyUserEdit(
            "main-input", 0, "BA4RLL QYT6900 5W YZ YZ");

        service.SetImeCompositionState("main-input", true);
        var edited = service.ApplyUserEdit(
            "main-input", original.Revision, "BA4VXR QYT6900 5W YZ YZ", true);
        service.SetImeCompositionState("main-input", false);

        Assert.Equal("BA4VXR QYT6900 5W YZ YZ", edited.Text);
        Assert.Equal(original.Revision + 1, edited.Revision);
        Assert.False(service.Current.IsImeComposing);
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
        Assert.True(events[1].ForceApplyToEditors);
        Assert.Equal("programmatic", events[1].Snapshot.OriginId);
        Assert.Equal(string.Empty, events[1].Snapshot.Text);
    }

    [Fact]
    public void ImeMetadataNeverRequestsAFullTextReplacement()
    {
        var service = new QuickInputDraftService();
        var events = new List<QuickInputDraftChangedEventArgs>();
        service.Changed += (_, args) => events.Add(args);

        service.ApplyUserEdit("quick-window-input", 0, "BA4RLL QYT6900 5W YZ YZ");
        service.SetImeCompositionState("quick-window-input", true);
        service.SetImeCompositionState("quick-window-input", false);

        Assert.NotEmpty(events);
        Assert.All(events, args => Assert.False(args.ForceApplyToEditors));
        Assert.Equal("BA4RLL QYT6900 5W YZ YZ", service.Current.Text);
    }
}
