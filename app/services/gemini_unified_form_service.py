import json
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.scraper_schema import UnifiedFormResponse


load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
MAX_FIELDS_PER_REQUEST = 200


SYSTEM_PROMPT = """
Analiza todos los campos recibidos.

Debes crear un unico formulario normalizado.

Reglas:
1. Eliminar duplicados.
2. Detectar equivalencias aunque esten en distintos idiomas.
Ejemplos:
"Director Name"
"Nombre Director"
"Filmmaker Name"
deben transformarse en un unico campo.
3. Mantener labels en espanol.
4. Agrupar campos en secciones.
Secciones sugeridas:
- Informacion del proyecto
- Informacion del director
- Produccion
- Contacto
- Distribucion
- Estreno
- Material promocional
- Archivos y enlaces
- Preguntas adicionales
5. Detectar automaticamente tipos:
email -> email
fecha -> date
texto corto -> text
texto largo -> textarea
checkbox -> checkbox
select -> select
radio -> radio
url -> url
number -> number
6. Mantener opciones reales detectadas.
7. No inventar opciones inexistentes.
8. Cada campo debe incluir:
key, label, type, required, options, sourceFields
9. No incluir:
password, cookies, session_id, credenciales, tokens
10. Si un campo no puede clasificarse:
enviarlo a Preguntas adicionales.
11. Responder unicamente JSON valido.

Formato obligatorio:
{
  "form": {
    "title": "Formulario Maestro",
    "description": "Formulario unificado generado automaticamente.",
    "sections": [
      {
        "title": "Informacion del proyecto",
        "fields": [
          {
            "key": "project_title",
            "label": "Titulo del proyecto",
            "type": "text",
            "required": true,
            "options": [],
            "sourceFields": ["project_title", "title"]
          }
        ]
      }
    ]
  }
}
""".strip()


FORBIDDEN_FIELD_MARKERS = (
    "password",
    "cookie",
    "cookies",
    "session_id",
    "sessionid",
    "credential",
    "credentials",
    "credencial",
    "credenciales",
    "token",
)


def _field_identity(field: dict[str, Any]) -> str:
    values = [
        field.get("key"),
        field.get("name"),
        field.get("id"),
        field.get("label"),
        field.get("type"),
    ]
    return " ".join(str(value).lower() for value in values if value is not None)


def _sanitize_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for field in fields:
        identity = _field_identity(field)
        if any(marker in identity for marker in FORBIDDEN_FIELD_MARKERS):
            continue
        sanitized.append(field)
    return sanitized


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("Gemini no respondio con un objeto JSON")
    return payload


def _build_prompt(source_url: str, fields: list[dict[str, Any]], retry: bool = False) -> str:
    retry_instruction = ""
    if retry:
        retry_instruction = (
            "\n\nLa respuesta anterior no fue JSON valido o no cumplio el schema. "
            "Corrige y responde solo con el objeto JSON obligatorio."
        )

    payload = {
        "source_url": source_url,
        "fields": fields,
    }
    return (
        f"{SYSTEM_PROMPT}{retry_instruction}\n\n"
        "Campos extraidos por Playwright:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


async def generate_unified_form(
    source_url: str,
    fields: list[dict[str, Any]],
) -> UnifiedFormResponse:
    if not fields:
        raise HTTPException(status_code=400, detail="fields no puede estar vacio")
    if len(fields) > MAX_FIELDS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Maximo {MAX_FIELDS_PER_REQUEST} campos por solicitud",
        )

    sanitized_fields = _sanitize_fields(fields)
    if not sanitized_fields:
        raise HTTPException(status_code=400, detail="fields no contiene campos procesables")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada")

    try:
        from google import genai
        from google.genai import types
    except ImportError as error:
        raise HTTPException(status_code=500, detail="google-genai no esta instalado") from error

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    client = genai.Client(api_key=api_key)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=_build_prompt(source_url, sanitized_fields, retry=attempt > 0),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            payload = _extract_json_object(response.text or "")
            return UnifiedFormResponse.model_validate(payload)
        except (json.JSONDecodeError, ValueError, ValidationError) as error:
            last_error = error
            continue
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail=f"Gemini no pudo generar el formulario: {type(error).__name__}: {error}",
            ) from error

    raise HTTPException(
        status_code=502,
        detail=f"Gemini respondio con JSON invalido: {last_error}",
    )
