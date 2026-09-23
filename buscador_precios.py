"""
Buscador de precios por LÍNEA DE PRODUCTO (no por SKU individual).

En vez de mantener una lista de URLs/SKUs producto por producto, este
script busca cada línea de marca (ej. "dove bond repair") en cada sitio
y descubre automáticamente todos los productos de esa línea que vende
ese sitio, con su precio final (incluyendo promos de 2x1 / llevando 2
cuando existen).

Requisitos:
    pip3 install requests beautifulsoup4 gspread google-auth --break-system-packages

Uso:
    python3 buscador_precios.py
"""

import re
import time
import random
import os
import json
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------
# CONFIGURACIÓN DE GOOGLE SHEETS
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"
NOMBRE_HOJA_LOG = "Precios_Log_Lineas"  # pestaña nueva, separada de la anterior
NOMBRE_HOJA_IMAGENES = "Imagenes_Productos"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# -----------------------------------------------------------------------
# LÍNEAS DE PRODUCTO A BUSCAR
# "busqueda": término (o LISTA de términos) tal como se usaría en la
#             barra de búsqueda del sitio. Si es una lista, se buscan
#             todos y se combinan los resultados sin duplicar productos
#             (útil para unificar líneas relacionadas, ej. DiabetTX y
#             Goicoechea, en una sola consulta/fila por producto).
# "incluir": lista de patrones (palabras o regex) — el producto SOLO se
#            guarda si su nombre contiene al menos uno. Filtra ruido de
#            búsquedas difusas (ej. en Coto, buscar "...400" a veces trae
#            productos de otras marcas que no tienen nada que ver).
# "excluir": lista de patrones (palabras o regex) — si el nombre contiene
#            alguno, se descarta. Los patrones son regex (case-insensitive),
#            así que "200\\s*ml" matchea "200ml", "200 ml", "x 200 ml", etc.
# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# EXCLUSIÓN GLOBAL: patrones que se descartan en TODAS las líneas, sin
# importar cuál sea (productos que nunca interesan independientemente
# de la línea de marca que se esté buscando).
# -----------------------------------------------------------------------
EXCLUIR_GLOBAL = [
    r"agua micelar",
    r"antitranspirante",
    r"\btalco\b",
    r"porcelana",
    r"jab[oó]n",
    r"manchas",
    r"limpieza",
    r"\bcover\b",
    r"multiprop[oó]sito",
    r"\bcoo\b",
    r"excellence",
]

EAN_EXCLUIDOS = {
    "7509552859133",
    "7891150104822",
    "7898587774901",
    "7791293051024",
    "650240077111",
    "7898636190706",
    "650240068676",
    "7798420161014",
    "650240073151",
    "4005900528223",
    "7798420160567",
    "7798420161021",
    "25066",
    "20279",
    "20092",

    # Sedal - excluir por el momento
    "7791293045795",
    "7791293045801",
    "7791293046389",
    "7791293045993",
    "7791293045986",
    "7791293045658",
    "7791293045818",
    "7791293045825",
    "7791293049724",
    "7791293045832",
    "7791293051444",
    "7791293046440",
    "7791293052205",
    "7791293045887",
    "7791293045689",
    "7791293046426",
    "7791293045863",
    "7791293045665",
    "7791293046365",
    "7791293045696",
    "7791293045856",
    "7791293045870",
    "7791293045672",
    "7791293045894",
    "7791293046013",
    "7791293046006",
    "7791293046020",
    "7791293046419",
    "7791293051475",
    "7791293051451",
    "7791293051420",
    "7791293049779",    
    "7791293049748",
    "7791293052199",    
}

# -----------------------------------------------------------------------
# EXCLUSIÓN POR COMERCIO
#
# Útil para códigos internos/SKU que un comercio utiliza como EAN.
# El mismo número puede existir en otro comercio y NO se excluye allí.
# -----------------------------------------------------------------------

EAN_EXCLUIDOS_POR_COMERCIO = {


   "coto": {
        # "25066",
    },

    "farmacity": {
        # "25066",
    },

    "farmalife": {
        # "25066",
    },

    "farmaplus": {
        "20283",
        "20277",        
    },

    "josimar": {
        # "25066",
    },

    "carrefour": {
        # "25066",
    },

    "diaonline": {
        # "25066",
    },

    "masonline": {
        # "25066",
    },

    "perfumeriaspigmento": {
        "25068",
    },

    "paradineiro": {
        # "25066",
    }

}

