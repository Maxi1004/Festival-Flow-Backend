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
from urllib.parse import urljoin

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

# Texts to identify "Submit Now" / CTA buttons on festival pages
_SUBMIT_CTA_TEXTS = [
    "submit to festival", "submit now", "submit your film", "submit film",
    "submit entry", "apply now", "enter now", "submit project", "add a project",
    "enviar pelicula", "enviar película", "postular", "inscribirse",
]

# URL fragments that indicate we are on a login page
_LOGIN_PAGE_MARKERS = [
    "login", "signin", "sign-in", "account/login", "session/new",
]

# ==============================
# SELECTORES FILMFREEWAY
# Si FilmFreeway cambia el HTML, modificar aqui los selectores.
# No cambiar la logica completa.
# ==============================
FILMFREEWAY_SELECTORS = {
    "submit_now": "a[data-event='openFestivalSubmission'], a[data-festival-submission-url], a.this-is-the-submit-button",
    "login_modal_button": "a[data-modal='log-in'], a[href='/login']",
    "login_form": "form#sign_in_user",
    "modal_email": "input#user_email_dialog, input[name='user_account[email]']",
    "modal_password": "input#user_password_dialog, input[name='user_account[password]']",
    "modal_submit": "button.Button-loginSignup",
    "page_email": "input#user_account_email, input[name='user_account[email]']",
    "page_password": "input#user_account_password, input[name='user_account[password]']",
    "page_submit": "input[type='submit'][value='Log In'], input[name='commit'], input.button.btn.btn-large.btn-success.span-12",
    "add_project": "a[href='/projects/new'], a.btn.btn-primary.span-full",
}

_FILMFREEWAY_LOGGED_IN_SELECTORS = (
    "a[href*='dashboard'], "
    "a[href*='projects'], "
    "a[href*='submissions'], "
    "a[href*='account'], "
    "[class*='avatar' i], "
    "[class*='user' i]"
)

_FILMFREEWAY_IGNORED_FIELD_NAMES = {
    "csrf",
    "authenticity_token",
    "form_signature",
}


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
                    headless=False,  # AQUI QUEDA VISIBLE
                    # headless=True,  # CON ESTE QUEDA INVISIBLE
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

def _click_submit_cta(driver: Any, By: Any) -> bool:
    """
    Click the first visible 'Submit Now' / CTA button on the page.
    Returns True if a button was found and clicked, False otherwise.
    Used for platforms like FilmFreeway where the login is behind a submit CTA.
    """
    try:
        candidates = driver.find_elements(By.CSS_SELECTOR, "a, button")
        for el in candidates:
            try:
                text = (el.text or "").lower().strip()
                href = (el.get_attribute("href") or "").lower()
                if any(kw in text or kw in href for kw in _SUBMIT_CTA_TEXTS):
                    if el.is_displayed() and el.is_enabled():
                        el.click()
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _is_on_login_page(driver: Any) -> bool:
    """Return True if the current URL looks like a login page."""
    url = (driver.current_url or "").lower()
    return any(marker in url for marker in _LOGIN_PAGE_MARKERS)


def _filmfreeway_log(message: str) -> None:
    print(f"[FilmFreeway] {message}", flush=True)


def _first_visible_by_css(driver: Any, By: Any, selector: str) -> Any:
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if el.is_displayed():
                    return el
            except Exception:
                continue
    except Exception:
        pass
    return None


def _first_clickable_by_css(driver: Any, By: Any, selector: str) -> Any:
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
    except Exception:
        pass
    return None


def _is_filmfreeway_logged_in(driver: Any, By: Any) -> bool:
    if _first_visible_by_css(driver, By, _FILMFREEWAY_LOGGED_IN_SELECTORS):
        return True

    try:
        candidates = driver.find_elements(By.CSS_SELECTOR, "a, button, [role='button']")
    except Exception:
        candidates = []

    logged_in_texts = ("dashboard", "my projects", "submissions")
    for el in candidates:
        try:
            text = (el.text or "").lower().strip()
            if el.is_displayed() and any(marker == text for marker in logged_in_texts):
                return True
        except Exception:
            continue
    return False


def _wait_for_visible_css(
    driver: Any,
    wait: Any,
    By: Any,
    selector: str,
    timeout_message: str,
) -> Any:
    try:
        return wait.until(lambda d: _first_visible_by_css(d, By, selector))
    except Exception as exc:
        raise RuntimeError(timeout_message) from exc


def click_filmfreeway_submit_now(driver: Any, wait: Any, By: Any) -> bool:
    submit = _wait_for_visible_css(
        driver,
        wait,
        By,
        FILMFREEWAY_SELECTORS["submit_now"],
        "Submit Now no encontrado",
    )
    _filmfreeway_log("Submit Now encontrado")

    submission_url = submit.get_attribute("data-festival-submission-url") or ""
    if submission_url:
        target_url = urljoin("https://filmfreeway.com", submission_url)
        _filmfreeway_log(f"submission_url detectada: {target_url}")
        driver.get(target_url)
        time.sleep(2)
        return True

    _filmfreeway_log("click directo")
    submit.click()
    time.sleep(2)
    return True


