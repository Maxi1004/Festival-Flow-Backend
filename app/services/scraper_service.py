"""
Scraper service: authenticated login + form extraction via Playwright.

Session management
------------------
  Login saves browser state (cookies + localStorage) to sessions/{session_id}.json.
  The session_id is a SHA-256 hash of (login domain + username) so the same
  credentials always map to the same session file — enabling automatic reuse.

  Passwords are NEVER logged, stored, or returned in any response.

Security
--------
  - Credentials are only held in memory for the duration of the login call.
  - Session files contain browser state, NOT credentials.
  - URL validation rejects non-http(s) schemes.
"""

import asyncio
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from app.services.captcha_service import detect_captcha, get_captcha_provider

# ── Session storage directory ─────────────────────────────────────────────────
# Project root / sessions / <session_id>.json
# Added to .gitignore — never committed.
_SESSIONS_DIR = Path(__file__).resolve().parents[2] / "sessions"

# ── Field selectors for login forms ──────────────────────────────────────────
_USERNAME_SELECTORS = [
    "input[type='email']",
    "input[name*='user' i]",
    "input[name*='email' i]",
    "input[name*='login' i]",
    "input[id*='user' i]",
    "input[id*='email' i]",
    "input[id*='login' i]",
    "input[type='text']",
]

_PASSWORD_SELECTORS = [
    "input[type='password']",
]

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Login')",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "button:has-text('Iniciar sesión')",
    "button:has-text('Iniciar sesion')",
    "button:has-text('Entrar')",
    "button:has-text('Acceder')",
]

_LOGIN_ERROR_MARKERS = [
    "contraseña incorrecta", "incorrect password", "invalid password",
    "wrong password", "authentication failed", "login failed",
    "credenciales inválidas", "invalid credentials",
    "usuario no encontrado", "user not found",
    "email o contraseña", "email or password",
]

_LOGIN_PAGE_MARKERS = ["login", "signin", "sign-in", "auth", "acceso", "ingresar"]

# ── JavaScript — extract all visible form fields ──────────────────────────────
# Identical extraction logic used in festival_scraper_service.py.
_FORM_EXTRACTION_JS = """
() => {
  function clean(value) {
    return (value || "").toString().trim();
  }

  function cssEscape(value) {
    if (!value) return "";
    return value.replace(/"/g, '\\"');
  }

  function labelFor(el) {
    const id = el.getAttribute("id");
    if (id) {
      const label = document.querySelector(`label[for="${cssEscape(id)}"]`);
      if (label && clean(label.innerText)) return clean(label.innerText);
    }

    const parentLabel = el.closest("label");
    if (parentLabel && clean(parentLabel.innerText)) {
      return clean(parentLabel.innerText);
    }

    const aria = el.getAttribute("aria-label");
    if (clean(aria)) return clean(aria);

    const placeholder = el.getAttribute("placeholder");
    if (clean(placeholder)) return clean(placeholder);

    let prev = el.previousElementSibling;
    let attempts = 0;
    while (prev && attempts < 3) {
      const txt = clean(prev.innerText || prev.textContent);
      if (txt) return txt;
      prev = prev.previousElementSibling;
      attempts++;
    }

    const fieldset = el.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && clean(legend.innerText)) return clean(legend.innerText);
    }

    return clean(el.getAttribute("name")) || clean(el.getAttribute("id")) || "Campo sin nombre";
  }

  function optionsFor(el) {
    if (el.tagName.toLowerCase() === "select") {
      return Array.from(el.querySelectorAll("option"))
        .map(o => clean(o.innerText || o.value))
        .filter(Boolean);
    }

    if (el.type === "radio" || el.type === "checkbox") {
      const name = el.getAttribute("name");
      if (!name) return [];
      return Array.from(document.querySelectorAll(`input[name="${cssEscape(name)}"]`))
        .map(input => labelFor(input))
        .filter(Boolean);
    }

    return [];
  }

  const elements = Array.from(document.querySelectorAll("input, textarea, select"));
  const visible = elements.filter(el => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const type = (el.getAttribute("type") || "").toLowerCase();

    if (type === "hidden") return false;
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (rect.width === 0 && rect.height === 0) return false;

    return true;
  });

  return visible.map(el => {
    const tag = el.tagName.toLowerCase();
    const inputType = (el.getAttribute("type") || "").toLowerCase();
    const type = tag === "input" ? (inputType || "text") : tag;

    return {
      label: labelFor(el),
      type,
      required: el.hasAttribute("required") || el.getAttribute("aria-required") === "true",
      placeholder: clean(el.getAttribute("placeholder")),
      name: clean(el.getAttribute("name")),
      id: clean(el.getAttribute("id")),
      options: optionsFor(el)
    };
  });
}
"""

