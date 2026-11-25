# Phase0 综合审计报告

| 项目 | 结论 |
| --- | --- |
| 日期/仓库 | 2026-11-14；H:\HAM EXCEL |
| 当前唯一产品 | C# / .NET 10 / WPF 点名助手；Python仅历史代码、旧数据格式和部分开发/发布工具，不是另一套现行产品。 |
| 本次交付 | 仅新增本审计包六份正式文档；综合静态源码、工程只读测量、历史兼容边界及素材证据，不实施重构。 |
| 签署状态 | 带限制提交，等待用户确认报告、优先级及后续阶段；文档落盘不等于产品通过，不自动进入Phase1。 |
| 证据分层 | 已确认表示源码/配置条件或素材观察成立，不代表现场事故；高度疑似表示条件性影响；待验证与设计建议另列。当前源码问题未运行复现、未修复。 |
| 当前计数 | 33 NAT + 18 ENG + 10 LB + 4 MEDIA = 65条来源；不是65个已确认产品缺陷，也不捏造去重后的独立bug总数。82项任务含阶段闸，不能当缺陷数。 |
| 操作限制 | 不改既有文件、源码、配置、数据库、原素材；不启动应用、构建、测试、基准、迁移、同步、联网安装；不清理、暂存、提交或发布。 |

按用户2026-11-14指令，本轮不包含素材声音/语音审查；原视频音轨保留

## 1. 正式文档导航与证据口径

| 文档 | 自包含交付内容 |
| --- | --- |
| [完整任务](PHASE0_TODO.md) | 82项八字段任务、四状态、完整依赖和阶段合同。 |
| [功能清单](FUNCTION_INVENTORY.md) | 29行九列，区分已实现、部分、未接通和领域边界。 |
| [覆盖清单](SOURCE_COVERAGE.md) | 56维护文件、1资源、14测试源、7工程输入，及生成物/历史材料边界。 |
| [问题台账](ISSUE_INVENTORY.md) | 65条来源逐项证据、分类、严重性、复现状态、原因/影响、建议与验收，另有主题去重映射。 |
| [素材另册](../triage/NVIDIA-Netease-issues.md) | 唯一MP4清单、保全、时间轴/视觉抽样和4条独立素材记录。 |

本包正文不依赖临时团队板才能理解。源代码位置均相对仓库根；缩写A=native/src/HamCheckin.Native.App，C=native/src/HamCheckin.Native.Core，B=native/src/HamCheckin.Native.Benchmarks，T=native/tests/HamCheckin.Native.Tests，U=native/tests/HamCheckin.Native.UiTests；缩写后的文件名接在该前缀下，不能当根目录文件。同一单元格中后续裸文件名沿用最近已写出的目录前缀。

原始日志、完整逐文件清单和机器本地证据保留在 C:\Users\wrdzgzs\AppData\Local\Temp\opencode\ham-phase0-20261114-000334。下文E=该根下engineering，M=该根下media。它们不是正式文档替代物；迁机或临时目录清理后可能不可访问，需另获批准归档，不在本轮移动或复制原件。

## 2. 项目、环境、版本与Git保护

