"""
selenium_captcha_solver.py
==========================
Script unificado de 3 capas para evadir y resolver CAPTCHAs sin APIs de pago.

Instalación (una vez):
    pip install selenium selenium-stealth easyocr webdriver-manager

Uso mínimo:
    solver = CaptchaSolver("https://example.com/login")
    solver.run()

    # O con todas las opciones:
    solver = CaptchaSolver(
        target_url="https://example.com/login",
        headless=False,          # False = ver el navegador (recomendado para depurar)
        buster_crx="extensiones/buster.crx",
    )
    result = solver.run()
    print(result)  # {"status": "solved" | "captcha_required" | "no_captcha"}
"""

import logging
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth

try:
    from webdriver_manager.chrome import ChromeDriverManager
    _WDM_AVAILABLE = True
except ImportError:
    _WDM_AVAILABLE = False

try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("captcha_solver")

# ── Selectores detectables de reCAPTCHA ──────────────────────────────────────
# Cambia estos selectores si el sitio objetivo usa variantes personalizadas.

_RECAPTCHA_CHECKBOX_IFRAME = (
    "iframe[title='reCAPTCHA'], "
    "iframe[src*='recaptcha/api2/anchor'], "
    "iframe[src*='recaptcha/enterprise/anchor']"
)

_RECAPTCHA_CHALLENGE_IFRAME = (
    "iframe[title*='recaptcha challenge'], "
    "iframe[src*='recaptcha/api2/bframe'], "
    "iframe[src*='recaptcha/enterprise/bframe']"
)

# ── Selectores del CAPTCHA de imagen tradicional ──────────────────────────────
# !! AJUSTA ESTOS SELECTORES según tu página objetivo !!

# ID o selector del <img> que contiene el CAPTCHA de imagen.
# Ejemplos comunes: "#captcha_img", ".captcha-image", "img[alt*='captcha']"
_IMAGE_CAPTCHA_IMG_SELECTOR = "#captcha_img"          # <-- CAMBIA AQUÍ

# ID o selector del <input> donde se escribe la solución del CAPTCHA.
# Ejemplos comunes: "#captcha_input", "input[name='captcha']", "#captcha"
_IMAGE_CAPTCHA_INPUT_SELECTOR = "#captcha_input"      # <-- CAMBIA AQUÍ

# Archivo temporal donde se guarda la captura del CAPTCHA para que EasyOCR lo procese.
_CAPTCHA_TEMP_IMAGE = "captcha_temporal.png"

# Ruta a la extensión Buster (relativa al directorio de trabajo).
_DEFAULT_BUSTER_PATH = "extensiones/buster.crx"

# ── Selectores del formulario de login ────────────────────────────────────────
# !! AJUSTA ESTOS SELECTORES según tu página objetivo !!
# Se prueban en orden; se usa el primero que esté visible.

# Campo de email / usuario
# Ejemplos: "input[name='email']", "#usuario", "input[name='login']"
_LOGIN_EMAIL_SELECTORS = [
    "input[type='email']",
    "input[name*='email' i]",
    "input[name*='usuario' i]",
    "input[name*='user' i]",
    "input[id*='email' i]",
    "input[id*='user' i]",
]

# Campo de contraseña
# Ejemplos: "input[name='clave']", "#password", "input[name='pass']"
_LOGIN_PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[name*='password' i]",
    "input[name*='contraseña' i]",
    "input[id*='password' i]",
]

# Botón o input de submit
# Ejemplos: "#btn-login", "button.submit", "input[value='Ingresar']"
_LOGIN_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button[id*='login' i]",
    "button[id*='submit' i]",
    "button[class*='login' i]",
]

# Fragmentos de URL que indican que seguimos en la pantalla de login.
_LOGIN_URL_MARKERS = ["login", "signin", "sign-in", "auth", "acceso", "ingresar"]


# ═════════════════════════════════════════════════════════════════════════════
# CAPA 1 — EVASIÓN: configuración del driver con selenium-stealth
# ═════════════════════════════════════════════════════════════════════════════

