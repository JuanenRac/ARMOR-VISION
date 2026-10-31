<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="Bannière d'ARMOR-VISION" width="100%">
</p>

# 👁️ ARMOR-VISION

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  🇫🇷 <b>Français</b> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Zones, masques et règles de détection pour les caméras

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 ou ultérieure">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Langage">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-90%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.0.5-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturité">
</p>

---

**Vérification d'honnêteté - ce qui fonctionne aujourd'hui :** Les zones, le contrôle du mouvement, le suivi, les règles et les 90 tests sont réels. **Il n'existe pas encore de vrai modèle de détection** et rien n'a tourné sur une caméra ni sur la Jetson Orin NX : la simulation utilise des détections scénarisées.

---

## 📋 En un coup d'œil

| | |
|---|---|
| Version | `0.0.5` |
| Maturité | Fonctionnel |
| Rôle | Zones, masques et règles de détection des caméras (famille : Core Services, parent : ARMOR-SERVER) |
| Technologie | Python 3.11+, bibliothèque standard uniquement |
| Tests | 90 (`python -m unittest discover -s tests`) |
| Fonctionne sur | N'importe quel ordinateur |
| Sur matériel réel | Aucun pour l'instant : ni détecteur réel, ni caméra, ni Jetson (une simulation avec des détections scriptées) |
| Licence | GPL-3.0-or-later |

**Aller à :** [Présentation](#-présentation) · [Architecture](#-architecture) · [Sécurité](#-sécurité-et-protection) · [Interfaces](#-interfaces) · [Configuration](#-configuration) · [Démarrage rapide](#-démarrage-rapide) · [Tests](#-tests) · [Dépannage](#-dépannage) · [Structure](#-structure-du-dépôt) · [Liés](#-projets-liés)

## 🚦 État du projet

Chaque ligne est une partie de ce dépôt et le feu dit où elle en est aujourd'hui. Elle est écrite d'après ce que le dépôt peut montrer (tests, compilations, exécutions), pas d'après ce qui est prévu.

🟢 Fait et vérifié · 🟡 Fonctionne, avec des limites connues · 🟠 À moitié fait ou pas encore vérifié · 🔴 Pas fait ou ne fonctionne pas

| Domaine | État | Ce que cela veut dire ici |
|---|---|---|
| Logiciel | 🟡 | Les zones, le contrôle du mouvement, le suivi et les règles fonctionnent, mais il n'y a pas encore de vrai modèle détecteur : la simulation utilise des détections scénarisées. |
| Tests | 🟢 | 90 tests réussissent (`python -m unittest discover -s tests`). |
| Matériel | 🔴 | Rien n'a tourné sur une caméra ni sur le Jetson Orin NX. |
| Documentation | 🟢 | Huit langues et le journal des modifications sont à jour. |

## 🎯 Présentation

* **Zones et masques :** des polygones dessinés en coordonnées normalisées (de 0 à 1), un même dessin sert donc à toute résolution ; une zone compte les détections, un masque ignore le mouvement. Chaque zone a un filtre d'étiquettes, un type (`alert` ou `detection`) et une inertie en images et en secondes.
* **D'abord le mouvement :** le détecteur, coûteux, ne s'exécute que lorsque assez de l'image a changé en dehors des masques.
* **Un suivi :** chaque objet garde son identité d'une image à l'autre, et ce qui reste immobile (une voiture garée) est mémorisé et ne produit pas de nouveaux événements.
* **Profils d'armement :** `away`, `home` et similaires choisissent les zones surveillées ; un mode inconnu surveille tout.
* **Des événements qui informent seulement :** une alerte ou une détection porte toujours `authorizes_action: false` ; le serveur décide quoi faire.

## 🧩 Rôle dans A.R.M.O.R.

ARMOR-VISION est la partie qui décide de ce que signifie l'image d'une caméra, indépendamment de tout détecteur : les zones et masques dessinés dessus, le contrôle de mouvement qui s'exécute avant le détecteur coûteux, le suiveur, les profils d'armement et les règles qui transforment des détections en événements. [ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI) est le service qui surveille les caméras aujourd'hui ; ARMOR-VISION est l'endroit où les règles pour un vrai modèle de détection sont prêtes, en l'attendant. Il ne fait que rapporter : les événements n'autorisent jamais une action.

| Nom | Comment | À quoi ça sert |
|---|---|---|
| ARMOR-SERVER-AI | les mêmes règles, dès qu'un modèle existe | Surveille les caméras aujourd'hui |
| ARMOR-SERVER | `armor.vision.event/v1` | Décide quoi faire d'un événement (pas encore dans le contrat d'ARMOR-COMMON) |

