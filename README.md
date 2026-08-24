# HX-HAM

面向业余无线电中继点名 / 主控场景的 Windows 本地录入助手。

HX-HAM 通过 **呼号识别、拼音/现场缩写、规则解析、历史画像和模糊匹配**，把现场快速输入整理为结构化点名记录，并保存到 SQLite、同步到 Excel，减少连续点名时的重复录入和后期整理工作。

> 核心点名、历史记录、SQLite 和 Excel 录入不依赖 AI / LLM / Token / 语音识别。
> 365dt 历史同步、NRL Nanny 监听、云端版本查询和自动更新属于可选联网功能。

**当前公开测试 Release：HX-HAM 0.0.2**  
**程序内部版本：0.9.4**

[下载 HX-HAM 0.0.2](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/HX-HAM-0.0.2) · [稳定版 Releases](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases) · [更新日志](CHANGELOG.md) · [问题反馈](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/issues)

> `HX-HAM-0.0.2` 当前属于测试 Release 标签，程序内部仍显示 `0.9.4`。这是现阶段的版本标识差异，不代表下载错误。测试 Release 与稳定版自动更新清单相互隔离。

---

## 它能做什么

现场可以直接输入：

```text
bg4tki njqx k6 y 5
```

程序会整理为类似：

```text
BG4TKI | 南京栖霞 | 泉盛 UV-K6 | 原装天线 | 5W
```

也支持字段乱序、重复缩写和常见设备型号，例如：

```text
ba4rll qyt6900 5w yz yz
```

可识别为：

```text
BA4RLL | 扬州 | 全易通 QYT-6900 | 原装天线 | 5W
```

无法可靠判断的内容不会直接丢弃，而会进入“未识别”字段，之后可以人工修改或补充词典。

---

## 主要功能

### 快速点名

- 呼号、QTH、设备、天线、功率快速解析
- 字段顺序自由，不要求固定输入格式
- 拼音 / 地区缩写，例如 `njqx → 南京栖霞`
- 常见设备型号和现场简称识别
- 模糊匹配与歧义候选
- 无法确认的 token 完整保留
- 主窗口与悬浮快速录入窗
- 快速写入键可自定义

### 历史与呼号画像

- 导入已有 `.xlsx` 点名记录
- 批量导入历史文件夹
- 根据历史数据生成呼号画像
- 提供最近一次 / 最常用的 QTH、设备、天线和功率建议
- `Tab` 手动接受历史建议
- 历史建议不会未经确认自动提交

### SQLite 与场次管理

- SQLite 作为本地主数据库
- 每个点名场次独立管理
- 结束场次只读保护
- 一键撤销采用软删除
- 修改记录保留审计逻辑
- 异常退出后的场次恢复
- 数据库备份与完整性检查
- Windows 单实例保护，避免多个实例同时写库

### Excel 联动

- 场次级工作簿 / 工作表绑定
- Excel 表头自动识别与 schema 校验
- 根据最后一条有效记录继续追加，不因内部空行覆盖已有内容
- SQLite 优先落库，再进行 Excel 写入
- 后台 Excel 保存，减少连续录入时的界面阻塞
- 同步失败保留状态，可执行补同步
- 重新同步本场
- SQLite / Excel 一致性检查
- 保留非受管列、公式列和人工备注列

> 实时 Excel 联动需要 Windows 上安装 Microsoft Excel，并使用 pywin32 COM 接口。

### 365dt 历史同步

- 按呼号状态执行增量同步
- UID 隔离
- 部分失败可重试
- 网络异常不会影响本地点名数据

### NRL Nanny 监听

- 只读监听 NRL Nanny 活动
- 提取候选呼号供主控选择
- 候选只会填入输入流程
- **不会自动写库，也不会自动提交点名记录**

---

## 推荐使用流程

![HX-HAM 使用流程](docs/usage-flow.svg)

### 1. 下载程序

进入当前测试 Release：

[HX-HAM 0.0.2](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/HX-HAM-0.0.2)

