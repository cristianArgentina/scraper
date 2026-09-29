"""Scraper de sitios Magento (Maxiconsumo)."""

import re

import requests
from bs4 import BeautifulSoup

from config.settings import HEADERS
from config.sitios import MAX_PAGINAS_MAGENTO, PRODUCTOS_POR_PAGINA_MAGENTO
from core.cache import CACHE_BUSQUEDA
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_ar
from imagenes import resolver_imagen
from scrapers.base import Scraper


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


class ScraperMagento(Scraper):
    pausa_tras_sitio = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.nombre = cfg["sitio"]

    def buscar(self, linea):
        return buscar_productos_magento(
            self.cfg["dominio"], self.cfg["sucursal"], self.termino(linea)
        )

    def imagen(self, prod):
        # Maxiconsumo no expone EAN, pero sí trae imagen y SKU propio en
        # el listado: se registra igual, cacheada como "sitio::sku" para
        # que quede atada a este producto de este sitio.
        return resolver_imagen(prod.get("imageurl"), prod.get("url"))
