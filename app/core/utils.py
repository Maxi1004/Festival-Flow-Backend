from datetime import datetime, timezone
import re
import unicodedata


CREW_CATEGORY_LABELS = {
    "ACTOR": "Actor / Actress",
    "CAMERA": "Camera",
    "SOUND": "Sound",
    "LIGHTING": "Lighting",
    "PRODUCTION": "Production",
    "ART": "Art",
    "FX": "FX",
    "MAKEUP": "Makeup",
    "HAIR": "Hair",
    "WARDROBE": "Wardrobe",
    "STUNT": "Stunt",
    "CATERING": "Catering",
    "OTHER": "Other",
}

_CREW_CATEGORY_ALIASES = {
    "ACTOR": (
        "actor",
        "actriz",
        "actor principal",
        "actor secundario",
        "actriz principal",
        "extra",
        "villano",
    ),
    "CAMERA": (
        "camera",
        "camara",
        "camarografo",
        "operador camara",
        "director fotografia",
        "director de fotografia",
        "audiovisual",
    ),
    "SOUND": ("sound", "sonido", "audio", "sonidista", "microfonista"),
    "LIGHTING": ("lighting", "luces", "iluminacion", "gaffer", "electrico"),
    "PRODUCTION": (
        "production",
        "produccion",
        "productor",
        "directora",
        "director",
        "asistente produccion",
    ),
    "ART": ("art", "arte", "direccion de arte", "escenografia"),
    "FX": ("fx", "efectos", "efectos especiales", "vfx"),
    "MAKEUP": ("makeup", "maquillaje", "maquillador", "maquilladora"),
    "HAIR": ("hair", "pelo", "peluqueria"),
    "WARDROBE": ("wardrobe", "vestuario", "costume", "costumes"),
    "STUNT": ("stunt", "doble", "doble de riesgo", "riesgo", "accion"),
    "CATERING": ("catering", "comida", "alimentacion"),
}


def _normalize_crew_category_text(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_CREW_CATEGORY_BY_ALIAS = {
    _normalize_crew_category_text(alias): category
    for category, aliases in _CREW_CATEGORY_ALIASES.items()
    for alias in aliases
}


def normalize_crew_category(
    value: str | None,
    role: str | None = None,
    specialty: str | None = None,
) -> str:
    for candidate in (value, role, specialty):
        normalized = _normalize_crew_category_text(candidate)
        if not normalized:
            continue

        official_category = normalized.upper()
        if official_category in CREW_CATEGORY_LABELS:
            return official_category

        mapped_category = _CREW_CATEGORY_BY_ALIAS.get(normalized)
        if mapped_category:
            return mapped_category

    return "OTHER"


def get_crew_category_label(category: str | None) -> str:
    return CREW_CATEGORY_LABELS[normalize_crew_category(category)]


def _clean_identifier(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def get_talent_uid_from_data(data: dict | None) -> str | None:
    if not isinstance(data, dict):
        return None

    for key in (
        "user_id",
        "user_uid",
        "talent_user_id",
        "talent_uid",
        "talent_id",
        "applicant_uid",
        "applicant_user_id",
        "actor_uid",
        "uid",
    ):
        if value := _clean_identifier(data.get(key)):
            return value

    nested_fields = (
        ("talent", ("user_id", "uid")),
        ("user", ("uid",)),
        ("profile", ("user_uid",)),
    )
    for object_key, keys in nested_fields:
        nested = data.get(object_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            if value := _clean_identifier(nested.get(key)):
                return value

    return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_date(value) -> str | None:
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)
