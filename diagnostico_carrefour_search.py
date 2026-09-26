#!/usr/bin/env python3

import requests
import json
import time
from urllib.parse import urlencode


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

BASE_URL = "https://www.carrefour.com.ar"

QUERY = "sedal"
SALES_CHANNEL = "1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.carrefour.com.ar/",
}


# =============================================================================
# UTILIDADES
# =============================================================================

def imprimir_separador(char="=", largo=80):
    print(char * largo)


def hacer_request(url, params=None, descripcion=""):
    print()
    imprimir_separador("-")
    print(f"REQUEST: {descripcion}")
    print(f"URL BASE: {url}")

    if params:
        print("PARAMETROS:")
        for k, v in params.items():
            print(f"  {k} = {v}")

    try:
        r = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=30,
        )

        print(f"HTTP: {r.status_code}")
        print(f"URL FINAL:")
        print(r.url)

        print("HEADERS RELEVANTES:")

        for h in [
            "resources",
            "cache-control",
            "content-type",
            "x-vtex-cache",
            "x-vtex-io-cluster-id",
        ]:
            if h in r.headers:
                print(f"  {h}: {r.headers[h]}")

        if not r.ok:
            print()
            print("RESPUESTA DE ERROR:")
            print(r.text[:3000])
            return None

        try:
            data = r.json()
        except Exception:
            print("La respuesta no es JSON.")
            print(r.text[:3000])
            return None

        return data

    except Exception as e:
        print(f"ERROR REQUEST: {type(e).__name__}: {e}")
        return None


def buscar_lista_productos(data):
    """
    Intenta encontrar la lista de productos en las distintas
    estructuras que podemos recibir de las APIs de VTEX.
    """

    if not isinstance(data, dict):
        return []

    # Estructura Intelligent Search
    if isinstance(data.get("products"), list):
        return data["products"]

    # Algunas respuestas pueden tener products dentro de otra estructura
    for key in ["data", "search", "result"]:
        value = data.get(key)

        if isinstance(value, dict):
            if isinstance(value.get("products"), list):
                return value["products"]

            if isinstance(value.get("items"), list):
                return value["items"]

    # Legacy
    if isinstance(data.get("items"), list):
        return data["items"]

    return []


def extraer_total(data, headers=None):
    """
    Busca el total informado por la API.
    """

    if headers:
        resources = headers.get("resources")
        if resources:
            try:
                # ejemplo: 0-49/99
                if "/" in resources:
                    return int(resources.split("/")[-1])
            except Exception:
                pass

    if isinstance(data, dict):

        for key in [
            "recordsFiltered",
            "records",
            "total",
            "totalCount",
            "count",
        ]:
            value = data.get(key)

            if isinstance(value, int):
                return value

        # algunas estructuras
        for key in ["pagination", "paging"]:
            obj = data.get(key)

            if isinstance(obj, dict):
                for k in ["total", "totalCount", "count"]:
                    if isinstance(obj.get(k), int):
                        return obj[k]

    return None


def extraer_nombre(producto):
    if not isinstance(producto, dict):
        return ""

    return (
        producto.get("productName")
        or producto.get("name")
        or producto.get("productNameComplete")
        or ""
    )


def extraer_product_id(producto):
    if not isinstance(producto, dict):
        return ""

    return (
        producto.get("productId")
        or producto.get("id")
        or ""
    )


def extraer_slug(producto):
    if not isinstance(producto, dict):
        return ""

    return (
        producto.get("linkText")
        or producto.get("slug")
        or ""
    )


def extraer_items(producto):
    if not isinstance(producto, dict):
        return []

    items = producto.get("items")

    if isinstance(items, list):
        return items

    return []


def imprimir_productos(productos, limite=100):
    print()
    imprimir_separador("-")
    print(f"PRODUCTOS RECIBIDOS: {len(productos)}")
    imprimir_separador("-")

    for i, producto in enumerate(productos[:limite], 1):

        nombre = extraer_nombre(producto)
        product_id = extraer_product_id(producto)
        slug = extraer_slug(producto)

        print()
        print(f"[{i}] {nombre}")
        print(f"    productId: {product_id}")
        print(f"    slug:      {slug}")

        items = extraer_items(producto)

        if items:
            print(f"    items:     {len(items)}")

            for item in items[:10]:

                item_id = item.get("itemId", "")
                ean = item.get("ean", "")

                print(
                    f"       SKU={item_id} "
                    f"EAN={ean}"
                )

                sellers = item.get("sellers", [])

                for seller in sellers[:10]:

                    seller_id = seller.get("sellerId", "")

                    offer = seller.get(
                        "commertialOffer",
                        {}
                    )

                    if not isinstance(offer, dict):
                        offer = {}

                    available = offer.get(
                        "AvailableQuantity"
                    )

                    is_available = offer.get(
                        "IsAvailable"
                    )

                    price = offer.get("Price")

                    print(
                        f"          seller={seller_id} "
                        f"available={available} "
                        f"IsAvailable={is_available} "
                        f"price={price}"
                    )

        else:
            # Para no perder información si Intelligent Search
            # devuelve otra estructura de SKU.
            print("    items: NO ENCONTRADOS")

    if len(productos) > limite:
        print()
        print(
            f"... se muestran {limite} de "
            f"{len(productos)} productos."
        )


