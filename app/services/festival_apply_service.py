"""
festival_apply_service.py
=========================
In-memory batch queue + background-thread worker for festival applications.

Security model
--------------
  - Credentials (username, password) are passed only as local variables in the
    worker thread's stack frame.  They are never stored in BatchState, never
    written to a log, and set to None immediately after use so they can be
    garbage-collected as soon as the reference count drops to zero.
  - BatchState holds only the batch_id, total count, and the event queue.

Concurrency model
-----------------
  - One daemon thread per batch; threads share no mutable state except
    _batches (guarded by _batches_lock).
  - The SSE consumer (async) polls the thread-safe queue.Queue via
    asyncio.to_thread so it never blocks the event loop.
"""

import json
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Make tools/ importable from the project root ─────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── In-memory registries ──────────────────────────────────────────────────────
_batches: dict[str, "_BatchState"] = {}
_batches_lock = threading.Lock()

_analyze_results: dict[str, dict] = {}
_analyze_lock = threading.Lock()

# Keywords used to detect festival application form links
_FORM_LINK_KEYWORDS = [
    "submit", "apply", "entry", "inscripcion", "convocatoria",
    "formulario", "inscription", "inscribir", "registro",
]


@dataclass
class _BatchState:
    batch_id: str
    total: int
    event_queue: queue.Queue = field(default_factory=queue.Queue)
    done: bool = False


# ── Public API ────────────────────────────────────────────────────────────────

def submit_batch(
    festivals: list[dict[str, str]],
    film_data: dict[str, Any],
) -> str:
    """
    Register a new batch and launch the background worker.
    Returns batch_id immediately — credentials only travel to the worker thread.
    """
    batch_id = str(uuid.uuid4())
    state = _BatchState(batch_id=batch_id, total=len(festivals))

    with _batches_lock:
        _batches[batch_id] = state

    t = threading.Thread(
        target=_process_batch,
        # Pass a shallow copy so caller mutations after submit don't affect us.
        args=(batch_id, list(festivals), film_data),
        daemon=True,
        name=f"apply-{batch_id[:8]}",
    )
    t.start()
    return batch_id


def batch_exists(batch_id: str) -> bool:
    with _batches_lock:
        return batch_id in _batches


def get_event_queue(batch_id: str) -> "queue.Queue | None":
    with _batches_lock:
        state = _batches.get(batch_id)
    return state.event_queue if state else None


# ── Worker internals ──────────────────────────────────────────────────────────

def _emit(q: queue.Queue, festival_id: str, status: str, message: str) -> None:
    """Push one SSE payload onto the queue."""
    q.put({"festival_id": festival_id, "status": status, "message": message})


def _process_batch(
    batch_id: str,
    festivals: list[dict[str, str]],
    film_data: dict[str, Any],
) -> None:
    """
    Background worker: processes each festival sequentially, emits events.
    Credentials live only in local variables and are cleared after each festival.
    """
    with _batches_lock:
        state = _batches.get(batch_id)
    if not state:
        return

    q = state.event_queue

    try:
        from tools.selenium_captcha_solver import CaptchaSolver

        for item in festivals:
            festival_id = item["festival_id"]
            login_url = item["login_url"]
            # Credentials in local vars only — never forwarded to any logger.
            _username = item["username"]
            _password = item["password"]

            _emit(q, festival_id, "processing", "Iniciando procesamiento...")

            try:
                solver = CaptchaSolver(
                    target_url=login_url,
                    headless=True,
                    wait_timeout=20,
                )
                result = solver.apply_to_festival(
                    email=_username,
                    password=_password,
                    max_retries=2,
                )
            except Exception as exc:
                result = {
                    "status": "error",
                    "message": f"Error inesperado: {type(exc).__name__}",
                    "final_url": "",
                }
            finally:
                # Release credentials ASAP — they are no longer needed.
                _username = None  # noqa: F841
                _password = None  # noqa: F841

            _emit(q, festival_id, result["status"], result.get("message", ""))

    except ImportError as exc:
        _emit(
            q,
            "__batch__",
            "error",
            (
                f"CaptchaSolver no disponible: {exc}. "
                "Instala las dependencias: pip install -r tools/requirements-captcha.txt"
            ),
        )
    except Exception as exc:
        _emit(q, "__batch__", "error", f"Error en el lote: {type(exc).__name__}: {exc}")

    finally:
        # Terminal event — tells the SSE generator to close the stream.
        q.put({
            "festival_id": "__done__",
            "status": "complete",
            "message": f"Lote {batch_id[:8]}… completado. {state.total} festival(es) procesado(s).",
        })
        with _batches_lock:
            if batch_id in _batches:
                _batches[batch_id].done = True


# ── Form analysis helpers ─────────────────────────────────────────────────────

