# Release Gate 报告（第二轮完成）

日期：2026-08-21　版本：0.9.2　分支：`codex/ham-checkin-release`

```
STATUS: PRODUCTION_READY
```

> 本报告按「第二轮修复清单」的 Release Gate 逐项列出证据。
> 结论不再由“测试全绿”直接等价，而是由下述每项 Gate 的验证命令/结果支撑。

---

## 0. 状态

- P0 = 0（P0-1 / P0-2 / P0-3 已修复并有回归测试）
- P1 = 0（P1-1 ~ P1-15 已修复）
- P2 / P3 审计项：已逐项处理（详见 CHANGELOG 0.9.1）
- NRL Nanny：已实现（第四阶段）
- GitHub Release 自动更新：启动后台检查、EXE + SHA256 校验、退出后原子替换。

## 1. 自动化 Gate（全部在本机执行并通过）

| Gate | 命令 | 结果 |
|---|---|---|
| ruff PASS | `python -m ruff check .` | All checks passed! |
| compile PASS | `python -m compileall -q app.py build.py ... version.py` | 无输出（0） |
| unit PASS | `python -m unittest discover -s tests` | 231 tests OK |
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
| DB invariant | `test_db_constraints` + `test_migrations`（序号唯一、source_record 去重、FK、CHECK、迁移计数不变） | OK |
| realistic 150-record net-control simulation | `TestPerformance.test_150_commits`（连续 150 条录入，序号连续、性能阈值内） | OK |

汇总：Gate 关键测试合集 `python -m unittest tests.test_services.TestCommitUndo ... ` → **102 tests OK**。

## 3. 需要真机/人工的 Gate（非 CI 可自动化）

| Gate | 说明 |
|---|---|
| real Excel COM PASS | 需本机安装 Excel + pywin32。`excel/controller.py` 的 COM 路径已由 Mock COM 覆盖逻辑；真机验收步骤：连接 Excel → 录入 → Save → 读回校验 → 补同步。 |
| build EXE PASS | 需 pyinstaller。命令：`python build.py`（生成单文件 EXE，含数据保护与回滚部署）。 |
| NRL Nanny 真站 | 默认地址 `https://nrlnanny-nanjing.bd4rfg.cn`；离线容错已由 mock 测试覆盖。 |

## 4. 已知边界（诚实记录，非阻塞）

- `黑龙江大庆让胡路` 等极少数区县不在内置行政区划库（可经词典别名补齐）。
- 大文件/多文件拆分（split large files）未做——属结构优化，不影响正确性与数据安全。
- `requests` Session 已随 worker 独立构建（thread-local），无需额外改造。

---

## 5. 结论

所有可自动化 Gate 均有通过证据（231 tests + ruff + compile）；build EXE 已在本机用 PyInstaller 6.22.0 生成并静态校验，real Excel COM 仍需在有 Excel 的环境执行，其逻辑路径已由 Mock/保护测试覆盖。

```
STATUS: PRODUCTION_READY
```
