# Phase0 完整任务与阶段合同

日期：2026-11-14。入口：[综合报告](PHASE0_AUDIT_REPORT.md)、[功能](FUNCTION_INVENTORY.md)、[覆盖](SOURCE_COVERAGE.md)、[问题](ISSUE_INVENTORY.md)、[素材](../triage/NVIDIA-Netease-issues.md)。

## 规则、状态与路径

| 规则 | 内容 |
| --- | --- |
| 总数/来源 | 原任务保留64项（NAT27、ENG18、LB11、素材7、ENG-000前置1），补充交付/阶段闸18，共82项。阶段闸不是新缺陷；ENG问题与同名任务是不同台账角色。 |
| 八字段/优先级 | ID、名称、描述、优先级、状态、依赖、文件/模块、验收；P0下一阶段先闭的基线/数据完整性，P1安全/功能/UI合同，P2文档/结构/归档，P3条件性素材兼容；不是漏洞评级。 |
| 四状态 | [ ]未开始/待确认；[/]已授权进行中；[x]仅列明范围有证据完成；[!]依赖未满足的阻塞。当前79个[ ]、0个[/]、3个[x]、0个[!]；下游未开始不机械标阻塞。 |
| 三项完成限定 | DOC-001仅六文档落盘/校验；MEDIA-TODO-01仅源清单保全；MEDIA-TODO-02仅机械扫描及声明的视觉抽样。三者都不是当前C#功能完成。 |
| 授权/顺序 | 本次审计docs已获批准，不再重复授权。未来实施/restore/网络/桌面/外设/生产/发布仍受ENG-000分项许可；运行时代码还须PLAN-P2-DESIGN批准。 |
| 依赖/滚动验收 | 全部依赖为表内完整ID且不得循环。NAT-T023在各修复批次滚动补证据，不等整包结束，也不依赖NAT-T024；平台复核在平台修复前执行。 |
| 复用/卫生 | 先标准库、仓库已有机制、已装依赖；没有第二真实调用者不造接口/工厂/注册表/旋钮；不造第二解析/词典/下载/发布实现。清理自己变更导致的死代码，XAML事件/接口参数不误删。 |
| 保护 | 当前唯一C#/.NET10/WPF；11既有diff和6168原未跟踪全保留，不改原素材/配置/DB/ignore。本表是后续计划，不是自动实施、提交发布许可。 |
| 路径图例 | A=native/src/HamCheckin.Native.App；C=native/src/HamCheckin.Native.Core；B=native/src/HamCheckin.Native.Benchmarks；T=native/tests/HamCheckin.Native.Tests；U=native/tests/HamCheckin.Native.UiTests。E/M为综合报告定义的本地engineering/media证据根；同一单元格中后续裸文件名沿用最近已写出的目录前缀。 |

