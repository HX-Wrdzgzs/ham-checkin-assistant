# 源码、测试、工程与材料覆盖

日期：2026-11-14。上游已分段全文静态阅读56个维护文件：44 C#、8 XAML、3 csproj、1 manifest；另1嵌入资源只核引用/加载方式。当前产品源若不含csproj为53，不能与56/57混算。本次将独立审阅结果正式落档，不重复产品调查或运行。

路径相对仓库根：A=native/src/HamCheckin.Native.App；C=native/src/HamCheckin.Native.Core；B=native/src/HamCheckin.Native.Benchmarks；T=native/tests/HamCheckin.Native.Tests；U=native/tests/HamCheckin.Native.UiTests。同一单元格中后续裸文件名沿用最近已写出的目录前缀；下表行号对应本次工作树，后续改码可能漂移。

[综合报告](PHASE0_AUDIT_REPORT.md) · [功能](FUNCTION_INVENTORY.md) · [问题](ISSUE_INVENTORY.md) · [任务](PHASE0_TODO.md) · [素材](../triage/NVIDIA-Netease-issues.md)

## 1. 全部维护文件（56项）

所有行覆盖信心High指静态阅读完整；运行状态一律NOT_RUN，不是行为通过。

| 序号 | 文件:范围 | 职责与已读入口 |
| --- | --- | --- |
| 01 | A/App.xaml.cs:1–192 | 启动/参数/隔离/单实例/退出；OnStartup20、VM114、Initialize120、Dispose130。 |
| 02 | A/App.xaml:1–159 | 色板/按钮/导航/输入/表格模板；固定浅色、按钮状态64–73。 |
| 03 | A/MainWindow.xaml:1–17 | 主窗800×600最小、标准边框/缩放/舍入/ContentView。 |
| 04 | A/MainWindow.xaml.cs:1–101 | 全局热键注册回退及释放；34、57–75。 |
| 05 | A/ViewModels/MainViewModel.cs:1–1055 | 草稿/解析/场次/提交/导出/资料/设置协调；命令84、初始化265、提交830、释放1030。 |
| 06 | A/Views/MainView.xaml:1–255 | 五页导航、场次/输入/表格/资料/录屏/设置；绑定73–92、155–246。 |
| 07 | A/Views/MainView.xaml.cs:1–1022 | 输入125、页面289、媒体526、字段731、场次844、布局快捷键。 |
| 08 | A/Views/QuickWindow.xaml:1–96 | 小窗输入28/提交29、候选57–65、最近3、置顶。 |
| 09 | A/Views/QuickWindow.xaml.cs:1–205 | 草稿同步/IME/快捷提交/隐藏；62、163、Closing200。 |
| 10 | A/Views/FieldEditWindow.xaml:1–89 | 字段/候选/片段/保存；74、86。 |
| 11 | A/Views/FieldEditWindow.xaml.cs:1–183 | 限定解析78、FillToken101、复制/Save132。 |
| 12 | A/Views/SessionEditorWindow.xaml:1–59 | 名称/日期/主控/中继/Excel路径。 |
| 13 | A/Views/SessionEditorWindow.xaml.cs:1–78 | 旧名称日期只读30–35、校验/结果52–58。 |
| 14 | A/Views/SessionPickerWindow.xaml:1–37 | 本地场次/状态/下一序号、双击选择。 |
| 15 | A/Views/SessionPickerWindow.xaml.cs:1–56 | Select23、Enter/Esc43、取消。 |
| 16 | A/Views/AboutWindow.xaml:1–75 | 版本/说明/更新/赞助；进度63、下载默认禁用69。 |
| 17 | A/Views/AboutWindow.xaml.cs:1–274 | 检查44、下载104、Installer217；说明文本化。 |
| 18 | A/Views/PreviewRenderer.cs:1–184 | 开发离屏WPF效果图RenderSet18、96DPI145；示例非业务数据。 |
| 19 | A/Infrastructure/ObservableObject.cs:1–24 | 属性通知SetProperty10–19。 |
| 20 | A/Infrastructure/RelayCommand.cs:1–50 | ICommand、异步单命令防重入14–49。 |
| 21 | A/Infrastructure/ShortcutGesture.cs:1–84 | TryParse20、精确修饰键匹配17。 |
| 22 | A/Infrastructure/GlobalHotkeyService.cs:1–89 | Win32 RegisterHotKey/WM_HOTKEY，注册20、释放60。 |
| 23 | A/Infrastructure/WindowsBackdrop.cs:1–45 | Win11 DWM/圆角/浅标题栏；旧系统不调15–18、dark=0。 |
| 24 | A/Media/RecordingModels.cs:1–55 | 窗口/mic目标、Options17、State25、结果。 |
| 25 | A/Media/ScreenCapture.cs:1–107 | 客户区BGRX/PrintWindow19，失败不桌面回退58–64。 |
| 26 | A/Media/ScreenRecordingService.cs:1–570 | 开始81、停止205、采集365、临时MP4/收尾。 |
| 27 | A/Media/MicrophoneCapture.cs:1–413 | WinMM/PCM/电平/非托管缓冲；Start167、Callback274、Stop318、Peak366。 |
| 28 | A/Media/Mp4FileWriter.cs:1–408 | H.264/AAC、样本时钟/释放；Video89、Audio111、Complete141、引用计数366。 |
| 29 | A/Media/MediaFoundationInterop.cs:1–230 | DLL/COM ABI；MFStartup33、IMFMediaType112、SinkWriter217；尚未逐一对照SDK。 |
| 30 | A/Properties/AssemblyInfo.cs:1–3 | UI测试内部可见性。 |
| 31 | A/HamCheckin.Native.App.csproj:1–29 | WPF/net10、框架WindowsForms、Core引用27。 |
| 32 | A/app.manifest:1–22 | identity/asInvoker7、PerMonitorV2 18、长路径。 |
| 33 | C/Models.cs:1–172 | 解析/Session/Checkin/字段审计DTO，13、33、44、109–155。 |
| 34 | C/RuntimeOptions.cs:1–69 | 进程内测试时钟/延迟/禁网，Configure50，非生产配置存储。 |
| 35 | C/Storage/AppPaths.cs:1–45 | 用户数据/备份/cache/旧路径和隔离；Native40、旧44。 |
| 36 | C/Storage/NativeStore.cs:1–767 | schema3/场次/事务/查询/字段审计；42、349、427、493。 |
| 37 | C/Storage/LegacyPythonMigration.cs:1–471 | C#旧格式导入，TryImport25、备份298；非Python运行入口。 |
| 38 | C/Storage/LegacyProfileReader.cs:1–51 | 旧库只读画像ReadAsync7；未找到App调用。 |
| 39 | C/Storage/ProfileAggregator.cs:1–38 | 频次/最近值聚合，仅Reader:49调用。 |
| 40 | C/Parsing/TextNormalizer.cs:1–118 | NFKC/分词、呼号/功率/信号正则9–22、NormalizePower98。 |
| 41 | C/Parsing/QuickInputDraftService.cs:1–198 | 双窗文本修订/IME，Edit64、条件Clear149。 |
| 42 | C/Parsing/InputParser.cs:1–342 | 确定整行解析/未知原文；Parse27、未知264–276、未识别278。 |
| 43 | C/Parsing/FieldParser.cs:1–127 | 限定字段/候选；Parse25、单设备候选92–99。 |
| 44 | C/Catalogs/CatalogService.cs:1–18 | Volatile读7、Reload9–16快照替换。 |
| 45 | C/Catalogs/CatalogLoader.cs:1–588 | 内置资源12、本地库244、旧别名408–489。 |
| 46 | C/Catalogs/CatalogSnapshot.cs:1–990 | 型号45、QTH95–260、查询263、前后缀516。 |
| 47 | C/Catalogs/NationwideAdminCatalog.cs:1–147 | 资源14–19、解码97–136、省码别名。 |
| 48 | C/Catalogs/QthPackageService.cs:1–149 | 本地全国树12、COUNT40；无下载实现。 |
| 49 | C/Catalogs/MiitCatalogSyncService.cs:1–669 | Sync118、重试294、HTTP331–408、替换597。 |
| 50 | C/Catalogs/Sm3.cs:1–89 | 公开接口摘要HashHex12，非用户认证/加密。 |
| 51 | C/Export/ExcelExportService.cs:1–435 | 九列新xlsx、InlineString、临时校验；23、70、303。 |
| 52 | C/Updates/NativeUpdateService.cs:1–386 | 版本/三路检查/受限下载/SHA；77、136、295。 |
| 53 | C/Properties/AssemblyInfo.cs:1–3 | 核心测试内部可见性。 |
| 54 | C/HamCheckin.Native.Core.csproj:1–13 | net10、Sqlite10.0.12/OpenXml3.1.1、资源11。 |
| 55 | B/Program.cs:1–134 | 解析20000次/SQLite临时150条基准/JSON，非应用启动基准。 |
| 56 | B/HamCheckin.Native.Benchmarks.csproj:1–10 | 独立控制台仅引用Core。 |

