# TODO：中央项目任务台账

更新日期：2026-11-20

本文件是唯一的长期项目任务入口。任务状态只按可核验结果更新；未开始不等于阻塞，审计发现不等于已修复。Phase0 的详细证据仍以[综合审计](docs/audit/PHASE0_AUDIT_REPORT.md)、[原任务合同](docs/audit/PHASE0_TODO.md)、[问题详细清单](docs/audit/ISSUE_INVENTORY.md)为准；以下保留其82项任务及完整依赖/验收字段，Phase0文件未修改。

Phase0来源任务的ID与含义在根表中保持不变；本轮长期上下文的六项独立交付仅由 `CTX-001..006` 跟踪，不复用审计任务编号。

## 任务规则

- 每项含八字段：TaskID、名称、描述、优先级、状态、依赖、文件/模块、可复现验收。
- 优先级 P0–P3 是执行顺序，不是漏洞严重性。依赖必须满足才开始；未开始的下游项保留 `[ ]`，不得机械标成阻塞。
- 状态仅用 `[ ] Todo`、`[/] In Progress`、`[x] Done`、`[!] Blocked`。Done 必须有该行验收证据；CI/构建/现场/UI未运行不能写 PASS。
- Phase0来源任务共82项：NAT 27、ENG 19（含 ENG-000 前置）、LB 11、MEDIA 7、DOC 1、PLAN 17；原基线79项待办、3项有范围限制的完成。Phase1上下文交付任务CTX-001..006已通过文件与链接校验。当前中央台账共88项：54项[ ]待办、1项[/]进行中、26项[x]完成、7项[!]阻塞（未完成合计62项）；其中完成项只代表各自行内定义的范围，不表示产品功能或测试已通过。
- 语义审查声音/语音已由用户取消，因此不新增该类任务，也不迁移被删的 MEDIA-TODO-04。保留 MEDIA-TODO-01/02 的有限范围已完成状态，以及现有录屏/麦克风产品功能与测试；不改原视频音轨，不把历史素材观察当作当前产品复现。
- 已确认的完整UI合同不是待决项：Phase2 IA / 候选设计规范文档及七项方向确认已完成；三主题为跟随系统/浅色/深色；全软件重设计并保留全部业务功能。具体实现与验收仍按后续任务推进，见[项目上下文](docs/PROJECT_CONTEXT.md)和对应 PLAN/NAT 任务。
- 当前用户目标授权继续完成TODO中的项目工作，包括本地C#/WPF源码工作及合成/隔离测试；仍须遵守任务依赖、计划审批和测试闸。ENG-000是Phase 3本地runtime工作的全局Code Gate；其[x]仅记录有限本地授权，不自动放行任何特别操作。联网restore/download/sync、生产数据库操作、真实桌面/外设验收仍须各自安全门与单独授权；正式发布/publish须另行授权；Git commit和Git push不在本任务授权内，二者各自均须单独授权；本任务仅文档。问题修复须有证据并更新[问题索引](docs/ISSUE_INVENTORY.md)与CHANGELOG。

## Phase0来源任务（82项）

