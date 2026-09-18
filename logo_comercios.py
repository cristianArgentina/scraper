import re
import time
import requests
import gspread

from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from urllib.parse import urljoin, urlparse

# ============================================================
# CONFIGURACIÓN
# ============================================================

# Ruta al JSON de la cuenta de servicio de Google
CREDENTIALS_FILE = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"

# ID del Google Sheets donde ya guardás los precios
#
# Ejemplo:
# https://docs.google.com/spreadsheets/d/1ABCDEF123456789/edit
#
# Entonces el ID es:
# 1ABCDEF123456789
#
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"

# Nombre de la nueva hoja
SHEET_NAME = "Logos_Comercios"


# ============================================================
# COMERCIOS
# ============================================================

COMERCIOS = [
    {
        "comercio": "farmaonline",
        "nombre": "Farmaonline",
        "url": "https://www.farmaonline.com/",
    },
    {
        "comercio": "farmalife",
        "nombre": "Farmalife",
        "url": "https://www.farmalife.com.ar/",
    },
    {
        "comercio": "farmacity",
        "nombre": "Farmacity",
        "url": "https://www.farmacity.com/",
    },
    {
        "comercio": "masonline",
        "nombre": "MâsOnline",
        "url": "https://www.masonline.com.ar/",
    },
    {
        "comercio": "perfumeriaspigmento",
        "nombre": "Perfumerías Pigmento",
        "url": "https://www.pigmento.com.ar/",
        "verify_ssl": False,
    },
    {
        "comercio": "farmaplus",
        "nombre": "FarmaPlus",
        "url": "https://www.farmaplus.com.ar/",
    },
    {
        "comercio": "josimar",
        "nombre": "Josimar",
        "url": "https://www.josimar.com.ar/",
    },
    {
        "comercio": "carrefour",
        "nombre": "Carrefour",
        "url": "https://www.carrefour.com.ar/",
    },
    {
        "comercio": "diaonline",
        "nombre": "DIA",
        "url": "https://diaonline.supermercadosdia.com.ar/",
    },
    {
        "comercio": "coto",
        "nombre": "Coto",
        "url": "https://www.coto.com.ar/",
    },
    {
        "comercio": "paradineiro",
        "nombre": "Paradineiro",
        "url": "http://www.paradineirofarmacias.com.ar/",
    },
]


# ============================================================
# SESIÓN HTTP
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    }
)


# ============================================================
# UTILIDADES
# ============================================================


def normalizar_url(url, base_url):
    """
    Convierte URLs relativas en absolutas.
    """

    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):
        return "https:" + url

    return urljoin(base_url, url)


def parece_logo(url, texto="", alt=""):
    """
    Devuelve un puntaje aproximado para determinar
    si una imagen probablemente sea el logo.
    """

    valor = f"{url} {texto} {alt}".lower()

    puntaje = 0

    palabras_logo = [
        "logo",
        "brand",
        "marca",
        "isotipo",
        "logotipo",
        "header-logo",
        "site-logo",
        "logo-header",
        "logo-footer",
    ]

    for palabra in palabras_logo:
        if palabra in valor:
            puntaje += 10

    # Penalizaciones
    palabras_no_logo = [
        "banner",
        "slider",
        "producto",
        "product",
        "category",
        "categoria",
        "icon",
        "favicon",
        "payment",
        "facebook",
        "instagram",
        "youtube",
    ]

    for palabra in palabras_no_logo:
        if palabra in valor:
            puntaje -= 5

    return puntaje


