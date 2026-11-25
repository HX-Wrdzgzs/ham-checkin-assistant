using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace HamCheckin.Native.App.Infrastructure;

internal static class WindowMotion
{
    private const double PageStartOpacity = 0.94;
    private const double DialogStartOpacity = 0.96;
    private const double EntranceOffset = 8;
    private static readonly TimeSpan PageDuration = TimeSpan.FromMilliseconds(180);
    private static readonly TimeSpan DialogDuration = TimeSpan.FromMilliseconds(160);

    public static bool IsMotionEnabled(bool appEnabled) =>
        appEnabled && SystemParameters.ClientAreaAnimation;

    public static void Attach(Window window, Func<bool> appEnabled)
    {
        window.Loaded += (_, _) =>
        {
            if (DesignerProperties.GetIsInDesignMode(window) || window.Content is not FrameworkElement content)
            {
                return;
            }

            PlayEntrance(content, IsMotionEnabled(appEnabled()), DialogStartOpacity, verticalOffset: true, DialogDuration);
        };
    }

    public static void PlayPageEntrance(FrameworkElement page, bool enabled) =>
        PlayEntrance(page, enabled, PageStartOpacity, verticalOffset: false, PageDuration);

    private static void PlayEntrance(
        FrameworkElement element, bool enabled, double startOpacity, bool verticalOffset, TimeSpan duration)
    {
        if (!enabled)
        {
            Reset(element);
            return;
        }

        // Cancel any entrance still in flight so a fast page switch or a
        // repeated window load restarts cleanly instead of stacking animations.
        element.BeginAnimation(UIElement.OpacityProperty, null);
        element.Opacity = 1;

        var translate = element.RenderTransform as TranslateTransform ?? new TranslateTransform();
        translate.BeginAnimation(TranslateTransform.XProperty, null);
        translate.BeginAnimation(TranslateTransform.YProperty, null);
        translate.X = 0;
        translate.Y = 0;
        element.RenderTransform = translate;

        // The base values above are the final state, so FillBehavior.Stop
        // leaves opacity 1 with a zero offset instead of jumping on completion.
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        element.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(startOpacity, 1, duration)
        {
            EasingFunction = ease,
            FillBehavior = FillBehavior.Stop
        });

        var axis = verticalOffset ? TranslateTransform.YProperty : TranslateTransform.XProperty;
        translate.BeginAnimation(axis, new DoubleAnimation(EntranceOffset, 0, duration)
        {
            EasingFunction = ease,
            FillBehavior = FillBehavior.Stop
        });
    }

    private static void Reset(FrameworkElement element)
    {
        element.BeginAnimation(UIElement.OpacityProperty, null);
        element.Opacity = 1;
        element.RenderTransform = Transform.Identity;
    }
}