def _build_driver(headless: bool = False, buster_crx: str | None = None) -> webdriver.Chrome:
    """
    Construye el driver de Chrome con parámetros anti-detección.

    selenium-stealth modifica las propiedades del navegador que los sitios
    leen (navigator.webdriver, plugins, lenguajes, etc.) para que parezca
    un usuario humano.  La extensión Buster se carga aquí si existe.
    """
    options = Options()

    # ── Modo headless opcional ────────────────────────────────────────────
    if headless:
        options.add_argument("--headless=new")      # headless moderno de Chrome ≥ 112

    # ── Flags de estabilidad ──────────────────────────────────────────────
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")

    # ── User-Agent humano ─────────────────────────────────────────────────
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # ── CAPA 2: Cargar extensión Buster si existe ─────────────────────────
    # Buster resuelve reCAPTCHA v2 usando el desafío de audio (100% gratuito).
    # Descarga: https://github.com/nicowillis/buster (o desde Chrome Web Store).
    if buster_crx:
        buster_path = Path(buster_crx).resolve()
        if buster_path.exists():
            options.add_extension(str(buster_path))
            log.info("Extensión Buster cargada desde: %s", buster_path)
        else:
            log.warning(
                "Buster no encontrado en '%s'. Se omitirá la resolución de reCAPTCHA. "
                "Descárgalo y colócalo en esa ruta.",
                buster_path,
            )

    # ── Inicializar ChromeDriver ──────────────────────────────────────────
    if _WDM_AVAILABLE:
        # webdriver-manager descarga automáticamente el ChromeDriver correcto.
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        # Si no está webdriver-manager, Selenium ≥ 4.6 lo gestiona solo.
        driver = webdriver.Chrome(options=options)

    # ── CAPA 1: Aplicar selenium-stealth ─────────────────────────────────
    # Estos valores deben coincidir con lo que reportaría un Chrome real en Windows.
    stealth(
        driver,
        languages=["es-ES", "es", "en-US", "en"],  # idiomas del navegador
        vendor="Google Inc.",                        # navigator.vendor
        platform="Win32",                            # navigator.platform
        webgl_vendor="Intel Inc.",                   # WebGL UNMASKED_VENDOR
        renderer="Intel Iris OpenGL Engine",         # WebGL UNMASKED_RENDERER
        fix_hairline=True,                           # corrige artefacto de 1px en headless
        run_on_insecure_origins=False,
    )

    log.info("Driver iniciado con selenium-stealth activo.")
    return driver


# ═════════════════════════════════════════════════════════════════════════════
# CAPA 2 — reCAPTCHA v2: resolución con la extensión Buster
# ═════════════════════════════════════════════════════════════════════════════