def _find_form_link(driver: Any, By: Any) -> "str | None":
    """Return href of the first link whose text/URL contains a form keyword."""
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            try:
                href = (link.get_attribute("href") or "").lower()
                text = link.text.lower()
                combined = href + " " + text
                if any(kw in combined for kw in _FORM_LINK_KEYWORDS):
                    full_href = link.get_attribute("href") or ""
                    if full_href.startswith("http"):
                        return full_href
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extract_form_fields(driver: Any, By: Any) -> list[dict]:
    """Extract metadata for every visible input/textarea/select on the page."""
    skip_types = {"hidden", "submit", "button", "reset", "image"}
    fields: list[dict] = []
    try:
        elements = driver.find_elements(
            By.CSS_SELECTOR, "input, textarea, select, [type='file']"
        )
        for el in elements:
            try:
                name = el.get_attribute("name") or ""
                field_id = el.get_attribute("id") or ""
                field_type = (el.get_attribute("type") or el.tag_name).lower()
                placeholder = el.get_attribute("placeholder") or ""
                required = el.get_attribute("required") is not None

                if field_type in skip_types:
                    continue
                if not name and not field_id:
                    continue

                label_text = ""
                if field_id:
                    try:
                        label = driver.find_element(
                            By.CSS_SELECTOR, f"label[for='{field_id}']"
                        )
                        label_text = label.text.strip()
                    except Exception:
                        pass

                fields.append({
                    "name": name,
                    "id": field_id,
                    "type": field_type,
                    "placeholder": placeholder,
                    "label": label_text,
                    "required": required,
                })
            except Exception:
                continue
    except Exception:
        pass
    return fields