## Native任务（27项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NAT-T001 | 冻结基线 | 唯一C#范围、dirty差异、隔离授权与问题→测试。 | P0 | [ ] | ENG-000 | README；native/docs；Git元数据 | 11修改/6168路径及归属可追溯，复用既有diff证据，不覆盖工作、不删历史功能。 |
| NAT-T002 | 全量导出 | 修复5000截断，独立对账。 | P0 | [ ] | NAT-T001、ENG-014 | C/Storage/NativeStore.cs；C/Export/ExcelExportService.cs；T/NativeEndToEndTests.cs | 5000/5001/10000/10001条DB count、首末序号/字段一致，失败不报成功。 |
| NAT-T003 | 导出请求/目标 | 固定会话、净化basename、覆盖须同意。 | P0 | [ ] | NAT-T001 | A/ViewModels/MainViewModel.cs；C/Export/ExcelExportService.cs | 同名/路径字符/绝对名/占用/切场；未同意、取消或失败原输出hash不变，标题数据同场、不越出选定目录。 |
| NAT-T004 | Native备份恢复 | 在线一致快照、元数据、校验与保留合同。 | P0 | [ ] | NAT-T001 | C/Storage/AppPaths.cs、NativeStore.cs；获准备份实现 | 合成库恢复逐表/原文/审计对账；坏备份/磁盘满/占用fail-closed，不用生产库。 |
| NAT-T005 | 一致快照导入 | 从同一已验证备份导入旧格式并解释结果。 | P0 | [ ] | NAT-T004、LB-T02、ENG-014 | C/Storage/LegacyPythonMigration.cs；A/ViewModels/MainViewModel.cs；T/LegacyPythonMigrationTests.cs | 并发WAL、VACUUM失败、中断/取消/重复/skip可核；无完成假标记，源不变，不运行Python。 |
| NAT-T006 | schema升级 | 有向版本迁移、未来拒绝、原子回滚。 | P0 | [ ] | NAT-T004、ENG-014 | C/Storage/NativeStore.cs；获准迁移定义 | v1/v2/v3路径与v4拒绝有隔离证据，不降标/半升级，备份回滚可验证。 |
| NAT-T007 | 事务不变量 | active、记录归属、呼号和编辑版本下沉存储。 | P0 | [ ] | NAT-T001、ENG-014 | C/Storage/NativeStore.cs、Models.cs；A/ViewModels/MainViewModel.cs；T/NativeStoreTests.cs | 直接Store/错场/ended/空呼号/结束交错/编辑冲突拒非法写；合法重复呼号保留。 |
| NAT-T008 | 字段采用/确认 | 最终片段集合、真实选择复制、确认标记、未知设备。 | P1 | [ ] | NAT-T007 | A/Views/FieldEditWindow.xaml及代码；C/Parsing/FieldParser.cs | A后B只消费最终明确采用项；重复索引/取消/手改/清空/确认及零一多候选，不擅改型号。 |
| NAT-T009 | 重建资料快照 | 内置/外部独立层与世代发布。 | P1 | [ ] | NAT-T001 | C/Catalogs/CatalogService.cs、CatalogLoader.cs、CatalogSnapshot.cs；T/CatalogLoaderTests.cs | 二次以上改删禁用/根切换正确，旧世代不盖新，输入热路径无I/O。 |
| NAT-T010 | 别名优先级 | 确认人工/本地/内置/MIIT归一化冲突。 | P1 | [ ] | NAT-T009、LB-T06 | C/Catalogs/CatalogLoader.cs、CatalogSnapshot.cs；T/CatalogLoaderTests.cs | 多priority/用户来源/碰撞/同名行政区及人工QTH目标稳定，不凭名称猜目标。 |
| NAT-T011 | 场次/导航真源 | 请求版本、提交完成、唯一导航状态。 | P1 | [ ] | NAT-T007、NAT-T001 | A/ViewModels/MainViewModel.cs、Views/MainView.xaml.cs；U/QuickInputUiTests.cs | 延迟提交与结束/重开/元信息/连续切场交错，DB、VM、可见页一致。 |
| NAT-T012 | MIIT单作业/续传 | 等取消完成、同路径互斥、正确大页游标。 | P1 | [ ] | NAT-T009、ENG-014 | A/ViewModels/MainViewModel.cs；C/Catalogs/MiitCatalogSyncService.cs；T/MiitCatalogSyncTests.cs | Running/Cancelling/Settled真实，1000条大页恢复正确，重页/空页/总数变化/401/403/超时/取消保正式库。 |
| NAT-T013 | MIIT数据合同 | 筛选、隐藏注销状态和副索引。 | P1 | [ ] | NAT-T012、ENG-000 | C/Catalogs/MiitCatalogSyncService.cs、CatalogLoader.cs；资料UI | 续证/包含排除冲突/隐藏注销/未知名称有fixture；模拟与官网分列，不假全量，访问拒绝停止。 |
| NAT-T014 | PCM/COM及释放 | 先平台复核，再回调错误隔离/失败释放设备。 | P1 | [ ] | PLAN-P4-PLATFORM、ENG-000 | A/Media/MicrophoneCapture.cs、MediaFoundationInterop.cs、ScreenRecordingService.cs | 核对.NET10 Math.Abs/SDK ABI后，-32768..32767、订阅异常、无设备/权限/拔设备不崩溃，失败释放，不先判ABI错。 |
| NAT-T015 | 媒体时钟/尺寸 | 公共时钟、帧deadline、暂停和resize策略。 | P1 | [ ] | NAT-T014 | A/Media/ScreenRecordingService.cs、ScreenCapture.cs、Mp4FileWriter.cs | 获批长录/帧率/漂移阈值；负载/暂停/resize/跨DPI真实解码播放及音画同步达标，不靠FourCC。 |
| NAT-T016 | 初始化/关闭 | 异步恢复及跟踪提交、导出、资料、录屏作业。 | P1 | [ ] | NAT-T007、NAT-T012、NAT-T014 | A/App.xaml.cs、MainWindow.xaml.cs、Views/MainView.xaml.cs、ViewModels/MainViewModel.cs | UI不同步等待窗口消息采集；Stop/关闭/更新退出无死锁/假成功，草稿与已提交结果可解释。 |
| NAT-T017 | 更新安全收尾 | 安装握手、旧EXE回滚、签名/URI/体积模型。 | P1 | [ ] | ENG-000、PLAN-P2-DESIGN | C/Updates/NativeUpdateService.cs；A/Views/AboutWindow.xaml.cs | 错hash/PE/恶意scheme/超量/取消/权限/锁定/重启失败有隔离证据；temp篡改不执行、旧EXE可恢复，不擅发布。 |
| NAT-T018 | 动作/设置持久化 | 统一可执行快捷动作/作用域，独立Native配置。 | P1 | [ ] | ENG-000、PLAN-P2-IA | A/Infrastructure、ViewModels/MainViewModel.cs；输入/字段视图 | 新键真实生效、Win modifier/冲突可见、重启保留；记录撤销先确认语义，不覆盖旧config.json。 |
| NAT-T019 | 可见状态/错误 | 绑定作业/快捷状态，捕获地点树异常，区分刷新下载。 | P1 | [ ] | NAT-T012、PLAN-P2-IA | A/Views/MainView.xaml及代码、ViewModels/MainViewModel.cs；C/Catalogs/QthPackageService.cs | busy/cancelling/failed/未配置可见，坏库不退出，本地刷新不宣称远程下载成功。 |
| NAT-T020 | 完整本场浏览 | 最近缓存与分页/总数/定位编辑分离。 | P1 | [ ] | NAT-T007、PLAN-P2-IA | A/ViewModels/MainViewModel.cs、Views/MainView.xaml；C/Storage/NativeStore.cs | 301/5001条重启切场仍能定位最早记录，编辑/导出一致，不用全表阻塞UI。 |
| NAT-T021 | 性能基线/优化 | 先版本绑定，再解析/目录索引缓存优化。 | P2 | [ ] | NAT-T009、NAT-T010、ENG-002、ENG-017 | C/Catalogs/CatalogSnapshot.cs、Parsing/InputParser.cs；B/Program.cs | 完整/缺库/10万目录/中文长输入p50/p95/p99及Dispatcher，原文/候选/金标准不退，不延迟丢输入刷分。 |
| NAT-T022 | 三主题桌面适配 | 按已定合同实现跟随系统、浅色、深色。 | P1 | [ ] | ENG-000、PLAN-P2-DESIGN | A/App.xaml、app.manifest、全部Views/MainWindow和样式资源 | Phase2具体方向批准后Phase3实施；系统变化、Win10/11、缩放/最小化/最大化/还原、100/125/150/200%DPI、多屏/字体、焦点/键盘/读屏/高对比/真实IME有证据，不再确认是否要三主题。 |
| NAT-T023 | Native滚动回归 | 33来源风险逐批绑定当前源码/EXE。 | P1 | [ ] | ENG-002、ENG-014、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、NAT-T008、NAT-T009、NAT-T010、NAT-T011、NAT-T012、NAT-T013、NAT-T014、NAT-T015、NAT-T016、NAT-T017、NAT-T018、NAT-T019、NAT-T020 | native/tests；native/docs/VERIFICATION.md；批准隔离产物 | 各批SHA+dirty/SDK/OS/DPI/EXE SHA/TRX/日志齐，失败/Skip/BLOCKED/NOT_RUN分列，不继承旧PASS。 |
| NAT-T024 | 证据驱动拆分 | 行为锁定后一次一个真实职责边界。 | P2 | [ ] | NAT-T001、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、NAT-T023 | A/ViewModels/MainViewModel.cs；MainView/About代码；对应Core | 可回退、业务性能不退，仍C#/WPF/.NET10/SQLite/OpenXml，不删字段、不预建服务层。 |
| NAT-T025 | 治理入口/证据 | 当前C#、历史标签、版本/能力/验收分开。 | P2 | [ ] | ENG-000、DOC-001 | README.md；native/README.md；native/docs；本审计包 | 当前运行无pip/python要求，旧章标历史，1.0.20与旧候选分开；既有文档仅获准后改。 |
| NAT-T026 | 保留范围合同 | 撤销/补同步/画像学习/历史导入/365dt/远程地点包。 | P2 | [ ] | ENG-000 | A/ViewModels/MainViewModel.cs；C/Storage/LegacyProfileReader.cs、Catalogs/QthPackageService.cs；需求记录 | 每项保留/暂缓、负责人、验收明确，辅助代码不算完成，不先删功能、不加未确认QSO/ADIF。 |
| NAT-T027 | 资源/隐私基线 | 行政区别名来源生成链、包和本地隐私。 | P2 | [ ] | ENG-000、ENG-005 | C/Catalogs/NationwideAdminCatalog.cs、CatalogLoader.cs、nationwide-admin.tsv.gz.b64；csproj | 来源/日期/license/hash/生成可追溯，独立金标准不自证；ACL/可选加密取舍明确，当前漏洞另核、不上传。 |