def _solve_recaptcha_v2(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """
    Detecta y resuelve reCAPTCHA v2 usando Buster.

    Flujo:
      1. Detecta el iframe del checkbox ("No soy un robot").
      2. Hace clic en el checkbox para activar el desafío.
      3. Cambia al iframe del desafío visual.
      4. Hace clic en el botón de Buster (.buster-button) que inicia el
         desafío de audio y lo resuelve automáticamente.

    Devuelve True si se resolvió correctamente, False si no hay reCAPTCHA.
    """
    # ── Detectar iframe del checkbox ──────────────────────────────────────
    try:
        checkbox_iframe = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _RECAPTCHA_CHECKBOX_IFRAME))
        )
    except Exception:
        log.debug("No se detectó iframe de reCAPTCHA v2.")
        return False

    log.info("reCAPTCHA v2 detectado. Iniciando resolución con Buster...")

    # ── Paso 1: Hacer clic en "No soy un robot" ───────────────────────────
    driver.switch_to.frame(checkbox_iframe)
    try:
        # !! Si el checkbox tiene un selector diferente en tu página, cámbialo aquí !!
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor")))
        checkbox.click()
        log.info("Checkbox reCAPTCHA clickeado.")
    except Exception as exc:
        log.error("No se pudo clickear el checkbox: %s", exc)
        driver.switch_to.default_content()
        return False

    # ── Volver al contenido principal ─────────────────────────────────────
    driver.switch_to.default_content()
    time.sleep(2)  # Dar tiempo a que aparezca el iframe del desafío

    # ── Paso 2: Cambiar al iframe del desafío visual ──────────────────────
    try:
        challenge_iframe = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _RECAPTCHA_CHALLENGE_IFRAME))
        )
        driver.switch_to.frame(challenge_iframe)
        log.info("Dentro del iframe del desafío reCAPTCHA.")
    except Exception as exc:
        log.warning(
            "No apareció el iframe del desafío (puede que el checkbox ya haya resuelto): %s", exc
        )
        driver.switch_to.default_content()
        return True  # El checkbox se marcó sin desafío adicional

    # ── Paso 3: Hacer clic en el botón de Buster ─────────────────────────
    # Buster inyecta un botón en el iframe del desafío.
    # !! Si usas una versión diferente de Buster, verifica el selector exacto
    #    inspeccionando el DOM del iframe (F12 → iframe → .buster-button) !!
    try:
        buster_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".buster-button"))
        )
        buster_btn.click()
        log.info("Botón Buster clickeado. Esperando resolución por audio...")
        time.sleep(8)  # Buster necesita ~5-8 s para procesar el audio
    except Exception as exc:
        log.error(
            "No se encontró .buster-button. Verifica que la extensión esté cargada "
            "y que el selector sea correcto: %s", exc
        )
        driver.switch_to.default_content()
        return False

    # ── Volver al contexto principal ──────────────────────────────────────
    driver.switch_to.default_content()

    # Verificar que el reCAPTCHA quedó marcado como resuelto.
    try:
        driver.switch_to.frame(checkbox_iframe)
        resolved = driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox-checked")
        driver.switch_to.default_content()
        if resolved:
            log.info("reCAPTCHA v2 resuelto correctamente.")
            return True
    except Exception:
        driver.switch_to.default_content()

    log.warning("No se pudo confirmar la resolución del reCAPTCHA.")
    return False


# ═════════════════════════════════════════════════════════════════════════════
# CAPA 3 — CAPTCHA de imagen: OCR local con EasyOCR
# ═════════════════════════════════════════════════════════════════════════════

def _solve_image_captcha(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """
    Detecta y resuelve un CAPTCHA de imagen (texto/números distorsionados)
    usando EasyOCR (procesamiento 100% local, sin API externa).

    Flujo:
      1. Localiza la imagen del CAPTCHA mediante _IMAGE_CAPTCHA_IMG_SELECTOR.
      2. Toma una captura de pantalla del elemento.
      3. EasyOCR analiza la imagen y extrae el texto.
      4. Escribe el texto en el input del formulario.
      5. Elimina la imagen temporal.

    Devuelve True si se procesó correctamente, False si no se encontró CAPTCHA.
    """
    if not _EASYOCR_AVAILABLE:
        log.error("EasyOCR no está instalado. Ejecuta: pip install easyocr")
        return False

    # ── Detectar imagen del CAPTCHA ───────────────────────────────────────
    # !! Cambia _IMAGE_CAPTCHA_IMG_SELECTOR arriba si tu página usa otro selector !!
    try:
        captcha_img = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _IMAGE_CAPTCHA_IMG_SELECTOR))
        )
    except Exception:
        log.debug("No se encontró imagen de CAPTCHA tradicional.")
        return False

    log.info("CAPTCHA de imagen detectado. Procesando con EasyOCR...")

    # ── Captura de pantalla del elemento ─────────────────────────────────
    # Se guarda como archivo temporal para que EasyOCR lo lea.
    try:
        captcha_img.screenshot(_CAPTCHA_TEMP_IMAGE)
        log.info("Captura guardada en '%s'.", _CAPTCHA_TEMP_IMAGE)
    except Exception as exc:
        log.error("Error al capturar la imagen del CAPTCHA: %s", exc)
        return False

    # ── OCR con EasyOCR ───────────────────────────────────────────────────
    # Se inicializa con español e inglés; ajusta los idiomas según tu caso.
    # La primera vez descargará los modelos (~200 MB) si no están en caché.
    # !! Si el CAPTCHA está en otro idioma, agrega el código aquí: ['fr', 'de', ...] !!
    try:
        reader = easyocr.Reader(["es", "en"], gpu=False)
        results = reader.readtext(_CAPTCHA_TEMP_IMAGE, detail=0, paragraph=True)
        captcha_text = "".join(results).strip().replace(" ", "")
        log.info("Texto detectado por OCR: '%s'", captcha_text)
    except Exception as exc:
        log.error("EasyOCR falló al procesar la imagen: %s", exc)
        return False
    finally:
        # Siempre eliminar la imagen temporal.
        if os.path.exists(_CAPTCHA_TEMP_IMAGE):
            os.remove(_CAPTCHA_TEMP_IMAGE)
            log.debug("Imagen temporal eliminada.")

    if not captcha_text:
        log.warning("OCR no extrajo texto. La imagen puede ser demasiado borrosa.")
        return False

    # ── Escribir solución en el formulario ────────────────────────────────
    # !! Cambia _IMAGE_CAPTCHA_INPUT_SELECTOR arriba si tu página usa otro selector !!
    try:
        captcha_input = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, _IMAGE_CAPTCHA_INPUT_SELECTOR))
        )
        captcha_input.clear()
        captcha_input.send_keys(captcha_text)
        log.info("Solución '%s' escrita en el input del CAPTCHA.", captcha_text)
        return True
    except Exception as exc:
        log.error(
            "No se encontró el input del CAPTCHA (%s): %s",
            _IMAGE_CAPTCHA_INPUT_SELECTOR, exc,
        )
        return False


