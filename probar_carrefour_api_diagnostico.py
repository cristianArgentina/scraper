#!/usr/bin/env python3

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

import requests


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_URL = "https://www.carrefour.com.ar"

SEARCH_URL = (
    f"{BASE_URL}/api/catalog_system/pub/products/search"
)

BUSQUEDA = "sedal"

SALES_CHANNEL = 1

PAGE_SIZE = 50

TIMEOUT = 30

OUTPUT_DIR = Path(".")


# ============================================================
# SESIÓN HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": BASE_URL + "/",
})


# ============================================================
# UTILIDADES
# ============================================================

def imprimir_titulo(texto):
    print()
    print("=" * 100)
    print(texto)
    print("=" * 100)


def imprimir_subtitulo(texto):
    print()
    print("-" * 100)
    print(texto)
    print("-" * 100)


def guardar_json(nombre, datos):
    ruta = OUTPUT_DIR / nombre

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(
            datos,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"Guardado: {ruta}")


def normalizar_texto(valor):
    if valor is None:
        return ""

    if isinstance(valor, str):
        return valor.strip()

    return str(valor)


def obtener_recursos(response):
    """
    VTEX suele devolver:
        resources: 0-49/99

    Devuelve:
        inicio, fin, total
    """

    resources = response.headers.get("resources", "")

    match = re.search(
        r"(\d+)-(\d+)/(\d+)",
        resources
    )

    if not match:
        return None, None, None

    inicio = int(match.group(1))
    fin = int(match.group(2))
    total = int(match.group(3))

    return inicio, fin, total


def hacer_request(params, descripcion=""):
    print()
    print(f"REQUEST: {descripcion}")

    print("PARAMETROS:")

    for clave, valor in params.items():
        print(f"  {clave} = {valor}")

    try:
        response = session.get(
            SEARCH_URL,
            params=params,
            timeout=TIMEOUT
        )

    except requests.RequestException as e:
        print(f"ERROR HTTP: {e}")
        return None, None

    print(f"URL FINAL:")
    print(response.url)

    print(f"HTTP: {response.status_code}")

    resources = response.headers.get("resources")

    if resources:
        print(f"resources: {resources}")

    cache_control = response.headers.get("cache-control")

    if cache_control:
        print(f"cache-control: {cache_control}")

    if response.status_code >= 400:

        print("RESPUESTA DE ERROR:")

        try:
            print(response.text[:2000])
        except Exception:
            pass

        return response, None

    try:
        data = response.json()

    except Exception as e:

        print(f"ERROR JSON: {e}")

        print(response.text[:1000])

        return response, None

    print(f"PRODUCTOS RECIBIDOS: {len(data)}")

    return response, data


# ============================================================
# LIMPIEZA DE CAMPOS MUY GRANDES / SENSIBLES
# ============================================================

def limpiar_para_diagnostico(obj, clave_actual=""):
    """
    Mantiene prácticamente toda la estructura pero evita
    guardar tokens gigantes e innecesarios.
    """

    if isinstance(obj, dict):

        resultado = {}

        for clave, valor in obj.items():

            clave_lower = clave.lower()

            # Evitamos guardar tokens de precio completos.
            if clave_lower in {
                "pricetoken",
                "token"
            }:
                if valor:
                    resultado[clave] = "[OCULTO_PARA_DIAGNOSTICO]"
                else:
                    resultado[clave] = valor

            else:
                resultado[clave] = limpiar_para_diagnostico(
                    valor,
                    clave
                )

        return resultado

    if isinstance(obj, list):

        return [
            limpiar_para_diagnostico(
                item,
                clave_actual
            )
            for item in obj
        ]

    return obj


# ============================================================
# EXTRACCIÓN DE CAMPOS DE DISPONIBILIDAD
# ============================================================

PALABRAS_DISPONIBILIDAD = (
    "stock",
    "available",
    "availability",
    "quantity",
    "inventory",
    "supply",
    "saleschannel",
    "delivery",
    "fulfillment",
)


def contiene_nombre_disponibilidad(nombre):
    nombre_lower = str(nombre).lower()

    return any(
        palabra in nombre_lower
        for palabra in PALABRAS_DISPONIBILIDAD
    )


