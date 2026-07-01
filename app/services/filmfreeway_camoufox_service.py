"""
FilmFreeway con Camoufox.

Flujo:
1. Login.
2. Llegar a /projects/new.
3. Extraer campos.
4. Mantener navegador abierto para rellenar despues desde el front.
"""

import os
import subprocess
import sys
import time
import uuid
from getpass import getpass
from typing import Any

from camoufox.sync_api import Camoufox

from app.services.festival_apply_service import (
    _empty_unified_form,
    _fallback_field_category,
    _field_should_be_ignored_for_fallback,
    register_external_unified_form,
)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
SCREENSHOT_PATH = os.path.join(BASE_DIR, "filmfreeway_result.png")
FIELD_TIMEOUT_MS = 2500
OPEN_VISIBLE_SCRIPT = os.path.join(os.path.dirname(__file__), "open_visible_camoufox.py")

_sessions: dict[str, dict[str, Any]] = {}
_visible_sessions: dict[str, dict[str, Any]] = {}


def _extract_form_fields(page: Any) -> dict[str, Any]:
    script = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    return el.getClientRects().length > 0;
  };
  const cssEscape = (value) => {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
    return String(value).replace(/["\\\\]/g, '\\\\$&');
  };
  const selectorFor = (el) => {
    const tag = (el.tagName || '').toLowerCase();
    if (el.id) return `${tag}#${cssEscape(el.id)}`;
    const name = el.getAttribute('name');
    const type = (el.getAttribute('type') || '').toLowerCase();
    const value = el.getAttribute('value');
    if (name && (type === 'radio' || type === 'checkbox') && value) {
      return `${tag}[name="${cssEscape(name)}"][value="${cssEscape(value)}"]`;
    }
    if (name) return `${tag}[name="${cssEscape(name)}"]`;
    return tag;
  };
  const labelFor = (el) => {
    const id = el.id || '';
    if (id) {
      const label = document.querySelector(`label[for="${cssEscape(id)}"]`);
      const text = clean(label && label.innerText);
      if (text) return text;
    }
    const aria = clean(el.getAttribute('aria-label'));
    if (aria) return aria;
    const placeholder = clean(el.getAttribute('placeholder'));
    if (placeholder) return placeholder;
    const wrapper = el.closest('label');
    const wrapperText = clean(wrapper && wrapper.innerText);
    if (wrapperText) return wrapperText;
    const holder = el.closest('.field, .form-group, .control-group, .input, .row, .columns, li, div');
    if (holder) {
      const label = holder.querySelector('label');
      const text = clean(label && label.innerText);
      if (text) return text;
    }
    return clean(el.getAttribute('name')) || clean(el.id);
  };
  const sectionFor = (el) => {
    const fieldset = el.closest('fieldset');
    const legend = clean(fieldset && fieldset.querySelector('legend') && fieldset.querySelector('legend').innerText);
    if (legend) return legend;
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend'))
      .filter((item) => isVisible(item) && clean(item.innerText));
    const previous = headings.filter((item) => item.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
    return previous.length ? clean(previous[previous.length - 1].innerText) : 'Formulario';
  };
  const optionsFor = (el) => Array.from(el.options || []).map((opt) => ({
    label: clean(opt.text),
    value: opt.value || clean(opt.text),
    selected: Boolean(opt.selected),
  }));
  const ignoredInput = (el) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const name = (el.getAttribute('name') || '').toLowerCase();
    return type === 'hidden' || type === 'submit' || type === 'button' ||
      ['authenticity_token', 'form_signature', 'commit'].includes(name);
  };

  const form = document.querySelector('form') || document.body;
  const controls = Array.from(form.querySelectorAll('input, textarea, select'))
    .filter((el) => {
      const tag = (el.tagName || '').toLowerCase();
      if (tag === 'input' && ignoredInput(el)) return false;
      if (tag === 'select' && el.name && (el.options || []).length > 0) return true;
      return isVisible(el);
    });

  const sections = [];
  const sectionMap = new Map();
  const grouped = new Set();
  const ensureSection = (title) => {
    const key = title || 'Formulario';
    if (!sectionMap.has(key)) {
      const section = { section: key, fields: [] };
      sectionMap.set(key, section);
      sections.push(section);
    }
    return sectionMap.get(key);
  };

  for (const el of controls) {
    const tag = (el.tagName || '').toLowerCase();
    const type = tag === 'select'
      ? (el.multiple ? 'multiselect' : 'select')
      : ((el.getAttribute('type') || tag).toLowerCase());
    const name = el.getAttribute('name') || '';
    const id = el.id || '';
    const label = labelFor(el);
    if (!name && !id && !label) continue;

    const section = ensureSection(sectionFor(el));

    if ((type === 'radio' || type === 'checkbox') && name) {
      const groupKey = `${section.section}:${type}:${name}`;
      if (grouped.has(groupKey)) continue;
      grouped.add(groupKey);
      const items = Array.from(form.querySelectorAll(`input[type="${type}"]`))
        .filter((item) => item.name === name && isVisible(item));
      const options = items.map((item) => ({
        label: labelFor(item),
        value: item.value || labelFor(item),
        id: item.id || '',
        selector: selectorFor(item),
        checked: Boolean(item.checked),
      }));
      section.fields.push({
        id,
        name,
        type: `${type}_group`,
        label: label || name,
        placeholder: '',
        selector: `input[type="${type}"][name="${cssEscape(name)}"]`,
        required: items.some((item) => item.required),
        options,
        value: type === 'radio'
          ? ((options.find((opt) => opt.checked) || {}).value || '')
          : options.filter((opt) => opt.checked).map((opt) => opt.value),
      });
      continue;
    }

    section.fields.push({
      id,
      name,
      type,
      label,
      placeholder: el.getAttribute('placeholder') || '',
      selector: selectorFor(el),
      required: Boolean(el.required),
      options: tag === 'select' ? optionsFor(el) : [],
      value: tag === 'select'
        ? Array.from(el.selectedOptions || []).map((opt) => opt.value || clean(opt.text)).join(', ')
        : (type === 'checkbox' ? Boolean(el.checked) : el.value || ''),
    });
  }

  return { sections };
}
"""
    return page.evaluate(script) or {"sections": []}


def _flatten_fields(structured_form: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for section in structured_form.get("sections", []):
        for field in section.get("fields", []):
            fields.append(field)
    return fields


def _latest_video_path(min_mtime: float = 0) -> str:
    if not os.path.isdir(VIDEO_DIR):
        return ""

    videos = [
        os.path.join(VIDEO_DIR, name)
        for name in os.listdir(VIDEO_DIR)
        if name.lower().endswith((".webm", ".mp4"))
        and os.path.getmtime(os.path.join(VIDEO_DIR, name)) >= min_mtime
    ]
    if not videos:
        return ""

    return max(videos, key=os.path.getmtime)


def _visible_page_errors(page: Any) -> list[str]:
    script = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const selectors = [
    '.error',
    '.errors',
    '.field_with_errors',
    '.invalid-feedback',
    '.form-error',
    '[role="alert"]',
    '.alert-error',
    '.alert-danger'
  ];
  const messages = [];
  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      const style = window.getComputedStyle(el);
      const visible = style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
      const text = clean(el.innerText || el.textContent);
      if (visible && text && !messages.includes(text)) messages.push(text);
    }
  }
  return messages.slice(0, 20);
}
"""
    try:
        return page.evaluate(script)
    except Exception:
        return []


def _fill_field(page: Any, field: dict[str, Any], value: Any) -> tuple[bool, str | None]:
    field_type = field.get("type") or "text"
    selector = field.get("selector") or ""
    if not selector:
        return False, "Campo sin selector"

    try:
        locator = page.locator(selector)
        if locator.count() == 0:
            return False, "Elemento no encontrado"

        if field_type in ("text", "email", "url", "search", "tel", "password", "number", "date", "textarea"):
            locator.first.fill(str(value or ""), timeout=FIELD_TIMEOUT_MS)
            return True, None

        if field_type in ("select", "multiselect"):
            raw_values = value if isinstance(value, list) else str(value).split(",")
            selected = [str(item).strip() for item in raw_values if str(item).strip()]
            if not selected:
                return False, "Valor select vacio"

            option_pairs = [
                (
                    str(option.get("value") or "").strip(),
                    str(option.get("label") or "").strip(),
                )
                for option in field.get("options", [])
            ]
            allowed_values = {item[0] for item in option_pairs if item[0]}
            label_to_value = {label.lower(): val for val, label in option_pairs if val and label}

            normalized: list[str] = []
            missing: list[str] = []
            for item in selected:
                if item in allowed_values:
                    normalized.append(item)
                elif item.lower() in label_to_value:
                    normalized.append(label_to_value[item.lower()])
                else:
                    missing.append(item)

            if missing:
                return False, f"Opcion no encontrada: {', '.join(missing)}"

            locator.first.select_option(normalized, timeout=FIELD_TIMEOUT_MS)
            return True, None

        if field_type == "checkbox":
            checked = bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes", "si", "on")
            locator.first.set_checked(checked, timeout=FIELD_TIMEOUT_MS)
            return True, None

        if field_type == "radio_group":
            target = str(value)
            for option in field.get("options", []):
                if target in (str(option.get("value")), str(option.get("label"))):
                    page.locator(option.get("selector")).first.check(timeout=FIELD_TIMEOUT_MS)
                    return True, None
            return False, "Opcion de radio no encontrada"

        if field_type == "checkbox_group":
            targets = value if isinstance(value, list) else str(value).split(",")
            targets = [str(item) for item in targets]
            for option in field.get("options", []):
                opt_value = str(option.get("value") or option.get("label") or "")
                opt_selector = option.get("selector") or ""
                if not opt_selector:
                    continue
                page.locator(opt_selector).first.set_checked(opt_value in targets, timeout=FIELD_TIMEOUT_MS)
            return True, None

        locator.first.fill(str(value or ""), timeout=FIELD_TIMEOUT_MS)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _sections_to_unified_form(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Convert the flat {section, fields} list returned by the Camoufox analyzer
    into the categories/fields shape expected by form_mapper_service.map_project_to_form
    and by /api/festivals/generate-form-answers.

    Each unified field's "key" is set to the same identifier
    (selector > id > name > label) that fill_open_form() indexes fields by,
    so form_values produced by generate-form-answers can be sent to
    /api/fill-open-form unchanged.
    """
    unified_form = _empty_unified_form()
    for section in sections:
        for field in section.get("fields", []):
            if _field_should_be_ignored_for_fallback(field):
                continue

            key = (
                str(field.get("selector") or "").strip()
                or str(field.get("id") or "").strip()
                or str(field.get("name") or "").strip()
                or str(field.get("label") or "").strip()
            )
            if not key:
                continue

            options = [
                option.get("label") or option.get("value")
                if isinstance(option, dict) else option
                for option in (field.get("options") or [])
            ]

            category = _fallback_field_category(field)
            unified_form["categories"][category]["fields"].append({
                "key": key,
                "label": field.get("label") or field.get("name") or field.get("id") or key,
                "name": field.get("name") or "",
                "type": field.get("type") or "text",
                "required": bool(field.get("required")),
                "options": [opt for opt in options if opt],
            })
    return unified_form


def analyze_filmfreeway_form(email: str, password: str, festival_url: str = "") -> dict[str, Any]:
    os.makedirs(VIDEO_DIR, exist_ok=True)

    manager = Camoufox(
        headless=True,
        humanize=1.5,
        i_know_what_im_doing=True,
    )
    browser = manager.__enter__()
    context = browser.new_context(
        no_viewport=True,
        record_video_dir=VIDEO_DIR,
        record_video_size={"width": 1280, "height": 720},
    )
    page = context.new_page()

    analyze_batch_id = str(uuid.uuid4())
    started_at = time.time()

    try:
        print("Navegando a la home...")
        page.goto("https://filmfreeway.com", wait_until="networkidle", timeout=45000)
        time.sleep(3)

        print("Navegando al login...")
        page.goto("https://filmfreeway.com/login", wait_until="networkidle", timeout=45000)

        for _ in range(15):
            title = page.title()
            if "Just a moment" not in title:
                break
            time.sleep(3)

        time.sleep(3)

        print("Llenando email...")
        page.locator("#user_account_email").click()
        time.sleep(1)
        page.locator("#user_account_email").fill(email)
        time.sleep(2)

        print("Llenando password...")
        page.locator("#user_account_password").click()
        time.sleep(1)
        page.locator("#user_account_password").fill(password)
        time.sleep(2)

        print("Haciendo click en Log In...")
        submit_btn = page.locator("input[type='submit'][name='commit']")
        submit_btn.hover()
        time.sleep(1)
        submit_btn.click()

        for i in range(15):
            time.sleep(3)
            url = page.url
            title = page.title()
            print(f"  [{i+1}] URL: {url} | Titulo: {title}")
            if "login" not in url.lower() and "Just a moment" not in title:
                print("\n=== LOGIN EXITOSO! ===")
                break

        if "/projects/new" not in page.url:
            page.goto("https://filmfreeway.com/projects/new", wait_until="networkidle", timeout=45000)
            time.sleep(3)

        page.screenshot(path=SCREENSHOT_PATH, full_page=True)
        structured_form = _extract_form_fields(page)
        fields = _flatten_fields(structured_form)

        _sessions[analyze_batch_id] = {
            "manager": manager,
            "browser": browser,
            "context": context,
            "page": page,
            "started_at": started_at,
            "festival_url": festival_url,
            "structured_form": structured_form,
            "fields": fields,
        }

        try:
            register_external_unified_form(
                analyze_batch_id,
                _sections_to_unified_form(structured_form.get("sections", [])),
            )
        except Exception as exc:
            print(f"[Camoufox] No se pudo registrar unified_form para generate-form-answers: {exc}", flush=True)

        return {
            "status": "OK",
            "analyze_batch_id": analyze_batch_id,
            "sections": structured_form.get("sections", []),
            "fields_count": len(fields),
            "video_dir": VIDEO_DIR,
            "screenshot_path": SCREENSHOT_PATH,
            "final_url": page.url,
            "final_title": page.title(),
        }
    except Exception:
        try:
            context.close()
            browser.close()
            manager.__exit__(None, None, None)
        except Exception:
            pass
        raise


def fill_open_form(analyze_batch_id: str, form_values: dict[str, Any]) -> dict[str, Any]:
    session = _sessions.get(analyze_batch_id)
    if not session:
        raise ValueError(f"No existe sesion para analyze_batch_id={analyze_batch_id}")

    page = session["page"]
    context = session["context"]
    browser = session["browser"]
    manager = session["manager"]
    festival_url = session.get("festival_url") or "https://filmfreeway.com/INDIESHORTSAWARDSCANNES"
    fields = session["fields"]
    index: dict[str, dict[str, Any]] = {}

    for field in fields:
        for key in ("id", "name", "label", "selector"):
            value = str(field.get(key) or "").strip()
            if value:
                index[value] = field

    filled_count = 0
    skipped_count = 0
    errors: list[dict[str, str]] = []
    print(f"[Fill] Iniciando rellenado: {len(form_values)} valores", flush=True)

    for index_number, (key, value) in enumerate(form_values.items(), start=1):
        field = index.get(key)
        if not field:
            skipped_count += 1
            errors.append({"key": key, "reason": "Campo no encontrado"})
            print(f"[Fill] {index_number}/{len(form_values)} omitido: {key} - Campo no encontrado", flush=True)
            continue

        label = field.get("label") or field.get("name") or key
        print(f"[Fill] {index_number}/{len(form_values)} rellenando: {label}", flush=True)
        ok, reason = _fill_field(page, field, value)
        if ok:
            filled_count += 1
            print(f"[Fill] OK: {label}", flush=True)
        else:
            skipped_count += 1
            errors.append({"key": key, "reason": reason or "No se pudo rellenar"})
            print(f"[Fill] Omitido: {label} - {reason}", flush=True)

    page.screenshot(path=SCREENSHOT_PATH, full_page=True)
    print(f"[Fill] Terminado. Rellenados: {filled_count}, omitidos: {skipped_count}", flush=True)

    print("[Save] Buscando boton Save Project", flush=True)
    save_button = page.locator(
        "input[data-project-save-button='true'], input[type='submit'][name='commit'][value='Save Project']"
    ).first
    save_button.click(timeout=10000)
    print("[Save] Click Save Project enviado", flush=True)

    time.sleep(10)
    for _ in range(30):
        current_url = page.url.lower()
        if "/projects/" in current_url and "/projects/new" not in current_url:
            break
        try:
            page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass
        time.sleep(1)

    saved_url = page.url
    save_errors = _visible_page_errors(page)
    save_ok = "/projects/" in saved_url.lower() and "/projects/new" not in saved_url.lower()
    print(f"[Save] URL despues de guardar: {saved_url}", flush=True)
    if save_errors:
        print(f"[Save] Errores visibles: {save_errors}", flush=True)

    if save_ok:
        print(f"[Submit Now] Navegando al festival: {festival_url}", flush=True)
        page.goto(festival_url, wait_until="networkidle", timeout=45000)
        time.sleep(3)

        submit = page.locator(
            "a[data-event='openFestivalSubmission'], "
            "a[data-festival-submission-url], "
            "a.this-is-the-submit-button"
        ).first

        submission_url = submit.get_attribute("data-festival-submission-url", timeout=10000) or ""
        if submission_url:
            target_url = "https://filmfreeway.com" + submission_url
            print(f"[Submit Now] submission_url detectada: {target_url}", flush=True)
            page.goto(target_url, wait_until="networkidle", timeout=45000)
        else:
            print("[Submit Now] Click directo", flush=True)
            submit.click(timeout=10000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass

        time.sleep(3)
    else:
        print("[Save] El proyecto no parece guardado. Se abrira la pagina actual para ver errores.", flush=True)

    final_url = page.url
    final_title = page.title()
    page.screenshot(path=SCREENSHOT_PATH, full_page=True)
    print(f"[Final] URL final: {final_url}", flush=True)

    print("[Final View] Abriendo ventana visible al final del proceso", flush=True)
    visible_error = ""
    storage_state_path = os.path.join(VIDEO_DIR, f"{analyze_batch_id}-storage-state.json")
    try:
        context.storage_state(path=storage_state_path)
        FESTIVAL_FINAL_URL = "https://filmfreeway.com/INDIESHORTSAWARDSCANNES"
        subprocess.Popen(
            [sys.executable, OPEN_VISIBLE_SCRIPT, storage_state_path, FESTIVAL_FINAL_URL],
            cwd=BASE_DIR,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        visible_error = str(exc)
        print(f"[Final View] No se pudo abrir ventana visible: {visible_error}", flush=True)

    video_path = ""
    video = page.video
    print("[Video] Cerrando contexto headless para guardar video", flush=True)
    context.close()
    try:
        video_path = video.path() if video else ""
    except Exception as exc:
        print(f"[Video] No se pudo obtener path exacto del video: {exc}", flush=True)
        video_path = ""
    if not video_path:
        video_path = _latest_video_path(float(session.get("started_at") or 0))

    try:
        browser.close()
    except Exception:
        pass
    try:
        manager.__exit__(None, None, None)
    except Exception:
        pass

    _sessions.pop(analyze_batch_id, None)
    print(f"[Video] Guardado en: {video_path or VIDEO_DIR}", flush=True)

    return {
        "status": "OK",
        "filled_count": filled_count,
        "skipped_count": skipped_count,
        "errors": errors,
        "screenshot_path": SCREENSHOT_PATH,
        "video_path": video_path,
        "video_dir": VIDEO_DIR,
        "saved_url": saved_url,
        "save_ok": save_ok,
        "save_errors": save_errors,
        "visible_error": visible_error,
        "final_url": final_url,
        "final_title": final_title,
    }


def login_filmfreeway(email: str, password: str) -> dict[str, Any]:
    return analyze_filmfreeway_form(email, password)


if __name__ == "__main__":
    EMAIL = input("Email FilmFreeway: ").strip()
    PASSWORD = getpass("Password FilmFreeway: ")
    login_filmfreeway(EMAIL, PASSWORD)