def buscar_logo(html, base_url):
    """
    Intenta encontrar el logo de varias maneras.
    """

    soup = BeautifulSoup(html, "html.parser")

    candidatos = []

    # --------------------------------------------------------
    # 1. JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all("script", type="application/ld+json"):

        try:
            contenido = script.string

            if not contenido:
                continue

            # Búsqueda simple de "logo": "URL"
            coincidencias = re.findall(
                r'"logo"\s*:\s*"([^"]+)"', contenido, flags=re.IGNORECASE
            )

            for url in coincidencias:

                url = normalizar_url(url, base_url)

                if url:
                    candidatos.append((100, url, "JSON-LD logo"))

        except Exception:
            pass

    # --------------------------------------------------------
    # 2. Open Graph
    # --------------------------------------------------------

    for meta in soup.find_all("meta"):

        prop = (meta.get("property") or meta.get("name") or "").lower()

        content = meta.get("content")

        if not content:
            continue

        # og:image no necesariamente es el logo,
        # pero sirve como candidato.
        if prop == "og:image":

            url = normalizar_url(content, base_url)

            if url:
                candidatos.append((40, url, "Open Graph"))

    # --------------------------------------------------------
    # 3. <img>
    # --------------------------------------------------------

    for img in soup.find_all("img"):

        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )

        if not src:
            continue

        url = normalizar_url(src, base_url)

        if not url:
            continue

        alt = img.get("alt", "")
        clase = " ".join(img.get("class", []))
        img_id = img.get("id", "")

        puntaje = parece_logo(url, texto=f"{clase} {img_id}", alt=alt)

        # Los logos suelen estar arriba de la página.
        try:
            posicion = list(soup.find_all("img")).index(img)

            if posicion < 10:
                puntaje += 3

        except Exception:
            pass

        if puntaje > 0:

            candidatos.append((puntaje, url, f"IMG alt='{alt}' class='{clase}'"))

    # --------------------------------------------------------
    # 4. Elementos <a> con clase/id relacionado con logo
    # --------------------------------------------------------

    for elemento in soup.find_all(["a", "div", "span"], class_=True):

        clases = " ".join(elemento.get("class", []))

        if "logo" not in clases.lower():
            continue

        img = elemento.find("img")

        if not img:
            continue

        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

        if not src:
            continue

        url = normalizar_url(src, base_url)

        if url:

            candidatos.append((90, url, "Elemento con clase logo"))

    # --------------------------------------------------------
    # Ordenar candidatos
    # --------------------------------------------------------

    # --------------------------------------------------------
    # COTO - búsqueda específica
    # --------------------------------------------------------

    if "coto" in base_url.lower():

        print("    → Buscando imágenes específicas de COTO...")

        for img in soup.find_all("img"):

            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
            )

            if not src:
                continue

            url = normalizar_url(src, base_url)

            if not url:
                continue

            alt = img.get("alt", "")
            clase = " ".join(img.get("class", []))
            img_id = img.get("id", "")

            texto = (f"{url} " f"{alt} " f"{clase} " f"{img_id}").lower()

            if any(
                palabra in texto
                for palabra in ["coto", "logo-coto", "logocoto", "logo_coto"]
            ):

                print(f"       Candidato COTO: {url}")

                candidatos.append((95, url, "Búsqueda específica COTO"))

    if not candidatos:
        return None, None

    candidatos.sort(key=lambda x: x[0], reverse=True)

    # Eliminar duplicados conservando
    # el mejor puntaje.
    vistos = set()

    candidatos_limpios = []

    for puntaje, url, metodo in candidatos:

        if url in vistos:
            continue

        vistos.add(url)

        candidatos_limpios.append((puntaje, url, metodo))

    if not candidatos_limpios:
        return None, None

    mejor = candidatos_limpios[0]

    return mejor[1], mejor[2]


def verificar_imagen(url):
    """
    Comprueba que la URL encontrada realmente responda
    como una imagen.
    """

    try:

        respuesta = session.head(url, timeout=15, allow_redirects=True)

        content_type = respuesta.headers.get("Content-Type", "").lower()

        if respuesta.status_code < 400:

            if "image" in content_type:
                return True, content_type

        # Algunos CDN no responden correctamente a HEAD.
        respuesta = session.get(url, timeout=15, stream=True)

        content_type = respuesta.headers.get("Content-Type", "").lower()

        return (respuesta.status_code < 400 and "image" in content_type, content_type)

    except Exception as e:

        return False, str(e)


# ============================================================
# GOOGLE SHEETS
# ============================================================


def conectar_sheets():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

    cliente = gspread.authorize(credentials)

    return cliente


def obtener_o_crear_hoja(spreadsheet):

    try:

        hoja = spreadsheet.worksheet(SHEET_NAME)

        print(f"✓ La hoja '{SHEET_NAME}' ya existe.")

        return hoja

    except gspread.WorksheetNotFound:

        print(f"→ Creando hoja '{SHEET_NAME}'...")

        hoja = spreadsheet.add_worksheet(title=SHEET_NAME, rows=100, cols=10)

        return hoja


# ============================================================
# PROCESO PRINCIPAL
# ============================================================


