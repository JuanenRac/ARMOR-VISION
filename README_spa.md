<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="Banner de ARMOR-VISION" width="100%">
</p>

# 👁️ ARMOR-VISION

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  🇪🇸 <b>Español</b> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Zonas, máscaras y reglas de detección para las cámaras

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 o posterior">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Lenguaje">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Pruebas">
  <img src="https://img.shields.io/badge/Version-0.0.3-0f6cbd.svg" alt="Versión">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Madurez">
</p>

---

**Comprobación de honestidad - qué funciona hoy:** Las zonas, la comprobación de movimiento, el seguimiento, las reglas y los 61 tests son reales. **Todavía no existe un modelo de detección real** y nada se ha ejecutado en una cámara ni en la Jetson Orin NX: la simulación usa detecciones guionizadas.

---

## 📋 De un vistazo

| | |
|---|---|
| Versión | `0.0.3` |
| Madurez | Funcional |
| Función | Zonas, máscaras y reglas de detección de cámaras (familia: Core Services, padre: ARMOR-SERVER) |
| Tecnología | Python 3.11+, solo biblioteca estándar |
| Pruebas | 61 (`python -m unittest discover -s tests`) |
| Funciona en | Cualquier ordenador |
| En hardware real | Ninguno todavía: ni detector real, ni cámara ni Jetson (una simulación con detecciones guionizadas) |
| Licencia | GPL-3.0-or-later |