## 工程任务及前置（19项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENG-000 | 分项操作授权 | 确认未来范围、diff归属、隔离/外设/网络许可。 | P0 | [ ] | 无 | C#产品；Git；候选/稳定；遗留工具 | 批准记录与保护基线明确；restore/网络/窗口/媒体/生产/发布分别许可，本次文档授权不自动放行。 |
| ENG-001 | 当前C# PR Gate | 普通PR/开发分支复用Native编译/xUnit。 | P0 | [ ] | ENG-000、ENG-002 | .github/workflows/ci.yml；Native sln/xUnit | 故意编译错与核心断言错各拦截，Native用例/Skip/TRX齐；历史兼容job单列。 |
| ENG-002 | SDK/资产 | 选定SDK10、TFM/RID及隔离资产。 | P0 | [ ] | ENG-000 | SDK策略；5csproj/sln；隔离obj | 本机/CI选定SDK可复现，App/Core/Tests assets匹配net10；不以旧net8缓存证构建。 |
| ENG-003 | 产品/工具边界 | 当前运行说明与Python发布工具分开。 | P1 | [ ] | ENG-000 | README/native文档；release.yml；release.py | 无Python目标机运行C# EXE，工具解释器/依赖/显式版本参数清楚，不盲删工具。 |
| ENG-004 | 唯一版本权威 | 派生一致性及候选证据绑定。 | P0 | [ ] | ENG-000、ENG-002 | App csproj/manifest/NativeVersion/UI/测试/发布元数据 | 任一源不一致被拦截；commit/dirty/EXE hash齐，候选与稳定指针分离。 |
| ENG-005 | 供应/复现策略 | SDK/Actions/依赖图锁定及漏洞来源。 | P1 | [ ] | ENG-000、ENG-002 | 依赖/SDK/CI；获准锁定策略 | 批准来源重建同一图，漂移失败；扫描带时间/源/版本，离线未知不是无漏洞。 |
| ENG-006 | 不可变发布 | promotion、并发/降级保护与权限。 | P1 | [ ] | ENG-004、ENG-005、ENG-014 | .github/workflows/release.yml；双清单 | 同Tag不静默改hash，旧/并行Tag不回退latest，上传/回读失败不切指针；专用仓库或获准演练。 |
| ENG-007 | 更新事务 | 复用下载器补安装/回滚/URI/限额/签名。 | P1 | [ ] | ENG-000、ENG-004、ENG-005、ENG-014 | C/Updates/NativeUpdateService.cs；A/Views/AboutWindow.xaml.cs | 非法URL/hash/超量拒绝，temp篡改不执行；权限/锁定/重启失败保旧EXE，用户数据hash不变。 |
| ENG-008 | 旧数据一致导入 | 备份与导入共用可恢复快照。 | P0 | [ ] | ENG-000、ENG-002、ENG-009、ENG-014 | C/Storage/LegacyPythonMigration.cs；迁移测试 | WAL/并发/损坏/中断恢复及计数对账，或完全不标完成；源不改，自动策略明确。 |
| ENG-009 | Native恢复/schema | 未来版本拒绝及备份恢复策略。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs；备份恢复合同 | 旧/当前/未来schema、半升级、坏备份、恢复失败有隔离证据，不覆盖生产好库。 |
| ENG-010 | 独立全量查询 | 导出与分页UI分离，DB独立对账。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs、Export/ExcelExportService.cs；T/NativeEndToEndTests.cs | 5001/10001首末序号/字段/行数一致；保留临时/OpenXml/InlineString，不用截断rows.Count自证。 |
| ENG-011 | ended写约束 | 所属场次可写性落事务。 | P0 | [ ] | ENG-000、ENG-002、ENG-014 | C/Storage/NativeStore.cs；A/ViewModels/MainViewModel.cs；Store/UI测试 | 直接API/旧状态/并发/双Store不能写ended；成功记录及审计保留。 |
| ENG-012 | 导出覆盖/快照 | 固定会话及保护人工工作簿。 | P0 | [ ] | ENG-000、ENG-002、ENG-010、ENG-014 | A/ViewModels/MainViewModel.cs；C/Export/ExcelExportService.cs | 切场不混标题数据；未同意人工列/公式旧文件字节不变，取消失败保原输出。 |
| ENG-013 | 资料作业安全 | 取消完成/同路径互斥/重载/断点/响应限额。 | P1 | [ ] | ENG-000、ENG-002、ENG-014 | A/ViewModels/MainViewModel.cs；C/Catalogs/MiitCatalogSyncService.cs、CatalogLoader.cs、CatalogService.cs | 取消重试保正式库/断点，型号更新不残留，401/403/分页失败hash不变；官网另许可。 |
| ENG-014 | 先故障契约 | 分层媒体、超时和当前结果归档。 | P0 | [ ] | ENG-000、ENG-002 | native/tests；CI；MIIT正式库/媒体fixture | 故障能使Gate失败，无设备明确Skip，有设备方向/覆盖安全/默认mic关/拒覆盖；有限超时，证据绑dirty。 |
| ENG-015 | 设置/撤销语义 | 先确认持久化与记录级撤销范围。 | P1 | [ ] | ENG-000、ENG-014、PLAN-P2-IA | A/ViewModels/MainViewModel.cs；C/Storage/NativeStore.cs；配置/输入/字段UI | 保留则重启设置恢复，撤销有事务/审计/场次/并发/导出语义；不支持不宣称，文字撤销不等记录撤销。 |
| ENG-016 | 真实重复收敛 | 契约稳定后输入适配/字段元数据/token消费。 | P2 | [ ] | ENG-001、ENG-008、ENG-009、ENG-010、ENG-011、ENG-012、ENG-013、ENG-014 | MainView/QuickWindow；FieldEdit；MainViewModel；NativeStore | 焦点/修订/IME/候选/消费不退，预览生产一致、性能不退，无无关diff，不先造框架。 |
| ENG-017 | 工具纳管 | 现有harness/fixture/基准参数化及操作许可。 | P1 | [ ] | ENG-000、ENG-002、ENG-014 | 自有artifacts辅助工程；B/Program.cs；获准入口 | 默认不读生产、不覆盖历史、不抢桌面，EXE hash/commit齐；网络/mic/键盘显式许可，基准有预算。 |
| ENG-018 | 保留manifest | 逐类区分源/依赖/素材/输出/历史证据。 | P2 | [ ] | ENG-000 | 6168完整清单；artifacts；release-notes | 源/原始材料不丢，历史按hash索引；参考ENG-017，删除/移动/ignore另授权，禁止整体忽略遮蔽。 |

