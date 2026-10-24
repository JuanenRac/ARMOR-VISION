<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-VISION banner" width="100%">
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
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-61%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.3-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**Ehrlichkeitsprüfung - was heute läuft:** Die Zonen, die Bewegungsprüfung, die Verfolgung, die Regeln und die 61 Tests sind real. Es gibt **noch kein echtes Erkennungsmodell**, und nichts lief auf einer Kamera oder auf dem Jetson Orin NX: die Simulation nutzt vorgegebene Erkennungen.

---

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.0.3` |
| Reifegrad | Funktionsfähig |
| Tests | 61 (`python -m unittest discover -s tests`) |
| Technik | Python 3.11+ |
| Auf echter Hardware | Noch keiner: weder echter Detektor noch Kamera noch Jetson (eine Simulation mit geskripteten Erkennungen) |

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

## 📂 Struktur des Repositorys

```text
ARMOR-VISION/
├── src/armor_vision/   geometry, config (zones, masks, profiles), motion, tracker, rules, detector, pipeline, cli
├── tests/              61 tests
└── docs/USAGE.md
```

## 🛠️ Entwicklungsumgebung

**Voraussetzungen:** Python 3.11+ (nur die Standardbibliothek)

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

Optionen und Format der Konfiguration: [Nutzung](docs/USAGE.md).

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
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Erkennt, installiert und aktualisiert die eigenen Repositories des Ökosystems
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architektur, Sicherheitsgrundlage und die Fähigkeitsmatrix

## 📚 Dokumentation und Community

Hier gibt es mehr zu lesen:

* [Fähigkeitsmatrix: was belegt ist und was nicht](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Projektkatalog: Versionen und wie die Repositorys voneinander abhängen](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Änderungsverlauf dieses Repositorys](CHANGELOG.md)
* [Lizenz (GPL-3.0-or-later)](LICENSE)
* Fragen, Ideen und Meldungen: electrohobby3d@gmail.com

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LIZENZ

GPL-3.0-or-later - siehe [LICENSE](LICENSE).
