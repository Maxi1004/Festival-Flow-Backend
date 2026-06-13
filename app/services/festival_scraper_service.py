import asyncio
import re
import sys
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from app.core.firebase import db
from app.core.utils import utc_now_iso


LOGIN_WORDS = [
    "login", "log in", "sign in", "iniciar sesión", "iniciar sesion",
    "crear cuenta", "create account", "register", "registrarse"
]

PAYMENT_WORDS = [
    "payment", "checkout", "pay", "fee", "tasa", "pago",
    "inscripción", "inscripcion", "entry fee"
]

CAPTCHA_WORDS = [
    "captcha", "recaptcha", "hcaptcha", "i'm not a robot", "no soy un robot"
]


def _normalize_key(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9áéíóúñü]+", "_", value)
    value = value.strip("_")
    return value[:80] or "field"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _contains_any(text: str, words: list[str]) -> bool:
    text = text.lower()
    return any(word in text for word in words)


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL inválida. Debe comenzar con http o https.")
    return url


async def _scrape_form_from_url(url: str) -> dict:
    url = _safe_url(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
            ],
        )
        try:
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )

            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

            await page.wait_for_timeout(2000)

            page_text = await page.locator("body").inner_text(timeout=10000)
            page_text_lower = page_text.lower()

            requires_login = _contains_any(page_text_lower, LOGIN_WORDS)
            requires_payment = _contains_any(page_text_lower, PAYMENT_WORDS)
            requires_captcha = _contains_any(page_text_lower, CAPTCHA_WORDS)

            form_count = await page.locator("form").count()

            fields = await page.evaluate(
                """
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

              function selectorFor(el) {
                const tag = el.tagName.toLowerCase();
                const id = el.getAttribute("id");
                const name = el.getAttribute("name");

                if (id) return `${tag}#${CSS.escape(id)}`;
                if (name) return `${tag}[name="${cssEscape(name)}"]`;

                return tag;
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
                  selector: selectorFor(el),
                  options: optionsFor(el),
                  max_length: el.getAttribute("maxlength") ? Number(el.getAttribute("maxlength")) : null
                };
              });
            }
            """
            )
        finally:
            await browser.close()

    normalized_fields = []
    seen_keys = set()

    for field in fields:
        label = _clean(field.get("label")) or _clean(field.get("name")) or "Campo sin nombre"
        key_base = _normalize_key(label)
        key = key_base
        counter = 2

        while key in seen_keys:
            key = f"{key_base}_{counter}"
            counter += 1

        seen_keys.add(key)

        normalized_fields.append(
            {
                "key": key,
                "label": label,
                "type": field.get("type") or "text",
                "required": bool(field.get("required")),
                "placeholder": field.get("placeholder") or None,
                "name": field.get("name") or None,
                "id": field.get("id") or None,
                "selector": field.get("selector") or None,
                "options": field.get("options") or [],
                "max_length": field.get("max_length"),
                "source": "playwright",
            }
        )

    requires_manual = (
        requires_login
        or requires_payment
        or requires_captcha
        or len(normalized_fields) == 0
    )

    if requires_login:
        status = "REQUIRES_LOGIN"
    elif requires_manual:
        status = "REQUIRES_MANUAL"
    elif len(normalized_fields) == 0:
        status = "NO_FORM_FOUND"
    else:
        status = "SUCCESS"

    return {
        "url": url,
        "status": status,
        "fields": normalized_fields,
        "forms_found": form_count,
        "fields_found": len(normalized_fields),
        "requires_login": requires_login,
        "requires_payment": requires_payment,
        "requires_captcha": requires_captcha,
        "requires_manual": requires_manual,
        "message": None,
        "raw_flags": {
            "login": requires_login,
            "payment": requires_payment,
            "captcha": requires_captcha,
        },
    }


def _scrape_form_with_proactor(url: str) -> dict:
    loop = asyncio.ProactorEventLoop()
    try:
        return loop.run_until_complete(_scrape_form_from_url(url))
    finally:
        loop.close()


async def scrape_form_from_url(url: str) -> dict:
    running_loop = asyncio.get_running_loop()
    if (
        sys.platform.startswith("win")
        and isinstance(running_loop, asyncio.SelectorEventLoop)
    ):
        return await asyncio.to_thread(_scrape_form_with_proactor, url)

    return await _scrape_form_from_url(url)


async def scrape_and_save_festival_form(festival_id: str) -> dict:
    doc_ref = db.collection("festivals").document(festival_id)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        raise ValueError("Festival no encontrado.")

    festival = snapshot.to_dict() or {}
    url = festival.get("submission_url") or festival.get("website")

    if not url:
        raise ValueError("El festival no tiene website ni submission_url.")

    result = await scrape_form_from_url(url)

    doc_ref.set(
        {
            "form_fields": result["fields"],
            "scrape_status": result["status"],
            "scrape_summary": {
                "forms_found": result["forms_found"],
                "fields_found": result["fields_found"],
                "requires_login": result["requires_login"],
                "requires_payment": result["requires_payment"],
                "requires_captcha": result["requires_captcha"],
                "requires_manual": result["requires_manual"],
            },
            "requires_login": result["requires_login"],
            "requires_payment": result["requires_payment"],
            "requires_captcha": result["requires_captcha"],
            "requires_manual": result["requires_manual"],
            "last_checked_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
        merge=True,
    )

    return result
