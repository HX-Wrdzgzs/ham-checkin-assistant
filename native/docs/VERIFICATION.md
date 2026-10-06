# Windows 原生版开发验收记录

## 1.0.17-r26 当前候选验证（2026-10-06）

本节是当前源代码和 1.0.17-r26 候选包的最新证据；下方的 1.0.16-r18、1.0.15-r17 与 1.0.14-r15 内容保留为历史记录，不能与本候选混用。

| 检查 | 实际结果 |
|---|---:|
| Release 全解决方案编译 | PASS，0 error；保留 34 条代码分析器 warning，没有编译错误 |
| Native 核心自动化测试 | PASS，187 / 187；`artifacts/test-results/1.0.17-r26-core/core-1.0.17-r26.trx` |
| WPF UI 自动化测试 | PASS，31 / 31；`artifacts/test-results/1.0.17-r26-ui/ui-1.0.17-r26.trx`；包含主窗口/小窗前中尾部编辑、双窗口同步、IME 元数据、录屏 MP4 与麦克风、响应式按钮边界和侧边栏页面同步 |
| 发布 EXE 真实启动与键盘黑盒 | PASS；1.0.17-r26 单文件 EXE `WaitForInputIdle=true`、保持运行 8 秒、隔离数据库和资料库路径均生效；主窗口和快速小窗前/中/尾部编辑均保持后缀，并直接读取 9 组视频/全国缩写识别样例解析卡；`artifacts/published-blackbox-1.0.17-r26/report.json` |
| 发布 EXE 在线启动与输入可用性 | PASS；候选 EXE 未使用 `--disable-network`，进入设置页后实际读到“已检查更新 · 当前 1.0.17 为最新”，主窗口/小窗输入和 9 组识别均通过；`artifacts/published-blackbox-1.0.17-r26-online/report.json` |
| 1.0.17-r26 自包含候选 EXE | PASS；文件版本 `1.0.17.0`，产品信息包含已推送提交 `8e1bfde`；实际字节数、SHA-256 和候选副本以 `artifacts/candidate-1.0.17-r26/SHA256SUMS.txt` 为准 |
| 全国行政区 ASCII 别名审计 | PASS；4,762 个唯一 ASCII 别名，0 个失败 |
| 行政区歧义审计 | PASS；269 个真实碰撞，0 个错误强行解析；`鼓楼区`、`栖霞区`、`东乡`保留候选并要求选择 |
| 重名行政区规范化 | PASS；临夏市、楚雄市、阿克苏市等不再输出重复的“省+市+同名市” |
| 短设备查询回归 | PASS；`k1` 不再吸附无关的 `TK11`，`pd780`、`r6`、`k5`、`k6` 仍有正确候选 |
| 视频样例识别审计 | PASS；`7900`、`jsycxs`、`山东qcd`、`广东省汕头市m507`、`bh8` 样例均按当前规则得到结果；完整机器结果见候选包 `识别准确性审计.json` |
| WPF 效果图渲染 | PASS；1.0.17-r26 自包含发布物实际输出 10 张真实控件效果图，含 800×600 窄窗、录屏/麦克风页和导航同步后的设置页 |
| 侧边栏与页面同步 | PASS；设置页/快速点名页切换后选中状态一致；新增 UI 回归测试包含在 31 / 31 中 |
| 候选包校验清单 | PASS；`SHA256SUMS.txt` 与候选 EXE 当前哈希一致 |
| NativeUpdateService 真实更新链路 | PASS（稳定 v1.0.5）；项目自己的更新服务在 GitHub API 403 时回退到 `main/updates/latest.json`，实际下载 78,580,274 字节并完成 SHA-256 校验，临时文件删除；`artifacts/update-live-probe/result.json` |

当前候选包中的正式证据文件：`artifacts/candidate-1.0.17-r26/输入与核心测试.trx`、`WPF黑盒测试.trx`、`发布包黑盒测试.json`、`在线启动输入黑盒.json`、`更新下载黑盒.json`、`识别准确性审计.json` 和 `SHA256SUMS.txt`。

当前仍未宣称完成的项目：真实微软拼音现场操作、用户可见的 Microsoft Excel 修复提示流程、长时间录屏稳定性、1.0.17 远程 GitHub Release 资产下载，以及用户生产库迁移。它们必须在现场或真实发布通道验证，不能由本地隔离测试替代。现有稳定 v1.0.5 下载链路和 1.0.17-r26 候选启动检查已分别通过真实清单回退/下载/SHA-256 与在线启动黑盒，但不能代替 1.0.17 Release 验证。

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