def extraer_campos_recursivos(
    objeto,
    ruta="",
    resultado=None
):
    """
    Busca recursivamente TODOS los campos cuyo nombre
    parezca relacionado con disponibilidad/stock.
    """

    if resultado is None:
        resultado = {}

    if isinstance(objeto, dict):

        for clave, valor in objeto.items():

            nueva_ruta = (
                f"{ruta}.{clave}"
                if ruta
                else clave
            )

            if contiene_nombre_disponibilidad(clave):

                resultado[nueva_ruta] = valor

            extraer_campos_recursivos(
                valor,
                nueva_ruta,
                resultado
            )

    elif isinstance(objeto, list):

        for i, item in enumerate(objeto):

            nueva_ruta = f"{ruta}[{i}]"

            extraer_campos_recursivos(
                item,
                nueva_ruta,
                resultado
            )

    return resultado


# ============================================================
# INFORMACIÓN RESUMIDA DE UN PRODUCTO
# ============================================================

def resumir_producto(producto):

    resumen = {
        "productId": producto.get("productId"),
        "productName": producto.get("productName"),
        "brand": producto.get("brand"),
        "brandId": producto.get("brandId"),
        "linkText": producto.get("linkText"),
        "link": producto.get("link"),
        "categories": producto.get("categories"),
        "categoryId": producto.get("categoryId"),
        "items": [],
        "availability_fields": {},
    }

    items = producto.get("items") or []

    for item in items:

        item_resumen = {
            "itemId": item.get("itemId"),
            "name": item.get("name"),
            "nameComplete": item.get("nameComplete"),
            "ean": item.get("ean"),
            "referenceId": item.get("referenceId"),
            "measurementUnit": item.get("measurementUnit"),
            "unitMultiplier": item.get("unitMultiplier"),
            "isKit": item.get("isKit"),
            "images": [],
            "sellers": [],
            "availability_fields": {},
        }

        # ----------------------------------------------------
        # IMÁGENES
        # ----------------------------------------------------

        for image in item.get("images") or []:

            item_resumen["images"].append({
                "imageId": image.get("imageId"),
                "imageUrl": image.get("imageUrl"),
                "imageText": image.get("imageText"),
                "imageLastModified": image.get(
                    "imageLastModified"
                ),
            })

        # ----------------------------------------------------
        # SELLERS
        # ----------------------------------------------------

        for seller in item.get("sellers") or []:

            oferta = seller.get(
                "commertialOffer"
            ) or {}

            seller_resumen = {
                "sellerId": seller.get("sellerId"),
                "sellerName": seller.get("sellerName"),

                "commertialOffer": {
                    "Price": oferta.get("Price"),
                    "ListPrice": oferta.get("ListPrice"),
                    "PriceWithoutDiscount": oferta.get(
                        "PriceWithoutDiscount"
                    ),
                    "FullSellingPrice": oferta.get(
                        "FullSellingPrice"
                    ),
                    "AvailableQuantity": oferta.get(
                        "AvailableQuantity"
                    ),
                    "IsAvailable": oferta.get(
                        "IsAvailable"
                    ),
                    "RewardValue": oferta.get(
                        "RewardValue"
                    ),
                    "Tax": oferta.get(
                        "Tax"
                    ),
                    "PriceValidUntil": oferta.get(
                        "PriceValidUntil"
                    ),
                    "GetInfoErrorMessage": oferta.get(
                        "GetInfoErrorMessage"
                    ),
                    "DeliverySlaSamples": oferta.get(
                        "DeliverySlaSamples"
                    ),
                    "DeliverySlaSamplesPerRegion": oferta.get(
                        "DeliverySlaSamplesPerRegion"
                    ),
                },

                "availability_fields": (
                    extraer_campos_recursivos(
                        seller
                    )
                ),
            }

            item_resumen["sellers"].append(
                seller_resumen
            )

        item_resumen["availability_fields"] = (
            extraer_campos_recursivos(item)
        )

        resumen["items"].append(
            item_resumen
        )

    resumen["availability_fields"] = (
        extraer_campos_recursivos(producto)
    )

    return resumen


# ============================================================
# BUSCAR TODAS LAS PÁGINAS
# ============================================================

