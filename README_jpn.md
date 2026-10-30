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
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  🇯🇵 <b>日本語</b> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### カメラのゾーン、マスク、検知ルール

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.4-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**正直さのチェック - 今日動いているもの:** ゾーン、動きの確認、追跡、ルール、61 件のテストは実在します。**実際の検知モデルはまだありません**。カメラや Jetson Orin NX では何も動かしていません。シミュレーションは台本どおりの検知結果を使います。

---

## 📋 ひと目で

| | |
|---|---|
| バージョン | `0.0.4` |
| 成熟度 | 機能する |
| 役割 | カメラのゾーン、マスク、検出ルール（ファミリー：Core Services、親：ARMOR-SERVER） |
| 技術 | Python 3.11+、標準ライブラリのみ |
| テスト | 61 (`python -m unittest discover -s tests`) |
| 動作環境 | 任意のコンピューター |
| 実機での確認 | まだありません：実際の検出器、カメラ、Jetson はなく、スクリプト化した検出によるシミュレーションのみ |
| ライセンス | GPL-3.0-or-later |

**移動先：** [概要](#-概要) · [アーキテクチャ](#-アーキテクチャ) · [セキュリティ](#-セキュリティと安全) · [インターフェース](#-インターフェース) · [設定](#-設定) · [クイックスタート](#-クイックスタート) · [テスト](#-テスト) · [トラブルシューティング](#-トラブルシューティング) · [構成](#-リポジトリの構成) · [関連](#-関連プロジェクト)

## 🚦 プロジェクトの状況

各行はこのリポジトリの一部分で、信号は今日どこまで進んでいるかを示します。計画ではなく、リポジトリが示せるもの（テスト、ビルド、実行）に基づいて書かれています。

🟢 完了・検証済み · 🟡 動作する（既知の制限あり） · 🟠 一部のみ、または未検証 · 🔴 未実装または動作しない

| 領域 | 状態 | ここでの意味 |
|---|---|---|
| ソフトウェア | 🟡 | ゾーン、動きの確認、トラッカー、規則は動作しますが、実際の検出モデルはまだありません。シミュレーションはスクリプト化した検出結果を使います。 |
| テスト | 🟢 | 61 件のテストが通ります（`python -m unittest discover -s tests`）。 |
| ハードウェア | 🔴 | カメラや Jetson Orin NX ではまだ何も動かしていません。 |
| ドキュメント | 🟢 | 8 言語と変更履歴は最新です。 |

## 🎯 概要

* **ゾーンとマスク:** 正規化座標（0 から 1）で描いた多角形なので、同じ図がどの解像度でも使えます。ゾーンは検知を数え、マスクは動きを無視します。各ゾーンにはラベルのフィルター、種類（`alert` または `detection`）、画像数と秒数の慣性があります。
* **まず動き:** 高価な検知器は、マスクの外で画面が十分に変化したときだけ動きます。
* **追跡:** 各物体は画像間で同一性を保ち、止まっているもの（駐車中の車）は記憶されて新しいイベントを出しません。
* **警戒プロファイル:** `away`、`home` などが監視するゾーンを選びます。未知のモードはすべてを監視します。
* **報告するだけのイベント:** 警報や検知には常に `authorizes_action: false` が付き、何をするかはサーバーが決めます。

## 🧩 A.R.M.O.R. での役割

ARMOR-VISION は、検出器とは別に、カメラの映像が何を意味するかを決める部分です。映像に描くゾーンとマスク、高価な検出器の前に走る動き検査、トラッカー、警戒プロファイル、検出をイベントに変えるルール。現在カメラを見張っているのは [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) で、ARMOR-VISION は実際の検出モデルのためのルールを用意して待っています。報告するだけで、イベントが動作を認可することはありません。

| 名前 | 方法 | 用途 |
|---|---|---|
| ARMOR-SERVER-AI | モデルができたら同じルールを使う | 現在カメラを監視する |
| ARMOR-SERVER | `armor.vision.event/v1` | イベントの扱いを決める（ARMOR-COMMON のコントラクトにはまだ含まれない） |

## 🏛️ アーキテクチャ

<p align="center">
  <img src="images/architecture.svg" alt="ARMOR-VISION のアーキテクチャ：呼び出し元、内部、依存先" width="100%">
</p>

## 🔒 セキュリティと安全

| 脅威 | 対策 |
|---|---|
| ルールエンジンが勝手に動く | すべてのイベントに `authorizes_action: false`（スキーマ `armor.vision.event/v1`）が付き、決めるのはサーバーです |
| カメラ設定の誤り | `check-config` はすべての問題を列挙し、1 つでもあれば何も受け付けません。座標は 0〜1、ゾーンは `alert` か `detection`、未知のフィールドはエラーです |
| 高コストな検出器が無駄に動く | まず動き判定：マスク外で 16 x 9 グリッドの十分なセルが変化したときだけ検出器を呼びます |
| 駐車中の車が何度もイベントを出す | トラッカーは静止物（3 秒で 0.01 未満の移動）を 300 秒覚え、新しいイベントを出しません |
| 未知の警戒モード | すべてのゾーンを監視します。プロファイルのない `disarmed` だけが `alert` ゾーンを止め、`detection` ゾーンは記録を続けます |

ここにある機能は安全機能ではありません。実際の検出モデルはまだありません。

## 🔌 インターフェース

| 名前 | 設定内容 |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | 組み込みシナリオ（私道を横切る人、駐車中の車、マスクした木の陰の動き）を実行し、イベントごとに JSON 1 行と、最後にカウンターの行を出力します |
| `python -m armor_vision check-config FILE` | 設定を検証してすべての問題を表示します。終了コード 0 正常、1 不正、2 読み取り不可 |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

ライブラリとして：`parse_config`、`Pipeline.process_detections`、`process_frame`。`load_detector("tensorrt")` は Jetson Orin NX 用のモデルが未実装のため `DetectorUnavailable` を送出します。[docs/USAGE.md](docs/USAGE.md) を参照。

## ⚙️ 設定

| 名前 | 設定内容 |
|---|---|
| `motion_threshold` | 1〜255：変化とみなす濃淡差 |
| `motion_min_cells` | 検出器を呼ぶ前に変化が必要な 16 x 9 グリッドのセル数 |
| `zones[]` | `id`、`name`、`kind`（`alert` または `detection`）、`labels`、`min_frames`、`min_seconds`、`points`（多角形、0〜1）。ボックスの足元で判定 |
| `masks[]` | 動きを無視する多角形。中心が内側にある検出は破棄されます |
| `profiles` | 警戒モードごとに監視するゾーン（`away`、`home` など） |

| 制限 | 値 |
|---|---|
| 検出とトラックの対応付け（重なり／到達範囲） | 0.3 / 1.0 |
| 動いているトラックが見えなくなって破棄されるまで | 2 s |
| 静止：判定窓／ずれ／保持時間 | 3 s / 0.01 / 300 s |
| 動き判定グリッド | 16 x 9 |

これらの値は現在 `tracker.py` と `motion.py` の定数です。設定ファイルにはゾーン、マスク、プロファイル、動きのしきい値があります。

## 🚀 クイックスタート

**必要なもの:** Python 3.11+（標準ライブラリのみ）。

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

## 🧪 テスト

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| テストファイル | テスト数 | 対象 |
|---|---|---|
| `test_vision.py` | 42 | 幾何、設定、動き、トラッカー、ルール、プロファイル、全体の流れ、コマンドライン |
| `test_vision_edges.py` | 19 | 境界条件：不正な設定、静止物、マスクされた検出、利用できない検出器 |

## 🏗️ ビルドとリリース

純粋な Python なのでコンパイルは不要です。バージョンは `pyproject.toml` と `armor.project.json` にあります。

## 🩺 トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `check-config` が終了コード 1 | 設定に問題があり、すべて表示される | すべて直す（未知のフィールドもエラー） |
| `check-config` が終了コード 2 | ファイルを読み取れない | パスと JSON 形式を確認する |
| `DetectorUnavailable` | `load_detector("tensorrt")`：実モデルは未実装 | `ScriptedDetector` を使う |
| ゾーンが反応しない | 足元がポリゴン外、ラベルが非対象、マスクで隠れている、またはそのモードのプロファイルにゾーンがない | 同じファイルとモードで `simulate` を実行 |

## 📂 リポジトリの構成

<p align="center">
  <img src="images/repository-structure.svg" alt="ARMOR-VISION のリポジトリ構造" width="100%">
</p>

<details>
<summary>ツリーのテキスト版</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      正規化座標の多角形
│   ├── config.py                        ゾーン、マスク、プロファイルとその検証
│   ├── motion.py                        16 x 9 の動き判定（マスクは無視）
│   ├── detector.py                      スクリプト化した検出。実モデルは未実装
│   ├── tracker.py                       画像間の識別、静止物
│   ├── rules.py                         ゾーンからイベントへ：armor.vision.event/v1
│   └── pipeline.py cli.py __main__.py   全体の流れとコマンドライン
├── tests/                               テスト
├── docs/                                このリポジトリのガイド
├── tools/                               共通の CI チェックとプロジェクトツール
├── .github/                             CI ワークフローと Issue・Pull Request のテンプレート
├── images/                              バナー、アイコン、この README の 2 つの図
├── build.sh build.bat                   共通のプロジェクトワークフローでビルド
├── test.sh test.bat                     共通のワークフローでテストを実行
├── run.sh run.bat                       共通のプロジェクトワークフローで起動
├── armor.project.json                   マニフェスト：バージョン、役割、成熟度、ビルドコマンド
├── CHANGELOG.md                         各バージョンの変更点
├── SECURITY.md SUPPORT.md LICENSE       セキュリティポリシー、サポート、ライセンス
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   貢献方法と行動規範
├── build-test.sh build-test.bat         共通のワークフローでテストを実行
├── pyproject.toml                       パッケージのメタデータ
└── .gitattributes .gitignore            Git の設定
```

</details>

## 🗺️ ロードマップと既知の制限

**現時点の既知の制限**

* 実際の検出モデルはまだなく、カメラや Jetson Orin NX では何も動いていません。シミュレーションはスクリプト化した検出を使います。
* イベントはまだ ARMOR-COMMON のコントラクトに含まれていません。
* トラッカーと動き判定の値は設定ファイルではなくコード内の定数です。

**今後**

* Jetson Orin NX 用の検出モデルを書き、実際のカメラで試す。
* トラッカーと動き判定の定数を設定ファイルへ移し、イベントを ARMOR-COMMON のコントラクトに入れる。

## 🌍 言語

README とテキストは、英語、スペイン語、フランス語、イタリア語、ドイツ語、中国語、日本語、ヨーロッパポルトガル語で提供されています。

## 🔗 関連プロジェクト

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）は、独立したリポジトリで構成される境界セキュリティシステムです。各リポジトリは独自のバージョン、テスト、README を持ちます。ファミリーは次のとおりです：

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - メッセージのコントラクト、バリデーター、適合ベクトル、生成された型
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - 3 つのレーダーと独自の Web パネルを備えた ESP32-S3 向けフィールドノードのファームウェア
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - ソーラーインバーターとバッテリーのプロトコル、ゲートウェイノードのメッセージ
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - 電気ノード：メーター、系統の読み取り値のメッセージ、切り替えのルール
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - 警報ノードとパネル：ゾーン、警戒、遅延、サイレン、PIN。サーバーありでもなしでも動作
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - タッチパネル：壁面画面でのシステムの状態、警戒と確認応答、そして音声アシスタントの置き場
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - ローカルネットワーク：そのデバイス、インターネット、そして変化
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - 中央コーディネーター：テレメトリ、警報、デバイス、ソーラーの読み取り値、カメラ
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web コンソール：カメラ、レーダー、警報、太陽光エネルギー、2D/3D のサイトデザイナー
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - ライブの 2D/3D レーダーを備えた Android オペレータークライアント
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone オペレータークライアント
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - 判断を説明し、決して作動させない視覚推論ポリシー
* **ARMOR-VISION**（このリポジトリ） - Jetson Orin NX 向けのカメラゾーン、マスク、検出ルール
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - 偽造できない確認つきのオフライン音声インテント
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - 筐体、電子回路、ベンチ受け入れマトリクス
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - デプロイ、CM5 テストベンチ、バックアップ、TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - 再現可能な障害を持つオフラインのテレメトリシミュレーター
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - エコシステム自身のリポジトリを検出、インストール、更新
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - アーキテクチャ、セキュリティのベースライン、機能マトリクス

## 📚 ドキュメント

* [使い方](docs/USAGE.md)：コマンド、設定、イベント、ライブラリ
* [機能マトリクス：何が証明され、何が証明されていないか](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [プロジェクトカタログ：バージョンと、リポジトリ同士の依存関係](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [このリポジトリの変更履歴](CHANGELOG.md)

## 🤝 コントリビュートとコミュニティ

* Pull Request の前に `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` を実行してください。通る必要があります。[CONTRIBUTING.md](CONTRIBUTING.md) と[行動規範](CODE_OF_CONDUCT.md)を参照してください。
* README は 8 言語で提供され、ARMOR-DOCS のソースから生成されます。文面の変更はそちらで行います。
* コンポーネント間のメッセージの変更は ARMOR-COMMON から始めます。
* ビルドしただけのものを、ボード上で動いているかのように書かないでください。
* 脆弱性は非公開で報告してください：[SECURITY.md](SECURITY.md)。質問、アイデア、報告：electrohobby3d@gmail.com（[SUPPORT.md](SUPPORT.md)）。

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 ライセンス

GPL-3.0-or-later - [LICENSE](LICENSE) を参照してください。
