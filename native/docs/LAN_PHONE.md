# 手机内网点名（设计/实现状态）

状态：**S3 已实现，未发布，未做真实手机/局域网验收**。仓库包含 S2 服务骨架（Kestrel、配对/令牌、待确认队列、回环测试）和 S3 WPF「手机收件」页面（启动/停止、地址选择、PIN/URL、已连接手机、待确认列表、确认/拒绝和快速页待确认提示）；App 已引用 LanServer 并显式引用 `Microsoft.AspNetCore.App` 共享框架。不会自动启动监听；真实手机与局域网联调仍属 S4。

## 目标

PC 作为唯一数据主机，手机浏览器只负责输入、预览和提交：

```text
手机浏览器（同源内嵌页面）
  → 私网 HTTP + 配对 PIN / Bearer 令牌
  → PC 端 Kestrel（默认关闭）
  → 服务端 InputParser / CatalogService
  → 待确认队列（内存，不落盘）
  → 操作员在 PC 明确确认
  → 既有 NativeStore 短 SQLite 事务（source = lan）
```

任何手机提交在 PC 确认前都不会写入 SQLite。手机页面不内置解析器、不访问资料库数据库。

## 安全默认

- 仅显式启动；默认不监听、不写配置、不开机自启。
- 只绑定具体私网 IPv4；回环仅用于自动化测试。拒绝通配地址和公网地址。
- 6 位配对 PIN，令牌只在 PC 内存保存 SHA-256；停止服务或轮换 PIN 即失效。
- 明文 HTTP 仅限可信局域网；同网段可嗅探呼号/QTH。PC 确认和 PIN/令牌不能替代公网安全边界。
- 不启用 CORS；拒绝跨源/Host 不匹配；API `no-store`，静态页 `no-cache`；请求体上限 8 KiB。
- 不执行 UPnP、端口映射、netsh/防火墙命令、公网请求或遥测。

## HTTP 接口（S2）

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/`、`/app.js`、`/app.css` | 无 | 内嵌手机页面 |
| POST | `/api/pair` | PIN | 换取 Bearer 令牌 |
| GET | `/api/health` | Bearer | 场次/服务状态 |
| POST | `/api/preview` | Bearer | 服务端解析预览 |
| POST | `/api/submissions` | Bearer | 创建待确认条目（不写库） |
| GET | `/api/submissions/{id}` | Bearer | 查询 pending/approved/rejected/expired |

错误码：`bad_pin`、`token_invalid`、`no_callsign`、`session_ended`、`queue_full`、`rate_limited`、`bad_request`、`payload_too_large`、`unknown`。

## 数据与幂等

- `checkins.submission_id` 仍是唯一键；LAN 批准使用带场次范围的 `lan-{sessionId}-{clientId}`。
- 同 `clientSubmissionId` 重试复用队列条目；批准重复不会产生第二条记录。
- 待确认队列上限 50；已决条目短期保留供手机轮询终态；条目过期或 PC 停止时不写库。
- 批准必须在点击时取当前场次快照；已结束场次不得批准。

## 代码位置

```text
native/src/HamCheckin.Native.Core/Lan/        契约、队列、PIN/令牌、限流、批准服务
native/src/HamCheckin.Native.LanServer/       Kestrel 宿主、端点、内嵌手机页面
native/src/HamCheckin.Native.App/ViewModels/LanPanelViewModel.cs  「手机收件」页面状态、启动/停止与确认入口
native/src/HamCheckin.Native.App/Views/MainView.xaml              「手机收件」页面、快速页待确认提示
native/tests/HamCheckin.Native.Tests/Lan*     回环端点/队列/鉴权/生命周期测试
native/tests/HamCheckin.Native.UiTests/LanPanelUiTests.cs         WPF 页面与回环 UI 测试
```

## 当前状态与未完成

- S3 代码已接入：WPF「手机收件」页面、启动/停止、地址选择、PIN/URL、已连接手机、待确认列表、确认/拒绝和快速页待确认提示均由 App→LanServer 实现；真实手机/局域网验收未进行。
- S4：真实手机/局域网联调、防火墙提示、PC 休眠/切网、二维码（另需依赖决策）和现场验收。
- 打包说明：App 项目已就地声明 `<FrameworkReference Include="Microsoft.AspNetCore.App" />`（WPF 进程内托管 Kestrel），运行时需要 ASP.NET Core 10 共享框架；自包含/单文件发布的体积和运行时前置条件尚未测量。
- 真实 DPI/移动端浏览器/读屏、Windows 10/11 局域网矩阵仍为 `NOT_RUN`/`NOT_VERIFIED`。
