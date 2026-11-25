# Phase0 问题来源与主题台账

日期：2026-11-14；当前唯一产品C#/.NET10/WPF。[报告](PHASE0_AUDIT_REPORT.md) · [任务](PHASE0_TODO.md) · [功能](FUNCTION_INVENTORY.md) · [覆盖](SOURCE_COVERAGE.md) · [素材](../triage/NVIDIA-Netease-issues.md)。

## 口径

| 规则 | 说明 |
| --- | --- |
| 65来源 | NAT-001～033共33，ENG-001～018共18，LB-01～10共10，MEDIA-001/002/003/005共4；不是65独立bug或65已确认产品缺陷。 |
| 分类/置信 | 确认指源码条件/缺口或素材观察，非现场事故；疑似是条件性影响；待验证/设计建议不冒充已确认。High/Medium为证据置信，不是安全级别。 |
| 严重性 | NAT栏为业务高/中，另标原安全High/Medium/Low；ENG保留原风险；LB原P1/P2是来源优先级，安全另列，不捏造业务严重性；MEDIA低/P3或中/P2/P1。 |
| 复现/状态 | 全部源码/工程/兼容项静态、未动态复现、未修复；表内“静态未复现”不表示尝试复现失败。素材记录按机械/读图证据，当前产品关联未建立。 |
| 去重 | R是风险/验收主题包，不是新缺陷。ENG-013同时映射快照与作业，同一来源只计一次；同包不代表已证明同根因，一次修复可关联多个任务别名。 |
| 路径 | A=native/src/HamCheckin.Native.App；C=native/src/HamCheckin.Native.Core；B=native/src/HamCheckin.Native.Benchmarks；T=native/tests/HamCheckin.Native.Tests；U=native/tests/HamCheckin.Native.UiTests。其余为repo相对路径；同一单元格中后续裸文件名沿用最近已写出的目录前缀。 |
| 证据根 | E/M分别为C:\Users\wrdzgzs\AppData\Local\Temp\opencode\ham-phase0-20261114-000334下engineering/media；只放原始本地证据，不代替本文。 |

## 1. Native逐来源（33条）