def buscar_todos(params_base, descripcion):

    imprimir_titulo(
        f"RECORRIDO COMPLETO: {descripcion}"
    )

    resultados = []

    offset = 0

    total_esperado = None

    pagina = 0

    while True:

        pagina += 1

        params = dict(params_base)

        params["_from"] = offset
        params["_to"] = offset + PAGE_SIZE - 1

        print()
        print(
            f"Página {pagina}: "
            f"_from={offset} "
            f"_to={offset + PAGE_SIZE - 1}"
        )

        response, data = hacer_request(
            params,
            descripcion
        )

        if response is None:
            break

        if data is None:
            break

        inicio, fin, total = obtener_recursos(
            response
        )

        if total is not None:

            if total_esperado is None:
                total_esperado = total

            print(
                f"Total informado por VTEX: {total}"
            )

        if not data:
            print(
                "No llegaron más productos."
            )
            break

        resultados.extend(data)

        print(
            f"Acumulados: {len(resultados)}"
        )

        if total_esperado is not None:

            if len(resultados) >= total_esperado:
                break

        if len(data) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

        time.sleep(0.5)

    print()
    print(
        f"TOTAL FINAL RECIBIDO: {len(resultados)}"
    )

    if total_esperado is not None:
        print(
            f"TOTAL QUE INFORMÓ VTEX: "
            f"{total_esperado}"
        )

    return resultados, total_esperado


# ============================================================
# ESTADÍSTICAS DE DISPONIBILIDAD
# ============================================================

def analizar_disponibilidad(productos):

    imprimir_titulo(
        "ANÁLISIS DE DISPONIBILIDAD / STOCK"
    )

    estadisticas = Counter()

    detalle = []

    for producto in productos:

        for item in producto.get("items") or []:

            ean = item.get("ean")

            nombre = (
                item.get("name")
                or item.get("nameComplete")
                or producto.get("productName")
            )

            for seller in item.get("sellers") or []:

                seller_id = seller.get(
                    "sellerId"
                )

                seller_name = seller.get(
                    "sellerName"
                )

                oferta = (
                    seller.get(
                        "commertialOffer"
                    )
                    or {}
                )

                price = oferta.get(
                    "Price"
                )

                available_quantity = oferta.get(
                    "AvailableQuantity"
                )

                is_available = oferta.get(
                    "IsAvailable"
                )

                delivery = oferta.get(
                    "DeliverySlaSamples"
                )

                # --------------------------------------------
                # CLASIFICACIONES
                # --------------------------------------------

                if is_available is True:
                    estadisticas[
                        "IsAvailable=true"
                    ] += 1

                elif is_available is False:
                    estadisticas[
                        "IsAvailable=false"
                    ] += 1

                else:
                    estadisticas[
                        "IsAvailable=null_o_ausente"
                    ] += 1

                if isinstance(
                    available_quantity,
                    (int, float)
                ):

                    if available_quantity > 0:
                        estadisticas[
                            "AvailableQuantity>0"
                        ] += 1

                    elif available_quantity == 0:
                        estadisticas[
                            "AvailableQuantity=0"
                        ] += 1

                    else:
                        estadisticas[
                            "AvailableQuantity<0"
                        ] += 1

                else:
                    estadisticas[
                        "AvailableQuantity=no_numerico"
                    ] += 1

                # --------------------------------------------
                # COMPARACIONES
                # --------------------------------------------

                if (
                    is_available is True
                    and isinstance(
                        available_quantity,
                        (int, float)
                    )
                    and available_quantity > 0
                ):
                    estadisticas[
                        "COHERENTE_disponible_y_stock"
                    ] += 1

                if (
                    is_available is False
                    and isinstance(
                        available_quantity,
                        (int, float)
                    )
                    and available_quantity > 0
                ):
                    estadisticas[
                        "CONTRADICCION_false_pero_stock"
                    ] += 1

                if (
                    is_available is True
                    and isinstance(
                        available_quantity,
                        (int, float)
                    )
                    and available_quantity == 0
                ):
                    estadisticas[
                        "CONTRADICCION_true_sin_stock"
                    ] += 1

                if delivery:
                    estadisticas[
                        "Tiene_DeliverySlaSamples"
                    ] += 1
                else:
                    estadisticas[
                        "Sin_DeliverySlaSamples"
                    ] += 1

                detalle.append({
                    "productId": producto.get(
                        "productId"
                    ),
                    "productName": producto.get(
                        "productName"
                    ),
                    "itemId": item.get(
                        "itemId"
                    ),
                    "itemName": nombre,
                    "ean": ean,
                    "sellerId": seller_id,
                    "sellerName": seller_name,
                    "Price": price,
                    "AvailableQuantity": (
                        available_quantity
                    ),
                    "IsAvailable": is_available,
                    "DeliverySlaSamples": delivery,

                    "availability_fields": (
                        extraer_campos_recursivos(
                            seller
                        )
                    ),
                })

    print()

    for clave, valor in estadisticas.items():
        print(
            f"{clave:<45} {valor}"
        )

    return estadisticas, detalle