def login_filmfreeway_if_needed(
    driver: Any,
    wait: Any,
    By: Any,
    email: str,
    password: str,
) -> dict[str, Any]:
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    def _wait_visible_with_fallback(
        selector: str,
        fallback_selectors: list[str],
        field_name: str,
    ) -> Any:
        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector {field_name} usado: {selector}")
        try:
            return wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
        except Exception:
            for fallback_selector in fallback_selectors:
                _filmfreeway_log(f"Selector {field_name} fallback: {fallback_selector}")
                try:
                    return wait.until(
                        EC.visibility_of_element_located(
                            (By.CSS_SELECTOR, fallback_selector)
                        )
                    )
                except Exception:
                    continue

        _filmfreeway_log(f"No se encontró login page selector: {selector}")
        raise RuntimeError(
            f"No se encontró login page selector para {field_name}: {selector}"
        )

    def _wait_clickable_with_fallback(
        selector: str,
        fallback_selectors: list[str],
        field_name: str,
    ) -> Any:
        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector {field_name} usado: {selector}")
        try:
            return wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        except Exception:
            for fallback_selector in fallback_selectors:
                _filmfreeway_log(f"Selector {field_name} fallback: {fallback_selector}")
                try:
                    return wait.until(
                        EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, fallback_selector)
                        )
                    )
                except Exception:
                    continue

        _filmfreeway_log(f"No se encontró login page selector: {selector}")
        raise RuntimeError(
            f"No se encontró login page selector para {field_name}: {selector}"
        )

    if _is_filmfreeway_logged_in(driver, By):
        _filmfreeway_log("Login exitoso")
        return {"status": "LOGIN_OK", "message": "Sesion ya iniciada."}

    _filmfreeway_log("Login requerido")

    _filmfreeway_log(f"URL actual: {driver.current_url}")
    try:
        WebDriverWait(driver, 10).until(
            lambda d: (
                "/login" in d.current_url.lower()
                or _first_visible_by_css(d, By, FILMFREEWAY_SELECTORS["login_form"])
                or _first_visible_by_css(d, By, "input#user_account_email")
                or _first_visible_by_css(d, By, "input#user_email_dialog")
            )
        )
    except Exception:
        pass

    current_url = driver.current_url
    _filmfreeway_log(f"URL después de esperar login: {current_url}")
    page_email_detected = _first_visible_by_css(driver, By, "input#user_account_email")
    modal_email_detected = _first_visible_by_css(driver, By, "input#user_email_dialog")

    is_login_page = "/login" in driver.current_url.lower() or bool(page_email_detected)
    if is_login_page:
        _filmfreeway_log("Login página detectado por URL/input")
        _filmfreeway_log("Login tipo: PAGINA")
        email_selector = FILMFREEWAY_SELECTORS["page_email"]
        password_selector = FILMFREEWAY_SELECTORS["page_password"]
        submit_selector = FILMFREEWAY_SELECTORS["page_submit"]
        email_fallbacks = [
            "input#user_account_email",
            "input[name='user_account[email]']",
        ]
        password_fallbacks = [
            "input#user_account_password",
            "input[name='user_account[password]']",
        ]
        submit_fallbacks = [
            "input[type='submit'][value='Log In']",
            "input[name='commit']",
            "input.button.btn.btn-large.btn-success.span-12",
        ]
    else:
        if modal_email_detected:
            _filmfreeway_log("Login modal detectado por input")
        _filmfreeway_log("Login tipo: MODAL")
        email_selector = FILMFREEWAY_SELECTORS["modal_email"]
        password_selector = FILMFREEWAY_SELECTORS["modal_password"]
        submit_selector = FILMFREEWAY_SELECTORS["modal_submit"]

        login_button = _first_clickable_by_css(
            driver, By, FILMFREEWAY_SELECTORS["login_modal_button"]
        )
        if login_button:
            login_button.click()
            time.sleep(1)

    _filmfreeway_log(f"Tipo de login detectado: {'PAGINA' if is_login_page else 'MODAL'}")
    _filmfreeway_log(f"Selector email usado: {email_selector}")
    _filmfreeway_log(f"Selector password usado: {password_selector}")
    _filmfreeway_log(f"Selector submit usado: {submit_selector}")

    if is_login_page:
        email_input = _wait_visible_with_fallback(
            email_selector, email_fallbacks, "email"
        )
        _filmfreeway_log("Email encontrado")
        password_input = _wait_visible_with_fallback(
            password_selector, password_fallbacks, "password"
        )
        _filmfreeway_log("Password encontrado")
    else:
        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector form usado: {FILMFREEWAY_SELECTORS['login_form']}")
        form = _wait_for_visible_css(
            driver,
            wait,
            By,
            FILMFREEWAY_SELECTORS["login_form"],
            "Formulario de login FilmFreeway no encontrado",
        )
        if not form:
            return {
                "status": "LOGIN_FAILED",
                "message": "Formulario de login FilmFreeway no encontrado.",
            }

        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector email usado: {email_selector}")
        email_input = _wait_for_visible_css(
            driver,
            wait,
            By,
            email_selector,
            "Campo email FilmFreeway no encontrado",
        )
        _filmfreeway_log("Email encontrado")

        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector password usado: {password_selector}")
        password_input = _wait_for_visible_css(
            driver,
            wait,
            By,
            password_selector,
            "Campo password FilmFreeway no encontrado",
        )
        _filmfreeway_log("Password encontrado")

    email_input.clear()
    email_input.send_keys(email)
    password_input.clear()
    password_input.send_keys(password)
    _filmfreeway_log("Credenciales escritas")

    if is_login_page:
        login_submit = _wait_clickable_with_fallback(
            submit_selector, submit_fallbacks, "submit"
        )
    else:
        _filmfreeway_log(f"URL actual: {driver.current_url}")
        _filmfreeway_log(f"Selector submit usado: {submit_selector}")
        login_submit = _first_clickable_by_css(
            driver, By, submit_selector
        )
    if not login_submit:
        _filmfreeway_log(f"No se encontró login page selector: {submit_selector}")
        return {
            "status": "LOGIN_FAILED",
            "message": "Boton Log In FilmFreeway no encontrado.",
        }

    login_submit.click()
    _filmfreeway_log("Click login enviado")
    try:
        wait.until(lambda d: _is_filmfreeway_logged_in(d, By))
    except Exception:
        time.sleep(4)

    if _is_filmfreeway_logged_in(driver, By):
        _filmfreeway_log("Login exitoso")
        return {"status": "LOGIN_OK", "message": "Login completado con exito."}

    _filmfreeway_log("Login fallo")
    return {
        "status": "LOGIN_FAILED",
        "message": "Login FilmFreeway no confirmado.",
    }