| 来源 | 主题 | 分类/置信 | 严重性/安全 | 文件:行 | 复现状态 | 原因事实与影响边界 | 建议/验收及任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NAT-001 | R01 | 确认/High | 高/High | C/Storage/NativeStore.cs:427–455；C/Export/ExcelExportService.cs:347–351 | 静态未复现 | 全量复用最近查询被Clamp5000，校验只比截断rows.Count；可能静默漏导。 | 全量查询独立DB对账，5001/10001首末一致；NAT-T002。 |
| NAT-002 | R02 | 确认/High | 高/High | A/ViewModels/MainViewModel.cs:488–499；C/Export/ExcelExportService.cs:34–54；A/Views/SessionEditorWindow.xaml.cs:42–58 | 静态未复现 | 固定同名overwrite且名称无路径限制；覆盖路径确证，越界影响待合成验证。 | 安全basename/目标/覆盖同意，拒绝失败原hash不变；NAT-T003。 |
| NAT-003 | R03 | 确认/High | 高/High | C/Storage/AppPaths.cs:32；NativeStore.cs:42–138,575–582；A/ViewModels/MainViewModel.cs:294–304 | 静态未复现 | Native日备份/校验/保留/恢复未接，旧文档能力混用；不能认定可恢复。 | 一致在线快照、quick_check/checksum和隔离恢复；NAT-T004。 |
| NAT-004 | R04 | 高度疑似/Medium | 高/High | C/Storage/LegacyPythonMigration.cs:61–63,203–218,298–329；T/LegacyPythonMigrationTests.cs:24–47 | 静态未复现 | VACUUM失败顺序Copy DB/WAL/SHM无校验，随后读源原库；活动写入时备份/导入或不一致。 | 同一一致快照导入，WAL/中断/恢复/源hash验收；NAT-T005。 |
| NAT-005 | R03 | 确认/High | 高/High | C/Storage/NativeStore.cs:14,127–138,729–745 | 静态未复现 | 启动无条件写schema3，仅补四列，无未来拒绝/完整迁移回滚。 | 有向迁移/前备份，v4拒写不降标，中断可恢复；NAT-T006。 |
| NAT-006 | R05 | 确认/High | 高/High | C/Storage/NativeStore.cs:349–419,493–538；A/ViewModels/MainViewModel.cs:84–87,451–467 | 静态未复现 | Add/Edit事务不查真实所属场次active；UI有防线，直接调用/旧状态可能绕过。 | 同事务归属/状态/呼号/版本校验，ended/错场拒写；NAT-T007。 |
| NAT-007 | R06 | 确认/High | 高/Medium | A/Views/FieldEditWindow.xaml.cs:101–137；C/Storage/NativeStore.cs:700–720 | 静态未复现 | 每次替换文本却累加所有点击索引，最终B可能连A也消费；RawInput仍在。 | 最终采用集合，A后B/手改/撤回/重复索引/取消；NAT-T008。 |
| NAT-008 | R07 | 确认/High | 高/Medium | C/Catalogs/CatalogService.cs:13–15；CatalogLoader.cs:251–264,351–359,395–405 | 静态未复现 | Current作基线、MIIT同key跳过，增量与重建混用，改删禁用可残留。 | 固定base+独立外部层/世代发布，二次重载准确；NAT-T009。 |
| NAT-009 | R08 | 确认/High | 高/Medium | C/Catalogs/CatalogLoader.cs:414–434,465–501；CatalogSnapshot.cs:910–917 | 静态未复现 | 高优先先读却后写覆盖，人工QTH目标先经旧映射；冲突结果依数据。 | 认可归一化first-wins/择优，人工目标不被抢；NAT-T010。 |
| NAT-010 | R09 | 高度疑似/Medium | 高/Medium | A/ViewModels/MainViewModel.cs:433–435,830–875；C/Storage/NativeStore.cs:283–307,361–423 | 静态未复现 | 提交捕获旧active，完成只比ID回写旧对象；结束/元信息交错或覆盖新状态。 | 版本化/串行场次操作，延迟提交+结束重开矩阵；NAT-T011。 |
| NAT-011 | R02 | 高度疑似/Medium | 高/High | A/ViewModels/MainViewModel.cs:480–500,360–383；C/Export/ExcelExportService.cs:23–25,173–190 | 静态未复现 | await前查旧session行、后读可变session；可能旧数据配新标题。 | 固定ExportRequest/快照/路径，A导出切B不混；NAT-T003。 |
| NAT-012 | R10 | 高度疑似/Medium | 高/Medium | A/ViewModels/MainViewModel.cs:583–601,628–645,672–678；C/Catalogs/MiitCatalogSyncService.cs:133–150 | 静态未复现 | Cancel即busy=false，按钮各自防重、服务无总门；旧未退新可碰partial。 | Running→Cancelling→Settled、jobId/同路径互斥；NAT-T012。 |
| NAT-013 | R10 | 确认/High | 中/Low | C/Catalogs/MiitCatalogSyncService.cs:163–167,240–241,527–536 | 静态未复现 | 正常步长pageSize/5，续传savedPage+1，游标不一致；总数影响待多页。 | 完整下一offset/mode，1000大页从201非2，重页/变化fixture；NAT-T012。 |
| NAT-014 | R10 | 待验证/Medium | 中/Low | C/Catalogs/MiitCatalogSyncService.cs:418–450,503–510,557–565；CatalogSnapshot.cs:263–319 | 静态未复现 | 包含先排除，del/display只存不筛；fts普通追加表未查询；是否错须合同。 | 先筛选/状态/副索引用途，不先删数据；NAT-T013。 |
| NAT-015 | R15 | 确认/High | 中/Low | A/ViewModels/MainViewModel.cs:569–571；A/Views/MainView.xaml.cs:248–279,712–728,999–1017；FieldEditWindow.xaml.cs:148–165 | 静态未复现 | undo只有配置，edit/copy硬编码，Win modifier未记；配置与执行分裂。 | 统一动作/作用域/提示，逐动作新键冲突验收；NAT-T018。 |
| NAT-016 | R15 | 确认/High | 中/Low | A/ViewModels/MainViewModel.cs:54,259–263,522–581；C/Storage/AppPaths.cs:43 | 静态未复现 | ResetShortcuts/设置内存，ConfigPath仅定义；推得重启重置，非重启实测。 | 独立版本配置/原子写/坏文件回退，不盖旧config；NAT-T018。 |
| NAT-017 | R16 | 确认/High | 中/Low | A/Views/MainView.xaml:168–183,240–251；MainView.xaml.cs:826–842；A/ViewModels/MainViewModel.cs:160–170,209–215,665–697 | 静态未复现 | 状态/busy无XAML绑定，async void地点刷新无捕获；异常退出影响待验证。 | 可见进度错误/禁用/取消中，坏库保旧树不退出；NAT-T019。 |
| NAT-018 | R06 | 确认/High | 中/Low | A/Views/FieldEditWindow.xaml:65–74；FieldEditWindow.xaml.cs:124–138；C/Parsing/FieldParser.cs:29–32,49–54,123–126 | 静态未复现 | 复制选中实际第0项，忽略RequiresConfirmation，空/异常呼号时间可保存。 | 真选择/明确文案、身份必填与可清空区分、显式确认；NAT-T007、NAT-T008。 |
| NAT-019 | R06 | 确认/High | 高/Medium | C/Parsing/FieldParser.cs:92–99；T/CatalogLoaderTests.cs:31–48；native/docs/USER-GUIDE.md:37 | 静态未复现 | 唯一模糊候选自动CanonicalValue，现测试仅两候选，违明确选择文案。 | 精确/建议分离，一模糊也需选择，零一多保原文；NAT-T008。 |
| NAT-020 | R09 | 确认/High | 中/Low | A/ViewModels/MainViewModel.cs:167,379；A/Views/MainView.xaml.cs:105–123,289–325；MainView.xaml:83,155,168,188,240 | 静态未复现 | VM CurrentPage与视图Visibility双真源，未订阅，切场路径可失配。 | 单导航真源/明确留页规则，VM/导航/Visible一致；NAT-T011。 |
| NAT-021 | R11 | 高度疑似/Medium | 高/Medium | A/App.xaml.cs:118–143；A/Views/MainView.xaml.cs:664–671；A/ViewModels/MainViewModel.cs:1030–1041；C/Storage/NativeStore.cs:761–765 | 静态未复现 | 初始化仅提示、同步Dispose，资料取消不await、提交无协调；或释放竞争/草稿/退出问题。 | 跟踪作业、止新提交、异步等结果、恢复/草稿提示；NAT-T016。 |
| NAT-022 | R12 | 高度疑似/Medium | 高/Medium | A/Media/MicrophoneCapture.cs:295–315,366–378；U/QuickInputUiTests.cs:1059–1074 | 静态未复现 | Int16 Math.Abs及回调异常边界，-32768溢出影响需.NET10复核，不先断言。 | 先合成PCM/重载语义，再转int/异常隔离，全范围不崩；NAT-T014。 |
| NAT-023 | R13 | 高度疑似/Medium | 高/Medium | A/Media/ScreenRecordingService.cs:54–63,316–319,367–408；Mp4FileWriter.cs:101–107,129–137 | 静态未复现 | delay叠采编成本，视频帧计时与音频样本分离、Elapsed含暂停；长录漂移推演。 | 单调公共时钟/deadline/暂停一致，负载resize长录同步量化；NAT-T015。 |
| NAT-024 | R11 | 高度疑似/Medium | 高/Medium | A/Views/MainView.xaml.cs:664–671；A/Media/ScreenRecordingService.cs:246–250,352–408；ScreenCapture.cs:58；U/QuickInputUiTests.cs:1318–1336 | 静态未复现 | UI同步等worker，worker PrintWindow可能需UI消息；等待循环是平台条件推演。 | 平台复核后异步Closing，阻塞抓帧/关闭/更新/Stop无死锁；NAT-T016。 |
| NAT-025 | R12 | 确认/High | 中/Medium | A/Media/ScreenRecordingService.cs:69–79,269–296,417–426,550–562；A/Views/MainView.xaml.cs:637–648 | 静态未复现 | Failed后mic到Stop才放，partial清理错未报路径；非隐私实测。 | 主动释放或显式占用/停止，残留真实路径，不假清理；NAT-T014。 |
| NAT-026 | R14 | 确认/High | 高/High | C/Updates/NativeUpdateService.cs:197–204,285–305；A/Views/AboutWindow.xaml.cs:120–128,217–274 | 静态未复现 | SHA/URL已有；安装仅copy/move失败无回报/旧EXE回滚/独立签名；未证攻击。 | 保下载协议、签名取舍、目标校验/握手/备份重启回滚；NAT-T017。 |
| NAT-027 | R14 | 待验证/Medium | 中/Medium | C/Updates/NativeUpdateService.cs:235–253,270–282,295–305；A/Views/AboutWindow.xaml.cs:150–156 | 静态未复现 | HtmlUrl交Shell、元数据无限额、仅初始URL；攻击影响依受信源/HTTP边界。 | https仓库URI/体积/最终重定向信任fixture；NAT-T017。 |
| NAT-028 | R21 | 待验证/Medium | 中/Low | A/ViewModels/MainViewModel.cs:724–793,854–857；C/Catalogs/CatalogSnapshot.cs:45–73,154–176,338–423；native/docs/performance-latest.json:7,15–17,69 | 静态未复现 | 同步解析/重复扫描；旧p95=15.4207ms、写均7.31ms不是当前基线，async不保证UI不阻塞。 | 同源基准/Dispatcher测量后索引，不以延迟丢输入刷分；NAT-T021。 |
| NAT-029 | R22 | 设计建议/Medium | 中/Low | A/App.xaml:5–27,42–147；A/Infrastructure/WindowsBackdrop.cs:23–28；A/app.manifest:18；U/QuickInputUiTests.cs:966–1020 | 静态未复现 | 当前固定浅色/小字/无主题切换证据，声明不证可访问；实际视觉未验。 | 按已定整软件UI/系统浅深合同设计实施，所有窗页11态/Win10/11/DPI/真实IME/读屏验；NAT-T022。 |
| NAT-030 | R20 | 确认/High | 高/Low | README.md:8–10,23–35,93–140,166–228；native/README.md:1,3,18；native/docs/ARCHITECTURE.md:83–89,104–117；VERIFICATION.md:3–30,131–136 | 静态未复现 | 旧入口/命令/备份/同步/不迁移说明与当前自动导入/1.0.20冲突。 | 当前C#入口、历史版本标签，获准后改旧文档、不删功能；NAT-T025。 |
| NAT-031 | R23 | 设计建议/High | 中/Low | A/ViewModels/MainViewModel.cs:569,879；C/Storage/LegacyProfileReader.cs:7–49；C/Catalogs/QthPackageService.cs:100–135；A/Views/MainView.xaml.cs:826–842 | 静态未复现 | 撤销/补同步/画像学习/远程包无完整链；命名/installed计数不是功能。 | 保留范围清单/真入口验收，不推定废弃或加QSO；NAT-T026。 |
| NAT-032 | R18 | 待验证/Medium | 中/Low | native/docs/VERIFICATION.md:3–30；T/NativeEndToEndTests.cs:67–76；MiitCatalogSyncTests.cs:33–74；U/QuickInputUiTests.cs:1037–1042,1059–1065,1245–1252；A/Media/MediaFoundationInterop.cs:75–230 | 静态未复现 | 旧PASS未绑dirty1.0.20；缺边界回归、设备Skip/FourCC局限，ABI未核不能判错。 | 当前版本证据/多页恢复/平台复核与分层测试；NAT-T023。 |
| NAT-033 | R24 | 确认/High | 中/Low | A/ViewModels/MainViewModel.cs:302–313,371–377,870–873；A/Views/MainView.xaml:155–163 | 静态未复现 | 本场与最近共缓存，重启切场仅300、无分页总数；运行可超300，不是删除。 | 分页/总数/定位编辑，301+重启仍查最早；NAT-T020。 |

