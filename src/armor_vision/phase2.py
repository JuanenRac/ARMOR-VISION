"""Second phase of the vision service: search by meaning, licence plates and faces. Everything here is OFF until the owner turns it on.

These three features read personal data (a plate identifies a vehicle and its keeper, a face identifies a person), so each has its own switch, all off by default, and
none can be turned on without the owner acknowledging the privacy notice of that feature (which exists in the eight languages of the project). A disabled feature
raises `FeatureDisabled` and does nothing: it is never half on. The readers behind each feature are interfaces; the only ones that exist are the simulated ones
(`SimulatedEmbedder`, `SimulatedPlateReader`, `SimulatedFaceMatcher`), so every result carries `evidence = "simulator"`. Nothing leaves the machine: results are
returned to the caller, and a face is only ever compared with the people the owner enrolled, never looked up anywhere else.

Around the features: an administrator-only role for lists, export and erasure, retention in days, a hash-chained audit log without personal data, and an encrypted vault for what is remembered. This module imports nothing that can open a connection.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from .geometry import Box
from .motion import Frame

EVIDENCE = "simulator"
FEATURES = ("semantic_search", "plates", "faces")
LANGUAGES = ("en", "es", "de", "fr", "it", "ja", "zh", "pt")

PRIVACY_NOTICE: dict[str, dict[str, str]] = {
    "semantic_search": {
        "en": "Search by meaning indexes what the cameras see so it can be searched with words. The index holds descriptions of people and vehicles; keep it only as long as you need it and only on this machine.",
        "es": "La búsqueda semántica indexa lo que ven las cámaras para poder buscarlo con palabras. El índice guarda descripciones de personas y vehículos; consérvalo solo el tiempo necesario y solo en esta máquina.",
        "de": "Die semantische Suche indiziert, was die Kameras sehen, damit es mit Worten gesucht werden kann. Der Index enthält Beschreibungen von Personen und Fahrzeugen; bewahren Sie ihn nur so lange wie nötig und nur auf diesem Rechner auf.",
        "fr": "La recherche sémantique indexe ce que voient les caméras afin de pouvoir le chercher avec des mots. L'index contient des descriptions de personnes et de véhicules ; ne le gardez que le temps nécessaire et seulement sur cette machine.",
        "it": "La ricerca semantica indicizza ciò che vedono le telecamere per poterlo cercare con le parole. L'indice contiene descrizioni di persone e veicoli; conservalo solo per il tempo necessario e solo su questa macchina.",
        "ja": "意味検索は、カメラに映ったものを言葉で検索できるように索引化します。索引には人物や車両の説明が含まれます。必要な期間だけ、このマシン上にのみ保管してください。",
        "zh": "语义搜索会为摄像头看到的内容建立索引，以便用文字检索。索引包含对人员和车辆的描述；请仅在需要的时间内保存，并且只保存在这台机器上。",
        "pt": "A pesquisa semântica indexa o que as câmaras veem para que possa ser procurado com palavras. O índice contém descrições de pessoas e veículos; guarde-o apenas o tempo necessário e só neste computador.",
    },
    "plates": {
        "en": "Reading licence plates identifies vehicles and, through them, their keepers. In many countries (GDPR in the European Union) this needs a lawful reason, a notice to the people filmed and a short retention. Turn it on only if you have that.",
        "es": "Leer matrículas identifica vehículos y, a través de ellos, a sus titulares. En muchos países (RGPD en la Unión Europea) exige una base legítima, aviso a las personas grabadas y una conservación breve. Actívalo solo si lo tienes.",
        "de": "Das Lesen von Kennzeichen identifiziert Fahrzeuge und damit deren Halter. In vielen Ländern (DSGVO in der Europäischen Union) braucht das einen rechtmäßigen Grund, einen Hinweis an die gefilmten Personen und eine kurze Aufbewahrung. Schalten Sie es nur ein, wenn Sie das haben.",
        "fr": "La lecture des plaques identifie les véhicules et, par eux, leurs titulaires. Dans de nombreux pays (RGPD dans l'Union européenne), elle exige une base légitime, une information des personnes filmées et une conservation courte. Ne l'activez que si vous remplissez ces conditions.",
        "it": "La lettura delle targhe identifica i veicoli e, tramite essi, i loro intestatari. In molti paesi (GDPR nell'Unione europea) richiede una base legittima, un'informativa alle persone riprese e una conservazione breve. Attivala solo se le hai.",
        "ja": "ナンバープレートの読み取りは車両を特定し、ひいてはその所有者を特定します。多くの国（EUではGDPR）で、正当な根拠、撮影される人への通知、短い保存期間が必要です。それらを満たす場合にのみ有効にしてください。",
        "zh": "读取车牌会识别车辆，进而识别车主。在许多国家（欧盟为 GDPR）这需要合法依据、向被拍摄者告知以及较短的保存期限。仅在满足这些条件时才启用。",
        "pt": "A leitura de matrículas identifica veículos e, através deles, os seus titulares. Em muitos países (RGPD na União Europeia) exige um fundamento legítimo, aviso às pessoas filmadas e uma conservação curta. Ative-a só se cumprir isso.",
    },
    "faces": {
        "en": "Face recognition processes biometric data, a special category of personal data. In the European Union (GDPR) it is forbidden without explicit consent or another narrow legal basis. Only people who enrolled themselves are compared; nobody else is identified. Turn it on only if you have that consent.",
        "es": "El reconocimiento facial trata datos biométricos, una categoría especial de datos personales. En la Unión Europea (RGPD) está prohibido sin consentimiento explícito u otra base legal muy limitada. Solo se compara a las personas que se han dado de alta ellas mismas; a nadie más se le identifica. Actívalo solo si tienes ese consentimiento.",
        "de": "Die Gesichtserkennung verarbeitet biometrische Daten, eine besondere Kategorie personenbezogener Daten. In der Europäischen Union (DSGVO) ist sie ohne ausdrückliche Einwilligung oder eine andere eng gefasste Rechtsgrundlage verboten. Verglichen werden nur Personen, die sich selbst registriert haben; niemand sonst wird identifiziert. Schalten Sie sie nur mit dieser Einwilligung ein.",
        "fr": "La reconnaissance faciale traite des données biométriques, une catégorie particulière de données personnelles. Dans l'Union européenne (RGPD), elle est interdite sans consentement explicite ou autre base légale étroite. Seules les personnes qui se sont inscrites elles-mêmes sont comparées ; personne d'autre n'est identifié. Ne l'activez qu'avec ce consentement.",
        "it": "Il riconoscimento facciale tratta dati biometrici, una categoria particolare di dati personali. Nell'Unione europea (GDPR) è vietato senza consenso esplicito o un'altra base giuridica ristretta. Vengono confrontate solo le persone che si sono registrate da sole; nessun altro viene identificato. Attivalo solo con tale consenso.",
        "ja": "顔認識は生体データという特別な種類の個人データを処理します。EU（GDPR）では、明示的な同意またはその他の限定的な法的根拠がなければ禁止されています。自分で登録した人だけが照合され、それ以外の人は特定されません。その同意がある場合にのみ有効にしてください。",
        "zh": "人脸识别处理生物识别数据，属于特殊类别的个人数据。在欧盟（GDPR）中，没有明确同意或其他严格的法律依据是被禁止的。只会比对自行登记的人员，不会识别其他任何人。仅在取得该同意后才启用。",
        "pt": "O reconhecimento facial trata dados biométricos, uma categoria especial de dados pessoais. Na União Europeia (RGPD) é proibido sem consentimento explícito ou outro fundamento legal restrito. Só são comparadas as pessoas que se registaram a si próprias; mais ninguém é identificado. Ative-o só com esse consentimento.",
    },
}


class FeatureDisabled(RuntimeError):
    """The feature is off, or its privacy notice was not acknowledged."""


def privacy_notice(feature: str, language: str = "en") -> str:
    if feature not in PRIVACY_NOTICE:
        raise KeyError(f"unknown feature {feature!r}")
    return PRIVACY_NOTICE[feature].get(language, PRIVACY_NOTICE[feature]["en"])


@dataclass(frozen=True)
class Phase2Settings:
    semantic_search: bool = False
    plates: bool = False
    faces: bool = False
    acknowledged: tuple[str, ...] = ()       # features whose privacy notice the owner accepted
    retention_days: int = 30                 # sightings and index entries older than this are erased (1..3650)
    audit_file: str = ""                     # hash-chained log of every use ("" = kept in memory only)
    vault_file: str = ""                     # encrypted file holding what the features remember ("" = memory only)
    key_file: str = ""                       # 32 bytes of key for the vault; created with owner-only permissions if missing, never part of the settings

    def enabled(self, feature: str) -> bool:
        return bool(getattr(self, feature)) and feature in self.acknowledged


def parse_phase2_settings(raw: Any) -> tuple[Phase2Settings | None, list[str]]:
    """`{"semantic_search": false, "plates": true, "faces": false, "acknowledged": ["plates"]}`. A switch on without the acknowledgement of its notice is an error, never a silent on."""
    if raw is None:
        return Phase2Settings(), []
    if not isinstance(raw, dict):
        return None, ["the second-phase settings must be an object"]
    known = set(FEATURES) | {"acknowledged", "retention_days", "audit_file", "vault_file", "key_file"}
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - known))}"] if set(raw) - known else []
    flags = {}
    for feature in FEATURES:
        value = raw.get(feature, False)
        if not isinstance(value, bool):
            errors.append(f"{feature} must be true or false")
        flags[feature] = value is True
    acknowledged = raw.get("acknowledged", [])
    if not isinstance(acknowledged, list) or not all(a in FEATURES for a in acknowledged):
        errors.append(f"acknowledged is a list of {', '.join(FEATURES)}")
        acknowledged = []
    for feature in FEATURES:
        if flags[feature] and feature not in acknowledged:
            errors.append(f"{feature} is on but its privacy notice was not acknowledged: read it (privacy_notice) and add {feature!r} to acknowledged")
    retention = raw.get("retention_days", 30)
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= 3650:
        errors.append("retention_days is a whole number of days from 1 to 3650")
        retention = 30
    paths = {}
    for name in ("audit_file", "vault_file", "key_file"):
        value = raw.get(name, "")
        if not isinstance(value, str) or value != value.strip():
            errors.append(f"{name} is a path (or empty for memory only)")
            value = ""
        paths[name] = value
    if paths["vault_file"] and not paths["key_file"]:
        errors.append("vault_file needs key_file: what is remembered is always encrypted")
    if errors:
        return None, errors
    return Phase2Settings(flags["semantic_search"], flags["plates"], flags["faces"], tuple(a for a in FEATURES if a in acknowledged), retention, **paths), []


# ---------------------------------------------------------------- readers (interfaces) and their simulated stand-ins

class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class PlateReader(Protocol):
    def read(self, frame: Frame, box: Box) -> tuple[str, float] | None: ...


class FaceMatcher(Protocol):
    def match(self, frame: Frame, box: Box, enrolled: dict[str, list[float]]) -> tuple[str, float] | None: ...


class SimulatedEmbedder:
    """A bag of hashed words: texts that share words are close. Stands in for a real model; evidence is `simulator`."""

    evidence = EVIDENCE

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.lower()):
            vector[int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector


class SimulatedPlateReader:
    evidence = EVIDENCE

    def __init__(self, script: dict[tuple[float, ...], tuple[str, float]] | None = None) -> None:
        self._script = script or {}

    def read(self, frame: Frame, box: Box) -> tuple[str, float] | None:
        return self._script.get(tuple(box))


class SimulatedFaceMatcher:
    evidence = EVIDENCE

    def __init__(self, script: dict[tuple[float, ...], tuple[str, float]] | None = None) -> None:
        self._script = script or {}

    def match(self, frame: Frame, box: Box, enrolled: dict[str, list[float]]) -> tuple[str, float] | None:
        found = self._script.get(tuple(box))
        return found if found is not None and found[0] in enrolled else None     # only an enrolled person can ever be named


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))   # vectors of different length are compared on the part they share
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


PLATE = re.compile(r"^[A-Z0-9]{2,5}[ -]?[A-Z0-9]{2,5}$")


# ---------------------------------------------------------------- who may do what, and the record of it

ADMIN = "admin"
ROLES = (ADMIN, "operator", "service")
CONFIRMATION: dict[str, str] = {
    "en": "I have read the notice, I have a lawful reason and I confirm that I want to turn this feature on.",
    "es": "He leído el aviso, tengo una base legítima y confirmo que quiero activar esta función.",
    "de": "Ich habe den Hinweis gelesen, habe einen rechtmäßigen Grund und bestätige, dass ich diese Funktion einschalten möchte.",
    "fr": "J'ai lu l'avis, j'ai une base légitime et je confirme vouloir activer cette fonction.",
    "it": "Ho letto l'avviso, ho una base legittima e confermo di voler attivare questa funzione.",
    "ja": "通知を読み、正当な根拠があることを確認のうえ、この機能を有効にします。",
    "zh": "我已阅读告知，具有合法依据，并确认要启用此功能。",
    "pt": "Li o aviso, tenho um fundamento legítimo e confirmo que quero ativar esta funcionalidade.",
}


class PermissionDenied(PermissionError):
    """Managing the lists, exporting and erasing belong to the administrator only."""


@dataclass(frozen=True)
class Actor:
    name: str
    role: str = "operator"

    def __post_init__(self) -> None:
        if not self.name or self.role not in ROLES:
            raise ValueError(f"an actor has a name and a role among {', '.join(ROLES)}")


SERVICE = Actor("service", "service")      # the detection loop: it may read, never manage


def confirmation_text(language: str = "en") -> str:
    return CONFIRMATION.get(language, CONFIRMATION["en"])


class AuditLog:
    """Every use of a feature, one JSON line each, chained by hash so that a removed or edited line is found by `verify`. It never holds a plate, a name or a description: only a salted
    digest of the subject, so the log can be read by an auditor without exposing anybody."""

    def __init__(self, path: str = "", clock: Callable[[], float] = time.time, salt: bytes = b"") -> None:
        self._path = Path(path) if path else None
        self._clock = clock
        self._salt = salt
        self.lines: list[str] = []
        if self._path is not None and self._path.exists():
            self.lines = [ln for ln in self._path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def subject_digest(self, subject: str) -> str:
        return hmac.new(self._salt or b"armor-vision-audit", subject.encode(), "sha256").hexdigest()[:16]

    def record(self, actor: Actor, action: str, feature: str, subject: str = "", result: str = "ok") -> dict[str, Any]:
        previous = json.loads(self.lines[-1])["hash"] if self.lines else "0" * 64
        entry: dict[str, Any] = {"seq": len(self.lines) + 1, "time": round(self._clock(), 3), "actor": actor.name, "role": actor.role, "action": action, "feature": feature,
                                 "subject": self.subject_digest(subject) if subject else "", "result": result, "previous": previous}
        entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        line = json.dumps(entry, sort_keys=True)
        self.lines.append(line)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(ln) for ln in self.lines]

    def verify(self) -> int | None:
        """None when the chain is whole, otherwise the number of the first line that does not follow."""
        previous = "0" * 64
        for number, line in enumerate(self.lines, 1):
            try:
                entry = json.loads(line)
                claimed = entry.pop("hash")
            except (ValueError, KeyError, AttributeError, TypeError):
                return number
            if entry.get("previous") != previous or entry.get("seq") != number or hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest() != claimed:
                return number
            previous = claimed
        return None


# ---------------------------------------------------------------- encryption at rest (standard library only)

KEY_BYTES = 32
NONCE_BYTES = 16
TAG_BYTES = 32


class VaultError(ValueError):
    """The vault cannot be opened: wrong key, damaged or tampered file."""


def load_key(path: str) -> bytes:
    """The key of the vault; made from the system random source with owner-only permissions the first time. It is never printed, logged or put in the settings."""
    file = Path(path)
    if file.exists():
        key = file.read_bytes()
        if len(key) != KEY_BYTES:
            raise VaultError(f"the key file must hold exactly {KEY_BYTES} bytes")
        return key
    file.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(KEY_BYTES)
    descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


def _stream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(b) for b in blocks) < length:
        blocks.append(hmac.new(enc_key, nonce + counter.to_bytes(8, "big"), "sha256").digest())
        counter += 1
    return b"".join(blocks)[:length]


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    return hmac.new(key, b"armor-vision/enc", "sha256").digest(), hmac.new(key, b"armor-vision/mac", "sha256").digest()


def seal(key: bytes, plain: bytes, nonce: bytes | None = None) -> bytes:
    """Encrypt then authenticate: nonce + ciphertext + tag (HMAC-SHA256 keystream, HMAC-SHA256 tag)."""
    enc_key, mac_key = _subkeys(key)
    nonce = nonce if nonce is not None else os.urandom(NONCE_BYTES)
    cipher = bytes(a ^ b for a, b in zip(plain, _stream(enc_key, nonce, len(plain)), strict=True))
    return nonce + cipher + hmac.new(mac_key, nonce + cipher, "sha256").digest()


def unseal(key: bytes, sealed: bytes) -> bytes:
    if len(sealed) < NONCE_BYTES + TAG_BYTES:
        raise VaultError("the vault is too short to be one")
    enc_key, mac_key = _subkeys(key)
    nonce, cipher, tag = sealed[:NONCE_BYTES], sealed[NONCE_BYTES:-TAG_BYTES], sealed[-TAG_BYTES:]
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + cipher, "sha256").digest()):
        raise VaultError("the vault does not open with this key or was changed")
    return bytes(a ^ b for a, b in zip(cipher, _stream(enc_key, nonce, len(cipher)), strict=True))


def normalise_plate(text: str) -> str:
    return re.sub(r"[\s-]", "", text.upper())


# ---------------------------------------------------------------- synthetic sources (for tests and the bench: no real people, no real plates)

def scripted_readers(raw: Any) -> tuple[SimulatedPlateReader, SimulatedFaceMatcher]:
    """Builds the simulated readers from a file of made-up readings: `{"plates": [{"box": [x1,y1,x2,y2], "text": "1234 ABC", "confidence": 0.9}], "faces": [{"box": [...], "person": "demo", "confidence": 0.9}]}`."""
    if not isinstance(raw, dict) or set(raw) - {"plates", "faces"}:
        raise ValueError("a script of readings has only 'plates' and 'faces'")
    plates: dict[tuple[float, ...], tuple[str, float]] = {}
    faces: dict[tuple[float, ...], tuple[str, float]] = {}
    for key, target, label in (("plates", plates, "text"), ("faces", faces, "person")):
        for item in raw.get(key, []):
            box = item.get("box") if isinstance(item, dict) else None
            confidence = item.get("confidence") if isinstance(item, dict) else None
            if (not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
                    or not isinstance(item.get(label), str) or isinstance(confidence, bool) or not isinstance(confidence, (int, float))):
                raise ValueError(f"every {key} reading has a box of four numbers, a {label} and a confidence")
            target[tuple(float(v) for v in box)] = (item[label], float(confidence))
    return SimulatedPlateReader(plates), SimulatedFaceMatcher(faces)


def load_scripted_readers(path: str) -> tuple[SimulatedPlateReader, SimulatedFaceMatcher]:
    return scripted_readers(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------- the features

class Phase2:
    """The three features behind their switches. Each call checks its switch first, is written to the audit log, and what is remembered goes into the encrypted vault only.

    Nothing here opens a connection: no result, index or template is ever sent anywhere, not even to an outside AI. Managing the lists, exporting and erasing need an administrator."""

    def __init__(self, settings: Phase2Settings, embedder: Embedder | None = None, plates: PlateReader | None = None, faces: FaceMatcher | None = None,
                 clock: Callable[[], float] = time.time, audit: AuditLog | None = None, key: bytes | None = None) -> None:
        self.settings = settings
        self._embedder = embedder or SimulatedEmbedder()
        self._plates = plates or SimulatedPlateReader()
        self._faces = faces or SimulatedFaceMatcher()
        self._clock = clock
        self._key = key
        if self._key is None and settings.key_file:
            self._key = load_key(settings.key_file)
        self.audit = audit or AuditLog(settings.audit_file, clock, self._key or b"")
        self._index: list[tuple[str, dict[str, Any], list[float], float]] = []
        self._enrolled: dict[str, list[float]] = {}
        self._allowed: dict[str, str] = {}                      # normalised plate -> label of the authorised vehicle
        self._sightings: list[tuple[str, str, float]] = []      # plate, camera, time
        self._vault = Path(settings.vault_file) if settings.vault_file else None
        if self._vault is not None and self._key is None:
            raise VaultError("a vault needs a key")
        if self._vault is not None and self._vault.exists():
            self._load()

    # --- guards
    def _require(self, feature: str) -> None:
        if not self.settings.enabled(feature):
            raise FeatureDisabled(f"{feature} is off (or its privacy notice is not acknowledged)")

    def _admin(self, actor: Actor | None, action: str, feature: str, subject: str = "") -> Actor:
        if actor is None or actor.role != ADMIN:
            self.audit.record(actor or Actor("unknown", "service"), action, feature, subject, "denied")
            raise PermissionDenied(f"{action} is for the administrator only")
        return actor

    # --- the vault
    def _state(self) -> dict[str, Any]:
        return {"index": [[i, m, v, t] for i, m, v, t in self._index], "enrolled": self._enrolled, "allowed": self._allowed, "sightings": [list(s) for s in self._sightings]}

    def _save(self) -> None:
        if self._vault is None or self._key is None:
            return
        self._vault.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._vault.with_suffix(self._vault.suffix + ".tmp")
        temporary.write_bytes(seal(self._key, json.dumps(self._state(), sort_keys=True).encode()))
        os.replace(temporary, self._vault)

    def _load(self) -> None:
        assert self._vault is not None and self._key is not None
        try:
            state = json.loads(unseal(self._key, self._vault.read_bytes()))
            self._index = [(str(i), dict(m), [float(x) for x in v], float(t)) for i, m, v, t in state["index"]]
            self._enrolled = {str(k): [float(x) for x in v] for k, v in state["enrolled"].items()}
            self._allowed = {str(k): str(v) for k, v in state["allowed"].items()}
            self._sightings = [(str(p), str(c), float(t)) for p, c, t in state["sightings"]]
        except (ValueError, KeyError, TypeError) as error:
            raise VaultError("the vault cannot be read") from error

    # --- enabling with an explicit confirmation
    def enable(self, actor: Actor | None, feature: str, confirmed: bool) -> Phase2Settings:
        """Turns a feature on for this object: administrator only, and only with the explicit confirmation of the notice (`confirmation_text`). The settings file still has to say so to survive a restart."""
        if feature not in FEATURES:
            raise KeyError(f"unknown feature {feature!r}")
        self._admin(actor, "enable", feature)
        assert actor is not None
        if confirmed is not True:
            self.audit.record(actor, "enable", feature, "", "not-confirmed")
            raise FeatureDisabled("a feature is turned on only after the notice is confirmed")
        flags: dict[str, Any] = {f: getattr(self.settings, f) for f in FEATURES}
        flags[feature] = True
        self.settings = replace(self.settings, **flags, acknowledged=tuple(f for f in FEATURES if f in self.settings.acknowledged or f == feature))
        self.audit.record(actor, "enable", feature)
        return self.settings

    def disable(self, actor: Actor | None, feature: str) -> Phase2Settings:
        if feature not in FEATURES:
            raise KeyError(f"unknown feature {feature!r}")
        self._admin(actor, "disable", feature)
        assert actor is not None
        off: dict[str, Any] = {feature: False}
        self.settings = replace(self.settings, **off)
        self.audit.record(actor, "disable", feature)
        return self.settings

    # --- retention
    def purge(self, now: float | None = None) -> dict[str, int]:
        """Erases the index entries and the plate sightings older than `retention_days`. Runs before every read; the people who enrolled stay until they ask to leave."""
        limit = (self._clock() if now is None else now) - self.settings.retention_days * 86400
        index, sightings = len(self._index), len(self._sightings)
        self._index = [e for e in self._index if e[3] >= limit]
        self._sightings = [s for s in self._sightings if s[2] >= limit]
        gone = {"index": index - len(self._index), "sightings": sightings - len(self._sightings)}
        if gone["index"] or gone["sightings"]:
            self._save()
            self.audit.record(SERVICE, "retention-purge", "retention", "", f"{gone['index']}+{gone['sightings']}")
        return gone

    # --- semantic search
    def index(self, entry_id: str, description: str, meta: dict[str, Any] | None = None, actor: Actor = SERVICE) -> None:
        self._require("semantic_search")
        self._index.append((entry_id, dict(meta or {}), self._embedder.embed(description), self._clock()))
        self._save()
        self.audit.record(actor, "index", "semantic_search", entry_id)

    def search(self, query: str, limit: int = 5, min_score: float = 0.1, actor: Actor = SERVICE) -> list[dict[str, Any]]:
        self._require("semantic_search")
        self.purge()
        vector = self._embedder.embed(query)
        scored = sorted(((round(_cosine(vector, v), 4), i, m) for i, m, v, _ in self._index), key=lambda r: (-r[0], r[1]))
        found = [{"id": i, "score": s, "meta": m, "evidence": EVIDENCE} for s, i, m in scored if s >= min_score][:max(0, limit)]
        self.audit.record(actor, "search", "semantic_search", query, f"{len(found)}")
        return found

    def forget_index(self, actor: Actor | None = None) -> int:
        """Erases the whole index (the way out for the owner and for a request to delete)."""
        self._admin(actor, "forget-index", "semantic_search")
        assert actor is not None
        count = len(self._index)
        self._index.clear()
        self._save()
        self.audit.record(actor, "forget-index", "semantic_search", "", f"{count}")
        return count

    # --- plates: the list of authorised vehicles is the administrator's
    def allow_plate(self, actor: Actor | None, plate: str, label: str = "") -> None:
        self._require("plates")
        self._admin(actor, "allow-plate", "plates", plate)
        assert actor is not None
        text = normalise_plate(plate)
        if not PLATE.match(text):
            raise ValueError("that is not a plate")
        self._allowed[text] = label
        self._save()
        self.audit.record(actor, "allow-plate", "plates", text)

    def disallow_plate(self, actor: Actor | None, plate: str) -> bool:
        self._admin(actor, "disallow-plate", "plates", plate)
        assert actor is not None
        removed = self._allowed.pop(normalise_plate(plate), None) is not None
        self._save()
        self.audit.record(actor, "disallow-plate", "plates", normalise_plate(plate), "ok" if removed else "absent")
        return removed

    def allowed_plates(self, actor: Actor | None) -> dict[str, str]:
        self._admin(actor, "list-plates", "plates")
        assert actor is not None
        self.audit.record(actor, "list-plates", "plates", "", f"{len(self._allowed)}")
        return dict(self._allowed)

    def read_plate(self, frame: Frame, box: Box, min_confidence: float = 0.6, camera: str = "", actor: Actor = SERVICE) -> dict[str, Any] | None:
        self._require("plates")
        self.purge()
        found = self._plates.read(frame, box)
        if found is None:
            self.audit.record(actor, "read-plate", "plates", "", "none")
            return None
        text, confidence = found
        text = text.upper().strip()
        if not PLATE.match(text) or not min_confidence <= confidence <= 1.0:
            self.audit.record(actor, "read-plate", "plates", "", "rejected")
            return None
        self._sightings.append((normalise_plate(text), camera, self._clock()))
        self._save()
        self.audit.record(actor, "read-plate", "plates", text)
        return {"plate": text, "confidence": round(confidence, 3), "authorized": normalise_plate(text) in self._allowed, "evidence": EVIDENCE, "authorizes_action": False}

    # --- faces: only people who enrolled themselves
    def enrol(self, person: str, template: list[float], consent: bool, actor: Actor | None = None) -> None:
        self._require("faces")
        self._admin(actor, "enrol", "faces", person)
        assert actor is not None
        if consent is not True:
            self.audit.record(actor, "enrol", "faces", person, "no-consent")
            raise FeatureDisabled("a person is enrolled only with their own explicit consent")
        self._enrolled[person] = list(template)
        self._save()
        self.audit.record(actor, "enrol", "faces", person)

    def unenrol(self, person: str, actor: Actor | None = None) -> bool:
        self._admin(actor, "unenrol", "faces", person)
        assert actor is not None
        removed = self._enrolled.pop(person, None) is not None
        self._save()
        self.audit.record(actor, "unenrol", "faces", person, "ok" if removed else "absent")
        return removed

    def match_face(self, frame: Frame, box: Box, min_confidence: float = 0.7, actor: Actor = SERVICE) -> dict[str, Any] | None:
        self._require("faces")
        found = self._faces.match(frame, box, self._enrolled)
        if found is None or not min_confidence <= found[1] <= 1.0:
            self.audit.record(actor, "match-face", "faces", "", "none")
            return None
        self.audit.record(actor, "match-face", "faces", found[0])
        return {"person": found[0], "confidence": round(found[1], 3), "evidence": EVIDENCE, "authorizes_action": False}

    # --- the right of access and of erasure (administrator, on request)
    def _of_subject(self, subject: str) -> dict[str, Any]:
        plate = normalise_plate(subject)
        return {"enrolled": subject in self._enrolled,
                "authorised_vehicle": self._allowed.get(plate),
                "sightings": [{"plate": p, "camera": c, "time": t} for p, c, t in self._sightings if p == plate],
                "index_entries": [i for i, m, _, _ in self._index if m.get("subject") == subject or i == subject]}

    def export_subject(self, actor: Actor | None, subject: str) -> dict[str, Any]:
        """Everything held about a person (by name) or a vehicle (by plate), as plain data for the person who asked. Biometric templates are not handed out, only whether one exists."""
        self._admin(actor, "export", "subject", subject)
        assert actor is not None
        data = {"subject": subject, "evidence": EVIDENCE, **self._of_subject(subject)}
        self.audit.record(actor, "export", "subject", subject)
        return data

    def erase_subject(self, actor: Actor | None, subject: str) -> dict[str, int]:
        self._admin(actor, "erase", "subject", subject)
        assert actor is not None
        plate = normalise_plate(subject)
        counts = {"enrolled": int(self._enrolled.pop(subject, None) is not None), "authorised_vehicle": int(self._allowed.pop(plate, None) is not None),
                  "sightings": sum(1 for s in self._sightings if s[0] == plate), "index_entries": sum(1 for e in self._index if e[1].get("subject") == subject or e[0] == subject)}
        self._sightings = [s for s in self._sightings if s[0] != plate]
        self._index = [e for e in self._index if not (e[1].get("subject") == subject or e[0] == subject)]
        self._save()
        self.audit.record(actor, "erase", "subject", subject, str(sum(counts.values())))
        return counts

    def erase_everything(self, actor: Actor | None) -> None:
        """Erases what every feature remembers and the vault file itself (the audit log stays: it holds no personal data)."""
        self._admin(actor, "erase-all", "all")
        assert actor is not None
        self._index.clear()
        self._enrolled.clear()
        self._allowed.clear()
        self._sightings.clear()
        if self._vault is not None and self._vault.exists():
            self._vault.write_bytes(os.urandom(max(64, self._vault.stat().st_size)))   # overwritten before it is removed
            self._vault.unlink()
        self.audit.record(actor, "erase-all", "all")
