# HAM 点名助手

面向业余无线电中继点名、主控现场的 Windows 本地点名录入助手。当前唯一现行产品是 **C# / .NET 10 / WPF / SQLite 原生版**；Python 0.9.4 及更早代码只作为历史兼容、旧数据格式和发布工具保留，不是 Native 目标机的运行依赖。

> 当前源码版本为 `1.0.20`。这是工作树版本，不代表已经发布或完成远端 Release 验收。

## 快速示例

```text
bg4tki njqx k6 y 5
```

解析预览会整理为类似：

```text
BG4TKI | 江苏省南京市栖霞区 | 泉盛 UV-K6 | 原装天线 | 5W
```

无法可靠判断的 token 不会被静默丢弃，而是保留为未识别内容，供操作员确认或修正。

## 主要功能

- **快速点名**：呼号、QTH、设备、天线、功率的本地实时解析；字段顺序可变化；主窗口与快速小窗同步输入。
- **呼号记忆**：已确认保存的呼号会按字段记住最近的 QTH、设备、天线和功率；下次输入时以半透明 chip 提示，只有明确点击才应用单个字段，不修改输入框原文、不自动提交。上次时间仅作参考显示。
- **场次与记录**：新建、选择、编辑、结束场次；结束场次只读；记录显式提交后写入 SQLite。
- **资料库**：内置全国行政区/现场别名；可读取已安装的 `miit_radio_catalog.db` 和 `qth_places.db` / `qth_admin.db`；型号搜索和 QTH 包树均离线使用，不把网络放进录入热路径。
- **Excel**：可选导入、导出和显式同步；Excel 不在点名提交热路径中，失败不会丢弃已经写入 SQLite 的记录。
- **界面**：跟随系统 / 浅色 / 深色三主题，高对比优先；主页面切换和五个二级窗口入口使用短过渡动画，可关闭。
- **录屏 / 麦克风**：只采集软件窗口客户区，输出 MP4；麦克风默认关闭，失败时不回退到桌面采集。
- **更新 / 关于**：GitHub Release / 更新清单 / SHA-256 校验约定保留；正式发布和远端状态须独立验收。

## 构建与运行

本机开发使用独立的 .NET 10 SDK。若 `dotnet` 已在 PATH 中，也可直接使用：

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"

& $dotnet10 restore .\native\HamCheckin.Native.sln --runtime win-x64
& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore
& $dotnet10 run --project .\native\src\HamCheckin.Native.App -c Release
```

启动时会创建或读取本地 Native 数据库；生产数据操作前请先阅读数据安全边界。

## 测试

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"

& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore

$env:HAM_CHECKIN_NATIVE_UI_TEST = '1'
& $dotnet10 test .\native\HamCheckin.Native.sln -c Release --no-build `
  --filter "Category!=Hardware"
```

当前工作树最近一次离线验收：Core `253/253`、UI `64/64`，合计 **317/317 passed**。硬件/麦克风测试需要 `HAM_CHECKIN_NATIVE_HARDWARE_TEST=1` 和真实设备；真实网络、生产库迁移、更新安装和发布仍需单独授权与验收。

## 数据位置

默认写入：

```text
%LOCALAPPDATA%\HAM点名助手\data\ham_checkin_native.db
```

只读兼容/资料源：

```text
%LOCALAPPDATA%\HAM点名助手\data\ham_checkin.db
%LOCALAPPDATA%\HAM点名助手\data\qth_places.db
%LOCALAPPDATA%\HAM点名助手\data\qth_admin.db
%LOCALAPPDATA%\HAM点名助手\data\miit_radio_catalog.db
```

旧版 Python SQLite 库只作为只读兼容来源；Native 不会静默删除、覆盖或迁移生产旧库。任何生产迁移、真实设备、联网同步和正式发布都需要单独授权。

## 项目结构

```text
native/src/HamCheckin.Native.App        WPF 应用、视图、ViewModel、主题、动画、录屏入口
native/src/HamCheckin.Native.Core       解析、目录快照、SQLite 存储、导入导出、更新与业务逻辑
native/src/HamCheckin.Native.Benchmarks 性能基准工具
native/tests/HamCheckin.Native.Tests    Core / 集成测试
native/tests/HamCheckin.Native.UiTests  WPF UI 测试
docs/                                   项目上下文、决策、UI 规范、审计与分诊资料
native/docs/                            Native 架构、兼容、验收和用户指南
```

## 文档

- [项目协作规则](AGENTS.md)
- [项目上下文](docs/PROJECT_CONTEXT.md)
- [任务台账](TODO.md)
- [变更日志](CHANGELOG.md)
- [决策记录](docs/DECISIONS.md)
- [问题索引](docs/ISSUE_INVENTORY.md)
- [Native 架构](native/docs/ARCHITECTURE.md)
- [Native 验收记录](native/docs/VERIFICATION.md)
- [用户指南](native/docs/USER-GUIDE.md)
- [旧版兼容说明](native/docs/LEGACY-COMPATIBILITY.md)
- [UI 设计规范](docs/UI_DESIGN_SPEC.md)

## 当前边界

- 手机内网点名仍在设计和分阶段实现中，尚未作为已发布功能；当前版本不自动监听局域网、不开放公网、不修改防火墙。
- 真实 DPI、多屏、实际 IME、读屏、真实设备、真实网络、生产库迁移和正式发布矩阵仍未全部验收。
- 仓库中的历史 Python 目录、旧 SQLite 文件、历史效果图和旧发布记录是兼容/审计材料，不代表当前 Native 产品的运行时或发布状态。
