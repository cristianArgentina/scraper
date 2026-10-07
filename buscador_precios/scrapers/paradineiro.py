"""Scraper de Paradineiro Farmacias (HTML + EAN desde createProductsListedEvent)."""

import re
import unicodedata

from bs4 import BeautifulSoup

from config.settings import HEADERS
from config.sitios import PARADINEIRO_DOMINIO, PARADINEIRO_SEARCH_URL
from core.cache import CACHE_BUSQUEDA
from core.ean import limpiar_ean
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_ar
from scrapers.base import Scraper


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


                disponibilidad = "sin_stock" if sin_stock else "available"
 
                # -----------------------------------------------------
                # PROMO 2x1
                #
                # La tarjeta muestra el precio de UNA unidad y, aparte,
                # una etiqueta "2x1" (span.promotion_label-short-title).
                # Llevando 2 se paga una: el precio por unidad es la mitad,
                # igual que en VTEX (promedio de 2 unidades) y Vea (50%).
                #
                # Solo se interpreta el patrón "NxM". Las etiquetas de
                # descuento directo ("-25%") NO se tocan: ese precio ya
                # viene con el descuento aplicado y se descontaría dos veces.
                # -----------------------------------------------------
 
                if precio is not None and not sin_stock:
                    for etiqueta in li.select(".promotion_label-short-title"):
                        texto_promo = etiqueta.get_text(strip=True)
                        m_promo = re.fullmatch(
                            r"(\d+)\s*x\s*(\d+)", texto_promo, re.IGNORECASE
                        )
                        if not m_promo:
                            continue
 
                        if (int(m_promo.group(1)), int(m_promo.group(2))) == (2, 1):
                            precio = round(precio / 2, 2)
                            disponibilidad = f"promo: {texto_promo}"
                        else:
                            # 3x2, 4x3...: exigen comprar más de 2 unidades,
                            # no se aplican (se avisa para poder revisarlo).
                            print(
                                f"[PROMO NO APLICADA] Paradineiro: "
                                f"'{texto_promo}' en {nombre}"
                            )
                        break
 

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
                        "disponibilidad": disponibilidad,
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


class ScraperParadineiro(Scraper):
    nombre = "paradineiro"
    pausa_tras_sitio = True

    def buscar(self, linea):
        return buscar_productos_paradineiro(self.termino(linea))
