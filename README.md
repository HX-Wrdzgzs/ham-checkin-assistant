# 江苏省中继 HAM 智能点名录入助手

Windows 本地点名辅助程序：通过**缩写 + 规则解析 + SQLite 历史 + 模糊匹配**大幅减少主控
录入操作，支持 Excel 实时写入、365dt 历史同步、NRL Nanny 中继监听。

**纯本地，无任何 AI / LLM / Token / 语音识别依赖，断网可用。**

## 功能

- 快速输入：`bg4tki njqx k6 y 5` → `BG4TKI | 南京栖霞 | 泉盛 UV-K6 | 原 | 5W`
- 字段自由顺序：呼号 / QTH / 设备 / 天线 / 功率 乱序均可
- 拼音缩写：`njqx`→南京栖霞，`ahwh`→安徽芜湖；重名（如 `gl`）给出候选必须选择
- 历史补全：输入呼号自动给出「最近一次 / 最常用」建议，`Tab` 接受，绝不自动提交
- 模糊匹配：错拼/多一字少一字给出候选（阈值可在设置调整）
- SQLite 主数据库，每次提交先 COMMIT 再写 Excel；Excel 失败不影响数据
- Excel 表头自动识别（不写死列），支持「重新同步本场」「导出本场」重建
- 历史 Excel 批量导入（单文件/文件夹）+ 去重
- 365dt 历史同步：**每次启动检查一次**，增量导入
- NRL Nanny 南京中继 Qt WebEngine 内嵌监听（失败自动降级，不影响录入）
- 一键撤销（软删除）、数据库每日备份、崩溃恢复、修改审计
- 悬浮快速录入窗：置顶 / 可拖动 / 可调透明度 / 全局快捷键呼出

## 运行

```bash
pip install -r requirements.txt
python app.py
```

## 快捷键

| 按键 | 功能 |
| ---- | ---- |
| Ctrl+Space | 唤出/隐藏悬浮窗 |
| Enter | 确认录入 |
| Tab | 接受历史建议 |
| Esc | 清空当前输入 |
| Ctrl+Z | 撤销上一条记录 |

## 测试

```bash
python -m unittest discover -s tests -v
```

## 打包 EXE

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name HAM点名助手 --add-data "data;data" app.py
```

首次运行会在项目目录生成 `data/`（SQLite）、`logs/`、`backup/` 与 `config.json`。

## 目录

```
app.py                入口
core/                 Parser / 预测 / 模糊 / 置信度
database/             连接 / 迁移 / 仓库 / 默认词典
normalizers/          呼号/QTH/设备/天线/功率 + 行政区划库
providers/            365dt / Excel 导入
excel/                COM 控制器 / 导出
monitor/              NRL Nanny 监听
services/             应用服务（UI 唯一入口）
ui/                   PySide6 界面
data/ logs/ backup/   运行时数据
tests/                单元测试
```
