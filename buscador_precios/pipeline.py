"""
Pipeline único de procesamiento: para una línea y un scraper, busca los
productos, los filtra, obtiene el precio, descarta lo que no sirve y
registra la imagen de lo que sobrevive.

Reemplaza los 4 bloques casi idénticos que antes vivían en main().
"""

from core.filtros import (
    disponibilidad_indica_sin_stock,
    ean_excluido,
    incluido_por_sku_forzado,
    pasa_filtro_exclusion,
    pasa_filtro_inclusion,
    sku_excluido,
)
from core.http import pausa_entre_pedidos
from imagenes import registrar_imagen


def _fila_error(fecha, linea, scraper, error):
    return {
        "fecha": fecha,
        "linea": linea["nombre"],
        "producto": None,
        "sitio": scraper.nombre,
        "precio": None,
        "disponibilidad": None,
        "error": error,
        "url": "",
    }


def _motivo_descarte_previo(prod, linea, scraper):
    """Filtros por nombre / EAN / SKU. Devuelve el motivo o None si pasa."""
    nombre = prod["nombre"]
    sitio = scraper.nombre

    if (
        scraper.aplica_incluir(linea)
        and not pasa_filtro_inclusion(nombre, linea.get("incluir", []))
        and not incluido_por_sku_forzado(prod.get("sku_id"), sitio, linea)
    ):
        return "filtrado por 'incluir'"

    if not pasa_filtro_exclusion(nombre, linea["excluir"]):
        return "filtrado por 'excluir'"

    if ean_excluido(prod.get("ean"), sitio):
        return f"EAN excluido {prod.get('ean')} en {sitio}"

    if sku_excluido(prod.get("sku_id"), sitio):
        return f"SKU excluido {prod.get('sku_id')} en {sitio}"

    return scraper.pre_descarte(prod)


def _procesar(linea, scraper, fecha):
    print(f"  Buscando en {scraper.nombre}...")

    productos, error = scraper.buscar(linea)
    if error:
        print(f"    [ERROR] {error}")
        return [_fila_error(fecha, linea, scraper, error)]

    if not productos:
        print("    (sin productos para este término)")
    else:
        print(f"    ({len(productos)} productos crudos)")

    filas = []

    for prod in productos or []:
        motivo = _motivo_descarte_previo(prod, linea, scraper)
        if motivo:
            print(f"    [{motivo}] {prod['nombre']}")
            continue

        resultado = scraper.obtener_precio(prod)

        fila = {
            "fecha": fecha,
            "linea": linea["nombre"],
            "producto": prod["nombre"],
            "sitio": scraper.nombre,
            "precio": resultado.get("precio"),
            "disponibilidad": resultado.get("disponibilidad"),
            "error": resultado.get("error", ""),
            "url": prod.get("url", ""),
            "ean": prod.get("ean"),
            "sku": prod.get("sku_id"),
        }

        # DESCARTES: primero se descarta, recién después (si el producto
        # sobrevivió) se registra su imagen. Así no se guardan imágenes
        # de productos sin precio ni sin stock.
        if fila["precio"] is None:
            print(
                f"    [sin precio, descartado] {fila['producto']} "
                f"({fila['disponibilidad']})"
            )
            if scraper.pausa_por_producto:
                pausa_entre_pedidos()
            continue

        if disponibilidad_indica_sin_stock(fila["disponibilidad"]):
            print(
                f"    [sin stock, descartado] {fila['producto']} "
                f"({fila['disponibilidad']})"
            )
            if scraper.pausa_por_producto:
                pausa_entre_pedidos()
            continue

        if prod.get("ean") or prod.get("sku_id"):
            imagen = scraper.imagen(prod)
            if imagen:
                registrar_imagen(
                    prod.get("ean"), prod.get("sku_id"), imagen, scraper.nombre
                )

        filas.append(fila)
        print(
            f"    -> {fila['producto']}: {fila['precio']} "
            f"({fila['disponibilidad']})"
        )

        if scraper.pausa_por_producto:
            pausa_entre_pedidos()

    return filas


def procesar_linea_en_scraper(linea, scraper, fecha):
    """Procesa una línea en un comercio y devuelve las filas a guardar."""
    filas = _procesar(linea, scraper, fecha)

    if scraper.pausa_tras_sitio:
        pausa_entre_pedidos()

    return filas