下载 Release 中的 `HAM.exe`。

程序采用单文件发布，不需要额外 `_internal` 文件夹。

如果 Windows SmartScreen 首次提示未知发布者，请确认文件来自本仓库 Release，并核对 Release 中的 SHA256 校验信息，不建议从第三方来源下载同名 EXE。

### 2. 准备历史数据（可选）

第一次使用可以直接开始点名，也可以先导入历史记录：

1. 打开“历史数据”。
2. 导入单个 `.xlsx` 或整个历史文件夹。
3. 如有需要，配置并同步 365dt。
4. 重新计算呼号画像。
5. 在呼号库中确认历史 QTH、设备、天线和功率建议。

历史数据越完整，后续录入时的建议越有效；没有历史数据不会阻止正常使用。

### 3. 新建场次

创建本次点名场次。

如果需要 Excel 实时联动：

1. 打开“本场记录”。
2. 点击“连接 Excel”。
3. 选择本场工作簿和工作表。
4. 确认界面显示已连接后开始录入。

每个场次保存自己的 Excel 绑定，切换场次不会自动写入其他场次的工作簿。

### 4. 快速录入

默认按 `Enter` 提交当前记录。

例如：

```text
ba4thg njqx k5 y 5
```

程序解析后先写入 SQLite，再处理 Excel 同步。

如果某项无法确定，原始内容会保存在“未识别”字段中，可以稍后在“本场记录”中修改，或在设置中增加稳定别名。

### 5. 点名结束

建议结束前执行：

1. 保存 / 补同步 Excel。
2. 执行一致性检查。
3. 确认 SQLite 与 Excel 数据正常。
4. 点击“结束本场”。

---

## 自定义快速点名按键

在：

```text
设置 → 常规 → 快速点名写入键
```

可以选择：

- Enter
- Space
- Ctrl + Enter
- Shift + Enter
- Alt + Enter
- F2 ～ F12

默认仍为 `Enter`。

### Space 模式

Space 模式适合大量“只录呼号”的点名场景。

输入有效呼号后按 `Space` 即可写入并进入下一位；普通 `Enter` 不会推进。

由于完整记录本身需要空格分隔字段，如果还要继续输入 QTH / 设备 / 天线等内容：

- `Shift + Space`：输入字段分隔空格
- `Ctrl + Enter`：提交完整记录

---

## 快捷键

| 按键 | 功能 |
| --- | --- |
| `Ctrl + Space` | 显示 / 隐藏悬浮录入窗 |
| `Enter` | 默认提交当前记录 |
| `Space` | 可配置为单呼号写入 / 下一位 |
| `Ctrl + Enter` | Space 模式下提交完整记录 |
| `Tab` | 接受历史建议 |
| `Esc` | 清空当前输入 |
| `Ctrl + Z` | 撤销输入框文字 |
| `Ctrl + Shift + Z` | 撤销上一条记录 |
| `Ctrl + S` | 立即保存 / 补同步当前 Excel 记录 |

---

## 数据安全设计

HX-HAM 不把 Excel 当作唯一数据源。

核心写入链路为：

```text
现场输入
   ↓
解析与确认
   ↓
SQLite 本地提交
   ↓
Excel 写入
   ↓
保存 / 校验 / 补同步
```

这样设计的目的，是避免 Excel 卡顿、保存失败或工作簿临时断开时，已经提交的现场点名记录直接丢失。

程序还包含：

- 场次级 Excel 绑定
- 行身份检查
- Excel 同步状态
- 失败补同步
- SQLite / Excel 一致性检查
- 数据库备份
- 崩溃恢复
- 配置损坏保护
- 单实例写入保护

更详细的测试和发布 Gate 可查看 [RELEASE_GATE.md](RELEASE_GATE.md)。

---

## 数据保存位置

默认运行数据位于：

```text
%LOCALAPPDATA%\HAM点名助手\
```

主要包括：