## 历史兼容任务（11项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LB-T01 | 当前入口/历史标签 | 文档置C#主线，标历史范围。 | P1 | [ ] | ENG-000、DOC-001 | README；native/README；native/docs/ARCHITECTURE；RELEASE_GATE | 新用户不启动/打包旧Python，历史Gate标版本而不当当前PASS，不删旧材料。 |
| LB-T02 | 兼容合同 | 旧→Native字段/表/来源/审计分类。 | P1 | [ ] | ENG-000 | C/Storage/LegacyPythonMigration.cs、NativeStore.cs；兼容说明 | 每个表字段保留/只读依赖/显式不迁移，明确不可丢信息，旧库可回查。 |
| LB-T03 | 场次身份 | 同日同名、external key独立或审计归并。 | P1 | [ ] | LB-T02 | C/Storage/LegacyPythonMigration.cs；T/LegacyPythonMigrationTests.cs | 不同主控/external key不无提示合并，旧→新id及原因可追溯。 |
| LB-T04 | 导入结果可见 | 已存在Native/完成/跳过marker的用户路径。 | P1 | [ ] | LB-T02 | A/ViewModels/MainViewModel.cs；C/Storage/LegacyPythonMigration.cs；设置 | 未导入原因/后续路径/跨重启明确，不静默删marker或强制混库、不只报就绪。 |
| LB-T05 | WAL故障原子性 | 复用SQLite一致快照并验证降级/恢复。 | P1 | [ ] | LB-T02、NAT-T004、ENG-014 | C/Storage/LegacyPythonMigration.cs；迁移测试 | 合成库副本一致可读，失败无完成/半导入，源内容不变，覆盖VACUUM降级/中断/取消。 |
| LB-T06 | 归一化优先级 | user/default/priority碰撞fixture。 | P1 | [ ] | ENG-000 | C/Catalogs/CatalogLoader.cs；T/CatalogLoaderTests.cs | uv-5r/uv5r等冲突中认可用户值不被反盖，禁用不参与，复用现有字典。 |
| LB-T07 | 旧源路径预检 | 非默认data_dir选择及指纹/计数展示。 | P2 | [ ] | LB-T02 | C/Storage/AppPaths.cs；迁移/设置入口 | 明确流程/版本/源目标路径，缺源不假成功，不扫描上传生产素材。 |
| LB-T08 | 旧资料依赖/画像 | 盘点当前入口及ProfileReader定位。 | P2 | [ ] | LB-T02 | C/Catalogs/CatalogLoader.cs；C/Storage/LegacyProfileReader.cs；资料模块 | 旧库归档/丢失依赖可见，不重复词典/画像，不把未找到调用当删除授权。 |
| LB-T09 | 有限兼容金标准 | 比较认可存量值，不复制旧缺陷/UI。 | P2 | [ ] | LB-T02、LB-T06 | 当前C#解析/迁移测试 | 呼号、歧义QTH、设备别名、信号功率冲突、未识别、旧时间文本覆盖。 |
| LB-T10 | 工具/Gate/附件 | 澄清Python工具、C#验收、同hash兼容名。 | P2 | [ ] | ENG-000 | .github/workflows/release.yml、ci.yml；release.py；构建说明 | EXE来自Native，同字节/hash附件，门禁标语言范围；不盲删或另造发布工具。 |
| LB-T11 | 版本证据 | 批准版本/工作树/说明/产物/远端核对。 | P2 | [ ] | ENG-004、ENG-006 | App csproj；README；updates/latest.json；获准发布证据 | 分支1.0.5不是线上事实，1.0.20不借旧PASS；远端另授权，本次不改清单发布。 |

