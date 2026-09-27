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
            _imeComposing);
        if (snapshot.Revision != _appliedInputRevision
            || !string.Equals(snapshot.Text, QuickInputBox.Text, StringComparison.Ordinal))
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
        _appliedInputRevision = e.Snapshot.Revision;
        if (e.Snapshot.OriginId == InputOrigin && QuickInputBox.IsKeyboardFocusWithin)
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