| 对象 | 已知事实 | 限制/后续 |
| --- | --- | --- |
| 架构 | App是WPF窗口/手写MVVM、命令和事件代码；Core处理解析、目录、SQLite、导出、更新；Benchmarks为独立控制台；两xUnit项目。解决方案共5项目。 | 不换技术栈，不把全面UI重设计等同重写业务后端。 |
| 目标框架 | App net10.0-windows，UseWPF和WindowsForms框架引用；Core/Benchmarks net10.0；核心测试net10.0，UI测试net10.0-windows/WPF。 | App的WindowsForms引用服务媒体绘图，不是产品换成WinForms。 |
| 直接依赖 | Microsoft.Data.Sqlite 10.0.12、DocumentFormat.OpenXml 3.1.1；Test SDK 17.12.0、xunit 2.9.2、runner.visualstudio 2.8.2。 | 已有assets/缓存登记25种包版本，不代表当前EXE实际装载图；本次新依赖0。 |
| 系统测量 | Windows NT 10.0.26300 x64、PowerShell 7.6.9、Git 2.54.0.windows.1。PATH的C:\Program Files\dotnet\dotnet.exe使用SDK 8.0.422、MSBuild17.11.48、Host10.0.10。 | 运行时10不等于SDK10；当前PATH不足以证明可编译net10。 |
| 已实测私有SDK | C:\Users\wrdzgzs\.codex\dotnet10\dotnet.exe为SDK10.0.401、MSBuild18.9.11、Host/NETCore/WindowsDesktop10.0.12，无workload。 | 后续明确选择可信SDK；artifacts/dotnet10-sdk仅登记为未跟踪第三方内容，未执行。 |
| 资产与复现 | App旧assets为net8.0-windows7.0，Core/核心Tests为net8.0；Benchmarks/UI.Tests为net10。无维护global.json、packages.lock.json、NuGet.Config、RestoreLockedMode。 | 不清obj、不restore、不新增锁文件；干净隔离构建可用性NOT_RUN。Actions/SDK范围版本和最新CVE/签名未核。 |
| 运行/发布边界 | 已审C#运行链未见Python子进程；EXE来自dotnet publish自包含Native。Tag流水线仍有历史Python测试和release.py元数据工具；HAM-legacy.exe为同字节兼容附件名。 | 不为语言口号删除release.py、历史测试或新造第二发布实现；尚无发布EXE动态进程取证。 |
| 分支/HEAD | codex/ham-checkin-release；1fd20a9b7d44a8fcad6af81c04c35697dcf0e013。 | 只读基线，不fetch；本地缓存远端引用+0/-0不证明实时远端一致。 |
| 原Git状态 | 224 tracked、11项未暂存修改、暂存差异0、6168未跟踪（artifacts6167、release-notes1）。 | 六份文档新增前的基线；所有原内容保留，不reset/clean/stash/回滚/格式化/更改ignore。 |
| 清单勘误 | 原metadata5602条，比完整Git清单少566；E/untracked-complete-6168.txt及分类CSV已补全。 | 差额是原清单覆盖不足，不是本轮新增566文件；未核全部6168文件哈希。 |
| 版本 | 工作树App/manifest/NativeVersion为1.0.20；README/native说明1.0.19；本分支updates/latest.json为1.0.5。 | 候选、说明、稳定指针语义不同；实时Release未知，不为表面一致提前刷新清单。 |
| 保全范围 | lead-final-preservation-check.json记录225个基线SHA零变化、30项运行元数据零变化、根config哈希不变、原未跟踪路径无增减。 | 225不是6168全量hash，元数据不等于内容恢复测试；不宣称数据库恢复或磁盘取证镜像已验证。 |

| 原有修改文件:行 | 原有内容与未验边界 | 原numstat +/− |
| --- | --- | --- |
| A/HamCheckin.Native.App.csproj:17–19 | 三处版本升1.0.20；不是本次实现。 | 3/3 |
| A/Media/MediaFoundationInterop.cs:13 | 新增MfMtDefaultStride GUID；平台契约待核。 | 1/0 |
| A/Media/Mp4FileWriter.cs:212–216 | 正stride=width*4；方向效果未实测。 | 5/0 |
| A/Views/AboutWindow.xaml:28 | 默认版本1.0.20。 | 1/1 |
| A/Views/AboutWindow.xaml.cs:30–32 | 候选说明/MIIT403文案不是测试证据。 | 3/1 |
| A/Views/MainView.xaml:246 | 设置页候选版本1.0.20。 | 1/1 |
| A/app.manifest:3 | identity=1.0.20.0，asInvoker未变。 | 1/1 |
| C/Catalogs/MiitCatalogSyncService.cs:1–102,171,308–355,381–387,627–639 | 请求头/Cookie/解压、预热、401/403快停；官网可用性/响应限额待验。 | 98/4 |
| C/Updates/NativeUpdateService.cs:11 | NativeVersion.Current=1.0.20。 | 1/1 |
| T/MiitCatalogSyncTests.cs:12–21,52–73,86–142 | fixture/403更新未预置旧正式库hash，不能证明保护成立。 | 69/2 |
| U/QuickInputUiTests.cs:721 | 版本断言同步，不是版本权威校验。 | 1/1 |