## Native任务（27项）
| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NAT-T001 | 冻结基线 | 唯一C#范围、dirty差异、隔离授权与问题→测试。 | P0 | [x] | ENG-000 | README；native/docs；Git元数据 | Phase0只读记录branch codex/ham-checkin-release、HEAD 1fd20a9b7d44a8fcad6af81c04c35697dcf0e013、11项既有Native dirty文件及6168个原未跟踪路径；225个基线SHA未变。仅完成基线冻结与归属，不覆盖工作、不删历史功能；不代表全6168项均做过hash验证。 |
| NAT-T002 | 全量导出 | 修复5000截断，独立对账。 | P0 | [ ] | NAT-T001、ENG-014 | C/Storage/NativeStore.cs；C/Export/ExcelExportService.cs；T/NativeEndToEndTests.cs | 5000/5001/10000/10001条DB count、首末序号/字段一致，失败不报成功。 |
| NAT-T003 | 导出请求/目标 | 固定会话、净化basename、显式路径级覆盖授权。 | P0 | [x] | NAT-T001 | A/ViewModels/MainViewModel.cs；C/Export/ExcelExportService.cs | 固定场次快照、目录/path sanitizer和临时工作簿验证；未确认现存目标不覆盖，竞争新建目标失败关闭。用户确认授权替换所选路径提交时的当前文件，确认框默认 `MessageBoxResult.No`；确认后外部修改仍可能被替换，非内容/hash/file-ID CAS。SDK 10.0.401 `--no-restore`：Native `ExcelExportTests`、`NativeEndToEndTests`、`VideoReplayEndToEndTests` 16/16；UI `ExportUsesCapturedSessionAfterSwitching` 1/1，默认No改动后再次1/1（均exit 0）。UI NOT VERIFIED: 本次自动化窄测未交互验证模态确认默认No，也未验证真实桌面、DPI/IME/读屏/真实Excel。
| NAT-T004 | Native备份恢复 | 在线一致快照、元数据、校验与保留合同。 | P0 | [ ] | NAT-T001 | C/Storage/AppPaths.cs、NativeStore.cs；获准备份实现 | 合成库恢复逐表/原文/审计对账；坏备份/磁盘满/占用fail-closed，不用生产库。 |
| NAT-T005 | 一致快照导入 | 从同一已验证备份导入旧格式并解释结果。 | P0 | [ ] | NAT-T004、LB-T02、ENG-014 | C/Storage/LegacyPythonMigration.cs；A/ViewModels/MainViewModel.cs；T/LegacyPythonMigrationTests.cs | 并发WAL、VACUUM失败、中断/取消/重复/skip可核；无完成假标记，源不变，不运行Python。 |
| NAT-T006 | schema升级 | 有向版本迁移、未来拒绝、原子回滚。 | P0 | [ ] | NAT-T004、ENG-014 | C/Storage/NativeStore.cs；获准迁移定义 | v1/v2/v3路径与v4拒绝有隔离证据，不降标/半升级，备份回滚可验证。 |
| NAT-T007 | 事务不变量 | active、记录归属、呼号和编辑版本下沉存储。 | P0 | [ ] | NAT-T001、ENG-014 | C/Storage/NativeStore.cs、Models.cs；A/ViewModels/MainViewModel.cs；T/NativeStoreTests.cs | 直接Store/错场/ended/空呼号/结束交错/编辑冲突拒非法写；合法重复呼号保留。 |
| NAT-T008 | 字段采用/确认 | 最终片段集合、真实选择复制、确认标记、未知设备。 | P1 | [ ] | NAT-T007 | A/Views/FieldEditWindow.xaml及代码；C/Parsing/FieldParser.cs | A后B只消费最终明确采用项；重复索引/取消/手改/清空/确认及零一多候选，不擅改型号。 |
| NAT-T009 | 重建资料快照 | 内置/外部独立层与世代发布。 | P1 | [x] | NAT-T001 | C/Catalogs/CatalogService.cs、CatalogLoader.cs、CatalogSnapshot.cs；T/CatalogLoaderTests.cs | 已验收：每次重载以fresh built-in + 指定root overlay重建快照；generation校验阻止过期结果覆盖新快照，失败/取消保留Current，热路径静态检查无磁盘/SQLite/网络/Loader调用。SDK 10.0.401 Release solution build exit 0（14 warnings/0 errors）；CatalogLoaderTests 15 passed/0 failed/0 skipped，CatalogPublicationViewModelTests 7 passed/0 failed/0 skipped；correctness复审0 Critical/0 Major。真实桌面UI未验证。本项不代表NAT-T010/LB-T06/PLAN-P3-CATALOG完成。 |
| NAT-T010 | 别名优先级 | 确认人工/本地/内置/MIIT归一化冲突。 | P1 | [x] | NAT-T009、LB-T06 | C/Catalogs/CatalogLoader.cs、CatalogSnapshot.cs；T/CatalogLoaderTests.cs | 已核对当前源码优先序为用户别名 > 本地别名 > 内置别名 > 工信部型号库；指定合成/预览测试覆盖本地别名胜同名MIIT、user/default优先级与disabled过滤、同键异canonical QTH保持歧义、人工QTH待确认及UI显式候选选择/同草稿后台重解析后选择保持。使用.NET SDK 10.0.401、`--no-restore`串行运行：Core 5 passed/0 failed/0 skipped，UI 2 passed/0 failed/0 skipped，均exit 0。仅验收上述静态顺序和合成/预览路径，不代表所有目录来源组合或真实地点数据验收。 |
| NAT-T011 | 场次/导航真源 | 请求版本、提交完成、唯一导航状态。 | P1 | [ ] | NAT-T007、NAT-T001 | A/ViewModels/MainViewModel.cs、Views/MainView.xaml.cs；U/QuickInputUiTests.cs | 延迟提交与结束/重开/元信息/连续切场交错，DB、VM、可见页一致。 |
| NAT-T012 | MIIT单作业/续传 | 等取消完成、同路径互斥、正确大页游标。 | P1 | [ ] | NAT-T009、ENG-014 | A/ViewModels/MainViewModel.cs；C/Catalogs/MiitCatalogSyncService.cs；T/MiitCatalogSyncTests.cs | Running/Cancelling/Settled真实，1000条大页恢复正确，重页/空页/总数变化/401/403/超时/取消保正式库。 |
| NAT-T013 | MIIT数据合同 | 筛选、隐藏注销状态和副索引。 | P1 | [ ] | NAT-T012、ENG-000 | C/Catalogs/MiitCatalogSyncService.cs、CatalogLoader.cs；资料UI | 续证/包含排除冲突/隐藏注销/未知名称有fixture；模拟与官网分列，不假全量，访问拒绝停止。 |
| NAT-T014 | PCM/COM及释放 | 先平台复核，再回调错误隔离/失败释放设备。 | P1 | [ ] | PLAN-P4-PLATFORM、ENG-000 | A/Media/MicrophoneCapture.cs、MediaFoundationInterop.cs、ScreenRecordingService.cs | 核对.NET10 Math.Abs/SDK ABI后，-32768..32767、订阅异常、无设备/权限/拔设备不崩溃，失败释放，不先判ABI错。 |
| NAT-T015 | 媒体时钟/尺寸 | 公共时钟、帧deadline、暂停和resize策略。 | P1 | [ ] | NAT-T014 | A/Media/ScreenRecordingService.cs、ScreenCapture.cs、Mp4FileWriter.cs | 获批长录/帧率/漂移阈值；负载/暂停/resize/跨DPI真实解码播放及音画同步达标，不靠FourCC。 |
| NAT-T016 | 初始化/关闭 | 异步恢复及跟踪提交、导出、资料、录屏作业。 | P1 | [ ] | NAT-T007、NAT-T012、NAT-T014 | A/App.xaml.cs、MainWindow.xaml.cs、Views/MainView.xaml.cs、ViewModels/MainViewModel.cs | UI不同步等待窗口消息采集；Stop/关闭/更新退出无死锁/假成功，草稿与已提交结果可解释。 |
| NAT-T017 | 更新安全收尾 | 安装握手、旧EXE回滚、签名/URI/体积模型。 | P1 | [ ] | ENG-000、PLAN-P2-DESIGN | C/Updates/NativeUpdateService.cs；A/Views/AboutWindow.xaml.cs | 错hash/PE/恶意scheme/超量/取消/权限/锁定/重启失败有隔离证据；temp篡改不执行、旧EXE可恢复，不擅发布。 |
| NAT-T018 | 动作/设置持久化 | 统一可执行快捷动作/作用域，独立Native配置。 | P1 | [!] | ENG-000、PLAN-P2-IA | A/Infrastructure、ViewModels/MainViewModel.cs；输入/字段视图 | 阻塞：静态检查未证实快捷键配置有独立Native持久化/重启加载；部分绑定未接入动作分发，Win modifier不能由设置UI录入，冲突比较/可见性有缺口（`MainViewModel.cs:65-99,540-594`; `MainView.xaml.cs:287-318,751-767,1038-1056`; `ShortcutGesture.cs:38-53`; `GlobalHotkeyService.cs:20-47,74-81`; `MainView.xaml:245`）。TODO明确要求记录撤销语义先确认，但尚无获批规则。解除条件：明确撤销范围/确认流程，完成独立配置及动作/Win/冲突可见行为，再用隔离配置和合成UI测试验证重启保留；未接触用户配置/生产DB，未运行代码或测试。 |
| NAT-T019 | 可见状态/错误 | 绑定作业/快捷状态，捕获地点树异常，区分刷新下载。 | P1 | [ ] | NAT-T012、PLAN-P2-IA | A/Views/MainView.xaml及代码、ViewModels/MainViewModel.cs；C/Catalogs/QthPackageService.cs | busy/cancelling/failed/未配置可见，坏库不退出，本地刷新不宣称远程下载成功。 |
| NAT-T020 | 完整本场浏览 | 最近缓存与分页/总数/定位编辑分离。 | P1 | [ ] | NAT-T007、PLAN-P2-IA | A/ViewModels/MainViewModel.cs、Views/MainView.xaml；C/Storage/NativeStore.cs | 301/5001条重启切场仍能定位最早记录，编辑/导出一致，不用全表阻塞UI。 |
| NAT-T021 | 性能基线/优化 | 先版本绑定，再解析/目录索引缓存优化。 | P2 | [ ] | NAT-T009、NAT-T010、ENG-002、ENG-017 | C/Catalogs/CatalogSnapshot.cs、Parsing/InputParser.cs；B/Program.cs | 完整/缺库/10万目录/中文长输入p50/p95/p99及Dispatcher，原文/候选/金标准不退，不延迟丢输入刷分。 |
| NAT-T022 | 三主题桌面适配 | 按已定合同实现跟随系统、浅色、深色。 | P1 | [ ] | ENG-000、PLAN-P2-DESIGN | A/App.xaml、app.manifest、全部Views/MainWindow和样式资源 | 既有源码实现、2026-11-17 SDK 10.0.401 Release build 结果为 0 errors；保留的 Release 构建日志含 54 行原始 warning 诊断记录（包含项目重复发出的诊断行），按项目/文件/行/列/代码/消息组合去重后，共 27 条项目范围内的不同诊断，涉及 8 种诊断代码；Category!=Hardware测试（303/303）及correctness review（0 Critical/0 Major）为独立证据。2026-11-20仅在Windows 11 build 26300 x64对指定Release apphost作隔离桌面观测：应用内Light/Dark/FollowSystem可见；实际Apps主题Dark及“水生”高对比设置引发用户可见变化，合成草稿仍在且未提交，系统设置已恢复；apphost SHA及截图见[验收记录](native/docs/VERIFICATION.md)。精确通知映射仍NOT_VERIFIED（ledger #116仍阻塞）；Windows 10、其他DPI、多显示器/混合DPI、实际IME、Narrator及更广可访问性矩阵NOT_RUN；选择保留NOT_TESTED。本次未构建/测试/发布。本行保持[ ]。 |
| NAT-T023 | Native滚动回归 | 33来源风险逐批绑定当前源码/EXE。 | P1 | [ ] | ENG-002、ENG-014、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、NAT-T008、NAT-T009、NAT-T010、NAT-T011、NAT-T012、NAT-T013、NAT-T014、NAT-T015、NAT-T016、NAT-T017、NAT-T018、NAT-T019、NAT-T020 | native/tests；native/docs/VERIFICATION.md；批准隔离产物 | 各批SHA+dirty/SDK/OS/DPI/EXE SHA/TRX/日志齐，失败/Skip/BLOCKED/NOT_RUN分列，不继承旧PASS。 |
| NAT-T024 | 证据驱动拆分 | 行为锁定后一次一个真实职责边界。 | P2 | [ ] | NAT-T001、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、NAT-T023 | A/ViewModels/MainViewModel.cs；MainView/About代码；对应Core | 可回退、业务性能不退，仍C#/WPF/.NET10/SQLite/OpenXml，不删字段、不预建服务层。 |
| NAT-T025 | 治理入口/证据 | 当前C#、历史标签、版本/能力/验收分开。 | P2 | [ ] | ENG-000、DOC-001 | README.md；native/README.md；native/docs；本审计包 | 当前运行无pip/python要求，旧章标历史，源码1.0.20与1.0.19-r29历史候选分开；没有当前1.0.20产物动态验收证据，任务保持开放；既有文档仅获准后改。 |
| NAT-T026 | 保留范围合同 | 撤销/补同步/画像学习/历史导入/365dt/远程地点包。 | P2 | [x] | ENG-000 | A/ViewModels/MainViewModel.cs；C/Storage/LegacyProfileReader.cs、Catalogs/QthPackageService.cs；需求记录 | 用户“不删既有业务功能”约束与29项功能清单已覆盖范围决策：所有既有能力须保留；未接线项保持待接/兼容，不作假实现，F28仍待业务验证。此Done仅表示范围决定，不是任何功能实现或兼容验收；具体功能仍由各自TODO验收，不加未确认QSO/ADIF。 |
| NAT-T027 | 资源/隐私基线 | 行政区别名来源生成链、包和本地隐私。 | P2 | [ ] | ENG-000、ENG-005 | C/Catalogs/NationwideAdminCatalog.cs、CatalogLoader.cs、nationwide-admin.tsv.gz.b64；csproj | 来源/日期/license/hash/生成可追溯，独立金标准不自证；ACL/可选加密取舍明确，当前漏洞另核、不上传。 |
## 工程任务及前置（19项）
| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENG-000 | 分项操作授权 | 记录持续目标下的本地工作范围与独立安全闸。 | P0 | [x] | 无 | C#产品；Git；候选/稳定；遗留工具 | 用户已授权按TODO继续本地C#/WPF源码工作及合成/隔离测试，须遵守任务依赖、计划与测试闸；按Phase0保护11项既有Native dirty文件及6168个原未跟踪路径。联网restore/download/sync、生产DB、真实桌面/外设仍分别另行授权；稳定发布/publish须另行授权；Git commit和Git push不在本目标授权内，二者各自均须单独授权；本Done只关闭授权范围矩阵，不放行这些操作。 |
| ENG-001 | 当前C# PR Gate | 普通PR/开发分支复用Native编译/xUnit。 | P0 | [x] | ENG-000、ENG-002 | .github/workflows/ci.yml；Native sln/xUnit | 已验收：workflow静态确认pull_request及main push触发、独立Windows/.NET 10 job、Python 3.11/3.12 matrix保留、`Category!=Hardware`/2m blame/TRX/metadata artifact；SDK 10.0.401 Release solution build exit 0（0 warnings/0 errors），Native Core tests 207 passed/0 failed/0 skipped；合成编译错误与断言错误注入均触发预期失败。仅本机验证，远端GitHub Actions未运行。 |
| ENG-002 | SDK/资产 | 选定SDK10、TFM/RID及隔离资产。 | P0 | [x] | ENG-000 | SDK策略；5csproj/sln；隔离obj | 本机使用 `native/README.md` 所列 .NET SDK 10.0.401（`%USERPROFILE%\.codex\dotnet10\dotnet.exe`）；release workflow声明 `10.0.x`。用本地NuGet缓存作为唯一source、禁用NuGetAudit，执行 `native/HamCheckin.Native.sln --runtime win-x64` restore成功（exit 0）；5项目assets均为 `net10.0` / `net10.0-windows` 并含 `win-x64` target；未以旧 `net8` assets构建。未运行build/test；ENG-001普通PR Native Gate已配置且本地离线门禁验收通过；未运行远端GitHub Actions。 |
| ENG-003 | 产品/工具边界 | 当前运行说明与Python发布工具分开。 | P1 | [x] | ENG-000 | README/native文档；release.yml；release.py | 根README明确现行Native工程版本1.0.20来自App csproj且不宣称远端Release已核验；Python旧版运行/备份/打包段落标为历史。release workflow从csproj取版本并显式传release.py --version，直接省略时退回历史version.py 0.9.4；Native为win-x64自包含目标，开发SDK/发布SDK范围、Native测试过滤及PR Native gate配置/远端未运行状态均有说明。只改文档；未运行发布/构建/测试。 |
| ENG-004 | 唯一版本权威 | 派生一致性及候选证据绑定。 | P0 | [ ] | ENG-000、ENG-002 | App csproj/manifest/NativeVersion/UI/测试/发布元数据 | 任一源不一致被拦截；commit/dirty/EXE hash齐，候选与稳定指针分离。 |
| ENG-005 | 供应/复现策略 | SDK/Actions/依赖图锁定及漏洞来源。 | P1 | [!] | ENG-000、ENG-002 | 依赖/SDK/CI；获准锁定策略 | 阻塞：Python有`requirements.txt`精确项但pyproject/CI/Release仍有范围或未固定工具；Native直接NuGet有版本号但SDK选择`10.0.x`、未启用锁定模式，本地未见`global.json`/NuGet锁文件；Actions为`@v4`/`@v5`可变tag；静态检查范围未见漏洞扫描步骤/带时间、来源、版本的扫描证据（`requirements.txt:1-7`; `pyproject.toml:6-20`; `.github/workflows/ci.yml:16-24,43-49,85`; `.github/workflows/release.yml:19-40,85-125`; Native csproj与`release.py:41-46,123-141`）。版本号/EXE SHA256不等于扫描通过，离线未知不代表无漏洞。解除条件：批准依赖来源和锁定策略并可重建同一图/漂移失败；有获授权的扫描数据源/工具后记录扫描时间、来源、版本。未联网或运行安装/restore/build/scan。 |
| ENG-006 | 不可变发布 | promotion、并发/降级保护与权限。 | P1 | [ ] | ENG-004、ENG-005、ENG-014 | .github/workflows/release.yml；双清单 | 同Tag不静默改hash，旧/并行Tag不回退latest，上传/回读失败不切指针；专用仓库或获准演练。 |
| ENG-007 | 更新事务 | 复用下载器补安装/回滚/URI/限额/签名。 | P1 | [ ] | ENG-000、ENG-004、ENG-005、ENG-014 | C/Updates/NativeUpdateService.cs；A/Views/AboutWindow.xaml.cs | 非法URL/hash/超量拒绝，temp篡改不执行；权限/锁定/重启失败保旧EXE，用户数据hash不变。 |
| ENG-008 | 旧数据一致导入 | 备份与导入共用可恢复快照。 | P0 | [ ] | ENG-000、ENG-002、ENG-009、ENG-014 | C/Storage/LegacyPythonMigration.cs；迁移测试 | WAL/并发/损坏/中断恢复及计数对账，或完全不标完成；源不改，自动策略明确。 |
| ENG-009 | Native恢复/schema | 未来版本拒绝及备份恢复策略。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs；备份恢复合同 | 旧/当前/未来schema、半升级、坏备份、恢复失败有隔离证据，不覆盖生产好库。 |
| ENG-010 | 独立全量查询 | 导出与分页UI分离，DB独立对账。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs、Export/ExcelExportService.cs；T/NativeEndToEndTests.cs | 5001/10001首末序号/字段/行数一致；保留临时/OpenXml/InlineString，不用截断rows.Count自证。 |
| ENG-011 | ended写约束 | 所属场次可写性落事务。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs；A/ViewModels/MainViewModel.cs；Store/UI测试 | 直接API/旧状态/并发/双Store不能写ended；成功记录及审计保留。 |
| ENG-012 | 导出覆盖/快照 | 固定会话及保护人工工作簿。 | P0 | [ ] | ENG-000、ENG-002、ENG-010、ENG-014 | A/ViewModels/MainViewModel.cs；C/Export/ExcelExportService.cs | 切场不混标题数据；未同意人工列/公式旧文件字节不变，取消失败保原输出。 |
| ENG-013 | 资料作业安全 | 取消完成/同路径互斥/重载/断点/响应限额。 | P1 | [ ] | ENG-000、ENG-002、ENG-014 | A/ViewModels/MainViewModel.cs；C/Catalogs/MiitCatalogSyncService.cs、CatalogLoader.cs、CatalogService.cs | 取消重试保正式库/断点，型号更新不残留，401/403/分页失败hash不变；官网另许可。 |
| ENG-014 | 先故障契约 | 分层媒体、超时和当前结果归档。 | P0 | [/] | ENG-000、ENG-002 | native/tests；CI；MIIT正式库/媒体fixture | 已完成门禁实现/本地合成验收：SDK 10.0.401 Release solution build exit 0（0 warnings/0 errors）；临时xUnit过滤器验证 `Category!=Hardware` 与 `Category=Hardware` 各选中1项并通过；`QuickInputUiTests.cs` 的硬件用例含显式授权守卫和无设备Skip；合成编译/断言故障日志证明对应步骤失败。correctness review approve（0 Critical/0 Major，1 Minor：麦克风枚举WaitAsync超时不会取消原生枚举，延迟异常可能未观察）。仍未完成：真实设备/桌面行为与远端GitHub Actions未运行（NOT_RUN），故任务保持In Progress。 |
| ENG-015 | 设置/撤销语义 | 先确认持久化与记录级撤销范围。 | P1 | [ ] | ENG-000、ENG-014、PLAN-P2-IA | A/ViewModels/MainViewModel.cs；C/Storage/NativeStore.cs；配置/输入/字段UI | 保留则重启设置恢复，撤销有事务/审计/场次/并发/导出语义；不支持不宣称，文字撤销不等记录撤销。 |
| ENG-016 | 真实重复收敛 | 契约稳定后输入适配/字段元数据/token消费。 | P2 | [ ] | ENG-001、ENG-008、ENG-009、ENG-010、ENG-011、ENG-012、ENG-013、ENG-014 | MainView/QuickWindow；FieldEdit；MainViewModel；NativeStore | 焦点/修订/IME/候选/消费不退，预览生产一致、性能不退，无无关diff，不先造框架。 |
| ENG-017 | 工具纳管 | 现有harness/fixture/基准参数化及操作许可。 | P1 | [ ] | ENG-000、ENG-002、ENG-014 | 自有artifacts辅助工程；B/Program.cs；获准入口 | 默认不读生产、不覆盖历史、不抢桌面，EXE hash/commit齐；网络/mic/键盘显式许可，基准有预算。 |
| ENG-018 | 保留manifest | 逐类区分源/依赖/素材/输出/历史证据；指定的完整清单文件当前本机缺失。 | P2 | [!] | ENG-000 | 6168完整清单；artifacts；release-notes | 源/原始材料不丢，历史按hash索引；参考ENG-017，删除/移动/ignore另授权，禁止整体忽略遮蔽。当前本机缺失的引用路径：`docs/audit/E/untracked-complete-6168.txt`（manifest）、`docs/audit/E/untracked-metadata-complete.json`（metadata）、`docs/audit/E/untracked-classification-complete-6168.csv`（classification）。解除阻塞条件：恢复权威manifest/metadata/classification文件，或经用户另行批准以新的只读方法重建清单；未经批准不重建。 |