## 素材任务（7项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MEDIA-TODO-01 | 清单保全 | 元数据、重复、前后哈希及索引。 | P0 | [x] | 无 | M/inventory-before/after；preservation-comparison.json | 上游证据1文件/0子目录，路径/大小/mtime/ctime/SHA一致，AllMatched=true；仅证明列明稳定元数据和内容。 |
| MEDIA-TODO-02 | 扫描/视觉抽样 | 全时间轴机械检测及限定疑点读图。 | P0 | [x] | MEDIA-TODO-01 | M/FRAME-INDEX.md、all-reviewed-frames、扫描/拼图/裁剪 | 上游31拼图341实例15裁剪、约308不同PTS≈0.14257%；中断续扫重叠14.76秒，不等逐帧、小字或持久化验证。 |
| MEDIA-TODO-03 | 历史构建绑定 | hash→录制构建/程序集→commit或历史参考决定。 | P1 | [ ] | ENG-000 | MEDIA-005；原片元数据/标题；获准版本资料 | 链可追溯，或用户确认仅历史交互参考；拟报当前缺陷另行复现。 |
| MEDIA-TODO-05 | 分享治理 | 有需要且获准后另存脱敏衍生版。 | P2 | [ ] | ENG-000、MEDIA-TODO-01 | MEDIA-003；保管者/获准输出 | 先确认分享，再另hash去非必要聊天/识别信息，复审拟分享全段；原件不变、不擅外发。 |
| MEDIA-TODO-06 | 候选回归矩阵 | 历史正常交互映射当前规则/测试。 | P2 | [ ] | MEDIA-TODO-03、NAT-T026 | 正式素材册；当前C#规格/测试 | 预览、双窗、QTH/设备编辑、IME、选区目标、列表/持久化列预期/结果/源码测试；正常画面不报bug。 |
| MEDIA-TODO-07 | 条件性兼容 | 必需读取器确有需求才核UDTA/长帧。 | P3 | [ ] | MEDIA-TODO-01、ENG-000 | MEDIA-001/002；授权副本/读取器 | 独立证明实际读取/感知影响或保留录制观察；不改原hash、不转码掩盖、不归因当前卡顿。 |
| MEDIA-TODO-08 | 可测试边界建议 | 有源码证据才规划最小职责边界。 | P2 | [ ] | MEDIA-TODO-06、PLAN-P2-DESIGN | 当前C#解析/状态/字段提交/持久化 | 沿现有命名结构逐项回归；不凭录像指定类、不全面换架构。 |