def handle_ready_to_submit_modal(driver: Any, By: Any) -> bool:
    add_project = None
    deadline = time.time() + 8
    while time.time() < deadline:
        add_project = _first_clickable_by_css(
            driver, By, FILMFREEWAY_SELECTORS["add_project"]
        )
        if add_project:
            break
        time.sleep(0.5)

    if not add_project:
        _filmfreeway_log("Modal Ready To Submit no detectado")
        return False

    _filmfreeway_log("Add Project detectado")
    add_project.click()
    time.sleep(3)
    return True


def _field_label(driver: Any, By: Any, element: Any, field_id: str) -> str:
    if field_id:
        try:
            label = driver.find_element(By.CSS_SELECTOR, f"label[for='{field_id}']")
            text = label.text.strip()
            if text:
                return text
        except Exception:
            pass

    try:
        wrapping_label = element.find_element(By.XPATH, "ancestor::label[1]")
        text = wrapping_label.text.strip()
        if text:
            return text
    except Exception:
        pass

    try:
        aria_labelledby = element.get_attribute("aria-labelledby") or ""
        labels = []
        for label_id in aria_labelledby.split():
            label_el = driver.find_element(By.CSS_SELECTOR, f"#{label_id}")
            label_text = label_el.text.strip()
            if label_text:
                labels.append(label_text)
        if labels:
            return " ".join(labels)
    except Exception:
        pass

    return element.get_attribute("aria-label") or ""


def _field_selector(element: Any, tag: str, field_id: str, name: str) -> str:
    if field_id:
        return f"#{field_id}"
    if name:
        return f"{tag}[name='{name}']"
    return tag


def extract_form_fields(driver: Any, By: Any) -> list[dict]:
    _filmfreeway_log("Extrayendo formulario")
    fields: list[dict] = []

    try:
        elements = driver.find_elements(
            By.CSS_SELECTOR, "input, textarea, select"
        )
    except Exception:
        elements = []

    for el in elements:
        try:
            tag = (el.tag_name or "").lower()
            field_type = (el.get_attribute("type") or tag).lower()
            name = el.get_attribute("name") or ""
            field_id = el.get_attribute("id") or ""
            name_key = name.lower()

            if field_type == "hidden":
                continue
            if name_key in _FILMFREEWAY_IGNORED_FIELD_NAMES:
                continue
            if "csrf" in name_key or "authenticity_token" in name_key:
                continue
            if not el.is_displayed():
                continue

            options: list[dict[str, Any]] = []
            if tag == "select":
                try:
                    for opt in el.find_elements(By.TAG_NAME, "option"):
                        options.append({
                            "label": (opt.text or "").strip(),
                            "value": opt.get_attribute("value") or "",
                        })
                except Exception:
                    options = []

            fields.append({
                "label": _field_label(driver, By, el, field_id),
                "name": name,
                "id": field_id,
                "type": field_type,
                "tag": tag,
                "required": el.get_attribute("required") is not None,
                "placeholder": el.get_attribute("placeholder") or "",
                "options": options,
                "selector": _field_selector(el, tag, field_id, name),
                "visible": True,
            })
        except Exception:
            continue

    _filmfreeway_log(f"Campos encontrados: {len(fields)}")
    return fields


