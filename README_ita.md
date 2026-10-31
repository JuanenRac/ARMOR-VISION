<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="Banner di ARMOR-VISION" width="100%">
</p>

# 👁️ ARMOR-VISION

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  🇮🇹 <b>Italiano</b> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Zone, maschere e regole di rilevamento per le telecamere

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 o successiva">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Linguaggio">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-90%20passing-2ea44f.svg" alt="Test">
  <img src="https://img.shields.io/badge/Version-0.0.5-0f6cbd.svg" alt="Versione">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturità">
</p>

---

**Controllo di onestà - cosa funziona oggi:** Le zone, il controllo del movimento, il tracciamento, le regole e i 90 test sono reali. **Non esiste ancora un vero modello di rilevamento** e nulla è stato eseguito su una telecamera o sulla Jetson Orin NX: la simulazione usa rilevamenti scriptati.

---

## 📋 In breve

| | |
|---|---|
| Versione | `0.0.5` |
| Maturità | Funzionale |
| Ruolo | Zone, maschere e regole di rilevamento delle telecamere (famiglia: Core Services, padre: ARMOR-SERVER) |
| Tecnologia | Python 3.11+, solo libreria standard |
| Test | 90 (`python -m unittest discover -s tests`) |
| Gira su | Qualsiasi computer |
| Su hardware reale | Ancora nessuno: né rilevatore reale, né telecamera, né Jetson (una simulazione con rilevamenti scriptati) |
| Licenza | GPL-3.0-or-later |

