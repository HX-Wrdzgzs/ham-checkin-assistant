# 变更日志

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