def extract_structured_form(driver: Any) -> dict[str, Any]:
    _filmfreeway_log("Extrayendo formulario")
    script = """
const isVisible = (el) => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  return el.getClientRects().length > 0;
};

const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();

const cssEscape = (value) => {
  if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\\\]/g, '\\\\$&');
};

const selectorFor = (el) => {
  const tag = (el.tagName || '').toLowerCase();
  if (el.id) return `${tag}#${cssEscape(el.id)}`;
  if (el.name) return `${tag}[name="${cssEscape(el.name)}"]`;
  const classes = Array.from(el.classList || []).slice(0, 3).map(cssEscape);
  if (classes.length) return `${tag}.${classes.join('.')}`;
  return tag;
};

const labelFor = (el) => {
  if (el.id) {
    const exact = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
    const text = cleanText(exact && exact.innerText);
    if (text) return text;
  }
  const aria = cleanText(el.getAttribute('aria-label'));
  if (aria) return aria;

  const labelledBy = cleanText(el.getAttribute('aria-labelledby'));
  if (labelledBy) {
    const parts = labelledBy.split(' ')
      .map((id) => cleanText((document.getElementById(id) || {}).innerText))
      .filter(Boolean);
    if (parts.length) return parts.join(' ');
  }

  const wrappingLabel = el.closest('label');
  const wrappingText = cleanText(wrappingLabel && wrappingLabel.innerText);
  if (wrappingText) return wrappingText;

  const holder = el.closest('.field, .form-group, .control-group, .input, .row, .columns, li, div');
  if (holder) {
    const label = holder.querySelector('label');
    const text = cleanText(label && label.innerText);
    if (text) return text;
  }

  return cleanText(el.getAttribute('placeholder')) || cleanText(el.getAttribute('name')) || cleanText(el.id);
};

const sectionHeadingSelectors = [
  'legend',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  '[role="heading"]',
  '[class*="section" i][class*="title" i]',
  '[class*="section" i][class*="header" i]',
  '[class*="accordion" i][class*="title" i]',
  '[class*="accordion" i][class*="header" i]',
  '[class*="panel" i][class*="title" i]',
  '[class*="panel" i][class*="header" i]'
].join(',');

const headingTextFrom = (container, control) => {
  if (!container) return '';
  const headings = Array.from(container.querySelectorAll(sectionHeadingSelectors))
    .filter((el) => isVisible(el) && cleanText(el.innerText));
  if (!headings.length) return '';
  const before = headings.filter((el) => (el.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING));
  const heading = before.length ? before[before.length - 1] : headings[0];
  return cleanText(heading.innerText);
};

const sectionFor = (el, currentTitle) => {
  const fieldset = el.closest('fieldset');
  const legendText = cleanText(fieldset && fieldset.querySelector('legend') && fieldset.querySelector('legend').innerText);
  if (legendText) return legendText;

  const sectionContainer = el.closest('section, article, .section, .form-section, .accordion, .accordion-item, .panel, .card, .fieldset, .row');
  const containerHeading = headingTextFrom(sectionContainer, el);
  if (containerHeading) return containerHeading;

  return currentTitle || 'Formulario';
};

const optionsForSelect = (el) => Array.from(el.options || []).map((opt) => ({
  label: cleanText(opt.text),
  value: opt.value || cleanText(opt.text),
  selected: Boolean(opt.selected),
}));

const optionForChoice = (el) => ({
  label: labelFor(el),
  value: el.value || labelFor(el),
  id: el.id || '',
  selector: selectorFor(el),
  checked: Boolean(el.checked),
});

const isIgnoredInput = (el) => {
  const type = (el.getAttribute('type') || '').toLowerCase();
  const name = (el.getAttribute('name') || '').toLowerCase();
  if (type === 'hidden') return true;
  if (type === 'submit') return true;
  if (type === 'search' && !el.name && !el.id) return true;
  if (['authenticity_token', 'form_signature', 'commit'].includes(name)) return true;
  return false;
};

const dynamicButtonText = (el) => cleanText(el.innerText || el.value || el.getAttribute('aria-label'));
const isDynamicButton = (el) => {
  const text = dynamicButtonText(el).toLowerCase();
  const href = (el.getAttribute('href') || '').toLowerCase();
  const classes = (el.className || '').toString().toLowerCase();
  return /^add\\b/.test(text) || text.includes(' add ') || href.includes('/new') || classes.includes('add');
};

const form = document.querySelector('form') || document.body;
const sections = [];
const sectionMap = new Map();
const groupedChoices = new Set();

const ensureSection = (title) => {
  const safeTitle = cleanText(title) || 'Formulario';
  if (!sectionMap.has(safeTitle)) {
    const section = { title: safeTitle, fields: [] };
    sectionMap.set(safeTitle, section);
    sections.push(section);
  }
  return sectionMap.get(safeTitle);
};

const addField = (sectionTitle, field) => {
  const section = ensureSection(sectionTitle);
  field.section = section.title;
  section.fields.push(field);
};

let currentTitle = 'Formulario';
const nodes = Array.from(form.querySelectorAll(`${sectionHeadingSelectors}, input, textarea, select, button, a`));

for (const node of nodes) {
  const tag = (node.tagName || '').toLowerCase();
  const nodeVisible = isVisible(node);
  const readableHiddenSelect = tag === 'select' && node.name && (node.options || []).length > 0;
  if (!nodeVisible && !readableHiddenSelect) continue;
  const text = cleanText(node.innerText);

  if (nodeVisible && node.matches(sectionHeadingSelectors) && text) {
    currentTitle = text;
    ensureSection(currentTitle);
    continue;
  }

  if (tag === 'button' || tag === 'a') {
    if (!isDynamicButton(node)) continue;
    addField(sectionFor(node, currentTitle), {
      label: dynamicButtonText(node),
      name: node.getAttribute('name') || '',
      id: node.id || '',
      type: 'dynamic_button',
      required: false,
      placeholder: '',
      selector: selectorFor(node),
      options: [],
      current_value: dynamicButtonText(node),
    });
    continue;
  }

  if (!['input', 'textarea', 'select'].includes(tag)) continue;
  if (tag === 'input' && isIgnoredInput(node)) continue;

  const type = tag === 'select'
    ? (node.multiple ? 'multiselect' : 'select')
    : ((node.getAttribute('type') || tag).toLowerCase());
  const name = node.getAttribute('name') || '';
  const id = node.id || '';
  const label = labelFor(node);
  if (!name && !label) continue;

  const sectionTitle = sectionFor(node, currentTitle);

  if ((type === 'checkbox' || type === 'radio') && name) {
    const groupKey = `${sectionTitle}:${type}:${name}`;
    if (groupedChoices.has(groupKey)) continue;
    groupedChoices.add(groupKey);

    const groupItems = Array.from(form.querySelectorAll(`input[type="${type}"]`))
      .filter((item) => item.name === name && isVisible(item));
    const options = groupItems.map(optionForChoice);
    const checked = options.filter((opt) => opt.checked).map((opt) => opt.value);

    addField(sectionTitle, {
      label: label || name,
      name,
      id,
      type: `${type}_group`,
      required: groupItems.some((item) => item.required || item.getAttribute('aria-required') === 'true'),
      placeholder: '',
      selector: `input[type="${type}"][name="${cssEscape(name)}"]`,
      options,
      current_value: type === 'radio' ? (checked[0] || '') : checked,
    });
    continue;
  }

  addField(sectionTitle, {
    label,
    name,
    id,
    type,
    required: Boolean(node.required || node.getAttribute('aria-required') === 'true'),
    placeholder: node.getAttribute('placeholder') || '',
    selector: selectorFor(node),
    options: tag === 'select' ? optionsForSelect(node) : [],
    current_value: tag === 'select'
      ? Array.from(node.selectedOptions || []).map((opt) => opt.value || cleanText(opt.text))
      : (type === 'checkbox' ? Boolean(node.checked) : node.value || ''),
  });
}

return { sections };
"""
    structured_form = driver.execute_script(script) or {"sections": []}
    sections = structured_form.get("sections", [])
    total_fields = 0
    for section in sections:
        fields_count = len(section.get("fields", []))
        total_fields += fields_count
        _filmfreeway_log(f"Sección encontrada: {section.get('title', 'Formulario')}")
        _filmfreeway_log(f"Campos sección: {fields_count}")

    _filmfreeway_log(f"Total secciones: {len(sections)}")
    _filmfreeway_log(f"Total campos: {total_fields}")
    return structured_form


