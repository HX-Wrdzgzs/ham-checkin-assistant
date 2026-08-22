# 变更日志

## 0.9.4 (2026-08-22)

本版本重点改进现场识别准确率、未识别数据保留、快速点名操作、自动更新发布链路，以及运行数据和安装目录兼容性。

### 识别能力改进

- 增加中文设备型号识别：
  - 八重洲150R
  - 海能达pdc580
  - 海能达pdc690
  - 好易通800
- 增加现场常见天线识别：
  - 八木
  - 老鹰507
  - x520
  - 770s
- 改进中文品牌+数字型号的识别规则，避免设备型号被错误放入 QTH。
- 改进未知设备和天线的字段保留逻辑，无法完全标准化时仍保留原始输入，不再直接丢失。
- 保留并回归验证 `qyt6900`、重复 `yz` 等已有现场输入规则。

### 未识别数据修复

- 手工将“未识别”内容修改为 QTH、设备或天线后，会自动从“未识别”列移除对应内容。
- 支持消费由多个 token 组成的设备型号，例如“海能达 pdc580”。
- 重复出现的相同未识别内容只移除一次，避免误删其他人工记录。
- SQLite 和 Excel 后台同步会同时更新标准字段和“未识别”字段，避免两边出现重复数据。

### 数据目录与安装兼容性