## 历史兼容任务（11项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LB-T01 | 当前入口/历史标签 | 文档置C#主线，标历史范围。 | P1 | [x] | ENG-000、DOC-001 | README；native/README；native/docs/ARCHITECTURE；RELEASE_GATE | 已核验：README首段及Native README明确现行C# Native产品与Python 0.9.4历史维护范围，365dt历史同步标为非Native；Native架构文档保持Native专属。`RELEASE_GATE.md`明确为2026-08-23 Python 0.9.4历史快照，其PASS/测试数不代表当前Native或GitHub Actions。未删旧材料。仅文档范围；未运行构建/测试/发布。 |
| LB-T02 | 兼容合同 | 旧→Native字段/表/来源/审计分类。 | P1 | [x] | ENG-000 | C/Storage/LegacyPythonMigration.cs、NativeStore.cs；native/docs/LEGACY-COMPATIBILITY.md | 已完成当前实现范围的逐字段兼容说明：显式 sessions/checkins 白名单、Native 映射/默认/跳过、CatalogLoader 与 LegacyProfileReader 的只读旧库依赖、未迁移字段及不可逆边界均有源码/隔离测试引用。版本规则为代码接受 v1–v10（1–5 无、6–10 有完整身份三元组）；仅合成 fixture 覆盖部分代表版本，不声明全历史 schema/生产库已验证。专用隔离测试日志 4 passed/0 failed/0 skipped；源库及 VACUUM 备份逐值一致。 |
| LB-T03 | 场次身份 | 同日同名、external key独立或审计归并。 | P1 | [!] | LB-T02 | C/Storage/LegacyPythonMigration.cs；T/LegacyPythonMigrationTests.cs | 阻塞：现实现对同日同名冲突拒绝整批而非静默合并，逐场次映射记录source、旧/新ID、external字段、decision、reason；合成测试验证不同external身份冲突拒绝及旧→新ID/签到关联（`LegacyPythonMigration.cs:117-145,169-204,571-595,650-684`；`LegacyPythonMigrationTests.cs:541-585,670-769`）。未批准不同主控/external key的同日同名场次应独立导入还是审计归并。解除条件：明确规则后用合成fixture验证不静默合并及映射/原因可追溯；未访问SQLite实例/未运行测试。 |
| LB-T04 | 导入结果可见 | 已存在Native/完成/跳过marker的用户路径。 | P1 | [x] | LB-T02 | A/ViewModels/MainViewModel.cs；C/Storage/LegacyPythonMigration.cs；设置 | 未导入原因/后续路径/跨重启明确，不静默删marker或强制混库、不只报就绪。已验收：SDK 10.0.401 Release build exit0（0 warnings/0 errors）；CatalogPublicationViewModelTests 隔离测试 11 passed/0 failed/0 skipped；correctness review 0 Critical/0 Major。真实桌面UI未验证。 |
| LB-T05 | WAL故障原子性 | 复用SQLite一致快照并验证降级/恢复。 | P1 | [ ] | LB-T02、NAT-T004、ENG-014 | C/Storage/LegacyPythonMigration.cs；迁移测试 | 合成库副本一致可读，失败无完成/半导入，源内容不变，覆盖VACUUM降级/中断/取消。 |
| LB-T06 | 归一化优先级 | user/default/priority碰撞fixture。 | P1 | [x] | ENG-000 | C/Catalogs/CatalogLoader.cs；T/CatalogLoaderTests.cs | 已验收：旧库别名仅读取`enabled=1`；以归一化键写入既有字典，非user项先、user项后，组内按priority/id升序并由后项覆盖。隔离碰撞`uv-5r`/`uv5r`证明user覆盖default、较高user priority胜出、disabled行不参与且来源标为用户别名。SDK 10.0.401 Release solution build exit 0（43 warnings/0 errors）；CatalogLoaderTests 16 passed/0 failed/0 skipped；仅覆盖LB-T06，不表示其它资料目录/同步/生产数据验收。 |
| LB-T07 | 旧源路径预检 | 非默认data_dir选择及指纹/计数展示。 | P2 | [!] | LB-T02 | C/Storage/AppPaths.cs；迁移/设置入口 | 阻塞：当前仅在启动参数`--data-root`提供进程级Root覆盖，设置页仅展示DatabasePath；调用处仅按FoundLegacyDatabase分支显示状态。未见设置页目录选择、旧源指纹/计数/迁移版本展示，或调用处明确区分源缺失的证据；不据此推断迁移器内部缺源行为。解除条件：批准非默认源路径选择、源/目标/迁移版本呈现、指纹/计数语义和缺源提示流程，再以隔离合成目录验证；本次未访问SQLite或生产素材。 |
| LB-T08 | 旧资料依赖/画像 | 盘点当前入口及ProfileReader定位。 | P2 | [x] | LB-T02 | C/Catalogs/CatalogLoader.cs；C/Storage/LegacyProfileReader.cs；资料模块 | 完成静态源码盘点：记录旧库位置、CatalogLoader只读别名字段/筛选及缺库/读取错误影响、LegacyProfileReader逐呼号读取最多300条未删除checkins及缺库/错误边界、ProfileAggregator各字段单一汇总值。对native/src与native/tests文本搜索未发现直接调用点，实际用户入口未知；不据此判定无用或授权删除。仅覆盖所列静态源码证据，不表示完整历史schema或生产库/生产迁移验收。 |
| LB-T09 | 有限兼容金标准 | 比较认可存量值，不复制旧缺陷/UI。 | P2 | [!] | LB-T02、LB-T06 | 当前C#解析/迁移测试 | 阻塞：本地Python测试虽对呼号、歧义QTH、设备别名、unmatched有候选断言（`tests/test_parser.py:36-58,67-79,90-108`; `tests/regression/test_device_dict.py:25-78,131-147`），但未绑定经认可的0.9.4源码提交/hash或用户批准范围；signal/power冲突及旧时间文本覆盖无golden（`core/parser.py:355-367,327-456`; `tests/regression/test_datetime_canonical.py:20-47`）。不得据历史实现臆造预期。解除条件：取得可绑定且获批准的golden矩阵，补齐缺项后用纯合成fixture核验；未运行Python、未访问历史/生产数据库。 |
| LB-T10 | 工具/Gate/附件 | 澄清Python工具、C#验收、同hash兼容名。 | P2 | [x] | ENG-000 | .github/workflows/release.yml、ci.yml；release.py；构建说明 | 静态核验：ci.yml保留Python 3.11/3.12 matrix、独立Native .NET 10 job及TRX/metadata上传；release.yml配置Python legacy regression、Native build/test及从Native App发布自包含EXE后传入release.py；release.py生成HAM.exe和中/ASCII兼容副本并校验同SHA-256、写SHA256SUMS.txt，既有测试源码覆盖逐字节复制、checksum及同尺寸/mtime旧资产替换。本行仅记workflow/source/test静态合同；本次未运行构建/测试/CI/Release，远端Actions/Release未验收。 |
| LB-T11 | 版本证据 | 批准版本/工作树/说明/产物/远端核对。 | P2 | [ ] | ENG-004、ENG-006 | App csproj；README；updates/latest.json；获准发布证据 | 分支1.0.5不是线上事实，1.0.20不借旧PASS；远端另授权，本次不改清单发布。 |