def _flatten_structured_form_fields(structured_form: dict[str, Any]) -> list[dict]:
    fields: list[dict] = []
    for section in structured_form.get("sections", []):
        section_title = section.get("title", "")
        for field in section.get("fields", []):
            flat_field = dict(field)
            flat_field.setdefault("section", section_title)
            flat_field["visible"] = True
            fields.append(flat_field)
    return fields


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


_LOCAL_FALLBACK_RULES = {
    "pelicula": [
        "project[title]",
        "project[synopsis]",
        "project[genres_video]",
        "project[runtime_hours]",
        "project[runtime_minutes]",
        "project[runtime_seconds]",
        "project[completion_date]",
        "project[production_budget]",
        "project[production_budget_currency]",
    ],
    "director": [
        "project[posted_credits][directors]",
        "first_name",
        "middle_name",
        "last_name",
    ],
    "tecnico": [
        "project[countries_of_origin]",
        "project[countries_of_filming]",
        "project[languages]",
        "project[shooting_format]",
        "project[aspect_ratio]",
        "project[film_color]",
        "project[student_project]",
        "project[first_time_filmmaker]",
    ],
    "archivos": [
        "project[project_website]",
        "project[social_twitter]",
        "project[social_bluesky]",
        "project[social_facebook]",
        "project[social_instagram]",
    ],
}

_LOCAL_FALLBACK_IGNORED_NAMES = {
    "authenticity_token",
    "form_signature",
    "commit",
}


def _unified_form_is_empty(unified_form: dict[str, Any]) -> bool:
    categories = unified_form.get("categories") or {}
    return not any(
        category.get("fields")
        for category in categories.values()
        if isinstance(category, dict)
    )


def _fallback_field_key(field: dict[str, Any]) -> str:
    raw = field.get("name") or field.get("id") or field.get("label") or "field"
    key = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(raw))
    key = "_".join(part for part in key.split("_") if part)
    return key or "field"


def _fallback_field_category(field: dict[str, Any]) -> str:
    name = str(field.get("name") or "").lower()
    field_id = str(field.get("id") or "").lower()
    label = str(field.get("label") or "").lower()
    combined = f"{name} {field_id} {label}"

    if "prior_credits" in combined and "directors" in combined:
        return "director"

    for category, rules in _LOCAL_FALLBACK_RULES.items():
        if any(rule in combined for rule in rules):
            return category

    return "pelicula"


def _field_should_be_ignored_for_fallback(field: dict[str, Any]) -> bool:
    name = str(field.get("name") or "").strip()
    field_id = str(field.get("id") or "").strip()
    label = str(field.get("label") or "").strip()
    field_type = str(field.get("type") or "").lower()

    if field_type == "submit":
        return True
    if field_type == "search" and not name and not field_id:
        return True
    if not name and not label:
        return True

    lowered_name = name.lower()
    if lowered_name in _LOCAL_FALLBACK_IGNORED_NAMES:
        return True
    if "authenticity_token" in lowered_name or "form_signature" in lowered_name:
        return True

    return False


