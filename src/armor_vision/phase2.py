"""Second phase of the vision service: search by meaning, licence plates and faces. Everything here is OFF until the owner turns it on.

These three features read personal data (a plate identifies a vehicle and its keeper, a face identifies a person), so each has its own switch, all off by default, and
none can be turned on without the owner acknowledging the privacy notice of that feature (which exists in the eight languages of the project). A disabled feature
raises `FeatureDisabled` and does nothing: it is never half on. The readers behind each feature are interfaces; the only ones that exist are the simulated ones
(`SimulatedEmbedder`, `SimulatedPlateReader`, `SimulatedFaceMatcher`), so every result carries `evidence = "simulator"`. Nothing leaves the machine: results are
returned to the caller, and a face is only ever compared with the people the owner enrolled, never looked up anywhere else.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

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

    def enabled(self, feature: str) -> bool:
        return bool(getattr(self, feature)) and feature in self.acknowledged


def parse_phase2_settings(raw: Any) -> tuple[Phase2Settings | None, list[str]]:
    """`{"semantic_search": false, "plates": true, "faces": false, "acknowledged": ["plates"]}`. A switch on without the acknowledgement of its notice is an error, never a silent on."""
    if raw is None:
        return Phase2Settings(), []
    if not isinstance(raw, dict):
        return None, ["the second-phase settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - set(FEATURES) - {'acknowledged'}))}"] if set(raw) - set(FEATURES) - {"acknowledged"} else []
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
    if errors:
        return None, errors
    return Phase2Settings(flags["semantic_search"], flags["plates"], flags["faces"], tuple(a for a in FEATURES if a in acknowledged)), []


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


class Phase2:
    """The three features behind their switches. Each call checks its switch first."""

    def __init__(self, settings: Phase2Settings, embedder: Embedder | None = None, plates: PlateReader | None = None, faces: FaceMatcher | None = None) -> None:
        self.settings = settings
        self._embedder = embedder or SimulatedEmbedder()
        self._plates = plates or SimulatedPlateReader()
        self._faces = faces or SimulatedFaceMatcher()
        self._index: list[tuple[str, dict[str, Any], list[float]]] = []
        self._enrolled: dict[str, list[float]] = {}

    def _require(self, feature: str) -> None:
        if not self.settings.enabled(feature):
            raise FeatureDisabled(f"{feature} is off (or its privacy notice is not acknowledged)")

    # semantic search
    def index(self, entry_id: str, description: str, meta: dict[str, Any] | None = None) -> None:
        self._require("semantic_search")
        self._index.append((entry_id, dict(meta or {}), self._embedder.embed(description)))

    def search(self, query: str, limit: int = 5, min_score: float = 0.1) -> list[dict[str, Any]]:
        self._require("semantic_search")
        vector = self._embedder.embed(query)
        scored = sorted(((round(_cosine(vector, v), 4), i, m) for i, m, v in self._index), key=lambda r: (-r[0], r[1]))
        return [{"id": i, "score": s, "meta": m, "evidence": EVIDENCE} for s, i, m in scored if s >= min_score][:max(0, limit)]

    def forget_index(self) -> int:
        """Erases the whole index (the way out for the owner and for a request to delete)."""
        count = len(self._index)
        self._index.clear()
        return count

    # plates
    def read_plate(self, frame: Frame, box: Box, min_confidence: float = 0.6) -> dict[str, Any] | None:
        self._require("plates")
        found = self._plates.read(frame, box)
        if found is None:
            return None
        text, confidence = found
        text = text.upper().strip()
        if not PLATE.match(text) or not min_confidence <= confidence <= 1.0:
            return None
        return {"plate": text, "confidence": round(confidence, 3), "evidence": EVIDENCE, "authorizes_action": False}

    # faces: only people who enrolled themselves
    def enrol(self, person: str, template: list[float], consent: bool) -> None:
        self._require("faces")
        if consent is not True:
            raise FeatureDisabled("a person is enrolled only with their own explicit consent")
        self._enrolled[person] = list(template)

    def unenrol(self, person: str) -> bool:
        return self._enrolled.pop(person, None) is not None

    def match_face(self, frame: Frame, box: Box, min_confidence: float = 0.7) -> dict[str, Any] | None:
        self._require("faces")
        found = self._faces.match(frame, box, self._enrolled)
        if found is None or not min_confidence <= found[1] <= 1.0:
            return None
        return {"person": found[0], "confidence": round(found[1], 3), "evidence": EVIDENCE, "authorizes_action": False}