# ============================================================
# DETECTAR CAMPOS DE DISPONIBILIDAD NO ESPERADOS
# ============================================================

def analizar_nombres_de_campos(productos):

    imprimir_titulo(
        "TODOS LOS CAMPOS RELACIONADOS CON STOCK / DISPONIBILIDAD"
    )

    contador = Counter()

    ejemplos = {}

    for producto in productos:

        campos = extraer_campos_recursivos(
            producto
        )

        for ruta, valor in campos.items():

            contador[ruta] += 1

            if ruta not in ejemplos:
                ejemplos[ruta] = valor

    for ruta, cantidad in contador.most_common():

        print()
        print(
            f"{cantidad:>5} x {ruta}"
        )

        valor = ejemplos.get(ruta)

        try:
            valor_texto = json.dumps(
                valor,
                ensure_ascii=False
            )

        except Exception:
            valor_texto = str(valor)

        if len(valor_texto) > 500:
            valor_texto = (
                valor_texto[:500]
                + "..."
            )

        print(
            f"      ejemplo: {valor_texto}"
        )

    return {
        ruta: {
            "cantidad": contador[ruta],
            "ejemplo": ejemplos.get(ruta),
        }
        for ruta in contador
    }


# ============================================================
# ANÁLISIS DE PRIMEROS PRODUCTOS
# ============================================================

def mostrar_primeros_productos(productos, cantidad=5):

    imprimir_titulo(
        f"PRIMEROS {cantidad} PRODUCTOS - RESUMEN"
    )

    for numero, producto in enumerate(
        productos[:cantidad],
        start=1
    ):

        print()
        print(
            f"PRODUCTO #{numero}"
        )

        print(
            f"  productId: "
            f"{producto.get('productId')}"
        )

        print(
            f"  productName: "
            f"{producto.get('productName')}"
        )

        print(
            f"  brand: "
            f"{producto.get('brand')}"
        )

        print(
            f"  brandId: "
            f"{producto.get('brandId')}"
        )

        print(
            f"  categoryId: "
            f"{producto.get('categoryId')}"
        )

        print(
            f"  categorías: "
            f"{producto.get('categories')}"
        )

        for item in producto.get("items") or []:

            print(
                f"    SKU itemId: "
                f"{item.get('itemId')}"
            )

            print(
                f"    Nombre: "
                f"{item.get('name')}"
            )

            print(
                f"    EAN: "
                f"{item.get('ean')}"
            )

            print(
                f"    Imágenes: "
                f"{len(item.get('images') or [])}"
            )

            for seller in item.get("sellers") or []:

                oferta = (
                    seller.get(
                        "commertialOffer"
                    )
                    or {}
                )

                print(
                    f"      Seller: "
                    f"{seller.get('sellerId')} "
                    f"({seller.get('sellerName')})"
                )

                print(
                    f"        Price: "
                    f"{oferta.get('Price')}"
                )

                print(
                    f"        ListPrice: "
                    f"{oferta.get('ListPrice')}"
                )

                print(
                    f"        AvailableQuantity: "
                    f"{oferta.get('AvailableQuantity')}"
                )

                print(
                    f"        IsAvailable: "
                    f"{oferta.get('IsAvailable')}"
                )


# ============================================================
# EXPLORACIÓN DE FILTROS
# ============================================================