## 2. 工程逐来源（18条）

| 来源 | 主题 | 分类/置信 | 原风险 | 文件:行 | 复现状态 | 原因事实与影响边界 | 建议/验收及同名任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENG-001 | R17 | 确认配置/High | High | .github/workflows/ci.yml:14–36；release.yml:54–62 | 静态未复现 | 普通CI仅Python，Native只Tag；绿灯不证C#。 | 普通Gate故意编译/断言错各失败，Native数量/Skip/TRX。 |
| ENG-002 | R17 | 确认环境/High | High | E/dotnet-info.txt:2,12,23–31；dotnet-private-info.txt:2,12,24–30；dotnet-assets-targets.json | 只读测量，构建NOT_RUN | PATH SDK8/私有SDK10，App/Core/Tests旧assets，非已实测编译失败。 | 明确SDK/TFM/RID、隔离匹配资产，不清旧obj。 |
| ENG-003 | R20 | 确认/High | Medium | .github/workflows/release.yml:35–39,51–52,83；release.py:22,93–100；README.md:138,168–170,234–239 | 静态未复现 | 工具有Python/默认旧version，运行文档误导；不是产品Python依赖。 | 无Python机运行C#，工具显式解释器/Native版本，不另造工具。 |
| ENG-004 | R20 | 确认/High | Medium | A/HamCheckin.Native.App.csproj:17–19；C/Updates/NativeUpdateService.cs:11；A/app.manifest:3；U/QuickInputUiTests.cs:721；updates/latest.json:2 | 静态未复现 | 多版本/旧证据混用；候选稳定不是同语义。 | 唯一权威/派生拦截，commit/dirty/EXE hash，不提前切稳定。 |
| ENG-005 | R19 | 确认/High | Medium | .github/workflows/release.yml:20,25,31,33,38–39；native/Directory.Build.props:3,7 | 静态未复现 | 可变Actions/SDK范围/依赖未锁；未查CVE，非确证漏洞。 | 批准来源/同依赖图/漂移失败，扫描标时间源版本。 |
| ENG-006 | R19 | 确认配置/High | High | .github/workflows/release.yml:8–9,98,110–143 | 静态未复现 | --clobber、无concurrency/单调/审核闸，写权限跨指针；非远端已覆盖证据。 | 同Tag hash不静改、旧/并行不降级、上传回读失败不切。 |
| ENG-007 | R14 | 确认边界/High | Medium | C/Updates/NativeUpdateService.cs:141–204,278–305；A/Views/AboutWindow.xaml.cs:154–156,219–237 | 静态未复现 | SHA/大小/初始URL已有，安装复验/回滚、页面URI/元数据/重定向不足。 | 错hash/仓库/scheme/超量拒，temp篡改不执行、故障保旧EXE；签名现状未知。 |
| ENG-008 | R04 | 疑似影响/Medium | High | C/Storage/LegacyPythonMigration.cs:61–63,303–328；T/LegacyPythonMigrationTests.cs:27–47 | 静态未复现 | 备份后重读原库、Copy fallback无恢复校验；并发可能不同时点。 | 同快照、WAL/损坏/满盘/中断要么可恢复原子导入要么不标完成。 |
| ENG-009 | R03 | 确认缺口/Medium影响 | High | C/Storage/NativeStore.cs:42–138；./README.md:217–222 | 静态未复现 | schema3直接写/缺未来拒绝/前备份，旧日备份不可沿用。 | 旧当前未来/半升级/坏备份/恢复故障隔离对账，不覆盖好库。 |
| ENG-010 | R01 | 确认/High | High | C/Storage/NativeStore.cs:443,453–455；A/ViewModels/MainViewModel.cs:498–499；C/Export/ExcelExportService.cs:347–351 | 静态未复现 | 500000请求被Clamp5000，rows.Count自证看不出漏。 | 5001/10001与DB独立count/字段/首末一致。 |
| ENG-011 | R05 | 确认缺口/Medium影响 | High | A/ViewModels/MainViewModel.cs:249,451–467；C/Storage/NativeStore.cs:349–424,493–567；U/QuickInputUiTests.cs:643–676 | 静态未复现 | 只UI保护ended，事务不读所属session状态；UI路径影响待验。 | 直接API/旧SessionInfo/并发/双Store拒写ended，审计保留。 |
| ENG-012 | R02 | 确认覆盖/Medium竞态 | High | A/ViewModels/MainViewModel.cs:491–499；C/Export/ExcelExportService.cs:53 | 静态未复现 | 固定Downloads/可覆盖且await两次读session；人工文件损失为条件影响。 | 会话快照、不确认人工列/公式hash不变，取消失败保原件。 |
| ENG-013 | R07/R10 | 疑似竞态/Medium | Medium | A/ViewModels/MainViewModel.cs:583–601,672–677；C/Catalogs/MiitCatalogSyncService.cs:133–140,337–343；CatalogLoader.cs:251–263,355–358 | 静态未复现 | 取消即解busy、同partial无门；旧快照跳过同型号、预热无限读；复合来源只计1。 | settled后解锁/同路径串行、重载更新、响应限额，正式库hash保护/官网另授权。 |
| ENG-014 | R18 | 确认证据缺口/High | Medium | T/MiitCatalogSyncTests.cs:60–73；U/QuickInputUiTests.cs:1033,1456,1465,1478；.github/workflows/release.yml:56–62；release-notes/HX-HAM-1.0.19-r35.md:27 | 静态未复现 | 403无旧库断言、零帧不证方向、过滤/环境/超时不足；隔离变量仍在。 | 故障真失败、设备分层/Skip原因、非对称方向/覆盖安全/默认mic关/拒覆盖/超时。 |
| ENG-015 | R15 | 确认证据缺口/High | Medium | A/ViewModels/MainViewModel.cs:96,522–580；A/Views/MainView.xaml.cs:248–279；C/Storage/AppPaths.cs:43；NativeStore.cs:124 | 静态未复现 | 设置仅内存、undo仅配置/is_undo无执行；文字撤销非记录撤销。 | 先保留范围，持久化/撤销事务审计并发合同或明确不支持，不误删入口。 |
| ENG-016 | R21 | 设计建议/Medium | Low | A/Views/MainView.xaml.cs:125–225；QuickWindow.xaml.cs:62–161；FieldEditWindow.xaml.cs:172–176；A/ViewModels/MainViewModel.cs:936–991；C/Storage/NativeStore.cs:700–720 | 静态未复现 | 大类与局部重复，预览/生产消费两实现可能漂移；非整文件重复证据。 | 契约锁后真实重复收敛，焦点/修订/IME/性能不退、无无关格式化。 |
| ENG-017 | R21 | 确认工具副作用/High | Medium | artifacts/published-blackbox-1.0.19-r29-harness/Program.cs:9–23,55,320–419；artifacts/update-live-probe/Program.cs:4–15；B/Program.cs:34–44,71–87,125–133 | 静态未运行 | 硬编码旧EXE/删固定输出/抢桌面/联网，基准读用户资料、无预算。 | 复用纳管最新版、参数化/显式许可，默认不碰生产/历史，输出版本hash/预算。 |
| ENG-018 | R28 | 确认清单/High | Low | .gitignore:14–21；E/untracked-complete-6168.txt、untracked-classification-complete-6168.csv | 只读枚举 | SDK/源/712图/3视频/260TRX混放，原metadata5602不全；不可整体忽略删除。 | 保留manifest/责任人/hash索引；删除移动ignore另许可。 |

