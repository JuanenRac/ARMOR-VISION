<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-VISION banner" width="100%">
</p>

# 👁️ ARMOR-VISION

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  🇨🇳 <b>简体中文</b> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### 摄像头的区域、遮罩与检测规则

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.3-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**诚实性检查 - 今天真正能运行的部分:** 区域、运动检查、跟踪、规则和 61 个测试都是真实的。**目前还没有真正的检测模型**，也没有在任何摄像头或 Jetson Orin NX 上运行过：模拟使用的是预设的检测结果。

---

## 📋 速览

| | |
|---|---|
| 版本 | `0.0.3` |
| 成熟度 | 可用 |
| 测试 | 61 (`python -m unittest discover -s tests`) |
| 技术栈 | Python 3.11+ |
| 真实硬件 | 暂无：没有真实的检测器、摄像头或 Jetson（使用脚本化检测的模拟） |

## 🚦 项目状态

每一行是本仓库的一个部分，灯号表示它今天做到了哪一步。内容依据仓库能够展示的证据（测试、构建、运行），而不是计划。

🟢 已完成并验证 · 🟡 可用，有已知限制 · 🟠 部分完成或尚未验证 · 🔴 未完成或不可用

| 领域 | 状态 | 在这里的含义 |
|---|---|---|
| 软件 | 🟡 | 防区、移动检查、跟踪器和规则都能工作，但目前还没有真实的检测模型：模拟使用的是脚本化的检测结果。 |
| 测试 | 🟢 | 61 项测试通过（`python -m unittest discover -s tests`）。 |
| 硬件 | 🔴 | 还没有在摄像头或 Jetson Orin NX 上运行过。 |
| 文档 | 🟢 | 八种语言和更新日志均为最新。 |

## 🎯 概述

* **区域与遮罩：** 用归一化坐标（0 到 1）绘制的多边形，因此同一张图在任何分辨率下都适用；区域统计检测结果，遮罩忽略运动。每个区域有标签过滤、类型（`alert` 或 `detection`）以及以帧数和秒数表示的惰性。
* **先看运动：** 只有当遮罩之外的画面变化足够多时，开销很大的检测器才会运行。
* **跟踪：** 每个物体在画面之间保持身份，静止的物体（停着的汽车）会被记住，不再产生新事件。
* **布防配置：** `away`、`home` 等决定监视哪些区域；未知模式则监视全部。
* **只报告的事件：** 告警或检测始终带有 `authorizes_action: false`；做什么由服务器决定。

## 🧩 在 A.R.M.O.R. 中的角色

ARMOR-VISION 是独立于任何检测器、决定摄像头画面含义的部分：画在上面的区域和遮罩、先于昂贵检测器运行的移动检查、跟踪器、布防配置，以及把检测变成事件的规则。如今观察摄像头的是 [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) 服务；ARMOR-VISION 则为真正的检测模型准备好了规则，等待它的到来。它只报告：事件从不授权任何动作。

## 📂 仓库结构

```text
ARMOR-VISION/
├── src/armor_vision/   geometry, config (zones, masks, profiles), motion, tracker, rules, detector, pipeline, cli
├── tests/              61 tests
├── tools/              the shared CI checks (armor_ci_validate.py, armor_project_tool.py, _armor_readme_parity.py)
└── docs/USAGE.md
```

## 🛠️ 开发环境

**环境要求:** Python 3.11+（仅标准库）

```powershell
$env:PYTHONPATH="src"
python -m armor_vision simulate --mode away
python -m armor_vision check-config my_cameras.json
python -m unittest discover -s tests   # 61 tests
```

```bash
PYTHONPATH=src python -m armor_vision simulate --mode away
PYTHONPATH=src python -m armor_vision check-config my_cameras.json
PYTHONPATH=src python -m unittest discover -s tests   # 61 tests
```

选项与配置格式：[用法](docs/USAGE.md)。

## 🔗 相关项目

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）是由若干独立仓库组成的周界安防系统。每个仓库都有自己的版本、测试和 README；家族成员如下：

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - 消息契约、验证器、一致性向量和生成的类型
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - 适用于 ESP32-S3 的现场节点固件，带三个雷达和自带网页面板
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - 太阳能逆变器与电池的协议，以及网关节点的消息
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - 电气节点：电表、电网读数消息和开关规则
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - 报警节点与报警主机：防区、布防、延时、警笛和 PIN，有无服务器均可
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - 触摸面板：墙面屏幕上的系统状态、布防与确认，以及语音助手的所在
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - 本地网络：其设备、互联网以及变化
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - 中央协调器：遥测、报警、设备、太阳能读数和摄像头
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - 网页控制台：摄像头、雷达、报警、太阳能和 2D/3D 场地设计器
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - 带实时 2D/3D 雷达的 Android 操作员客户端
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone 操作员客户端
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - 会解释决策且从不执行动作的视觉推理策略
* **ARMOR-VISION** (本仓库) - Jetson Orin NX 上的摄像头区域、遮罩与检测规则
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - 带无法伪造确认的离线语音意图
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - 外壳、电子器件和台架验收矩阵
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - 部署、CM5 测试台、备份与 TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - 带可重复故障的离线遥测模拟器
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - 发现、安装并更新生态系统自身的仓库
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - 架构、安全基线和能力矩阵

## 📚 文档与社区

更多阅读：

* [能力矩阵：哪些已被证实，哪些没有](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [项目目录：版本以及各仓库之间的依赖](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [本仓库的变更记录](CHANGELOG.md)
* [许可证（GPL-3.0-or-later）](LICENSE)
* 问题、想法与反馈：electrohobby3d@gmail.com

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 许可证

GPL-3.0-or-later - 见 [LICENSE](LICENSE)。
