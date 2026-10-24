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
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  🇵🇹 <b>Português</b>
</p>

### Zonas, máscaras e regras de deteção para as câmaras

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.3-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**Verificação de honestidade - o que funciona hoje:** As zonas, a verificação de movimento, o seguidor, as regras e os 61 testes são reais. **Ainda não há nenhum modelo detetor real** e nada correu numa câmara nem no Jetson Orin NX: a simulação usa deteções com guião.

---

## 📋 Num relance

| | |
|---|---|
| Versão | `0.0.3` |
| Maturidade | Funcional |
| Testes | 61 (`python -m unittest discover -s tests`) |
| Tecnologia | Python 3.11+ |
| Em hardware real | Nenhum ainda: nem detetor real, nem câmara, nem Jetson (uma simulação com deteções guionizadas) |

## 🚦 Estado do projeto

Cada linha é uma parte deste repositório e a luz diz até onde chega hoje. É escrita com o que o repositório consegue demonstrar (testes, compilações, execuções), não com o que está previsto.

🟢 Feito e verificado · 🟡 Funciona, com limites conhecidos · 🟠 Feito a meio ou ainda por verificar · 🔴 Por fazer ou a não funcionar

| Área | Estado | O que significa aqui |
|---|---|---|
| Software | 🟡 | As zonas, a verificação de movimento, o seguimento e as regras funcionam, mas ainda não há um modelo detetor real: a simulação usa deteções com guião. |
| Testes | 🟢 | Passam 61 testes (`python -m unittest discover -s tests`). |
| Hardware | 🔴 | Nada funcionou numa câmara nem no Jetson Orin NX. |
| Documentação | 🟢 | Oito idiomas e o registo de alterações estão atualizados. |

## 🎯 Visão geral

* **Zonas e máscaras:** polígonos desenhados em coordenadas normalizadas (0 a 1), para que um só desenho funcione em qualquer resolução; uma zona conta deteções, uma máscara ignora o movimento. Cada zona tem um filtro de etiquetas, um tipo (`alert` ou `detection`) e uma inércia em imagens e segundos.
* **Primeiro o movimento:** o detetor caro só corre quando mudou o suficiente da imagem, fora das máscaras.
* **Um seguidor:** cada objeto mantém a sua identidade entre imagens, e o que está parado (um carro estacionado) é lembrado e não gera eventos novos.
* **Perfis de armação:** `away`, `home` e semelhantes escolhem que zonas se vigiam; um modo desconhecido vigia tudo.
* **Eventos que só reportam:** um alerta ou uma deteção leva sempre `authorizes_action: false`; o servidor decide o que fazer.

## 🧩 Papel no A.R.M.O.R.

O ARMOR-VISION é a parte que decide o que significa a imagem de uma câmara, à parte de qualquer detetor: as zonas e máscaras desenhadas nela, a verificação de movimento que corre antes do detetor dispendioso, o seguidor, os perfis de armar e as regras que transformam deteções em eventos. O [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) é o serviço que hoje vigia as câmaras; o ARMOR-VISION é onde as regras para um modelo de deteção real estão prontas, à sua espera. Só comunica: os eventos nunca autorizam uma ação.

## 📂 Estrutura do repositório

```text
ARMOR-VISION/
├── src/armor_vision/   geometry, config (zones, masks, profiles), motion, tracker, rules, detector, pipeline, cli
├── tests/              61 tests
├── tools/              the shared CI checks (armor_ci_validate.py, armor_project_tool.py, _armor_readme_parity.py)
└── docs/USAGE.md
```

## 🛠️ Ambiente de desenvolvimento

**Requisitos:** Python 3.11+ (apenas a biblioteca padrão)

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

Opções e formato de configuração: [utilização](docs/USAGE.md).

## 🔗 Projetos relacionados

O **A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) é um sistema de segurança perimetral feito de repositórios independentes. Cada um tem a sua própria versão, os seus próprios testes e o seu próprio README; esta é a família:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratos de mensagens, validadores, vetores de conformidade e tipos gerados
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware de nó de campo para ESP32-S3 com três radares e o seu próprio painel web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolos de inversores e baterias solares e as mensagens de um nó de ligação
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nó elétrico: contadores, a mensagem das leituras da rede e as regras de comutação
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nó e central de alarme: zonas, armar, atrasos, sirene e PIN, com o servidor ou sem ele
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Painel tátil: o estado do sistema num ecrã de parede, armar e reconhecer, e a casa do assistente de voz
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - A rede local: os seus dispositivos, a internet e o que muda
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordenador central: telemetria, alarmes, dispositivos, leituras solares e câmaras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Consola web: câmaras, radar, alarmes, energia solar e o desenhador de local 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Cliente Android de operador com um radar 2D/3D em direto
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Cliente de operador para iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Política de inferência visual que explica as suas decisões e nunca atua
* **ARMOR-VISION** (este repositório) - Zonas de câmara, máscaras e regras de deteção para o Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenções de voz offline com uma confirmação que não se pode falsificar
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Caixas, eletrónica e a matriz de aceitação de bancada
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Implementação, a bancada de testes CM5, cópias de segurança e TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - Simulador de telemetria offline com falhas repetíveis
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Deteta, instala e atualiza os próprios repositórios do ecossistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Arquitetura, linha de base de segurança e a matriz de capacidades

## 📚 Documentação e comunidade

Onde ler mais:

* [Matriz de capacidades: o que está provado e o que não](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catálogo de projetos: versões e como os repositórios dependem uns dos outros](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Registo de alterações deste repositório](CHANGELOG.md)
* [Licença (GPL-3.0-or-later)](LICENSE)
* Perguntas, ideias e relatórios: electrohobby3d@gmail.com

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENÇA

GPL-3.0-or-later - veja [LICENSE](LICENSE).