def explorar_filtro(
    nombre,
    params
):

    imprimir_subtitulo(
        f"REQUEST: {nombre}"
    )

    response, data = hacer_request(
        params,
        nombre
    )

    if response is None:
        return {
            "nombre": nombre,
            "status_code": None,
            "total": None,
            "recibidos": 0,
            "error": "No se pudo realizar request",
        }

    total = None

    _, _, total = obtener_recursos(
        response
    )

    recibidos = (
        len(data)
        if data is not None
        else 0
    )

    print()

    print("RESULTADO:")
    print(
        f"  HTTP total informado: "
        f"{total}"
    )

    print(
        f"  Productos recibidos: "
        f"{recibidos}"
    )

    if data:

        print(
            f"  Primer producto: "
            f"{data[0].get('productName')}"
        )

    return {
        "nombre": nombre,
        "status_code": response.status_code,
        "total": total,
        "recibidos": recibidos,
        "primer_producto": (
            data[0].get("productName")
            if data
            else None
        ),
    }


# ============================================================
# MAIN
# ============================================================

def main():

    inicio = time.time()

    imprimir_titulo(
        "DIAGNÓSTICO COMPLETO CARREFOUR ARGENTINA / VTEX"
    )

    print(
        f"URL: {SEARCH_URL}"
    )

    print(
        f"Búsqueda: {BUSQUEDA}"
    )

    print(
        f"Sales channel: {SALES_CHANNEL}"
    )

    print(
        f"Fecha/hora inicio: "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # ========================================================
    # 1. BÚSQUEDA COMPLETA
    # ========================================================

    productos, total_vtex = buscar_todos(
        {
            "ft": BUSQUEDA,
        },
        f"Búsqueda ft={BUSQUEDA}"
    )

    print()

    print(
        f"Productos únicos recibidos: "
        f"{len(productos)}"
    )

    # ========================================================
    # 2. GUARDAR RESPUESTA ORIGINAL
    # ========================================================

    guardar_json(
        "carrefour_sedal_original_completo.json",
        limpiar_para_diagnostico(productos)
    )

    # ========================================================
    # 3. RESUMEN DE PRODUCTOS
    # ========================================================

    resumen_productos = [
        resumir_producto(producto)
        for producto in productos
    ]

    guardar_json(
        "carrefour_sedal_diagnostico_productos.json",
        resumen_productos
    )

    # ========================================================
    # 4. PRIMEROS PRODUCTOS
    # ========================================================

    mostrar_primeros_productos(
        productos,
        cantidad=5
    )

    # ========================================================
    # 5. DISPONIBILIDAD
    # ========================================================

    estadisticas, detalle_stock = (
        analizar_disponibilidad(
            productos
        )
    )

    guardar_json(
        "carrefour_sedal_disponibilidad.json",
        {
            "estadisticas": dict(
                estadisticas
            ),
            "detalle": detalle_stock,
        }
    )

    # ========================================================
    # 6. CAMPOS DESCONOCIDOS DE DISPONIBILIDAD
    # ========================================================

    campos_disponibilidad = (
        analizar_nombres_de_campos(
            productos
        )
    )

    guardar_json(
        "carrefour_sedal_campos_disponibilidad.json",
        campos_disponibilidad
    )

    # ========================================================
    # 7. PRODUCTOS DISPONIBLES SEGÚN SKU
    # ========================================================

    productos_disponibles = []

    for producto in productos:

        copia = None

        for item in producto.get("items") or []:

            for seller in item.get("sellers") or []:

                oferta = (
                    seller.get(
                        "commertialOffer"
                    )
                    or {}
                )

                cantidad = oferta.get(
                    "AvailableQuantity"
                )

                disponible = oferta.get(
                    "IsAvailable"
                )

                if (
                    disponible is True
                    or (
                        isinstance(
                            cantidad,
                            (int, float)
                        )
                        and cantidad > 0
                    )
                ):

                    if copia is None:
                        copia = limpiar_para_diagnostico(
                            producto
                        )

                    break

            if copia is not None:
                break

        if copia is not None:
            productos_disponibles.append(
                copia
            )

    guardar_json(
        "carrefour_sedal_disponibles_por_sku.json",
        productos_disponibles
    )

    print()
    print(
        "Productos considerados disponibles "
        f"por SKU: {len(productos_disponibles)}"
    )

    # ========================================================
    # 8. EXPLORACIÓN DE FILTROS
    # ========================================================

    imprimir_titulo(
        "EXPLORACIÓN DE FILTROS VTEX"
    )

    filtros = []

    # --------------------------------------------------------
    # Disponibilidad sales channel = 1
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Disponibilidad sales channel 1 | "
            "fq=isAvailablePerSalesChannel_1:1",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": (
                    f"isAvailablePerSalesChannel_"
                    f"{SALES_CHANNEL}:1"
                ),
            }
        )
    )

    # --------------------------------------------------------
    # true
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Disponibilidad sales channel 1 = verdadero | "
            "fq=isAvailablePerSalesChannel_1:true",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": (
                    f"isAvailablePerSalesChannel_"
                    f"{SALES_CHANNEL}:true"
                ),
            }
        )
    )

    # --------------------------------------------------------
    # 1
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Disponibilidad sales channel 1 = 1 | "
            "fq=isAvailablePerSalesChannel_1:1",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": (
                    f"isAvailablePerSalesChannel_"
                    f"{SALES_CHANNEL}:1"
                ),
            }
        )
    )

    # --------------------------------------------------------
    # Marca B:Sedal
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Marca Sedal usando B | fq=B:Sedal",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": "B:Sedal",
            }
        )
    )

    # --------------------------------------------------------
    # brand:Sedal
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Marca Sedal usando brand | fq=brand:Sedal",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": "brand:Sedal",
            }
        )
    )

    # --------------------------------------------------------
    # brandId
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Marca Sedal usando brandId | fq=brandId:2002023",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": "brandId:2002023",
            }
        )
    )

    # --------------------------------------------------------
    # Categoría 405
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Categoría 405 | fq=C:405",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": "C:405",
            }
        )
    )

    # --------------------------------------------------------
    # categoryId
    # --------------------------------------------------------

    filtros.append(
        explorar_filtro(
            "Categoría 405 usando categoryId | "
            "fq=categoryId:405",
            {
                "_from": 0,
                "_to": 49,
                "ft": BUSQUEDA,
                "fq": "categoryId:405",
            }
        )
    )

    guardar_json(
        "carrefour_sedal_filtros.json",
        filtros
    )

    # ========================================================
    # 9. RESUMEN DE FILTROS
    # ========================================================

    imprimir_titulo(
        "RESUMEN DE FILTROS"
    )

    print(
        f"{'PRUEBA':<60}"
        f"{'TOTAL':>10}"
        f"{'RECIBIDOS':>12}"
    )

    print("-" * 85)

    for filtro in filtros:

        print(
            f"{filtro['nombre'][:60]:<60}"
            f"{str(filtro.get('total')):>10}"
            f"{str(filtro.get('recibidos')):>12}"
        )

    # ========================================================
    # 10. RESUMEN FINAL
    # ========================================================

    duracion = time.time() - inicio

    imprimir_titulo(
        "RESUMEN FINAL DEL DIAGNÓSTICO"
    )

    print(
        f"Busqueda:                 {BUSQUEDA}"
    )

    print(
        f"Total informado por VTEX: {total_vtex}"
    )

    print(
        f"Productos descargados:    {len(productos)}"
    )

    print(
        f"Productos disponibles:    "
        f"{len(productos_disponibles)}"
    )

    print(
        f"Duración:                 "
        f"{duracion:.2f} segundos"
    )

    print()
    print(
        "ARCHIVOS GENERADOS:"
    )

    archivos = [
        "carrefour_sedal_original_completo.json",
        "carrefour_sedal_diagnostico_productos.json",
        "carrefour_sedal_disponibilidad.json",
        "carrefour_sedal_campos_disponibilidad.json",
        "carrefour_sedal_disponibles_por_sku.json",
        "carrefour_sedal_filtros.json",
    ]

    for archivo in archivos:
        print(
            f"  {archivo}"
        )

    print()
    print(
        "=" * 100
    )

    print(
        "DIAGNÓSTICO TERMINADO"
    )

    print(
        "=" * 100
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Diagnóstico interrumpido por el usuario."
        )

        sys.exit(1)

    except Exception as e:

        print()
        print(
            "ERROR NO CONTROLADO:"
        )

        print(
            repr(e)
        )

        raise