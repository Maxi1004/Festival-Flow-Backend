"""
Captcha detection and provider management.

Providers
---------
  manual   → ManualCaptchaProvider   — always returns None (signals CAPTCHA_REQUIRED to caller).
  external → ExternalCaptchaProvider — stub, see external_captcha_provider.py for integration docs.

Configuration
-------------
  Set CAPTCHA_PROVIDER=external in .env to activate the external provider.
"""

import os
from typing import Optional, Protocol


# ── Detection ────────────────────────────────────────────────────────────────

_CAPTCHA_SELECTORS = [
    ".g-recaptcha",
    ".h-captcha",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "[data-sitekey]",
    "#captcha",
]

_CAPTCHA_TEXT_MARKERS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "i'm not a robot",
    "no soy un robot",
    "verificación humana",
    "human verification",
]


async def detect_captcha(page) -> bool:
    """Return True if any captcha widget is detected on the page."""
    for selector in _CAPTCHA_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            pass

    try:
        text = (await page.locator("body").inner_text(timeout=5000)).lower()
        if any(marker in text for marker in _CAPTCHA_TEXT_MARKERS):
            return True
    except Exception:
        pass

    return False


# ── Provider protocol ─────────────────────────────────────────────────────────

class CaptchaProvider(Protocol):
    async def solve(self, page, site_key: Optional[str] = None) -> Optional[str]:
        """
        Attempt to solve the captcha on `page`.
        Returns the solution token string, or None if it cannot be solved automatically.
        """
        ...


# ── Manual provider ───────────────────────────────────────────────────────────

class ManualCaptchaProvider:
    """
    Documents the CaptchaProvider interface; never solves automatically.
    When this provider is active the caller must return CAPTCHA_REQUIRED
    to the client so a human can intervene.
    """

    async def solve(self, page, site_key: Optional[str] = None) -> Optional[str]:
        # Nothing to do — signal the caller to stop and return CAPTCHA_REQUIRED.
        return None


# ── External provider ─────────────────────────────────────────────────────────

class ExternalCaptchaProvider:
    """
    Delegates to external_captcha_provider.solve().
    See app/services/external_captcha_provider.py for full integration docs.
    """

    async def solve(self, page, site_key: Optional[str] = None) -> Optional[str]:
        from app.services import external_captcha_provider
        return await external_captcha_provider.solve(page, site_key)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_captcha_provider() -> CaptchaProvider:
    """Return the configured captcha provider based on CAPTCHA_PROVIDER env var."""
    name = os.getenv("CAPTCHA_PROVIDER", "manual").strip().lower()
    if name == "external":
        return ExternalCaptchaProvider()
    return ManualCaptchaProvider()