## 2. 资源（1项）

| 资源 | 实际覆盖 | 明确未覆盖 |
| --- | --- | --- |
| C/Catalogs/nationwide-admin.tsv.gz.b64 | 目录存在、C/HamCheckin.Native.Core.csproj:11引用、C/Catalogs/NationwideAdminCatalog.cs:97–136加载解码机制。 | 未解压逐条核地理准确性/来源license/生成链；资源自证测试不是独立金标准。 |

## 3. 测试源（14项，全部NOT_RUN）

| 文件:范围 | 静态已读覆盖/缺口 |
| --- | --- |
| T/ParserTests.cs:1–549 | 整行金标准/全国缩写/同名候选/视频派生文本/未知保留，非本轮看视频。 |
| T/FieldParserTests.cs:1–170 | 限定字段/全国别名，地理期望部分来自同一资源。 |
| T/QuickInputDraftServiceTests.cs:1–149 | 前中尾/旧修订拒绝/IME元数据/条件清空，非真实IME。 |
| T/CatalogLoaderTests.cs:1–149 | 一次装载/本地优先/两候选，缺二次替换删除。 |
| T/QthPackageServiceTests.cs:1–85 | 全国树/本地数，非远程下载。 |
| T/NativeStoreTests.cs:1–150 | 25条原子序号/无呼号拒绝/生命周期/字段与重复token，缺跨Store/结束并发。 |
| T/NativeEndToEndTests.cs:1–213 | 501条/重启/字段/xlsx，未触发5001。 |
| T/LegacyPythonMigrationTests.cs:1–126 | 两条旧记录/备份存在/不重复，不是恢复/WAL故障验证。 |
| T/MiitCatalogSyncTests.cs:1–143 | SM3/两条单页/403快停，缺分页取消续传与旧库hash。 |
| T/NativeUpdateServiceTests.cs:1–133 | API/校验/main回退/对错SHA，未验安装器。 |
| T/ExcelExportTests.cs:1–104 | 元数据/九列/OpenXml/公式样式InlineString。 |
| T/VideoReplayEndToEndTests.cs:1–303 | 已转录文本重放解析/库/编辑/重启/导出，非本轮原视频观看。 |
| T/GlobalUsings.cs:1 | xUnit全局引用。 |
| U/QuickInputUiTests.cs:1–1513 | WPF控件/共享VM/布局/媒体短测/隔离更新；非当前黑盒实测，媒体方向/关闭/超时不足。 |