**Vai a:** [Panoramica](#-panoramica) · [Architettura](#-architettura) · [Sicurezza](#-sicurezza-e-protezione) · [Interfacce](#-interfacce) · [Configurazione](#-configurazione) · [Avvio rapido](#-avvio-rapido) · [Test](#-test) · [Problemi](#-risoluzione-dei-problemi) · [Struttura](#-struttura-del-repository) · [Correlati](#-progetti-correlati)

## 🚦 Stato del progetto

Ogni riga è una parte di questo repository e il semaforo dice a che punto è oggi. È scritta in base a ciò che il repository può mostrare (test, compilazioni, esecuzioni), non a ciò che è previsto.

🟢 Fatto e verificato · 🟡 Funziona, con limiti noti · 🟠 Fatto a metà o non ancora verificato · 🔴 Non fatto o non funzionante

| Area | Stato | Cosa significa qui |
|---|---|---|
| Software | 🟡 | Le zone, il controllo del movimento, il tracciamento e le regole funzionano, ma non c'è ancora un vero modello di rilevamento: la simulazione usa rilevamenti da script. |
| Test | 🟢 | Superano 90 test (`python -m unittest discover -s tests`). |
| Hardware | 🔴 | Nulla ha girato su una telecamera né sulla Jetson Orin NX. |
| Documentazione | 🟢 | Otto lingue e il registro delle modifiche sono aggiornati. |

## 🎯 Panoramica

* **Zone e maschere:** poligoni disegnati in coordinate normalizzate (da 0 a 1), così lo stesso disegno vale a qualsiasi risoluzione; una zona conta i rilevamenti, una maschera ignora il movimento. Ogni zona ha un filtro di etichette, un tipo (`alert` o `detection`) e un'inerzia in immagini e secondi.
* **Prima il movimento:** il rilevatore, costoso, viene eseguito solo quando è cambiata abbastanza immagine fuori dalle maschere.
* **Un tracciamento:** ogni oggetto mantiene la sua identità da un'immagine all'altra, e ciò che sta fermo (un'auto parcheggiata) viene ricordato e non genera nuovi eventi.
* **Profili di inserimento:** `away`, `home` e simili scelgono quali zone sono sorvegliate; una modalità sconosciuta sorveglia tutto.
* **Eventi che informano soltanto:** un allarme o un rilevamento porta sempre `authorizes_action: false`; il server decide cosa fare.

## 🧩 Ruolo in A.R.M.O.R.

ARMOR-VISION è la parte che decide cosa significa l'immagine di una telecamera, a prescindere da qualsiasi rilevatore: le zone e le maschere disegnate su di essa, il controllo di movimento che gira prima del rilevatore costoso, il tracker, i profili di inserimento e le regole che trasformano i rilevamenti in eventi. [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) è il servizio che oggi sorveglia le telecamere; ARMOR-VISION è dove le regole per un vero modello di rilevamento sono pronte, in attesa. Si limita a riferire: gli eventi non autorizzano mai un'azione.

| Nome | Come | A cosa serve |
|---|---|---|
| ARMOR-SERVER-AI | le stesse regole, quando ci sarà un modello | Oggi sorveglia le telecamere |
| ARMOR-SERVER | `armor.vision.event/v1` | Decide cosa fare di un evento (non ancora nel contratto di ARMOR-COMMON) |

## 🏛️ Architettura

<p align="center">
  <img src="images/architecture.svg" alt="Architettura di ARMOR-VISION: chi lo chiama, cosa contiene e da cosa dipende" width="100%">
</p>

## 🔒 Sicurezza e protezione

| Minaccia | Difesa |
|---|---|
| Il motore di regole agisce da solo | Ogni evento porta `authorizes_action: false` (schema `armor.vision.event/v1`); decide il server |
| Una configurazione di telecamera errata | `check-config` elenca ogni problema e uno solo basta a non accettare nulla; le coordinate vanno da 0 a 1, una zona è `alert` o `detection`, i campi sconosciuti sono errori |
| Il rilevatore costoso gira senza motivo | Prima il movimento: il rilevatore è interpellato solo se cambiano abbastanza celle della griglia 16 x 9 fuori dalle maschere |
| Un'auto parcheggiata genera un evento dopo l'altro | Il tracker ricorda ciò che è fermo (deriva sotto 0,01 in 3 s) per 300 s e non genera nuovi eventi |
| Una modalità di inserimento sconosciuta | Si sorvegliano tutte le zone; solo `disarmed` senza profilo mette a tacere le zone `alert` e le `detection` registrano ancora |
| La pipeline di attività conserva o rivela immagini di persone | È spenta per impostazione predefinita; conserva solo un conteggio per cella della griglia (posizioni, etichette e numeri), mai un'immagine, un riquadro o un'identità; l'esportazione dice `contains_images: false`. Un file di rilevamenti malformato, che torna indietro nel tempo o oltre 16 MiB viene rifiutato per intero, e la mappa ha un limite rigido di memoria |

Nulla qui è una funzione di sicurezza: non esiste ancora un vero modello di rilevamento.

## 🔌 Interfacce

| Nome | Cosa imposta |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | Esegue uno scenario integrato (una persona attraversa un vialetto, un'auto parcheggiata, movimento dietro un albero mascherato) e stampa una riga JSON per evento e una finale con i contatori |
| `python -m armor_vision check-config FILE` | Valida una configurazione e stampa ogni problema; uscita 0 buona, 1 non valida, 2 illeggibile |
| `python -m armor_vision simulate --simulate-events --activity-config FILE [--seed N] [--detections-file FILE]` | Pipeline di attività, SPENTA salvo che il file dica `"enabled": true` (codice 3 se spenta): una scena sintetica con seme fisso, o rilevamenti registrati, dà una riga JSON per evento (`zone_enter`, `zone_exit`, `dwell`, `loiter`, `line_cross`) |
| `python -m armor_vision simulate --heatmap OUT --activity-config FILE` | Scrive la mappa di calore dell'attività (conteggi per cella, `OUT` termina in `.json`, `.png` o `.svg`); solo posizioni aggregate, mai immagini |
| `python -m armor_vision activity-example` / `check-activity-config FILE` | Stampa una configurazione di attività di partenza / ne convalida una (codice 0 buono, 1 non valida, 2 illeggibile) |
| `ActivityEngine`, `heatmap_route` | Come libreria: il motore e il gestore di `GET /heatmap?camera=ID&format=json` (anche `png` e `svg`), per il servizio che lo monterà; questo repository non ha un server proprio e la rotta risponde 404 finché la pipeline è spenta |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

Come libreria: `parse_config`, `Pipeline.process_detections` e `process_frame`. `load_detector("tensorrt")` solleva `DetectorUnavailable` perché il modello per il Jetson Orin NX non è scritto. Vedi [docs/USAGE.md](docs/USAGE.md).

## ⚙️ Configurazione

| Nome | Cosa imposta |
|---|---|
| `motion_threshold` | da 1 a 255: la differenza di grigio che conta come cambiamento |
| `motion_min_cells` | Quante celle della griglia 16 x 9 devono cambiare prima di interpellare il rilevatore |
| `zones[]` | `id`, `name`, `kind` (`alert` o `detection`), `labels`, `min_frames`, `min_seconds`, `points` (poligono, da 0 a 1); si conta dai piedi del riquadro |
| `masks[]` | Poligoni dove il movimento è ignorato; i rilevamenti con il centro all'interno vengono scartati |
| `profiles` | Quali zone sono sorvegliate in ogni modalità di inserimento (`away`, `home`, ...) |
| `configurazione di attività (file a parte)` | `enabled` (predefinito `false`), `heatmap` (`cols`, `rows`, `window_seconds`, `half_life_seconds`, `slices`, `max_cells` fino a 65536, `position`, `labels`) ed `events` (`dwell_seconds`, `loiter_seconds`, `loiter_radius`, `lost_seconds`, `labels`, `lines[]` con `id`, `a`, `b`); la mappa è normalizzata come peso diviso per il massimo |

| Limite | Valore |
|---|---|
| Abbinamento di un rilevamento a una traccia (sovrapposizione / portata) | 0.3 / 1.0 |
| Una traccia in movimento non vista viene scartata dopo | 2 s |
| Fermo: finestra / deriva / ricordato per | 3 s / 0.01 / 300 s |
| Griglia di movimento | 16 x 9 |

Oggi questi valori sono costanti di `tracker.py` e `motion.py`; il file di configurazione contiene zone, maschere, profili e soglie di movimento.

## 🚀 Avvio rapido

**Requisiti:** Python 3.11+ (solo libreria standard).

```powershell
$env:PYTHONPATH = "src"
python -m armor_vision simulate --mode away
python -m armor_vision check-config my_cameras.json
python -m unittest discover -s tests   # 90 tests
```

```bash
PYTHONPATH=src python -m armor_vision simulate --mode away
PYTHONPATH=src python -m armor_vision check-config my_cameras.json
PYTHONPATH=src python -m unittest discover -s tests   # 90 tests
```

## 🧪 Test

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| File di test | Test | Cosa copre |
|---|---|---|
| `test_vision.py` | 42 | Geometria, configurazione, movimento, tracker, regole, profili, la catena e la riga di comando |
| `test_vision_edges.py` | 19 | I casi limite: configurazioni errate, oggetti fermi, rilevamenti mascherati e rilevatore non disponibile |
| `test_characterization.py` | 2 | Fissa byte per byte l'uscita della simulazione integrata, così non cambia finché la pipeline di attività è spenta |
| `test_activity.py` | 27 | Configurazione di attività, sorgenti sintetica e registrata, eventi, mappa di calore (determinismo, somma uguale ai rilevamenti, niente fuori dalla griglia, finestra, decadimento, memoria), il gestore `/heatmap` e la riga di comando |

## 🏗️ Compilazione e rilascio

È Python puro: nulla da compilare. La versione sta in `pyproject.toml` e `armor.project.json`.

## 🩺 Risoluzione dei problemi

| Vedi | Perché | Fai |
|---|---|---|
| `check-config` termina con 1 | La configurazione ha problemi; li elenca tutti | Correggili tutti: i campi sconosciuti sono errori |
| `check-config` termina con 2 | Il file non può essere letto | Controlla il percorso e che sia JSON |
| `DetectorUnavailable` | `load_detector("tensorrt")`: il modello reale non è scritto | Usa `ScriptedDetector` |
| Una zona non scatta mai | I piedi sono fuori dal poligono, l'etichetta non è accettata, una maschera la nasconde, o la modalità non ha un profilo con quella zona | Esegui `simulate` con lo stesso file e modalità |

## 📂 Struttura del repository

<p align="center">
  <img src="images/repository-structure.svg" alt="Struttura del repository di ARMOR-VISION" width="100%">
</p>

<details>
<summary>Versione testuale dell'albero</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      poligoni in coordinate normalizzate
│   ├── config.py                        zone, maschere, profili e la loro validazione
│   ├── motion.py                        il controllo del movimento 16 x 9, maschere ignorate
│   ├── detector.py                      rilevamenti scriptati; il modello reale non c'è
│   ├── tracker.py                       identità tra immagini; oggetti fermi
│   ├── rules.py                         dalle zone agli eventi: armor.vision.event/v1
│   ├── activity_config.py               impostazioni della pipeline di attività, spenta di default
│   ├── sources.py heatmap.py            sorgenti sintetica e registrata; mappa di calore
│   ├── activity.py                      eventi e gestore /heatmap
│   └── pipeline.py cli.py __main__.py   tutta la catena e la riga di comando
├── tests/                               i test
├── docs/                                le guide di questo repository
├── tools/                               i controlli CI condivisi e gli strumenti del progetto
├── .github/                             workflow CI e modelli per issue e pull request
├── images/                              banner, icona e le due immagini di questo README
├── build.sh build.bat                   build tramite il flusso di progetto condiviso
├── test.sh test.bat                     eseguire i test tramite il flusso condiviso
├── run.sh run.bat                       avvio tramite il flusso di progetto condiviso
├── armor.project.json                   manifesto: versione, ruolo, maturità, comando di build
├── CHANGELOG.md                         cosa è cambiato in ogni versione
├── SECURITY.md SUPPORT.md LICENSE       politica di sicurezza, supporto e licenza
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   come contribuire e il codice di condotta
├── build-test.sh build-test.bat         eseguire i test tramite il flusso condiviso
├── pyproject.toml                       metadati del pacchetto
└── .gitattributes .gitignore            impostazioni di Git
```

</details>

## 🗺️ Roadmap e limiti noti

**Limiti noti oggi**

* Non esiste ancora un vero modello di rilevamento e nulla ha girato su una telecamera né sul Jetson Orin NX: la simulazione usa rilevamenti scriptati.
* La sorgente telecamera o RTSP della pipeline di attività è per l'hardware e non è scritta: oggi funziona su una scena sintetica o un file di rilevamenti. La mappa di calore qui non ha un server HTTP, solo il gestore.
* L'evento non fa ancora parte del contratto di ARMOR-COMMON.
* I valori di tracker e movimento sono costanti nel codice, non nel file di configurazione.

**Prossimi passi**

* Scrivere il modello di rilevamento per il Jetson Orin NX e provarlo con una telecamera reale.
* Spostare le costanti di tracker e movimento nel file di configurazione e inserire l'evento nel contratto di ARMOR-COMMON.

## 🌍 Lingue

Il README e i testi esistono in inglese, spagnolo, francese, italiano, tedesco, cinese, giapponese e portoghese europeo.

## 🔗 Progetti correlati

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) è un sistema di sicurezza perimetrale fatto di repository indipendenti. Ognuno ha la propria versione, i propri test e il proprio README; ecco la famiglia:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratti dei messaggi, validatori, vettori di conformità e tipi generati
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware del nodo di campo per ESP32-S3 con tre radar e un proprio pannello web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolli di inverter e batterie solari e messaggi di un nodo gateway
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nodo elettrico: contatori, il messaggio delle letture della rete e le regole di manovra
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nodo e centrale d'allarme: zone, inserimento, ritardi, sirena e PIN, con il server o senza
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Pannello touch: lo stato del sistema su uno schermo a parete, attivare e riconoscere gli allarmi, e la casa dell'assistente vocale
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - La rete locale: i suoi dispositivi, internet e ciò che cambia
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinatore centrale: telemetria, allarmi, dispositivi, letture solari e telecamere
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Console web: telecamere, radar, allarmi, energia solare e progettista del sito 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Client Android dell'operatore con radar 2D/3D in tempo reale
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Client operatore per iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Politica di inferenza visiva che spiega le sue decisioni e non agisce mai
* **ARMOR-VISION** (questo repository) - Zone delle telecamere, maschere e regole di rilevamento per la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenti vocali offline con una conferma impossibile da falsificare
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Contenitori, elettronica e matrice di accettazione da banco
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Distribuzione, banco di prova CM5, backup e TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - Simulatore di telemetria offline con guasti ripetibili
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Rileva, installa e aggiorna i repository stessi dell'ecosistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architettura, base di sicurezza e matrice delle capacità

## 📚 Documentazione

* [Uso](docs/USAGE.md): i comandi, la configurazione, l'evento e la libreria
* [Matrice delle capacità: cosa è provato e cosa no](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catalogo dei progetti: versioni e dipendenze tra i repository](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Cronologia delle modifiche di questo repository](CHANGELOG.md)

## 🤝 Contribuire e comunità

* Prima di una pull request esegui `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`: deve passare. Vedi [CONTRIBUTING.md](CONTRIBUTING.md) e il [codice di condotta](CODE_OF_CONDUCT.md).
* Il README esiste in otto lingue ed è generato dalle sorgenti in ARMOR-DOCS: una modifica al testo si fa lì.
* Una modifica a un messaggio tra componenti parte da ARMOR-COMMON.
* Non descrivere come funzionante su una scheda ciò che è stato solo compilato.
* Segnala una vulnerabilità in privato: [SECURITY.md](SECURITY.md). Domande, idee e segnalazioni: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTORE

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENZA

GPL-3.0-or-later - vedi [LICENSE](LICENSE).