## 3. 架构、业务链与术语

| 业务链 | 当前行为与位置 | 保留/验收边界 |
| --- | --- | --- |
| 启动 | A/App.xaml.cs:114–120构造VM、Show后初始化；A/ViewModels/MainViewModel.cs:265–325初始化Store→检查旧库→场次→最近300条→Ready→后台外部资料装载，同时启动更新检查。 | 内置快照在VM构造时同步建立；不能说所有资料都后台加载。初始化失败仅提示，恢复/关闭待完善。 |
| 主/小窗输入 | A/Views/MainView.xaml.cs:125–245、QuickWindow.xaml.cs:62–184→C/Parsing/QuickInputDraftService.cs:64–193→InputParser.cs:27–299。 | 文本修订与焦点所有权保护原文，解析同步发生于输入事件；真实微软拼音、候选Enter、前中尾编辑待验。 |
| 解析与候选 | 内存词典确定性解析呼号、QTH、设备、天线、功率、信号；同名QTH显示候选，选择不改输入；未知token保留。 | 不把规格匹配当官方设备事实；单模糊设备候选自动替换和别名冲突有静态缺口。 |
| 提交 | A/ViewModels/MainViewModel.cs:830–884捕获场次/草稿修订；C/Storage/NativeStore.cs:349–425写门+Serializable短事务算序号、插入；成功按revision清草稿，失败留文。 | SQLite是真源，Excel不参与提交；active/ended不变量、重试幂等和关闭交错仍需合同/验证。 |
| 字段修改 | A/Views/MainView.xaml.cs:694–757→FieldEditWindow.xaml.cs:101–139→VM→C/Storage/NativeStore.cs:493–567。 | 只改enum白名单字段，比对UpdatedAt，同事务写field_edit_audit；不重解析整行、不改RawInput；历史点击累计消费和确认标记未落实。 |
| 列表/导出 | 重启或切场仅加载300条；LoadAllForExport仍经Clamp5000；OpenXml生成九列新xlsx、InlineString、临时结构校验后overwrite移动。 | 未加载不是删除；全量与UI分页须分离。导出目标、覆盖同意、同场快照及独立DB计数优先修。 |
| 资料/同步 | CatalogService原子交换引用；MIIT预热GET→POST/SM3→partial每页事务/断点→计数/quick_check→替换正式库→重载。 | 热输入不I/O；重载基线、优先级、取消完成、续传游标和筛选合同待闭合。地点按钮只刷新本地树，尚无远程包下载链。 |
| 更新 | GitHub API→main→兼容分支回退；不自动下载；现有URL/250MB/SHA保护；About通过cmd等旧PID退出再替换重启。 | 同源hash不等于签名；安装握手、回滚、外部URI/元数据限额需设计，不能称已被攻击。 |
| 录屏/麦克风 | 仅主窗口客户区PrintWindow，失败不回退桌面；默认mic关闭，显式测试会开设备；H.264/AAC、partial收尾后拒覆盖移动。 | 保留既有业务；PCM/COM、失败释放、关闭等待、暂停/尺寸/长录音画同步须分层验证，与素材治理分开。 |