LINEAS = [
    {
        "nombre": "Dove Bond Repair",
        "busqueda": "dove-bond-repair",
        "busqueda_por_sitio": {"perfumeriaspigmento": "bond-repair"},
        "incluir": ["bond"],
        "excluir": [r"200\s*(ml|cc)", r"193\s*(ml|cc)", r"385\s*(ml|cc)"],
    },
    {
        "nombre": "Dove UV Repair",
        "busqueda": "dove-uv-repair",
        "busqueda_por_sitio": {"perfumeriaspigmento": "uv-repair"},
        "incluir": [r"uv\s*repair", r"reparaci[oó]n\s*y\s*brillo"],
        "excluir": [r"200\s*(ml|cc)"],
    },
    {
        "nombre": "Extraordinario",
        "busqueda": "extraordinario",
        "incluir": ["elvive", "extraordinario"],
        "excluir": ["coco", "rizos", "libro", r"200\s*(ml|cc)", r"750\s*(ml|cc)"],
    },
    {
        "nombre": "Dream Liso",
        "busqueda": "dream-liso",
        "incluir": ["elvive", r"dream\s*liso"],
        "excluir": [r"200\s*(ml|cc)", r"750\s*(ml|cc)"],
    },
    {
        "nombre": "Cicatricure 400",
        "busqueda": ["cicatricure-400", "cicatricure-age-care", "cicatricure-gel-60"],
        "incluir": ["cicatricure"],
        "excluir": [
            r"\bgel\b",
            r"\bporcelana\b",
            r"\bacqua defense\b",
            r"\bage care\b",
            r"\bfacial\b",
            r"\bcontorno\b",
            r"\bs[eé]rum\b",
            r"\bpeeling\b",
            r"\btricure\b",
            r"\bantiedad\b",
            r"\baclarante\b",
            r"\bblur\b",
            r"beauty care",
            r"maquillaje",
            r"gold lift",
            r"regene-?plast",
            r"protector solar",
            r"reparaci[oó]n epid[eé]rmica",
            r"neuro-?zen",
        ],
    },
    {
        "nombre": "Cicatricure Age Care",
        "busqueda": ["cicatricure-400", "cicatricure-age-care", "cicatricure-gel-60"],
        "incluir": [r"age care"],
        "aplicar_incluir_en_vtex": True,
        "excluir": [],
    },
    {
        "nombre": "DiabetTX / Goicoechea 400",
        "busqueda": ["diabettx-400", "goicoechea-400"],
        "incluir": ["diabettx", "goicoechea"],
        "excluir": [],
    },
    {
        "nombre": "Nivea Creme 150",
        "busqueda": "nivea-creme-150",
        "incluir": [r"(?=.*creme)(?=.*150)"],
        "excluir": [],
    },
    {
        "nombre": "Sedal",
        "busqueda": "sedal",
        "incluir": ["sedal"],
        "excluir": [],
    },
    {
        "nombre": "Cicatricure Gel 60",
        "busqueda": ["cicatricure-400", "cicatricure-age-care", "cicatricure-gel-60"],
        "incluir": ["cicatricure"],
        "excluir": [
            r"\bcorporal\b",
            r"400\s*(ml|cc)",
            r"\bage care\b",
            r"beauty care",
            r"maquillaje",
            r"gold lift",
            r"\bcontorno\b",
        ],
    },
]