def _build_local_unified_form(fields_by_festival: dict[str, Any]) -> dict[str, Any]:
    unified_form = _empty_unified_form()
    seen: dict[str, dict[str, Any]] = {}
    total_fields = 0

    for festival_id, festival_data in fields_by_festival.items():
        for field in festival_data.get("fields", []):
            if _field_should_be_ignored_for_fallback(field):
                continue

            category = _fallback_field_category(field)
            key = _fallback_field_key(field)
            dedupe_key = f"{category}:{field.get('name') or field.get('id') or key}"

            if dedupe_key not in seen:
                unified_field = {
                    "key": key,
                    "label": field.get("label") or field.get("placeholder") or field.get("name") or field.get("id") or key,
                    "type": field.get("type") or field.get("tag") or "text",
                    "required": bool(field.get("required")),
                    "options": field.get("options") or [],
                    "festivals": [],
                    "source_fields": [],
                }
                seen[dedupe_key] = unified_field
                unified_form["categories"][category]["fields"].append(unified_field)
                total_fields += 1

            unified_field = seen[dedupe_key]
            if festival_id not in unified_field["festivals"]:
                unified_field["festivals"].append(festival_id)
            unified_field["required"] = bool(
                unified_field["required"] or field.get("required")
            )
            if not unified_field["options"] and field.get("options"):
                unified_field["options"] = field.get("options") or []
            unified_field["source_fields"].append({
                "festival_id": festival_id,
                "name": field.get("name", ""),
                "id": field.get("id", ""),
                "selector": field.get("selector", ""),
                "label": field.get("label", ""),
            })

    unified_form["warning"] = "IA no disponible, formulario generado con fallback local"
    print(
        f"[Festival Analyze] Unified form fallback creado con {total_fields} campos",
        flush=True,
    )
    return unified_form


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
    )

    fields_by_festival: dict[str, Any] = {}
    structured_forms: dict[str, Any] = {}
    form_urls: dict[str, str] = {}
    kept_drivers: dict[str, Any] = {}

    for festival_id in festival_ids:
        creds = credentials_map.get(festival_id, {})
        _username = creds.get("username", "")
        _password = creds.get("password", "")
        festival_url = creds.get("festival_url") or creds.get("login_url", "")

        driver = None
        try:
            driver = _build_driver(headless=False, buster_crx=_DEFAULT_BUSTER_PATH)  # AQUI QUEDA VISIBLE
            # driver = _build_driver(headless=True, buster_crx=_DEFAULT_BUSTER_PATH)  # CON ESTE QUEDA INVISIBLE
            wait = WebDriverWait(driver, 20)

            festival_page_url = festival_url  # remember original URL for post-login nav

            _filmfreeway_log("Abriendo festival")
            driver.get(festival_url)
            time.sleep(3)

            # If the page has a "Submit Now" CTA (e.g. FilmFreeway festival page),
            # click it — this typically redirects to the platform's login page.
            click_filmfreeway_submit_now(driver, wait, By)

            login_result = login_filmfreeway_if_needed(
                driver, wait, By, _username, _password
            )
            if login_result["status"] != "LOGIN_OK":
                structured_forms[festival_id] = {"sections": []}
                fields_by_festival[festival_id] = {
                    "status": login_result["status"],
                    "message": login_result["message"],
                    "fields": [],
                    "structured_form": {"sections": []},
                }
                continue

            # After login, navigate to the festival page if we're not already there.
            _filmfreeway_log("Volviendo a Submit Now")
            if driver.current_url.rstrip("/") != festival_page_url.rstrip("/"):
                driver.get(festival_page_url)
                time.sleep(3)

            # Click the CTA to reach the actual submission form.
            click_filmfreeway_submit_now(driver, wait, By)
            handle_ready_to_submit_modal(driver, By)
            time.sleep(3)

            # Try to extract fields from the current page first.
            form_url = driver.current_url
            structured_form = extract_structured_form(driver)
            fields = _flatten_structured_form_fields(structured_form)
            if not fields:
                fields = extract_form_fields(driver, By)
                structured_form = {
                    "sections": [{
                        "title": "Formulario",
                        "fields": fields,
                    }],
                }

            if not fields:
                structured_forms[festival_id] = {"sections": []}
                fields_by_festival[festival_id] = {
                    "status": "NO_FORM_FIELDS_FOUND",
                    "message": "Se llego al flujo de postulacion, pero no se encontraron campos visibles.",
                    "fields": [],
                    "structured_form": {"sections": []},
                }
                continue

            form_urls[festival_id] = form_url
            structured_forms[festival_id] = structured_form
            fields_by_festival[festival_id] = {
                "status": "OK",
                "form_url": form_url,
                "fields": fields,
                "structured_form": structured_form,
            }

        except Exception as exc:
            structured_forms[festival_id] = {"sections": []}
            fields_by_festival[festival_id] = {
                "status": "error",
                "message": f"{type(exc).__name__}: {exc}",
                "fields": [],
                "structured_form": {"sections": []},
            }
        finally:
            if driver:
                kept_drivers[festival_id] = driver
            _username = None  # noqa: F841
            _password = None  # noqa: F841

    try:
        unified_form = _call_gemini_unify_forms(fields_by_festival)
        if _unified_form_is_empty(unified_form):
            print(
                "[Festival Analyze] Gemini falló, usando fallback local",
                flush=True,
            )
            unified_form = _build_local_unified_form(fields_by_festival)
    except Exception as exc:
        print(
            "[Festival Analyze] Gemini falló, usando fallback local",
            flush=True,
        )
        unified_form = _build_local_unified_form(fields_by_festival)
        unified_form["error"] = f"Error al generar formulario unificado: {exc}"

    analyze_batch_id = str(uuid.uuid4())
    with _analyze_lock:
        _analyze_results[analyze_batch_id] = {
            "fields_by_festival": fields_by_festival,
            "form_urls": form_urls,
            "structured_form": structured_forms,
            "drivers": kept_drivers,
            "credentials_map": {
                fid: dict(c) for fid, c in credentials_map.items()
            },
            "unified_form": unified_form,
        }

    return {
        "analyze_batch_id": analyze_batch_id,
        "unified_form": unified_form,
        "fields_by_festival": fields_by_festival,
        "structured_form": structured_forms,
    }


