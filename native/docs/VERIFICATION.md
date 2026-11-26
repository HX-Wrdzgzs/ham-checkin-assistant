# Windows 原生版开发验收记录

## 当前工作树：2026-11-26 手机收件 S2/S3（未发布）

- 实现：Kestrel/LanServer 7 端点、PIN/令牌、内存待确认队列、审批租约与幂等写、内嵌手机页；WPF「手机收件」页（启动/停止、地址/PIN/URL、已连接手机、待确认列表、确认/拒绝、快速页横幅）。默认不启动；批准前不写 SQLite。
- 构建/测试：.NET SDK 10.0.401；Release `--no-restore` 构建 0 errors；LAN 66/66、Native 308 + UI 70 = **378/378 passed / 0 failed / 0 skipped**；日志 `s3-build.log`、`s3-targeted.log`、`s3-full2.log`、`s2-lan-tests.log`。
- 隔离界面：`NAT-lan-page-20261126-195854.png`（手机收件页，未启动，端口 8731–8740 无监听）。
- 未验证：真实手机/局域网、防火墙提示、PC 休眠/切网、自包含单文件体积/ASP.NET Core 运行时前置；这些仍属 S4，`UI NOT VERIFIED`。
- 边界：未连接真实手机、未访问生产数据/用户配置，未修改防火墙或发布。

## 当前工作树：2026-11-22 呼号历史提示 S1 与关于页修正（未发布）

