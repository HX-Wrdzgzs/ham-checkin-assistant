# HAM 点名助手 Native（Windows）

这是当前唯一现行的 C# / .NET 10 / WPF 产品工程。根目录的 Python 0.9.4 代码只保留为历史兼容和发布工具，不进入 Native 目标机运行时。

- 目标框架：`net10.0-windows`（WPF）；Core、测试和基准工程使用 .NET 10。
- 本地存储：SQLite；Excel 是可选导入、导出和显式同步边界。
- 源码版本：`1.0.20`（工作树版本，不代表已发布或远端 Release 已验收）。
- 发布配置：win-x64 自包含单文件；实际发布 EXE 需另行验收。

## 构建

推荐使用独立安装的 .NET 10 SDK；本机路径为 `%USERPROFILE%\.codex\dotnet10\dotnet.exe`：

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"

& $dotnet10 restore .\native\HamCheckin.Native.sln --runtime win-x64
& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore
```

启动：

```powershell
& $dotnet10 run --project .\native\src\HamCheckin.Native.App -c Release
```

## 测试

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"

& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore

$env:HAM_CHECKIN_NATIVE_UI_TEST = '1'
& $dotnet10 test .\native\HamCheckin.Native.sln -c Release --no-build `
  --filter "Category!=Hardware"
```

当前工作树最近一次结果：Core `253/253`、UI `64/64`，合计 **317/317 passed**。

- 硬件/麦克风测试需要 `HAM_CHECKIN_NATIVE_HARDWARE_TEST=1` 和真实设备，未设置时不会冒充通过。
- 真实网络、生产库迁移、更新安装/发布不在普通测试范围内，需单独授权。
- UI 测试通过 `HAM_CHECKIN_NATIVE_UI_TEST=1` 跳过真实启动路径；不要把它当成桌面矩阵验收。

## 工程结构

```text
src/HamCheckin.Native.App        WPF、视图、ViewModel、主题、动画、录屏/麦克风入口
src/HamCheckin.Native.Core       解析、目录、SQLite、Excel、更新、兼容迁移
src/HamCheckin.Native.Benchmarks 性能基准
tests/HamCheckin.Native.Tests    Core/集成测试
tests/HamCheckin.Native.UiTests  WPF UI 测试
docs/                            架构、兼容、验收、用户指南
```

## 数据安全

默认 Native 数据库：

```text
%LOCALAPPDATA%\HAM点名助手\data\ham_checkin_native.db
```

旧版 `ham_checkin.db`、已安装的 `qth_places.db` / `qth_admin.db` 和 `miit_radio_catalog.db` 只读使用；Native 不静默修改、删除或覆盖旧源库。生产迁移、真实设备、联网同步和正式发布必须先获得单独授权，并在隔离副本上演练。

## 当前实现要点

- 输入解析在内存完成，`Enter` 才执行短 SQLite 事务。
- 呼号历史记忆从已确认 `checkins` 只读派生，按字段显示半透明建议；点击才应用单个字段，不自动改写输入框或提交。
- 三主题、页面/窗口过渡动画和全局字重已接入；真实 DPI、多屏、IME、读屏矩阵仍未全部验收。
- 目录/QTH/MIIT 数据只在已安装时加载；未安装时会明确显示空状态，不伪造“全量在线”。
- 手机内网点名的 PC「手机收件」页已接入（S2/S3）：需操作员显式启动，手机提交必须由 PC 确认后才写入 SQLite；真实手机/局域网、自包含发布体积和现场验收仍未完成。应用不会自动监听端口或修改防火墙。

## 相关文档

- [根 README](../README.md)
- [项目规则](../AGENTS.md)
- [项目上下文](../docs/PROJECT_CONTEXT.md)
- [架构](docs/ARCHITECTURE.md)
- [验收记录](docs/VERIFICATION.md)
- [用户指南](docs/USER-GUIDE.md)
- [旧版兼容](docs/LEGACY-COMPATIBILITY.md)