def analyze_batch_exists(analyze_batch_id: str) -> bool:
    with _analyze_lock:
        return analyze_batch_id in _analyze_results


def get_analyze_result(analyze_batch_id: str) -> dict | None:
    """Return the full cached analysis result for the given batch ID, or None."""
    with _analyze_lock:
        return _analyze_results.get(analyze_batch_id)


def register_external_unified_form(analyze_batch_id: str, unified_form: dict[str, Any]) -> None:
    """
    Register a unified form produced by another flow (e.g. the Camoufox
    FilmFreeway analyzer) under this module's batch store, keyed by the same
    analyze_batch_id it was generated with.

    This lets /api/festivals/generate-form-answers map project data onto forms
    analyzed outside of analyze_festival_forms(), without duplicating its
    local/Gemini mapping logic.
    """
    with _analyze_lock:
        _analyze_results[analyze_batch_id] = {"unified_form": unified_form}


# ── fill-open-form helpers ────────────────────────────────────────────────────

def _locate_element(driver: Any, By: Any, field: dict) -> Any:
    """Locate a DOM element using selector → id → name priority."""
    selector = (field.get("selector") or "").strip()
    field_id = (field.get("id") or "").strip()
    field_name = (field.get("name") or "").strip()

    if selector:
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in candidates:
                try:
                    if el.is_enabled():
                        return el
                except Exception:
                    pass
            if candidates:
                return candidates[0]
        except Exception:
            pass

    if field_id:
        try:
            return driver.find_element(By.ID, field_id)
        except Exception:
            pass

    if field_name:
        try:
            return driver.find_element(By.NAME, field_name)
        except Exception:
            pass

    return None


def _locate_option_element(driver: Any, By: Any, opt: dict) -> Any:
    """Locate a checkbox/radio option element from its metadata dict."""
    opt_selector = (opt.get("selector") or "").strip()
    opt_id = (opt.get("id") or "").strip()

    if opt_selector:
        try:
            return driver.find_element(By.CSS_SELECTOR, opt_selector)
        except Exception:
            pass

    if opt_id:
        try:
            return driver.find_element(By.ID, opt_id)
        except Exception:
            pass

    return None


def _fill_select_element(driver: Any, el: Any, value: Any) -> "tuple[bool, str | None]":
    """Fill a <select> element; falls back to JS for hidden selects."""
    from selenium.webdriver.support.ui import Select

    is_visible = False
    try:
        is_visible = el.is_displayed()
    except Exception:
        pass

    if is_visible:
        try:
            sel = Select(el)
            try:
                sel.select_by_value(str(value))
                return True, None
            except Exception:
                pass
            try:
                sel.select_by_visible_text(str(value))
                return True, None
            except Exception:
                pass
            return False, f"Valor '{value}' no encontrado en las opciones del select"
        except Exception as exc:
            return False, f"Select error: {exc}"

    # Hidden select (custom plugin) — JS fallback
    try:
        driver.execute_script(
            "arguments[0].value = arguments[1]; "
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true})); "
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
            el, str(value),
        )
        return True, None
    except Exception as exc:
        return False, f"JS select error: {exc}"


def _fill_multiselect_element(el: Any, values: Any) -> "tuple[bool, str | None]":
    """Fill a multiple-select element with a list of values."""
    from selenium.webdriver.support.ui import Select

    vals = values if isinstance(values, list) else [values]
    try:
        sel = Select(el)
        sel.deselect_all()
        for v in vals:
            try:
                sel.select_by_value(str(v))
            except Exception:
                try:
                    sel.select_by_visible_text(str(v))
                except Exception:
                    pass
        return True, None
    except Exception as exc:
        return False, f"Multiselect error: {exc}"


def _fill_choice_group(
    driver: Any, By: Any, field: dict, field_type: str, value: Any
) -> "tuple[bool, str | None]":
    """Fill radio_group or checkbox_group by clicking the matching options."""
    options = field.get("options") or []

    if field_type == "radio_group":
        target = str(value)
        for opt in options:
            opt_val = str(opt.get("value") or opt.get("label") or "")
            if opt_val == target or opt_val.lower() == target.lower():
                el = _locate_option_element(driver, By, opt)
                if el:
                    try:
                        el.click()
                        return True, None
                    except Exception as exc:
                        return False, f"Radio click error: {exc}"
        return False, f"Radio value '{value}' no encontrado entre opciones"

    # checkbox_group
    if isinstance(value, bool):
        targets: list[str] = []
    elif isinstance(value, list):
        targets = [str(v) for v in value]
    else:
        targets = [str(value)]
    targets_lower = [t.lower() for t in targets]

    for opt in options:
        opt_val = str(opt.get("value") or opt.get("label") or "")
        should_check = opt_val in targets or opt_val.lower() in targets_lower

        el = _locate_option_element(driver, By, opt)
        if el is None:
            continue

        try:
            is_checked = el.is_selected()
            if should_check and not is_checked:
                el.click()
            elif not should_check and is_checked:
                el.click()
        except Exception:
            pass

    return True, None


