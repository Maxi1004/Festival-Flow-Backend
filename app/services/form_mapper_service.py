"""
form_mapper_service.py
======================
Maps a project's Firestore data to a unified festival form structure.

Flow:
  1. Local keyword/name-based mapping (confidence 1.0, source="project")
  2. Single bulk Gemini call for all remaining ambiguous text fields (source="ai")
  3. Anything still unmapped goes to missing_fields

Never raises — Gemini failures fall back gracefully to missing_fields.
Must be called synchronously (use asyncio.to_thread from async routes).
"""

import json
import os
import re
from typing import Any


# ── Ambiguous field detection ─────────────────────────────────────────────────
# Fields whose values cannot be derived from project data and need AI generation.

_AI_FIELD_PATTERNS = [
    r"why.*(select|chosen|this|film|short)",
    r"director.{0,10}statement",
    r"filmmaker.{0,10}statement",
    r"artist.{0,10}statement",
    r"production.{0,10}note",
    r"festival.{0,10}strateg",
    r"motivation",
    r"vision\b",
    r"note.*director",
    r"justif",
    r"declaraci[oó]n",
    r"por qu[eé]",
    r"what.*mean",
    r"describe.*film",
    r"about.*project",
]


# ── Label → project field mapping ─────────────────────────────────────────────
# Pattern matched against: "<label> <key> <name>" (lowercased, joined).
# First match wins.

_LABEL_MAP: list[tuple[str, str]] = [
    # Title
    (r"original.?title|t[ií]tulo.?original", "original_title"),
    (r"\btitle\b|t[ií]tulo\b", "title"),
    # Synopsis / description
    (r"short.?synopsis|sinopsis.?corta", "short_synopsis"),
    (r"long.?synopsis|sinopsis.?larga|full.?synopsis", "long_synopsis"),
    (r"tagline", "tagline"),
    (r"logline", "logline"),
    (r"synopsis|sinopsis|summary|resumen|logline|description|descripci[oó]n", "description"),
    # Runtime
    (r"runtime.{0,10}hour|hora.{0,10}duraci[oó]n", "runtime_hours"),
    (r"runtime.{0,10}minute|minuto.{0,10}duraci[oó]n", "runtime_minutes"),
    (r"runtime.{0,10}second|segundo.{0,10}duraci[oó]n", "runtime_seconds"),
    (r"runtime|running.?time|duraci[oó]n", "runtime"),
    # Dates
    (r"completion.{0,10}date|fecha.{0,10}finaliz|year.{0,10}complet|a[nñ]o.{0,10}complet", "end_date"),
    (r"production.{0,10}year|a[nñ]o.{0,10}producci[oó]n|release.{0,10}year", "end_date"),
    (r"premiere.{0,10}date|fecha.{0,10}estreno", "premiere_date"),
    # Budget
    (r"budget.{0,10}currency|moneda", "currency"),
    (r"budget|presupuesto", "budget"),
    # Country / language
    (r"countr.{0,10}origin|pa[ií]s.{0,10}origen", "country"),
    (r"countr.{0,10}filming|pa[ií]s.{0,10}filmac|filming.{0,10}countr", "filming_countries"),
    (r"\blanguage\b|idioma", "language"),
    # Technical
    (r"aspect.?ratio|relaci[oó]n.{0,10}aspecto|proporci[oó]n", "aspect_ratio"),
    (r"\bcolor\b|\bcolour\b|b&w|black.*white|blanco.*negro", "color"),
    (r"student|estudiante", "student_project"),
    (r"first.?time.?filmmaker|primer.{0,10}film", "first_time_filmmaker"),
    (r"\bformat\b|formato", "format"),
    # Director
    (r"director.{0,15}first|nombre.{0,15}director|first.{0,10}name.{0,10}director", "director_first_name"),
    (r"director.{0,15}last|apellido.{0,15}director|last.{0,10}name.{0,10}director", "director_last_name"),
    (r"director.{0,15}email|email.{0,15}director", "director_email"),
    (r"director.{0,15}bio|biograf[ií]a.{0,15}director", "director_bio"),
    (r"director.{0,15}nationalit|nacionalidad.{0,15}director", "director_nationality"),
    (r"director.{0,15}countr|pa[ií]s.{0,15}director", "director_country"),
    (r"\bdirector\b", "director_name"),
    # Crew
    (r"producer|productor", "producer_name"),
    (r"writer|screenwriter|guionista", "writer_name"),
    (r"cast|elenco|\bactor\b|\bactriz\b", "cast"),
    (r"composer|compositor", "composer"),
    (r"cinematograph|director.{0,10}photo|fotograf[ií]a|dop\b", "cinematographer"),
    (r"\beditor\b|montaje", "editor"),
    # Contact / Social
    (r"\bphone\b|tel[eé]fono", "phone"),
    (r"instagram", "instagram"),
    (r"facebook", "facebook"),
    (r"twitter|x\.com", "twitter"),
    (r"bluesky", "bluesky"),
    (r"website|sitio.?web|web.?site|homepage", "website"),
    (r"\bemail\b|correo", "contact_email"),
    # Files / links
    (r"\bposter\b", "poster_url"),
    (r"press.?kit|presskit|dossier", "press_kit_url"),
    (r"\btrailer\b", "trailer_url"),
    (r"\bteaser\b", "teaser_url"),
    (r"screener|screening.?link", "screener_url"),
    (r"still|photo\b|imagen", "stills_url"),
]