# ═════════════════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS — usadas por apply_to_festival()
# ═════════════════════════════════════════════════════════════════════════════

def _detect_captcha_type(driver: webdriver.Chrome, timeout: int = 10) -> str | None:
    """
    Detecta qué tipo de CAPTCHA está visible.

    Usa un único WebDriverWait para ambos tipos (reCAPTCHA e imagen) de modo
    que el tiempo de espera máximo sea `timeout` segundos en total, no por tipo.
    Retorna 'recaptcha', 'image' o None. Nunca lanza excepción.

    El orden de discriminación importa: reCAPTCHA se comprueba primero porque
    Buster puede resolverlo de forma autónoma; el CAPTCHA imagen requiere OCR.
    """
    # Selector combinado: detecta cualquiera de los dos con una sola espera.
    combined = f"{_RECAPTCHA_CHECKBOX_IFRAME}, {_IMAGE_CAPTCHA_IMG_SELECTOR}"
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, combined))
        )
    except Exception:
        log.debug("No se detectó CAPTCHA en %ds.", timeout)
        return None

    # Ya hay algo presente — discriminar sin esperar (find_elements no lanza).
    if driver.find_elements(By.CSS_SELECTOR, _RECAPTCHA_CHECKBOX_IFRAME):
        log.info("CAPTCHA detectado: reCAPTCHA v2")
        return "recaptcha"
    log.info("CAPTCHA detectado: imagen tradicional")
    return "image"


def _find_first_visible(driver: webdriver.Chrome, selectors: list) -> object | None:
    """
    Devuelve el primer elemento visible que coincida con alguno de los selectores.
    No usa WebDriverWait — espera que el DOM ya esté cargado.
    !! Ajusta _LOGIN_*_SELECTORS si los campos de tu formulario no son detectados !!
    """
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None


def _find_first_clickable(driver: webdriver.Chrome, selectors: list) -> object | None:
    """Devuelve el primer botón/input clickeable que coincida con algún selector."""
    for sel in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def _is_login_form_gone(driver: webdriver.Chrome) -> bool:
    """
    Devuelve True si ya no hay ningún campo de contraseña visible.
    Señal de que el formulario de login desapareció tras un login exitoso.
    """
    for sel in _LOGIN_PASSWORD_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                return False  # sigue visible → login no terminó
        except Exception:
            continue
    return True  # ningún campo de contraseña visible → formulario desapareció