## 🏛️ Architecture

<p align="center">
  <img src="images/architecture.svg" alt="Architecture de ARMOR-VISION : qui l'appelle, ce qu'il contient et de quoi il dépend" width="100%">
</p>

## 🔒 Sécurité et protection

| Menace | Défense |
|---|---|
| Le moteur de règles agit de lui-même | Chaque événement porte `authorizes_action: false` (schéma `armor.vision.event/v1`) ; le serveur décide |
| Une mauvaise configuration de caméra | `check-config` liste chaque problème et un seul problème fait tout refuser ; les coordonnées vont de 0 à 1, une zone est `alert` ou `detection`, les champs inconnus sont des erreurs |
| Le détecteur coûteux tourne pour rien | Le mouvement d'abord : le détecteur n'est sollicité que si assez de cellules de la grille 16 x 9 changent hors des masques |
| Une voiture garée déclenche événement sur événement | Le suivi mémorise ce qui est immobile (dérive sous 0,01 en 3 s) pendant 300 s sans nouvel événement |
| Un mode d'armement inconnu | Toutes les zones sont surveillées ; seul `disarmed` sans profil réduit au silence les zones `alert`, les zones `detection` enregistrent encore |
| La chaîne d'activité conserve ou divulgue des images de personnes | Elle est éteinte par défaut ; elle ne garde qu'un compte par cellule de la grille (positions, étiquettes et nombres), jamais une image, une boîte ou une identité ; l'export dit `contains_images: false`. Un fichier de détections mal formé, qui remonte le temps ou de plus de 16 Mio est refusé en entier, et la carte a une limite dure de mémoire |

Rien ici n'est une fonction de sécurité : il n'y a pas encore de vrai modèle de détection.

## 🔌 Interfaces

| Nom | Ce qu'elle règle |
|---|---|
| `python -m armor_vision simulate [--config FILE] [--mode MODE]` | Exécute un scénario intégré (une personne traverse une allée, une voiture garée, un mouvement derrière un arbre masqué) et imprime une ligne JSON par événement puis une ligne de compteurs |
| `python -m armor_vision check-config FILE` | Valide une configuration et imprime chaque problème ; sortie 0 bonne, 1 invalide, 2 illisible |
| `python -m armor_vision simulate --simulate-events --activity-config FILE [--seed N] [--detections-file FILE]` | Chaîne d'activité, ÉTEINTE sauf si le fichier dit `"enabled": true` (code 3 si éteinte) : une scène synthétique à graine fixe, ou des détections enregistrées, donne une ligne JSON par événement (`zone_enter`, `zone_exit`, `dwell`, `loiter`, `line_cross`) |
| `python -m armor_vision simulate --heatmap OUT --activity-config FILE` | Écrit la carte de chaleur de l'activité (comptes par cellule, `OUT` finit par `.json`, `.png` ou `.svg`) ; seulement des positions agrégées, jamais d'images |
| `python -m armor_vision activity-example` / `check-activity-config FILE` | Affiche une configuration d'activité de départ / en valide une (code 0 bon, 1 invalide, 2 illisible) |
| `ActivityEngine`, `heatmap_route` | En bibliothèque : le moteur et le gestionnaire de `GET /heatmap?camera=ID&format=json` (aussi `png` et `svg`), pour le service qui le montera ; ce dépôt n'a pas de serveur propre et la route répond 404 tant que la chaîne est éteinte |

```json
{"schema": "armor.vision.event/v1", "type": "alert", "camera_id": "cam-front", "zone_id": "drive",
 "zone_name": "Driveway", "track_id": 1, "label": "person", "confidence": 0.9,
 "box": [0.41, 0.62, 0.47, 0.82], "timestamp": 1.0, "authorizes_action": false}
```

En bibliothèque : `parse_config`, `Pipeline.process_detections` et `process_frame`. `load_detector("tensorrt")` lève `DetectorUnavailable` car le modèle pour le Jetson Orin NX n'est pas écrit. Voir [docs/USAGE.md](docs/USAGE.md).

## ⚙️ Configuration