# ── Common browser launch args ────────────────────────────────────────────────
_BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-setuid-sandbox",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL inválida. Debe comenzar con http o https.")
    return url


def _make_session_id(login_url: str, username: str) -> str:
    """Deterministic, opaque session identifier: SHA-256(domain + username)."""
    domain = urlparse(login_url).netloc or login_url
    return hashlib.sha256(f"{domain}:{username}".encode()).hexdigest()[:32]


def _session_path(session_id: str) -> Path:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSIONS_DIR / f"{session_id}.json"


def _normalize_key(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9áéíóúñü]+", "_", value)
    value = value.strip("_")
    return value[:80] or "field"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _is_login_url(url: str) -> bool:
    return any(marker in url.lower() for marker in _LOGIN_PAGE_MARKERS)


# ── Playwright helpers ────────────────────────────────────────────────────────

async def _find_and_fill(page, selectors: list[str], value: str) -> bool:
    """Fill the first visible element matching any selector. Returns True on success."""
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible():
                await el.fill(value)
                return True
        except Exception:
            continue
    return False


async def _click_submit(page) -> None:
    """Click the first visible submit control, or press Enter as fallback."""
    for selector in _SUBMIT_SELECTORS:
        try:
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible():
                await el.click()
                return
        except Exception:
            continue
    await page.keyboard.press("Enter")


async def _navigate(page, url: str) -> None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
    except PlaywrightTimeoutError:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)


# ── Core login logic ──────────────────────────────────────────────────────────

async def _perform_login(
    login_url: str,
    target_url: str,
    username: str,
    password: str,
    session_id: str,
) -> dict:
    """
    Playwright login flow.
    password is accepted as a parameter but NEVER stored, logged, or returned.
    """
    session_file = _session_path(session_id)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=_BROWSER_ARGS)
        try:
            ctx_kwargs: dict = {"user_agent": _USER_AGENT}
            if session_file.exists():
                ctx_kwargs["storage_state"] = str(session_file)

            context = await browser.new_context(**ctx_kwargs)
            page = await context.new_page()

            # Reuse existing session: verify it can access target_url without redirecting to login.
            if session_file.exists():
                try:
                    await _navigate(page, target_url)
                    if not _is_login_url(page.url):
                        return {"status": "LOGIN_OK", "session_id": session_id}
                except Exception:
                    pass

            # Navigate to the login page.
            await _navigate(page, login_url)
            await page.wait_for_timeout(1500)

            if await detect_captcha(page):
                token = await get_captcha_provider().solve(page)
                if token is None:
                    return {"status": "CAPTCHA_REQUIRED", "session_id": None}
                await page.wait_for_timeout(2000)

            # Fill credentials.  Password is passed directly and never stored.
            if not await _find_and_fill(page, _USERNAME_SELECTORS, username):
                return {
                    "status": "LOGIN_FAILED",
                    "session_id": None,
                    "message": "Campo de usuario no encontrado",
                }

            if not await _find_and_fill(page, _PASSWORD_SELECTORS, password):
                return {
                    "status": "LOGIN_FAILED",
                    "session_id": None,
                    "message": "Campo de contraseña no encontrado",
                }

            if await detect_captcha(page):
                token = await get_captcha_provider().solve(page)
                if token is None:
                    return {"status": "CAPTCHA_REQUIRED", "session_id": None}
                await page.wait_for_timeout(1500)

            # Submit form and wait for navigation.
            pre_url = page.url
            await _click_submit(page)
            try:
                await page.wait_for_url(lambda u: u != pre_url, timeout=10000)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(2000)

            if await detect_captcha(page):
                token = await get_captcha_provider().solve(page)
                if token is None:
                    return {"status": "CAPTCHA_REQUIRED", "session_id": None}
                await page.wait_for_timeout(3000)

            # Detect login failure from page content.
            try:
                page_text = (await page.locator("body").inner_text(timeout=5000)).lower()
                if any(marker in page_text for marker in _LOGIN_ERROR_MARKERS):
                    return {
                        "status": "LOGIN_FAILED",
                        "session_id": None,
                        "message": "Credenciales incorrectas",
                    }
            except Exception:
                pass

            # Persist browser state (cookies + localStorage).  No credentials here.
            await context.storage_state(path=str(session_file))

            return {"status": "LOGIN_OK", "session_id": session_id}

        finally:
            await browser.close()


