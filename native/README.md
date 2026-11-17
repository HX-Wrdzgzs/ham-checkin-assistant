# HAM 点名助手 Windows 原生版（Native 工程版本 1.0.20）

这是当前唯一现行的 C#/WPF Native 产品；旧 Python/PySide6 0.9.4 仅作为兼容与维护工具保留，不是 Native 目标机运行依赖。旧版更新通道及正式替换仍按独立验收边界处理。当前构建使用独立安装的 .NET 10 SDK
10.0.401（本机 SDK 路径 `%USERPROFILE%\.codex\dotnet10\dotnet.exe`），目标框架为 `net10.0-windows`；发布工作流声明 SDK `10.0.x`。发布配置为 win-x64 自包含单文件，目标机不要求 Python 或单独安装 .NET；实际发布 EXE 未动态核验。运行时和 SDK 版本边界见
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)。源码版本字段见 [App 项目文件](src/HamCheckin.Native.App/HamCheckin.Native.App.csproj#L17-L19)；当前 `1.0.20` 产物未动态验收。本文所列 `1.0.19-r28` / `1.0.19-r29` 候选包、效果图与 `v1.0.19` 发布计划均属历史资料，不代表当前产物或远端 Release 状态已核验。

当前阶段先验证最关键的现场链路：

- 窗口快速出现，全国行政区快照立即可用，工信部/QTH 详细地点和旧别名在后台只读装载；
- 键盘输入即时解析，`Enter` 原子写入 SQLite；
- Excel 不在录入热路径中；
- 数据写入 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin_native.db`；
- 旧版 SQLite 兼容导入只读访问旧库、先生成备份再写入独立 Native 库；旧库不修改或删除。字段、默认/跳过及已核实版本范围有限，真实生产迁移尚未验收，详见[兼容说明](docs/LEGACY-COMPATIBILITY.md)；Excel 不在启动时连接；
- 页面切换和成功提交具有短促过渡动画；逐字解析不触发动画，可在设置中关闭反馈动画；
- 窗口使用标准 Windows 可缩放边框，避免自绘标题栏导致最小宽度异常。
- 原生库、工信部电台库和地点库均不写入 EXE 当前目录；快捷方式或移动 EXE 不改变数据位置。
- 快速录入只走内存解析和 SQLite 短事务；Excel 不在启动和录入热路径中。
- 设置页提供“关于 / 版本”窗口、数据目录、稳定 GitHub Release 渠道、更新说明、SHA-256 校验和下载按钮及自愿赞助入口；程序启动后会后台检查更新。源码将固定常量 `NativeVersion.Current = "1.0.20"` 赋给版本字段（见 [`NativeVersion`](src/HamCheckin.Native.Core/Updates/NativeUpdateService.cs#L9-L12) 与 [`AboutWindow`](src/HamCheckin.Native.App/Views/AboutWindow.xaml.cs#L21)）；当前 `1.0.20` EXE 未动态核验，因此不承诺该产物实际显示的版本。
- “录屏 / 麦克风”只采集软件窗口客户区，输出 MP4；已有文件拒绝覆盖，失败录屏使用临时文件并清理；操作步骤见 [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md)。

## 界面效果

- [1440×900 实际 XAML 效果图](docs/native-ui-actual.png)
- [960×680 窄窗实际 XAML 效果图](docs/native-ui-narrow.png)
- [早期概念效果图](docs/native-ui-concept.png)
- 关于 / 版本 / 更新效果图：见历史 `1.0.19-r28` 候选包 `%USERPROFILE%\Downloads\HAM点名助手-HX-HAM-1.0.19-r28-候选\效果图\08-关于-版本-更新.png`
- [架构与完整替换边界](docs/ARCHITECTURE.md)
- [本机验证记录](docs/VERIFICATION.md)
- [用户现场验收流程](docs/ACCEPTANCE-TEST.md)
- [操作指南](docs/USER-GUIDE.md)
- [机器可读性能结果](docs/performance-latest.json)

## 本地构建

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"
& $dotnet10 restore .\native\HamCheckin.Native.sln --runtime win-x64
& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore
& $dotnet10 test .\native\HamCheckin.Native.sln -c Release --no-restore
& $dotnet10 run --project .\native\src\HamCheckin.Native.Benchmarks -c Release --no-build
```

`1.0.19-r28` 历史候选效果图渲染命令（不显示窗口、不控制鼠标键盘）：

```powershell
& $dotnet10 run --project .\native\src\HamCheckin.Native.App -c Release --no-build -- --render-ui-set "$env:USERPROFILE\Downloads\HAM点名助手-UI效果图-1.0.19-r28"
```

`1.0.19-r28` 历史候选效果图固定输出十张：快速点名、窄窗口、独立小窗、QTH 字段修正、设备资料库、地点包省市树、快捷键设置、关于/版本/更新、编辑场次信息、录屏与麦克风。

## 更新渠道边界

原生版继续使用旧版 GitHub 仓库、稳定清单、测试标签和 SHA-256 校验约定；Native 客户端进入可录入状态后后台检查更新，关于页仍可手动检查和下载。
历史发布计划曾使用 `v1.0.19` Tag；Release 工作流配置为构建和校验通过后刷新稳定更新清单。本文件不证明该计划已执行、远端 Release/稳定清单的当前状态，亦不代表当前 `1.0.20` 产物已经动态验收。

## 当前尚未宣称完成的部分

- 真实用户生产数据库尚未执行迁移；隔离测试已验证迁移前备份、场次/签到导入、旧库保留和重复启动不重复导入。
- 地点包页面显示全国省/市树，并合并已安装 `qth_places.db` / `qth_admin.db` 的数量；远程详细道路/地标包源尚未配置，不能把按钮当成已完成联网下载。
- 工信部同步器已实现断点、临时库、筛选和原子替换，并有模拟接口测试；尚未做真实全量官网同步。
- 场次新建/选择/结束、Excel 后台补同步、补全批次撤销、真实 GitHub 下载和用户现场更新安装仍需单独验收。
- SQLite 依赖已升级到 `Microsoft.Data.Sqlite 10.0.12`；NuGet 漏洞检查当前结果为无易受攻击包。
