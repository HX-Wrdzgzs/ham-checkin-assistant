# 长期问题索引

更新日期：2026-11-15。本文件是长期导航/摘要，不复制维护完整问题表。**唯一详细登记册**是[Phase0问题来源与主题台账](audit/ISSUE_INVENTORY.md)，其中保存来源、严重性、置信度及静态检查/未复现细节。新增或关闭问题时先更新详细登记册，再同步此处摘要与[TODO](../TODO.md)，避免两个独立事实源。

以下问题来自Phase0审计时工作树的静态证据；各行状态按后续独立证据逐项维护。Phase0冻结审计记录其审计时结论，不代表当前每项状态；已缓解项仍注明残余风险和未验收范围。

| 风险/类型 | 来源类别 | 状态 | 证据与影响 | 跟进/验收 |
| --- | --- | --- | --- | --- |
| Excel导出最多处理5000条，可能静默缺少较早/较新记录。数据完整性/P0 | NAT、ENG | Open；静态确认，未复现 | `NativeStore.cs:443-455`；导出行数/数据库记录数可能不一致。 | NAT-T002、ENG-010；分别对账5000/5001/10000/10001条首末序号、字段和总数。 |
| 同名目标文件可能被替换。数据安全/P0 | NAT、ENG | 已缓解（DEC-010）；路径级竞争风险已由用户接受 | Phase0 `ExcelExportService.cs:53`；当前替换路径 `ExcelExportService.cs:89`；授权仅针对所选路径，不绑定内容/hash/file ID；确认后外部更改的内容仍可能被替换。 | NAT-T003、ENG-012；SDK 10.0.401 `--no-restore`：`ExcelExportTests`、`NativeEndToEndTests`、`VideoReplayEndToEndTests` 16/16；`ExportUsesCapturedSessionAfterSwitching` 1/1，默认No改动后再次1/1（exit 0）。0 Critical/Major；Minor：模态取消/拒绝及默认焦点缺自动化UI测试（非Yes会提前返回）。UI NOT VERIFIED: 本次自动化窄测未交互验证模态确认默认No，也未验证真实桌面、DPI/IME/读屏/真实Excel。 |
| Excel导出临时工作簿清理可能掩盖原错误或遗留临时文件。可靠性/Minor | NAT | Review minor；静态发现，未复现 | `ExcelExportService.cs:105-107,500-512`；finally调用TryDelete仅捕获IOException，UnauthorizedAccessException可能逸出并掩盖原错误、遗留临时文件。 | 后续验证清理拒绝/导出失败时主错误保留且目标文件hash不变；本次未修改该行为。 |
| 备份、恢复、旧库快照迁移、schema升级和事务业务约束未形成完整可证明合同。数据完整性/P0 | NAT、ENG、LB | Open；多项未验收 | Phase0指出Native备份恢复/schema、WAL一致快照、未来schema拒绝、场次/记录写入不变量仍有风险；迁移不是整库克隆。 | NAT-T004..007、ENG-008/009/011、LB-T02..05；隔离合成库逐表/原文对账，故障可回滚，生产源库不变。 |
| 普通PR Native C# Gate 的远端执行结果尚未验证。 | ENG | 已缓解（Native job已配置且本机故障注入已验收；远端未运行） | `.github/workflows/ci.yml` 配置独立 Windows/.NET 10 job，Python 3.11/3.12 matrix保留；SDK 10.0.401 Release build 0 warnings/0 errors、Native Core tests 207/207，合成编译/断言故障分别被拦截。GitHub Actions远端未运行，未核验真实runner触发及artifact。 | ENG-001；首次获准的远端运行再核验实际runner与artifact；不得将本机故障注入写成远端运行。 |
| 资料快照重建、同键别名优先级及旧库部分别名依赖边界未充分验证。正确性/P1 | NAT、LB | Open；静态/测试覆盖不足 | `CatalogLoader`仅只读旧库部分别名；快照更新与优先级不可从旧文档推定完成。 | NAT-T009/T010、LB-T06/LB-T08；重复重载、删除/禁用、冲突fixture及热路径无I/O。 |
| 版本/构建证据互相不一致，远端状态未核验。发布/溯源 | ENG、LB | Open；状态待确认 | dirty工作树Native 1.0.20；Native指南1.0.19；分支 `updates/latest.json` 1.0.5。无远端最新证明。 | ENG-004、ENG-006、LB-T10/T11；候选、commit/dirty、SDK、EXE hash、发布清单和远端状态分别验证；未批准不发布。 |
| 三主题与完整重设计尚未实现/验证。UI/P1 | NAT、PLAN | Open；需求已确认、实现未验收 | 当前主题固定浅色；全页面完整重设计及系统/浅/深三主题是既定目标。 | NAT-T022、PLAN-P2-IA、PLAN-P2-DESIGN、PLAN-P3-UI、PLAN-P4-UI；按Win10/11、窗口状态、DPI、多屏、字体、焦点/键盘/IME/读屏矩阵验收。 |
| 历史素材不是当前Native产品行为的复现证据。证据边界 | MEDIA | Open/适用范围受限 | MEDIA-TODO-01/02只证明其列明的保全、机械扫描和有限视觉抽样；没有逐帧证明，也没有当前运行行为复现。声音/语音语义审查已取消。 | 仅按MEDIA-TODO-03/05/06/07/08的授权条件跟进；不修改原片、不把素材观察报成Native缺陷。 |

## 跟进约定

1. 复现前核对详细登记册中的来源、静态/动态范围、严重性和置信度；不要因相似路径重复建条目。
2. 修复任务引用具体问题与独立验收；只有证据闭环后才将登记册和TODO状态关闭。构建/测试未运行时写NOT_RUN。
3. 审计快照不可覆盖；修订错误通过带时间/版本的增补记录，保持历史和当前状态可区分。
4. 用户资料、生产数据库、私人素材不得上传或用于未经批准的外部复现。