## 3. 历史兼容逐来源（10条）

| 来源 | 主题 | 分类/置信 | 原优先级/安全 | 文件:行 | 复现状态 | 原因事实与影响边界 | 建议/验收及任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LB-01 | R20 | 确认/High | P1/Low | README.md:166–170,232–239；native/README.md:3–4；native/docs/ARCHITECTURE.md:83–117 | 静态未复现 | 旧Python入口/预览不迁移说明与当前C#默认导入矛盾。 | 当前入口/历史标签，不删旧资料；LB-T01。 |
| LB-02 | R25 | 确认边界/High，影响Medium | P1/Medium | C/Storage/LegacyPythonMigration.cs:80–114,398–408；NativeStore.cs:78–79 | 静态未复现 | date+name归并，不用external key，后者元信息或不独立；是否应归并待业务。 | 不同主控/外部键fixture、独立身份或审计归并；LB-T02、LB-T03。 |
| LB-03 | R26 | 确认/High | P1/Medium | C/Storage/LegacyPythonMigration.cs:48–58,371–380；A/ViewModels/MainViewModel.cs:319–321 | 静态未复现 | Native有签到写永久skip，UI非Imported常只就绪，或不知旧库未导。 | 原因/后续/跨重启可见，不删marker强混；LB-T04。 |
| LB-04 | R04 | 疑似损坏/Medium | P1/High | C/Storage/LegacyPythonMigration.cs:298–328 | 静态未复现 | 降级Copy DB/WAL/SHM事实High；外部写入时不同时点、可恢复性未验。 | 合成活动WAL/复制失败，一致快照/可读校验，失败不称成功；LB-T05。 |
| LB-05 | R27 | 确认覆盖边界/High | P1/Medium | C/Storage/LegacyPythonMigration.cs:203–218,224–277；C/Catalogs/CatalogLoader.cs:319–334 | 静态未复现 | 来源键/审计补全导入同步未搬，别名仍读旧库；不能“全部迁移可删”。 | 逐表字段合同/保留规则/必要证据；LB-T02、LB-T08、LB-T09。 |
| LB-06 | R26 | 确认自动发现边界/High | P2/Low | C/Storage/AppPaths.cs:40–44；A/ViewModels/MainViewModel.cs:295–298；config/settings.py:372–392 | 静态未复现 | 固定旧路径未消费旧data_dir，其他路径可能被当无旧库。 | 明确源路径/版本/计数预检，不扫上传真实资料；LB-T07。 |
| LB-07 | R08 | 疑似优先级/Medium影响 | P1/Medium | C/Catalogs/CatalogLoader.cs:415–434；C/Parsing/TextNormalizer.cs:24–32 | 静态未复现 | user/高priority先读、destination赋值后盖，归一化同key或低优先反盖。 | uv-5r/uv5r冲突，认可规则后复用字典修正；LB-T06。 |
| LB-08 | R23 | 待确认/设计建议/Medium | P2/Low | C/Storage/LegacyProfileReader.cs:5–49；native/src符号检索 | 静态未复现 | 类存在但未找到生产调用，有限否定不证明所有画像机制都不存在。 | 核当前入口/替代机制再决定辅助类定位，不删；LB-T08。 |
| LB-09 | R20 | 确认本地差异/High | P2/Low | A/HamCheckin.Native.App.csproj:17；./README.md:8；updates/latest.json:2 | 静态未复现 | 1.0.20/1.0.19/本分支1.0.5不同；远端未知。 | 批准版本/产物说明清单核对，不提前刷新稳定；LB-T11。 |
| LB-10 | R17/R20 | 确认工具事实/High | P2/Low | .github/workflows/release.yml:35–52,64–83；ci.yml:14–36 | 静态未复现 | Tag有Python历史测试/工具，普通CI仅Python；不是C#验收。 | 当前C# Gate/工具/同hash附件明确，不盲删release.py；LB-T10。 |

