# 变更日志

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
