# 旧 Python SQLite → Native 兼容说明

## 范围与结论

本页描述当前 `LegacyPythonMigration` 代码及其隔离合成测试所覆盖的范围，不代表完整旧版数据库格式目录，也不代表真实用户库迁移已验收。迁移器只处理旧库 `sessions` 与 `checkins` 的显式字段白名单；用 `PRAGMA table_info` 检查存在列，未列入查询的旧字段不导入。缺失表、未支持的 `user_version` 或身份列契约不匹配会拒绝整批导入（[源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L292)、[版本校验](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L553)）。

实现规则接受 `user_version` 1–5 且没有身份三元组列，或 6–10 且恰有 `external_source`、`external_uid`、`external_key` 三列。测试只对若干代表版本和合成 schema 作断言；不能据此推定所有历史发行版或自定义 schema 均兼容。

## sessions 字段

| 旧字段 | Native 去向 / 分类 | 规则与边界 | 证据 |
| --- | --- | --- | --- |
| `id` | `native_meta` 的旧场次→Native 场次映射；不作为 Native 主键 | Native 场次使用新 ID，映射记录旧 ID、Native ID、源和判定信息。 | [迁移源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L172)、[Native ID 查询](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L190)、[映射写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L201)、[新 ID 断言](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L63)、[映射断言](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L90) |
| `name`, `date` | `sessions.name/date`，保留 | 空值分别规范为“旧版场次”和 `1970-01-01`；这会丢失原始空值状态。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L105)、[默认值测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L210) |
| `status` | `sessions.status`，归一化 | 仅不区分大小写的 `ended` 保留为 `ended`；其他值一律成为 `active`。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L180)、[归一化](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L709) |
| `operator_callsign`, `repeater_name` | 同名 Native 场次字段，保留 | 值按文本读取；缺失或 NULL 变为空字符串。 | [字段读取](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L322)、[写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L181) |
| `excel_path`, `excel_sheet_name` | `sessions.workbook_path/sheet_name`，改名保留 | Excel 文件本身不搬迁；只保存路径/工作表文本。 | [字段读取](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L326)、[工作表读取](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L330)、[写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L183) |
| `started_at`, `ended_at`, `created_at`, `updated_at` | 同语义 Native 时间字段，保留 | `started_at/created_at/updated_at` 空值改用当前 UTC 时间；`ended_at` 空值保留为空。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L185)、[时间默认](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L712)、[测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L215) |
| `external_source`, `external_uid`, `external_key` | `native_meta` 映射记录，非 Native 场次业务字段 | 按 1–5 / 6–10 版本契约全无或全有；部分列、重复身份或缺列与版本不符时整批拒绝。 | [版本/身份校验](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L560)、[映射写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L201)、[正向测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L471)、[拒绝测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L502) |

## checkins 字段

| 旧字段 | Native 去向 / 分类 | 规则与边界 | 证据 |
| --- | --- | --- | --- |
| `id` | `submission_id` 编码为 `legacy-python:<旧id>`；不作为 Native 主键 | 缺失旧 ID 用 0，因此会生成 `legacy-python:0`；重复提交键会被跳过。 | [submission_id 生成/重复检查](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L216)、[默认测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L229) |
| `session_id` | 通过旧场次映射关联 Native 场次 | 找不到可导入的父场次则跳过该签到；不直接复用旧场次 ID。 | [筛选](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L207)、[写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L238) |
| `sequence_no` | `checkins.sequence_no`，归一化 | 小于 1 改为 1；遇到活动记录冲突时向上递增到可用序号。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L226)、[冲突检查](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L227) |
| `checkin_time`, `callsign`, `qth_raw/standard`, `device_raw/standard`, `antenna_raw/standard`, `power_raw/standard`, `signal`, `raw_input`, `unmatched` | 对应 Native `checkins` 字段，保留文本 | 原文与既有标准值分别复制，不由迁移器重新解析；缺失或 NULL 文本成为空字符串。 | [字段白名单](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L370)、[Native 写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L235)、[字段断言](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L79) |
| `source` | `checkins.source` | 空白来源改为 `legacy-python`；非空值保留。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L264) |
| `is_deleted` | 不迁移已删除行；导入行写 `0` | 非 0 的行以及没有可映射场次的行计入 skipped。 | [筛选](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L209)、[写入](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L247) |
| `created_at`, `updated_at` | 同名 Native 时间字段，保留 | 空值改用当前 UTC 时间。 | [源码](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L268)、[默认值](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L712) |
| 旧 `excel_sync_status`（若存在） | 不读取；Native 状态固定为 `deferred` | 旧同步状态不保留，导入记录需由 Native 同步路径后续处理。 | [Native INSERT](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L237) |

存在列的 NULL 文本使用空字符串、缺列使用 SQL fallback；表内 ID/父 ID/序号/删除标记缺列时的读取 fallback 为 0（[fallback 实现](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L409)）。此类默认折叠了“缺失、NULL、空值”的差别，不能据 Native 结果反推出旧值原先属于哪一种。

## 仍只读使用或不纳入本次导入

### 旧库位置与持续只读依赖