def fill_selenium_field(
    driver: Any, By: Any, field: dict, value: Any
) -> "tuple[bool, str | None]":
    """
    Fill a single form field in the open browser.
    Returns (success, error_reason). error_reason is None on success.
    """
    field_type = (field.get("type") or "text").lower()

    if field_type == "dynamic_button":
        return False, "dynamic_button: skip"

    if field_type in ("checkbox_group", "radio_group"):
        return _fill_choice_group(driver, By, field, field_type, value)

    el = _locate_element(driver, By, field)
    if el is None:
        return False, "Elemento no encontrado en el DOM"

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(0.15)
    except Exception:
        pass

    try:
        if field_type in ("text", "email", "url", "search", "number", "date", "tel", "password"):
            el.clear()
            el.send_keys(str(value))
            return True, None

        if field_type == "textarea":
            el.clear()
            el.send_keys(str(value))
            return True, None

        if field_type in ("select", "select-one"):
            return _fill_select_element(driver, el, value)

        if field_type in ("multiselect", "select-multiple"):
            return _fill_multiselect_element(el, value)

        if field_type == "checkbox":
            target_checked = (
                bool(value)
                if isinstance(value, bool)
                else str(value).lower() in ("true", "1", "yes", "si", "on")
            )
            if el.is_selected() != target_checked:
                el.click()
            return True, None

        # Default: treat as text input
        el.clear()
        el.send_keys(str(value))
        return True, None

    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _build_festival_field_index(
    structured_form_by_festival: dict[str, Any],
    fields_by_festival: dict[str, Any],
    festival_id: str,
) -> dict[str, dict]:
    """
    Build a lookup index {attr_value → field_dict} for a single festival.
    Indexes by id, name, selector, label, key, and field_id.
    """
    index: dict[str, dict] = {}

    def _register(field: dict) -> None:
        for attr in ("key", "field_id", "id", "name", "selector", "label"):
            val = (field.get(attr) or "").strip()
            if val:
                index.setdefault(val, field)
                low = val.lower()
                if low != val:
                    index.setdefault(low, field)

    sf = structured_form_by_festival.get(festival_id, {})
    for section in sf.get("sections", []):
        for field in section.get("fields", []):
            _register(field)

    festival_data = fields_by_festival.get(festival_id, {})
    for field in festival_data.get("fields", []):
        _register(field)

    return index


# ── Public API: fill_open_form ────────────────────────────────────────────────

def fill_open_form(
    analyze_batch_id: str,
    form_values: dict[str, Any],
) -> dict[str, Any]:
    """
    Fill open Selenium browser(s) using drivers kept from analyze_festival_forms.
    Does NOT submit the form and does NOT close any browser window.

    Raises ValueError with a descriptive message on invalid batch / missing data.
    """
    from selenium.webdriver.common.by import By

    print(f"[Fill Open Form] Batch: {analyze_batch_id}", flush=True)

    with _analyze_lock:
        analyze_data = _analyze_results.get(analyze_batch_id)

    if not analyze_data:
        raise ValueError(f"Batch '{analyze_batch_id}' no encontrado")

    drivers: dict[str, Any] = analyze_data.get("drivers", {})
    if not drivers:
        raise ValueError("No hay drivers guardados para este batch")

    structured_form_by_festival: dict = analyze_data.get("structured_form", {})
    fields_by_festival: dict = analyze_data.get("fields_by_festival", {})

    if not structured_form_by_festival and not fields_by_festival:
        raise ValueError(
            "No hay datos de formulario (structured_form / fields_by_festival) para este batch"
        )

    filled_count = 0
    skipped_count = 0
    errors: list[dict] = []
    matched_keys: set[str] = set()

    for festival_id, driver in drivers.items():
        print(f"[Fill Open Form] Driver encontrado para festival: {festival_id}", flush=True)

        field_index = _build_festival_field_index(
            structured_form_by_festival, fields_by_festival, festival_id
        )

        for key, value in form_values.items():
            field = field_index.get(key) or field_index.get(key.lower())
            if field is None:
                continue

            matched_keys.add(key)
            label = (field.get("label") or field.get("name") or key).strip()

            try:
                ok, reason = fill_selenium_field(driver, By, field, value)
            except Exception as exc:
                ok, reason = False, f"{type(exc).__name__}: {exc}"

            if ok:
                filled_count += 1
                print(f"[Fill Open Form] Campo rellenado: {label} ({key})", flush=True)
            elif reason == "dynamic_button: skip":
                # Silently skip dynamic buttons — they are not fillable fields
                pass
            else:
                skipped_count += 1
                print(f"[Fill Open Form] Campo omitido: {label} ({key}) - {reason}", flush=True)
                errors.append({"key": key, "label": label, "reason": reason or "No se pudo rellenar"})

    # Any key that never matched a field in any festival counts as skipped
    for key in form_values:
        if key not in matched_keys and key.lower() not in matched_keys:
            skipped_count += 1
            print(f"[Fill Open Form] Campo omitido: {key} - No encontrado en formulario", flush=True)
            errors.append({"key": key, "label": "", "reason": "Campo no encontrado en formulario"})

    print(f"[Fill Open Form] Total rellenados: {filled_count}", flush=True)
    print(f"[Fill Open Form] Total omitidos: {skipped_count}", flush=True)

    return {
        "status": "OK",
        "filled_count": filled_count,
        "skipped_count": skipped_count,
        "errors": errors,
    }


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
                driver = _build_driver(headless=False, buster_crx=_DEFAULT_BUSTER_PATH)  # AQUI QUEDA VISIBLE
                # driver = _build_driver(headless=True, buster_crx=_DEFAULT_BUSTER_PATH)  # CON ESTE QUEDA INVISIBLE
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