- 验证日期：2026-11-22；Windows 11 build 26300 x64；工作树 dirty，未暂存、未提交。
- 被测产物：Release WPF apphost `native/src/HamCheckin.Native.App/bin/Release/net10.0-windows/HAM点名助手.exe`（本次构建）；实现为 `Core/Memory/CallsignMemoryService` 从 `checkins` 只读派生 QTH/设备/天线/功率，WPF 主页面与 QuickWindow 显示半透明 chip；不新建表、不改写路径。
- 构建：SDK `10.0.401`；`dotnet build native/HamCheckin.Native.sln -c Release --no-restore` exit 0，0 errors；日志 `%LOCALAPPDATA%\Temp\opencode\s1-rerun-build.log`（增量 0 warnings）及 `s1b-build.log`（全量既有分析器 warnings）。
- 测试：`HAM_CHECKIN_NATIVE_UI_TEST=1`；`dotnet test native/HamCheckin.Native.sln -c Release --no-build --filter "Category!=Hardware"` exit 0；Core `253/253`、UI `64/64`，合计 `317 passed / 0 failed / 0 skipped`；日志 `s1-rerun-test.log`、`s1b-test2.log`。新增覆盖：CallsignMemoryService top3/正常化/50 条窗口/只读、提示去抖不改输入、逐字段应用、撤销、revision 失效、QTH 候选+记忆撤销后同修订重解析、QuickWindow 紧凑高度、About 副标题。
- 隔离界面截图：`NAT-s1-hints-20261122-142159.png`（呼号 `BG4TKI`，提示行显示“记忆 / 上次 14:18 / QTH … / 天线 4.2米玻璃钢 / 功率 25W”，半透明），位于 `%LOCALAPPDATA%\Temp\opencode\`；About 无副标题由 UI 视觉树测试覆盖，未单独截图。
- 关于页：删除整行副标题，版本、更新渠道、数据位置等内容保留；未修改窗口标题、侧栏文字或 App 错误文案。
- 已知边界：用户已确认 `1907` 是设备型号（当前解析为 YAESU FT-1907R），不是时间；因此不新增时间字段。提示字段不包含时间/信号；`InputText` 与撤销栈不被改写。
- `UI NOT VERIFIED:` 真实 DPI、多屏、实际 IME、读屏及 QuickWindow 真实视觉间距未做人工验收；首次全量运行曾出现既有动画测试取样时序抖动，单独及第二次全量通过，已记录为环境抖动，未见产品失败。硬件/真实网络/生产库/更新安装仍 `NOT_RUN`。

## 当前工作树：2026-11-22 过渡动画与全功能离线测试（未发布）

- 测试日期与机器：2026-11-22；Windows 11 build 26300，x64；工作树 dirty，未暂存、未提交。
- 被测产物：Release WPF apphost `native/src/HamCheckin.Native.App/bin/Release/net10.0-windows/HAM点名助手.exe`，SHA-256 `045EA3211D59C24788623FECDC00B20262E4C6A029CD3B236D95246300EAE0D7`；应用程序集 `HAM点名助手.dll`，SHA-256 `087CAD1BED672AF736AD077B081FEEA3470CD6A7DADDDAE2FC6A28BDA2AC188C`。
- 隔离启动：`--data-root "%LOCALAPPDATA%\Temp\opencode\NAT-animation-ui-20261122-115643" --disable-network`；未使用生产数据、用户配置、真实设备或网络。主页面与“本场记录”页截图分别见 `NAT-animation-main-20261122-115818.png`（SHA-256 `A8B0C22C435F6E76C3D0A97FD35C673E8C0028BBBBEB0F83C1E0EA75745A56AE`）和 `NAT-animation-records-20261122-115941.png`（SHA-256 `C42F1CDCC81A9C094CCB0CF32DC8BB6E3338F358BAD1117A84705BC0982144B6`），均位于 `%LOCALAPPDATA%\Temp\opencode\`。
- 实现：`WindowMotion` 统一页面 180 ms / 窗口 160 ms 淡入+位移；`MainView.xaml.cs` 页面切换与六个窗口挂接点（About、FieldEdit、Quick、SessionEditor 新建/编辑、SessionPicker）使用该统一实现；尊重 `SystemParameters.ClientAreaAnimation` 与 `AnimationsEnabled`；快速切页取消旧动画，结束回落到 opacity 1 / 零偏移。`ShortcutCaptureWindow` 与 `PreviewRenderer` 不在本批范围。
- 构建：SDK `10.0.401`；`dotnet build native/HamCheckin.Native.sln -c Release --no-restore` exit 0，0 errors、0 warnings（增量构建）；日志 `%LOCALAPPDATA%\Temp\opencode\animation-build-final.log`。
- 测试：`HAM_CHECKIN_NATIVE_UI_TEST=1`；`dotnet test native/HamCheckin.Native.sln -c Release --no-build --filter "Category!=Hardware"` exit 0；Core `250/250`、UI `55/55`，合计 `305 passed / 0 failed / 0 skipped`；日志 `animation-full-test.log`。新增动效用例 `PageEntranceAnimatesThenSettlesAtRestWhenMotionIsEnabled`、`RapidPageSwitchesCancelAndSettleAtRestWhenMotionIsEnabled` 与既有禁用用例连续 3 轮 `3/3` 通过（`animation-targeted.log`、`animation-repeat-1..3.log`）。
- 覆盖：解析器、字段解析、存储/场次、草稿、端到端、Excel 导出、目录/QTH/MIIT、更新服务、旧数据迁移、视频回放、UI/主题/快速输入均有自动化证据；硬件/麦克风 3 例 `NOT_RUN`（需 `HAM_CHECKIN_NATIVE_HARDWARE_TEST=1` 与真实设备）；真实网络、生产库迁移、更新安装/发布 `NOT_RUN`。
- `UI NOT VERIFIED:` 五个二级窗口入口动画仅有静态代码审查，未做逐帧视觉抓取；真实桌面 DPI、多屏、实际 IME、读屏及更广可访问性矩阵仍 `NOT_RUN`。本记录不证明发布产物或远端 CI。

## 当前工作树：2026-11-20 NAT-T022隔离 Windows 11 桌面主题验证（未发布）

- 验证日期与机器：2026-11-20；Windows 11 build 26300，x64。
- 被测产物：Release WPF apphost `native/src/HamCheckin.Native.App/bin/Release/net10.0-windows/HAM点名助手.exe`，SHA-256 `7E816CD80413CCF82FC97906BBBB7DB02EEA45C120D1324B571FCF85F7D96CFB`。使用本机已安装的 .NET 10 runtime 启动，参数为 `--data-root "%LOCALAPPDATA%\Temp\opencode\NAT-T022-desktop-20261120-174206" --disable-network`。
- 隔离边界：data-root 指向上述临时目录；未使用生产数据或用户配置，网络禁用，未使用真实设备。隔离配置记录 `themePreference: FollowSystem`。
- 截图审计证据位于 `%LOCALAPPDATA%\te-river\computeruse\audit\2026-11-20\abb53d0f\shots\`；仅引用文件名，不将截图复制到仓库。

| 截图引用 | 可见观察 |
| --- | --- |
| `a0035.png`、`a0039.png`、`a0043.png` | 应用内 Light、Dark、FollowSystem 选项可见。 |
| `a0049.png` | 合成未保存草稿可见，主题切换前。 |
| `a0064.png` | Windows Apps theme 设为 Dark 后，应用可见变化；草稿仍在。 |
| `a0082.png` | 启用 Windows Contrast theme“水生”后，应用可见切为高对比；草稿仍在。 |
| `a0089.png` | Windows Contrast theme 已设回 None。 |
| `a0097.png` | Windows Apps theme 已恢复 Light。 |
| `a0101.png` | 应用恢复为 Light，草稿仍在。 |

- 合成未保存草稿 `bg4tki njqx k6 y 5` 在主题变更前后均可见（`a0049.png`、`a0064.png`、`a0082.png`、`a0101.png`）；未按 Enter，也未保存。输入框焦点样式可见；未建立选择范围，因此选择保留为 `NOT_TESTED`。
- 恢复与关闭：Windows Contrast theme 设为 None（`a0089.png`），Apps theme 恢复 Light（`a0097.png`），应用以 Light 和草稿显示（`a0101.png`）；通过应用正常关闭按钮退出。主会话独立核验 `AppsUseLightTheme=1`、WPF `SystemParameters.HighContrast=False`、精确 app executable 进程数为 0、关闭后 TCP connections 为 0。
- 本次仅证明实际 Windows 设置变化时用户可见的主题响应；未捕获通知事件日志/trace。精确的 `SystemEvents.UserPreferenceChanged` / `SystemParameters.StaticPropertyChanged` 通知映射仍为 `NOT_VERIFIED`（ledger #116 仍阻塞）。
- 覆盖范围仅为这台 Windows 11 build 26300 x64 机器。Windows 10、其他 DPI、多显示器/混合 DPI、实际 IME、Narrator 及更广可访问性矩阵均为 `NOT_RUN`；选择保留为 `NOT_TESTED`。NAT-T022 保持开放。
- 本次运行未构建、未测试、未发布应用。下方 2026-11-17 源码构建/测试记录是独立证据，不证明本次桌面运行或发布。

## 既有证据：2026-11-17 NAT-T022主题源码验证（未发布）

- .NET SDK 10.0.401；Native Release build `--no-restore` PASS（exit 0，0 errors）；保留的 Release 构建日志含 54 行原始 warning 诊断记录（包含项目重复发出的诊断行），按项目/文件/行/列/代码/消息组合去重后，共 27 条项目范围内的不同诊断，涉及 8 种诊断代码；`Category!=Hardware` solution tests PASS（Core 250、UI 53，合计303 passed/0 failed/0 skipped）；correctness review PASS（0 Critical/0 Major）。
- 未启动WPF应用；`UI NOT VERIFIED: WPF 应用未启动；真实桌面/系统主题通知矩阵未授权且未测试。` AppsUseLightTheme通知映射、DWM/Win10/11/DPI/多屏/IME/Narrator为NOT_VERIFIED/NOT_RUN。此记录仅绑定当前dirty源码树，不是EXE/Release/commit验收。

## 历史：1.0.19-r29 候选验证（2026-10-06）

本节记录当时源码状态与 `1.0.19-r29` 候选包的历史验收；App 项目源码版本字段为 `1.0.20`（见 [App 项目文件](../src/HamCheckin.Native.App/HamCheckin.Native.App.csproj#L17-L19)），但没有当前 `1.0.20` 产物的动态验收证据，也不代表当前 Native 工作树、远端 Actions 或 Release 已验收。下方的 `1.0.18-r27` 及更早内容也保留为历史记录，不能与本候选混用。

| 检查 | 实际结果 |
|---|---:|
| Release 全解决方案编译 | PASS，0 error；保留现有代码分析器 warning，没有编译错误 |
| Native 核心自动化测试 | PASS，194 / 194；包含 500 条 SQLite 端到端写入、重启、字段限定编辑和导出链路；`artifacts/test-results/continuation-r29/core/core-r29.trx` |
| WPF UI 自动化测试 | PASS，33 / 33；`artifacts/test-results/continuation-r29/ui/ui-r29.trx`；包含主窗口/小窗前中尾部编辑、双窗口同步、IME 元数据、录屏默认安全、覆盖窗口安全、MP4 与麦克风、响应式按钮边界和侧边栏页面同步 |
| 发布 EXE 离线启动与键盘黑盒 | PASS；1.0.19-r29 自包含 EXE `WaitForInputIdle=true`、保持运行 8 秒、隔离 SQLite 生效；主窗口和快捷小窗前/中/尾部编辑均保持后缀，并额外各执行 25 轮真实键盘编辑（共 50 次）；读取视频样例及全国跨省缩写；`artifacts/published-blackbox-1.0.19-r29-offline/report.json` |
| 发布 EXE 在线启动与输入可用性 | PASS；候选 EXE 未使用 `--disable-network`，进入设置页后实际读到“已检查更新 · 当前 1.0.19 为最新”，主窗口/小窗输入和识别均通过；`artifacts/published-blackbox-1.0.19-r29-online/report.json` |
| 1.0.19-r29 自包含候选 EXE | PASS；文件版本 `1.0.19.0`；最终候选 EXE 的字节数和 SHA-256 以候选包 `SHA256SUMS.txt` 为准，避免文档哈希与后续正式构建元数据脱节 |
| 全国行政区 ASCII 别名审计 | PASS；现有全国行政区别名扫描通过；另有省码锚定的未知尾缀保留回归 |
| 行政区歧义审计 | PASS；269 个真实碰撞，0 个错误强行解析；`鼓楼区`、`栖霞区`、`东乡`保留候选并要求选择 |
| 重名行政区规范化 | PASS；临夏市、楚雄市、阿克苏市等不再输出重复的“省+市+同名市” |
| 短设备查询回归 | PASS；`k1` 不再吸附无关的 `TK11`，`pd780`、`r6`、`k5`、`k6` 仍有正确候选 |
| 视频样例识别审计 | PASS（保守保留未知尾缀）；`7900`、`jsycxs`、`bh8` 完整识别；`山东qcd` 得到 `山东省` + 待修正 `qcd`，`广东省汕头市m507` 得到完整已知 QTH + 待修正 `m507`，没有擅自猜城市或吞掉尾缀；完整机器结果见黑盒 `report.json` |
| 录屏默认安全回归 | PASS；真实 WPF 客户区抓帧使用 `PW_CLIENTONLY + PW_RENDERFULLCONTENT`，不回退到桌面；默认麦克风为 Off，录屏目标明确为软件窗口，输出为 MP4；`artifacts/test-results/continued-ui-recording-2/ui-recording-2.trx` |
| 发布 EXE 实际录屏黑盒 | PASS；离线和联网发布 EXE 均实际点击开始/停止，隔离目录生成可读 MP4；两次结果均含 `ftyp`、`moov`、`mdat`，实际字节数以对应黑盒 `report.json` 的 `recordingArtifact` 为准（抓帧时序会使大小变化） |
| 录屏覆盖窗口安全回归 | PASS；专用 WPF 黑盒用红色覆盖窗口覆盖绿色目标窗口，采样帧仍全部来自 HAM 目标窗口，且没有红色覆盖内容；不会因采集失败回退到桌面 |
| WPF 效果图渲染 | PASS；1.0.19-r29 自包含发布物实际输出 10 张真实控件效果图，含 800×600 窄窗、关于/版本页和录屏/麦克风页；目录为 `artifacts/published-ui-effects-1.0.19-r29-final-commit` |
| 侧边栏与页面同步 | PASS；设置页/快速点名页切换后选中状态一致；新增 UI 回归测试包含在 33 / 33 中 |
| 候选包校验清单 | PASS；`SHA256SUMS.txt` 与候选 EXE 当前哈希一致 |
| NativeUpdateService 真实更新链路 | PASS（当时稳定通道 v1.0.5）；项目自己的更新服务在 GitHub API 403 时回退到 `main/updates/latest.json`，既有 SHA-256 下载/拒绝测试通过；1.0.19-r29 在线启动实际显示已检查更新；候选版尚未创建远程 Release |

当前候选包中的正式证据文件：`artifacts/candidate-1.0.19-r29/输入与核心测试.trx`、`WPF黑盒测试.trx`、`发布包黑盒测试.json`、`在线启动输入黑盒.json`、`识别准确性审计.json`、`效果图/` 和 `SHA256SUMS.txt`。源测试原始结果另见 `artifacts/test-results/continuation-r29/core/core-r29.trx` 与 `artifacts/test-results/continuation-r29/ui/ui-r29.trx`。

这份 `1.0.19-r29` 历史候选验证仍未宣称完成的项目：真实微软拼音现场操作、用户可见的 Microsoft Excel 修复提示流程、长时间录屏稳定性、1.0.19 远程 GitHub Release 资产下载，以及用户生产库迁移。它们必须在现场或真实发布通道验证，不能由本地隔离测试替代。历史记录中的稳定 v1.0.5 下载链路和 1.0.19-r29 候选启动检查，分别有真实清单回退/下载/SHA-256 与在线启动黑盒证据；这些证据不代表当前稳定通道或当前 1.0.20 Release 已验证，也不能代替 1.0.19 Release 验证。

## 门禁与产物来源（静态配置/代码合同）

以下是仓库当前 workflow/source/test 文本所表述的合同，不是本次运行或远端 Actions/Release 已通过的证据，也不改变上方 1.0.19-r29 历史候选记录的范围。

- 普通 CI 保留 Python 3.11/3.12 legacy job matrix，并配置独立 Native (.NET 10) job 执行 Release build/test（排除 Hardware 类测试），always 上传 TRX 与 metadata；见 [ci.yml](../../.github/workflows/ci.yml#L13-L90)。
- Release workflow 配置 Python legacy regression 与 Native solution build/test，并从 Native App 项目 self-contained publish `HAM点名助手.exe` 后将明确路径传给 `release.py`；见 [release.yml](../../.github/workflows/release.yml#L24-L83)。这是配置文本，不是本次执行、资产上传或远端 Release 完成证据。
- `release.py` 以传入 EXE 生成 `HAM.exe`、中文名和 GitHub ASCII 名兼容副本，校验副本与主文件 SHA-256 一致并写 `SHA256SUMS.txt`；既有测试源码包含输入 EXE 逐字节复制、checksum 内容和同大小/mtime 旧资产替换断言，见 [release.py](../../release.py#L117-L159) 与 [test_release_prepare.py](../../tests/regression/test_release_prepare.py#L27-L78)。测试本次未运行。

## 历史：1.0.14-r15 验证

验证时间：2026-10-06（Asia/Shanghai）
平台：Windows 11 / win-x64 / .NET 10.0.12 Runtime / .NET SDK 10.0.401（独立安装目录）

## 结果

| 检查 | 实际结果 |
|---|---:|
| Release 全解决方案编译 | PASS，0 error；干净 Rebuild 有 34 条代码分析器 warning，2026-10-06 复跑 |
| Native 核心 xUnit 自动化测试 | PASS，180 / 180；`artifacts/test-results/final-r34/core-r34.trx`，含实际点名表设备别名、短别名误吸附防回归、全国省市缩写、境外地点人工确认保护、歧义短码保护和非活动旧修订拒绝 |
| WPF UI 自动化测试 | PASS，29 / 29；`artifacts/test-results/final-r32/ui-r32.trx`，包含快捷小窗前/中/尾部编辑、QTH 候选后台重解析保持、`420×190` 最小尺寸布局、输入编辑不触发预览动画、关闭动画后页面无残留过渡，以及 800/1024/1280/1440 窗口下顶部场次按钮不越界 |
| 快捷小窗最小尺寸布局 | PASS；`420×190` 时折叠最近记录，输入、解析、提交和状态仍可用；恢复普通高度后最近记录重新显示 |
| 视频回放端到端测试 | PASS，2 / 2；包含 `ba4scr bfuv36 扬州邗江 7900`、`ba4vnn jsycxs bfuv5r yz 高` 和 `zs7900` 字段编辑样例 |
| Open XML Excel 验证测试 | PASS，2 / 2 |
| 隔离 Microsoft Excel 只读打开 | PASS；当前导出文件在独立 Excel 进程中打开为 22 行、9 列，未修改源文件；仍不把该探针等同于用户桌面人工验收 |
| 当前 Windows 会话短时麦克风与 MP4 双流测试 | PASS；麦克风枚举、PCM 采集、窗口视频和 AAC 音频轨道均通过 |
| 解析循环 | 20,000 次 |
| 内置解析 p50 / p95 / p99 | 0.1159 / 2.1484 / 3.381 ms |
| 完整资料快照解析 p50 / p95 / p99 | 9.2164 / 15.4207 / 18.7593 ms |
| 首次内置解析（含 JIT） | 19.289 ms |
| 后台现有资料装载 | 95 ms |
| 全国行政区记录 | 2,521 条 |
| QTH 名称与别名键 | 11,971 个 |
| 本地设备别名 | 196 个 |
| 工信部规范化唯一型号 | 7,704 个 |
| SQLite 连续提交 | 150 条 |
| SQLite 平均单条提交 | 7.31 ms |
| SQLite `quick_check` | `ok` |
| 自包含 win-x64 单 EXE | 78,645,352 bytes；SHA-256 `7F8A770976A6EA21A8411CFF3891471DCF93204D34624E27231F6F3F116A6FA2`，见 1.0.14-r15 候选包 `SHA256SUMS.txt` |
| 发布 EXE 离屏渲染自检 | PASS，生成 10 张真实 WPF 控件 PNG；目录为 `%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15` |
| 自包含候选包正常启动保持运行 | PASS；源码发布目录和 Downloads 候选副本均 `WaitForInputIdle=true`、窗口标题正确、显式隔离目录创建 `data\ham_checkin_native.db`，保持 8 秒后主动关闭退出码 0；证据为 `startup-smoke-1.0.14-r15.json` 与 `startup-smoke-download-1.0.14-r15.json` |
| 发布候选 EXE 真实键盘黑盒 | PASS；直接启动 Downloads 中的 1.0.14-r15 单文件 EXE，在隔离数据目录中对主窗口和真实快捷小窗分别执行前/中/尾部编辑，6 / 6 结果均保持未修改后缀；证据为 `artifacts/published-blackbox-1.0.14-r15/report.json` |
| 用户实际点名表只读识别审计 | PASS；WeChat 文件目录中 3 个实际工作簿共 129 条记录，QTH/设备/非空天线/功率按规范化期望 129 / 129，无剩余差异；`artifacts/workbook-audit-2026-10-06/result-final.json` |
| 录屏新增识别回归 | PASS；`山东qcd`、`广东省汕头市m507`、`KT-8900D`、`jsjr + shks8600` 均有独立测试，未知城市不强猜；同码多地点显示候选 |
| 录屏逐帧问题回放 | PASS；旧录屏中 `7900` 未识别、`jsycxs` 被遗留并由 `yz` 误导 QTH、`bh8` 被误判北海以及 Excel `sheet1.xml` 修复提示均已形成证据；当前隔离回放分别得到完整 QTH/设备/天线/功率、`bh8` 不进入 QTH，当前导出可被 Excel 只读打开 |
| QTH 候选确认回归 | PASS；`bj` 不再强行解析为北京市，候选包含北京市、贵州省毕节市等；点击候选只改变 QTH，原始输入保持不变 |
| 启动输入回归 | PASS；SQLite/场次启动初始化在后台执行，初始化前可输入，初始化完成后原文和 QTH 解析仍保留 |
| 全国省/市地点树 | PASS；内置行政区树覆盖全国省级节点，已安装地点库数量与“未下载”节点合并显示 |
| Native 更新下载与启动检查 | PASS（模拟/隔离）；下载校验 4/4，真实初始化启动检查 2/2；真实 GitHub 上传下载仍未宣称完成 |
| 现有远程更新渠道只读探测 | NOT_VERIFIED；本轮没有把本地 1.0.14 候选包冒充为 GitHub Release；远程上传和稳定清单切换仍未宣称完成 |

自包含包包含 .NET 10 Desktop 运行时；本次单文件为 78,645,352 bytes（约 74.99 MiB），仍应以用户机器的冷启动和现场持续输入为最终体验依据。离屏渲染同时创建完整 WPF 视觉树和 1440×900 位图，也不等同于严格冷启动。

完整机器可读输出见 [`performance-latest.json`](performance-latest.json)。这些是本机受控基准，不等同于所有用户电脑的冷启动或现场持续输入结果。

## 识别金标准

| 输入 | QTH | 设备 | 天线 | 功率 | 未识别 |
|---|---|---|---|---|---|
| `BA4RLL QYT6900 5W YZ YZ` | 江苏省扬州市 | 全易通 QYT-6900 | 原装天线 | 5W | 空 |
| `BA4AAA NJXW PD780 4.2M 5W` | 江苏省南京市玄武区 | 海能达 PD-780 | 4.2米玻璃钢 | 5W | 空 |
| `BA4AAA R6 Y H NJXW` | 江苏省南京市玄武区 | 摩托罗拉 R6 | 原装天线 | 高 | 空 |
| `BA4AAA UVK6 771 1W YZ` | 江苏省扬州市 | 泉盛 UV-K6 | SRH-771 | 1W | 空 |
| `BA4SCR BFUV36 扬州邗江 7900` | 江苏省扬州市邗江区 | 宝峰 UV-36 | 钻石 7900 | 空 | 空 |
| `BA4VNN JSYCXS BFUV5R YZ 高` | 江苏省盐城市响水县 | 宝峰 UV-5R | 原装天线 | 高 | 空 |
| `BH8` | 空 | 空 | 空 | 空 | `bh8` |
| `BA4AAA XZ-991 5W MYSTERY` | 空 | XZ-991（原文保留） | 空 | 5W | MYSTERY |

这组用例在加载现有 QTH、旧版别名和工信部资料后执行，验证了本地 `R6` 别名优先于工信部同名记录，也验证了未收录型号不丢失。

## 下载目录效果图与本地验收物

实际 WPF 控件离屏渲染的效果图位于：

```text
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\01-快速点名-1440x900.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\02-快速点名-800x600.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\03-独立快速小窗.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\04-QTH字段编辑-未识别修正.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\05-设备资料库.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\06-地点包省市树.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\07-快捷键设置.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\08-关于-版本-更新.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\09-编辑场次信息-修正版.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图-1.0.14-r15\10-录屏与麦克风.png
```

效果图命令使用真实 WPF 控件和真实绑定数据，不叠加伪造文字层；1.0.14-r15 自包含发布物已实际生成 10 张 PNG，包括 800×600 窄窗、字段修正、地点树、关于页和录屏/麦克风页面。

自包含 .NET 10 候选包（r15）：

```text
%USERPROFILE%\Downloads\HAM点名助手-HX-HAM-1.0.14-r15-候选\HAM点名助手.exe
SHA-256：见同目录 `SHA256SUMS.txt`
文件版本：1.0.14.0
```

本轮没有生成框架依赖小包；候选目录提供的是包含 .NET 10 Desktop 运行时的 self-contained 版本，现场优先使用该包。

## 验证边界

- 没有启动或控制用户当前桌面、鼠标、键盘和 Excel；效果图由 WPF 内存离屏渲染。
- 没有写入、迁移或修改真实旧版 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin.db`；迁移逻辑只在隔离临时库测试，并验证了备份和重复启动不重复导入。
- 自动测试全部使用临时 SQLite 数据库；真实资料库只读。
- 当前尚未在本轮验证中创建 GitHub Tag/Release；本地客户端已切换 Native 1.0.14 更新协议。远程上传、Release 资产下载和稳定清单切换没有被本地模拟测试冒充为已完成。
- 本轮新增了提交场次隔离回归：保存旧场次期间切换到新场次，旧记录仍写入旧场次，新场次界面不出现旧记录、不跳号；新增未知型号相近候选回归，候选不会自动替换用户原文；结束场次只读、录屏识别和全国省/市树回归也已通过。地点树读取入口在 r4 中改为静态服务调用，r5 验证了歧义 QTH 候选确认，r6 又验证了启动初始化期间草稿可用且不丢失，r12 验证了 QTH 候选在同一输入修订的后台资料重解析后仍保持，r13 将四个公开行政归属地点加入金标准并重新执行核心/UI 回归，r14 增加了窄窗口顶部操作按钮边界回归。
- 真实用户生产库迁移、中文输入法现场操作、用户可见的 Microsoft Excel 修复提示流程，以及长时间录屏/现场回放仍需现场验收；本轮只完成隔离只读 Excel COM 打开探针，本地短时麦克风和 MP4 双流测试不冒充长时间现场 PASS。

## 版本边界

- 本次本地构建目标框架是 `net10.0-windows`，核心/测试/基准项目分别使用 `net10.0`，SDK 10.0.401；候选版本为 Native 1.0.14，候选迭代为 r15。
- 还原、构建和发布均使用 `C:\Users\wrdzgzs\AppData\Local\dotnet10\dotnet.exe`（SDK 10.0.401），没有改写系统已有的 .NET 8 安装或 PATH。
- `Microsoft.Data.Sqlite` 已升级到 10.0.12；`dotnet list package --vulnerable --include-transitive` 实测为当前源没有易受攻击的包。
- 没有发布 GitHub、Tag 或 Release；本地 1.0.14 候选包已验证候选文件、SHA-256 清单和 Native 更新服务的模拟下载流程。
