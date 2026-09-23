import requests
import time

DOMINIO = "www.masonline.com.ar"
BUSQUEDA = "sedal"

PRODUCTOS_POR_PAGINA = 40
MAX_PAGINAS = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def analizar_disponibilidad(producto):
    """
    Analiza los sellers/items del producto y determina
    si existe al menos una oferta disponible.
    """

    items = producto.get("items", [])

    disponible = False
    tiene_informacion = False

    detalles_sellers = []

    for item in items:
        item_id = item.get("itemId")
        ean = item.get("ean")

        sellers = item.get("sellers", [])

        for seller in sellers:
            seller_id = seller.get("sellerId")
            seller_name = seller.get("sellerName")

            oferta = seller.get("commertialOffer") or {}

            # Campos habituales de VTEX
            is_available = oferta.get("IsAvailable")
            available_quantity = oferta.get("AvailableQuantity")
            price = oferta.get("Price")

            if (
                is_available is not None
                or available_quantity is not None
                or price is not None
            ):
                tiene_informacion = True

            # Consideramos disponible si VTEX dice explícitamente
            # IsAvailable=True o si AvailableQuantity > 0.
            seller_disponible = (
                is_available is True
                or (
                    isinstance(available_quantity, (int, float))
                    and available_quantity > 0
                )
            )

            if seller_disponible:
                disponible = True

            detalles_sellers.append({
                "item_id": item_id,
                "ean": ean,
                "seller_id": seller_id,
                "seller_name": seller_name,
                "is_available": is_available,
                "available_quantity": available_quantity,
                "price": price,
            })

    return disponible, tiene_informacion, detalles_sellers


def buscar_masonline():
    productos = {}

    print()
    print("=" * 80)
    print("MASONLINE - BÚSQUEDA SEDAL")
    print("=" * 80)
    print(
        f"Configuración: {MAX_PAGINAS} páginas × "
        f"{PRODUCTOS_POR_PAGINA} productos"
    )

    for pagina in range(MAX_PAGINAS):

        desde = pagina * PRODUCTOS_POR_PAGINA
        hasta = desde + PRODUCTOS_POR_PAGINA - 1

        url = (
            f"https://{DOMINIO}/api/catalog_system/pub/products/search/"
            f"{BUSQUEDA}?_from={desde}&_to={hasta}"
        )

        print()
        print("-" * 80)
        print(f"PÁGINA {pagina + 1}")
        print(f"Rango: _from={desde} &_to={hasta}")
        print(f"URL: {url}")

        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(f"HTTP: {resp.status_code}")

            # Masonline devuelve 206 (Partial Content)
            # y es una respuesta válida para esta API.
            if resp.status_code not in (200, 206):
                print("ERROR:")
                print(resp.text[:1000])
                continue

            data = resp.json()

            print(f"Productos recibidos: {len(data)}")

        except Exception as e:
            print(f"ERROR DE PETICIÓN: {type(e).__name__}: {e}")
            continue

        for producto in data:

            product_id = producto.get("productId")

            if product_id in productos:
                continue

            productos[product_id] = producto

            nombre = producto.get(
                "productName",
                "SIN NOMBRE"
            )

            disponible, tiene_info, sellers = (
                analizar_disponibilidad(producto)
            )

            # Buscar EAN/SKU principal para mostrar
            ean = None
            sku = None

            for item in producto.get("items", []):
                if sku is None:
                    sku = item.get("itemId")

                if ean is None:
                    ean = item.get("ean")

            if disponible:
                estado = "DISPONIBLE"
            elif tiene_info:
                estado = "NO DISPONIBLE"
            else:
                estado = "SIN INFO"

            print()
            print(
                f"[{estado}] "
                f"{nombre}"
            )
            print(
                f"    Product ID: {product_id}"
            )
            print(
                f"    SKU:        {sku or '-'}"
            )
            print(
                f"    EAN:        {ean or '-'}"
            )

            if not sellers:
                print("    Sellers:     ninguno")

            for seller in sellers:
                print(
                    f"    Seller:      "
                    f"{seller['seller_name'] or seller['seller_id']}"
                )
                print(
                    f"      IsAvailable:       "
                    f"{seller['is_available']}"
                )
                print(
                    f"      AvailableQuantity: "
                    f"{seller['available_quantity']}"
                )
                print(
                    f"      Price:             "
                    f"{seller['price']}"
                )

        # Si devuelve menos de 40, no tiene sentido seguir.
        if len(data) < PRODUCTOS_POR_PAGINA:
            print()
            print(
                "La página devolvió menos de "
                f"{PRODUCTOS_POR_PAGINA} productos. "
                "Se detiene la paginación."
            )
            break

        time.sleep(2)


    # ------------------------------------------------------------------
    # RESUMEN
    # ------------------------------------------------------------------

    total = 0
    disponibles = 0
    no_disponibles = 0
    sin_info = 0

    print()
    print()
    print("=" * 80)
    print("RESUMEN FINAL")
    print("=" * 80)

    for producto in productos.values():

        total += 1

        disponible, tiene_info, _ = (
            analizar_disponibilidad(producto)
        )

        if disponible:
            disponibles += 1
        elif tiene_info:
            no_disponibles += 1
        else:
            sin_info += 1

    print(f"Productos únicos encontrados: {total}")
    print(f"Disponibles:                  {disponibles}")
    print(f"No disponibles:               {no_disponibles}")
    print(f"Sin información:              {sin_info}")

    print()
    print(
        "IMPORTANTE: AvailableQuantity=0 significa inventario 0. "
        "Los valores 1/10/100/99999 son rangos estimados."
    )


if __name__ == "__main__":
    buscar_masonline()