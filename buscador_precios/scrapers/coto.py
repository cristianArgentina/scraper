"""Scraper de Coto (API de Constructor.io)."""

from config.settings import HEADERS
from config.sitios import COTO_SEARCH_KEY, COTO_SEARCH_URL
from core.cache import CACHE_BUSQUEDA
from core.ean import limpiar_ean
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_punto
from imagenes import extraer_imagen_de_datos
from scrapers.base import Scraper


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


class ScraperCoto(Scraper):
    nombre = "coto"
    pausa_tras_sitio = True

    def buscar(self, linea):
        return buscar_productos_coto(self.termino(linea))
