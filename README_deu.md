<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-VISION-Banner" width="100%">
</p>

# 👁️ ARMOR-VISION

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  🇩🇪 <b>Deutsch</b> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Zonen, Masken und Erkennungsregeln für die Kameras

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 oder neuer">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Sprache">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.4-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Reifegrad">
</p>

---

**Ehrlichkeitsprüfung - was heute läuft:** Die Zonen, die Bewegungsprüfung, die Verfolgung, die Regeln und die 61 Tests sind real. Es gibt **noch kein echtes Erkennungsmodell**, und nichts lief auf einer Kamera oder auf dem Jetson Orin NX: die Simulation nutzt vorgegebene Erkennungen.

---

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.0.4` |
| Reifegrad | Funktionsfähig |
| Rolle | Kamerazonen, Masken und Erkennungsregeln (Familie: Core Services, übergeordnet: ARMOR-SERVER) |
| Technik | Python 3.11+, nur Standardbibliothek |
| Tests | 61 (`python -m unittest discover -s tests`) |
| Läuft auf | Jeder Computer |
| Auf echter Hardware | Noch keiner: weder echter Detektor noch Kamera noch Jetson (eine Simulation mit geskripteten Erkennungen) |
| Lizenz | GPL-3.0-or-later |

**Springe zu:** [Überblick](#-überblick) · [Architektur](#-architektur) · [Sicherheit](#-sicherheit-und-schutz) · [Schnittstellen](#-schnittstellen) · [Konfiguration](#-konfiguration) · [Schnellstart](#-schnellstart) · [Tests](#-tests) · [Probleme](#-fehlerbehebung) · [Struktur](#-struktur-des-repositorys) · [Verwandte](#-verwandte-projekte)

## 🚦 Projektstatus

Jede Zeile ist ein Teil dieses Repositorys, und die Ampel sagt, wie weit er heute ist. Sie beruht auf dem, was das Repository zeigen kann (Tests, Builds, Läufe), nicht auf dem, was geplant ist.

🟢 Fertig und überprüft · 🟡 Funktioniert, mit bekannten Grenzen · 🟠 Teilweise fertig oder noch nicht überprüft · 🔴 Nicht gemacht oder funktioniert nicht

| Bereich | Stand | Was das hier bedeutet |
|---|---|---|
| Software | 🟡 | Die Zonen, die Bewegungsprüfung, die Verfolgung und die Regeln funktionieren, aber es gibt noch kein echtes Erkennungsmodell: Die Simulation nutzt geskriptete Erkennungen. |
| Tests | 🟢 | 61 Tests bestehen (`python -m unittest discover -s tests`). |
| Hardware | 🔴 | Nichts lief an einer Kamera oder auf dem Jetson Orin NX. |
| Dokumentation | 🟢 | Acht Sprachen und das Änderungsprotokoll sind aktuell. |

## 🎯 Überblick

* **Zonen und Masken:** Polygone in normalisierten Koordinaten (0 bis 1), eine Zeichnung gilt also bei jeder Auflösung; eine Zone zählt Erkennungen, eine Maske ignoriert Bewegung. Jede Zone hat einen Label-Filter, eine Art (`alert` oder `detection`) und eine Trägheit in Bildern und Sekunden.
* **Zuerst die Bewegung:** der teure Detektor läuft nur, wenn sich außerhalb der Masken genug vom Bild verändert hat.
* **Eine Verfolgung:** jedes Objekt behält seine Identität von Bild zu Bild, und was stillsteht (ein geparktes Auto), wird gemerkt und erzeugt keine neuen Ereignisse.
* **Scharfschaltprofile:** `away`, `home` und ähnliche wählen, welche Zonen überwacht werden; ein unbekannter Modus überwacht alles.
* **Ereignisse, die nur melden:** ein Alarm oder eine Erkennung trägt immer `authorizes_action: false`; der Server entscheidet, was zu tun ist.

## 🧩 Rolle in A.R.M.O.R.

ARMOR-VISION ist der Teil, der entscheidet, was das Bild einer Kamera bedeutet, unabhängig von jedem Detektor: die darauf gezeichneten Zonen und Masken, die Bewegungsprüfung, die vor dem teuren Detektor läuft, der Tracker, die Scharfschaltprofile und die Regeln, die Erkennungen zu Ereignissen machen. [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) ist der Dienst, der heute die Kameras beobachtet; ARMOR-VISION ist der Ort, an dem die Regeln für ein echtes Erkennungsmodell bereitliegen und darauf warten. Es meldet nur: Die Ereignisse autorisieren nie eine Aktion.

| Name | Wie | Wozu |
|---|---|---|
| ARMOR-SERVER-AI | dieselben Regeln, sobald es ein Modell gibt | Überwacht heute die Kameras |
| ARMOR-SERVER | `armor.vision.event/v1` | Entscheidet, was mit einem Ereignis geschieht (noch nicht Teil des ARMOR-COMMON-Vertrags) |

## 🏛️ Architektur

<p align="center">
  <img src="images/architecture.svg" alt="Architektur von ARMOR-VISION: wer es aufruft, was es enthält und wovon es abhängt" width="100%">
</p>

## 🔒 Sicherheit und Schutz

| Bedrohung | Abwehr |
|---|---|
| Die Regelmaschine handelt auf eigene Faust | Jedes Ereignis trägt `authorizes_action: false` (Schema `armor.vision.event/v1`); der Server entscheidet |
| Eine falsche Kamerakonfiguration | `check-config` listet jedes Problem auf, und ein Problem bedeutet, dass nichts akzeptiert wird; Koordinaten liegen zwischen 0 und 1, eine Zone ist `alert` oder `detection`, unbekannte Felder sind Fehler |
| Der teure Detektor läuft ohne Grund | Erst die Bewegung: Der Detektor wird nur gefragt, wenn genug Zellen des 16-x-9-Rasters außerhalb der Masken wechseln |
| Ein geparktes Auto löst Ereignis um Ereignis aus | Der Tracker merkt sich Ruhendes (Drift unter 0,01 in 3 s) 300 s lang, es gibt keine neuen Ereignisse |
| Ein unbekannter Scharfschaltmodus | Alle Zonen werden überwacht; nur `disarmed` ohne Profil schaltet die `alert`-Zonen stumm, `detection`-Zonen zeichnen weiter auf |

Nichts davon ist eine Sicherheitsfunktion: Es gibt noch kein echtes Erkennungsmodell.

## 🔌 Schnittstellen

| Name | Was sie festlegt |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | Führt ein eingebautes Szenario aus (eine Person quert eine Einfahrt, ein geparktes Auto, Bewegung hinter einem maskierten Baum) und druckt je Ereignis eine JSON-Zeile und zuletzt die Zähler |
| `python -m armor_vision check-config FILE` | Prüft eine Konfiguration und druckt jedes Problem; Exit 0 gut, 1 ungültig, 2 nicht lesbar |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

Als Bibliothek: `parse_config`, `Pipeline.process_detections` und `process_frame`. `load_detector("tensorrt")` löst `DetectorUnavailable` aus, weil das Modell für den Jetson Orin NX nicht geschrieben ist. Siehe [docs/USAGE.md](docs/USAGE.md).

## ⚙️ Konfiguration

| Name | Was sie festlegt |
|---|---|
| `motion_threshold` | 1 bis 255: der Graustufenunterschied, der als Änderung zählt |
| `motion_min_cells` | Wie viele Zellen des 16-x-9-Rasters wechseln müssen, bevor der Detektor gefragt wird |
| `zones[]` | `id`, `name`, `kind` (`alert` oder `detection`), `labels`, `min_frames`, `min_seconds`, `points` (Polygon, 0 bis 1); gezählt wird an den Füßen der Box |
| `masks[]` | Polygone, in denen Bewegung ignoriert wird; Erkennungen mit Mittelpunkt darin entfallen |
| `profiles` | Welche Zonen in jedem Scharfschaltmodus überwacht werden (`away`, `home`, ...) |

| Grenze | Wert |
|---|---|
| Zuordnung einer Erkennung zu einer Spur (Überlappung / Reichweite) | 0.3 / 1.0 |
| Eine bewegte, nicht gesehene Spur entfällt nach | 2 s |
| Ruhend: Fenster / Drift / gemerkt für | 3 s / 0.01 / 300 s |
| Bewegungsraster | 16 x 9 |

Diese Werte sind heute Konstanten in `tracker.py` und `motion.py`; die Konfigurationsdatei enthält Zonen, Masken, Profile und die Bewegungsschwellen.

## 🚀 Schnellstart

**Voraussetzungen:** Python 3.11+ (nur Standardbibliothek).

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

## 🧪 Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Testdatei | Tests | Was sie abdeckt |
|---|---|---|
| `test_vision.py` | 42 | Geometrie, Konfiguration, Bewegung, Tracker, Regeln, Profile, die Kette und die Kommandozeile |
| `test_vision_edges.py` | 19 | Die Grenzfälle: falsche Konfigurationen, ruhende Objekte, maskierte Erkennungen und der nicht verfügbare Detektor |

## 🏗️ Build und Veröffentlichung

Es ist reines Python: nichts zu kompilieren. Die Version steht in `pyproject.toml` und `armor.project.json`.

## 🩺 Fehlerbehebung

| Sie sehen | Weil | Tun Sie |
|---|---|---|
| `check-config` endet mit 1 | Die Konfiguration hat Probleme; es listet jedes auf | Behebe alle: Unbekannte Felder sind Fehler |
| `check-config` endet mit 2 | Die Datei kann nicht gelesen werden | Prüfe den Pfad und dass es JSON ist |
| `DetectorUnavailable` | `load_detector("tensorrt")`: Das echte Modell fehlt | Nutze `ScriptedDetector` |
| Eine Zone löst nie aus | Die Füße liegen außerhalb, das Label wird nicht akzeptiert, eine Maske verdeckt sie, oder der Modus hat kein Profil mit dieser Zone | Starte `simulate` mit derselben Datei und demselben Modus |

## 📂 Struktur des Repositorys

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository-Struktur von ARMOR-VISION" width="100%">
</p>

<details>
<summary>Textversion des Baums</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      Polygone in normalisierten Koordinaten
│   ├── config.py                        Zonen, Masken, Profile und ihre Prüfung
│   ├── motion.py                        die 16-x-9-Bewegungsprüfung ohne Masken
│   ├── detector.py                      geskriptete Erkennungen; das echte Modell fehlt
│   ├── tracker.py                       Identität zwischen Bildern; ruhende Objekte
│   ├── rules.py                         von Zonen zu Ereignissen: armor.vision.event/v1
│   └── pipeline.py cli.py __main__.py   die ganze Kette und die Kommandozeile
├── tests/                               die Tests
├── docs/                                die Anleitungen dieses Repositorys
├── tools/                               die gemeinsamen CI-Prüfungen und Projektwerkzeuge
├── .github/                             CI-Workflow sowie Vorlagen für Issues und Pull Requests
├── images/                              Banner, Symbol und die zwei Bilder dieses READMEs
├── build.sh build.bat                   Build über den gemeinsamen Projekt-Workflow
├── test.sh test.bat                     Tests über den gemeinsamen Workflow ausführen
├── run.sh run.bat                       Start über den gemeinsamen Projekt-Workflow
├── armor.project.json                   Manifest: Version, Rolle, Reifegrad, Build-Befehl
├── CHANGELOG.md                         was sich in jeder Version geändert hat
├── SECURITY.md SUPPORT.md LICENSE       Sicherheitsrichtlinie, Support und Lizenz
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   Mitwirkung und Verhaltenskodex
├── build-test.sh build-test.bat         Tests über den gemeinsamen Workflow ausführen
├── pyproject.toml                       Paketmetadaten
└── .gitattributes .gitignore            Git-Einstellungen
```

