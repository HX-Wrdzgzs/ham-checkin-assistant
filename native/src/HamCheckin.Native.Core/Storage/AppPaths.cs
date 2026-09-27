namespace HamCheckin.Native.Core.Storage;

public static class AppPaths
{
    private static string? _overrideRoot;

    public static string LocalAppDataRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "HAM点名助手");

    /// <summary>
    /// Optional process-local data root used by isolated test runs and preview
    /// launches. Production runs leave this unset and continue using
    /// %LOCALAPPDATA%\HAM点名助手.
    /// </summary>
    public static string Root => _overrideRoot ?? LocalAppDataRoot;

    public static bool IsOverridden => _overrideRoot is not null;

    public static void ConfigureDataRoot(string? root)
    {
        if (string.IsNullOrWhiteSpace(root))
        {
            _overrideRoot = null;
            return;
        }

        _overrideRoot = Path.GetFullPath(root.Trim());
    }

    public static string DataRoot => Path.Combine(Root, "data");
    public static string BackupRoot => Path.Combine(Root, "backup");
    public static string LogRoot => Path.Combine(Root, "logs");
    public static string CacheRoot => Path.Combine(Root, "cache");
    public static string QthPackageRoot => Path.Combine(DataRoot, "qth_packages");
    public static string NativePreviewRoot => Root;
    public static string NativePreviewDataRoot => DataRoot;
    // 旧 Python 版已经占用 data\ham_checkin.db。原生版在用户明确迁移前使用
    // 同一正式目录下的独立文件，避免首次启动改写现场数据。
    public static string NativeDatabasePath => Path.Combine(DataRoot, "ham_checkin_native.db");
    public static string MiitRadioCatalogPath => Path.Combine(DataRoot, "miit_radio_catalog.db");
    public static string QthAdminPath => Path.Combine(DataRoot, "qth_admin.db");
    public static string ConfigPath => Path.Combine(Root, "config.json");
    public static string LegacyDatabasePath => Path.Combine(Root, "data", "ham_checkin.db");
}