| Nom | Ce qu'elle règle |
|---|---|
| `motion_threshold` | 1 à 255 : l'écart de gris qui compte comme changement |
| `motion_min_cells` | Combien de cellules de la grille 16 x 9 doivent changer avant de solliciter le détecteur |
| `zones[]` | `id`, `name`, `kind` (`alert` ou `detection`), `labels`, `min_frames`, `min_seconds`, `points` (polygone, 0 à 1) ; compté par les pieds de la boîte |
| `masks[]` | Polygones où le mouvement est ignoré ; les détections dont le centre est dedans sont écartées |
| `profiles` | Quelles zones sont surveillées dans chaque mode d'armement (`away`, `home`, ...) |
| `configuration d'activité (fichier à part)` | `enabled` (par défaut `false`), `heatmap` (`cols`, `rows`, `window_seconds`, `half_life_seconds`, `slices`, `max_cells` jusqu'à 65536, `position`, `labels`) et `events` (`dwell_seconds`, `loiter_seconds`, `loiter_radius`, `lost_seconds`, `labels`, `lines[]` avec `id`, `a`, `b`) ; la carte est normalisée comme poids divisé par le maximum |

| Limite | Valeur |
|---|---|
| Appariement d'une détection à une piste (recouvrement / portée) | 0.3 / 1.0 |
| Une piste en mouvement non vue est abandonnée après | 2 s |
| Immobile : fenêtre / dérive / mémorisé pendant | 3 s / 0.01 / 300 s |
| Grille de mouvement | 16 x 9 |

Ces valeurs sont aujourd'hui des constantes de `tracker.py` et `motion.py` ; le fichier de configuration contient les zones, masques, profils et seuils de mouvement.

## 🚀 Démarrage rapide

**Prérequis:** Python 3.11+ (bibliothèque standard uniquement).

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

## 🧪 Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Fichier de tests | Tests | Ce qu'il couvre |
|---|---|---|
| `test_vision.py` | 42 | Géométrie, configuration, mouvement, suivi, règles, profils, la chaîne et la ligne de commande |
| `test_vision_edges.py` | 19 | Les cas limites : mauvaises configurations, objets immobiles, détections masquées et détecteur indisponible |
| `test_characterization.py` | 2 | Fixe octet par octet la sortie de la simulation intégrée, pour qu'elle ne change pas tant que la chaîne d'activité est éteinte |
| `test_activity.py` | 27 | Configuration d'activité, sources synthétique et enregistrée, événements, carte de chaleur (déterminisme, somme égale aux détections, rien hors de la grille, fenêtre, décroissance, mémoire), le gestionnaire `/heatmap` et la ligne de commande |

## 🏗️ Compilation et publication

C'est du Python pur : rien à compiler. La version est dans `pyproject.toml` et `armor.project.json`.

## 🩺 Dépannage

| Vous voyez | Parce que | Faites |
|---|---|---|
| `check-config` se termine par 1 | La configuration a des problèmes ; il les liste tous | Corrigez-les tous : les champs inconnus sont des erreurs |
| `check-config` se termine par 2 | Le fichier est illisible | Vérifiez le chemin et que c'est du JSON |
| `DetectorUnavailable` | `load_detector("tensorrt")` : le vrai modèle n'est pas écrit | Utilisez `ScriptedDetector` |
| Une zone ne se déclenche jamais | Les pieds sont hors du polygone, l'étiquette n'est pas acceptée, un masque la cache, ou le mode n'a pas de profil avec cette zone | Lancez `simulate` avec le même fichier et mode |

## 📂 Structure du dépôt

<p align="center">
  <img src="images/repository-structure.svg" alt="Structure du dépôt de ARMOR-VISION" width="100%">
</p>

<details>
<summary>Version texte de l'arborescence</summary>

```text
ARMOR-VISION/
├── src/armor_vision/
│   ├── geometry.py                      polygones en coordonnées normalisées
│   ├── config.py                        zones, masques, profils et leur validation
│   ├── motion.py                        le contrôle de mouvement 16 x 9, masques ignorés
│   ├── detector.py                      détections scriptées ; le vrai modèle n'est pas écrit
│   ├── tracker.py                       identité entre images ; objets immobiles
│   ├── rules.py                         des zones aux événements : armor.vision.event/v1
│   ├── activity_config.py               réglages de la chaîne d'activité, éteinte par défaut
│   ├── sources.py heatmap.py            sources synthétique et enregistrée ; carte de chaleur
│   ├── activity.py                      événements et gestionnaire /heatmap
│   └── pipeline.py cli.py __main__.py   toute la chaîne et la ligne de commande
├── tests/                               les tests
├── docs/                                les guides de ce dépôt
├── tools/                               les contrôles CI partagés et les outils du projet
├── .github/                             workflow CI et modèles d'issues et de pull requests
├── images/                              bannière, icône et les deux images de ce README
├── build.sh build.bat                   build par le flux de projet partagé
├── test.sh test.bat                     lancer les tests par le flux partagé
├── run.sh run.bat                       démarrer par le flux de projet partagé
├── armor.project.json                   manifeste : version, rôle, maturité, commande de build
├── CHANGELOG.md                         ce qui a changé à chaque version
├── SECURITY.md SUPPORT.md LICENSE       politique de sécurité, support et licence
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   comment contribuer et le code de conduite
├── build-test.sh build-test.bat         lancer les tests par le flux partagé
├── pyproject.toml                       métadonnées du paquet
└── .gitattributes .gitignore            réglages Git
```

</details>

## 🗺️ Feuille de route et limites connues

**Limites connues aujourd'hui**

* Il n'y a pas encore de vrai modèle de détection et rien n'a tourné sur une caméra ni sur le Jetson Orin NX : la simulation utilise des détections scriptées.
* La source caméra ou RTSP de la chaîne d'activité relève du matériel et n'est pas écrite : aujourd'hui elle fonctionne sur une scène synthétique ou un fichier de détections. La carte de chaleur n'a pas ici de serveur HTTP, seulement le gestionnaire.
* L'événement ne fait pas encore partie du contrat d'ARMOR-COMMON.
* Les valeurs du suivi et du mouvement sont des constantes du code, pas du fichier de configuration.

**Ensuite**

* Écrire le modèle de détection pour le Jetson Orin NX et l'essayer avec une vraie caméra.
* Déplacer les constantes du suivi et du mouvement dans le fichier de configuration et mettre l'événement dans le contrat d'ARMOR-COMMON.

## 🌍 Langues

Le README et les textes existent en anglais, espagnol, français, italien, allemand, chinois, japonais et portugais européen.

## 🔗 Projets liés

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) est un système de sécurité périmétrique composé de dépôts indépendants. Chacun a sa propre version, ses propres tests et son propre README ; voici la famille :

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contrats de messages, validateurs, vecteurs de conformité et types générés
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware du nœud de terrain pour ESP32-S3 avec trois radars et son propre panneau web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocoles des onduleurs et batteries solaires et messages d'un nœud passerelle
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nœud électrique : compteurs, le message des mesures du réseau et les règles de commutation
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nœud et centrale d'alarme : zones, armement, temporisations, sirène et PIN, avec ou sans le serveur
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Panneau tactile : l'état du système sur un écran mural, armer et acquitter, et la maison de l'assistant vocal
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Le réseau local : ses appareils, internet et ce qui change
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinateur central : télémétrie, alarmes, appareils, relevés solaires et caméras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Console web : caméras, radar, alarmes, énergie solaire et concepteur de site 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Client Android de l'opérateur avec radar 2D/3D en direct
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Client opérateur iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Politique d'inférence visuelle qui explique ses décisions et n'agit jamais
* **ARMOR-VISION** (ce dépôt) - Zones de caméra, masques et règles de détection pour la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intentions vocales hors ligne avec une confirmation impossible à falsifier
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Boîtiers, électronique et matrice d'acceptation sur banc
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Déploiement, banc d'essai CM5, sauvegarde et TLS
* **[ARMOR-SIMULATOR](https://github.com/JuanenRac/ARMOR-SIMULATOR)** - Simulateur de télémétrie hors ligne avec des pannes reproductibles
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Détecte, installe et met à jour les propres dépôts de l'écosystème
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architecture, base de sécurité et matrice des capacités

## 📚 Documentation

* [Utilisation](docs/USAGE.md) : les commandes, la configuration, l'événement et la bibliothèque
* [Matrice des capacités : ce qui est prouvé et ce qui ne l'est pas](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catalogue des projets : versions et dépendances entre les dépôts](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Historique des modifications de ce dépôt](CHANGELOG.md)

## 🤝 Contribuer et communauté

* Avant une pull request, lancez `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` : il doit réussir. Voir [CONTRIBUTING.md](CONTRIBUTING.md) et le [code de conduite](CODE_OF_CONDUCT.md).
* Le README existe en huit langues et est généré à partir des sources d'ARMOR-DOCS : une modification du texte se fait là-bas.
* Une modification d'un message entre composants commence dans ARMOR-COMMON.
* Ne décrivez pas comme fonctionnant sur une carte ce qui a seulement été compilé.
* Signalez une vulnérabilité en privé : [SECURITY.md](SECURITY.md). Questions, idées et rapports : electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTEUR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCE

GPL-3.0-or-later - voir [LICENSE](LICENSE).