## 4. 素材逐来源（4条）

源S=C:\Users\wrdzgzs\Videos\NVIDIA\Netease\Netease 2026.10.06 - 21.00.21.01.mp4。每项完整字段见正式素材册，此处仍保留主要事实/建议，不借本地旧日志充当当前缺陷。

| 来源 | 主题 | 分类/置信 | 严重性 | 文件:位置/证据 | 复现状态 | 原因事实与影响边界 | 建议/验收及任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MEDIA-001 | R29 | 确认素材观察/High | 低/P3 | S容器UDTA头；M/probe-warning-repro.stderr.txt | ffprobe/ffmpeg警告复核，产品未关联 | 本读取器回退确证；私有布局/版本兼容仅可能原因，探测扫描仍成功。 | 保原hash，必要时副本跨读取器/atom根因和必需元数据；MEDIA-TODO-07。 |
| MEDIA-002 | R30 | 确认时序/High，感知待核 | 低/P3 | S 00:01:35.415944–00:01:35.591533；M/frames-94-97.json、packets-analysis.json | 包/解码帧/密采相符，当前未复现 | 帧175.589ms；采集根因未知，不叫丢10帧/挂起/当前卡顿。 | 独立感知复核或录制观察，不转码掩盖，当前bug须重现；MEDIA-TODO-07。 |
| MEDIA-003 | R31 | 确认共享风险/High | 中/P2 | S首帧至约01:36及尾菜单；M/content-crops、tail-detail | 已读图存在，不穷尽 | 聊天/桌面/识别信息入镜；录制设置未知，未发现本轮外泄。 | 分享另授权另存脱敏/另hash/复审全拟分享段，原件不变；MEDIA-TODO-05。 |
| MEDIA-005 | R33 | 待验证版本绑定/High缺口 | 中/P1 | S全片/2026-10-06元数据；M/inventory-after.json、M/probe.json、M/content-crops/opening-title.png | 标题/日期已读，构建未绑定 | 目录无程序集/commit映射；具体构建未知，不能用正常演示证当前通过。 | hash→录制→版本→commit，或历史参考决定+当前独立复现；MEDIA-TODO-03。 |