</details>

## 🗺️ Roadmap und bekannte Grenzen

**Bekannte Grenzen heute**

* Es gibt noch kein echtes Erkennungsmodell, und nichts lief auf einer Kamera oder dem Jetson Orin NX: Die Simulation nutzt geskriptete Erkennungen.
* Das Ereignis ist noch nicht Teil des ARMOR-COMMON-Vertrags.
* Die Werte von Tracker und Bewegung sind Konstanten im Code, nicht in der Konfigurationsdatei.

**Als Nächstes**

* Das Erkennungsmodell für den Jetson Orin NX schreiben und mit einer echten Kamera erproben.
* Die Konstanten von Tracker und Bewegung in die Konfigurationsdatei verlegen und das Ereignis in den ARMOR-COMMON-Vertrag aufnehmen.

## 🌍 Sprachen

README und Texte gibt es auf Englisch, Spanisch, Französisch, Italienisch, Deutsch, Chinesisch, Japanisch und europäischem Portugiesisch.

## 🔗 Verwandte Projekte

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) ist ein Perimeter-Sicherheitssystem aus unabhängigen Repositorys. Jedes hat eine eigene Version, eigene Tests und ein eigenes README; hier ist die Familie:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Nachrichtenverträge, Validierer, Konformitätsvektoren und generierte Typen
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Feldknoten-Firmware für ESP32-S3 mit drei Radaren und eigenem Web-Panel
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protokolle für Solar-Wechselrichter und -Batterien und die Nachrichten eines Gateway-Knotens
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Elektroknoten: Zähler, die Nachricht der Netzmesswerte und die Regeln fürs Schalten
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Alarmknoten und Alarmzentrale: Zonen, Scharfschalten, Verzögerungen, Sirene und PIN, mit dem Server oder ohne ihn
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Touch-Panel: der Systemzustand auf einem Wandbildschirm, Scharf- und Quittieren sowie das Zuhause des Sprachassistenten
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Das lokale Netzwerk: seine Geräte, das Internet und was sich ändert
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Zentraler Koordinator: Telemetrie, Alarme, Geräte, Solarmesswerte und Kameras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web-Konsole: Kameras, Radar, Alarme, Solarenergie und 2D/3D-Standortdesigner
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Android-Bedienclient mit Live-Radar in 2D/3D
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone-Bedienclient
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Visuelle Inferenzrichtlinie, die ihre Entscheidungen erklärt und nie handelt
* **ARMOR-VISION** (dieses Repository) - Kamerazonen, Masken und Erkennungsregeln für den Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Offline-Sprachabsichten mit einer nicht fälschbaren Bestätigung
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Gehäuse, Elektronik und die Abnahmematrix am Prüfstand
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Bereitstellung, CM5-Prüfstand, Backup und TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - Offline-Telemetriesimulator mit wiederholbaren Fehlern
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Erkennt, installiert und aktualisiert die eigenen Repositorys des Ökosystems
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architektur, Sicherheitsgrundlage und die Fähigkeitsmatrix

## 📚 Dokumentation

* [Verwendung](docs/USAGE.md): die Befehle, die Konfiguration, das Ereignis und die Bibliothek
* [Fähigkeitsmatrix: was belegt ist und was nicht](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Projektkatalog: Versionen und wie die Repositorys voneinander abhängen](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Änderungsverlauf dieses Repositorys](CHANGELOG.md)

## 🤝 Mitwirken und Community

* Führe vor einem Pull Request `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` aus: Es muss bestehen. Siehe [CONTRIBUTING.md](CONTRIBUTING.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.md).
* Das README gibt es in acht Sprachen, und es wird aus den Quellen in ARMOR-DOCS erzeugt: Eine Textänderung erfolgt dort.
* Eine Änderung an einer Nachricht zwischen Komponenten beginnt in ARMOR-COMMON.
* Beschreibe nichts als auf einer Platine funktionierend, was nur gebaut wurde.
* Melde eine Schwachstelle privat: [SECURITY.md](SECURITY.md). Fragen, Ideen und Meldungen: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LIZENZ

GPL-3.0-or-later - siehe [LICENSE](LICENSE).
