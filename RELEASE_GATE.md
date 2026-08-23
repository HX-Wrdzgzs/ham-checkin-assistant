# Release Gate 报告（0.9.4）

日期：2026-08-23　版本：0.9.4（跨版本更新兼容修复）　分支：`codex/ham-checkin-release`

```
STATUS: RELEASE_REPAIRED; REAL_V093_E2E_PENDING
```

> 本报告按「第二轮修复清单」的 Release Gate 逐项列出证据。
> 结论不再由“测试全绿”直接等价，而是由下述每项 Gate 的验证命令/结果支撑。

---

## 0. 状态

- P0 = 0（P0-1 / P0-2 / P0-3 已修复并有回归测试）
- P1 = 0（P1-1 ~ P1-15 已修复）
- P2 / P3 审计项：已逐项处理（详见 CHANGELOG 0.9.1）
- NRL Nanny：已实现（第四阶段）
- GitHub Release 自动更新：启动后台检查、EXE + SHA256 校验、瞬态校验失败自动重试、退出后原子替换；新增 Tag 驱动的自动构建/发布/清单回写。当前线上 v0.9.4 Release 已用线上原始 `HAM.exe` 修复为 `HAM.exe` + `HAM-legacy.exe`（label=`HAM点名助手.exe`）+ 双条目 checksum；main 与 codex 备用清单均指向 v0.9.4。本次未重建或移动 v0.9.4 Tag。

## 1. 自动化 Gate（全部在本机执行并通过）

| Gate | 命令 | 结果 |
|---|---|---|
| ruff PASS | `python -m ruff check .` | All checks passed! |
| compile PASS | `python -m compileall -q app.py build.py ... version.py` | 无输出（0） |
| unit PASS | 当前 Python 环境单进程完整测试 | 255 tests OK |
| regression PASS | 同上（含 regression 包） | OK |
| migration PASS | `tests.regression.test_migrations`（v1→latest / v2→latest / latest→latest / v10 FK+CHECK / 非破坏性 / 报告留痕） | 16 OK |

## 2. 行为 Gate（回归测试证据）

| Gate | 覆盖测试 | 结果 |
|---|---|---|
| AppService concurrent commit | `TestDBConstraints.test_concurrent_next_sequence_cannot_duplicate`（8 线程并发分配序号） | OK |
| undo → commit | `test_undo_recommit`（撤销后立即重录、多次撤销、序号复用、Excel resync） | OK |
| cross-date import | `test_import_cross_date`（同名记录不同日期不误判重复） | OK |
| Excel Mock COM | `test_excel_controller_mock`（查找 workbook / 追加行 / 受管列 / 行身份 / 批量读取） | 13 OK |
| 365dt incremental | `test_sync_365_incremental`（per-callsign 增量 / UID 隔离 / 部分失败 partial / retry） | OK |
| 365dt partial/retry | 同上 + `test_dt365_retry`（Retry-After 上限 / 重试耗尽抛错） | OK |
| worker shutdown | `test_sync_lifecycle`（SyncWorker / WorkerManager shutdown 有序停止、worker 关自己 DB） | OK |
| deploy rollback | `test_build_protection`（产物校验、target.old 回滚、EXE 缺失拒绝部署） | OK |
| backup/restore | `test_backup_restore`（100→backup→120→restore→精确 100 + quick_check；损坏拒绝；同日坏备份重建；metadata） | 5 OK |
| UI smoke | `test_ui_smoke`（offscreen 实例化 MainWindow，6 个选项卡齐全，退出路径安全） | OK |
| NRL monitor | `test_nrl_monitor`（超时/连接重置/非法响应/空活动/请求中停止/退出期间停止/只读不变量） | 10 OK |
| parser / unmatched retention | `tests.test_parser` + `tests.test_services` + `tests.regression.test_excel_sync`（中文设备/天线、qyt6900、重复 yz、未识别消费和 Excel 同步） | OK |
| user data path migration | `tests.regression.test_user_data_paths`（相对路径、迁移不覆盖、冻结版默认目录） | 3 OK |
| DB invariant | `test_db_constraints` + `test_migrations`（序号唯一、source_record 去重、FK、CHECK、迁移计数不变） | OK |
| realistic 150-record net-control simulation | `TestPerformance.test_150_commits`（连续 150 条录入，序号连续、性能阈值内） | OK |
| update backward compatibility | `tests.regression.test_update_backward_compat`（旧 name/label/checksum/fallback 语义） | 7 OK；线上资产回读 PASS |

汇总：当前仓库共 **255** 项测试；本次兼容修复后已用 CI 同款单进程 `unittest discover` 完整执行，**255 tests 全部 OK**。Python 3.13 / 3.14 的历史 CI 证据仍为 248 项；新增 7 项兼容回归已在当前环境执行。

## 3. 需要真机/人工的 Gate（非 CI 可自动化）

| Gate | 说明 |
|---|---|
| real Excel COM PASS | 需本机安装 Excel + pywin32。`excel/controller.py` 的 COM 路径已由 Mock COM 覆盖逻辑；真机验收步骤：连接 Excel → 录入 → Save → 读回校验 → 补同步。 |
| published v0.9.4 asset PASS | 从现有 v0.9.4 Release 下载真实 `HAM.exe`，复制为兼容资产并分别回读校验；主资产和 `HAM-legacy.exe` 均为 SHA256=`3fded59437d1fb7ac221b7ca553cdd326d99ab83c925ede25c37fce66c6306dc`。本次修复未重建 v0.9.4。 |
| real v0.9.3 → v0.9.4 E2E | `H:\HAM-UPDATE-E2E\HAM.exe` 已准备并校验为 v0.9.3 原始发布文件；启动/替换/重启/数据留痕待当前运行中的 HAM 进程退出后执行。 | PENDING |
| NRL Nanny 真站 | 默认地址 `https://nrlnanny-nanjing.bd4rfg.cn`；离线容错已由 mock 测试覆盖。 |

## 4. 已知边界（诚实记录，非阻塞）

- `黑龙江大庆让胡路` 等极少数区县不在内置行政区划库（可经词典别名补齐）。
- 大文件/多文件拆分（split large files）未做——属结构优化，不影响正确性与数据安全。
- `requests` Session 已随 worker 独立构建（thread-local），无需额外改造。

---

## 5. 结论

所有当前可自动化 Gate 均有通过证据（255 tests + ruff + compile）；线上 v0.9.4 Release 的兼容附件和双条目 SHA256 已真实回读通过。v0.9.3 原始 EXE 已在隔离目录准备完成，但真实启动升级仍受当前两个 HAM 进程占用全局单实例互斥体影响；关闭它们后才能完成最后的替换/重启/数据持久性证据。real Excel COM 仍需在有 Excel 的环境执行，其逻辑路径已由 Mock/保护测试覆盖。

```
STATUS: RELEASE_REPAIRED; REAL_V093_E2E_PENDING
```
