"""Scraper de sitios PrestaShop (Maxidescuento, y cualquier otro PrestaShop 1.7).

El listado de búsqueda (/busqueda?controller=search&s=TÉRMINO) ya trae todo lo
necesario por producto, así que no hace falta un pedido por producto:

    article.product-miniature[data-id-product]   -> SKU interno
      meta[itemprop=gtin13]   "EAN Code:7791293045658"  -> EAN
      meta[itemprop=image]    imagen grande (URL absoluta)
      a.product-thumbnail     -> link a la ficha
      h3.product-title        -> nombre
      span.price[itemprop=price]  (atributo content) -> precio FINAL, ya con
                                  el descuento aplicado, sin separadores
      span.regular-price      -> precio de lista tachado (solo si hay oferta)
      span.discount-percentage / .product-flag.discount -> "-30%"
      link[itemprop=availability] -> InStock cuando hay stock

Producto SIN stock: el listado lo muestra igual, pero sin bloque de precio ni
availability (en la ficha: quantity 0, show_price "0"). Se devuelve con
precio None y disponibilidad "sin_stock"; el pipeline lo descarta.

Paginación: &page=N. Hay más páginas mientras exista el enlace "Siguiente"
(a.next / rel=next). Cada página trae hasta 54 productos.

El precio ya incluye todo (price_tax_exc == price_amount en las fichas
revisadas) y no hay descuentos por cantidad (quantity_discounts vacío), así
que no se simula compra de 2 unidades como en VTEX.
"""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from config.settings import HEADERS
from config.sitios import MAX_PAGINAS_PRESTASHOP
from core.cache import CACHE_BUSQUEDA
from core.ean import limpiar_ean
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_ar
from scrapers.base import Scraper

# HEADERS trae Accept/Content-Type de JSON (pensados para las APIs de VTEX).
# Acá se pide una página HTML: sin "Accept: application/json" para que
# PrestaShop no responda en formato AJAX.
HEADERS_HTML = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}


def _texto(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _meta(art, propiedad):
    tag = art.select_one(f'meta[itemprop="{propiedad}"]')
    return (tag.get("content") or "").strip() if tag else ""


def _limpiar_ean_gtin(valor):
    """'EAN Code:7791293045658' -> '7791293045658' (o None si no hay)."""
    return limpiar_ean(re.sub(r"\D", "", valor or ""))


def _precio_final(art):
    """Precio final como float, o None si el producto no muestra precio."""
    span = art.select_one('.product-price-and-shipping span.price[itemprop="price"]')
    if span is None:
        return None

    # Atributo content = número limpio ("13830"); es lo más confiable.
    contenido = (span.get("content") or "").strip()
    try:
        return float(contenido)
    except ValueError:
        pass

    # Respaldo: el texto visible ("$ 13.830,00", formato argentino).
    return parsear_precio_ar(_texto(span))


def parsear_listado_prestashop(html, base_url):
    """Devuelve (productos, hay_pagina_siguiente) de una página de resultados."""
    soup = BeautifulSoup(html, "html.parser")
    productos = []

    for art in soup.select("article.product-miniature"):
        sku_id = (art.get("data-id-product") or _meta(art, "sku")).strip()

        enlace = art.select_one("a.product-thumbnail") or art.select_one(
            ".product-title a"
        )
        titulo = art.select_one(".product-title")
        if not sku_id or enlace is None or titulo is None:
            continue

        url = enlace.get("href", "").strip()
        if url.startswith("/"):
            url = base_url + url

        precio = _precio_final(art)
        hay_stock = precio is not None and art.select_one(
            'link[itemprop="availability"][href*="InStock"]'
        ) is not None

        # Oferta: aparece el precio de lista tachado además del final.
        precio_lista = art.select_one(".regular-price")
        descuento = art.select_one(".discount-percentage")

        if not hay_stock:
            disponibilidad = "sin_stock"
            precio = None
        elif precio_lista is not None:
            texto_desc = _texto(descuento)
            disponibilidad = f"promo: {texto_desc}" if texto_desc else "promo: oferta"
        else:
            disponibilidad = "available"

        imagen = _meta(art, "image")
        if not imagen:
            img = art.select_one("img")
            imagen = (img.get("data-full-size-image-url") or img.get("data-src") or "").strip() if img else ""

        productos.append(
            {
                "sku_id": sku_id,
                "nombre": _texto(titulo),
                "precio": precio,
                "disponibilidad": disponibilidad,
                "url": url,
                "imageurl": imagen or None,
                "ean": _limpiar_ean_gtin(_meta(art, "gtin13")),
            }
        )

    siguiente = soup.select_one("nav.pagination a.next, nav.pagination a[rel=next]")
    hay_siguiente = siguiente is not None and "disabled" not in (
        siguiente.get("class") or []
    )
    return productos, hay_siguiente


def buscar_productos_prestashop(dominio, ruta_busqueda, busqueda):
    """Busca una línea (uno o varios términos) en un PrestaShop y devuelve
    (productos, error), sin duplicados por SKU. Usa CACHE_BUSQUEDA."""
    base_url = f"https://{dominio}"
    productos_por_sku = {}

    for termino in normalizar_terminos(busqueda):
        clave_cache = ("prestashop", dominio, termino)

        if clave_cache in CACHE_BUSQUEDA:
            productos_termino = CACHE_BUSQUEDA[clave_cache]
        else:
            productos_termino = []
            # Las líneas usan guiones para las URLs de VTEX ("dove-bond-repair");
            # el buscador de PrestaShop espera palabras separadas.
            consulta = quote_plus(termino.replace("-", " "))

            for pagina in range(1, MAX_PAGINAS_PRESTASHOP + 1):
                url = f"{base_url}{ruta_busqueda}?controller=search&s={consulta}"
                if pagina > 1:
                    url += f"&page={pagina}"

                try:
                    resp = request_con_reintentos("GET", url, headers=HEADERS_HTML)
                    resp.raise_for_status()
                except Exception as e:
                    return None, (
                        f"error de búsqueda ('{termino}', página {pagina}): {e}"
                    )

                items, hay_siguiente = parsear_listado_prestashop(resp.text, base_url)

                if not items:
                    break

                print(
                    f"    [PrestaShop] {termino} → página {pagina}: "
                    f"{len(items)} productos"
                )
                productos_termino.extend(items)

                if not hay_siguiente:
                    break

                pausa_entre_pedidos()

            CACHE_BUSQUEDA[clave_cache] = productos_termino
            pausa_entre_pedidos()

        for prod in productos_termino:
            if prod["sku_id"] in productos_por_sku:
                continue
            productos_por_sku[prod["sku_id"]] = prod

    return list(productos_por_sku.values()), None


class ScraperPrestashop(Scraper):
    pausa_tras_sitio = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.nombre = cfg["sitio"]

    def buscar(self, linea):
        return buscar_productos_prestashop(
            self.cfg["dominio"],
            self.cfg.get("ruta_busqueda", "/busqueda"),
            self.termino(linea),
        )
