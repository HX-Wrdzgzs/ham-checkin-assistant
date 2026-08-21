# 江苏省中继 HAM 智能点名录入助手

> 面向业余无线电中继点名主控的 Windows 本地辅助工具。
> 用更短的输入完成呼号、QTH、设备、天线、功率等信息录入，并通过 SQLite 历史、模糊匹配和 Excel 联动减少重复操作。

**当前版本：v0.9.0**

核心录入能力采用 **规则解析 + 拼音缩写 + SQLite 历史 + 模糊匹配**，不依赖 AI / LLM / Token / 云端推理。
核心录入、历史查询与本地数据管理可离线使用；**365dt 历史同步属于可选联网功能**。

---

## 适合什么场景

典型使用场景是中继台网点名、应急通信演练、HAM 活动签到等需要连续录入大量台站信息的场合。

传统方式通常需要在 Excel 中反复切换单元格、输入完整地名和设备名称。本项目将常见信息压缩为短指令，例如：

```text
bg4tki njqx k6 y 5
```

可解析为：

```text
BG4TKI | 南京栖霞 | 泉盛 UV-K6 | 原装天线 | 5W
```

字段顺序不要求固定，呼号、QTH、设备、天线、功率可以混合输入。

---

## 主要功能

### 快速录入与智能解析

- 支持呼号 / QTH / 设备 / 天线 / 功率自由顺序输入
- 支持常用地名与设备的拼音缩写
  - `njqx` → 南京栖霞
  - `ahwh` → 安徽芜湖
- 支持呼号格式规范化
- 支持常用设备、天线、功率的别名与缩写
- 对存在歧义的缩写给出候选，不盲目自动选择

### 历史建议

输入呼号后可根据 SQLite 历史记录给出：

- 最近一次使用信息
- 最常用信息

历史建议不会自动写入本次记录：

- `Tab`：显式接受历史建议
- `Enter`：提交本次明确输入或已经接受的历史信息

这可以避免“历史值看起来正确，但实际本次已经更换设备/QTH”的误录。

### 模糊匹配

针对拼写错误、缺字、多字和近似缩写提供候选。

只有在：

```text
top1 >= fuzzy_high
且
top1 - top2 >= fuzzy_margin
```

时才允许高置信度自动接受，否则要求人工选择。

默认阈值：

```text
fuzzy_high   = 92
fuzzy_mid    = 75
fuzzy_margin = 5
```

### SQLite 主数据库

SQLite 是程序的主数据源，Excel 不是唯一数据副本。

每次录入采用：

```text
解析输入
  ↓
写入 SQLite
  ↓
COMMIT 成功
  ↓
同步 Excel
```

因此即使 Excel 写入或保存失败，已经确认的点名记录仍保留在数据库中。

同时支持：

- 场次管理
- 一键撤销（软删除）
- 修改审计
- 台站历史统计
- 每日数据库备份
- 崩溃后的 active session 恢复

### Excel 实时联动

每个点名场次独立绑定自己的 Excel 工作簿和工作表。

主要行为：

- 场次级 Excel 绑定
- 切换场次时自动切换绑定
- 指定工作簿不存在时 fail-closed，不回退到任意打开的工作簿
- 自动识别表头，不写死列号
- 缺少必要字段时拒绝连接
- 从最后一条有效数据记录之后继续写入
- 内部空行不会导致覆盖后续已有数据
- 更新前校验“序号 + 呼号”行身份
- Excel Save 失败不会伪装为已同步
- 外部字符串以 `= + - @` 开头时按文本写入，降低公式注入风险

Excel 同步状态：

```text
pending → written → persisted → verified
```

异常情况下会保留 `error` / `conflict` / `pending`，方便之后重新同步。

### 历史 Excel 导入

支持：

- `.xlsx` 单文件导入
- 文件夹批量导入
- 原子导入
- 跨文件业务去重
- 导入失败整体回滚，避免半导入状态

### 365dt 历史同步

支持从 365dt 获取台站历史数据，用于补充本地历史建议。

同步采用按呼号状态判断的增量策略：

```text
排行 count 变化
或 从未同步
或 上次同步失败
        ↓
才拉取该呼号详情
```

特点：