# -----------------------------------------------------------------------
# SITIOS VTEX
# "metodo_precio": "promo2u" (default, simula compra de 2 unidades para
#                  capturar promos de cantidad) o "css" (para sitios donde
#                  la API de simulación no refleja el precio real, como
#                  Josimar; en ese caso se lee el precio del HTML)
# "fallback_css": si la API de simulación dice "withoutStock" (y por eso
# "sales_channel": el número de canal de venta VTEX de la cuenta. La
#                  mayoría usa "1" por defecto, pero cada cuenta lo
#                  configura a su gusto (ej. Farmacity usa "4" — lo
#                  encontramos mirando la cookie vtex_segment del sitio).
#                  Si de golpe un sitio empieza a marcar "sin stock" de
#                  forma sospechosamente constante, vale la pena revisar
#                  esta cookie para confirmar el canal real.
# -----------------------------------------------------------------------
# "postal_code": código postal a usar en la simulación de compra.
#                Por defecto en None (no se manda el campo) en todos los
#                sitios, porque en varios casos (Farmacity, MasOnline)
#                mandarlo hace que VTEX busque stock de un depósito local
#                puntual y devuelva "sin stock"/"no se puede entregar",
#                aunque el producto sí esté disponible a nivel nacional
#                y la promo activa no se aplique por eso. Si algún sitio
#                necesita el código postal para calcular bien el precio
#                (poco común), se le puede poner acá puntualmente.
# -----------------------------------------------------------------------
SITIOS_VTEX = [
    {
        "sitio": "farmaonline",
        "dominio": "www.farmaonline.com",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmalife",
        "dominio": "www.farmalife.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmacity",
        "dominio": "www.farmacity.com",
        "metodo_precio": "promo2u",
        "fallback_css": False,
        "sales_channel": "4",
        "postal_code": None,
    },
    {
        "sitio": "masonline",
        "dominio": "www.masonline.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "perfumeriaspigmento",
        "dominio": "www.perfumeriaspigmento.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmaplus",
        "dominio": "www.farmaplus.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "josimar",
        "dominio": "www.josimar.com.ar",
        "metodo_precio": "css",
        "fallback_css": False,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "carrefour",
        "dominio": "www.carrefour.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "diaonline",
        "dominio": "diaonline.supermercadosdia.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
]

COTO_SEARCH_URL = (
    "https://api.coto.com.ar/api/v1/ms-digital-sitio-bff-web/api/v1/products/search/"
)
COTO_SEARCH_KEY = "key_r6xzz4IAoTWcipni"

PARADINEIRO_SEARCH_URL = "https://www.paradineirofarmacias.com.ar/shop"
PARADINEIRO_DOMINIO = "https://www.paradineirofarmacias.com.ar"

PRODUCTOS_POR_PAGINA_VTEX = 40
MAX_PAGINAS_VTEX = 3

def request_con_reintentos(metodo: str, url: str, max_intentos: int = 3, **kwargs):
    """
    Hace un request con reintentos y backoff exponencial si el sitio
    devuelve 429 (too many requests) o algún error 5xx transitorio.
    Entre pedidos exitosos también espera un tiempo aleatorio corto para
    no generar un patrón de tráfico perfectamente regular.
    """
    for intento in range(1, max_intentos + 1):
        try:
            resp = requests.request(metodo, url, timeout=15, **kwargs)
        except requests.RequestException as e:
            if intento == max_intentos:
                raise
            time.sleep(2**intento)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if intento == max_intentos:
                return resp  # devolvemos igual, el llamador maneja el error
            espera = (2**intento) + random.uniform(0, 1)
            print(
                f"    [rate limit / error {resp.status_code}] esperando {espera:.1f}s y reintentando..."
            )
            time.sleep(espera)
            continue

        return resp

    return resp


def pausa_entre_pedidos():
    time.sleep(1 + random.uniform(0, 0.8))


# -----------------------------------------------------------------------
# UTILIDADES DE PARSEO
# -----------------------------------------------------------------------
def parsear_precio_ar(texto: str):
    """Convierte '$ 9.599,40' (formato argentino) -> 9599.40"""
    match = re.search(r"([\d.]+,\d{2}|[\d.]+)", texto)
    if not match:
        return None
    limpio = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def parsear_precio_punto(texto: str):
    """Convierte '$6830.64' (punto decimal) -> 6830.64"""
    match = re.search(r"[\d]+\.?\d*", texto)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None

def ean_excluido(ean, sitio):
    """
    Determina si un EAN debe excluirse.

    1. Si está en EAN_EXCLUIDOS, se excluye globalmente.
    2. Si está en EAN_EXCLUIDOS_POR_COMERCIO, se excluye
       solamente del comercio correspondiente.

    El mismo código puede estar excluido en un comercio
    y ser válido en otro.
    """

    ean = str(ean or "").strip()
    sitio = str(sitio or "").strip().lower()

    if not ean:
        return False

    # Exclusión global
    if ean in EAN_EXCLUIDOS:
        return True

    # Exclusión específica del comercio
    eans_comercio = EAN_EXCLUIDOS_POR_COMERCIO.get(
        sitio,
        set()
    )

    return ean in eans_comercio

def pasa_filtro_exclusion(nombre: str, excluir: list):
    nombre_str = nombre or ""
    todos_los_patrones = list(excluir) + EXCLUIR_GLOBAL
    return not any(
        re.search(patron, nombre_str, re.IGNORECASE) for patron in todos_los_patrones
    )


def pasa_filtro_inclusion(nombre: str, incluir: list):
    if not incluir:
        return True
    nombre_str = nombre or ""
    return any(re.search(patron, nombre_str, re.IGNORECASE) for patron in incluir)


def normalizar_terminos(busqueda):
    """Acepta un string o una lista de strings y siempre devuelve una lista."""
    if isinstance(busqueda, str):
        return [busqueda]
    return list(busqueda)


# -----------------------------------------------------------------------
# CACHÉ DE BÚSQUEDAS
# Si dos líneas piden el mismo término al mismo sitio (ej. las 3 líneas
# de Cicatricure comparten los mismos 3 términos), la segunda vez se
# reutiliza el resultado ya obtenido en vez de volver a pedirlo por red.
# Clave: (tipo_sitio, identificador_sitio, término) -> lista de productos
# crudos (antes de aplicar incluir/excluir de cada línea).
# -----------------------------------------------------------------------
CACHE_BUSQUEDA = {}

# -----------------------------------------------------------------------
# CACHÉ DE IMÁGENES
#
# Se carga una sola vez desde Google Sheets al comenzar la ejecución.
# EAN -> {"imageurl": "...", "fuente": "..."}
#
# De esta manera, si un EAN ya tiene imagen, no volvemos a buscarla.
# -----------------------------------------------------------------------
CACHE_IMAGENES = {}

# EAN que durante ESTA corrida ya fueron procesados.
# Evita intentar obtener la misma imagen varias veces si el producto
# aparece en varios comercios/líneas.
EANS_IMAGEN_PROCESADOS = set()

# Nuevas imágenes que se subirán a Google Sheets al finalizar.
NUEVAS_IMAGENES = []


def es_url_imagen_valida(url):
    if not url:
        return False

    if not isinstance(url, str):
        return False

    url = url.strip()

    return url.startswith("http://") or url.startswith("https://")


def extraer_imagen_de_datos(datos):
    """
    Extrae una URL de imagen sin hacer ninguna petición adicional.

    Para VTEX primero busca en el campo estándar:
        images -> imageUrl

    Si no encuentra nada, hace una búsqueda recursiva
    sobre campos habituales de imagen.
    """

    if not isinstance(datos, (dict, list)):
        return None

    # ---------------------------------------------------------------
    # 1. Caso estándar VTEX: images -> imageUrl
    # ---------------------------------------------------------------

    if isinstance(datos, dict):
        imagenes = datos.get("images")

        if isinstance(imagenes, list):
            for imagen in imagenes:
                if not isinstance(imagen, dict):
                    continue

                url = imagen.get("imageUrl")

                if es_url_imagen_valida(url):
                    return url.strip()

    # ---------------------------------------------------------------
    # 2. Respaldo: búsqueda recursiva
    # ---------------------------------------------------------------

    campos_prioritarios = [
        "imageUrl",
        "image_url",
        "imageURL",
        "imageurl",
        "imageUri",
        "image_uri",
    ]

    def recorrer(obj):

        if isinstance(obj, dict):

            for campo in campos_prioritarios:
                valor = obj.get(campo)

                if isinstance(valor, str):
                    if es_url_imagen_valida(valor):
                        return valor.strip()

            for valor in obj.values():
                resultado = recorrer(valor)

                if resultado:
                    return resultado

        elif isinstance(obj, list):

            for elemento in obj:
                resultado = recorrer(elemento)

                if resultado:
                    return resultado

        return None

    return recorrer(datos)


# -----------------------------------------------------------------------
# DESCUBRIMIENTO DE PRODUCTOS
# -----------------------------------------------------------------------
def buscar_productos_vtex(dominio, busqueda):
    """
    Busca una línea de producto en VTEX y devuelve la lista de productos
    encontrados con nombre, skuId, link, EAN e imagen.

    Utiliza paginación:
      - hasta 40 productos por página
      - máximo 3 páginas
      - continúa a la siguiente página solamente si la anterior
        devolvió exactamente 40 productos.

    Usa CACHE_BUSQUEDA para no repetir un mismo término
    en el mismo sitio durante esta corrida.
    """
    productos_por_sku = {}

    for termino in normalizar_terminos(busqueda):
        clave_cache = ("vtex", dominio, termino)

        if clave_cache in CACHE_BUSQUEDA:
            productos_termino = CACHE_BUSQUEDA[clave_cache]

        else:
            productos_termino = []

            for pagina in range(MAX_PAGINAS_VTEX):
                desde = pagina * PRODUCTOS_POR_PAGINA_VTEX
                hasta = desde + PRODUCTOS_POR_PAGINA_VTEX - 1

                url = (
                    f"https://{dominio}/api/catalog_system/pub/products/search/"
                    f"{termino}"
                    f"?_from={desde}&_to={hasta}"
                )

                try:
                    resp = request_con_reintentos(
                        "GET",
                        url,
                        headers=HEADERS
                    )
                    resp.raise_for_status()
                    data = resp.json()

                except Exception as e:
                    return None, (
                        f"error de búsqueda ('{termino}', "
                        f"página {pagina + 1}): {e}"
                    )

                print(
                    f"    [VTEX] {termino} → página {pagina + 1}: "
                    f"{len(data)} productos"
                )

                for p in data:
                    items = p.get("items", [])

                    if not items:
                        continue

                    item = items[0]

                    productos_termino.append(
                        {
                            "nombre": p.get("productName", ""),
                            "sku_id": item.get("itemId"),
                            "link": p.get("link"),
                            "ean": item.get("ean"),
                            "imageurl": extraer_imagen_de_datos(item),
                        }
                    )

                # Si vinieron menos de 40, ya no hay otra página.
                if len(data) < PRODUCTOS_POR_PAGINA_VTEX:
                    break

                # Evita hacer consultas consecutivas demasiado rápido.
                pausa_entre_pedidos()

            CACHE_BUSQUEDA[clave_cache] = productos_termino

            # Mantener la pausa que ya tenía el buscador
            # después de completar el término.
            pausa_entre_pedidos()

        for prod in productos_termino:
            if prod["sku_id"] in productos_por_sku:
                continue

            productos_por_sku[prod["sku_id"]] = prod

    return list(productos_por_sku.values()), None


def buscar_productos_coto(busqueda):
    """Busca una línea de producto (uno o varios términos) en Coto (API
    de Constructor.io) y devuelve la lista de productos con nombre,
    precio final (con promo si aplica) y URL de referencia, sin
    duplicados (por sku_id) si varios términos traen el mismo producto.
    Usa CACHE_BUSQUEDA para no repetir un mismo término si ya se pidió
    antes en esta corrida."""
    params = {
        "key": COTO_SEARCH_KEY,
        "num_results_per_page": 96,
        "pre_filter_expression": '{"name":"store_availability","value":"200"}',
        "c": "cio-fe-web-coto-4.1.0",
    }
    productos_por_sku = {}
    for termino in normalizar_terminos(busqueda):
        clave_cache = ("coto", "coto", termino)
        if clave_cache in CACHE_BUSQUEDA:
            productos_termino = CACHE_BUSQUEDA[clave_cache]
        else:
            try:
                resp = request_con_reintentos(
                    "GET", COTO_SEARCH_URL + termino, headers=HEADERS, params=params
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                return None, f"error de búsqueda ('{termino}'): {e}"

            resultados = data.get("response", {}).get("results", [])
            productos_termino = []
            for r in resultados:
                d = r.get("data", {})
                sku_id = d.get("sku_id") or d.get("id")
                nombre = r.get("value") or d.get("sku_display_name", "")
                descuentos = d.get("discounts", [])
                promo_info = None
                if descuentos:
                    precio = parsear_precio_punto(
                        descuentos[0].get("discountPrice", "")
                    )
                    promo_info = descuentos[0].get("discountText")
                else:
                    precio = d.get("product_list_price")
                url_rel = d.get("url", "")
                url_completa = (
                    f"https://www.coto.com.ar/sitios/cdigi/productos/producto/{url_rel}"
                )
                productos_termino.append(
                    {
                        "sku_id": sku_id,
                        "nombre": nombre,
                        "precio": precio,
                        "disponibilidad": (
                            f"promo: {promo_info}" if promo_info else "sin_promo"
                        ),
                        "url": url_completa,
                        "ean": d.get("product_main_ean"),
                        "imageurl": extraer_imagen_de_datos(d),
                    }
                )

            CACHE_BUSQUEDA[clave_cache] = productos_termino
            pausa_entre_pedidos()

        for prod in productos_termino:
            if prod["sku_id"] in productos_por_sku:
                continue
            productos_por_sku[prod["sku_id"]] = prod

    return list(productos_por_sku.values()), None


def normalizar_nombre_paradineiro(texto):
    """
    Normaliza nombres para poder comparar el nombre del producto
    del listado HTML con el nombre que aparece en createProductsListedEvent.
    """
    texto = unicodedata.normalize("NFD", texto or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def buscar_ean_paradineiro(nombre, mapa_ean):
    """
    Busca el EAN correspondiente al nombre del producto.

    Primero intenta coincidencia exacta. Si no encuentra, intenta
    una coincidencia muy similar para casos como:
    'Univ 750' vs 'Universal 750 ml'.
    """
    nombre_norm = normalizar_nombre_paradineiro(nombre)

    # 1) Coincidencia exacta
    if nombre_norm in mapa_ean:
        return mapa_ean[nombre_norm][0]

    # 2) Coincidencia aproximada muy conservadora
    from difflib import SequenceMatcher

    mejor_ean = None
    mejor_score = 0
    segundo_score = 0

    for nombre_evento, eans in mapa_ean.items():
        score = SequenceMatcher(None, nombre_norm, nombre_evento).ratio()

        if score > mejor_score:
            segundo_score = mejor_score
            mejor_score = score
            mejor_ean = eans[0] if eans else None
        elif score > segundo_score:
            segundo_score = score

    # Solo aceptamos coincidencias muy fuertes
    # y evitamos casos donde hay dos candidatos demasiado parecidos.
    if mejor_ean and mejor_score >= 0.92 and (mejor_score - segundo_score >= 0.02):
        return mejor_ean

    return None


def buscar_productos_paradineiro(busqueda):
    """
    Busca una línea de producto en Paradineiro Farmacias.

    Además de precio, stock e imagen, obtiene los EAN que Paradineiro
    incluye dentro de createProductsListedEvent() en el HTML de la
    búsqueda.
    """

    productos_por_id = {}

    for termino in normalizar_terminos(busqueda):

        clave_cache = ("paradineiro", "paradineiro", termino)

        if clave_cache in CACHE_BUSQUEDA:
            productos_termino = CACHE_BUSQUEDA[clave_cache]

        else:
            try:
                resp = request_con_reintentos(
                    "GET",
                    PARADINEIRO_SEARCH_URL,
                    headers=HEADERS,
                    params={"s": termino},
                )
                resp.raise_for_status()

            except Exception as e:
                return None, f"error de búsqueda ('{termino}'): {e}"

            # ---------------------------------------------------------
            # EXTRAER EAN DEL createProductsListedEvent()
            # ---------------------------------------------------------

            mapa_ean_paradineiro = {}

            patron_ean = re.compile(
                r"\{\s*"
                r"a:\s*'([^']*)'\s*,\s*"
                r"b:\s*'([^']*)'\s*,\s*"
                r"c:\s*'([^']*)'\s*,\s*"
                r"d:\s*'([^']*)'",
                re.IGNORECASE,
            )

            for match in patron_ean.finditer(resp.text):

                eans = [e.strip() for e in match.group(1).split(",") if e.strip()]

                nombre_evento = match.group(2).strip()

                if eans and nombre_evento:
                    mapa_ean_paradineiro[
                        normalizar_nombre_paradineiro(nombre_evento)
                    ] = eans

            # ---------------------------------------------------------
            # EXTRAER PRODUCTOS DEL HTML
            # ---------------------------------------------------------

            soup = BeautifulSoup(resp.text, "html.parser")

            productos_termino = []

            for li in soup.select("li.product"):

                contenedor = li.select_one("div[data-product]")

                producto_id = contenedor.get("data-product") if contenedor else None

                if not producto_id:
                    continue

                a_tag = li.find("a", href=True)

                if not a_tag:
                    continue

                link = PARADINEIRO_DOMINIO + a_tag["href"]

                titulo_tag = li.select_one("h3.kw-details-title span.child-top")

                nombre = titulo_tag.get_text(strip=True) if titulo_tag else None

                # -----------------------------------------------------
                # PRECIO
                # -----------------------------------------------------

                precio = None

                precio_tag = li.select_one("span.price")

                if precio_tag:

                    # El precio final es el amount que NO está
                    # dentro de un <del>.
                    for amt in precio_tag.find_all("span", class_="amount"):
                        if amt.find_parent("del"):
                            continue

                        precio = parsear_precio_ar(amt.get_text())

                # -----------------------------------------------------
                # STOCK
                # -----------------------------------------------------

                sin_stock = "SIN STOCK" in li.get_text().upper()

                # -----------------------------------------------------
                # IMAGEN
                # -----------------------------------------------------

                imagen_url = None

                img_tag = li.select_one("img")

                if img_tag:

                    imagen_url = (
                        img_tag.get("src")
                        or img_tag.get("data-src")
                        or img_tag.get("data-lazy-src")
                    )

                    if imagen_url and imagen_url.startswith("//"):
                        imagen_url = "https:" + imagen_url

                    elif imagen_url and imagen_url.startswith("/"):
                        imagen_url = PARADINEIRO_DOMINIO.rstrip("/") + imagen_url

                # -----------------------------------------------------
                # EAN
                # -----------------------------------------------------

                ean = buscar_ean_paradineiro(nombre, mapa_ean_paradineiro)

                if not ean and nombre:
                    print(f"[EAN NO ENCONTRADO] Paradineiro: {nombre}")

                elif ean:
                    print(f"[EAN ENCONTRADO] Paradineiro: " f"{ean} -> {nombre}")

                productos_termino.append(
                    {
                        "sku_id": producto_id,
                        "nombre": nombre,
                        "precio": precio,
                        "disponibilidad": ("sin_stock" if sin_stock else "available"),
                        "url": link,
                        "imageurl": imagen_url,
                        "ean": ean,
                    }
                )

            CACHE_BUSQUEDA[clave_cache] = productos_termino

            pausa_entre_pedidos()

        # -------------------------------------------------------------
        # EVITAR DUPLICADOS ENTRE TÉRMINOS DE UNA MISMA LÍNEA
        # -------------------------------------------------------------

        for prod in productos_termino:

            if prod["sku_id"] in productos_por_id:
                continue

            productos_por_id[prod["sku_id"]] = prod

    return list(productos_por_id.values()), None


# -----------------------------------------------------------------------
# CHEQUEO DE DISPONIBILIDAD (sitios VTEX)
# -----------------------------------------------------------------------
def disponibilidad_indica_sin_stock(disponibilidad):
    """
    True si el string de disponibilidad indica que el producto
    no tiene stock real, sin importar si vino acompañado de un
    precio (rescatado por el fallback CSS, promos, etc).
    """
    if not disponibilidad:
        return False
    return disponibilidad.strip().lower().startswith("withoutstock")

# -----------------------------------------------------------------------
# OBTENCIÓN DE PRECIO FINAL (sitios VTEX)
# -----------------------------------------------------------------------
def obtener_precio_css(url: str):
    try:
        resp = request_con_reintentos("GET", url, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"error de conexión: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    
    
    # Chequeo de disponibilidad real: en Carrefour, este span aparece
    # con el texto "No Disponible" cuando el botón de compra está
    # deshabilitado, independientemente de que el precio siga
    # renderizado en la página.
    boton_no_disponible = soup.select_one(
        "span[class*='incompatible-cart'][class*='buttonContentText']"
    )
    if boton_no_disponible and "no disponible" in boton_no_disponible.get_text(strip=True).lower():
        return {"precio": None, "disponibilidad": "sin_stock"}
    
    contenedor = soup.select_one(".vtex-product-price-1-x-sellingPrice")
    if contenedor is None:
        return {"error": "no se encontró el contenedor de precio"}

    precio = parsear_precio_ar(contenedor.get_text())
    if precio is None:
        return {"error": f"no se pudo parsear el precio: '{contenedor.get_text()}'"}

    return {"precio": precio, "disponibilidad": None}


def obtener_precio_simulacion_promo_2u(
    dominio: str, sku_id: str, sales_channel: str = "1", postal_code: str = None
):
    """Simula compra de 2 unidades y devuelve el precio promedio por
    unidad, capturando promos tipo 2x1 / llevando 2."""
    url = f"https://{dominio}/api/checkout/pub/orderForms/simulation?sc={sales_channel}"
    body = {
        "items": [{"id": str(sku_id), "quantity": 2, "seller": "1"}],
        "country": "ARG",
    }
    if postal_code:
        body["postalCode"] = postal_code
    try:
        resp = request_con_reintentos("POST", url, json=body, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return {"error": f"error de conexión: {e}"}
    except ValueError:
        return {"error": "la respuesta no vino en formato JSON"}

    items = data.get("items", [])
    if not items:
        return {"error": "la API no devolvió items"}

    total_centavos = 0
    total_unidades = 0
    disponible = items[0].get("availability")
    hay_promo = bool(
        (data.get("ratesAndBenefitsData") or {}).get("rateAndBenefitsIdentifiers")
    )

    for item in items:
        precio_venta = item.get("sellingPrice")
        cantidad = item.get("quantity", 1)
        if precio_venta is None:
            if disponible == "withoutStock":
                return {"precio": None, "disponibilidad": "withoutStock"}
            return {"error": "no vino sellingPrice en alguno de los items"}
        total_centavos += precio_venta * cantidad
        total_unidades += cantidad

    if total_unidades == 0:
        return {"error": "no se pudo calcular la cantidad total de unidades"}

    precio_por_unidad = (total_centavos / total_unidades) / 100

    nombre_promo = None
    if hay_promo:
        nombre_promo = data["ratesAndBenefitsData"]["rateAndBenefitsIdentifiers"][
            0
        ].get("name")

    return {
        "precio": precio_por_unidad,
        "disponibilidad": f"promo: {nombre_promo}" if nombre_promo else disponible,
    }


def cargar_cache_imagenes(planilla):
    """
    Lee una sola vez la pestaña Imagenes_Productos.

    Devuelve:
        {
            "EAN": {
                "imageurl": "...",
                "fuente": "..."
            }
        }

    Si la hoja no existe, la crea.
    """

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_IMAGENES)

    except gspread.exceptions.WorksheetNotFound:

        print(f"[IMAGENES] Creando pestaña '{NOMBRE_HOJA_IMAGENES}'...")

        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_IMAGENES, rows=2000, cols=3)

        hoja.append_row(["ean", "imageurl", "fuente"])

        return {}

    valores = hoja.get_all_values()

    if not valores:
        return {}

    encabezados = [str(x).strip().lower() for x in valores[0]]

    try:
        indice_ean = encabezados.index("ean")
        indice_imagen = encabezados.index("imageurl")
    except ValueError:
        print(
            f"[IMAGENES] La hoja '{NOMBRE_HOJA_IMAGENES}' "
            "no tiene los encabezados esperados."
        )
        return {}

    indice_fuente = encabezados.index("fuente") if "fuente" in encabezados else None

    cache = {}

    for fila in valores[1:]:

        if len(fila) <= indice_ean:
            continue

        ean = str(fila[indice_ean]).strip()

        if not ean:
            continue

        imageurl = ""

        if len(fila) > indice_imagen:
            imageurl = str(fila[indice_imagen]).strip()

        if not es_url_imagen_valida(imageurl):
            continue

        fuente = ""

        if indice_fuente is not None and len(fila) > indice_fuente:
            fuente = str(fila[indice_fuente]).strip()

        cache[ean] = {"imageurl": imageurl, "fuente": fuente}

    print(f"[IMAGENES] {len(cache)} EAN con imagen ya almacenados.")

    return cache


def registrar_imagen(ean, imageurl, fuente):

    if not ean:
        return False

    ean = str(ean).strip()

    if not es_url_imagen_valida(imageurl):
        return False

    # Ya existe en Google Sheets.
    if ean in CACHE_IMAGENES:
        return False

    # Ya conseguimos una imagen durante esta corrida.
    if ean in EANS_IMAGEN_PROCESADOS:
        return False

    EANS_IMAGEN_PROCESADOS.add(ean)

    registro = {"imageurl": imageurl.strip(), "fuente": fuente}

    CACHE_IMAGENES[ean] = registro

    NUEVAS_IMAGENES.append({"ean": ean, "imageurl": imageurl.strip(), "fuente": fuente})

    print(f"    [IMAGEN NUEVA] " f"EAN {ean} → {fuente}")

    return True


def guardar_nuevas_imagenes(planilla):
    """
    Guarda en Google Sheets únicamente las imágenes nuevas
    encontradas durante esta corrida.
    """

    if not NUEVAS_IMAGENES:
        print("[IMAGENES] No hay imágenes nuevas para guardar.")
        return

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_IMAGENES)
    except gspread.exceptions.WorksheetNotFound:
        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_IMAGENES, rows=2000, cols=3)
        hoja.append_row(["ean", "imageurl", "fuente"])

    filas = [
        [item["ean"], item["imageurl"], item["fuente"]] for item in NUEVAS_IMAGENES
    ]

    hoja.append_rows(filas, value_input_option="USER_ENTERED")

    print(
        f"[IMAGENES] {len(filas)} imágenes nuevas guardadas "
        f"en '{NOMBRE_HOJA_IMAGENES}'."
    )


# -----------------------------------------------------------------------
# GOOGLE SHEETS
# -----------------------------------------------------------------------


def obtener_credenciales_google():

    credenciales_json = os.environ.get("GOOGLE_CREDENTIALS")

    if credenciales_json:
        datos = json.loads(credenciales_json)

        return Credentials.from_service_account_info(
            datos,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )

    # Ejecución local
    return Credentials.from_service_account_file(
        RUTA_CREDENCIALES,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )


def escribir_en_google_sheets(filas: list):

    creds = obtener_credenciales_google()

    cliente = gspread.authorize(creds)

    planilla = cliente.open_by_key(SPREADSHEET_ID)

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_LOG)

    except gspread.exceptions.WorksheetNotFound:

        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_LOG, rows=2000, cols=10)

        hoja.append_row(
            [
                "fecha",
                "linea",
                "producto",
                "sitio",
                "precio",
                "disponibilidad",
                "error",
                "url",
                "ean",
            ]
        )

    filas_para_subir = [
        [
            f["fecha"],
            f["linea"],
            f["producto"],
            f["sitio"],
            f["precio"],
            f["disponibilidad"],
            f["error"],
            f["url"],
            f.get("ean"),
        ]
        for f in filas
    ]

    hoja.append_rows(filas_para_subir, value_input_option="USER_ENTERED")

    print(
        f"\n{len(filas_para_subir)} filas subidas a la pestaña "
        f"'{NOMBRE_HOJA_LOG}' del Google Sheet."
    )

# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
def main():
    fecha = datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M")
    filas = []

    # -------------------------------------------------------------------
    # CARGAR IMÁGENES EXISTENTES
    # -------------------------------------------------------------------

    try:
        creds = obtener_credenciales_google()
        cliente = gspread.authorize(creds)
        planilla = cliente.open_by_key(SPREADSHEET_ID)

        CACHE_IMAGENES.update(cargar_cache_imagenes(planilla))

    except Exception as e:
        print(
            f"[AVISO] No se pudo cargar la caché de imágenes: "
            f"{type(e).__name__}: {e}"
        )
        planilla = None

    for linea in LINEAS:
        print(f"\n=== Línea: {linea['nombre']} ===")

        # --- Sitios VTEX ---
        for sitio in SITIOS_VTEX:
            print(f"  Buscando en {sitio['sitio']}...")
            termino_busqueda = linea.get("busqueda_por_sitio", {}).get(
                sitio["sitio"], linea["busqueda"]
            )
            productos, error = buscar_productos_vtex(sitio["dominio"], termino_busqueda)
            if error:
                print(f"    [ERROR] {error}")
                filas.append(
                    {
                        "fecha": fecha,
                        "linea": linea["nombre"],
                        "producto": None,
                        "sitio": sitio["sitio"],
                        "precio": None,
                        "disponibilidad": None,
                        "error": error,
                        "url": "",
                    }
                )
                continue

            if not productos:
                print("    (la API no devolvió ningún producto para este término)")
            else:
                print(f"    ({len(productos)} productos crudos de la API)")

            for prod in productos:
                if linea.get("aplicar_incluir_en_vtex") and not pasa_filtro_inclusion(
                    prod["nombre"], linea.get("incluir", [])
                ):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if ean_excluido(prod.get("ean"), sitio["sitio"]):
                    print(
                        f"    [EAN excluido] "
                        f"{prod.get('ean')} en {sitio['sitio']}: "
                        f"{prod['nombre']}"
                    )
                    continue
                if sitio["metodo_precio"] == "css" and prod["link"]:
                    resultado = obtener_precio_css(prod["link"])
                else:
                    resultado = obtener_precio_simulacion_promo_2u(
                        sitio["dominio"],
                        prod["sku_id"],
                        sitio.get("sales_channel", "1"),
                        sitio.get("postal_code"),
                    )
                    if (
                        sitio.get("fallback_css")
                        and resultado.get("disponibilidad") == "withoutStock"
                        and prod.get("link")
                    ):
                        resultado_css = obtener_precio_css(prod["link"])
                        if resultado_css.get("precio") is not None:
                            print(
                                f"    [fallback HTML] {prod['nombre']}: API daba {resultado.get('precio')}, HTML da {resultado_css['precio']}"
                            )
                            resultado = {
                                "precio": resultado_css["precio"],
                                "disponibilidad": "withoutStock (verificado en HTML)",
                            }
                fila = {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": prod["nombre"],
                    "sitio": sitio["sitio"],
                    "precio": resultado.get("precio"),
                    "disponibilidad": resultado.get("disponibilidad"),
                    "error": resultado.get("error", ""),
                    "url": prod.get("link", ""),
                    "ean": prod.get("ean"),
                }

                if prod.get("ean") and prod.get("imageurl"):
                    registrar_imagen(prod["ean"], prod["imageurl"], sitio["sitio"])
                if fila["precio"] is None:
                    print(
                        f"    [sin precio, descartado] {fila['producto']} ({fila['disponibilidad']})"
                    )
                    pausa_entre_pedidos()
                    continue
                if disponibilidad_indica_sin_stock(fila["disponibilidad"]):
                    print(
                        f"    [sin stock, descartado] {fila['producto']} ({fila['disponibilidad']})"
                    )
                    pausa_entre_pedidos()
                    continue                
                filas.append(fila)
                print(
                    f"    -> {fila['producto']}: {fila['precio']} ({fila['disponibilidad']})"
                )
                pausa_entre_pedidos()

        # --- Coto ---
        print(f"  Buscando en coto...")
        productos_coto, error = buscar_productos_coto(linea["busqueda"])
        if error:
            print(f"    [ERROR] {error}")
            filas.append(
                {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": None,
                    "sitio": "coto",
                    "precio": None,
                    "disponibilidad": None,
                    "error": error,
                    "url": "",
                }
            )
        else:
            if not productos_coto:
                print("    (la API no devolvió ningún producto para este término)")
            else:
                print(f"    ({len(productos_coto)} productos crudos de la API)")

            for prod in productos_coto:
                if not pasa_filtro_inclusion(prod["nombre"], linea.get("incluir", [])):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if ean_excluido(prod.get("ean"), sitio["sitio"]):
                    print(
                        f"    [EAN excluido] "
                        f"{prod.get('ean')} en {sitio['sitio']}: "
                        f"{prod['nombre']}"
                    )
                    continue
                fila = {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": prod["nombre"],
                    "sitio": "coto",
                    "precio": prod["precio"],
                    "disponibilidad": prod["disponibilidad"],
                    "error": "",
                    "url": prod["url"],
                    "ean": prod.get("ean"),
                }

                if prod.get("ean") and prod.get("imageurl"):
                    registrar_imagen(prod["ean"], prod["imageurl"], "coto")
                if fila["precio"] is None:
                    print(
                        f"    [sin precio, descartado] {fila['producto']} ({fila['disponibilidad']})"
                    )
                    continue
                filas.append(fila)
                print(
                    f"    -> {fila['producto']}: {fila['precio']} ({fila['disponibilidad']})"
                )

        pausa_entre_pedidos()

        # --- Paradineiro Farmacias ---
        print(f"  Buscando en paradineiro...")
        productos_paradineiro, error = buscar_productos_paradineiro(linea["busqueda"])
        if error:
            print(f"    [ERROR] {error}")
            filas.append(
                {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": None,
                    "sitio": "paradineiro",
                    "precio": None,
                    "disponibilidad": None,
                    "error": error,
                    "url": "",
                }
            )
        else:
            if not productos_paradineiro:
                print("    (la búsqueda no devolvió ningún producto para este término)")
            else:
                print(
                    f"    ({len(productos_paradineiro)} productos crudos de la búsqueda)"
                )

            for prod in productos_paradineiro:
                if not pasa_filtro_inclusion(prod["nombre"], linea.get("incluir", [])):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if ean_excluido(prod.get("ean"), sitio["sitio"]):
                    print(
                        f"    [EAN excluido] "
                        f"{prod.get('ean')} en {sitio['sitio']}: "
                        f"{prod['nombre']}"
                    )
                    continue
                fila = {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": prod["nombre"],
                    "sitio": "paradineiro",
                    "precio": prod["precio"],
                    "disponibilidad": prod["disponibilidad"],
                    "error": "",
                    "url": prod["url"],
                    "ean": prod.get("ean"), 
                }

                if prod.get("ean") and prod.get("imageurl"):
                    registrar_imagen(
                        prod["ean"],
                        prod["imageurl"],
                        "paradineiro"
                    )
                if fila["precio"] is None:
                    print(
                        f"    [sin precio, descartado] {fila['producto']} ({fila['disponibilidad']})"
                    )
                    continue
                if fila["disponibilidad"] == "sin_stock":
                    print(f"    [sin stock, descartado] {fila['producto']}")
                    continue
                filas.append(fila)
                print(
                    f"    -> {fila['producto']}: {fila['precio']} ({fila['disponibilidad']})"
                )

        pausa_entre_pedidos()

    try:
        escribir_en_google_sheets(filas)
    except Exception as e:
        print(f"\n[ERROR subiendo a Google Sheets]: {type(e).__name__}: {e}")

    try:

        if planilla is None:
            creds = obtener_credenciales_google()
            cliente = gspread.authorize(creds)
            planilla = cliente.open_by_key(SPREADSHEET_ID)

        guardar_nuevas_imagenes(planilla)

    except Exception as e:

        print(f"\n[ERROR guardando imágenes]: " f"{type(e).__name__}: {e}")

    
if __name__ == "__main__":
    main()