**Ir a:** [Resumen](#-resumen) · [Arquitectura](#-arquitectura) · [Seguridad](#-seguridad-y-protección) · [Interfaces](#-interfaces) · [Configuración](#-configuración) · [Inicio rápido](#-inicio-rápido) · [Pruebas](#-pruebas) · [Problemas](#-resolución-de-problemas) · [Estructura](#-estructura-del-repositorio) · [Relacionados](#-proyectos-relacionados)

## 🚦 Estado del proyecto

Cada línea es una parte de este repositorio y la luz dice hasta dónde llega hoy. Está escrito con lo que el repositorio puede demostrar (pruebas, compilaciones, ejecuciones), no con lo que está planeado.

🟢 Hecho y verificado · 🟡 Funciona, con límites conocidos · 🟠 Parcial o sin verificar todavía · 🔴 No hecho o no funciona

| Área | Estado | Qué significa aquí |
|---|---|---|
| Software | 🟡 | Las zonas, la comprobación de movimiento, el seguimiento y las reglas funcionan, pero aún no hay un modelo detector real: la simulación usa detecciones guionizadas. |
| Pruebas | 🟢 | Pasan 61 pruebas (`python -m unittest discover -s tests`). |
| Hardware | 🔴 | Nada ha funcionado en una cámara ni en la Jetson Orin NX. |
| Documentación | 🟢 | Ocho idiomas y el historial de cambios están al día. |

## 🎯 Resumen

* **Zonas y máscaras:** polígonos dibujados en coordenadas normalizadas (de 0 a 1), así un mismo dibujo vale a cualquier resolución; una zona cuenta detecciones, una máscara ignora el movimiento. Cada zona tiene un filtro de etiquetas, un tipo (`alert` o `detection`) y una inercia en fotogramas y segundos.
* **Primero el movimiento:** el detector, que es caro, solo se ejecuta cuando ha cambiado lo bastante de la imagen fuera de las máscaras.
* **Un seguimiento:** cada objeto conserva su identidad entre imágenes, y lo que está quieto (un coche aparcado) se recuerda y no genera eventos nuevos.
* **Perfiles de armado:** `away`, `home` y similares eligen qué zonas se vigilan; un modo desconocido vigila todo.
* **Eventos que solo informan:** una alerta o una detección lleva siempre `authorizes_action: false`; el servidor decide qué hacer.

## 🧩 Papel en A.R.M.O.R.

ARMOR-VISION es la parte que decide qué significa la imagen de una cámara, al margen de cualquier detector: las zonas y máscaras dibujadas sobre ella, la comprobación de movimiento que corre antes del detector costoso, el seguidor, los perfiles de armado y las reglas que convierten detecciones en eventos. [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) es el servicio que vigila hoy las cámaras; ARMOR-VISION es donde las reglas para un modelo de detección real están listas, esperándolo. Solo informa: los eventos nunca autorizan una acción.

| Nombre | Cómo | Para qué |
|---|---|---|
| ARMOR-SERVER-AI | las mismas reglas, cuando haya un modelo | Vigila las cámaras hoy |
| ARMOR-SERVER | `armor.vision.event/v1` | Decide qué hacer con un evento (aún no forma parte del contrato de ARMOR-COMMON) |

## 🏛️ Arquitectura

<p align="center">
  <img src="images/architecture.svg" alt="Arquitectura de ARMOR-VISION: quién lo llama, qué contiene y de qué depende" width="100%">
</p>

## 🔒 Seguridad y protección

| Amenaza | Defensa |
|---|---|
| El motor de reglas actúa por su cuenta | Todo evento lleva `authorizes_action: false` (esquema `armor.vision.event/v1`); decide el servidor |
| Una configuración de cámara errónea | `check-config` lista todos los problemas y uno solo impide aceptar nada; las coordenadas van de 0 a 1, una zona es `alert` o `detection`, los campos desconocidos son errores |
| El detector costoso se ejecuta sin motivo | Primero el movimiento: el detector solo se consulta si cambian suficientes celdas de la rejilla 16 x 9 fuera de las máscaras |
| Un coche aparcado genera evento tras evento | El seguimiento recuerda lo que está quieto (deriva menor de 0,01 en 3 s) durante 300 s y no genera eventos nuevos |
| Un modo de armado desconocido | Se vigilan todas las zonas; solo `disarmed` sin perfil silencia las zonas `alert` y las `detection` siguen registrando |

Nada de esto es una función de seguridad: aún no hay un modelo de detección real.

## 🔌 Interfaces

| Nombre | Qué define |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | Ejecuta un escenario integrado (una persona cruza un camino, un coche aparcado, movimiento tras un árbol enmascarado) e imprime una línea JSON por evento y una última con los contadores |
| `python -m armor_vision check-config FILE` | Valida una configuración e imprime cada problema; salida 0 correcta, 1 inválida, 2 ilegible |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

Como biblioteca: `parse_config`, `Pipeline.process_detections` y `process_frame`. Pedir `load_detector("tensorrt")` lanza `DetectorUnavailable` porque el modelo para la Jetson Orin NX no está escrito. Consulta [docs/USAGE.md](docs/USAGE.md).

## ⚙️ Configuración

| Nombre | Qué define |
|---|---|
| `motion_threshold` | 1 a 255: la diferencia de gris que cuenta como cambio |
| `motion_min_cells` | Cuántas celdas de la rejilla 16 x 9 deben cambiar antes de consultar al detector |
| `zones[]` | `id`, `name`, `kind` (`alert` o `detection`), `labels`, `min_frames`, `min_seconds`, `points` (polígono, 0 a 1); se cuenta por los pies de la caja |
| `masks[]` | Polígonos donde se ignora el movimiento; se descartan las detecciones cuyo centro está dentro |
| `profiles` | Qué zonas se vigilan en cada modo de armado (`away`, `home`, ...) |

| Límite | Valor |
|---|---|
| Emparejado de una detección con una pista (solape / alcance) | 0.3 / 1.0 |
| Una pista en movimiento no vista se descarta tras | 2 s |
| Quieto: ventana / deriva / se recuerda durante | 3 s / 0.01 / 300 s |
| Rejilla de movimiento | 16 x 9 |

Hoy estos valores son constantes de `tracker.py` y `motion.py`; el fichero de configuración contiene las zonas, máscaras, perfiles y los umbrales de movimiento.

## 🚀 Inicio rápido

**Requisitos:** Python 3.11+ (solo biblioteca estándar).

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

## 🧪 Pruebas

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Fichero de pruebas | Pruebas | Qué cubre |
|---|---|---|
| `test_vision.py` | 42 | Geometría, configuración, movimiento, seguimiento, reglas, perfiles, la cadena y la línea de órdenes |
| `test_vision_edges.py` | 19 | Los bordes: configuraciones erróneas, objetos quietos, detecciones enmascaradas y el detector no disponible |

## 🏗️ Compilación y publicación

Es Python puro: no hay nada que compilar. La versión vive en `pyproject.toml` y `armor.project.json`.

## 🩺 Resolución de problemas

| Ves | Porque | Haz |
|---|---|---|
| `check-config` termina con 1 | La configuración tiene problemas; los lista todos | Corrígelos todos: los campos desconocidos son errores |
| `check-config` termina con 2 | No se puede leer el fichero | Comprueba la ruta y que sea JSON |
| `DetectorUnavailable` | `load_detector("tensorrt")`: el modelo real no está escrito | Usa `ScriptedDetector` |
| Una zona nunca salta | Los pies están fuera del polígono, la etiqueta no se acepta, una máscara la oculta, o el modo no tiene un perfil con esa zona | Ejecuta `simulate` con el mismo fichero y modo |

## 📂 Estructura del repositorio

<p align="center">
  <img src="images/repository-structure.svg" alt="Estructura del repositorio de ARMOR-VISION" width="100%">
</p>

<details>
<summary>Versión en texto del árbol</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      polígonos en coordenadas normalizadas
│   ├── config.py                        zonas, máscaras, perfiles y su validación
│   ├── motion.py                        la comprobación de movimiento 16 x 9, máscaras ignoradas
│   ├── detector.py                      detecciones guionizadas; el modelo real no está escrito
│   ├── tracker.py                       identidad entre imágenes; objetos quietos
│   ├── rules.py                         de zonas a eventos: armor.vision.event/v1
│   └── pipeline.py cli.py __main__.py   toda la cadena y la línea de órdenes
├── tests/                               las pruebas
├── docs/                                las guías de este repositorio
├── tools/                               las comprobaciones de CI compartidas y las herramientas del proyecto
├── .github/                             flujo de CI y plantillas de issues y pull requests
├── images/                              banner, icono y las dos imágenes de este README
├── build.sh build.bat                   compilar con el flujo de proyecto compartido
├── test.sh test.bat                     ejecutar las pruebas con el flujo compartido
├── run.sh run.bat                       arrancar con el flujo de proyecto compartido
├── armor.project.json                   manifiesto: versión, rol, madurez, comando de build
├── CHANGELOG.md                         qué cambió en cada versión
├── SECURITY.md SUPPORT.md LICENSE       política de seguridad, soporte y licencia
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   cómo contribuir y el código de conducta
├── build-test.sh build-test.bat         ejecutar las pruebas con el flujo compartido
├── pyproject.toml                       metadatos del paquete
└── .gitattributes .gitignore            ajustes de Git
```

</details>

## 🗺️ Hoja de ruta y límites conocidos

**Límites conocidos hoy**

* Aún no hay un modelo de detección real y nada se ha ejecutado en una cámara ni en la Jetson Orin NX: la simulación usa detecciones guionizadas.
* El evento aún no forma parte del contrato de ARMOR-COMMON.
* Los valores del seguimiento y del movimiento son constantes del código, no del fichero de configuración.

**Lo siguiente**

* Escribir el modelo de detección para la Jetson Orin NX y probarlo con una cámara real.
* Pasar las constantes de seguimiento y movimiento al fichero de configuración y meter el evento en el contrato de ARMOR-COMMON.

## 🌍 Idiomas

El README y los textos existen en inglés, español, francés, italiano, alemán, chino, japonés y portugués de Portugal.

## 🔗 Proyectos relacionados

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) es un sistema de seguridad perimetral hecho de repositorios independientes. Cada uno tiene su propia versión, sus propias pruebas y su propio README; esta es la familia:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratos de mensajes, validadores, vectores de conformidad y tipos generados
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware de nodo de campo para ESP32-S3 con tres radares y su propio panel web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolos de inversores y baterías solares y los mensajes de un nodo pasarela
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nodo eléctrico: medidores, el mensaje de las lecturas de la red y las reglas de maniobra
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nodo y panel de alarma: zonas, armado, retardos, sirena y PIN, con el servidor o sin él
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Panel táctil: el estado del sistema en una pantalla de pared, armar y reconocer, y el hogar del asistente de voz
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - La red local: sus dispositivos, internet y lo que cambia
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinador central: telemetría, alarmas, dispositivos, lecturas solares y cámaras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Consola web: cámaras, radar, alarmas, energía solar y el diseñador 2D/3D del emplazamiento
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Cliente de operador Android con radar 2D/3D en vivo
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Cliente de operador para iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Política de inferencia visual que explica sus decisiones y nunca actúa
* **ARMOR-VISION** (este repositorio) - Zonas de cámara, máscaras y reglas de detección para la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenciones de voz sin conexión con una confirmación que no se puede falsificar
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Cajas, electrónica y la matriz de aceptación en banco
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Despliegue, el banco de pruebas de la CM5, copias de seguridad y TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - Simulador de telemetría sin conexión con fallos repetibles
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Detecta, instala y actualiza los repositorios del propio ecosistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Arquitectura, base de seguridad y la matriz de capacidades

## 📚 Documentación

* [Uso](docs/USAGE.md): las órdenes, la configuración, el evento y la biblioteca
* [Matriz de capacidades: qué está demostrado y qué no](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catálogo de proyectos: versiones y cómo dependen unos repositorios de otros](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Registro de cambios de este repositorio](CHANGELOG.md)

## 🤝 Contribuir y comunidad

* Antes de un pull request ejecuta `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`: debe pasar. Consulta [CONTRIBUTING.md](CONTRIBUTING.md) y el [código de conducta](CODE_OF_CONDUCT.md).
* El README existe en ocho idiomas y se genera desde las fuentes de ARMOR-DOCS: un cambio de texto se hace allí.
* Un cambio en un mensaje entre componentes empieza en ARMOR-COMMON.
* No describas como funcionando en una placa lo que solo se ha compilado.
* Informa de una vulnerabilidad en privado: [SECURITY.md](SECURITY.md). Preguntas, ideas e informes: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCIA

GPL-3.0-or-later - véase [LICENSE](LICENSE).