def main():

    print()
    print("=" * 70)
    print(" OBTENER LOGOS DE COMERCIOS")
    print("=" * 70)
    print()

    # --------------------------------------------------------
    # Conectar Google Sheets
    # --------------------------------------------------------

    print("Conectando con Google Sheets...")

    cliente = conectar_sheets()

    spreadsheet = cliente.open_by_key(SPREADSHEET_ID)

    print(f"✓ Spreadsheet: {spreadsheet.title}")

    hoja = obtener_o_crear_hoja(spreadsheet)

    print()

    # --------------------------------------------------------
    # Encabezados
    # --------------------------------------------------------

    encabezados = [
        "comercio",
        "nombre",
        "sitio_web",
        "logo_url",
        "metodo",
        "content_type",
        "estado",
        "fecha_actualizacion",
    ]

    # --------------------------------------------------------
    # Buscar logos
    # --------------------------------------------------------

    resultados = []

    total = len(COMERCIOS)

    for numero, comercio in enumerate(COMERCIOS, start=1):

        nombre = comercio["nombre"]
        codigo = comercio["comercio"]
        sitio = comercio["url"]

        print(f"[{numero}/{total}] " f"{nombre}")

        print(f"    Sitio: {sitio}")

        try:

            respuesta = session.get(
                sitio, timeout=25, verify=comercio.get("verify_ssl", True)
            )

            respuesta.raise_for_status()

            logo_url, metodo = buscar_logo(respuesta.text, respuesta.url)

            if not logo_url:

                print("    ✗ No se encontró automáticamente.")

                resultados.append(
                    [
                        codigo,
                        nombre,
                        sitio,
                        "",
                        "",
                        "",
                        "NO ENCONTRADO",
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                    ]
                )

                continue

            print(f"    Logo encontrado:")

            print(f"    {logo_url}")

            print(f"    Método: {metodo}")

            # ------------------------------------------------
            # Verificar URL
            # ------------------------------------------------

            valida, content_type = verificar_imagen(logo_url)

            if valida:

                estado = "OK"

                print(f"    ✓ Imagen válida " f"({content_type})")

            else:

                estado = "URL_ENCONTRADA_PERO_NO_VERIFICADA"

                print(
                    "    ⚠ Se encontró la URL " "pero no se pudo verificar como imagen."
                )

            resultados.append(
                [
                    codigo,
                    nombre,
                    sitio,
                    logo_url,
                    metodo,
                    content_type,
                    estado,
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

        except Exception as e:

            print(f"    ✗ ERROR: {e}")

            resultados.append(
                [
                    codigo,
                    nombre,
                    sitio,
                    "",
                    "",
                    "",
                    f"ERROR: {e}",
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

        print()

        # Pequeña pausa para no golpear los sitios.
        time.sleep(1)

    # ========================================================
    # ESCRIBIR GOOGLE SHEETS
    # ========================================================

    print("=" * 70)
    print("Guardando resultados en Google Sheets...")
    print("=" * 70)

    # Limpiar hoja existente
    hoja.clear()

    datos = [encabezados] + resultados

    hoja.update(range_name="A1", values=datos)

    # Formato básico
    try:

        hoja.format("A1:H1", {"textFormat": {"bold": True}})

        hoja.format("D2:D100", {"wrapStrategy": "CLIP"})

        # Anchos aproximados
        anchos = {
            "A": 180,
            "B": 200,
            "C": 300,
            "D": 500,
            "E": 220,
            "F": 150,
            "G": 250,
            "H": 180,
        }

        for columna, ancho in anchos.items():

            hoja.format(f"{columna}:{columna}", {"columnWidth": ancho})

    except Exception as e:

        print(f"⚠ No se pudo aplicar algún formato: {e}")

    # ========================================================
    # RESUMEN
    # ========================================================

    encontrados = sum(1 for fila in resultados if fila[6] == "OK")

    no_encontrados = sum(1 for fila in resultados if fila[6] == "NO ENCONTRADO")

    errores = sum(1 for fila in resultados if fila[6].startswith("ERROR"))

    print()
    print("=" * 70)
    print(" PROCESO TERMINADO")
    print("=" * 70)

    print(f"Total comercios: {total}")

    print(f"Logos encontrados y verificados: {encontrados}")

    print(f"No encontrados: {no_encontrados}")

    print(f"Errores: {errores}")

    print()

    print(f"✓ Hoja actualizada: {SHEET_NAME}")

    print()


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