- 配置文件、SQLite 数据库、日志和备份默认迁移到：

  `%LOCALAPPDATA%\HAM点名助手\`

- 软件不再依赖 EXE 所在目录或快捷方式的当前工作目录。
- 软件移动到其他磁盘、通过快捷方式启动或安装到其他目录时，数据位置保持不变。
- 导出本场和生成模板的默认保存位置改为用户“文档”目录。
- 首次升级时自动复制旧版 EXE 同目录中的运行数据。
- 迁移采用不覆盖策略，目标目录中已有文件不会被旧数据覆盖。
- 旧版运行目录暂时保留，便于用户确认数据完整后可以手工处理。
- 用户在配置中明确填写的绝对路径不会被程序强制搬动。

### 快速点名操作

- “设置 → 常规”新增“快速点名写入键”，支持 Enter、Space、Ctrl/Shift/Alt+Enter 与 F2～F12，保存后主窗口和悬浮窗即时生效。
- 默认仍使用 Enter，已有用户升级后操作习惯不变。
- Space 模式下，单独输入有效呼号后按空格即可写入并进入下一位，普通 Enter 不会误推进。
- 因完整记录本身依赖空格分隔字段，Space 模式保留 `Shift+Space` 继续补字段、`Ctrl+Enter` 提交完整记录的安全路径。

### 自动更新与发布

- 正式 Release 附件统一使用 `HAM.exe`，客户端同时兼容旧版 `HAM点名助手.exe` / 中文 label。
- 稳定备用清单迁移到 `main/updates/latest.json`，并继续读取旧 `codex/ham-checkin-release` 清单作为过渡兼容。
- 新增 `release.py`：从真实 PyInstaller EXE 计算 SHA256，生成 `HAM.exe`、`SHA256SUMS.txt` 和更新清单，禁止手填散列值。
- 新增 GitHub Actions Tag 发布流程：完整测试 → 构建 EXE → 生成真实 SHA256 → 创建/刷新 Release → 回写 main 清单，并同步旧分支清单帮助 0.9.2/0.9.3 客户端跨版本升级。

### 稳定性与验证

- 增加中文设备、天线、未识别清理、用户数据迁移、自定义写入键、Release 产物和更新兼容回归测试。
- 当前测试加载器共发现 247 项；为避免桥接器长任务 502，分 4 批执行 47 + 67 + 42 + 91 项，全部通过。
- Ruff 静态检查通过。
- `compileall` 通过。
- PyInstaller 6.22.0 单文件 EXE 真构建通过；0.9.4 发布产物 SHA256 为 `413419b1afc806c867e5caa4513991e7e858ec79d1164237133db306ddb5a2f7`。
- 保留原有 Excel 行身份校验、SQLite 优先写入和后台 Excel 保存机制。

## 0.9.3 (2026-08-21)

- 自动更新测试版本：用于验证启动检查、下载、SHA256 校验和替换重启流程。
- 本版本功能与 0.9.2 一致，不改变本地 `data/`、`logs/`、`backup/` 和 `config.json`。
- 下载内容出现瞬态 SHA256 不一致时，自动清理并绕过 CDN 缓存重试，最多 3 次。

## 0.9.2 (2026-08-21)

- README 增加“数据画像 → 连接 Excel → 快速点名 → 保存/更新”的图文使用流程。
- 发布版启动后后台检查 GitHub Release；下载更新前校验 SHA256，更新时保留本地数据库、备份和配置；API 限流时回退到公开更新清单。
- 打包改为单文件 `HAM点名助手.exe`，不再要求携带 `_internal` 文件夹。
- 兼容 GitHub 对中文 Release 资产 API 名称的归一化，更新检查同时识别资产名和显示标签。

## 0.9.1 (2026-08-14)
第二轮修复（P0/P1/P2/P3 + NRL Nanny 第四阶段）完成：

### P0（数据完整性）
- 撤销后重新录入不再撞序号约束：序列唯一索引改为 partial（`WHERE is_deleted=0`）+ 稳定重编号。
- 迁移禁止直接 DELETE 历史签到：冲突稳定重编号/完整字段确认后才 merge，前后计数写入 `migration_log`。
- 历史 Excel 跨日期误去重修复：`file_hash` 含文件名，业务指纹含 canonical datetime。
- 迁移 v10：重建 `checkins`/`sessions` 加外键（session_id→sessions.id）+ CHECK（is_deleted/status）。

### P1
- Excel 状态机、原子批量状态、resync 逐行校验、信号列同步、自动保存；callsign 修改规范化+校验。
- 后台 worker 独立 SQLite 连接 + `WorkerManager` 统一生命周期；设置热更新；formula 注入防护。
- 区划后缀算法、设备词典去伪、`build.py` 原子可回滚部署。

### P2
- `sync_state` 主键改 `(source, source_uid)`；QTH 模糊不丢歧义地点（跨城歧义强制候选）。
- 自动场次名取最大编号+1；completion 按标准值频率排序；session stats duplicate 定义明确。
- `_read_rows` 批量 Range 读取；Excel 大文件导入移 worker；Retry-After 上限。
- 备份：当天已有文件也 quick_check；config 损坏保留坏文件并提示；设置页补 opacity/置顶 + 备份/恢复 UI。
- 快速录入补充 `qyt6900`、重复 `yz` 跨字段解析；未识别 token 持久化并自动补建 Excel“未识别”列。
- 场次选择限定本地数据；正常退出自动恢复上次本地进行中场次，异常终止仍进入恢复流程。
- 修改本场记录时，Excel 单行写入与 Save 移入独立 COM worker，避免慢保存阻塞主窗口。
- 输入框 `Ctrl+Z` 恢复为文字撤销，记录级撤销改为 `Ctrl+Shift+Z`；界面撤销不再同步整场 Excel 重排，整场重写 Save 失败会恢复受管列内存数据。

### P3
- `threading.excepthook` 直接挂载；非 Windows 单实例退出释放；`build.py` 防 `code` 未赋值。
- ruff 规则收敛（B023/UP015 修复后不再忽略）；依赖锁定 `requirements.txt`；旧投影 API 私有化。

### 第四阶段 NRL Nanny（只读监听）
- `providers/nrl_nanny.py` + `services/monitor_service.py`：启停/断线重连/状态机
  （offline/connecting/online/degraded/error）/最近活动/原始内容保留/候选呼号提取。
- UI「NRL 监听」页：点击候选填入 QuickInput；**绝不自动写库、绝不自动提交**。
- 网络容错测试：超时、连接重置、非法响应、空活动、请求中停止、应用退出期间停止。

## 0.9.0 (2026-08-14)
第一阶段（数据安全 / Excel / 会话 / 核心不变量）全量完成：

### 数据安全
- 测试与 benchmark 完全隔离：`Settings(path=...)` 显式配置路径；`tests/helpers/` 工厂；
  测试/bench 绝不触碰真实 `config.json`（SHA256 校验回归测试）。
- `build.py` 重构：备份/恢复 `data/ logs/ backup/ config.json`，build 失败也恢复；
  部署前保留既有 runtime，绝不覆盖 DB/backup/config。
- Windows 单实例保护（`CreateMutexW`）；重复实例拒绝启动。

### 会话状态机
- `ended` 场次只读；`end_current_session()` 清空当前；结束后提交自动新建场次；
  显式 `reopen_session()` 才能恢复；崩溃恢复顺序：读 active → 恢复 → 才建新场次。

### 数据库约束
- `UNIQUE(session_id, sequence_no)`（含并发安全分配器，迁移时去重既有重复）。
- `UNIQUE(source, source_record_id)`（部分索引，仅非空；DB 负责最终去重）。
- `source_station_state`（365dt 真增量）、`import_jobs`（导入完成状态）、
  sessions 外部键（source+uid+date）。

### Excel 数据完整性
- Excel 绑定 Session 级：切换场次断开旧绑定；无绑定显示未连接；
  指定 workbook 缺失 fail-closed，绝不回退到任意 ActiveWorkbook。
- 追加行算法按「最后一条有效数据记录」，内部空行后不会覆盖已有数据。
- `rewrite_all` 只清理受管列，保留用户列/公式列/备注列/格式。
- 行身份校验：更新前验证 sequence+callsign；不匹配搜索唯一匹配，否则 conflict。
- Excel 同步状态机：`pending/written/persisted/verified/conflict/error`；
  Save 失败不标记已同步；补同步单事务（collect→写→Save→verify→标记）。
- schema 校验：连接时缺少必要列（序号/时间/呼号/QTH）即失败。
- 一致性检查：重复/非法序列、空行后继续检查、extra/missing/field diff/identity。

### Station/Profile 投影
- `stations`/`station_profiles` 改为 `checkins` 的可重建投影（按时间聚合），
  编辑/撤销/改呼号绝不 count+1；`last_seen` 不因导入顺序回退。

### 第二阶段（Parser / 365dt / 线程）
- Parser 建议模型：历史只进 `result.history`，Enter 只提交显式字段，Tab 接受历史。
- 模糊匹配 margin：`top1-top2 >= fuzzy_margin` 才自动接受，否则强制候选。
- 呼号规则强化：`/` 后缀需主体+后缀合法（`BA4XXX/P` 接受，`///` 拒绝）。
- 365dt 真增量：per-callsign count 变化/未同步/失败才拉取；UID 隔离；
  partial 失败 + retry；max_fetch 不双倍；默认规模 200。
- 同步线程：`sync_in_progress` 单任务；worker 连 `done` 信号；run() 总异常保护。

### 第三阶段（导入 / 配置 / 备份 / 迁移）
- Excel 导入原子化：单事务写 raw_imports+checkins，失败整体回滚（0 half-import）。
- 导入 job 状态：只有 completed 才整文件跳过；跨文件业务指纹去重；`.xlsx` only。
- 时间规范化：数据库统一 `YYYY-MM-DDTHH:MM:SS`（`2000/20:00/20:00:00/datetime` 全标准化）。
- Settings 原子写（tmp→fsync→replace）失败返回 False，UI 明确提示。
- 备份：temp → backup API → quick_check → 原子改名 + metadata.json；新增恢复能力。
- 迁移：v3~v7，v1/v2→latest 迁移测试 + 去重测试。

## 0.8.0
历史版本（V2 增量同步、模糊匹配、撤销等）。
