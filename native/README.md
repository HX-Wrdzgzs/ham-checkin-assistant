# HAM 点名助手 Windows 原生版（Native 1.0.0 候选版）

这是与现有 Python/PySide6 版本并存、准备替代旧版更新通道的 C#/WPF 原生版。当前构建使用独立安装的 .NET 10 SDK
10.0.401，目标框架为 `net10.0-windows`；旧 Python/PySide6 版本不受影响。运行时和 SDK 版本边界见
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)。

当前阶段先验证最关键的现场链路：

- 窗口快速出现，工信部/QTH/旧别名在后台只读装载；
- 键盘输入即时解析，`Enter` 原子写入 SQLite；
- Excel 不在录入热路径中；
- 数据写入 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin_native.db`；
- 首次运行会把旧版生产数据库只读备份后导入 Native 库；旧库原文件不删除、不覆盖，Excel 不在启动时连接；
- 页面切换、解析结果和成功提交具有短促过渡动画，可在设置中关闭；
- 窗口使用标准 Windows 可缩放边框，避免自绘标题栏导致最小宽度异常。
- 原生库、工信部电台库和地点库均不写入 EXE 当前目录；快捷方式或移动 EXE 不改变数据位置。
- 快速录入只走内存解析和 SQLite 短事务；Excel 不在启动和录入热路径中。
- 设置页提供真实“关于 / 版本”窗口：显示 1.0.0、数据目录、稳定 GitHub Release 渠道、更新说明、SHA-256 校验和下载按钮。

## 界面效果

- [1440×900 实际 XAML 效果图](docs/native-ui-actual.png)
- [960×680 窄窗实际 XAML 效果图](docs/native-ui-narrow.png)
- [早期概念效果图](docs/native-ui-concept.png)
- 关于 / 版本 / 更新效果图：见 `%USERPROFILE%\Downloads\HAM点名助手-UI效果图\08-关于-版本-更新.png`
- [架构与完整替换边界](docs/ARCHITECTURE.md)
- [本机验证记录](docs/VERIFICATION.md)
- [用户现场验收流程](docs/ACCEPTANCE-TEST.md)
- [机器可读性能结果](docs/performance-latest.json)

## 本地构建

```powershell
$dotnet10 = "$env:USERPROFILE\.codex\dotnet10\dotnet.exe"
& $dotnet10 restore .\native\HamCheckin.Native.sln --runtime win-x64
& $dotnet10 build .\native\HamCheckin.Native.sln -c Release --no-restore
& $dotnet10 test .\native\HamCheckin.Native.sln -c Release --no-restore
& $dotnet10 run --project .\native\src\HamCheckin.Native.Benchmarks -c Release --no-build
```

生成真实 WPF 效果图（不显示窗口、不控制鼠标键盘）：

```powershell
& $dotnet10 run --project .\native\src\HamCheckin.Native.App -c Release --no-build -- --render-ui-set "$env:USERPROFILE\Downloads\HAM点名助手-UI效果图"
```

本次候选版效果图固定输出八张：快速点名、窄窗口、独立小窗、QTH 字段修正、设备资料库、地点包省市树、快捷键设置、关于/版本/更新。

## 更新渠道边界

原生版继续使用旧版 GitHub 仓库、稳定清单、测试标签和 SHA-256 校验约定；Native 客户端新增本地关于页和点击触发的更新检查。
本地候选包已生成 `v1.0.0` 的 Release 资产和清单，但当前工作流尚未在 GitHub 创建 Tag/Release，远程清单仍需正式发布后切换。

## 当前尚未宣称完成的部分

- 真实用户生产数据库尚未执行迁移；隔离测试已验证迁移前备份、场次/签到导入、旧库保留和重复启动不重复导入。
- 地点包页面目前能读取已安装 `qth_places.db` 的省/市树；远程省份/城市包源尚未配置，不能把按钮当成已完成下载。
- 工信部同步器已实现断点、临时库、筛选和原子替换，并有模拟接口测试；尚未做真实全量官网同步。
- 场次新建/选择/结束、Excel 后台补同步、补全批次撤销、真实 GitHub 下载和用户现场更新安装仍需单独验收。
- SQLite 依赖已升级到 `Microsoft.Data.Sqlite 10.0.12`；NuGet 漏洞检查当前结果为无易受攻击包。