| 术语/规则 | 已确认含义 |
| --- | --- |
| 场次 | 最早日期/id的active优先，不是今天最后打开项；全ended才创建当天未用第N场。C/Storage/NativeStore.cs:140–184,614–625,644–672。结束后元数据可否编辑需业务决定。 |
| 重复呼号/序号 | 同场允许同呼号多次；唯一性是submission_id和未删除session_id+sequence_no，不能擅加callsign唯一。 |
| 原文/未识别 | Parser先Trim整行再对token做NFKC；RawInput不是原文件逐字节归档。字段编辑只应消费最终明确采用片段，重复token按索引区分。 |
| 本场/最近 | 目前共用Checkins缓存，完整本场浏览尚缺分页/总数；不能将显示数量当库总数。 |
| Excel绑定/补同步 | WorkbookPath/SheetName只是场次元数据；当前导出固定生成新文件，不存在Native补同步队列/旧受管列闭环。导出失败不得删除已提交签到。 |
| 领域边界 | 当前是签到/场次，不是已实现完整QSO日志；未发现ADIF/签到频率/波段/模式/经纬度对象，未获确认不新增。 |
| 辅助代码不算功能 | ProfileReader/聚合、is_undo、配置键、提示或按钮不能证明画像学习、记录撤销、365dt、历史导入、远程包已接通，也不构成删除授权。 |

## 4. 数据结构、安全与恢复

| 对象 | 当前结构/行为 | 风险与保护要求 |
| --- | --- | --- |
| ParseResult/ParseField | C/Models.cs:3–31：RawText/Tokens、六类解析字段、Unmatched；字段含Value/Source/Confidence/Raw/Candidates。 | 解析元数据不是已验证事实，也非全部逐字段持久化。 |
| sessions | C/Storage/NativeStore.cs:62–79：id/name/date/status、主控/中继、工作簿路径/表名、起止/创建/更新时间。 | 日期名称唯一；没有外部场次UID；TEXT日期校验、ended写约束待完善。 |
| checkins | 同文件:81–111：submission_id/session/sequence/time/callsign，QTH/设备/天线/功率raw+standard，signal/source/raw_input/unmatched、软删、Excel状态/时间戳。 | 原文/呼号/详细QTH涉及本地隐私；不捏造未见领域字段。 |
| field_edit_audit | 同文件:113–125,541–560：旧新值/未识别、消费token、来源、时间、is_undo。 | 存在审计写链，但未见查询UI/撤销执行链；旧值取commit.OldValue，领域控制仍需复核。 |
| 路径/权限 | C/Storage/AppPaths.cs:7–44默认%LOCALAPPDATA%/HAM点名助手/data/ham_checkin_native.db；asInvoker，不依赖EXE/CWD。 | 普通SQLite；未发现源码中的加密/专门ACL强化；本地威胁模型、备份ACL、可选加密需决策，不擅加账号联网登录。 |
| 写安全 | WAL、foreign_keys、busy_timeout、每实例SemaphoreSlim、短事务、enum列白名单和参数值。 | 保留已有机制；Windows会话单实例不代替DB不变量；NORMAL断电RPO、双Store交错NOT_RUN。 |
| Native升级/备份 | schema常量3，启动直接upsert3后补列；BackupRoot主要用于旧库导入前备份。 | 未见未来schema拒绝、完整版本迁移/回滚、Native每日备份/保留/checksum/验证恢复闭环；先恢复合同再扩大写入。 |
| 旧库导入 | C# ReadOnly源，空Native才导入sessions/非软删有效checkins；legacy-python:旧id、冲突序号顺延；完成marker与导入同事务。 | 先VACUUM INTO，失败顺序Copy DB/WAL/SHM，后读原库非同一快照；活动写入下的一致性/恢复未验。 |
| 旧资料依赖 | Loader仍只读旧四类别名；ProfileReader只读旧checkins最多300条聚合，未找到生产调用。 | 成功迁移不能删旧库。Native已有数据写永久skip marker；固定旧路径不自动发现自定义data_dir；必须可见提示。 |
| 未迁移资产 | raw_imports/import_jobs、station_profiles/stations、audit/completion日志、sync_state/source_station_state、外部来源键/旧Excel同步信息留旧库。 | 不是整库克隆；逐表/字段决定保留、只读依赖或明确不迁移；同日同名身份不能无说明合并。 |
| 可重建资料 | QTH/admin/MIIT目录库与签到库分离；MIIT写partial/checkpoint并quick_check后替换。 | SM3是公开请求摘要，不是用户认证/签到加密；401/403停止，不绕过。 |
| 导出/网络/媒体隐私 | InlineString防公式已有实现；已审HTTP链未见上传签到/RawInput/录屏；窗口限定、默认mic关、拒覆盖已有实现。 | 不作OS级绝对无外传保证；不上传真实库/原片/工作簿；素材共享须另授权脱敏衍生版。 |