## 5. 去重主题与全来源映射

保留既有R编号便于追溯，编号不连续不表示遗漏。下表是65来源的完整主题集合；ENG-013、LB-10跨主题引用不增计，不能把32主题称32个独立bug。

| 主题 | 范围 | 全部来源 |
| --- | --- | --- |
| R01 | 全量截断 | NAT-001、ENG-010 |
| R02 | 导出覆盖/路径/会话快照 | NAT-002、NAT-011、ENG-012 |
| R03 | Native备份/schema恢复 | NAT-003、NAT-005、ENG-009 |
| R04 | 旧库一致快照 | NAT-004、ENG-008、LB-04 |
| R05 | ended事务约束 | NAT-006、ENG-011 |
| R06 | 最终片段/复制/确认/未知型号 | NAT-007、NAT-018、NAT-019 |
| R07 | 快照重建 | NAT-008、ENG-013 |
| R08 | 别名归一化优先级 | NAT-009、LB-07 |
| R09 | 场次完成/导航状态 | NAT-010、NAT-020 |
| R10 | 取消/续传/筛选/响应 | NAT-012、NAT-013、NAT-014、ENG-013 |
| R11 | 初始化/关闭/PrintWindow等待 | NAT-021、NAT-024 |
| R12 | PCM/失败释放/清理反馈 | NAT-022、NAT-025 |
| R13 | 媒体公共时钟/暂停 | NAT-023 |
| R14 | 更新安装/真实性/URI限额 | NAT-026、NAT-027、ENG-007 |
| R15 | 快捷动作/配置/撤销范围 | NAT-015、NAT-016、ENG-015 |
| R16 | 可见状态/异常边界 | NAT-017 |
| R17 | 当前C# Gate/SDK | ENG-001、ENG-002、LB-10 |
| R18 | 当前基线/分层测试证据 | NAT-032、ENG-014 |
| R19 | 供应与不可变发布 | ENG-005、ENG-006 |
| R20 | 当前入口/版本/历史证据 | NAT-030、ENG-003、ENG-004、LB-01、LB-09、LB-10 |
| R21 | 性能/结构/工具可控性 | NAT-028、ENG-016、ENG-017 |
| R22 | 全软件UI/三主题/桌面适配 | NAT-029 |
| R23 | 辅助代码与保留范围 | NAT-031、LB-08 |
| R24 | 300条完整浏览边界 | NAT-033 |
| R25 | 旧场次独立身份 | LB-02 |
| R26 | skip提示/自定义旧路径 | LB-03、LB-06 |
| R27 | 兼容数据/旧资料依赖 | LB-05 |
| R28 | 清单/保留归档 | ENG-018 |
| R29 | 素材UDTA读取观察 | MEDIA-001 |
| R30 | 素材长帧观察 | MEDIA-002 |
| R31 | 素材共享治理 | MEDIA-003 |
| R33 | 历史构建绑定 | MEDIA-005 |

Medium竞态/平台/性能/URI结论影响设计前必须复核。未来修复须逐来源填证据，保持源ID/别名与任务对应；本轮没有任何源码问题修复或动态PASS。