# ── HTML name attribute → project field mapping ───────────────────────────────
# Matches against the field's "name" attribute (e.g. project[title]).

_NAME_MAP: dict[str, str] = {
    "project[title]": "title",
    "project[original_title]": "original_title",
    "project[synopsis]": "description",
    "project[short_synopsis]": "short_synopsis",
    "project[long_synopsis]": "long_synopsis",
    "project[tagline]": "tagline",
    "project[logline]": "logline",
    "project[runtime_hours]": "runtime_hours",
    "project[runtime_minutes]": "runtime_minutes",
    "project[runtime_seconds]": "runtime_seconds",
    "project[completion_date]": "end_date",
    "project[production_budget]": "budget",
    "project[production_budget_currency]": "currency",
    "project[countries_of_origin]": "country",
    "project[countries_of_filming]": "filming_countries",
    "project[languages]": "language",
    "project[shooting_format]": "format",
    "project[aspect_ratio]": "aspect_ratio",
    "project[film_color]": "color",
    "project[student_project]": "student_project",
    "project[first_time_filmmaker]": "first_time_filmmaker",
    "project[project_website]": "website",
    "project[social_twitter]": "twitter",
    "project[social_bluesky]": "bluesky",
    "project[social_facebook]": "facebook",
    "project[social_instagram]": "instagram",
    "project[posted_credits][directors]": "director_name",
    "project[genres_video]": "production_type",
    "project[film_color][0]": "color",
    "first_name": "director_first_name",
    "middle_name": "director_middle_name",
    "last_name": "director_last_name",
}

_VALID_STATUSES = {"completed", "published", "finalizado", "completado", "publicado"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json_from_text(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start: end + 1])
        raise


def _get_value(project: dict, key: str) -> Any:
    """Return non-empty project[key], or None."""
    val = project.get(key)
    if val is None or val == "" or val == [] or val == {}:
        return None
    return val


def _extract_director_info(project: dict) -> dict:
    """
    Pull director data from whatever structure the project uses.
    Supports direct fields, lists, and nested crew/credits dicts.
    """
    result: dict[str, Any] = {}

    for key in ("director_name", "director", "directors"):
        val = project.get(key)
        if not val:
            continue
        if isinstance(val, list):
            names = []
            for item in val:
                if isinstance(item, dict):
                    names.append(item.get("name") or item.get("nombre") or "")
                    if not result.get("director_first_name"):
                        result["director_first_name"] = item.get("first_name") or item.get("nombre") or ""
                    if not result.get("director_last_name"):
                        result["director_last_name"] = item.get("last_name") or item.get("apellido") or ""
                    if not result.get("director_email"):
                        result["director_email"] = item.get("email") or ""
                    if not result.get("director_bio"):
                        result["director_bio"] = item.get("bio") or item.get("biography") or ""
                else:
                    names.append(str(item))
            result["director_name"] = ", ".join(n for n in names if n)
        elif isinstance(val, dict):
            result["director_name"] = val.get("name") or val.get("nombre") or ""
            result["director_first_name"] = val.get("first_name") or ""
            result["director_last_name"] = val.get("last_name") or ""
            result["director_email"] = val.get("email") or ""
            result["director_bio"] = val.get("bio") or ""
        else:
            result["director_name"] = str(val)
        break

    # Also check nested crew/credits structures
    crew = project.get("crew") or project.get("credits") or {}
    if isinstance(crew, dict) and not result.get("director_name"):
        directors = crew.get("directors") or crew.get("director") or []
        if isinstance(directors, list) and directors:
            first = directors[0]
            if isinstance(first, dict):
                result["director_name"] = first.get("name") or first.get("nombre") or ""
            else:
                result["director_name"] = str(first)
        elif isinstance(directors, str) and directors:
            result["director_name"] = directors

    # Producer
    for key in ("producer_name", "producer", "producers"):
        val = project.get(key)
        if not val:
            continue
        if isinstance(val, list):
            result["producer_name"] = ", ".join(
                (v.get("name") or str(v)) if isinstance(v, dict) else str(v)
                for v in val
            )
        elif isinstance(val, dict):
            result["producer_name"] = val.get("name") or ""
        else:
            result["producer_name"] = str(val)
        break

    # Writer
    for key in ("writer_name", "writer", "writers", "screenwriter", "screenwriters", "guionista"):
        val = project.get(key)
        if not val:
            continue
        if isinstance(val, list):
            result["writer_name"] = ", ".join(
                (v.get("name") or str(v)) if isinstance(v, dict) else str(v)
                for v in val
            )
        else:
            result["writer_name"] = str(val)
        break

    return result