## 5. 风险汇总与已有测试边界

| 顺序 | 主题与来源示例 | 下一步验收 |
| --- | --- | --- |
| P0基线/门禁 | ENG-001/002/014、NAT-032：普通CI只Python、SDK/缓存错位、旧PASS不绑定dirty1.0.20。 | 先批准隔离SDK/故障契约；新日志须含commit/dirty、SDK/OS、EXE SHA、失败/Skip/NOT_RUN。 |
| P0数据安全 | NAT-001～006、011及ENG-008～012、LB-04：全量截断、覆盖/会话快照、Native恢复/schema、旧库一致快照、ended事务。 | 5001/10001独立对账、原输出保护、合成库恢复/未来schema/并发WAL/双Store。不是本轮已复现事故。 |
| P1业务状态 | NAT-007～020、033、LB-02/03/05/07：字段消费、快照/冲突、场次完成、取消续传、快捷设置、列表/兼容身份。 | 认可合同+最小修复+逐项反例，复用现有机制；同一修复可覆盖别名，不造第二实现。 |
| P1媒体/更新 | NAT-021～027、ENG-006/007/013：生命周期/PCM/时钟疑似、失败释放、安装回滚、发布不可变性。 | Medium平台解释先复核；媒体分能力、真实长录同步；更新隔离故障和专用发布演练，真实网/生产另许可。 |
| P1/P2产品文档/UI | NAT-029～031、ENG-003/004/015～018、LB-01/08～10：能力/版本混写、未接线范围、完整UI设计及桌面适配。 | 已确认三主题与全软件重设计；设计方向确认后分批实施，不以旧布局/现有视觉为要求上限。 |
| 素材单列 | MEDIA-001/002/003/005。 | 读取兼容/长帧观察、共享治理、历史版本绑定；已确认当前产品缺陷0不意味着全部功能通过。 |

| 测试/证据 | 当前记录 | 不可推导的结论 |
| --- | --- | --- |
| 静态测试清单 | 14个C#源共3788行（含GlobalUsings），89 Fact/18 Theory/140 InlineData；核心约196/UI33为属性展开估计。 | 不是运行发现数、通过数或覆盖率；旧3888为已纠正笔误。 |
| 已有不足 | E2E501未触发>5000；迁移只happy path/备份存在；目录单页/一次重载；403缺正式库hash；MP4零帧/FourCC不证方向；无设备Skip、fixture等待缺超时。 | 不用旧测试代码或历史TRX替代本轮结果；COM ABI未对照SDK不能判错。 |
| 历史记录 | 1.0.19-r29的194/194、33/33，r35/r36及旧performance JSON仅历史。 | 不绑定当前1.0.20；预览11张96DPI示例图不是当前运行截图/性能/目录规模证据。 |
| 动态状态 | Build/Test/Benchmark/Release/应用运行/迁移/恢复/真实网络/设备验收全部NOT_RUN。 | 本次只做文档/工作树校验；未运行不写PASS。 |
| 素材证据 | 1原片，前后哈希一致；31拼图、341帧实例、15裁剪，约308不同源PTS/216035帧≈0.14257%；中断后重叠续扫无已知时间轴缺口。 | 不是逐帧、小字、采样间短提示或当前功能持久化验证。详见正式素材册。 |

## 6. 后续阶段、已定合同与退出闸

