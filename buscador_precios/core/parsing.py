"""Utilidades de parseo de precios y términos de búsqueda."""

import re


# -----------------------------------------------------------------------
# UTILIDADES DE PARSEO
# -----------------------------------------------------------------------
def parsear_precio_ar(texto: str):
    """Convierte '$ 9.599,40' (formato argentino) -> 9599.40"""
    match = re.search(r"([\d.]+,\d{2}|[\d.]+)", texto)
    if not match:
        return None
    limpio = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def parsear_precio_punto(texto: str):
    """Convierte '$6830.64' (punto decimal) -> 6830.64"""
    match = re.search(r"[\d]+\.?\d*", texto)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def normalizar_terminos(busqueda):
    """Acepta un string o una lista de strings y siempre devuelve una lista."""
    if isinstance(busqueda, str):
        return [busqueda]
    return list(busqueda)