def _normalize_runtime(project: dict) -> dict:
    """Derive runtime_hours / runtime_minutes from raw runtime if needed."""
    result: dict[str, Any] = {}
    runtime = project.get("runtime") or project.get("duration")
    if runtime is None:
        return result

    total_min: int | None = None
    if isinstance(runtime, (int, float)):
        total_min = int(runtime)
    elif isinstance(runtime, str):
        match = re.search(r"(\d+)", runtime)
        if match:
            total_min = int(match.group(1))

    if total_min is not None:
        result["runtime_hours"] = str(total_min // 60) if total_min >= 60 else "0"
        result["runtime_minutes"] = str(total_min % 60)
        result["runtime_seconds"] = "0"
        result["runtime"] = f"{total_min} min"
    return result


def _build_extended_project(project: dict) -> dict:
    """
    Return an enriched copy of the project dict with derived/normalized fields.
    The raw Firestore data may have more fields than the Pydantic schema exposes;
    all are preserved and supplemented here.
    """
    extended = dict(project)

    # Derive synopsis variants from description
    desc = project.get("description") or project.get("synopsis") or ""
    if desc:
        extended.setdefault("short_synopsis", desc[:250].rsplit(" ", 1)[0] + ("…" if len(desc) > 250 else ""))
        extended.setdefault("long_synopsis", desc)

    # Country fallback from location
    if not project.get("country") and project.get("location"):
        extended["country"] = project["location"]

    # Runtime normalization
    extended.update(_normalize_runtime(project))

    # Director / crew extraction
    extended.update(_extract_director_info(project))

    # Twitter / X aliases
    if project.get("x") and not project.get("twitter"):
        extended["twitter"] = project["x"]
    elif project.get("twitter") and not project.get("x"):
        extended["x"] = project["twitter"]

    # Contact email fallback
    if not project.get("contact_email") and project.get("email"):
        extended["contact_email"] = project["email"]

    return extended


def _is_ambiguous_field(label: str) -> bool:
    norm = label.lower().strip()
    return any(re.search(p, norm) for p in _AI_FIELD_PATTERNS)


def _try_local_map(field: dict, project: dict) -> tuple[Any, float, str] | None:
    """
    Try local mapping rules. Returns (value, confidence, source) or None.
    Priority: HTML name attribute → label/key pattern → direct key match.
    """
    label = str(field.get("label") or "")
    name = str(field.get("name") or "")
    key = str(field.get("key") or "")
    combined = f"{label} {key} {name}".lower()

    # 1. Exact HTML name attribute match (most reliable — tied to FilmFreeway's form)
    if name and name in _NAME_MAP:
        proj_key = _NAME_MAP[name]
        val = _get_value(project, proj_key)
        if val is not None:
            return (val, 1.0, "project")

    # 2. Label / key pattern match
    for pattern, proj_key in _LABEL_MAP:
        if re.search(pattern, combined):
            val = _get_value(project, proj_key)
            if val is not None:
                return (val, 1.0, "project")

    # 3. Direct key match (the unified field key happens to match a project field)
    if key and _get_value(project, key) is not None:
        return (_get_value(project, key), 0.9, "project")

    return None


# ── Gemini bulk call ──────────────────────────────────────────────────────────

def _call_gemini_bulk(project: dict, fields: list[dict]) -> dict[str, str]:
    """
    Generate values for multiple ambiguous fields in a single Gemini call.
    Returns {field_key: generated_text}.
    Never raises — returns {} on any failure.
    """
    if not fields:
        return {}

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {}

    # Compact project context (skip internal / empty fields)
    project_ctx = {
        k: v for k, v in project.items()
        if k not in {"id", "owner_uid", "created_at", "updated_at", "runtime_hours", "runtime_minutes", "runtime_seconds"}
        and v not in (None, "", [], {})
        and isinstance(v, (str, int, float, bool, list))
    }

    fields_for_prompt = [
        {"key": f.get("key", ""), "label": f.get("label") or f.get("key") or ""}
        for f in fields
        if f.get("key")
    ]

    prompt = (
        "Eres un asistente especializado en postulaciones a festivales de cine internacionales.\n"
        "Dado el siguiente proyecto de cine, genera respuestas apropiadas para cada campo del formulario.\n\n"
        f"Proyecto:\n{json.dumps(project_ctx, ensure_ascii=False, indent=2)}\n\n"
        f"Campos a completar:\n{json.dumps(fields_for_prompt, ensure_ascii=False, indent=2)}\n\n"
        "Reglas:\n"
        "- Responde en español o inglés según lo que mejor corresponda al contexto del festival.\n"
        "- Máximo 500 caracteres por campo.\n"
        "- Si no hay información suficiente para generar un valor útil, usa null.\n"
        "- Responde ÚNICAMENTE con un JSON válido donde las keys son los 'key' de los campos.\n"
        "Ejemplo: {\"director_statement\": \"El film explora...\", \"festival_strategy\": null}"
    )

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.35,
                response_mime_type="application/json",
            ),
        )
        data = _extract_json_from_text(response.text or "")
        return {
            k: str(v)
            for k, v in data.items()
            if v is not None and str(v).strip()
        }
    except Exception:
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def map_project_to_form(
    project: dict[str, Any],
    unified_form: dict[str, Any],
) -> dict[str, Any]:
    """
    Cross-reference project data with the unified form and produce form_values.

    Args:
        project:      Raw Firestore document dict (all fields).
        unified_form: The unified form stored in _analyze_results[batch_id]["unified_form"].

    Returns:
        {
            "form_values": {key: {"value": ..., "confidence": ..., "source": ...}},
            "missing_fields": [{"field": ..., "reason": ...}],
            "mapped_fields": int,
            "missing_count": int,
            "ai_fields": int,
        }
    """
    extended = _build_extended_project(project)

    form_values: dict[str, dict] = {}
    ambiguous_pending: list[dict] = []   # fields queued for Gemini
    missing_fields: list[dict] = []

    # ── Pass 1: local mapping ─────────────────────────────────────────────────
    for category_data in unified_form.get("categories", {}).values():
        for field in category_data.get("fields", []):
            key = field.get("key") or ""
            if not key:
                continue
            label = field.get("label") or key

            local = _try_local_map(field, extended)
            if local:
                value, confidence, source = local
                form_values[key] = {"value": value, "confidence": confidence, "source": source}
            elif _is_ambiguous_field(label):
                ambiguous_pending.append(field)
            else:
                missing_fields.append({
                    "field": label,
                    "reason": "No existe información en el proyecto",
                })

    # ── Pass 2: single Gemini call for ambiguous fields ───────────────────────
    ai_count = 0
    if ambiguous_pending:
        print(f"[Generate Answers] Llamando Gemini para {len(ambiguous_pending)} campos ambiguos", flush=True)
        ai_results = _call_gemini_bulk(extended, ambiguous_pending)
        for field in ambiguous_pending:
            key = field.get("key") or ""
            label = field.get("label") or key
            if key in ai_results:
                form_values[key] = {"value": ai_results[key], "confidence": 0.75, "source": "ai"}
                ai_count += 1
            else:
                missing_fields.append({
                    "field": label,
                    "reason": "IA no pudo generar una respuesta",
                })

    mapped_count = len(form_values)

    print(f"[Generate Answers] Campos mapeados: {mapped_count}", flush=True)
    print(f"[Generate Answers] Campos IA: {ai_count}", flush=True)
    print(f"[Generate Answers] Campos faltantes: {len(missing_fields)}", flush=True)

    return {
        "form_values": form_values,
        "missing_fields": missing_fields,
        "mapped_fields": mapped_count,
        "missing_count": len(missing_fields),
        "ai_fields": ai_count,
    }
