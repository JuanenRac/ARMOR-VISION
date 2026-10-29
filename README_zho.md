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
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.3-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**诚实性检查 - 今天真正能运行的部分：** 区域、运动检查、跟踪、规则和 61 个测试都是真实的。**目前还没有真正的检测模型**，也没有在任何摄像头或 Jetson Orin NX 上运行过：模拟使用的是预设的检测结果。

---

## 📋 速览

| | |
|---|---|
| 版本 | `0.0.3` |
| 成熟度 | 可用 |
| 角色 | 摄像头区域、遮罩和检测规则（家族：Core Services，上级：ARMOR-SERVER） |
| 技术栈 | Python 3.11+，仅标准库 |
| 测试 | 61 (`python -m unittest discover -s tests`) |
| 运行位置 | 任何计算机 |
| 真实硬件 | 暂无：没有真实的检测器、摄像头或 Jetson（使用脚本化检测的模拟） |
| 许可证 | GPL-3.0-or-later |

**跳转到：** [概述](#-概述) · [架构](#-架构) · [安全](#-安全与防护) · [接口](#-接口) · [配置](#-配置) · [快速开始](#-快速开始) · [测试](#-测试) · [故障排除](#-故障排除) · [结构](#-仓库结构) · [相关项目](#-相关项目)

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

| 名称 | 方式 | 用途 |
|---|---|---|
| ARMOR-SERVER-AI | 有模型后使用同样的规则 | 目前负责监视摄像头 |
| ARMOR-SERVER | `armor.vision.event/v1` | 决定如何处理事件（尚未纳入 ARMOR-COMMON 合约） |

## 🏛️ 架构

<p align="center">
  <img src="images/architecture.svg" alt="ARMOR-VISION 的架构：谁调用它、它包含什么、它依赖什么" width="100%">
</p>

## 🔒 安全与防护

| 威胁 | 防御 |
|---|---|
| 规则引擎自行行动 | 每个事件都带有 `authorizes_action: false`（模式 `armor.vision.event/v1`）；由服务器决定 |
| 错误的摄像头配置 | `check-config` 会列出所有问题，只要有一个问题就不接受任何配置；坐标为 0 到 1，区域为 `alert` 或 `detection`，未知字段视为错误 |
| 耗资源的检测器无故运行 | 先检测运动：只有遮罩之外 16 x 9 网格中足够多的单元发生变化，才会调用检测器 |
| 停放的汽车不断触发事件 | 跟踪器会记住静止物体（3 秒内漂移小于 0.01）300 秒，不再产生新事件 |
| 未知的布防模式 | 监视所有区域；只有没有配置文件的 `disarmed` 会让 `alert` 区域静默，`detection` 区域仍会记录 |

这里没有任何安全功能：目前还没有真实的检测模型。

## 🔌 接口

| 名称 | 作用 |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | 运行内置场景（有人穿过车道、停放的汽车、被遮罩的树后有动静），每个事件输出一行 JSON，最后输出计数器 |
| `python -m armor_vision check-config FILE` | 校验配置并输出所有问题；退出码 0 正常、1 无效、2 无法读取 |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

作为库使用：`parse_config`、`Pipeline.process_detections` 和 `process_frame`。调用 `load_detector("tensorrt")` 会抛出 `DetectorUnavailable`，因为 Jetson Orin NX 的模型尚未编写。参见 [docs/USAGE.md](docs/USAGE.md)。

## ⚙️ 配置

| 名称 | 作用 |
|---|---|
| `motion_threshold` | 1 到 255：被视为变化的灰度差 |
| `motion_min_cells` | 调用检测器前必须变化的 16 x 9 网格单元数 |
| `zones[]` | `id`、`name`、`kind`（`alert` 或 `detection`）、`labels`、`min_frames`、`min_seconds`、`points`（多边形，0 到 1）；按框的脚部计数 |
| `masks[]` | 忽略运动的多边形；中心位于其中的检测会被丢弃 |
| `profiles` | 每种布防模式下监视哪些区域（`away`、`home` 等） |

| 限制 | 值 |
|---|---|
| 检测与轨迹的匹配（重叠／范围） | 0.3 / 1.0 |
| 移动轨迹未被看到则在此时间后丢弃 | 2 s |
| 静止：窗口／漂移／记忆时长 | 3 s / 0.01 / 300 s |
| 运动网格 | 16 x 9 |

这些值目前是 `tracker.py` 和 `motion.py` 中的常量；配置文件包含区域、遮罩、配置文件和运动阈值。

## 🚀 快速开始

**要求:** Python 3.11+（仅标准库）。

```powershell
$env:PYTHONPATH = "src"
python -m armor_vision simulate --mode away
python -m armor_vision check-config my_cameras.json
python -m unittest discover -s tests   # 61 tests
```

```bash
PYTHONPATH=src python -m armor_vision simulate --mode away
PYTHONPATH=src python -m armor_vision check-config my_cameras.json
PYTHONPATH=src python -m unittest discover -s tests   # 61 tests
```

## 🧪 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| 测试文件 | 测试数 | 覆盖内容 |
|---|---|---|
| `test_vision.py` | 42 | 几何、配置、运动、跟踪、规则、配置文件、流程和命令行 |
| `test_vision_edges.py` | 19 | 边界情况：错误配置、静止物体、被遮罩的检测以及不可用的检测器 |

## 🏗️ 构建与发布

纯 Python：无需编译。版本在 `pyproject.toml` 和 `armor.project.json` 中。

## 🩺 故障排除

| 现象 | 原因 | 处理 |
|---|---|---|
| `check-config` 退出码为 1 | 配置有问题，会逐条列出 | 全部修正：未知字段也算错误 |
| `check-config` 退出码为 2 | 无法读取文件 | 检查路径以及是否为 JSON |
| `DetectorUnavailable` | `load_detector("tensorrt")`：真实模型尚未编写 | 使用 `ScriptedDetector` |
| 区域从不触发 | 脚部在多边形之外、标签不被接受、被遮罩挡住，或该模式的配置文件不含此区域 | 用同样的文件和模式运行 `simulate` |

## 📂 仓库结构

<p align="center">
  <img src="images/repository-structure.svg" alt="ARMOR-VISION 的仓库结构" width="100%">
</p>

<details>
<summary>目录树的文本版</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      归一化坐标的多边形
│   ├── config.py                        区域、遮罩、配置文件及其校验
│   ├── motion.py                        16 x 9 运动检测（忽略遮罩）
│   ├── detector.py                      脚本化检测；真实模型尚未编写
│   ├── tracker.py                       跨画面的身份；静止物体
│   ├── rules.py                         从区域到事件：armor.vision.event/v1
│   └── pipeline.py cli.py __main__.py   整个流程与命令行
├── tests/                               测试
├── docs/                                本仓库的指南
├── tools/                               共享的 CI 检查和项目工具
├── .github/                             CI 工作流以及 Issue 和 Pull Request 模板
├── images/                              横幅、图标和本 README 的两幅图
├── build.sh build.bat                   通过共享的项目工作流构建
├── test.sh test.bat                     通过共享工作流运行测试
├── run.sh run.bat                       通过共享的项目工作流启动
├── armor.project.json                   清单：版本、角色、成熟度、构建命令
├── CHANGELOG.md                         每个版本的变化
├── SECURITY.md SUPPORT.md LICENSE       安全策略、支持和许可证
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   如何贡献与行为准则
├── build-test.sh build-test.bat         通过共享工作流运行测试
├── pyproject.toml                       包元数据
└── .gitattributes .gitignore            Git 设置
```

</details>

## 🗺️ 路线图与已知限制

**目前已知的限制**

* 目前还没有真实的检测模型，也没有在摄像头或 Jetson Orin NX 上运行过：模拟使用脚本化的检测。
* 该事件尚未纳入 ARMOR-COMMON 合约。
* 跟踪与运动的数值是代码中的常量，不在配置文件中。

**下一步**

* 为 Jetson Orin NX 编写检测模型，并用真实摄像头试验。
* 把跟踪与运动常量移到配置文件，并将该事件纳入 ARMOR-COMMON 合约。

## 🌍 语言

README 和文本提供英语、西班牙语、法语、意大利语、德语、汉语、日语和欧洲葡萄牙语版本。

## 🔗 相关项目

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）是一个由相互独立的仓库组成的周界安全系统。每个仓库都有自己的版本、自己的测试和自己的 README；这是整个系列：

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - 消息契约、验证器、一致性向量和生成的类型
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - 面向 ESP32-S3 的现场节点固件，配三个雷达和自带的网页面板
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - 太阳能逆变器和电池的协议，以及网关节点的消息
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - 电气节点：电表、电网读数的消息和切换规则
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - 报警节点与面板：防区、布防、延时、警笛和 PIN，可配合服务器也可独立使用
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - 触摸面板：壁挂屏幕上的系统状态、布防与确认，以及语音助手的所在
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - 本地网络：其设备、互联网以及变化
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - 中央协调器：遥测、报警、设备、太阳能读数和摄像头
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - 网页控制台：摄像头、雷达、报警、太阳能以及 2D/3D 场地设计器
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - 带实时 2D/3D 雷达的 Android 操作员客户端
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone 操作员客户端
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - 视觉推理策略，会解释其决策且从不驱动设备
* **ARMOR-VISION**（本仓库） - 面向 Jetson Orin NX 的摄像头区域、遮罩和检测规则
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - 离线语音意图，附带无法伪造的确认
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - 外壳、电子器件和台架验收矩阵
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - 部署、CM5 测试台、备份和 TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - 带可重复故障的离线遥测模拟器
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - 检测、安装和更新生态系统自身的仓库
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - 架构、安全基线和能力矩阵

## 📚 文档

* [用法](docs/USAGE.md)：命令、配置、事件和库
* [能力矩阵：哪些已被证明，哪些没有](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [项目目录：版本以及各仓库之间如何相互依赖](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [本仓库的更新日志](CHANGELOG.md)

## 🤝 参与贡献与社区

* 提交 Pull Request 之前请运行 `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`：必须通过。参见 [CONTRIBUTING.md](CONTRIBUTING.md) 和[行为准则](CODE_OF_CONDUCT.md)。
* README 提供八种语言，由 ARMOR-DOCS 中的源文件生成：文本的修改在那里进行。
* 组件之间消息的变更从 ARMOR-COMMON 开始。
* 不要把仅仅构建过的东西描述为已在板子上运行。
* 请私下报告漏洞：[SECURITY.md](SECURITY.md)。问题、想法和报告：electrohobby3d@gmail.com（[SUPPORT.md](SUPPORT.md)）。

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 许可证

GPL-3.0-or-later - 见 [LICENSE](LICENSE)。