## 素材任务（7项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MEDIA-TODO-01 | 清单保全 | 元数据、重复、前后哈希及索引。 | P0 | [x] | 无 | M/inventory-before/after；preservation-comparison.json | 上游证据1文件/0子目录，路径/大小/mtime/ctime/SHA一致，AllMatched=true；仅证明列明稳定元数据和内容。 |
| MEDIA-TODO-02 | 扫描/视觉抽样 | 全时间轴机械检测及限定疑点读图。 | P0 | [x] | MEDIA-TODO-01 | M/FRAME-INDEX.md、all-reviewed-frames、扫描/拼图/裁剪 | 上游31拼图341实例15裁剪、约308不同PTS≈0.14257%；中断续扫重叠14.76秒，不等逐帧、小字或持久化验证。 |
| MEDIA-TODO-03 | 历史构建绑定 | hash→录制构建/程序集→commit或历史参考决定。 | P1 | [!] | ENG-000 | MEDIA-005；原片元数据/标题；获准版本资料 | 阻塞：现有跟踪triage记载目录无经校验的程序集/源码commit/发布清单映射、录制构建未确定，并提出无法绑定时需用户确认仅作历史交互参考（`docs/triage/NVIDIA-Netease-issues.md:132-143`; `docs/ISSUE_INVENTORY.md:102`）；已检文档中无此确认。未读取、散列或播放原片，不做声音/语义审查。解除条件：提供可追溯构建链，或有明确的仅历史参考决定；拟报当前缺陷须在当前构建独立复现。 |
| MEDIA-TODO-05 | 分享治理 | 有需要且获准后另存脱敏衍生版。 | P2 | [ ] | ENG-000、MEDIA-TODO-01 | MEDIA-003；保管者/获准输出 | 先确认分享，再另hash去非必要聊天/识别信息，复审拟分享全段；原件不变、不擅外发。 |
| MEDIA-TODO-06 | 候选回归矩阵 | 历史正常交互映射当前规则/测试。 | P2 | [ ] | MEDIA-TODO-03、NAT-T026 | 正式素材册；当前C#规格/测试 | 预览、双窗、QTH/设备编辑、IME、选区目标、列表/持久化列预期/结果/源码测试；正常画面不报bug。 |
| MEDIA-TODO-07 | 条件性兼容 | 必需读取器确有需求才核UDTA/长帧。 | P3 | [ ] | MEDIA-TODO-01、ENG-000 | MEDIA-001/002；授权副本/读取器 | 独立证明实际读取/感知影响或保留录制观察；不改原hash、不转码掩盖、不归因当前卡顿。 |
| MEDIA-TODO-08 | 可测试边界建议 | 有源码证据才规划最小职责边界。 | P2 | [ ] | MEDIA-TODO-06、PLAN-P2-DESIGN | 当前C#解析/状态/字段提交/持久化 | 沿现有命名结构逐项回归；不凭录像指定类、不全面换架构。 |

