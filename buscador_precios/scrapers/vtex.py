"""Scraper de sitios VTEX (Farmaonline, Farmacity, Carrefour, etc.)."""

from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config.settings import HEADERS, ZONA_HORARIA
from config.sitios import MAX_PAGINAS_VTEX, PRODUCTOS_POR_PAGINA_VTEX
from core.cache import CACHE_BUSQUEDA
from core.ean import limpiar_ean
from core.http import pausa_entre_pedidos, request_con_reintentos
from core.parsing import normalizar_terminos, parsear_precio_ar
from imagenes import extraer_imagen_de_datos, resolver_imagen
from scrapers.base import Scraper


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
                    resp = request_con_reintentos("GET", url, headers=HEADERS)
                    resp.raise_for_status()
                    data = resp.json()

                except Exception as e:
                    return None, (
                        f"error de búsqueda ('{termino}', " f"página {pagina + 1}): {e}"
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
                
            else:
                # el bucle terminó sin "break": la última página vino completa
                print(
                    f"    [AVISO] '{termino}': la última página vino completa; "
                    f"puede haber más productos sin traer (MAX_PAGINAS_VTEX={MAX_PAGINAS_VTEX})"
                )
                
            CACHE_BUSQUEDA[clave_cache] = productos_termino

            # Mantener la pausa que ya tenía el buscador
            # después de completar el término.
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
# PROMOCIONES PROPIAS DE LA TIENDA (ej. Vea: POST /_v/search-promotions)
#
# En Vea la simulación de compra de VTEX NO aplica promos tipo 2x1 / 2do al
# 80% (devuelve el precio de lista aunque se pidan 2 unidades). La tienda
# las calcula aparte, en este endpoint, y trae por SKU un
# "effectiveDiscount" (ej. "0.50" para un 2x1) = descuento promedio por
# unidad llevando la cantidad de la promo. Precio final = precio * (1 - d).
# Se activa con cfg["promociones"] = {"url": ..., "seller": ...}.
# -----------------------------------------------------------------------
TAMANIO_LOTE_PROMOCIONES = 10


def _promo_vigente(promo, ahora):
    """True si hoy está entre start y end. Sin fechas = vigente; con
    fechas ilegibles = no se aplica (mejor precio normal que uno falso)."""
    try:
        inicio = promo.get("start")
        fin = promo.get("end")
        if inicio and ahora < datetime.fromisoformat(inicio):
            return False
        if fin and ahora > datetime.fromisoformat(fin):
            return False
    except (ValueError, TypeError):
        return False
    return True


def consultar_promociones_tienda(dominio: str, cfg_promos: dict, skus: list):
    """Devuelve {sku: promo} con las promos VIGENTES de los SKUs pedidos.
    Si el endpoint falla, devuelve {} (se usa el precio normal)."""
    url = cfg_promos["url"]
    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Origin": f"https://{dominio}",
        "Referer": f"https://{dominio}/",
    }
    ahora = datetime.now(ZONA_HORARIA)
    resultado = {}

    for i in range(0, len(skus), TAMANIO_LOTE_PROMOCIONES):
        lote = [str(s) for s in skus[i : i + TAMANIO_LOTE_PROMOCIONES]]
        body = {"seller": cfg_promos["seller"], "skus": lote}
        try:
            resp = request_con_reintentos("POST", url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(
                f"    [AVISO] no se pudieron consultar las promos de {len(lote)} "
                f"SKU(s) {lote} ({type(e).__name__}): {e}"
            )
            continue

        # Solo "generic". "jumbo_prime" es para clientes del programa Prime.
        promos = ((data.get("promotions") or {}).get("generic") or {}).get(
            "promotions"
        ) or {}

        for sku, promo in promos.items():
            try:
                descuento = float(promo.get("effectiveDiscount"))
            except (TypeError, ValueError):
                continue
            if not (0 < descuento < 1):
                continue
            if not _promo_vigente(promo, ahora):
                continue
            resultado[str(sku)] = {
                "descuento": descuento,
                "nombre": promo.get("name") or promo.get("code") or "promo",
            }

    return resultado


class ScraperVtex(Scraper):
    pausa_por_producto = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.nombre = cfg["sitio"]

    def buscar(self, linea):
        productos, error = buscar_productos_vtex(
            self.cfg["dominio"], self.termino(linea)
        )
        if productos:
            for prod in productos:
                prod["url"] = prod.get("link", "")
        return productos, error

    def preparar(self, productos):
        """Trae las promos propias de la tienda (si el sitio las tiene
        configuradas) solo para los productos que pasaron los filtros."""
        cfg_promos = self.cfg.get("promociones")
        if not cfg_promos:
            return

        pendientes = [str(p["sku_id"]) for p in productos if "promo" not in p]
        if not pendientes:
            return

        promos = consultar_promociones_tienda(
            self.cfg["dominio"], cfg_promos, pendientes
        )
        for prod in productos:
            if "promo" not in prod:
                prod["promo"] = promos.get(str(prod["sku_id"]))

    def aplica_incluir(self, linea):
        # En VTEX el filtro 'incluir' es opcional: solo se aplica si la
        # línea lo pide explícitamente con aplicar_incluir_en_vtex.
        return bool(linea.get("aplicar_incluir_en_vtex"))

    def pre_descarte(self, prod):
        if self.cfg.get("verificar_stock_catalogo") and (
            prod.get("stock_catalogo") == 0 or prod.get("disponible_catalogo") is False
        ):
            return "sin stock en catálogo, descartado"
        return None

    def obtener_precio(self, prod):
        cfg = self.cfg

        if cfg["metodo_precio"] == "css" and prod["link"]:
            return obtener_precio_css(prod["link"])

        resultado = obtener_precio_simulacion_promo_2u(
            cfg["dominio"],
            prod["sku_id"],
            cfg.get("sales_channel", "1"),
            cfg.get("postal_code"),
        )

        if (
            cfg.get("fallback_css")
            and resultado.get("disponibilidad") == "withoutStock"
            and prod.get("link")
        ):
            resultado_css = obtener_precio_css(prod["link"])
            if resultado_css.get("precio") is not None:
                print(
                    f"    [fallback HTML] {prod['nombre']}: API daba "
                    f"{resultado.get('precio')}, HTML da {resultado_css['precio']}"
                )
                resultado = {
                    "precio": resultado_css["precio"],
                    "disponibilidad": "withoutStock (verificado en HTML)",
                }

        return self._aplicar_promo_tienda(prod, resultado)

    def _aplicar_promo_tienda(self, prod, resultado):
        """Aplica la promo propia de la tienda (ver consultar_promociones_tienda)
        solo si el producto tiene precio y stock, y la simulación de VTEX no
        aplicó ya una promo (para no descontar dos veces)."""
        promo = prod.get("promo")
        if not promo or resultado.get("precio") is None:
            return resultado

        disponibilidad = resultado.get("disponibilidad") or ""
        if disponibilidad != "available":
            return resultado  # sin stock / ya trae promo de VTEX / verificado en HTML

        nuevo = dict(resultado)
        nuevo["precio"] = round(resultado["precio"] * (1 - promo["descuento"]), 2)
        nuevo["disponibilidad"] = f"promo: {promo['nombre']}"
        return nuevo

    def imagen(self, prod):
        # resolver_imagen prueba primero la de la API/listado y, si falta
        # o está rota (404 real, pasa con algunos kits/combos de
        # Farmaonline), cae al fallback de la página de detalle.
        return resolver_imagen(prod.get("imageurl"), prod.get("url"))