## 交付与阶段闸（18项）

| ID | 名称 | 描述 | 优先级 | 状态 | 依赖 | 文件/模块 | 验收 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DOC-001 | 正式审计docs | 用获准原生补丁工具落六份自包含文档。 | P1 | [x] | 无 | docs/audit/PHASE0_AUDIT_REPORT.md、PHASE0_TODO.md、FUNCTION_INVENTORY.md、SOURCE_COVERAGE.md、ISSUE_INVENTORY.md；docs/triage/NVIDIA-Netease-issues.md | git apply检查/应用及落盘读取、82任务/65来源、依赖无环/链接有效/六文件边界校验成立；旧工具缺口已解决，不以团队板代替正文；不是源码功能完成。 |
| PLAN-P1-DOC | 长期文档工作流 | 建立并持续维护下节指定文档。 | P1 | [ ] | DOC-001、NAT-T025、LB-T01、LB-T10、ENG-003 | 根AGENTS/TODO/CHANGELOG；docs/PROJECT_CONTEXT、DECISIONS、ISSUE_INVENTORY；本审计包/素材册 | 满足下节十五类、五类事实、八字段四状态/优先级、Keep-a-Changelog及前读后同步；当前不新建这些未来文件，Phase4/5真实结果持续回填。 |
| PLAN-P2-IA | 全软件信息架构 | 页面/导航/职责/数据关系/用户路径/状态/快捷操作。 | P1 | [ ] | ENG-000、NAT-T026、LB-T02、LB-T08、DOC-001 | 未来docs/UI_INFORMATION_ARCHITECTURE.md；全页面/主小窗/对话框；29功能/兼容 | 唯一导航/状态真源，保留业务，覆盖下节UI合同；不是只保留旧布局，不删功能、不加未确认QSO/ADIF。 |
| PLAN-P2-DESIGN | 完整UI及安全设计闸 | 页面/组件/色字间距/动画/交互状态与关键页；兼顾最小技术/回滚。 | P0 | [ ] | PLAN-P2-IA、NAT-T001 | 未来设计规范包；数据/场次/导出/目录/媒体/更新方案 | 全软件重设计及三主题/11态/简洁桌面方向齐；关键页面先确认再大规模实现，Medium影响先复核，不预设新框架/依赖/接口层。 |
| PLAN-P3-DATA | 数据安全批次 | 统一别名的安全修复汇总验收。 | P0 | [ ] | PLAN-P2-DESIGN、NAT-T002、NAT-T003、NAT-T004、NAT-T005、NAT-T006、NAT-T007、ENG-008、ENG-009、ENG-010、ENG-011、ENG-012、LB-T03、LB-T04、LB-T05、LB-T07 | 导出/目标保护、备份schema、兼容/Store约束 | 先失败契约后最小修复，同补丁关联别名；对账/恢复/源目标保护齐再扩状态；生产另许可。 |
| PLAN-P3-STATE | 业务状态批次 | 输入/字段/场次/设置/列表。 | P1 | [ ] | PLAN-P3-DATA、NAT-T008、NAT-T011、NAT-T018、NAT-T019、NAT-T020、ENG-015 | VM/视图、Draft、Store、设置 | 认可业务合同逐项闭合，DB/VM/UI一致、失败保原文；候选/清空/撤销不擅改，无无关格式化。 |
| PLAN-P3-CATALOG | 资料批次 | 重建/优先级/同步/本地树。 | P1 | [ ] | PLAN-P3-DATA、NAT-T009、NAT-T010、NAT-T012、NAT-T013、ENG-013、LB-T06 | CatalogService/Loader/Snapshot；MIIT partial/checkpoint | fixture证明重载/冲突/取消完成/游标/保正式库；官网另许可单列，不造第二词典/下载通道。 |
| PLAN-P3-MEDIA | 媒体生命周期批次 | 既有录屏/mic/停止关闭安全。 | P1 | [ ] | PLAN-P3-DATA、PLAN-P4-PLATFORM、NAT-T014、NAT-T015、NAT-T016、ENG-014 | WinMM/Media Foundation/PrintWindow与关闭链 | 平台契约先核，默认mic关/窗口限定/失败释放/并发停止关闭/长录同步阈值有证据；素材观察不代替产品测试。 |
| PLAN-P3-UPDATE | 更新批次 | 下载/安装/回滚与现有发布合同。 | P1 | [ ] | PLAN-P3-DATA、NAT-T017、ENG-007 | C/Updates/NativeUpdateService.cs；About安装 | 同源hash与签名分清，URI/限额/篡改/失败/回滚隔离验，不碰真实稳定指针。 |
| PLAN-P3-STRUCT | 最后职责收敛 | 仅获准且有真实耦合/重复证据时抽取。 | P2 | [ ] | PLAN-P3-STATE、PLAN-P3-CATALOG、PLAN-P3-MEDIA、PLAN-P3-UPDATE、NAT-T024、ENG-016、MEDIA-TODO-08 | 主小窗适配、字段消费、大类边界 | 第二真实调用者前不造接口/工厂/注册表/旋钮；一次一边界可回退，无第二实现；暂缓不假完成。 |
| PLAN-P3-UI | 全页面UI实施 | 按获批方向分批统一界面、组件、三主题及交互。 | P1 | [ ] | PLAN-P2-DESIGN、PLAN-P3-DATA、PLAN-P3-STATE、PLAN-P3-CATALOG、PLAN-P3-MEDIA、PLAN-P3-UPDATE、NAT-T022 | 全页面/主小窗/场次字段对话框/列表资料录屏设置关于更新 | 不缩成换色修补；每批覆盖下节矩阵、保业务、针对测试、版本证据/回退及TODO/CHANGELOG/必要CONTEXT/AGENTS同步。 |
| PLAN-P4-PLATFORM | 平台前置复核 | .NET10 PCM与本地Windows SDK COM/HRESULT/PreserveSig。 | P1 | [ ] | ENG-000、ENG-002 | 合成probe；现有媒体边界 | 签名/运算/回调语义逐项有依据，无依据不判ABI错；不下载SDK、不用生产媒体，缺材料如实阻塞。 |
| PLAN-P4-CORE | 核心分层验收 | 纯函数/隔离DB/OpenXml/HTTP故障。 | P0 | [ ] | PLAN-P3-DATA、PLAN-P3-STATE、PLAN-P3-CATALOG、ENG-014 | 现有xUnit解析/Store/迁移/导出/目录/更新fixture | 5001/10001、schema/WAL/取消/冲突/正式库hash，失败/Skip/TRX/版本齐；各修复前后滚动验。 |
| PLAN-P4-UI | 真实桌面矩阵 | 全新UI/三主题/全页面状态与真实Windows交互。 | P1 | [ ] | PLAN-P4-CORE、PLAN-P3-STATE、NAT-T022、ENG-017、PLAN-P3-UI | 当前候选全页面/主小窗/对话框；U项目/真实桌面 | 系统变化/浅深、Win10/11、全部窗口状态、DPI/多屏/字体、键盘焦点/真实IME/读屏/高对比；图像绑版本，模拟IME/预览/旧PASS不代替。 |
| PLAN-P4-MEDIA | 真实媒体验收 | 能力分层、非对称画面、设备/解码/长录。 | P1 | [ ] | PLAN-P4-PLATFORM、PLAN-P3-MEDIA、ENG-014、ENG-017 | 纯fixture/受控窗口/获准设备 | stride方向、覆盖窗口安全、权限/拔设备/默认mic关/拒覆盖、暂停/resize/音画同步；无设备明确Skip，不过滤抹失败。 |
| PLAN-P4-E2E | 业务/性能兼容签署 | 当前EXE完整链与有限金标准。 | P1 | [ ] | PLAN-P4-CORE、PLAN-P4-UI、PLAN-P4-MEDIA、PLAN-P3-UPDATE、LB-T09、NAT-T021、NAT-T023、MEDIA-TODO-06 | 当前候选；合成库/工作簿/回归矩阵 | 输入→提交→字段改→切场→重启→全导出/恢复对账；性能兼容达标；若批次含结构调整另验PLAN-P3-STRUCT，历史画面不算PASS。 |
| PLAN-P5-BUILD | 干净构建打包 | 隔离SDK10/Native自包含win-x64候选及双清单附件。 | P0 | [ ] | PLAN-P4-E2E、ENG-001、ENG-002、ENG-004、ENG-005、ENG-017、LB-T10、LB-T11、NAT-T027 | 获准SDK/资产/发布输入；隔离产物 | restore/build/test/publish分别获准留日志；commit+dirty/SDK/依赖/EXE SHA/签名策略/用例/Skip齐；无Python目标机运行，资源可追溯。 |
| PLAN-P5-RELEASE | 最终发布闸 | 现场、安装回滚、promotion与签署。 | P0 | [ ] | PLAN-P5-BUILD、ENG-006、ENG-007、PLAN-P1-DOC、MEDIA-TODO-03 | 专用演练；候选→稳定；最终文档/用户签字 | 安装/旧版恢复、不可变资产/并发降级/hash回读成立；文档和历史构建决定齐；产品验收与正式发布另授权，未许可不推送发布。 |