def _do_login_attempt(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    email: str,
    password: str,  # NEVER logged
) -> dict:
    """
    Ejecuta un intento de login completo sobre la página YA cargada en `driver`.
    No navega (el caller debe hacer driver.get(url) antes de llamar esta función).

    Pasos:
      1. Llenar email y contraseña.
      2. Detectar y resolver CAPTCHA pre-submit (10 s de espera, no rompe).
      3. Submit (clic en botón o fallback Enter).
      4. Detectar y resolver CAPTCHA post-submit (10 s de espera, no rompe).
      5. Confirmar login: URL cambió O formulario de login desapareció.

    Retorna dict con claves: status, message, final_url.
    """
    initial_url = driver.current_url

    # ── PASO 0: Manejar social-login (ej. FilmFreeway muestra "Continue with
    #    Google / Apple / Email" antes de mostrar el formulario tradicional).
    #    Si no hay campo de email visible, busca un botón "continue/sign in with email"
    #    y haz click para revelar el formulario clásico.
    if not _find_first_visible(driver, _LOGIN_EMAIL_SELECTORS):
        _CONTINUE_EMAIL_TEXTS = [
            "continue with email", "sign in with email", "log in with email",
            "login with email", "use email", "email", "continue",
        ]
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']")
            for el in candidates:
                try:
                    text = (el.text or "").lower().strip()
                    if any(kw in text for kw in _CONTINUE_EMAIL_TEXTS) and el.is_displayed():
                        el.click()
                        time.sleep(2)
                        break
                except Exception:
                    continue
        except Exception:
            pass

    # ── PASO 1: Llenar email ──────────────────────────────────────────────
    # !! Si el campo no se detecta, ajusta _LOGIN_EMAIL_SELECTORS arriba !!
    email_field = _find_first_visible(driver, _LOGIN_EMAIL_SELECTORS)
    if not email_field:
        return {
            "status": "LOGIN_FAILED",
            "message": "Campo de email/usuario no encontrado. Ajusta _LOGIN_EMAIL_SELECTORS.",
            "final_url": driver.current_url,
        }
    email_field.clear()
    email_field.send_keys(email)
    log.info("Email ingresado.")

    # ── PASO 2: Llenar contraseña ─────────────────────────────────────────
    # !! Si el campo no se detecta, ajusta _LOGIN_PASSWORD_SELECTORS arriba !!
    password_field = _find_first_visible(driver, _LOGIN_PASSWORD_SELECTORS)
    if not password_field:
        return {
            "status": "LOGIN_FAILED",
            "message": "Campo de contraseña no encontrado. Ajusta _LOGIN_PASSWORD_SELECTORS.",
            "final_url": driver.current_url,
        }
    password_field.clear()
    password_field.send_keys(password)
    log.info("Contraseña ingresada.")

    # ── PASO 3: Detectar y resolver CAPTCHA PRE-submit ────────────────────
    # WebDriverWait interno de 10 s: no lanza excepción si no hay CAPTCHA.
    pre_type = _detect_captcha_type(driver, timeout=10)

    if pre_type == "recaptcha":
        log.info("reCAPTCHA v2 detectado antes del submit. Resolviendo con Buster...")
        if not _solve_recaptcha_v2(driver, wait):
            return {
                "status": "CAPTCHA_REQUIRED",
                "message": "No se pudo resolver el reCAPTCHA v2 (pre-submit).",
                "final_url": driver.current_url,
            }

    elif pre_type == "image":
        log.info("CAPTCHA imagen detectado antes del submit. Resolviendo con EasyOCR...")
        if not _solve_image_captcha(driver, wait):
            return {
                "status": "CAPTCHA_REQUIRED",
                "message": "No se pudo resolver el CAPTCHA imagen (pre-submit).",
                "final_url": driver.current_url,
            }

    # ── PASO 4: Submit ────────────────────────────────────────────────────
    # !! Si el botón no se detecta, ajusta _LOGIN_SUBMIT_SELECTORS arriba !!
    submit_btn = _find_first_clickable(driver, _LOGIN_SUBMIT_SELECTORS)
    if submit_btn:
        submit_btn.click()
        log.info("Botón submit clickeado.")
    else:
        # Fallback: Enter en el campo de contraseña si no hay botón visible.
        password_field.send_keys(Keys.RETURN)
        log.info("Submit por Enter (botón no encontrado).")

    time.sleep(2)  # Pausa para que el servidor responda

    # ── PASO 5: Detectar y resolver CAPTCHA POST-submit ───────────────────
    # Algunos sitios muestran el CAPTCHA sólo después del primer intento.
    post_type = _detect_captcha_type(driver, timeout=10)

    if post_type == "recaptcha":
        log.info("reCAPTCHA v2 detectado después del submit. Resolviendo con Buster...")
        if not _solve_recaptcha_v2(driver, wait):
            return {
                "status": "CAPTCHA_REQUIRED",
                "message": "No se pudo resolver el reCAPTCHA v2 (post-submit).",
                "final_url": driver.current_url,
            }

    elif post_type == "image":
        log.info("CAPTCHA imagen detectado después del submit. Resolviendo con EasyOCR...")
        if not _solve_image_captcha(driver, wait):
            return {
                "status": "CAPTCHA_REQUIRED",
                "message": "No se pudo resolver el CAPTCHA imagen (post-submit).",
                "final_url": driver.current_url,
            }

    if post_type:
        time.sleep(2)  # Esperar navegación tras resolución post-submit

    # ── PASO 6: Confirmar login exitoso ───────────────────────────────────
    final_url = driver.current_url

    # Criterio A: la URL cambió y ya no apunta a la pantalla de login.
    url_changed = (
        final_url != initial_url
        and not any(m in final_url.lower() for m in _LOGIN_URL_MARKERS)
    )

    # Criterio B: el formulario de login ya no está visible.
    form_gone = _is_login_form_gone(driver)

    if url_changed or form_gone:
        log.info("Login exitoso. URL final: %s", final_url)
        return {"status": "LOGIN_OK", "message": "Login completado con éxito.", "final_url": final_url}

    log.warning("Login no confirmado. URL final: %s", final_url)
    return {
        "status": "LOGIN_FAILED",
        "message": "Credenciales rechazadas o formulario de login persistente.",
        "final_url": final_url,
    }