- 默认单次最大拉取 `200`
- 部分失败可重试
- 不同 UID 使用独立同步命名空间
- 数据库通过 `UNIQUE(source, source_record_id)` 做最终去重

> 365dt 是可选联网能力。关闭网络不会影响本地核心录入，但无法执行在线历史同步。

### 悬浮快速录入窗

提供适合点名主控操作的悬浮输入窗口：

- 窗口置顶
- 可拖动
- 可调透明度
- 全局快捷键呼出 / 隐藏

### 单实例保护

Windows 下使用单实例锁，重复启动时直接拒绝第二个实例，避免同时出现：

- 多个 SQLite writer
- 多个 Excel controller
- 多个 365dt 同步任务

---

## 快速开始

### 运行环境

建议环境：

- Windows 10 / 11
- Python 3.10+（建议使用当前稳定版本）
- Microsoft Excel 桌面版（需要实时 COM 联动时）

主要依赖：

- PySide6
- pywin32
- openpyxl
- rapidfuzz
- pypinyin
- requests

### 1. 克隆仓库

```bash
git clone https://github.com/HX-Wrdzgzs/ham-checkin-assistant.git
cd ham-checkin-assistant
```

### 2. 创建虚拟环境（推荐）

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

CMD：

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. 安装依赖

```bash
python -m pip install -U pip
pip install -r requirements.txt
```

### 4. 启动

```bash
python app.py
```

首次运行后，会在程序目录生成运行时数据：

```text
data/          SQLite 数据库
logs/          运行日志
backup/        自动备份
config.json    用户配置
```

---

## 基本使用流程

推荐流程：

```text
启动程序
  ↓
创建 / 恢复点名场次
  ↓
可选：连接本场 Excel
  ↓
输入短指令
  ↓
检查解析结果 / 候选 / 历史建议
  ↓
Enter 提交
  ↓
SQLite COMMIT
  ↓
Excel 同步
```

如果 Excel 临时不可用，可继续依赖 SQLite 记录，之后使用“重新同步本场”恢复 Excel。

---

## 快捷键

| 按键 | 功能 |
| --- | --- |
| `Ctrl + Space` | 唤出 / 隐藏悬浮录入窗 |
| `Enter` | 提交本次明确输入 / 已接受的历史建议 |
| `Tab` | 接受历史建议 |
| `Esc` | 清空当前输入 |
| `Ctrl + Z` | 撤销上一条记录 |

---

## Excel 表格要求

程序会自动识别表头，但用于实时绑定的工作表至少需要能够识别以下核心字段：

- 序号
- 时间
- 呼号
- QTH

缺少必要字段时会拒绝连接，而不是猜测列位置。

写入时程序只管理识别到的受管列；执行全量重写时，不应主动删除用户自定义的备注列、公式列等非受管内容。

---

## 配置

首次运行会生成 `config.json`。

当前主要默认配置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `default_province` | `江苏` | 默认省份 |
| `default_repeater_name` | `江苏省中继` | 默认中继名称 |
| `default_operator_callsign` | 空 | 主控呼号 |
| `global_hotkey` | `Ctrl+Space` | 悬浮窗快捷键 |
| `excel_auto_save` | `true` | Excel 自动保存 |
| `dt365_max_fetch` | `200` | 365dt 单次最大同步数量 |
| `backup_keep` | `30` | 默认备份保留数量 |
| `fuzzy_high` | `92` | 高置信度模糊匹配阈值 |
| `fuzzy_mid` | `75` | 中等匹配阈值 |
| `fuzzy_margin` | `5` | 第一、第二候选最小分差 |
| `window_opacity` | `0.95` | 悬浮窗透明度 |
| `window_on_top` | `true` | 悬浮窗置顶 |

配置保存采用临时文件写入、`fsync` 和原子替换，降低配置文件在异常中断时损坏的概率。

---

## 数据安全设计

这个项目把“点名过程中不能丢数据、不能错写旧表格”放在功能优先级之前。

主要保护措施包括：

- SQLite 先提交、Excel 后同步
- Excel 场次级绑定
- Excel 行身份校验
- Excel 同步状态机
- Save 后验证
- 导入事务化
- 数据库唯一约束
- 修改审计
- 软删除
- 单实例保护
- 每日 SQLite 备份
- `PRAGMA quick_check`
- 备份元数据与 checksum
- 恢复前验证 + 临时副本 + 原子替换