# ── Core form extraction logic ────────────────────────────────────────────────

async def _perform_extract(target_url: str, session_id: Optional[str]) -> dict:
    session_file = _session_path(session_id) if session_id else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=_BROWSER_ARGS)
        try:
            ctx_kwargs: dict = {"user_agent": _USER_AGENT}
            if session_file and session_file.exists():
                ctx_kwargs["storage_state"] = str(session_file)

            context = await browser.new_context(**ctx_kwargs)
            page = await context.new_page()

            await _navigate(page, target_url)
            await page.wait_for_timeout(2000)

            raw_fields: list[dict] = await page.evaluate(_FORM_EXTRACTION_JS)

        finally:
            await browser.close()

    # Normalize extracted fields.
    normalized: list[dict] = []
    seen_keys: set[str] = set()

    for field in raw_fields:
        label = _clean(field.get("label")) or _clean(field.get("name")) or "Campo sin nombre"
        key_base = _normalize_key(label)
        key = key_base
        counter = 2
        while key in seen_keys:
            key = f"{key_base}_{counter}"
            counter += 1
        seen_keys.add(key)

        normalized.append(
            {
                "label": label,
                "id": field.get("id") or None,
                "name": field.get("name") or None,
                "type": field.get("type") or "text",
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder") or None,
                "options": field.get("options") or [],
            }
        )

    return {"url": target_url, "fields": normalized}


# ── Windows ProactorEventLoop wrappers (mirrors festival_scraper_service.py) ──

def _login_with_proactor(
    login_url: str, target_url: str, username: str, password: str, session_id: str
) -> dict:
    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(
            _perform_login(login_url, target_url, username, password, session_id)
        )
    finally:
        loop.close()


def _extract_with_proactor(target_url: str, session_id: Optional[str]) -> dict:
    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(_perform_extract(target_url, session_id))
    finally:
        loop.close()


# ── Public API ────────────────────────────────────────────────────────────────

async def login_and_save_session(
    login_url: str,
    target_url: str,
    username: str,
    password: str,
) -> dict:
    """
    Log in to login_url with the given credentials, save the browser session,
    and return {status, session_id}.

    status values:
      LOGIN_OK          — login succeeded; session_id is set.
      CAPTCHA_REQUIRED  — a captcha was detected; manual intervention needed.
      LOGIN_FAILED      — credentials were rejected or form fields not found.

    The password is NEVER stored, logged, or included in the return value.
    """
    _safe_url(login_url)
    _safe_url(target_url)
    session_id = _make_session_id(login_url, username)

    running_loop = asyncio.get_running_loop()
    if (
        sys.platform.startswith("win")
        and isinstance(running_loop, asyncio.SelectorEventLoop)
    ):
        return await asyncio.to_thread(
            _login_with_proactor, login_url, target_url, username, password, session_id
        )

    return await _perform_login(login_url, target_url, username, password, session_id)


async def extract_form_from_url(
    target_url: str,
    session_id: Optional[str] = None,
) -> dict:
    """
    Navigate to target_url (loading saved session if session_id is provided)
    and extract all visible form fields.

    Returns {url, fields} where each field has:
      label, id, name, type, required, placeholder, options.
    """
    _safe_url(target_url)

    running_loop = asyncio.get_running_loop()
    if (
        sys.platform.startswith("win")
        and isinstance(running_loop, asyncio.SelectorEventLoop)
    ):
        return await asyncio.to_thread(_extract_with_proactor, target_url, session_id)

    return await _perform_extract(target_url, session_id)