# ═════════════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL — CaptchaSolver
# ═════════════════════════════════════════════════════════════════════════════

class CaptchaSolver:
    """
    Resolvedor unificado de CAPTCHAs con 3 capas de acción.

    Parámetros
    ----------
    target_url : str
        URL de la página que contiene el CAPTCHA.
    headless : bool
        True = navegador invisible. False (default) = visible (mejor para depurar).
    buster_crx : str
        Ruta al archivo .crx de la extensión Buster (default: 'extensiones/buster.crx').
    wait_timeout : int
        Segundos de espera máxima para cada elemento (default: 15).
    """

    def __init__(
        self,
        target_url: str,
        headless: bool = False,
        buster_crx: str = _DEFAULT_BUSTER_PATH,
        wait_timeout: int = 15,
    ):
        self.target_url = target_url
        self.headless = headless
        self.buster_crx = buster_crx
        self.wait_timeout = wait_timeout

    def run(self) -> dict:
        """
        Navega a target_url y aplica las 3 capas de resolución de CAPTCHA.

        Retorna
        -------
        dict con claves:
          status  : "solved" | "captcha_required" | "no_captcha" | "error"
          message : descripción del resultado
        """
        driver: webdriver.Chrome | None = None

        try:
            # ── Inicializar driver (Capa 1: evasión activa) ───────────────
            driver = _build_driver(headless=self.headless, buster_crx=self.buster_crx)
            wait = WebDriverWait(driver, self.wait_timeout)

            log.info("Navegando a: %s", self.target_url)
            driver.get(self.target_url)
            time.sleep(2)  # Pausa humana para que la página cargue completamente

            # ── Capa 2: intentar resolver reCAPTCHA v2 ────────────────────
            recaptcha_solved = _solve_recaptcha_v2(driver, wait)

            # ── Capa 3: intentar resolver CAPTCHA de imagen ───────────────
            image_solved = _solve_image_captcha(driver, wait)

            # ── Evaluar resultado ─────────────────────────────────────────
            if recaptcha_solved or image_solved:
                return {"status": "solved", "message": "CAPTCHA resuelto correctamente."}

            # Ninguna capa encontró CAPTCHA: la página puede estar limpia.
            log.info("No se detectó CAPTCHA en la página.")
            return {"status": "no_captcha", "message": "No se detectó CAPTCHA."}

        except Exception as exc:
            log.exception("Error inesperado durante la resolución: %s", exc)
            return {"status": "error", "message": str(exc)}

        finally:
            # Siempre cerrar el navegador, incluso si hubo excepción.
            if driver:
                log.info("Cerrando navegador.")
                driver.quit()

    def apply_to_festival(
        self,
        email: str,
        password: str,
        login_url: str | None = None,
        max_retries: int = 2,
    ) -> dict:
        """
        Flujo completo de login con reintentos automáticos.

        Por cada intento: navega a la URL, llena credenciales, resuelve CAPTCHAs
        pre- y post-submit, confirma login.  Si el resultado es CAPTCHA_REQUIRED
        o LOGIN_FAILED relacionado con CAPTCHA, refresca la página y reintenta
        hasta `max_retries` veces adicionales (total max_retries + 1 intentos).

        La lógica de cada intento está en _do_login_attempt() — apply_to_festival()
        solo gestiona el driver y el bucle de reintentos.

        Parámetros
        ----------
        email       : usuario o email (nunca logueado).
        password    : contraseña (nunca logueada ni persistida).
        login_url   : URL del formulario; si es None usa self.target_url.
        max_retries : reintentos adicionales tras el primer intento (default 2).

        Retorna
        -------
        dict con claves:
          status    : "LOGIN_OK" | "LOGIN_FAILED" | "CAPTCHA_REQUIRED" | "error"
          message   : descripción legible del resultado
          final_url : URL en la que terminó el navegador
        """
        url = login_url or self.target_url
        driver: webdriver.Chrome | None = None
        last_result: dict = {
            "status": "error",
            "message": "No se ejecutó ningún intento.",
            "final_url": "",
        }

        try:
            # Crear el driver UNA SOLA VEZ y reutilizarlo en todos los reintentos.
            driver = _build_driver(headless=self.headless, buster_crx=self.buster_crx)
            wait = WebDriverWait(driver, self.wait_timeout)

            for attempt in range(max_retries + 1):
                if attempt == 0:
                    log.info("Intento 1/%d — navegando a: %s", max_retries + 1, url)
                else:
                    log.info(
                        "Reintento %d/%d — refrescando página: %s",
                        attempt, max_retries, url,
                    )

                # Navegar (o refrescar) antes de cada intento.
                driver.get(url)
                time.sleep(2)

                # Delegar la lógica del intento al helper modular.
                last_result = _do_login_attempt(driver, wait, email, password)

                if last_result["status"] == "LOGIN_OK":
                    return last_result

                # Decidir si vale la pena reintentar.
                msg_lower = last_result.get("message", "").lower()
                is_retriable = last_result["status"] == "CAPTCHA_REQUIRED" or (
                    last_result["status"] == "LOGIN_FAILED"
                    and "captcha" in msg_lower
                )

                if not is_retriable:
                    log.info(
                        "Resultado '%s' no reintentable. Abortando.",
                        last_result["status"],
                    )
                    break

                if attempt < max_retries:
                    log.info(
                        "Intento %d fallido (%s). Reintentando (%d restante/s)...",
                        attempt + 1,
                        last_result["status"],
                        max_retries - attempt,
                    )
                else:
                    log.warning(
                        "Se agotaron los %d reintentos. Último estado: %s",
                        max_retries,
                        last_result["status"],
                    )

            return last_result

        except Exception as exc:
            log.exception("Error inesperado en apply_to_festival: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "final_url": driver.current_url if driver else "",
            }

        finally:
            if driver:
                log.info("Cerrando navegador.")
                driver.quit()


# ═════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA — ejecución directa del script
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # !! Reemplaza estos valores por los de tu sitio objetivo !!
    TARGET_URL = "https://example.com/login"   # <-- CAMBIA AQUÍ
    EMAIL      = "tu@email.com"                # <-- CAMBIA AQUÍ
    PASSWORD   = "tu_contraseña"               # <-- CAMBIA AQUÍ

    solver = CaptchaSolver(
        target_url=TARGET_URL,
        headless=False,           # False = ver el navegador mientras trabaja
        buster_crx=_DEFAULT_BUSTER_PATH,
        wait_timeout=20,
    )

    result = solver.apply_to_festival(email=EMAIL, password=PASSWORD)

    print("\n── Resultado final ──────────────────────────────")
    print(f"  Estado    : {result['status']}")
    print(f"  Mensaje   : {result['message']}")
    print(f"  URL final : {result['final_url']}")
    print("─────────────────────────────────────────────────\n")