## 交付与阶段闸（18项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DOC-001 | 正式审计docs | 用获准原生补丁工具落六份自包含文档。 | P1 | [x] | 无 | docs/audit/PHASE0_AUDIT_REPORT.md、PHASE0_TODO.md、FUNCTION_INVENTORY.md、SOURCE_COVERAGE.md、ISSUE_INVENTORY.md；docs/triage/NVIDIA-Netease-issues.md | git apply检查/应用及落盘读取、82任务/65来源、依赖无环/链接有效/六文件边界校验成立；旧工具缺口已解决，不以团队板代替正文；不是源码功能完成。 |
| PLAN-P1-DOC | 长期文档工作流 | 建立并持续维护下节指定文档。 | P1 | [ ] | DOC-001、NAT-T025、LB-T01、LB-T10、ENG-003 | 根AGENTS/TODO/CHANGELOG；docs/PROJECT_CONTEXT、DECISIONS、ISSUE_INVENTORY；本审计包/素材册 | 满足下节十五类、五类事实、八字段四状态/优先级、Keep-a-Changelog及前读后同步；根规则、项目上下文、中央任务、决策和问题入口已建立；Phase4/5真实结果回填与后续维护仍开放。 |
| PLAN-P2-IA | 全软件信息架构 | 页面/导航/职责/数据关系/用户路径/状态/快捷操作。 | P1 | [x] | ENG-000、NAT-T026、DOC-001 | docs/UI_INFORMATION_ARCHITECTURE.md（USER_APPROVED 方向，详细内容仍 PROPOSED）；全页面/主小窗/对话框；29功能/兼容 | 七项用户选择均已确认 A；文档记录所选导航、详情、QuickWindow、主题、品牌、快捷键与现有字段筛选方向，并保留29项映射/业务边界。仅文档范围完成，不代表运行实现或UI验收PASS。LB-T02与LB-T08的文档盘点范围已完成；旧库完整schema、LegacyProfileReader实际用户入口及生产兼容仍未验证，不构成此非破坏性导航文档的前置条件。 |
| PLAN-P2-DESIGN | 完整UI及安全设计闸 | 页面/组件/色字间距/动画/交互状态与关键页；兼顾最小技术/回滚。 | P0 | [x] | PLAN-P2-IA、NAT-T001 | docs/UI_DESIGN_SPEC.md（用户确认方向，具体布局 / 密度 / tonal tokens 仍 PROPOSED）；数据/场次/导出/目录/媒体/更新方案 | 用户已确认七项均选A；文档明确三主题方向、11态与Windows验收矩阵，并区分已确认方向和待检验细节。此项仅按文档范围完成；后续实施按TODO依赖、计划及测试/安全闸推进；所有运行/Windows验收仍NOT_VERIFIED。 |
| PLAN-P3-DATA | 数据安全批次 | 统一别名的安全修复汇总验收。 | P0 | [ ] | ENG-000、PLAN-P2-DESIGN、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、ENG-008、ENG-009、ENG-010、ENG-011、ENG-012、LB-T02、LB-T03、LB-T04、LB-T05、LB-T07、LB-T08 | 导出/目标保护、备份schema、兼容/Store约束 | 先失败契约后最小修复，同补丁关联别名；LB-T02/T08旧数据字段合同及入口盘点须先闭合；合成/隔离验证与源目标保护齐再扩状态；生产另许可。 |
| PLAN-P3-STATE | 业务状态批次 | 输入/字段/场次/设置/列表。 | P1 | [ ] | ENG-000、PLAN-P3-DATA、NAT-T008、NAT-T011、NAT-T018、NAT-T019、NAT-T020、ENG-015 | VM/视图、Draft、Store、设置 | 认可业务合同逐项闭合，DB/VM/UI一致、失败保原文；候选/清空/撤销不擅改，无无关格式化。 |
| PLAN-P3-CATALOG | 资料批次 | 重建/优先级/同步/本地树。 | P1 | [ ] | ENG-000、PLAN-P3-DATA、NAT-T009、NAT-T010、NAT-T012、NAT-T013、ENG-013、LB-T06 | CatalogService/Loader/Snapshot；MIIT partial/checkpoint | fixture证明重载/冲突/取消完成/游标/保正式库；官网另许可单列，不造第二词典/下载通道。 |
| PLAN-P3-MEDIA | 媒体生命周期批次 | 既有录屏/mic/停止关闭安全。 | P1 | [ ] | ENG-000、PLAN-P3-DATA、PLAN-P4-PLATFORM、NAT-T014、NAT-T015、NAT-T016、ENG-014 | WinMM/Media Foundation/PrintWindow与关闭链 | 平台契约先核，默认mic关/窗口限定/失败释放/并发停止关闭/长录同步阈值有证据；真实桌面/设备操作另须明确批准；素材观察不代替产品测试。 |
| PLAN-P3-UPDATE | 更新批次 | 下载/安装/回滚与现有发布合同。 | P1 | [ ] | ENG-000、PLAN-P3-DATA、NAT-T017、ENG-007 | C/Updates/NativeUpdateService.cs；About安装 | 同源hash与签名分清，URI/限额/篡改/失败/回滚隔离验；联网下载/安装及稳定指针均另须明确批准。 |
| PLAN-P3-STRUCT | 最后职责收敛 | 仅获准且有真实耦合/重复证据时抽取。 | P2 | [ ] | ENG-000、PLAN-P3-STATE、PLAN-P3-CATALOG、PLAN-P3-MEDIA、PLAN-P3-UPDATE、NAT-T024、ENG-016、MEDIA-TODO-08 | 主小窗适配、字段消费、大类边界 | 第二真实调用者前不造接口/工厂/注册表/旋钮；一次一边界可回退，无第二实现；暂缓不假完成。 |
| PLAN-P3-UI | 全页面UI实施 | 按获批方向分批统一界面、组件、三主题及交互。 | P1 | [ ] | ENG-000、PLAN-P2-DESIGN、PLAN-P3-DATA、PLAN-P3-STATE、PLAN-P3-CATALOG、PLAN-P3-MEDIA、PLAN-P3-UPDATE、NAT-T022 | 全页面/主小窗/场次字段对话框/列表资料录屏设置关于更新 | 不缩成换色修补；每批覆盖下节矩阵、保业务、针对测试、版本证据/回退及TODO/CHANGELOG/必要CONTEXT/AGENTS同步；真实桌面验收另须明确批准。2026-11-21 字重修正：`MainWindow.xaml:14` 根节点继承 `FontWeight="SemiBold"`；SDK10.0.401 Release `--no-restore` build 0 errors/24 warnings；隔离截图确认未选导航、字段标签、表头及状态文字变粗，选中项字重不变。PLAN-P3-UI 其余页面/状态/主题/DPI 矩阵仍开放。2026-11-22 页面切换与五个二级窗口入口过渡已实现：页面 180 ms、窗口 160 ms，统一 `WindowMotion`，尊重系统减动与动画开关；新增 UI 测试 3 例（启用/禁用/快速取消），SDK10.0.401 Release 构建 0 errors，`Category!=Hardware` 305/305 通过；真实 DPI/多屏/IME/读屏及硬件/网络/生产/安装矩阵仍 NOT_RUN。2026-11-22 呼号历史提示 S1：从 `checkins` 派生 QTH/设备/天线/功率 chip，显式点击逐字段应用、可撤销、不自动提交；关于页副标题删除。SDK10.0.401 Release 构建 0 errors，`Category!=Hardware` 317/317 通过；真实 DPI/快捷窗视觉/读屏矩阵仍 NOT_VERIFIED，`1907` 是时间还是设备型号待用户确认。 |
| PLAN-P4-PLATFORM | 平台前置复核 | .NET10 PCM与本地Windows SDK COM/HRESULT/PreserveSig。 | P1 | [ ] | ENG-000、ENG-002 | 合成probe；现有媒体边界 | 签名/运算/回调语义逐项有依据，无依据不判ABI错；不下载SDK、不用生产媒体，缺材料如实阻塞。 |
| PLAN-P4-CORE | 核心分层验收 | 纯函数/隔离DB/OpenXml/HTTP故障。 | P0 | [ ] | PLAN-P3-DATA、PLAN-P3-STATE、PLAN-P3-CATALOG、ENG-014 | 现有xUnit解析/Store/迁移/导出/目录/更新fixture | 5001/10001、schema/WAL/取消/冲突/正式库hash，失败/Skip/TRX/版本齐；各修复前后滚动验。 |
| PLAN-P4-UI | 真实桌面矩阵 | 全新UI/三主题/全页面状态与真实Windows交互。 | P1 | [ ] | PLAN-P4-CORE、PLAN-P3-STATE、NAT-T022、ENG-017、PLAN-P3-UI | 当前候选全页面/主小窗/对话框；U项目/真实桌面 | 系统变化/浅深、Win10/11、全部窗口状态、DPI/多屏/字体、键盘焦点/真实IME/读屏/高对比；图像绑版本，模拟IME/预览/旧PASS不代替。 |
| PLAN-P4-MEDIA | 真实媒体验收 | 能力分层、非对称画面、设备/解码/长录。 | P1 | [ ] | PLAN-P4-PLATFORM、PLAN-P3-MEDIA、ENG-014、ENG-017 | 纯fixture/受控窗口/获准设备 | stride方向、覆盖窗口安全、权限/拔设备/默认mic关/拒覆盖、暂停/resize/音画同步；无设备明确Skip，不过滤抹失败。 |
| PLAN-P4-E2E | 业务/性能兼容签署 | 当前EXE完整链与有限金标准。 | P1 | [ ] | PLAN-P4-CORE、PLAN-P4-UI、PLAN-P4-MEDIA、PLAN-P3-UPDATE、LB-T09、NAT-T021、NAT-T023、MEDIA-TODO-06 | 当前候选；合成库/工作簿/回归矩阵 | 输入→提交→字段改→切场→重启→全导出/恢复对账；性能兼容达标；若批次含结构调整另验PLAN-P3-STRUCT，历史画面不算PASS。 |
| PLAN-P5-BUILD | 干净构建打包 | 隔离SDK10/Native自包含win-x64候选及双清单附件。 | P0 | [ ] | PLAN-P4-E2E、ENG-001、ENG-002、ENG-004、ENG-005、ENG-017、LB-T10、LB-T11、NAT-T027 | 获准SDK/资产/发布输入；隔离产物 | restore/build/test/publish分别获准留日志；commit+dirty/SDK/依赖/EXE SHA/签名策略/用例/Skip齐；无Python目标机运行，资源可追溯。 |
| PLAN-P5-RELEASE | 最终发布闸 | 现场、安装回滚、promotion与签署。 | P0 | [ ] | PLAN-P5-BUILD、ENG-006、ENG-007、PLAN-P1-DOC、MEDIA-TODO-03 | 专用演练；候选→稳定；最终文档/用户签字 | 安装/旧版恢复、不可变资产/并发降级/hash回读成立；文档和历史构建决定齐；产品验收与正式发布另授权，未许可不推送发布。 |