```text
data\        SQLite 数据
logs\        运行日志
backup\      数据库备份
config.json  用户配置
```

因此移动或更新 `HAM.exe` 时，正常情况下不会覆盖用户数据库、日志、备份和配置。

从旧版升级时，程序包含旧运行目录的数据迁移兼容逻辑，并采用不覆盖已有目标文件的策略。

---

## 联网与隐私边界

HX-HAM 的核心录入流程可以在没有网络的情况下使用，但以下功能需要联网：

- 365dt 历史同步
- NRL Nanny 监听
- GitHub Release 版本查询
- 自动更新检查与下载

这些联网功能不可用时，本地 SQLite、快速点名和 Excel 录入不会因此停止工作。

当前项目不依赖任何 AI / LLM 服务，也不需要 API Token。

---

## 自动更新

稳定发布版支持后台检查 GitHub Release：

1. 查询可用稳定版本。
2. 向用户显示更新提示和 Release 摘要。
3. 用户确认后下载 `HAM.exe`。
4. 使用 Release 中的 SHA256 信息校验文件。
5. 当前程序正常退出后执行替换。
6. 重新启动更新后的程序。

测试标签采用：

```text
HX-HAM-X.Y.Z
```

稳定标签采用：

```text
vX.Y.Z
```

测试 Release 与稳定自动更新清单隔离，因此 `HX-HAM-0.0.2` 不会作为稳定更新自动推送给普通稳定版用户。

源码运行 `python app.py` 时不会自动替换 Python 源码。

---

## 关于 / 版本

HX-HAM 的“关于 / 版本”页面可以查看：

- 当前运行版本
- GitHub 云端版本信息
- Release 更新说明
- 发布日期
- GitHub 项目地址
- Release 页面
- 自愿赞助入口

GitHub 查询失败只影响云端版本显示，不影响本地点名、SQLite 或 Excel。

本软件持续免费使用，赞助完全自愿，不影响功能、数据保存或后续更新。

[自愿赞助支持作者](https://www.ifdian.net/a/wrdzgzs?utm_source=copylink&utm_medium=link)

---

## 从源码运行

### 环境

- Windows
- Python
- Microsoft Excel（仅实时 Excel COM 联动需要）

安装依赖：

```bash
pip install -r requirements.txt
```

启动：

```bash
python app.py
```

主要运行依赖包括：

- PySide6
- pywin32
- openpyxl
- rapidfuzz
- pypinyin
- requests

---

## 项目状态

当前 `HX-HAM-0.0.2` 是测试 Release。

该版本对应代码仍使用内部版本号 `0.9.4`，并包含尚处于 `Unreleased` 区域的“关于 / 版本 / 支持”等功能。后续正式发布时建议统一：

- GitHub Tag
- `version.py`
- CHANGELOG 版本标题
- 软件“关于 / 版本”页面
- 自动更新 manifest

避免出现“Release 显示 HX-HAM 0.0.2、程序内部显示 0.9.4”的版本识别差异。

---

## 问题反馈

如果遇到以下问题：

- 某个呼号 / 地区 / 设备 / 天线无法正确识别
- Excel 无法连接或同步
- 数据出现冲突
- 365dt 同步异常
- NRL Nanny 监听异常
- 自动更新失败
- 软件崩溃
- 功能建议

请前往：

[GitHub Issues](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/issues)

提交问题时建议附带：

- 使用的 HX-HAM / 程序版本
- Windows 版本
- 问题复现步骤
- 错误提示或截图
- 必要的日志片段

公开 Issue 前请删除不需要公开的个人信息、电话号码、地址或完整点名数据。

---

## 相关文档

- [CHANGELOG.md](CHANGELOG.md) — 版本变更记录
- [RELEASE_GATE.md](RELEASE_GATE.md) — 发布验证与已知边界
- [GitHub Releases](https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases) — EXE 下载与 Release 说明

---

HX-HAM 的目标很简单：**让中继主控把注意力放在点名本身，而不是反复敲表格。**