测试LOC为3788：149+104+170+1+126+143+213+150+133+549+85+149+303+1513；旧3888已纠正。89 Fact/18 Theory/140 InlineData，核心约196/UI33只是静态展开估计，不是本轮发现/通过数。

## 4. 维护工程输入（7项）

前三项已计入56，表内重复登记职责，不再加成63。

| 工程文件:范围 | 静态覆盖 |
| --- | --- |
| A/HamCheckin.Native.App.csproj:1–29 | net10-windows/WPF/框架引用/Core/版本/manifest。 |
| C/HamCheckin.Native.Core.csproj:1–13 | net10、两直接包、嵌入资源。 |
| B/HamCheckin.Native.Benchmarks.csproj:1–10 | net10控制台/Core。 |
| T/HamCheckin.Native.Tests.csproj:1–20 | net10/xUnit2.9.2/TestSDK17.12.0/runner2.8.2/Core。 |
| U/HamCheckin.Native.UiTests.csproj:1–21 | net10-windows/WPF/同测试包/App。 |
| native/Directory.Build.props:1–9 | nullable/implicit usings/确定性/推荐分析器。 |
| native/HamCheckin.Native.sln:1–43 | App/Core/Benchmarks/核心测试/UI测试五项目。 |

## 5. 其他工程、历史材料与完整清单边界