默认旧库为 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin.db`：`AppPaths.Root` 默认位于 LocalApplicationData 下的 `HAM点名助手`，`DataRoot` 加入 `data`，`LegacyDatabasePath` 指向 `data/ham_checkin.db`；测试/预览可覆写 root。[LocalApplicationData路径](../src/HamCheckin.Native.Core/Storage/AppPaths.cs#L7)、[Root默认值](../src/HamCheckin.Native.Core/Storage/AppPaths.cs#L16)、[DataRoot](../src/HamCheckin.Native.Core/Storage/AppPaths.cs#L31)、[LegacyDatabasePath](../src/HamCheckin.Native.Core/Storage/AppPaths.cs#L44)

| 持续只读用途 | 入口/字段与筛选 | 缺库或读取错误的影响 | 源码证据 |
| --- | --- | --- | --- |
| CatalogLoader 旧别名叠加 | 以 `dataRoot/ham_checkin.db` 打开旧库，只读载入 `device_aliases`、`antenna_aliases`、`power_aliases`、`qth_aliases`；各查询限定 `enabled = 1`。字段包括设备的 `alias/standard_value/source`、简单别名的 `alias/standard_value`，以及 QTH 的 `alias/standard_value/province/city/district/source`。 | 文件不存在时跳过旧别名分支，该来源的别名不载入；受支持的读取异常会标记目录读取错误并报告“旧别名未载入”，load report 的 `Succeeded` 为 false。 | [旧库路径](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L322)、[缺库分支](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L325)、[读取异常报告](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L335)、[设备筛选/字段](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L441)、[简单别名筛选/字段](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L472)、[QTH筛选/字段](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L491)、[报告状态](../src/HamCheckin.Native.Core/Catalogs/CatalogLoader.cs#L410) |
| LegacyProfileReader 按呼号读取画像 | `ReadAsync` 可传 `databasePath`，默认使用上述旧库；SQLite 以 ReadOnly 打开。只查询 `checkins` 的 `qth_standard/device_standard/antenna_standard/power_standard` 与 `COALESCE(updated_at, created_at, '')`，按 `callsign` 且 `is_deleted = 0` 筛选，`id DESC` 排序并 `LIMIT 300`。 | 空白呼号或文件不存在返回空列表；打开、缺表/列、损坏库或 SQL 错误没有在该方法中被转换为空列表，作为异步读取错误传播。 | [方法签名](../src/HamCheckin.Native.Core/Storage/LegacyProfileReader.cs#L7)、[默认路径与缺库处理](../src/HamCheckin.Native.Core/Storage/LegacyProfileReader.cs#L12)、[只读连接](../src/HamCheckin.Native.Core/Storage/LegacyProfileReader.cs#L18)、[字段/筛选/300条上限](../src/HamCheckin.Native.Core/Storage/LegacyProfileReader.cs#L28) |

`ProfileAggregator` 对这最多 300 条未删除签到记录的 QTH、设备、天线、功率字段分别忽略空白值并按 `OrdinalIgnoreCase` 分组；每个字段只返回出现次数最多的一项，次数相同按最后时间降序。因此画像只是按呼号得出的至多四个聚合值，不是完整历史、全库迁移，也不是替代目录；[聚合规则](../src/HamCheckin.Native.Core/Storage/ProfileAggregator.cs#L5)、[分组与选值](../src/HamCheckin.Native.Core/Storage/ProfileAggregator.cs#L21)。

本次对 `native/src` 与 `native/tests` 中 `LegacyProfileReader` / `ProfileAggregator` 的文本搜索只发现类声明及 Reader 内部调用 `Aggregate`，未发现直接调用点；LegacyProfileReader 的实际用户入口未知。此静态搜索不证明全局不存在其他调用，也不构成删除或判定无用的依据。

### 其他未纳入本次导入

| 数据 / 来源 | 分类 | 证据 |
| --- | --- | --- |
| 其他表、未列入 SELECT 白名单的列、未知历史字段 | 未证明 / 不导入 | 当前迁移器的读取白名单见 [sessions](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L318) 与 [checkins](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L370) 查询；不得按字段名猜测映射。 |

## 源库保护、备份与不可逆边界

旧库以 SQLite ReadOnly 模式读取；迁移前用 `VACUUM INTO` 生成独立备份，实际导入只写入 Native 库及其 `native_meta` 映射/状态。隔离测试逐值比较源库与备份，确认二者都保持原内容（[只读读取与备份](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L292)、[VACUUM INTO](../src/HamCheckin.Native.Core/Storage/LegacyPythonMigration.cs#L412)、[测试](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L88)）。

不可逆的信息边界：Native 主键会重建；时间/名称/状态/序号可能被默认或归一化；已删除/孤立签到会跳过；旧 Excel 同步状态与未列出的字段不会进入 Native 记录。备份和旧源可以回查，但当前合同没有“从 Native 反向还原为原始旧库”的路径。真实历史库版本分布、未见 schema、自定义字段及生产库迁移结果均未验证。

## 隔离验收证据

`LegacyPythonMigrationTests` 的本地合成 SQLite 目标运行记录为 4 passed / 0 failed / 0 skipped（`legacy-python-migration-tests-20261115.log`）；测试分别覆盖可用字段/源与备份保留、NULL/缺列默认、选定版本身份契约与整批拒绝路径（[测试源码](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L12)、[默认值](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L177)、[版本与身份](../tests/HamCheckin.Native.Tests/LegacyPythonMigrationTests.cs#L428)）。这是有限合成 fixture 证据，不是所有旧版发行物、真实用户库或生产迁移 PASS。
