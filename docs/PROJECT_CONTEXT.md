# 项目上下文

更新日期：2026-11-20。本文为C#现行产品的长期上下文；与历史README冲突时，按用户确认和Phase0源码审计陈述事实，但不擅自改写旧文档。每条判断按以下类别标识，不能将计划/推测冒充当前实现。

## 证据类别与优先来源

- **已确认事实**：用户明确合同、当前工程目标框架及Phase0审计证据。
- **当前实现**：静态源码/测试/现有产品文档明确显示；未运行验收的功能不得写成动态通过。
- **计划实现**：TODO中尚未完成的设计或开发。
- **合理推测**：从代码路径推导的工作方式，明确注明不是业务批准。
- **待用户确认**：需求/数据契约/版本权威/上线边界仍无足够证据。

当前最权威快照：[综合审计报告](audit/PHASE0_AUDIT_REPORT.md)、[功能清单](audit/FUNCTION_INVENTORY.md)、[源码覆盖](audit/SOURCE_COVERAGE.md)、[问题详细登记册](audit/ISSUE_INVENTORY.md)、[Phase0任务合同](audit/PHASE0_TODO.md)。实现设计参考[Native架构](../native/docs/ARCHITECTURE.md)；较旧用户叙述参考[根README](../README.md)、[Native README](../native/README.md)和[验证记录](../native/docs/VERIFICATION.md)，不得让旧文档标题/版本覆盖Phase0结论。

## 已确认事实

| 主题 | 已确认事实 | 来源与限制 |
| --- | --- | --- |
| 唯一现行产品 | 当前产品是C#/.NET 10/WPF；App目标为 `net10.0-windows`，Native Core等目标为.NET 10。Python不是产品运行栈。 | Phase0报告与项目文件。README存在大量旧Python产品说法，冲突尚未在本次修订。 |
| 版本状态 | 工作树源码版本为Native 1.0.20，但工作树dirty，未由本任务运行验收；Native README/用户指南文字仍描述1.0.19；该分支 `updates/latest.json` 写1.0.5。它们不是远端稳定版本的证明。 | Phase0报告/审计；远端Release和清单未核验，不宣称“线上最新”。 |
| 数据主存储 | 现场记录本地保存于SQLite；Excel是可选导入、导出及显式同步介质。录入热路径不等待Excel或网络。 | Native架构、源码覆盖与审计。SQLite备份/恢复/schema升级仍存在未关闭风险。 |
| 记录字段 | 当前模型实际包含呼号、QTH、设备、天线、功率、信号、原始输入、未识别内容、时间、场次关联等。 | Phase0功能/源码清单；不要由此添加未经批准字段。QSO/ADIF并未确认或证明实现。 |
| 数据保护 | Native迁移从旧SQLite sessions/checkins读取，须保留源库；`CatalogLoader`从旧库只读加载有限别名，不是全库克隆。 | Phase0迁移/目录审计。任何生产迁移须单独授权并隔离演练。 |
| UI方向 | 全软件完整UI重设计及跟随系统/浅色/深色三主题均为已确认要求；Phase 2 IA / 设计规范文档交付范围完成，七项选择（均 A）已获用户确认。 | 用户合同、“全部A 然后继续”（2026-11-14）；[DEC-008](DECISIONS.md)、[信息架构](UI_INFORMATION_ARCHITECTURE.md)、[设计规范](UI_DESIGN_SPEC.md)。仅文档方向获确认，不代表实现或验收；继续目标与安全边界见[DEC-009](DECISIONS.md)。 |
| 功能保护 | 所有既有业务功能必须保留，包括现有录屏/麦克风功能与测试。声音/语音语义审查已取消，不删原视频音轨、不新增同类验收。 | 用户指令；功能盘点见审计。取消素材审查不等于取消软件功能。 |

## 当前实现（静态源码/文档所示；非本次运行验收）

### 输入、解析与提交