E=C:\Users\wrdzgzs\AppData\Local\Temp\opencode\ham-phase0-20261114-000334\engineering；仅原始本地证据，正文覆盖事实已列，不把临时材料当已交付正式文档。

| 对象 | 实际覆盖/证据 | 限制 |
| --- | --- | --- |
| 跟踪全表 | E/maintained-scope-review-all-224.csv登记224项路径/角色/行数或二进制/hash；跟踪文本静态扫描。 | 不是SDK/.venv/二进制人工逐行审查。 |
| 发布/工具 | .github/workflows/ci.yml、release.yml、release.py、updates/latest.json；工程配置/版本/发布链已读。 | Python工具/兼容测试不是第二现行产品；不执行。 |
| 自有辅助工程 | 10份csproj和10份Program.cs：准确性、工作簿、更新探针及7份发布黑盒；E/all-owned-projects-source.txt及supplemental-maintained-source-review.csv。 | 硬编码EXE/删固定输出/全局按键/联网等副作用已登记；本轮不运行，不当维护产品源。 |
| 历史辅助脚本 | artifacts/dotnet-install.ps1及native/artifacts/build_stable_report.py在22项补充表。 | 前者第三方，后者历史报告工具，未执行安装；不当产品依赖。 |
| 说明登记 | 139非依赖/非生成说明、201环境生成说明、31维护/候选清单条目含requirements.txt；E/existing-documents-complete.csv等。 | requirements是依赖非说明；历史artifacts登记不等全部内容为当前规范。 |
| 已读主要文档 | README/CHANGELOG/RELEASE_GATE；native/README及ARCHITECTURE/VERIFICATION/ACCEPTANCE-TEST/USER-GUIDE/performance-latest.json；docs/usage-flow.svg；tests/fixtures/README；20份release-notes（19跟踪+1未跟踪）。 | 旧Python入口/备份/不迁移/旧Gate与当前行为冲突，后续治理；原usage-flow.svg保持。 |
| 历史Python | 仅当前C#旧数据消费、资料装载、发布工具/文档边界；旧tests AST方法/副作用登记及语料。 | 已停止旧Python全源码逐文件/全功能独立计划，不冒称完成，不继续发展旧产品。 |
| 文件系统 | E/workspace-all-files-classified.csv登记除.git外18295文件；.venv7370、第三方SDK5577等分类。 | SDK有808被原ignore排除；5577文件系统数不等4769 Git未跟踪SDK数。 |
| 未跟踪完整路径 | E/untracked-complete-6168.txt、untracked-metadata-complete.json、untracked-classification-complete-6168.csv。 | 原metadata5602少566，是覆盖不足；补全路径不代表6168全hash，不清理/改ignore。 |
| 源素材 | 另册1个约10GB MP4，341帧实例视觉抽样及完整时间轴机械扫描。 | 原片不在6168仓库清单中混算；不是逐帧/当前功能验收。 |

| 原未跟踪类别 | 数量 | 字节数 |
| --- | --- | --- |
| 第三方SDK | 4769 | 804351256 |
| 历史图片/材料/UI证据 | 712 | 75119700 |
| 历史TRX | 260 | 28326996 |
| 历史文档/日志/JSON | 221 | 816268 |
| 历史二进制/包 | 131 | 4488581213 |
| obj生成内容 | 50 | 575872 |
| 自有审计/黑盒源项目 | 20 | 159890 |
| 视频/录屏材料 | 3 | 312696 |
| 第三方安装脚本 | 1 | 76676 |
| 候选说明 | 1 | 985 |

本轮新增六份docs是基线之后的明确增量，不把6168旧清单当落盘后的未跟踪总数。构建、测试、基准、运行、同步、恢复、发布均NOT_RUN；覆盖完整不等功能正确。
