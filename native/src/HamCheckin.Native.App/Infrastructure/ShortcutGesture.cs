using System.Windows.Input;

namespace HamCheckin.Native.App.Infrastructure;

internal static class ShortcutGesture
{
    public static bool Matches(string gesture, KeyEventArgs e) =>
        Matches(gesture, e.Key == Key.System ? e.SystemKey : e.Key, Keyboard.Modifiers);

    public static bool Matches(string gesture, Key key, ModifierKeys modifiers)
    {
        if (!TryParse(gesture, out var expectedModifiers, out var expectedKey))
        {
            return false;
        }

        return expectedModifiers == modifiers && expectedKey == key;
    }

    public static bool TryParse(string gesture, out ModifierKeys modifiers, out Key key)
    {
        modifiers = ModifierKeys.None;
        key = Key.None;
        if (string.IsNullOrWhiteSpace(gesture))
        {
            return false;
        }

        var parts = gesture.Split('+', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 0)
        {
            return false;
        }

        var keyName = parts[^1];
        foreach (var part in parts[..^1])
        {
            switch (part.ToUpperInvariant())
            {
                case "CTRL":
                case "CONTROL":
                    modifiers |= ModifierKeys.Control;
                    break;
                case "SHIFT":
                    modifiers |= ModifierKeys.Shift;
                    break;
                case "ALT":
                    modifiers |= ModifierKeys.Alt;
                    break;
                case "WIN":
                case "WINDOWS":
                    modifiers |= ModifierKeys.Windows;
                    break;
                default:
                    return false;
            }
        }

        key = keyName.ToUpperInvariant() switch
        {
            "ESC" or "ESCAPE" => Key.Escape,
            "RETURN" => Key.Enter,
            "SPACE" => Key.Space,
            "PLUS" or "OEMPLUS" => Key.OemPlus,
            "MINUS" or "OEMMINUS" => Key.OemMinus,
            "ADD" => Key.Add,
            "SUBTRACT" => Key.Subtract,
            "0" => Key.D0,
            "1" => Key.D1,
            "2" => Key.D2,
            "3" => Key.D3,
            "4" => Key.D4,
            "5" => Key.D5,
            "6" => Key.D6,
            "7" => Key.D7,
            "8" => Key.D8,
            "9" => Key.D9,
            _ when Enum.TryParse<Key>(keyName, true, out var parsed) => parsed,
            _ => Key.None
        };

        return key != Key.None;
    }
}
