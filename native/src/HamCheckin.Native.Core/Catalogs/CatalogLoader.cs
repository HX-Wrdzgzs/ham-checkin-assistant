using System.Diagnostics;
using HamCheckin.Native.Core.Parsing;
using Microsoft.Data.Sqlite;

namespace HamCheckin.Native.Core.Catalogs;

public static class CatalogLoader
{
    public static string DefaultDataRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "HAM点名助手", "data");

    public static CatalogSnapshot CreateBuiltIn()
    {
        var devices = new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal);
        var antennas = new Dictionary<string, string>(StringComparer.Ordinal);
        var powers = new Dictionary<string, string>(StringComparer.Ordinal);
        var qths = new Dictionary<string, List<QthCandidate>>(StringComparer.Ordinal);

        AddDevices(devices, "内置别名", new (string Alias, string Standard)[]
        {
            ("qyt6900", "全易通 QYT-6900"), ("ryt6900", "全易通 QYT-6900"),
            ("k6", "泉盛 UV-K6"), ("uvk6", "泉盛 UV-K6"),
            ("k5", "泉盛 UV-K5"), ("uvk5", "泉盛 UV-K5"),
            ("k1", "泉盛 UV-K1"), ("uvk1", "泉盛 UV-K1"),
            ("uvk18", "泉盛 UV-K1(8)"), ("k18", "泉盛 UV-K1(8)"),
            ("pd780", "海能达 PD-780"), ("pd780g", "海能达 PD-780G"),
            ("pdc580", "海能达 PD-C580"), ("pdc690", "海能达 PD-C690"),
            ("r6", "摩托罗拉 R6"), ("r7", "摩托罗拉 R7"),
            ("m8268", "摩托罗拉 M8268"), ("mtm8268", "摩托罗拉 M8268"),
            ("m8668", "摩托罗拉 M8668"),
            ("m8220", "摩托罗拉 M8220"), ("p8260", "摩托罗拉 P8260"),
            ("p6620", "摩托罗拉 P6620"), ("gm300", "摩托罗拉 GM300"),
            ("gp338", "摩托罗拉 GP338"), ("gp328", "摩托罗拉 GP328"),
            ("gm3688", "摩托罗拉 GM3688"),
            ("vrn76", "威诺 VR-N76"), ("vr-n76", "威诺 VR-N76"),
            ("n76", "威诺 VR-N76"),
            ("vnn76", "威诺 VR-N76"),
            ("vrn7600", "威诺 VR-N7600"),
            ("uv5r", "宝锋 UV-5R"), ("宝峰 uv5r", "宝锋 UV-5R"),
            ("5rh", "宝锋 UV-5R-H"), ("宝峰 5rh", "宝锋 UV-5R-H"),
            ("uv5rh", "宝峰 UV-5RH"), ("bfuv5rh", "宝峰 UV-5RH"),
            ("5rhpro", "宝峰 UV-5R Pro"),
            ("5rmini", "宝锋 UV-5R Mini"), ("uv5rmini", "宝锋 UV-5R Mini"),
            ("宝峰 5rhpro", "宝峰 UV-5R Pro"),
            ("宝峰 5rmini", "宝锋 UV-5R Mini"), ("uv32", "宝锋 UV-32"),
            ("uv36", "宝峰 UV-36"), ("bfuv36", "宝峰 UV-36"),
            ("bfuv5r", "宝峰 UV-5R"),
            ("ic705", "ICOM IC-705"), ("icom705", "ICOM IC-705"),
            ("id52", "ICOM ID-52"), ("icomid52plus", "ICOM ID-52 PLUS"),
            ("ft1907r", "YAESU FT-1907R"), ("1907r", "YAESU FT-1907R"),
            ("ft70d", "YAESU FT-70DR"), ("ft70dr", "YAESU FT-70DR"),
            ("ft5dr", "YAESU FT-5DR"), ("5dr", "YAESU FT-5DR"),
            ("shk8800", "森海克斯 SHK-8800"), ("shks8600", "森海克斯 8600"),
            ("gx8500", "冠星 GX8500"),
            ("tm481", "建武 TM-481"), ("tm8118", "TM-8118"),
            ("tm800", "HYT-TM800"), ("hyttm800", "HYT-TM800"),
            ("m8260", "M8260"),
            ("wpks2200", "威泰克斯 VX-2200"), ("vx2200", "威泰克斯 VX-2200"),
            ("vx2108", "威泰克斯 VX-2108"), ("wpks2108", "威泰克斯 VX-2108"),
            ("ct1300", "摩托罗拉 CT1300"), ("qs118", "泉盛 QS-118"),
            ("300d", "300D"),
            ("建武808", "建武 808"), ("808", "建武 808"),
            ("d9000", "即时通 D9000"), ("nrl", "NRL互联"),
            ("ht", "HT"), ("73ham", "73HAM")
        });

        AddAliases(antennas, new (string Alias, string Standard)[]
        {
            ("y", "原装天线"), ("yz", "原装天线"), ("原", "原装天线"),
            ("原装", "原装天线"), ("原装天线", "原装天线"),
            ("771", "SRH-771"), ("srh771", "SRH-771"),
            ("770", "770"), ("770h", "770H"), ("770s", "770s"),
            ("4.2m", "4.2米玻璃钢"), ("4.2米", "4.2米玻璃钢"),
            ("4.2米玻璃钢", "4.2米玻璃钢"),
            ("1.2m", "1.2米玻璃钢"), ("1.5m", "1.5米玻璃钢"),
            ("1.8m", "1.8米玻璃钢"), ("1.8米玻璃钢", "1.8米玻璃钢"),
            ("1.8米gp", "1.8米GP"), ("2.4米玻璃钢", "2.4米玻璃钢"),
            ("5.2米玻璃钢", "5.2米玻璃钢"),
            ("gp", "GP"), ("gp天线", "GP天线"), ("dp", "DP"),
            ("4y", "4单元八木"), ("4单元八木", "4单元八木"),
            ("5y", "5单元八木"),
            ("5单元八木", "5单元八木"), ("5单元八木天线", "5单元八木天线"),
            ("24单元八木", "24单元八木天线"), ("24单元八木天线", "24单元八木天线"),
            ("八木", "八木"), ("自制八木", "自制八木"),
            ("775拉杆天线", "775拉杆天线"), ("吸盘天线", "吸盘天线"),
            ("车载苗子", "车载苗子"), ("车苗", "车载苗子"),
            ("车载天线", "车载天线"), ("橡胶天线", "橡胶天线"),
            ("十字交叉偶极天线", "十字交叉偶极天线"), ("x520", "X520"),
            ("srh701", "SRH-701"), ("srh518", "SRH-518"),
            ("钻石vr77天线", "钻石 VR-77 天线"),
            ("7900", "钻石 7900"), ("钻石7900", "钻石 7900")
        });

        AddAliases(powers, new (string Alias, string Standard)[]
        {
            ("01", "0.1W"), ("02", "0.2W"), ("05", "0.5W"),
            ("1", "1W"), ("2", "2W"), ("4", "4W"), ("5", "5W"),
            ("8", "8W"), ("10", "10W"), ("15", "15W"), ("20", "20W"),
            ("25", "25W"), ("30", "30W"), ("50", "50W"),
            ("l", "低"), ("m", "中"), ("h", "高"), ("f", "满"),
            ("低", "低"), ("中", "中"), ("高", "高"), ("满", "满")
        });

        AddQth(qths, "njxw", new("江苏省南京市玄武区", "江苏省", "南京市", "玄武区", "admin_region", 1000));
        AddQth(qths, "njqx", new("江苏省南京市栖霞区", "江苏省", "南京市", "栖霞区", "admin_region", 1000));
        AddQth(qths, "njgl", new("江苏省南京市鼓楼区", "江苏省", "南京市", "鼓楼区", "admin_region", 1000));
        AddQth(qths, "njqh", new("江苏省南京市秦淮区", "江苏省", "南京市", "秦淮区", "admin_region", 1000));
        AddQth(qths, "njjy", new("江苏省南京市建邺区", "江苏省", "南京市", "建邺区", "admin_region", 1000));
        AddQth(qths, "njyht", new("江苏省南京市雨花台区", "江苏省", "南京市", "雨花台区", "admin_region", 1000));
        AddQth(qths, "njjn", new("江苏省南京市江宁区", "江苏省", "南京市", "江宁区", "admin_region", 1000));
        AddQth(qths, "njpk", new("江苏省南京市浦口区", "江苏省", "南京市", "浦口区", "admin_region", 1000));
        AddQth(qths, "njgc", new("江苏省南京市高淳区", "江苏省", "南京市", "高淳区", "admin_region", 1000));
        AddQth(qths, "南京鼓楼", new("江苏省南京市鼓楼区", "江苏省", "南京市", "鼓楼区", "admin_region", 1000));
        AddQth(qths, "南京秦淮", new("江苏省南京市秦淮区", "江苏省", "南京市", "秦淮区", "admin_region", 1000));
        AddQth(qths, "南京栖霞", new("江苏省南京市栖霞区", "江苏省", "南京市", "栖霞区", "admin_region", 1000));
        AddQth(qths, "南京建邺", new("江苏省南京市建邺区", "江苏省", "南京市", "建邺区", "admin_region", 1000));
        AddQth(qths, "南京雨花台", new("江苏省南京市雨花台区", "江苏省", "南京市", "雨花台区", "admin_region", 1000));
        AddQth(qths, "板桥新城", new("江苏省南京市雨花台区板桥新城", "江苏省", "南京市", "雨花台区", "place", 1200));
        AddQth(qths, "南京江宁", new("江苏省南京市江宁区", "江苏省", "南京市", "江宁区", "admin_region", 1000));
        AddQth(qths, "南京浦口", new("江苏省南京市浦口区", "江苏省", "南京市", "浦口区", "admin_region", 1000));
        AddQth(qths, "南京高淳", new("江苏省南京市高淳区", "江苏省", "南京市", "高淳区", "admin_region", 1000));
        AddQth(qths, "江北新区", new("江苏省南京市江北新区", "江苏省", "南京市", "江北新区", "admin_region", 1000));
        AddQth(qths, "njjbxq", new("江苏省南京市江北新区", "江苏省", "南京市", "江北新区", "admin_region", 1000));
        AddQth(qths, "yz", new("江苏省扬州市", "江苏省", "扬州市", "", "admin_region", 1000));
        AddQth(qths, "扬州邗江", new("江苏省扬州市邗江区", "江苏省", "扬州市", "邗江区", "admin_region", 1000));
        AddQth(qths, "yzgj", new("江苏省扬州市邗江区", "江苏省", "扬州市", "邗江区", "admin_region", 1000));
        AddQth(qths, "zj", new("江苏省镇江市", "江苏省", "镇江市", "", "admin_region", 1000));
        AddQth(qths, "jsjr", new("江苏省镇江市句容市", "江苏省", "镇江市", "句容市", "admin_region", 1000));
        AddQth(qths, "句容", new("江苏省镇江市句容市", "江苏省", "镇江市", "句容市", "admin_region", 1000));
        AddQth(qths, "江苏盐城", new("江苏省盐城市", "江苏省", "盐城市", "", "admin_region", 1000));
        AddQth(qths, "jsyc", new("江苏省盐城市", "江苏省", "盐城市", "", "admin_region", 1000));
        AddQth(qths, "ahwh", new("安徽省芜湖市", "安徽省", "芜湖市", "", "admin_region", 1000));
        AddQth(qths, "安徽芜湖", new("安徽省芜湖市", "安徽省", "芜湖市", "", "admin_region", 1000));
        AddQth(qths, "浙江衢州", new("浙江省衢州市", "浙江省", "衢州市", "", "admin_region", 1000));
        AddQth(qths, "山东青岛", new("山东省青岛市", "山东省", "青岛市", "", "admin_region", 1000));
        AddQth(qths, "安徽芜湖湾沚", new("安徽省芜湖市湾沚区", "安徽省", "芜湖市", "湾沚区", "admin_region", 1000));
        AddQth(qths, "玄武湖", new("江苏省南京市玄武湖", "江苏省", "南京市", "玄武湖", "place", 1200));
        AddQth(qths, "南京工程学院", new("江苏省南京市南京工程学院", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京大学仙林校区", new("江苏省南京市南京大学仙林校区", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京工业大学", new("江苏省南京市南京工业大学", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京禄口机场", new("江苏省南京市南京禄口机场", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京马群", new("江苏省南京市马群", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京市河西德基", new("江苏省南京市河西德基", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京市水游城", new("江苏省南京市水游城", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "南京新街口", new("江苏省南京市南京新街口", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "西安门地铁站", new("江苏省南京市西安门地铁站", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "仙林湖万达茂", new("江苏省南京市仙林湖万达茂", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "龙蟠中路338号", new("江苏省南京市龙蟠中路338号", "江苏省", "南京市", "", "place", 1200));
        AddQth(qths, "东南大学九龙湖校区", new("江苏省南京市江宁区东南大学九龙湖校区", "江苏省", "南京市", "江宁区", "place", 1200));
        AddQth(qths, "东大九龙湖校区", new("江苏省南京市江宁区东大九龙湖校区", "江苏省", "南京市", "江宁区", "place", 1200));

        return BuildSnapshot(
            devices,
            new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal),
            antennas,
            powers,
            qths,
            0);
    }

    public static Task<(CatalogSnapshot Snapshot, CatalogLoadReport Report)> LoadExistingDataAsync(
        CatalogSnapshot baseline,
        string? dataRoot = null,
        CancellationToken cancellationToken = default) => Task.Run(
            () => LoadExistingData(baseline, dataRoot ?? DefaultDataRoot, cancellationToken),
            cancellationToken);

    private static (CatalogSnapshot Snapshot, CatalogLoadReport Report) LoadExistingData(
        CatalogSnapshot baseline,
        string dataRoot,
        CancellationToken cancellationToken)
    {
        var timer = Stopwatch.StartNew();
        var messages = new List<string>();
        var devices = new Dictionary<string, DeviceCandidate>(baseline.DeviceAliases, StringComparer.Ordinal);
        var miit = new Dictionary<string, DeviceCandidate>(StringComparer.Ordinal);
        foreach (var item in baseline.MiitModels)
        {
            miit[item.Key] = item.Value;
        }

        var antennas = new Dictionary<string, string>(baseline.AntennaAliases, StringComparer.Ordinal);
        var powers = new Dictionary<string, string>(baseline.PowerAliases, StringComparer.Ordinal);
        var qths = baseline.QthAliases.ToDictionary(
            static item => item.Key,
            static item => item.Value.ToList(),
            StringComparer.Ordinal);
        var qthPlaceCount = 0;

        // 正式版使用 qth_admin.db；兼容此前已下载的 qth_places.db，避免
        // 用户升级后丢失已经安装的全国行政区/地点索引。
        var qthPath = File.Exists(Path.Combine(dataRoot, "qth_admin.db"))
            ? Path.Combine(dataRoot, "qth_admin.db")
            : Path.Combine(dataRoot, "qth_places.db");
        if (File.Exists(qthPath))
        {
            try
            {
                using var connection = OpenReadOnly(qthPath);
                using var command = connection.CreateCommand();
                command.CommandText = """
                    SELECT name, aliases, province, city, district, canonical_qth, kind
                    FROM qth_places
                    """;
                using var reader = command.ExecuteReader();
                while (reader.Read())
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    var canonical = reader.GetString(5);
                    var candidate = new QthCandidate(
                        canonical,
                        reader.IsDBNull(2) ? "" : reader.GetString(2),
                        reader.IsDBNull(3) ? "" : reader.GetString(3),
                        reader.IsDBNull(4) ? "" : reader.GetString(4),
                        reader.IsDBNull(6) ? "place" : reader.GetString(6),
                        100);
                    AddQth(qths, reader.GetString(0), candidate);
                    AddQth(qths, canonical, candidate);
                    if (!reader.IsDBNull(1))
                    {
                        foreach (var alias in reader.GetString(1)
                                     .Split('|', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                        {
                            AddQth(qths, alias, candidate);
                        }
                    }

                    qthPlaceCount++;
                }
                messages.Add($"全国地点 {qthPlaceCount:N0} 条");
            }
            catch (Exception exception) when (exception is SqliteException or IOException)
            {
                messages.Add($"地点库未载入：{exception.Message}");
            }
        }
        else
        {
            messages.Add("未找到本地地点库");
        }

        var legacyPath = Path.Combine(dataRoot, "ham_checkin.db");
        if (File.Exists(legacyPath))
        {
            try
            {
                using var connection = OpenReadOnly(legacyPath);
                LoadDeviceAliases(connection, devices, cancellationToken);
                LoadSimpleAliases(connection, "antenna_aliases", antennas, cancellationToken);
                LoadSimpleAliases(connection, "power_aliases", powers, cancellationToken);
                LoadQthAliases(connection, qths, cancellationToken);
                messages.Add("旧版自定义别名已只读载入");
            }
            catch (Exception exception) when (exception is SqliteException or IOException)
            {
                messages.Add($"旧别名未载入：{exception.Message}");
            }
        }

        var miitPath = Path.Combine(dataRoot, "miit_radio_catalog.db");
        if (File.Exists(miitPath))
        {
            try
            {
                using var connection = OpenReadOnly(miitPath);
                using var command = connection.CreateCommand();
                command.CommandText = """
                    SELECT normalized_model, standard_name, model, device_name,
                           applicant, brand
                    FROM miit_radio_devices
                    WHERE normalized_model IS NOT NULL AND normalized_model <> ''
                    ORDER BY approved_at DESC
                    """;
                using var reader = command.ExecuteReader();
                while (reader.Read())
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    var key = TextNormalizer.NormalizeKey(reader.GetString(0));
                    if (key.Length == 0 || miit.ContainsKey(key))
                    {
                        continue;
                    }

                    var model = reader.IsDBNull(2) ? "" : reader.GetString(2).Trim();
                    var brand = reader.IsDBNull(5) ? "" : reader.GetString(5).Trim();
                    var standard = reader.IsDBNull(1) ? "" : reader.GetString(1).Trim();
                    if (standard.Length == 0)
                    {
                        standard = string.Join(' ', new[] { brand, model }
                            .Where(static value => value.Length > 0));
                    }
                    if (standard.Length == 0)
                    {
                        standard = model;
                    }

                    miit[key] = new DeviceCandidate(
                        standard,
                        model,
                        reader.IsDBNull(3) ? "" : reader.GetString(3),
                        reader.IsDBNull(4) ? "" : reader.GetString(4),
                        brand,
                        "工信部型号库",
                        0.93);
                }
                messages.Add($"工信部型号 {miit.Count:N0} 个");
            }
            catch (Exception exception) when (exception is SqliteException or IOException)
            {
                messages.Add($"工信部库未载入：{exception.Message}");
            }
        }
        else
        {
            messages.Add("未找到工信部型号库");
        }

        timer.Stop();
        var snapshot = BuildSnapshot(devices, miit, antennas, powers, qths, qthPlaceCount);
        var report = new CatalogLoadReport(
            dataRoot,
            snapshot.DeviceAliasCount,
            snapshot.QthAliasCount,
            snapshot.QthPlaceCount,
            snapshot.MiitModelCount,
            timer.ElapsedMilliseconds,
            string.Join("；", messages));
        return (snapshot, report);
    }

    private static void LoadDeviceAliases(
        SqliteConnection connection,
        IDictionary<string, DeviceCandidate> destination,
        CancellationToken cancellationToken)
    {
        using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT alias, standard_value, source
            FROM device_aliases
            WHERE enabled = 1
            ORDER BY CASE WHEN source = 'user' THEN 0 ELSE 1 END, priority DESC, id DESC
            """;
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var key = TextNormalizer.NormalizeKey(reader.GetString(0));
            var standard = reader.GetString(1).Trim();
            if (key.Length == 0 || standard.Length == 0)
            {
                continue;
            }

            destination[key] = new DeviceCandidate(
                standard, reader.GetString(0), "", "", "",
                reader.IsDBNull(2) || reader.GetString(2) != "user" ? "本地别名" : "用户别名",
                1.0);
        }
    }

    private static void LoadSimpleAliases(
        SqliteConnection connection,
        string table,
        IDictionary<string, string> destination,
        CancellationToken cancellationToken)
    {
        using var command = connection.CreateCommand();
        command.CommandText = $"SELECT alias, standard_value FROM {table} WHERE enabled = 1 ORDER BY priority, id";
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var key = TextNormalizer.NormalizeKey(reader.GetString(0));
            if (key.Length > 0 && !reader.IsDBNull(1))
            {
                destination[key] = reader.GetString(1).Trim();
            }
        }
    }

    private static void LoadQthAliases(
        SqliteConnection connection,
        IDictionary<string, List<QthCandidate>> destination,
        CancellationToken cancellationToken)
    {
        using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT alias, standard_value, province, city, district, source
            FROM qth_aliases
            WHERE enabled = 1
            ORDER BY priority, id
            """;
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var alias = reader.GetString(0);
            var standard = reader.IsDBNull(1) ? "" : reader.GetString(1);
            // The old alias table often stores a short display value such as
            // “南京玄武”. Prefer the nationwide catalog entry already attached
            // to the alias so the native app emits the full province/city/district.
            var existing = FindBest(destination, alias) ?? FindBest(destination, standard);
            var candidate = existing ?? new QthCandidate(
                standard,
                reader.IsDBNull(2) ? "" : reader.GetString(2),
                reader.IsDBNull(3) ? "" : reader.GetString(3),
                reader.IsDBNull(4) ? "" : reader.GetString(4),
                "local_alias",
                2000);
            AddQth(destination, alias, candidate with { Priority = 2000 });
        }
    }

    private static QthCandidate? FindBest(
        IDictionary<string, List<QthCandidate>> source,
        string query)
    {
        var key = TextNormalizer.NormalizeKey(query);
        if (key.Length == 0 || !source.TryGetValue(key, out var candidates))
        {
            return null;
        }

        return candidates.OrderBy(static item => item.Depth).FirstOrDefault();
    }

    private static SqliteConnection OpenReadOnly(string path)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Shared,
            Pooling = true
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }

    private static CatalogSnapshot BuildSnapshot(
        IReadOnlyDictionary<string, DeviceCandidate> devices,
        IReadOnlyDictionary<string, DeviceCandidate> miit,
        IReadOnlyDictionary<string, string> antennas,
        IReadOnlyDictionary<string, string> powers,
        IReadOnlyDictionary<string, List<QthCandidate>> qths,
        int qthPlaceCount) => new(
            new Dictionary<string, DeviceCandidate>(devices, StringComparer.Ordinal),
            new Dictionary<string, DeviceCandidate>(miit, StringComparer.Ordinal),
            new Dictionary<string, string>(antennas, StringComparer.Ordinal),
            new Dictionary<string, string>(powers, StringComparer.Ordinal),
            qths.ToDictionary(
                static item => item.Key,
                static item => (IReadOnlyList<QthCandidate>)item.Value
                    .DistinctBy(static value => value.Canonical, StringComparer.Ordinal)
                    .ToArray(),
                StringComparer.Ordinal),
            qthPlaceCount);

    private static void AddDevices(
        IDictionary<string, DeviceCandidate> destination,
        string source,
        IEnumerable<(string Alias, string Standard)> values)
    {
        foreach (var (alias, standard) in values)
        {
            var key = TextNormalizer.NormalizeKey(alias);
            destination[key] = new DeviceCandidate(standard, alias, "", "", "", source, 1.0);
        }
    }

    private static void AddAliases(
        IDictionary<string, string> destination,
        IEnumerable<(string Alias, string Standard)> values)
    {
        foreach (var (alias, standard) in values)
        {
            destination[TextNormalizer.NormalizeKey(alias)] = standard;
        }
    }

    private static void AddQth(
        IDictionary<string, List<QthCandidate>> destination,
        string alias,
        QthCandidate candidate)
    {
        var key = TextNormalizer.NormalizeKey(alias);
        if (key.Length == 0)
        {
            return;
        }

        if (!destination.TryGetValue(key, out var values))
        {
            values = new List<QthCandidate>();
            destination[key] = values;
        }

        var current = values.FindIndex(item => string.Equals(
            item.Canonical, candidate.Canonical, StringComparison.Ordinal));
        if (current >= 0)
        {
            if (candidate.Priority > values[current].Priority)
            {
                values[current] = candidate;
            }
            return;
        }
        values.Add(candidate);
    }
}