def _extract_json_from_text(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def _empty_unified_form() -> dict:
    return {
        "title": "Formulario Unificado de Festivales",
        "categories": {
            "pelicula": {"label": "Información de la Película", "fields": []},
            "director": {"label": "Información del Director", "fields": []},
            "tecnico": {"label": "Información Técnica", "fields": []},
            "archivos": {"label": "Archivos y Enlaces", "fields": []},
        },
    }


def _call_gemini_unify_forms(fields_by_festival: dict[str, Any]) -> dict[str, Any]:
    """
    Send all per-festival field data to Gemini and ask it to produce
    a unified form grouped into 4 fixed categories, with per-field festival mapping.
    Uses GEMINI_API_KEY and GEMINI_MODEL from environment (default: gemini-2.5-flash).
    Runs synchronously — must be called from a thread, not the async event loop.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai no está instalado. Ejecuta: pip install google-genai"
        ) from exc

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no configurada en el entorno")

    festival_data = {
        fid: data.get("fields", [])
        for fid, data in fields_by_festival.items()
        if data.get("fields")
    }
    if not festival_data:
        return _empty_unified_form()

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    prompt = (
        "Analiza los campos de formulario extraídos de múltiples festivales de cine "
        "y genera un formulario unificado en JSON.\n\n"
        f"Campos por festival:\n{json.dumps(festival_data, ensure_ascii=False, indent=2)}\n\n"
        "Genera un formulario unificado agrupado exactamente en estas 4 categorías:\n"
        "1. pelicula: título, año, duración, país, idioma, sinopsis, género, premiere\n"
        "2. director: nombre, email, bio, nacionalidad\n"
        "3. tecnico: formato, relación de aspecto, subtítulos, DCP, archivo\n"
        "4. archivos: screener link, poster, press kit\n\n"
        "Por cada campo unificado incluye:\n"
        "- key: identificador en snake_case\n"
        "- label: nombre legible en español\n"
        "- type: tipo de input (text, email, number, textarea, select, url, file, date)\n"
        "- required: true si es requerido en al menos un festival\n"
        "- options: lista de opciones si aplica, vacío en caso contrario\n"
        "- festivals: lista de festival_ids donde existe este campo\n"
        '- source_fields: lista de {"festival_id": "...", "name": "...", "id": "..."} '
        "indicando el campo original por festival\n\n"
        "Responde únicamente con JSON válido:\n"
        '{\n  "title": "Formulario Unificado de Festivales",\n'
        '  "categories": {\n'
        '    "pelicula": {"label": "Información de la Película", "fields": [...]},\n'
        '    "director": {"label": "Información del Director", "fields": [...]},\n'
        '    "tecnico": {"label": "Información Técnica", "fields": [...]},\n'
        '    "archivos": {"label": "Archivos y Enlaces", "fields": [...]}\n'
        "  }\n}"
    )

    client = genai.Client(api_key=api_key)
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return _extract_json_from_text(response.text or "")
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            continue
        except Exception as exc:
            raise RuntimeError(
                f"Gemini API error: {type(exc).__name__}: {exc}"
            ) from exc

    raise RuntimeError(f"Gemini respondió con JSON inválido: {last_error}")


# ── Public API: analyze_festival_forms ───────────────────────────────────────

def analyze_festival_forms(
    festival_ids: list[str],
    credentials_map: dict[str, dict],
) -> dict[str, Any]:
    """
    For each festival: login with CaptchaSolver, find the application form link,
    navigate to it, and extract all field metadata.
    Then call Gemini (GEMINI_MODEL) to produce a unified form grouped in 4 categories.

    Stores results in _analyze_results keyed by analyze_batch_id so that
    submit_forms() can re-use the field mapping without re-scraping.

    Runs synchronously — the route handler must wrap with asyncio.to_thread.
    Credentials live only in local variables and are set to None after each festival.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from tools.selenium_captcha_solver import (
        _build_driver,
        _DEFAULT_BUSTER_PATH,
        _do_login_attempt,
    )

    fields_by_festival: dict[str, Any] = {}
    form_urls: dict[str, str] = {}

    for festival_id in festival_ids:
        creds = credentials_map.get(festival_id, {})
        _username = creds.get("username", "")
        _password = creds.get("password", "")
        login_url = creds.get("login_url", "")

        driver = None
        try:
            driver = _build_driver(headless=True, buster_crx=_DEFAULT_BUSTER_PATH)
            wait = WebDriverWait(driver, 20)

            driver.get(login_url)
            time.sleep(2)

            login_result = _do_login_attempt(driver, wait, _username, _password)
            if login_result["status"] != "LOGIN_OK":
                fields_by_festival[festival_id] = {
                    "status": login_result["status"],
                    "message": login_result["message"],
                    "fields": [],
                }
                continue

            form_url = _find_form_link(driver, By)
            if not form_url:
                fields_by_festival[festival_id] = {
                    "status": "NO_FORM_FOUND",
                    "message": "No se encontró link al formulario de inscripción",
                    "fields": [],
                }
                continue

            form_urls[festival_id] = form_url
            driver.get(form_url)
            time.sleep(2)

            fields = _extract_form_fields(driver, By)
            fields_by_festival[festival_id] = {
                "status": "OK",
                "form_url": form_url,
                "fields": fields,
            }

        except Exception as exc:
            fields_by_festival[festival_id] = {
                "status": "error",
                "message": f"{type(exc).__name__}: {exc}",
                "fields": [],
            }
        finally:
            if driver:
                driver.quit()
            _username = None  # noqa: F841
            _password = None  # noqa: F841

    try:
        unified_form = _call_gemini_unify_forms(fields_by_festival)
    except Exception as exc:
        unified_form = _empty_unified_form()
        unified_form["error"] = f"Error al generar formulario unificado: {exc}"

    analyze_batch_id = str(uuid.uuid4())
    with _analyze_lock:
        _analyze_results[analyze_batch_id] = {
            "fields_by_festival": fields_by_festival,
            "form_urls": form_urls,
            "credentials_map": {
                fid: dict(c) for fid, c in credentials_map.items()
            },
            "unified_form": unified_form,
        }

    return {
        "analyze_batch_id": analyze_batch_id,
        "unified_form": unified_form,
        "fields_by_festival": {
            fid: {"status": d.get("status"), "fields": d.get("fields", [])}
            for fid, d in fields_by_festival.items()
        },
    }


def analyze_batch_exists(analyze_batch_id: str) -> bool:
    with _analyze_lock:
        return analyze_batch_id in _analyze_results


# ── Public API: submit_forms ──────────────────────────────────────────────────

def submit_forms(analyze_batch_id: str, form_data: dict[str, Any]) -> tuple[str, int]:
    """
    Start a background thread that re-logs in to each festival, navigates to
    its form URL, fills the fields using the unified→specific mapping, and submits.

    Returns (submit_batch_id, total_festivals).
    The caller can stream progress via the existing /apply/stream/{submit_batch_id}.
    """
    with _analyze_lock:
        analyze_data = _analyze_results.get(analyze_batch_id)

    if not analyze_data:
        raise ValueError(f"Análisis '{analyze_batch_id}' no encontrado")

    form_urls = analyze_data.get("form_urls", {})
    total = len(form_urls)

    submit_batch_id = str(uuid.uuid4())
    state = _BatchState(batch_id=submit_batch_id, total=total)

    with _batches_lock:
        _batches[submit_batch_id] = state

    t = threading.Thread(
        target=_process_submit_batch,
        args=(submit_batch_id, analyze_batch_id, form_data),
        daemon=True,
        name=f"submit-{submit_batch_id[:8]}",
    )
    t.start()
    return submit_batch_id, total


# ── Submit worker internals ───────────────────────────────────────────────────

def _build_field_mapping(
    unified_form: dict, form_data: dict
) -> dict[str, list[dict]]:
    """
    Build {festival_id: [{unified_key, name, id}]} for all unified keys
    that are present in form_data, using source_fields from the unified form.
    """
    mapping: dict[str, list[dict]] = {}
    for cat_data in unified_form.get("categories", {}).values():
        for field in cat_data.get("fields", []):
            unified_key = field.get("key", "")
            if unified_key not in form_data:
                continue
            for source in field.get("source_fields", []):
                festival_id = source.get("festival_id")
                if not festival_id:
                    continue
                mapping.setdefault(festival_id, []).append({
                    "unified_key": unified_key,
                    "name": source.get("name", ""),
                    "id": source.get("id", ""),
                })
    return mapping


def _fill_festival_form(
    driver: Any, By: Any, field_mappings: list[dict], form_data: dict
) -> int:
    """Fill fields on the current page. Returns count of successfully filled inputs."""
    filled = 0
    for mapping in field_mappings:
        value = form_data.get(mapping.get("unified_key", ""))
        if value is None:
            continue

        el = None
        target_id = mapping.get("id", "")
        target_name = mapping.get("name", "")

        if target_id:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f"#{target_id}")
            except Exception:
                pass
        if el is None and target_name:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f"[name='{target_name}']")
            except Exception:
                pass

        if el is None:
            continue
        try:
            tag = el.tag_name.lower()
            if tag == "select":
                from selenium.webdriver.support.ui import Select
                Select(el).select_by_visible_text(str(value))
            else:
                el.clear()
                el.send_keys(str(value))
            filled += 1
        except Exception:
            continue
    return filled