## 本次上下文交付任务

| TaskID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 可复现验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CTX-001 | 协作规则入口 | 提供15类项目规则并链接长期事实，要求任务前阅读、任务后同步。 | P1 | [x] | DOC-001 | AGENTS.md | 15方面齐全；内部链接可解析；不把历史README叙述当现行产品。 |
| CTX-002 | 项目事实与边界 | 建立事实/当前实现/计划/推测/待确认五类上下文。 | P1 | [x] | CTX-001 | docs/PROJECT_CONTEXT.md | 关键版本、业务字段、存储、外部边界和未验证状态均有来源与分类。 |
| CTX-003 | 中央任务台账 | 迁入Phase0的82项，增加本次六个文档任务。 | P1 | [x] | CTX-001、CTX-002 | TODO.md；docs/audit/PHASE0_TODO.md | 82个源TaskID逐项存在，依赖/八字段完整；无声音语义审查项；录屏/麦克风任务保留。 |
| CTX-004 | 真实变更日志 | 仅记录本次已实现文档变更，不预报代码或验收。 | P2 | [x] | CTX-001、CTX-002、CTX-003 | CHANGELOG.md | 新增未发布文档区；日期正确；明确未改产品行为且未运行测试。 |
| CTX-005 | 决策记录 | 把用户已确认方向与事实依据分开记录，未决规则仍待确认。 | P1 | [x] | CTX-002 | docs/DECISIONS.md | 每条具ID、状态、依据、影响；三主题与完整UI重设计不降级为待确认。 |
| CTX-006 | 长期问题入口 | 汇总高风险未修复项并链接唯一详细问题登记册。 | P1 | [x] | CTX-002、CTX-003 | docs/ISSUE_INVENTORY.md；docs/audit/ISSUE_INVENTORY.md | 入口/相对链接有效；未修复项不标Done、不复制出第二份65项登记册。 |

## 状态与更新

关闭任务时记录实际命令/日志、版本与范围；未执行的构建、测试、桌面验收或生产操作使用 NOT_RUN。发现状态与来源证据冲突时先保留差异并标待确认，不改写Phase0冻结证据。每项产品改动前读取[协作规则](AGENTS.md)、[项目上下文](docs/PROJECT_CONTEXT.md)和本表；完成后更新本表、CHANGELOG及受影响的上下文文档。
