using System.Collections.Generic;
using System.Windows;
using System.Windows.Input;
using HamCheckin.Native.Core;

namespace HamCheckin.Native.App.Views;

public partial class SessionPickerWindow : Window
{
    public SessionInfo? SelectedSession => SessionList.SelectedItem as SessionInfo;

    public SessionPickerWindow(IReadOnlyList<SessionInfo> sessions)
    {
        InitializeComponent();
        SessionList.ItemsSource = sessions;
        if (sessions.Count > 0)
        {
            SessionList.SelectedIndex = 0;
        }
        PreviewKeyDown += Window_PreviewKeyDown;
    }

    private void Select_Click(object sender, RoutedEventArgs e)
    {
        if (SelectedSession is null)
        {
            MessageBox.Show("请先选择一个场次。", "选择场次", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        DialogResult = true;
    }

    private void SessionList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (SelectedSession is not null)
        {
            DialogResult = true;
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;

    private void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            DialogResult = false;
            e.Handled = true;
        }
        else if (e.Key == Key.Enter && SelectedSession is not null)
        {
            DialogResult = true;
            e.Handled = true;
        }
    }
}