快速输入先成为用户可编辑草稿；Native解析器以当前内存 `CatalogSnapshot` 提供结构化预览、互斥候选和未识别原文。操作者明确按Enter后，由NativeStore通过短SQLite事务保存记录。历史/建议结果不得自动覆盖当前文本或字段；失败时原文/未知token应保留。解析/目录/Excel/网络不应进入键盘热路径。此处是审计的源码现状描述，不代表本次已运行验证。

现有实体字段关系以“场次包含记录、记录保存原始输入及已确认字段”为简化模型；准确约束、记录归属、ended写入校验和编辑并发仍应按[NAT-T007等任务](../TODO.md)验证。主持人/参与者是否为正式角色模型尚无证据。

### 存储、兼容与数据位置

Native架构文档列示默认写入 `%LOCALAPPDATA%\HAM点名助手\data\ham_checkin_native.db`，旧库 `ham_checkin.db`、地点库 `qth_places.db`、MIIT型号库 `miit_radio_catalog.db`只读。Native README描述首次迁移前只读备份并导入场次/签到；这不等同于完整、经过生产演练的备份恢复合同。必须保护源库及用户数据。

旧Python代码、旧SQLite表、旧资料别名是历史兼容来源/工具边界。兼容性是部分而非整库克隆；表字段映射、重复场次、skip marker、WAL快照和恢复策略未全部关闭，见[问题索引](ISSUE_INVENTORY.md)与[迁移任务](../TODO.md)。

### 资料与外部依赖

| 能力 | 证据分类 | 当前边界 |
| --- | --- | --- |
| 本地资料快照/别名 | 当前实现 | 解析读取内存快照；旧库别名有限只读装载。重建快照、同键优先级仍是开放风险。 |
| MIIT型号目录 | 当前实现/部分验收 | 存在同步与测试实现；真实官网全量同步/失败恢复未完整验收，需另外授权网络。 |
| QTH地点包 | 当前实现/局部 | 有本地地点数据路径/包入口；远程详细道路/地标包源未配置的状态不能说成已下载/已同步。 |
| 更新服务 | 当前实现/远端待核 | GitHub Release、更新清单与SHA-256约定存在于代码/文档；分支清单、候选、稳定Release彼此分开，远端状态未核实。 |
| Excel | 当前实现 | 明确导入/导出/同步入口；点名提交不依赖Excel。导出5000行截断仍开放（NAT-T002）。同名覆盖采用用户对所选路径的显式授权，确认框默认 `MessageBoxResult.No`；不绑定内容/hash/file ID，确认后外部更改仍可能被替换（DEC-010）。临时工作簿清理仅捕获 `IOException`；`UnauthorizedAccessException` 可能掩盖原错误或遗留临时文件（Minor，未改）。

### 当前限制

- Native 1.0.20是dirty工作树版本，未做本次运行验收；既有1.0.19指南、1.0.5分支清单、远端Release三者不可混为同一“最新版本”。
- 当前主题源码已实现 FollowSystem/Light/Dark、高对比优先、全窗口动态语义资源及偏好持久化。2026-11-17独立离线证据：SDK 10.0.401 Release build 结果为 0 errors；保留的 Release 构建日志含 54 行原始 warning 诊断记录（包含项目重复发出的诊断行），按项目/文件/行/列/代码/消息组合去重后，共 27 条项目范围内的不同诊断，涉及 8 种诊断代码；Native Category!=Hardware tests 303/303 pass、correctness review 0 Critical/0 Major。2026-11-20对指定Release apphost（SHA见[Native验收记录](../native/docs/VERIFICATION.md)）在Windows 11 build 26300 x64 的隔离桌面观测，确认实际Apps主题/Contrast设置变化会引起用户可见主题响应，并已恢复系统设置；这只覆盖该机与列明状态。没有通知事件trace，精确 `SystemEvents.UserPreferenceChanged` / `SystemParameters.StaticPropertyChanged` 映射仍NOT_VERIFIED（ledger #116仍阻塞）；Windows 10、其他DPI、多屏/混合DPI、实际IME、Narrator及更广可访问性矩阵NOT_RUN，选择保留NOT_TESTED，NAT-T022保持开放。数据风险仍开放；总体继续目标不自动放行网络、生产数据、真实桌面/外设或正式发布；Git commit和Git push不在本目标授权内，二者各自均须单独授权，见[DEC-009](DECISIONS.md)。
- 普通 PR 与 main push 已配置独立 Windows/.NET 10 Native job，历史 Python matrix 保留；本机静态配置、Release build/Core tests 与合成故障注入已有本地证据，但远端 GitHub Actions 未运行。
- 导出完整性、备份/恢复、schema迁移、事务业务约束、完整历史兼容和本地资料快照优先级均未标Done。详见[中央任务](../TODO.md)。

