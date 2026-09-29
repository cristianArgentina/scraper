"""
Buscador de precios por LÍNEA DE PRODUCTO (no por SKU individual).

En vez de mantener una lista de URLs/SKUs producto por producto, este
script busca cada línea de marca (ej. "dove bond repair") en cada sitio
y descubre automáticamente todos los productos de esa línea que vende
ese sitio, con su precio final (incluyendo promos de 2x1 / llevando 2
cuando existen).

Requisitos:
    pip3 install requests beautifulsoup4 gspread google-auth --break-system-packages

Estructura:
    config/      -> líneas, sitios, exclusiones (exclusiones.json), settings
    core/        -> http, parsing, ean, filtros, cache
    imagenes.py  -> manejo de imágenes
    sheets.py    -> Google Sheets

Uso:
    python3 buscador_precios.py
"""

import re
import unicodedata
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import gspread

from config.lineas import LINEAS
from config.settings import HEADERS, SPREADSHEET_ID, ZONA_HORARIA
from config.sitios import (
    COTO_SEARCH_KEY,
    COTO_SEARCH_URL,
    MAX_PAGINAS_MAGENTO,
    MAX_PAGINAS_VTEX,
    PARADINEIRO_DOMINIO,
    PARADINEIRO_SEARCH_URL,
    PRODUCTOS_POR_PAGINA_MAGENTO,
    PRODUCTOS_POR_PAGINA_VTEX,
    SITIOS_MAGENTO,
    SITIOS_VTEX,
)
from core.cache import CACHE_BUSQUEDA
from core.ean import limpiar_ean
from core.filtros import (
    disponibilidad_indica_sin_stock,
    ean_excluido,
    incluido_por_sku_forzado,
    pasa_filtro_exclusion,
    pasa_filtro_inclusion,
    sku_excluido,
)
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_ar, parsear_precio_punto
from imagenes import (
    CACHE_IMAGENES,
    extraer_imagen_de_datos,
    registrar_imagen,
    resolver_imagen,
)
from sheets import (
    cargar_cache_imagenes,
    escribir_en_google_sheets,
    guardar_nuevas_imagenes,
    obtener_credenciales_google,
)


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

                    sellers = item.get("sellers") or []
                    seller = next(
                        (s for s in sellers if s.get("sellerDefault")),
                        sellers[0] if sellers else {},
                    )
                    oferta = seller.get("commertialOffer") or {}

                    productos_termino.append(
                        {
                            "nombre": p.get("productName", ""),
                            "sku_id": item.get("itemId"),
                            "link": p.get("link"),
                            "ean": limpiar_ean(item.get("ean")),
                            "imageurl": extraer_imagen_de_datos(item),
                            "stock_catalogo": oferta.get("AvailableQuantity"),
                            "disponible_catalogo": oferta.get("IsAvailable"),
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
                        "ean": limpiar_ean(d.get("product_main_ean")),
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

                ean = limpiar_ean(
                    buscar_ean_paradineiro(nombre, mapa_ean_paradineiro)
                )

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
# MAGENTO (Maxiconsumo)
# -----------------------------------------------------------------------

# Sesión global reutilizada entre búsquedas, para no tener que pedir
# cookies de nuevo en cada llamada. Se inicializa la primera vez que se
# necesita (una por dominio, por si en el futuro se suma otro sitio
# Magento).
_SESIONES_MAGENTO = {}


def obtener_sesion_magento(dominio: str, sucursal: str):
    if dominio in _SESIONES_MAGENTO:
        return _SESIONES_MAGENTO[dominio]

    sesion = requests.Session()
    try:
        sesion.get(f"https://{dominio}/{sucursal}/", headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"    [AVISO] no se pudo precargar cookies de {dominio}: {e}")

    _SESIONES_MAGENTO[dominio] = sesion
    return sesion


def buscar_productos_magento(dominio: str, sucursal: str, busqueda):
    """
    Busca una línea de producto en un sitio Magento (Maxiconsumo) usando
    el buscador nativo (/catalogsearch/result/). El precio final
    guardado es el de "bulto cerrado" (el que se ve en pantalla, con
    IVA), no el unitario suelto. Maxiconsumo siempre expone junto a
    ese precio un segundo monto que es el neto sin IVA (nunca se
    muestra en pantalla, precio1/precio2 = 1.21) — no es un descuento,
    así que ese segundo monto se ignora.

    IMPORTANTE: no usar el parámetro product_list_limit en esta ruta,
    rompe el sitio (da 500 - probado). Sin ese parámetro trae 12
    productos por página; paginamos con &p=N.

    No devuelve EAN (Maxiconsumo no lo expone en el listado de
    búsqueda): queda en None y el producto se identifica por su SKU
    interno de Magento.
    """
    productos_por_sku = {}

    sesion = obtener_sesion_magento(dominio, sucursal)

    for termino in normalizar_terminos(busqueda):
        clave_cache = ("magento", dominio, termino)

        if clave_cache in CACHE_BUSQUEDA:
            productos_termino = CACHE_BUSQUEDA[clave_cache]
        else:
            productos_termino = []
            termino_url = termino.replace(" ", "+")

            for pagina in range(1, MAX_PAGINAS_MAGENTO + 1):
                sufijo_pagina = f"&p={pagina}" if pagina > 1 else ""
                url = (
                    f"https://{dominio}/{sucursal}/catalogsearch/result/"
                    f"?q={termino_url}{sufijo_pagina}"
                )

                try:
                    resp = request_con_reintentos(
                        "GET", url, headers=HEADERS, cookies=sesion.cookies
                    )
                    resp.raise_for_status()
                except Exception as e:
                    return None, (
                        f"error de búsqueda ('{termino}', página {pagina}): {e}"
                    )

                soup = BeautifulSoup(resp.text, "html.parser")
                items = soup.select("li.product-item")

                if not items:
                    break

                print(
                    f"    [Magento] {termino} → página {pagina}: "
                    f"{len(items)} productos"
                )

                for li in items:
                    a_tag = (
                        li.find("a", class_="product-item-link")
                        or li.find("a", href=re.compile(r"-\d+\.html$"))
                        or li.find("a", href=True)
                    )
                    if not a_tag:
                        continue

                    nombre = a_tag.get_text(strip=True)
                    link = a_tag.get("href", "")
                    texto = li.get_text(" ", strip=True)

                    sku_match = re.search(r"\bSKU\s*(\d+)", texto, re.IGNORECASE)
                    sku_id = sku_match.group(1) if sku_match else link

                    texto_lower = texto.lower()
                    sin_stock = (
                        "agotado" in texto_lower or "sin stock" in texto_lower
                    )

                    precio_bulto = None
                    match_unitario = re.search(
                        r"Precio unitario\s*\$\s*([\d.,]+)",
                        texto,
                        re.IGNORECASE,
                    )
                    if match_unitario:
                        precio_bulto = parsear_precio_ar(match_unitario.group(1))

                    if precio_bulto is None:
                        # fallback: precio por bulto cerrado (ej. si el
                        # sitio no expone precio suelto para este producto)
                        match_bulto = re.search(
                            r"Precio unitario por bulto cerrado\s*\$\s*([\d.,]+)",
                            texto,
                            re.IGNORECASE,
                        )
                        if match_bulto:
                            precio_bulto = parsear_precio_ar(match_bulto.group(1))

                    img_tag = a_tag.find("img") or li.find("img")
                    imagen_url = None
                    if img_tag:
                        # Primero data-src (lazy-load): en la grilla de
                        # resultados, "src" suele tener un placeholder
                        # y la imagen real está en data-src. Si no hay
                        # data-src (imagen no lazy-loaded), se usa src.
                        imagen_url = img_tag.get("data-src") or img_tag.get("src")

                        if imagen_url and imagen_url.startswith("//"):
                            imagen_url = "https:" + imagen_url

                    productos_termino.append(
                        {
                            "sku_id": sku_id,
                            "nombre": nombre,
                            "precio": precio_bulto,
                            "disponibilidad": (
                                "sin_stock" if sin_stock else "available"
                            ),
                            "url": link,
                            "imageurl": imagen_url,
                            "ean": None,  # no disponible en Maxiconsumo
                        }
                    )

                if len(items) < PRODUCTOS_POR_PAGINA_MAGENTO:
                    break

                pausa_entre_pedidos()

            CACHE_BUSQUEDA[clave_cache] = productos_termino
            pausa_entre_pedidos()

        for prod in productos_termino:
            if prod["sku_id"] in productos_por_sku:
                continue
            productos_por_sku[prod["sku_id"]] = prod

    return list(productos_por_sku.values()), None


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

    if disponible != "available":
        return {"precio": None, "disponibilidad": disponible or "desconocida"}
    
    for item in items:
        precio_venta = item.get("sellingPrice")
        cantidad = item.get("quantity", 1)
        if precio_venta is None:
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
                if (
                    linea.get("aplicar_incluir_en_vtex")
                    and not pasa_filtro_inclusion(prod["nombre"], linea.get("incluir", []))
                    and not incluido_por_sku_forzado(
                        prod.get("sku_id"), sitio["sitio"], linea
                    )
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
                if sitio.get("verificar_stock_catalogo") and (
                    prod.get("stock_catalogo") == 0
                    or prod.get("disponible_catalogo") is False
                ):
                    print(f"    [sin stock en catálogo, descartado] {prod['nombre']}")
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
                    "sku": prod.get("sku_id"),
                }

                # -------------------------------------------------------
                # DESCARTES: primero se descarta, recién después (si el
                # producto sobrevivió) se registra su imagen. Así no se
                # guardan imágenes de productos sin precio ni sin stock.
                # -------------------------------------------------------
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

                # resolver_imagen prueba primero la de la API/listado y,
                # si falta o está rota (404 real, no solo el formato del
                # string — pasa con algunos kits/combos de Farmaonline),
                # cae al fallback de la página de detalle del producto.
                imagen_prod = resolver_imagen(
                    prod.get("imageurl"), prod.get("link")
                )

                if imagen_prod and (prod.get("ean") or prod.get("sku_id")):
                    registrar_imagen(
                        prod.get("ean"),
                        prod.get("sku_id"),
                        imagen_prod,
                        sitio["sitio"],
                    )

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
                if not pasa_filtro_inclusion(
                    prod["nombre"], linea.get("incluir", [])
                ) and not incluido_por_sku_forzado(prod.get("sku_id"), "coto", linea):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if ean_excluido(prod.get("ean"), "coto"):
                    print(
                        f"    [EAN excluido] "
                        f"{prod.get('ean')} en coto: "
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
                    "sku": prod.get("sku_id"),
                }

                if fila["precio"] is None:
                    print(
                        f"    [sin precio, descartado] {fila['producto']} ({fila['disponibilidad']})"
                    )
                    continue

                if prod.get("imageurl") and (prod.get("ean") or prod.get("sku_id")):
                    registrar_imagen(
                        prod.get("ean"), prod.get("sku_id"), prod["imageurl"], "coto"
                    )

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
                if not pasa_filtro_inclusion(
                    prod["nombre"], linea.get("incluir", [])
                ) and not incluido_por_sku_forzado(
                    prod.get("sku_id"), "paradineiro", linea
                ):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if ean_excluido(prod.get("ean"), "paradineiro"):
                    print(
                        f"    [EAN excluido] "
                        f"{prod.get('ean')} en paradineiro: "
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
                    "sku": prod.get("sku_id"),
                }

                if fila["precio"] is None:
                    print(
                        f"    [sin precio, descartado] {fila['producto']}"
                    )
                    continue
                if fila["disponibilidad"] == "sin_stock":
                    print(f"    [sin stock, descartado] {fila['producto']}")
                    continue

                if prod.get("imageurl") and (prod.get("ean") or prod.get("sku_id")):
                    registrar_imagen(
                        prod.get("ean"),
                        prod.get("sku_id"),
                        prod["imageurl"],
                        "paradineiro",
                    )

                filas.append(fila)
                print(
                    f"    -> {fila['producto']}: {fila['precio']} ({fila['disponibilidad']})"
                )

        pausa_entre_pedidos()

        # --- Sitios Magento (Maxiconsumo, etc.) ---
        for sitio_magento in SITIOS_MAGENTO:
            print(f"  Buscando en {sitio_magento['sitio']}...")
            productos_magento, error = buscar_productos_magento(
                sitio_magento["dominio"], sitio_magento["sucursal"], linea["busqueda"]
            )
            if error:
                print(f"    [ERROR] {error}")
                filas.append(
                    {
                        "fecha": fecha,
                        "linea": linea["nombre"],
                        "producto": None,
                        "sitio": sitio_magento["sitio"],
                        "precio": None,
                        "disponibilidad": None,
                        "error": error,
                        "url": "",
                    }
                )
                continue

            if not productos_magento:
                print("    (no se encontraron productos para este término)")
            else:
                print(f"    ({len(productos_magento)} productos crudos)")

            for prod in productos_magento:
                if not pasa_filtro_inclusion(
                    prod["nombre"], linea.get("incluir", [])
                ) and not incluido_por_sku_forzado(
                    prod.get("sku_id"), sitio_magento["sitio"], linea
                ):
                    print(f"    [filtrado por 'incluir'] {prod['nombre']}")
                    continue
                if not pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                    print(f"    [filtrado por 'excluir'] {prod['nombre']}")
                    continue
                if sku_excluido(prod.get("sku_id"), sitio_magento["sitio"]):
                    print(
                        f"    [SKU excluido] "
                        f"{prod.get('sku_id')} en {sitio_magento['sitio']}: "
                        f"{prod['nombre']}"
                    )
                    continue

                fila = {
                    "fecha": fecha,
                    "linea": linea["nombre"],
                    "producto": prod["nombre"],
                    "sitio": sitio_magento["sitio"],
                    "precio": prod["precio"],
                    "disponibilidad": prod["disponibilidad"],
                    "error": "",
                    "url": prod["url"],
                    "ean": prod.get("ean"),  # siempre None por ahora
                    "sku": prod.get("sku_id"),
                }

                if fila["precio"] is None:
                    print(f"    [sin precio, descartado] {fila['producto']}")
                    continue
                if fila["disponibilidad"] == "sin_stock":
                    print(f"    [sin stock, descartado] {fila['producto']}")
                    continue

                # Maxiconsumo no expone EAN, pero sí trae imagen y SKU
                # propio en el listado: se registra igual, cacheada
                # como "sitio::sku" para que quede atada a este mismo
                # producto de este mismo sitio.
                imagen_prod = resolver_imagen(
                    prod.get("imageurl"), prod.get("url")
                )

                if imagen_prod and prod.get("sku_id"):
                    registrar_imagen(
                        None,
                        prod.get("sku_id"),
                        imagen_prod,
                        sitio_magento["sitio"],
                    )

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