def _process_submit_batch(
    batch_id: str,
    analyze_batch_id: str,
    form_data: dict[str, Any],
) -> None:
    """Background worker: re-authenticates and fills each festival's form."""
    with _batches_lock:
        state = _batches.get(batch_id)
    if not state:
        return

    q = state.event_queue

    with _analyze_lock:
        analyze_data = _analyze_results.get(analyze_batch_id)

    if not analyze_data:
        q.put({
            "festival_id": "__done__",
            "status": "error",
            "message": "Datos de análisis no encontrados",
        })
        return

    unified_form = analyze_data.get("unified_form", {})
    form_urls: dict[str, str] = analyze_data.get("form_urls", {})
    credentials_map: dict[str, dict] = analyze_data.get("credentials_map", {})
    field_mapping = _build_field_mapping(unified_form, form_data)

    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from tools.selenium_captcha_solver import (
            _DEFAULT_BUSTER_PATH,
            _LOGIN_SUBMIT_SELECTORS,
            _build_driver,
            _do_login_attempt,
            _find_first_clickable,
        )

        for festival_id, form_url in form_urls.items():
            creds = credentials_map.get(festival_id, {})
            _username = creds.get("username", "")
            _password = creds.get("password", "")
            login_url = creds.get("login_url", "")
            festival_mappings = field_mapping.get(festival_id, [])

            _emit(q, festival_id, "processing", "Re-autenticando...")
            driver = None
            try:
                driver = _build_driver(headless=True, buster_crx=_DEFAULT_BUSTER_PATH)
                wait = WebDriverWait(driver, 20)

                driver.get(login_url)
                time.sleep(2)

                login_result = _do_login_attempt(driver, wait, _username, _password)
                if login_result["status"] != "LOGIN_OK":
                    _emit(q, festival_id, "LOGIN_FAILED", login_result["message"])
                    continue

                _emit(q, festival_id, "processing", "Navegando al formulario...")
                driver.get(form_url)
                time.sleep(2)

                filled = _fill_festival_form(driver, By, festival_mappings, form_data)

                _emit(q, festival_id, "processing", f"Enviando formulario ({filled} campos)...")
                submit_btn = _find_first_clickable(driver, _LOGIN_SUBMIT_SELECTORS)
                if submit_btn:
                    submit_btn.click()
                    time.sleep(3)
                    _emit(
                        q, festival_id, "SUBMITTED",
                        f"Formulario enviado ({filled} campos rellenados).",
                    )
                else:
                    _emit(
                        q, festival_id, "NO_SUBMIT_BTN",
                        f"No se encontró botón de envío ({filled} campos rellenados).",
                    )

            except Exception as exc:
                _emit(q, festival_id, "error", f"{type(exc).__name__}: {exc}")
            finally:
                if driver:
                    driver.quit()
                _username = None  # noqa: F841
                _password = None  # noqa: F841

    except ImportError as exc:
        _emit(q, "__batch__", "error", f"CaptchaSolver no disponible: {exc}")
    except Exception as exc:
        _emit(q, "__batch__", "error", f"Error en el lote de envío: {type(exc).__name__}: {exc}")
    finally:
        q.put({
            "festival_id": "__done__",
            "status": "complete",
            "message": (
                f"Envío completado. {len(form_urls)} festival(es) procesado(s)."
            ),
        })
        with _batches_lock:
            if batch_id in _batches:
                _batches[batch_id].done = True
