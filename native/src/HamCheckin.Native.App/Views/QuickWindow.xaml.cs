using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.App.ViewModels;
using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Parsing;

namespace HamCheckin.Native.App.Views;

public partial class QuickWindow : Window
{
    private const string InputOrigin = "quick-window-input";
    private MainViewModel? _viewModel;
    private bool _synchronizingInput;
    private bool _imeComposing;
    private long _appliedInputRevision;

    public QuickWindow()
    {
        InitializeComponent();
        TextCompositionManager.AddPreviewTextInputStartHandler(QuickInputBox, QuickInputBox_TextInputStart);
        TextCompositionManager.AddPreviewTextInputUpdateHandler(QuickInputBox, QuickInputBox_TextInputUpdate);
        TextCompositionManager.AddTextInputHandler(QuickInputBox, QuickInputBox_TextInput);
        Loaded += (_, _) =>
        {
            QuickInputBox.Focus();
            Keyboard.Focus(QuickInputBox);
        };
    }

    private void Window_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.InputDraftChanged -= ViewModel_InputDraftChanged;
        }

        _viewModel = e.NewValue as MainViewModel;
        if (_viewModel is not null)
        {
            _viewModel.InputDraftChanged += ViewModel_InputDraftChanged;
            SyncInputBox(_viewModel.InputDraft, moveCaretToEnd: false);
        }
    }

    private void Window_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (RecentCheckinsCard is null)
        {
            return;
        }

        // At the declared minimum height the input, parsed fields and footer
        // are the usable controls.  Recent rows are useful context, but must
        // not push the submit button or status out of the client area.
        var compact = e.NewSize.Height < 235;
        RecentCheckinsCard.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        RecentCheckinsCard.IsHitTestVisible = !compact;
    }

    private void QuickInputBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_synchronizingInput || _viewModel is null)
        {
            return;
        }

        var snapshot = _viewModel.ApplyInputEdit(
            InputOrigin,
            _appliedInputRevision,
            QuickInputBox.Text,
            _imeComposing,
            QuickInputBox.IsKeyboardFocusWithin);
        _appliedInputRevision = snapshot.Revision;
        if (!string.Equals(snapshot.Text, QuickInputBox.Text, StringComparison.Ordinal)
            && !QuickInputBox.IsKeyboardFocusWithin)
        {
            SyncInputBox(snapshot, moveCaretToEnd: false);
        }
    }

    private void QuickInputBox_GotKeyboardFocus(object sender, KeyboardFocusChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            SyncInputBox(_viewModel.InputDraft, moveCaretToEnd: false);
        }
    }

    private void QthCandidate_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is Button { Tag: string candidate })
        {
            _viewModel.SelectQthCandidate(candidate);
            QuickInputBox.Focus();
        }
    }

    private void QuickInputBox_TextInputStart(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(true);

    private void QuickInputBox_TextInputUpdate(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(true);

    private void QuickInputBox_TextInput(object sender, TextCompositionEventArgs e) =>
        SetImeComposition(false);

    private void SetImeComposition(bool composing)
    {
        _imeComposing = composing;
        _viewModel?.SetImeCompositionState(InputOrigin, composing);
    }

    private void ViewModel_InputDraftChanged(object? sender, QuickInputDraftChangedEventArgs e)
    {
        // The focused TextBox is the authoritative editor.  A notification
        // from the other surface may be stale relative to a keyboard event.
        // Do not replace the full Text property while the user is editing;
        // this also covers IME metadata events, which are not text edits but
        // can arrive between the composition TextChanged events.  Only an
        // explicit operation (submit clear/session switch) may force it.
        if (QuickInputBox.IsKeyboardFocusWithin && !e.ForceApplyToEditors)
        {
            return;
        }

        SyncInputBox(e.Snapshot, moveCaretToEnd: true);
    }

    private void SyncInputBox(QuickInputDraftSnapshot? snapshot, bool moveCaretToEnd)
    {
        if (snapshot is null)
        {
            return;
        }

        _appliedInputRevision = snapshot.Revision;
        if (string.Equals(QuickInputBox.Text, snapshot.Text, StringComparison.Ordinal))
        {
            if (moveCaretToEnd && !QuickInputBox.IsKeyboardFocusWithin)
            {
                QuickInputBox.CaretIndex = QuickInputBox.Text.Length;
            }
            return;
        }

        _synchronizingInput = true;
        try
        {
            QuickInputBox.Text = snapshot.Text;
            if (moveCaretToEnd)
            {
                QuickInputBox.CaretIndex = QuickInputBox.Text.Length;
            }
        }
        finally
        {
            _synchronizingInput = false;
        }
    }

    private void Input_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (DataContext is not MainViewModel viewModel)
        {
            return;
        }
        var gesture = viewModel.GetShortcut("submit")?.Gesture;
        if (gesture is not null && ShortcutGesture.Matches(gesture, e))
        {
            if (viewModel.SubmitCommand.CanExecute(null))
            {
                viewModel.SubmitCommand.Execute(null);
            }
            e.Handled = true;
        }
        else if (viewModel.GetShortcut("clear")?.Gesture is { } clearGesture
                 && ShortcutGesture.Matches(clearGesture, e))
        {
            viewModel.ClearCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void Topmost_Checked(object sender, RoutedEventArgs e) => Topmost = true;
    private void Topmost_Unchecked(object sender, RoutedEventArgs e) => Topmost = false;
    private void CloseButton_Click(object sender, RoutedEventArgs e) => Hide();

    private void ShowMain_Click(object sender, RoutedEventArgs e)
    {
        if (Application.Current.MainWindow is Window main)
        {
            main.Show();
            main.WindowState = WindowState.Normal;
            main.Activate();
        }
    }

    private void Window_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        e.Cancel = true;
        Hide();
    }
}
