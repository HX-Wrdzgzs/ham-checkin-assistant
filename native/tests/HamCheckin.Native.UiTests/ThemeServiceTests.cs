using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using HamCheckin.Native.App.Infrastructure;
using HamCheckin.Native.Core.Storage;
using Xunit;

namespace HamCheckin.Native.UiTests;

[CollectionDefinition("Theme preference persistence", DisableParallelization = true)]
public sealed class ThemePreferencePersistenceCollection
{
}

[Collection("Native WPF application")]
public sealed class ThemeServiceTests
{
    private static readonly string[] PaletteKeys =
    [
        "AppBackgroundBrush",
        "SurfaceBrush",
        "SurfaceAltBrush",
        "FieldBackgroundBrush",
        "SidebarBrush",
        "HeaderBrush",
        "BorderBrush",
        "TextBrush",
        "MutedBrush",
        "AccentBrush",
        "AccentSoftBrush",
        "AccentTextBrush",
        "SuccessBrush",
        "SuccessSoftBrush",
        "WarningSoftBrush",
        "WarningTextBrush",
        "ErrorBrush",
        "FocusBrush",
        "SelectionBrush",
        "SelectionTextBrush",
        "TableGridBrush",
        "TableHeaderBrush",
        "ButtonHoverBrush",
        "ButtonPressedBrush",
        "DisabledTextBrush",
        "DisabledBackgroundBrush",
        "EmptyBrush"
    ];

    private readonly WpfDispatcherFixture _fixture;

    public ThemeServiceTests(WpfDispatcherFixture fixture) => _fixture = fixture;

    [Theory]
    [InlineData(ThemePreference.FollowSystem, true, false, EffectiveTheme.Light)]
    [InlineData(ThemePreference.FollowSystem, false, false, EffectiveTheme.Dark)]
    [InlineData(ThemePreference.Light, false, false, EffectiveTheme.Light)]
    [InlineData(ThemePreference.Dark, true, false, EffectiveTheme.Dark)]
    [InlineData(ThemePreference.Light, true, true, EffectiveTheme.HighContrast)]
    [InlineData(ThemePreference.Dark, false, true, EffectiveTheme.HighContrast)]
    [InlineData((ThemePreference)99, false, false, EffectiveTheme.Dark)]
    public void ResolveAppliesPreferenceAndHighContrastPrecedence(
        ThemePreference preference,
        bool appsUseLightTheme,
        bool highContrast,
        EffectiveTheme expected)
    {
        var actual = new ThemeService().Resolve(preference, appsUseLightTheme, highContrast);

        Assert.Equal(expected, actual);
    }

    [Fact]
    public void ThemePalettesProvideEverySemanticResourceAndHighContrastUsesSystemRoles()
    {
        _fixture.Run(() =>
        {
            foreach (var theme in new[] { EffectiveTheme.Light, EffectiveTheme.Dark, EffectiveTheme.HighContrast })
            {
                var palette = ThemeService.CreateThemeDictionary(theme);
                foreach (var key in PaletteKeys)
                {
                    Assert.IsAssignableFrom<Brush>(palette[key]);
                }
            }

            var highContrast = ThemeService.CreateThemeDictionary(EffectiveTheme.HighContrast);
            Assert.Same(SystemColors.WindowBrush, highContrast["AppBackgroundBrush"]);
            Assert.Same(SystemColors.WindowBrush, highContrast[SystemColors.WindowBrushKey]);
            Assert.Same(SystemColors.WindowTextBrush, highContrast["TextBrush"]);
            Assert.Same(SystemColors.HighlightBrush, highContrast["SelectionBrush"]);
            Assert.Same(SystemColors.HighlightTextBrush, highContrast["SelectionTextBrush"]);
        });
    }

    [Fact]
    public void ApplyingThemeReplacesSharedApplicationResourcesWithoutAccumulatingDictionaries()
    {
        _fixture.Run(() =>
        {
            var application = Application.Current!;
            var initialDictionaryCount = application.Resources.MergedDictionaries.Count;
            using var service = new ThemeService();

            service.ApplyEffectiveTheme(EffectiveTheme.Light);
            var lightDictionary = application.Resources.MergedDictionaries[0];
            var lightBackground = lightDictionary["AppBackgroundBrush"];

            service.ApplyEffectiveTheme(EffectiveTheme.Dark);
            var darkDictionary = application.Resources.MergedDictionaries[0];

            Assert.Equal(initialDictionaryCount + 1, application.Resources.MergedDictionaries.Count);
            Assert.NotSame(lightDictionary, darkDictionary);
            Assert.NotSame(lightBackground, darkDictionary["AppBackgroundBrush"]);
            Assert.Equal(EffectiveTheme.Dark, service.CurrentTheme);
        });
    }
}

[Collection("Theme preference persistence")]
public sealed class AppSettingsStoreTests
{
    [Fact]
    public void ThemePreferenceRoundTripsAndPreservesUnknownConfigurationFields()
    {
        InIsolatedConfigRoot(root =>
        {
            Assert.Equal(ThemePreference.FollowSystem, AppSettingsStore.LoadThemePreference());
            Assert.False(File.Exists(Path.Combine(root, "config.json")));

            File.WriteAllText(AppPaths.ConfigPath, """{"themePreference":"FuturePreference"}""");
            Assert.Equal(ThemePreference.FollowSystem, AppSettingsStore.LoadThemePreference());

            File.WriteAllText(
                AppPaths.ConfigPath,
                """{"otherSetting":{"keep":42},"themePreference":"Dark"}""");
            Assert.Equal(ThemePreference.Dark, AppSettingsStore.LoadThemePreference());
            Assert.True(AppSettingsStore.TrySaveThemePreference(ThemePreference.Light, out var error), error);

            using var document = JsonDocument.Parse(File.ReadAllText(AppPaths.ConfigPath));
            Assert.Equal(42, document.RootElement.GetProperty("otherSetting").GetProperty("keep").GetInt32());
            Assert.Equal("Light", document.RootElement.GetProperty("themePreference").GetString());
        });
    }

    [Fact]
    public void InvalidConfigurationFallsBackAndIsNotOverwrittenWhenSaving()
    {
        InIsolatedConfigRoot(_ =>
        {
            const string invalidJson = "{not valid JSON";
            File.WriteAllText(AppPaths.ConfigPath, invalidJson);

            Assert.Equal(ThemePreference.FollowSystem, AppSettingsStore.LoadThemePreference());
            Assert.False(AppSettingsStore.TrySaveThemePreference(ThemePreference.Dark, out var error));
            Assert.False(string.IsNullOrWhiteSpace(error));
            Assert.Equal(invalidJson, File.ReadAllText(AppPaths.ConfigPath));
        });
    }

    private static void InIsolatedConfigRoot(Action<string> action)
    {
        var previousRoot = AppPaths.IsOverridden ? AppPaths.Root : null;
        var temporaryRoot = Path.Combine(Path.GetTempPath(), $"ham-theme-settings-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(temporaryRoot);
            AppPaths.ConfigureDataRoot(temporaryRoot);
            action(temporaryRoot);
        }
        finally
        {
            AppPaths.ConfigureDataRoot(previousRoot);
            if (Directory.Exists(temporaryRoot))
            {
                Directory.Delete(temporaryRoot, recursive: true);
            }
        }
    }
}