### 备份目录

默认：

```text
backup/
```

每日首次启动会创建备份，并为备份生成元数据。

损坏或无法通过校验的备份会被拒绝恢复。

> 仍建议定期将 `data/` 和 `backup/` 复制到另一块磁盘或其他独立存储介质。程序内自动备份不能替代异地备份。

---

## 隐私与网络

核心数据默认保存在本机：

```text
data/ham_checkin.db
```

项目本身不依赖 AI / LLM 服务，也不需要 API Token 才能完成核心录入。

但以下功能会访问网络：

- 365dt 历史同步

如果不需要 365dt，可仅使用本地数据库、规则解析、历史记录和 Excel 功能。

---

## 测试

运行全部测试：

```bash
python -m unittest discover -s tests -v
```

测试使用隔离的临时配置、数据库以及 Mock Excel，不应访问真实：

```text
config.json
data/
backup/
```

仓库同时包含 `bench.py`，用于相关性能 / 压力测试工作。

---

## 打包 Windows EXE

安装打包依赖：

```bash
pip install pyinstaller pillow
```

执行：

```bash
python build.py
```

`build.py` 在构建过程中会保护已有运行时数据，包括：

```text
data/
logs/
backup/
config.json
```

构建失败时也会尝试恢复这些数据；部署时不应覆盖既有数据库、配置和备份。

---

## 项目结构

```text
ham-checkin-assistant/
├─ app.py                 # 应用入口、单实例保护、全局异常处理
├─ config/                # 配置读取、校验与原子保存
├─ core/                  # Parser、预测、模糊匹配、时间规范化等核心逻辑
├─ database/              # SQLite 连接、迁移、Repository、默认词典
├─ normalizers/           # 呼号/QTH/设备/天线/功率规范化
├─ providers/             # 365dt、历史数据来源
├─ excel/                 # Excel COM 控制器、导出、模板处理
├─ services/              # 应用服务与同步服务
├─ ui/                    # PySide6 主界面与悬浮窗
├─ tests/                 # 单元测试、回归测试、Mock COM 测试
├─ assets/                # 图标等资源
├─ bench.py               # Benchmark / 压力测试
├─ build.py               # Windows EXE 构建脚本
├─ version.py             # 当前版本
├─ requirements.txt       # Python 依赖
└─ CHANGELOG.md           # 版本变更记录
```

运行时还会创建：

```text
data/
logs/
backup/
config.json
```

---

## 当前状态

当前仓库版本为 **0.9.0**。

已实现的重点包括：

- 本地点名解析
- 拼音缩写
- 历史建议
- 模糊匹配
- SQLite 主数据库
- 场次管理
- Excel 实时同步与一致性保护
- Excel 历史批量导入
- 365dt 增量同步
- 撤销 / 修改审计
- 自动备份与恢复
- 悬浮快速录入窗
- Windows 单实例保护

### 尚未实现 / 不应视为现有功能

- NRL Nanny 实时监听（原计划 `monitor/`）

该功能只有在实现、测试并通过实际点名场景验证后才会加入正式功能列表。

---

## 开发原则

本项目优先保证：

1. **不丢数据** —— SQLite 是主数据源，外部同步失败不能导致记录消失。
2. **不静默猜错** —— 有歧义时要求人工确认，而不是为了“智能”强行自动选择。
3. **不覆盖错误 Excel** —— 场次绑定和行身份验证必须 fail-closed。
4. **可恢复** —— 同步、导入、备份和场次状态都应允许在异常后恢复。
5. **核心功能尽量本地化** —— 不把点名主流程依赖在 AI 或第三方在线服务上。

---

## 变更记录

详细版本变化见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 问题反馈

如果遇到：

- 缩写无法识别
- QTH / 设备名称匹配错误
- Excel 表头无法识别
- 场次同步异常
- 365dt 数据异常
- 崩溃或数据库恢复问题

建议提交 Issue，并尽可能附上：

```text
程序版本
Windows 版本
Python 版本（源码运行时）
复现步骤
预期结果
实际结果
相关日志（注意先检查并移除不希望公开的信息）
```

项目地址：<https://github.com/HX-Wrdzgzs/ham-checkin-assistant>