# =============================================================================
# PRUEBA 1
# LEGACY CATALOG SEARCH
# =============================================================================

def prueba_legacy():

    url = (
        f"{BASE_URL}/api/catalog_system/"
        f"pub/products/search"
    )

    params = {
        "_from": 0,
        "_to": 49,
        "ft": QUERY,
    }

    data = hacer_request(
        url,
        params,
        "LEGACY - búsqueda simple"
    )

    if data is not None:
        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos recibidos: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 2
# LEGACY + isAvailablePerSalesChannel
# =============================================================================

def prueba_legacy_disponibilidad():

    url = (
        f"{BASE_URL}/api/catalog_system/"
        f"pub/products/search"
    )

    params = {
        "_from": 0,
        "_to": 49,
        "ft": QUERY,
        f"fq": f"isAvailablePerSalesChannel_{SALES_CHANNEL}:1",
    }

    data = hacer_request(
        url,
        params,
        "LEGACY - disponibilidad por sales channel"
    )

    if data is not None:

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos recibidos: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 3
# INTELLIGENT SEARCH V1
#
# query como parámetro
# =============================================================================

def prueba_intelligent_v1_query():

    url = (
        f"{BASE_URL}/api/intelligent-search/"
        f"v1/product-search"
    )

    params = {
        "query": QUERY,
        "sc": SALES_CHANNEL,
        "hideUnavailableItems": "true",
    }

    data = hacer_request(
        url,
        params,
        "INTELLIGENT SEARCH V1 - query + hideUnavailableItems"
    )

    if data is not None:

        print()
        print("ESTRUCTURA PRINCIPAL DE RESPUESTA:")

        if isinstance(data, dict):
            print(
                "Claves:",
                ", ".join(str(k) for k in data.keys())
            )

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos encontrados: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 4
# INTELLIGENT SEARCH V1
#
# fullText como parámetro
# =============================================================================

def prueba_intelligent_v1_fulltext():

    url = (
        f"{BASE_URL}/api/intelligent-search/"
        f"v1/product-search"
    )

    params = {
        "fullText": QUERY,
        "sc": SALES_CHANNEL,
        "hideUnavailableItems": "true",
    }

    data = hacer_request(
        url,
        params,
        "INTELLIGENT SEARCH V1 - fullText + hideUnavailableItems"
    )

    if data is not None:

        print()
        print("ESTRUCTURA PRINCIPAL DE RESPUESTA:")

        if isinstance(data, dict):
            print(
                "Claves:",
                ", ".join(str(k) for k in data.keys())
            )

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos encontrados: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 5
# INTELLIGENT SEARCH V1
#
# query + sc sin hideUnavailableItems
# =============================================================================

def prueba_intelligent_v1_sin_filtro():

    url = (
        f"{BASE_URL}/api/intelligent-search/"
        f"v1/product-search"
    )

    params = {
        "query": QUERY,
        "sc": SALES_CHANNEL,
    }

    data = hacer_request(
        url,
        params,
        "INTELLIGENT SEARCH V1 - query SIN filtro de disponibilidad"
    )

    if data is not None:

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos encontrados: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 6
# INTELLIGENT SEARCH V1
#
# hideUnavailableItems=false
# =============================================================================

def prueba_intelligent_v1_false():

    url = (
        f"{BASE_URL}/api/intelligent-search/"
        f"v1/product-search"
    )

    params = {
        "query": QUERY,
        "sc": SALES_CHANNEL,
        "hideUnavailableItems": "false",
    }

    data = hacer_request(
        url,
        params,
        "INTELLIGENT SEARCH V1 - hideUnavailableItems=false"
    )

    if data is not None:

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos encontrados: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# PRUEBA 7
# INTELLIGENT SEARCH V1
#
# URL con facet query
#
# La API v1 utiliza product-search/{facets}.
# Probamos la forma de full-text de VTEX.
# =============================================================================

def prueba_intelligent_v1_facets():

    # La forma más simple es dejar facets vacío
    # y pasar el texto por query.
    #
    # También imprimimos la URL para comprobar
    # exactamente qué está aceptando Carrefour.

    url = (
        f"{BASE_URL}/api/intelligent-search/"
        f"v1/product-search/"
    )

    params = {
        "query": QUERY,
        "sc": SALES_CHANNEL,
        "hideUnavailableItems": "true",
    }

    data = hacer_request(
        url,
        params,
        "INTELLIGENT SEARCH V1 - ruta /product-search/ + filtro"
    )

    if data is not None:

        productos = buscar_lista_productos(data)

        print()
        print("RESULTADO:")
        print(f"Productos encontrados: {len(productos)}")

        imprimir_productos(productos)