## 计划实现

仅描述计划，不是现有能力承诺：

1. Phase 2 IA / 设计方向与七项选择已完成文档范围；NAT-T022三主题源码实现、.NET10离线构建/Category!=Hardware测试及正确性审查已有独立证据。2026-11-20另有一台Windows 11 build 26300 x64 的隔离桌面观测，实际系统设置变化的用户可见响应经核验；精确通知映射仍NOT_VERIFIED（ledger #116仍阻塞），Windows 10及其他DPI/混合屏/实际IME/Narrator/更广可访问性仍NOT_RUN，选择保留NOT_TESTED。因此NAT-T022与PLAN-P4-UI维持开放；详见[验收记录](../native/docs/VERIFICATION.md)。后续按任务依赖、计划及测试/安全闸推进；外部/生产/真实桌面/外设/发布操作另行闸控；本目标不授权Git commit或Git push，二者各自均须单独授权，见DEC-009。
2. 先关闭剩余P0的数据完整性/备份迁移/schema/事务/导出任务，再逐批完成状态、目录、媒体、更新、构建、现场与发布验收；ENG-001普通PR Native Gate已完成本机离线验收，远端工作流未运行。
3. 保留本地SQLite主存储与可选Excel边界；扩展兼容字段/业务范围须有明确需求和迁移验收。
4. Phase2/3/4的详细依赖、状态与可验收结果以[TODO.md](../TODO.md)为唯一任务记录。

## 合理推测（非新增业务决策）

- 快速录入面向现场操作，优先离线、低延迟、显式提交是现有架构表现；这一推测不能替代用户确认的字段/主持人流程。
- 原始文本与未识别内容的保留有助于纠错和兼容，但不自动授权增加新的持久化字段或自动学习行为。
- 资料、Excel、网络同步与更新操作若失败，应与已提交记录隔离；实际回滚/恢复仍需要故障测试。

## 待用户确认或待独立证据

- 1.0.20对应的正式候选、版本权威、分支清单与远端Release如何关联；不得查询/更改远端发布而未获授权。
- 旧库各表/字段/别名/skip marker的完整迁移合同，生产迁移窗口和恢复责任。
- Excel自动补同步、用户工作簿覆盖提示、同名文件确认、更新安装回滚/签名的完整业务合同。
- QTH远端道路/地标来源、MIIT全量同步验收、外部数据许可和刷新周期。
- 正式业务角色、未确认的QSO/ADIF或新增字段；未明确前不进入产品范围。
- 备份保留策略、加密/ACL方案与真实数据恢复验收；不得把当前迁移前备份描述升级为完整灾难恢复保证。

## 长期导航

- [中央任务台账](../TODO.md)：唯一实施顺序、状态与验收。
- [决策记录](DECISIONS.md)：已确认约束与仍待确认的规则。
- [问题索引](ISSUE_INVENTORY.md)：重要开放风险；详细65条以Phase0登记册为准。
- [Phase0来源/证据](audit/PHASE0_AUDIT_REPORT.md)、[功能清单](audit/FUNCTION_INVENTORY.md)、[源码覆盖](audit/SOURCE_COVERAGE.md)、[详细问题登记册](audit/ISSUE_INVENTORY.md)。
