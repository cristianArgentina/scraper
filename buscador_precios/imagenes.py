"""Obtención, validación y registro de imágenes de producto (sin tocar Google Sheets)."""

import requests
from bs4 import BeautifulSoup

from config.settings import HEADERS
from core.ean import clave_imagen
from core.http import request_con_reintentos


# -----------------------------------------------------------------------
# CACHÉ DE IMÁGENES
#
# Se carga una sola vez desde Google Sheets al comenzar la ejecución.
# CLAVE -> {"imageurl": "...", "fuente": "...", "ean": "...", "sku": "..."}
#
# La CLAVE es:
#   - el EAN, cuando el producto tiene uno (caso normal); o
#   - "sitio::sku", cuando el producto NO tiene EAN (combos/kits que
#     arman algunos sitios, donde en vez de EAN hay un identificador
#     propio del sitio). Así la imagen queda atada a ESE producto de
#     ESE sitio puntual, y nunca se toma "de forma arbitraria" la
#     imagen de otro producto/sitio distinto que comparta nombre.
#
# De esta manera, si una clave ya tiene imagen, no volvemos a buscarla.
# -----------------------------------------------------------------------
CACHE_IMAGENES = {}


# Claves (EAN o "sitio::sku") que durante ESTA corrida ya fueron
# procesadas. Evita intentar obtener la misma imagen varias veces si
# el producto aparece en varios comercios/líneas.
CLAVES_IMAGEN_PROCESADAS = set()


# Nuevas imágenes que se subirán a Google Sheets al finalizar.
NUEVAS_IMAGENES = []


def es_url_imagen_valida(url):
    if not url:
        return False

    if not isinstance(url, str):
        return False

    url = url.strip()

    return url.startswith("http://") or url.startswith("https://")


def es_imagen_accesible(url):
    """
    A diferencia de es_url_imagen_valida (que solo mira el formato del
    string), esto hace una request real para confirmar que la imagen
    efectivamente carga. Hace falta porque algunos sitios (confirmado
    en Farmaonline) devuelven en su API una URL con pinta de válida
    pero que da 404 — el activo fue borrado/nunca se subió del lado
    del sitio.
    """
    if not es_url_imagen_valida(url):
        return False

    try:
        resp = request_con_reintentos(
            "HEAD", url, headers=HEADERS, max_intentos=1
        )

        if resp.status_code >= 400:
            # Algunos CDNs no responden bien a HEAD; se prueba GET.
            resp = request_con_reintentos(
                "GET", url, headers=HEADERS, max_intentos=1
            )

        return resp.status_code < 400

    except requests.RequestException:
        return False


def resolver_imagen(imageurl_api, link_detalle):
    """
    Devuelve una URL de imagen que realmente carga.

    Prioriza la que vino de la API/listado; si no hay, o está rota
    (formato válido pero 404/5xx real), prueba con la página de
    detalle del producto (obtener_imagen_de_pagina). Devuelve None si
    ninguna de las dos funciona.
    """
    if imageurl_api and es_imagen_accesible(imageurl_api):
        return imageurl_api

    if link_detalle:
        imagen_pagina = obtener_imagen_de_pagina(link_detalle)

        if imagen_pagina and es_imagen_accesible(imagen_pagina):
            return imagen_pagina

    return None


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


def obtener_imagen_de_pagina(url):
    """
    Fallback para cuando no se pudo sacar imagen del listado/API de
    búsqueda (pasa con kits/combos en VTEX, y con productos chicos
    lazy-loaded en Magento/Maxiconsumo). Pide la página de detalle del
    producto (siempre del mismo sitio de donde salió `url`) y busca la
    imagen ahí, primero por la meta "og:image" (estándar en VTEX y en
    la mayoría de temas Magento), y si no está, por el primer <img>
    que apunte a una ruta típica de imagen de producto.
    """
    if not url:
        return None

    try:
        resp = request_con_reintentos("GET", url, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    meta_img = soup.select_one('meta[property="og:image"]')

    if meta_img:
        url_imagen = meta_img.get("content")

        if es_url_imagen_valida(url_imagen):
            return url_imagen.strip()

    # Fallback: primer <img> que apunte a una ruta típica de imagen de
    # producto (Magento: /media/catalog/product/, VTEX: vtexassets.com
    # / vteximg.com.br).
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src")

        if not src:
            continue

        if any(
            patron in src
            for patron in (
                "/media/catalog/product/",
                "vtexassets.com",
                "vteximg.com.br",
            )
        ):
            if src.startswith("//"):
                src = "https:" + src

            if es_url_imagen_valida(src):
                return src.strip()

    return None


def registrar_imagen(ean, sku, imageurl, fuente):
    """
    Registra la imagen de un producto en la caché.

    - Si el producto tiene EAN, se cachea por EAN (como siempre).
    - Si NO tiene EAN pero sí un SKU propio del sitio (combos/kits),
      se cachea por "sitio::sku", usando `fuente` como sitio. Así,
      la próxima vez que aparezca ESE MISMO producto en ESE MISMO
      sitio, se reutiliza SU imagen — nunca la de otro producto u
      otro sitio.
    """

    if not es_url_imagen_valida(imageurl):
        return False

    clave = clave_imagen(ean, sku, fuente)

    if not clave:
        return False

    # Ya existe en Google Sheets.
    if clave in CACHE_IMAGENES:
        return False

    # Ya conseguimos una imagen durante esta corrida.
    if clave in CLAVES_IMAGEN_PROCESADAS:
        return False

    CLAVES_IMAGEN_PROCESADAS.add(clave)

    ean = str(ean).strip() if ean else ""
    sku = str(sku).strip() if sku else ""

    registro = {
        "imageurl": imageurl.strip(),
        "fuente": fuente,
        "ean": ean,
        "sku": sku,
    }

    CACHE_IMAGENES[clave] = registro

    NUEVAS_IMAGENES.append(
        {
            "ean": ean,
            "sku": sku,
            "sitio": fuente,
            "imageurl": imageurl.strip(),
            "fuente": fuente,
        }
    )

    if ean:
        print(f"    [IMAGEN NUEVA] EAN {ean} → {fuente}")
    else:
        print(f"    [IMAGEN NUEVA] SKU {sku} en {fuente} (sin EAN, combo/kit)")

    return True
