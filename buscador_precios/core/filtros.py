"""Filtros de inclusión/exclusión de productos y chequeo de stock."""

import re

from config.exclusiones import (
    EAN_EXCLUIDOS,
    EAN_EXCLUIDOS_POR_COMERCIO,
    EXCLUIR_GLOBAL,
    SKU_EXCLUIDOS_POR_COMERCIO,
)


def ean_excluido(ean, sitio):
    """
    Determina si un EAN debe excluirse.

    1. Si está en EAN_EXCLUIDOS, se excluye globalmente.
    2. Si está en EAN_EXCLUIDOS_POR_COMERCIO, se excluye
       solamente del comercio correspondiente.

    El mismo código puede estar excluido en un comercio
    y ser válido en otro.
    """

    ean = str(ean or "").strip()
    sitio = str(sitio or "").strip().lower()

    if not ean:
        return False

    # Exclusión global
    if ean in EAN_EXCLUIDOS:
        return True

    # Exclusión específica del comercio
    eans_comercio = EAN_EXCLUIDOS_POR_COMERCIO.get(
        sitio,
        set()
    )

    return ean in eans_comercio


def sku_excluido(sku, sitio):
    """
    Igual que ean_excluido(), pero para comercios que no exponen EAN
    (por ahora, Maxiconsumo) y usan el SKU interno como identificador.
    """
    sku = str(sku or "").strip()
    sitio = str(sitio or "").strip().lower()

    if not sku:
        return False

    skus_comercio = SKU_EXCLUIDOS_POR_COMERCIO.get(sitio, set())

    return sku in skus_comercio


def pasa_filtro_exclusion(nombre: str, excluir: list):
    nombre_str = nombre or ""
    todos_los_patrones = list(excluir) + EXCLUIR_GLOBAL
    return not any(
        re.search(patron, nombre_str, re.IGNORECASE) for patron in todos_los_patrones
    )


def pasa_filtro_inclusion(nombre: str, incluir: list):
    if not incluir:
        return True
    nombre_str = nombre or ""
    return any(re.search(patron, nombre_str, re.IGNORECASE) for patron in incluir)


def incluido_por_sku_forzado(sku, sitio: str, linea: dict):
    """
    Permite forzar la inclusión de un producto puntual (por SKU/sku_id
    del sitio) aunque su nombre no pase el filtro 'incluir' de la
    línea. Útil para casos donde el nombre del producto en un comercio
    en particular está incompleto/mal cargado y no menciona la palabra
    clave de la línea (ej. un "ACONDICIONADOR DOVE REPAIR 250 ML" en
    Maxiconsumo que en realidad SÍ es de la línea Bond Repair, pero no
    lo dice en el nombre).

    Se configura en LINEAS con la clave opcional "incluir_sku_por_sitio":
        "incluir_sku_por_sitio": {
            "maxiconsumo": {"22781"},
            "coto": {"123456"},
        }

    OJO: esto NO bypassea el filtro 'excluir' (tamaños, etc.) ni
    EAN_EXCLUIDOS/SKU_EXCLUIDOS_POR_COMERCIO — solo el filtro 'incluir'
    por nombre. Si un SKU forzado igual cae en una exclusión, se sigue
    descartando (hay que sacarlo de la exclusión correspondiente si de
    verdad se lo quiere).
    """
    sku = str(sku or "").strip()
    sitio = str(sitio or "").strip().lower()

    if not sku:
        return False

    forzados = linea.get("incluir_sku_por_sitio", {}).get(sitio, set())
    return sku in {str(s) for s in forzados}


# -----------------------------------------------------------------------
# CHEQUEO DE DISPONIBILIDAD (sitios VTEX)
# -----------------------------------------------------------------------
def disponibilidad_indica_sin_stock(disponibilidad):
    """
    True si el string de disponibilidad indica que el producto
    no tiene stock real, sin importar si vino acompañado de un
    precio (rescatado por el fallback CSS, promos, etc).
    """
    if not disponibilidad:
        return False
    return disponibilidad.strip().lower().startswith(("withoutstock", "sin_stock"))
