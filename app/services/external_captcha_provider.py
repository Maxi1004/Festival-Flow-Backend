"""
External Captcha Provider — SolveCaptcha.com
============================================
Implementación completa usando el SDK oficial de Python de SolveCaptcha.

Variables de entorno requeridas (.env):
  CAPTCHA_PROVIDER=external
  CAPTCHA_API_KEY=<tu API key de solvecaptcha.com>
  CAPTCHA_TIMEOUT_SECONDS=120   (opcional, default 120)

Flujo:
  1. detect_captcha(page) → True
  2. ExternalCaptchaProvider.solve(page)  →  este módulo
  3. extract_site_key      — lee [data-sitekey] del DOM
  4. _detect_captcha_type  — reCAPTCHA vs hCaptcha
  5. _solve_sync           — llama al SDK (bloqueante, corre en thread)
  6. inject_solution       — inyecta el token y dispara el callback
"""

import asyncio
import os
from typing import Optional

from solvecaptcha import Solvecaptcha


def _get_solver() -> Solvecaptcha:
    """Lazy init: lee las vars de entorno en el momento de la llamada."""
    api_key = os.getenv("CAPTCHA_API_KEY", "")
    timeout = int(os.getenv("CAPTCHA_TIMEOUT_SECONDS", "120"))
    return Solvecaptcha(api_key, defaultTimeout=timeout)


# ── Paso 1: extraer site key ──────────────────────────────────────────────────

async def extract_site_key(page) -> Optional[str]:
    """Lee el atributo data-sitekey del DOM."""
    return await page.evaluate(
        "() => document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey') ?? null"
    )


# ── Paso 2: detectar tipo de captcha ─────────────────────────────────────────

async def _detect_captcha_type(page) -> str:
    """Devuelve 'hcaptcha' si detecta hCaptcha, si no 'recaptcha'."""
    try:
        count = await page.locator(".h-captcha, iframe[src*='hcaptcha']").count()
        if count > 0:
            return "hcaptcha"
    except Exception:
        pass
    return "recaptcha"


# ── Paso 3: llamar al SDK (síncrono → corre en thread) ───────────────────────

def _solve_sync(key: str, url: str, captcha_type: str) -> Optional[str]:
    """Llama al SDK de SolveCaptcha de forma bloqueante. Se llama vía asyncio.to_thread."""
    try:
        solver = _get_solver()
        if captcha_type == "hcaptcha":
            result = solver.hcaptcha(sitekey=key, url=url)
        else:
            result = solver.recaptcha(sitekey=key, url=url)
        return result.get("code") if isinstance(result, dict) else str(result)
    except Exception:
        return None


# ── Paso 4: inyectar el token en el DOM ──────────────────────────────────────

async def inject_solution(page, token: str) -> None:
    """
    Inyecta el token en los campos ocultos de reCAPTCHA/hCaptcha
    y dispara el callback para que el sitio procese la solución.
    """
    safe_token = token.replace("'", "\\'")
    await page.evaluate(f"""
        (() => {{
            // reCAPTCHA v2
            const rc = document.getElementById('g-recaptcha-response');
            if (rc) rc.innerHTML = '{safe_token}';

            if (window.___grecaptcha_cfg) {{
                try {{
                    const client = Object.values(window.___grecaptcha_cfg.clients)[0];
                    const fn = client && Object.values(client).find(
                        x => x && typeof x.callback === 'function'
                    );
                    if (fn) fn.callback('{safe_token}');
                }} catch (_) {{}}
            }}

            // hCaptcha
            const hc = document.querySelector('[name="h-captcha-response"]');
            if (hc) hc.innerHTML = '{safe_token}';
        }})()
    """)


# ── Entry point (llamado por ExternalCaptchaProvider) ────────────────────────

async def solve(page, site_key: Optional[str] = None) -> Optional[str]:
    """
    Flujo completo: extrae key → detecta tipo → llama API → inyecta token.
    Devuelve el token string en éxito, None si falla (el caller retorna CAPTCHA_REQUIRED).
    """
    try:
        key = site_key or await extract_site_key(page)
        if not key:
            return None

        page_url = page.url
        captcha_type = await _detect_captcha_type(page)

        # El SDK es síncrono; lo corremos en un thread para no bloquear el event loop.
        token = await asyncio.to_thread(_solve_sync, key, page_url, captcha_type)
        if not token:
            return None

        await inject_solution(page, token)
        return token

    except Exception:
        return None
