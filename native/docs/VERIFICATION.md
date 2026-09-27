# Windows 原生版开发验收记录

验证时间：2026-09-27（Asia/Shanghai）
平台：Windows 11 / win-x64 / .NET 10.0.12 Runtime / .NET SDK 10.0.401（独立安装目录）

## 结果

| 检查 | 实际结果 |
|---|---:|
| Release 全解决方案编译 | PASS，0 error；25 个 CA 代码分析警告 |
| Native 核心 xUnit 自动化测试 | PASS，73 / 73 |
| WPF UI 自动化测试 | PASS，4 / 4 |
| 解析循环 | 20,000 次 |
| 解析 p50 / p95 / p99 | 0.1161 / 0.3024 / 0.4857 ms |
| 首次内置解析（含 JIT） | 32.402 ms |
| 后台现有资料装载 | 91 ms（文件已进入系统缓存的本次测量） |
| 全国行政区记录 | 2,521 条 |
| QTH 名称与别名键 | 9,628 个 |
| 本地设备别名 | 179 个 |
| 工信部规范化唯一型号 | 7,704 个 |
| SQLite 连续提交 | 150 条 |
| SQLite 平均单条提交 | 9.121 ms |
| SQLite `quick_check` | `ok` |
| 自包含 win-x64 单 EXE | 68,000,982 bytes；SHA-256 `CF5CA8298C682043988B2FE78BE2D652F304C4430A9A82A2552853EA195EDF83` |
| 框架依赖 win-x64 EXE | 921,805 bytes；同目录 `e_sqlite3.dll` 1,978,880 bytes |
| 发布 EXE 离屏渲染自检 | PASS，退出码 0 |
| 两个发布包正常启动保持运行 5 秒 | PASS；均无 .NET Runtime 1026 异常 |

自包含包包含 .NET 10 Desktop 运行时；本次单文件为约 64.8 MiB，仍应以用户机器的冷启动和现场持续输入为最终体验依据。离屏渲染同时创建完整 WPF 视觉树和 1440×900 位图，也不等同于严格冷启动。

完整机器可读输出见 [`performance-latest.json`](performance-latest.json)。这些是本机受控基准，不等同于所有用户电脑的冷启动或现场持续输入结果。

## 识别金标准

| 输入 | QTH | 设备 | 天线 | 功率 | 未识别 |
|---|---|---|---|---|---|
| `BA4RLL QYT6900 5W YZ YZ` | 江苏省扬州市 | 全易通 QYT-6900 | 原装天线 | 5W | 空 |
| `BA4AAA NJXW PD780 4.2M 5W` | 江苏省南京市玄武区 | 海能达 PD-780 | 4.2米玻璃钢 | 5W | 空 |
| `BA4AAA R6 Y H NJXW` | 江苏省南京市玄武区 | 摩托罗拉 R6 | 原装天线 | 高 | 空 |
| `BA4AAA UVK6 771 1W YZ` | 江苏省扬州市 | 泉盛 UV-K6 | SRH-771 | 1W | 空 |
| `BA4AAA XZ-991 5W MYSTERY` | 空 | XZ-991（原文保留） | 空 | 5W | MYSTERY |

这组用例在加载现有 QTH、旧版别名和工信部资料后执行，验证了本地 `R6` 别名优先于工信部同名记录，也验证了未收录型号不丢失。

## 下载目录效果图与本地验收物

实际 WPF 控件离屏渲染的效果图位于：

```text
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\01-快速点名-1440x900.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\02-快速点名-800x600.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\03-独立快速小窗.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\04-QTH字段编辑-未识别修正.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\05-设备资料库.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\06-地点包省市树.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\07-快捷键设置.png
%USERPROFILE%\Downloads\HAM点名助手-UI效果图\08-关于-版本-更新.png
```

效果图命令使用真实 WPF 控件和真实绑定数据，不叠加伪造文字层；源码运行和自包含发布物运行的渲染命令退出码均为 0。

自包含 .NET 10 候选包：

```text
%USERPROFILE%\Downloads\HAM点名助手-v1.0.0-候选-20260927-3\HAM点名助手.exe
SHA-256: CF5CA8298C682043988B2FE78BE2D652F304C4430A9A82A2552853EA195EDF83
文件版本：1.0.0.0
```

轻量框架依赖 .NET 10 验收包：

```text
%USERPROFILE%\Downloads\HAM点名助手-原生验收版-框架依赖-0.1.0-net10\HAM点名助手.Native.exe
同目录：e_sqlite3.dll
SHA-256（EXE）：D0E5B15FCE784DC8E6144707BF5081D390C341C25EA85FDB5BA6616EDA3213A7
SHA-256（e_sqlite3.dll）：B7385D722C83FB52142A00477A726723745916D22A555711EE89834C1111FB2E
```

框架依赖包需要 Windows 上安装 .NET 10 Desktop Runtime；当前开发机已安装。没有 .NET 10 Runtime 时优先使用上面的自包含包。

## 验证边界

- 没有启动或控制用户当前桌面、鼠标、键盘和 Excel；效果图由 WPF 内存离屏渲染。
- 没有写入、迁移或修改真实旧版 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin.db`；迁移逻辑只在隔离临时库测试，并验证了备份和重复启动不重复导入。
- 自动测试全部使用临时 SQLite 数据库；真实资料库只读。
- 当前尚未发布 GitHub Tag/Release；代码已切换 Native 1.0.0 更新协议，远程清单要等正式 Release 工作流成功后才会切换。
- 真实用户生产库迁移、中文输入法现场操作和 Microsoft Excel 人工打开仍需现场验收；本地自动化不冒充这些 PASS。

## 版本边界

- 本次本地构建目标框架是 `net10.0-windows`，核心/测试/基准项目分别使用 `net10.0`，SDK 10.0.401。
- 还原、构建和发布均使用 `C:\Users\wrdzgzs\.codex\dotnet10\dotnet.exe`，没有改写系统已有的 .NET 8 安装或 PATH。
- `Microsoft.Data.Sqlite` 已升级到 10.0.12；`dotnet list package --vulnerable --include-transitive` 实测为当前源没有易受攻击的包。
- 没有发布 GitHub、Tag 或 Release；本地候选包已验证 Release 资产、SHA-256 清单和 Native 更新服务的模拟下载流程。