# =============================================================================
# RESUMEN COMPARATIVO
# =============================================================================

def obtener_total_resources(url, params):

    try:

        r = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=30,
        )

        resources = r.headers.get("resources")

        if resources and "/" in resources:

            try:
                return int(
                    resources.split("/")[-1]
                )
            except Exception:
                pass

        return None

    except Exception:
        return None


def resumen():

    print()
    imprimir_separador("=")
    print("RESUMEN COMPARATIVO")
    imprimir_separador("=")

    pruebas = [

        (
            "Legacy",
            f"{BASE_URL}/api/catalog_system/pub/products/search",
            {
                "_from": 0,
                "_to": 49,
                "ft": QUERY,
            },
        ),

        (
            "Legacy + disponibilidad",
            f"{BASE_URL}/api/catalog_system/pub/products/search",
            {
                "_from": 0,
                "_to": 49,
                "ft": QUERY,
                "fq":
                    f"isAvailablePerSalesChannel_"
                    f"{SALES_CHANNEL}:1",
            },
        ),

        (
            "Intelligent v1 + hide=true",
            f"{BASE_URL}/api/intelligent-search/v1/product-search",
            {
                "query": QUERY,
                "sc": SALES_CHANNEL,
                "hideUnavailableItems": "true",
            },
        ),

        (
            "Intelligent v1 sin hide",
            f"{BASE_URL}/api/intelligent-search/v1/product-search",
            {
                "query": QUERY,
                "sc": SALES_CHANNEL,
            },
        ),

        (
            "Intelligent v1 + hide=false",
            f"{BASE_URL}/api/intelligent-search/v1/product-search",
            {
                "query": QUERY,
                "sc": SALES_CHANNEL,
                "hideUnavailableItems": "false",
            },
        ),
    ]

    print()
    print(
        f"{'PRUEBA':40} {'HTTP':8} {'TOTAL':10}"
    )
    print("-" * 65)

    for nombre, url, params in pruebas:

        try:

            r = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=30,
            )

            total = obtener_total_resources(
                url,
                params
            )

            if total is None:

                try:
                    data = r.json()
                    productos = buscar_lista_productos(data)

                    if isinstance(data, dict):
                        total = (
                            data.get("recordsFiltered")
                            or data.get("total")
                            or data.get("totalCount")
                            or len(productos)
                        )

                except Exception:
                    total = "?"

            print(
                f"{nombre:40} "
                f"{r.status_code:<8} "
                f"{str(total):<10}"
            )

        except Exception as e:

            print(
                f"{nombre:40} ERROR    {e}"
            )

    print()
    print("OBJETIVO OBSERVADO MANUALMENTE EN CARREFOUR: ~70/71")
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():

    imprimir_separador("=")
    print("DIAGNÓSTICO CARREFOUR - BÚSQUEDA VTEX")
    imprimir_separador("=")

    print()
    print("Este programa:")
    print("  - NO modifica Google Sheets")
    print("  - NO genera archivos")
    print("  - NO guarda JSON")
    print("  - NO consulta producto por producto")
    print("  - consulta directamente los endpoints de búsqueda")
    print()
    print(f"Consulta:       {QUERY}")
    print(f"Sales channel:  {SALES_CHANNEL}")
    print()
    print(
        "Objetivo: encontrar qué endpoint/filtro reproduce "
        "los ~70/71 productos que muestra Carrefour."
    )

    # -------------------------------------------------------------------------
    # Ejecutamos las pruebas
    # -------------------------------------------------------------------------

    prueba_legacy()

    time.sleep(1)

    prueba_legacy_disponibilidad()

    time.sleep(1)

    prueba_intelligent_v1_sin_filtro()

    time.sleep(1)

    prueba_intelligent_v1_query()

    time.sleep(1)

    prueba_intelligent_v1_fulltext()

    time.sleep(1)

    prueba_intelligent_v1_false()

    time.sleep(1)

    prueba_intelligent_v1_facets()

    # -------------------------------------------------------------------------
    # Resumen
    # -------------------------------------------------------------------------

    resumen()

    imprimir_separador("=")
    print("DIAGNÓSTICO TERMINADO")
    imprimir_separador("=")

    print()
    print("Pegame TODA la salida desde:")
    print("  DIAGNÓSTICO CARREFOUR - BÚSQUEDA VTEX")
    print()
    print("Especialmente:")
    print("  1. HTTP de cada prueba")
    print("  2. TOTAL")
    print("  3. claves de la respuesta Intelligent Search")
    print("  4. primeros productos")
    print("  5. RESUMEN COMPARATIVO")


if __name__ == "__main__":
    main()