## Phase1长期文档合同（尚未实施）

| 文件/流程 | 必须内容 |
| --- | --- |
| 根AGENTS.md | 简洁规则入口并引用详情；必须含下表十五类，不以本审计包代替后续入口。 |
| docs/PROJECT_CONTEXT.md | 区分事实、当前实现、计划、推测、待确认五类；真实入口/模块/数据/SDK依赖/证据版本，不把计划写成已实现。 |
| 根TODO.md | 八字段、P0–P3、[ ]/[/]/[x]/[!]四状态、完整依赖与验收；不丢任务/来源/阻塞。 |
| 根CHANGELOG.md | Keep-a-Changelog，仅实际发生且有对应验证的变更；不预填未实施UI/未运行PASS，不把审计发现当功能完成。 |
| docs/DECISIONS.md | 获批方案、约束、依据/取舍/影响；UI方向/主题/兼容/数据安全/签名等，未确认仍待确认。 |
| docs/ISSUE_INVENTORY.md | 长期入口保留所有来源/别名/类别/风险/证据/未复现/修复验收状态；与本audit快照区分，路径近似不漏交。 |
| 既有文档/审计包 | 获准后治理README/native指南/架构/备份/验收/版本标签；保留本六文档及素材原件，动态结果后续回填。 |
| 任务前/后 | 前读AGENTS、PROJECT_CONTEXT、TODO；后同步TODO、CHANGELOG，按变化更新必要CONTEXT/AGENTS；每个Phase3批次同样执行，状态有证据。 |