| 阶段 | 交付与顺序 | 验收/等待确认 |
| --- | --- | --- |
| Phase0 | 本六文档、65来源、82任务及证据限制。DOC-001仅在实际落盘和校验成立后完成。 | 提交用户确认，不自动改代码；历史素材版本绑定仍待决定。 |
| Phase1 | 建立/维护根AGENTS.md、TODO.md、CHANGELOG.md和docs/PROJECT_CONTEXT.md、DECISIONS.md、ISSUE_INVENTORY.md；保留审计快照与素材册。 | AGENTS十五类、上下文五类、TODO八字段四状态P0–P3、Keep-a-Changelog实变更、任务前读入口/后同步。详细合同见完整任务；本轮未创建这些未来文件。 |
| Phase2 | docs/UI_INFORMATION_ARCHITECTURE.md完整页面/导航/职责/数据关系/路径/重要状态/快捷操作；完整页面/组件/颜色/字体/间距/动画/状态规范及关键页设计；另保留安全技术/回滚方案。 | 全软件重设计、跟随系统/浅色/深色三主题已定，不重复确认是否需要；用户确认具体设计方向后才大规模实现。 |
| Phase3 | P0数据安全先闭；STATE/CATALOG/MEDIA/UPDATE分组保留；PLAN-P3-UI分批统一所有页面/主小窗/对话框/组件。STRUCT最后且仅有证据获准时做。 | 每批业务回归、针对测试、版本绑定证据、文档同步、回退方案；不把全UI实现缩成换色/资源化，不删功能/换栈/擅加依赖。 |
| Phase4 | 平台契约先于平台修复；核心纯函数→隔离DB/OpenXml/HTTP模拟→真实WPF/IME→设备/真实解码/长录→业务E2E/性能兼容。 | 全页面11交互态与Windows10/11、窗口状态、DPI/多屏/字体、焦点/键盘/读屏/真实微软拼音矩阵；设计图不代替运行证据。 |
| Phase5 | 干净隔离构建/打包/候选证据→安装回滚/用户现场→正式promotion。 | 构建测试与生产发布分项许可；不可变资产/签名策略/回读hash/并发降级保护齐备才签署；本次不提交发布。 |

UI定位为简洁直接的Windows桌面，不做网页营销化；单品牌强调色，成功/警告/错误色只表达状态。禁止大渐变、玻璃滥用、发光、巨大圆角阴影、装饰卡片、巨统计、Hero、emoji、无意义复杂动画及过多弹窗。十一状态为默认、悬停、按下、焦点、选中、禁用、加载、成功、错误、空、离线；逐页面/组件说明适用与不适用理由。动画仅表达反馈，不阻塞业务、不让每按钮缩放；初始建议悬停80–120ms、按钮60–120ms、菜单100–180ms、弹窗150–220ms、页面150–250ms，调整须说明设计依据。

## 7. 限制、待确认与交接

| 项目 | 保留的不确定性/决定 |
| --- | --- |
| 运行结论 | 静态未复现；Medium竞态、PCM、COM/PrintWindow、性能、URI影响先复核；无生产恢复/当前构建通过结论。 |
| 产品保留 | 旧表/字段/身份、结束后元数据、字段清空/确认、记录撤销/补同步/画像学习/历史导入/365dt/远程地点源需明确合同；不以暂缓为已完成或删除授权。 |
| UI确认 | 三主题与全面重设计已确定；Phase2只确认具体信息架构/视觉方案和关键页，不退回“是否需要三主题”。 |
| 数据/资源 | Native恢复合同、NORMAL RPO、备份ACL/可选加密、资源来源/license/生成链和独立地理金标准尚待批准验证。 |
| 外部状态 | 实时远端/仓库保护/Release、产物签名、最新CVE、官网完整同步、真实安装回滚未知，不能沿用旧“无漏洞/全通过”。 |
| 素材 | 2026-10-06录制未绑定当前程序集/commit；仅3项确认素材观察/共享风险与1项版本待验证，不归因当前C#。 |
| 历史与保全 | 原板/五附件及本地原证据只读保留；225哈希、30元数据、config不变的边界不扩大；完整6168清单在E，不清理归档。 |
| 最终交接 | 新修订合同优先于旧建议；本包提交Lead等待用户确认，不自动实施，不启动任何后续阶段。 |
