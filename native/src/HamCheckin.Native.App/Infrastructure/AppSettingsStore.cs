using System.Diagnostics;
using System.IO;
using System.Security;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using HamCheckin.Native.Core.Storage;

namespace HamCheckin.Native.App.Infrastructure;

public static class AppSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true
    };

    public static ThemePreference LoadThemePreference()
    {
        try
        {
            using var stream = File.OpenRead(AppPaths.ConfigPath);
            using var document = JsonDocument.Parse(stream);
            if (document.RootElement.ValueKind == JsonValueKind.Object
                && document.RootElement.TryGetProperty("themePreference", out var value)
                && value.ValueKind == JsonValueKind.String
                && Enum.TryParse(value.GetString(), ignoreCase: true, out ThemePreference preference)
                && Enum.IsDefined(typeof(ThemePreference), preference))
            {
                return preference;
            }

            return ThemePreference.FollowSystem;
        }
        catch (FileNotFoundException)
        {
            return ThemePreference.FollowSystem;
        }
        catch (DirectoryNotFoundException)
        {
            return ThemePreference.FollowSystem;
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException
            or JsonException
            or ArgumentException
            or NotSupportedException
            or SecurityException)
        {
            Trace.TraceWarning("Unable to load the theme preference: {0}", exception.Message);
            return ThemePreference.FollowSystem;
        }
    }

    public static bool TrySaveThemePreference(ThemePreference preference, out string? error)
    {
        error = null;
        if (!Enum.IsDefined(typeof(ThemePreference), preference))
        {
            error = "主题选项无效。";
            return false;
        }

        try
        {
            var configPath = AppPaths.ConfigPath;
            var directory = Path.GetDirectoryName(configPath);
            if (string.IsNullOrWhiteSpace(directory))
            {
                error = "配置文件路径无效。";
                return false;
            }

            Directory.CreateDirectory(directory);
            JsonObject settings;
            try
            {
                using var stream = File.OpenRead(configPath);
                if (JsonNode.Parse(stream) is not JsonObject existingSettings)
                {
                    error = "配置文件根节点不是 JSON 对象，未修改现有文件。";
                    return false;
                }

                settings = existingSettings;
            }
            catch (FileNotFoundException)
            {
                settings = new JsonObject();
            }

            settings["themePreference"] = preference.ToString();
            var temporaryPath = Path.Combine(directory, $"config.{Guid.NewGuid():N}.tmp");
            try
            {
                File.WriteAllText(temporaryPath, settings.ToJsonString(JsonOptions), new UTF8Encoding(false));
                File.Move(temporaryPath, configPath, overwrite: true);
                return true;
            }
            finally
            {
                if (File.Exists(temporaryPath))
                {
                    File.Delete(temporaryPath);
                }
            }
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException
            or JsonException
            or ArgumentException
            or NotSupportedException
            or SecurityException)
        {
            error = $"无法保存主题设置：{exception.Message}";
            return false;
        }
    }
}