| AGENTS类别 | 规则内容与详情落点 |
| --- | --- |
| 01产品技术栈 | 当前唯一C#/.NET/WPF、历史/工具边界、不擅改栈；CONTEXT/DECISIONS。 |
| 02结构职责 | 维护源/测试/资源/生成物、入口/职责；CONTEXT/覆盖。 |
| 03文档流程 | 前读三入口、后同步，简洁引用；CONTEXT/TODO/CHANGELOG。 |
| 04任务完成定义 | 八字段、四状态、P0–P3、依赖/验收；TODO/长期问题。 |
| 05证据未知 | 五类上下文、静态动态分开；CONTEXT/长期问题。 |
| 06Git既有工作 | 最小diff，保用户修改/未跟踪，不擅清理暂存提交；CONTEXT/DECISIONS。 |
| 07质量错误处理 | 不留自己造成的死代码/未使用参数/标记/注释掉代码、不吞错、不误删XAML事件/接口约束；DECISIONS/问题。 |
| 08复用依赖 | 标准库→仓库→已装依赖，真实调用才抽象，新依赖说明理由；DECISIONS/CONTEXT。 |
| 09UI主题交互 | 整软件设计、三主题、桌面视觉/状态/动画/禁用风格；IA/设计规范。 |
| 10Windows可访问性 | Win10/11、窗口/DPI/多屏/字体/焦点键盘IME读屏；规范/TODO/验收。 |
| 11数据兼容 | SQLite真源、原文审计/场次不变量、旧表字段合同、不擅删功能；CONTEXT/DECISIONS。 |
| 12备份迁移恢复 | 一致快照/恢复合同先行，隔离故障、生产另许可；DECISIONS/TODO/验收。 |
| 13隐私素材网络 | 原素材保全，上传下载同步须批准、历史构建缺口可见；素材册/问题。 |
| 14测试SDK门禁 | SDK/TFM资产匹配、分层、版本hash、失败/Skip/BLOCKED/NOT_RUN不混PASS；CONTEXT/TODO/验收。 |
| 15版本发布 | 只记验证事实、候选稳定分离、签名/回滚/promotion/正式发布另授权；CHANGELOG/DECISIONS。 |

## Phase2至Phase4完整UI合同

| 维度 | 已确认要求/验收 |
| --- | --- |
| 覆盖 | 全页面、导航、主小窗、场次/字段对话框、列表、资料/地点/MIIT、录屏/mic、设置、关于/更新、共用组件；29功能业务保留，不以旧布局为上限。 |
| Phase2输出 | IA含页面/导航/职责/数据关系/用户路径/重要状态/快捷操作；完整设计/页面/组件/颜色/字体/间距/动画/状态规范及关键页，交付清单登记规范包文件名，当前不冒称已生成。 |
| 主题/方向闸 | 系统/浅色/深色确定；系统变化规则与全部窗口组件一致；确认具体关键页方向后Phase3实施，不重复确认功能需求。 |
| 桌面视觉 | 简洁直接、非网页，单品牌强调色，成功/警告/错误仅表状态；不大渐变/滥玻璃/发光/巨圆角阴影/装饰卡片/巨统计/Hero/emoji/无意义复杂动画/过多弹窗。 |
| 十一状态 | Default默认、Hover悬停、Pressed按下、Focus焦点、Selected选中、Disabled禁用、Loading加载、Success成功、Error错误、Empty空、Offline离线；逐组件页面标适用行为，不适用有理由。 |
| 短反馈动画 | 状态/反馈语义，不阻塞、不每按钮缩放；悬停80–120ms、按钮60–120ms、菜单100–180ms、弹窗150–220ms、页面150–250ms为初始建议，可说明设计理由调整。 |
| 系统/窗口 | Win10与Win11，连续缩放/最小化/最大化/还原，主800×600/小420×190基线和标准边框可用；不以声明或审计机代替实测。 |
| DPI/字体/多屏 | 100%及125/150/200%，混合DPI/跨屏、多屏、Windows字体缩放，查裁切溢出/对齐滚动/可操作。 |
| 输入/无障碍 | 可见焦点/正确流转、快捷操作/选择/取消/确认一致；真实微软拼音候选Enter、读屏、高对比，不靠模拟IME/预览证明。 |
| 实施/回归 | 每批获批页面/组件/主题/状态范围、业务回归/针对测试、当前版本证据与回退，前读后同步；Phase4汇总与Phase5发布闸仍独立。 |

本次只做文档落盘校验，运行验收均NOT_RUN。报告及计划交Lead等待用户确认，不自动实施。
