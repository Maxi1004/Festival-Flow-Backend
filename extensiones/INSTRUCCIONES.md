# Carpeta de extensiones Chrome

## buster.crx — extensión requerida para la Capa 2 (reCAPTCHA v2)

### Qué es Buster
Buster es una extensión gratuita y de código abierto que resuelve reCAPTCHA v2
activando el desafío de audio y transcribiéndolo automáticamente, sin ninguna API de pago.

### Cómo obtener el archivo buster.crx

**Opción A — Desde el repositorio oficial (recomendado):**
1. Ve a https://github.com/nicowillis/buster/releases
2. Descarga el archivo `buster-x.x.x-chrome.zip`
3. Descomprímelo y renombra el resultado a `buster.crx`
4. Copia `buster.crx` en esta carpeta

**Opción B — Empaquetar desde Chrome Web Store:**
1. Instala la extensión desde Chrome Web Store (busca "Buster Captcha Solver")
2. Abre chrome://extensions/  →  activa "Modo desarrollador"
3. Haz clic en los 3 puntos de la extensión  →  "Empaquetar extensión"
4. El archivo .crx resultante cópialo aquí con el nombre `buster.crx`

### Verificación
Una vez colocado el archivo, la ruta debe quedar:
    extensiones/buster.crx

El script lo cargará automáticamente al iniciar Chrome.
