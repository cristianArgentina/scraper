"""Normalización y validación de EAN, y clave de caché de imágenes."""


def limpiar_ean(valor):
    """
    Normaliza un EAN crudo tal como lo devuelve la API/HTML de un
    sitio. Algunos sitios (confirmado en Farmacity, para varios
    combos/kits) devuelven literalmente "0" en el campo ean en vez de
    dejarlo vacío. Si no se filtra acá, distintos productos con
    ean="0" terminan compartiendo el mismo identificador/clave más
    adelante (se agrupan entre sí en el catálogo, o se pisan la imagen
    en la caché) — se trata igual que si no hubiera EAN.
    """
    ean = str(valor).strip() if valor else ""

    if not ean:
        return None

    if set(ean) == {"0"}:
        return None

    return ean


def es_ean_valido(ean):
    """
    Valida el dígito de control GS1 de un EAN-8 o EAN-13.

    Algunos sitios (ej. Farmaonline) meten en el campo "ean" de sus
    combos/kits un ID interno propio en vez de un EAN real — pero como
    tiene 8 dígitos, "parece" un EAN válido a simple vista. Esta
    función distingue un EAN real de uno inventado, sin necesidad de
    mantener a mano una lista de códigos "falsos" conocidos.
    """

    if not ean:
        return False

    ean = str(ean).strip()

    if not ean.isdigit() or len(ean) not in (8, 13):
        return False

    digitos = [int(c) for c in ean]
    cuerpo, digito_control = digitos[:-1], digitos[-1]

    # EAN-8: pesos 3,1,3,1,3,1,3 · EAN-13: pesos 1,3,1,3,... (12 dígitos)
    pesos = [3, 1, 3, 1, 3, 1, 3] if len(cuerpo) == 7 else [1, 3] * 6

    suma = sum(d * p for d, p in zip(cuerpo, pesos))
    control_calculado = (10 - (suma % 10)) % 10

    return control_calculado == digito_control


def clave_imagen(ean, sku, fuente):
    """
    Calcula la clave de caché para un producto:
      - el EAN si es un EAN real (pasa el checksum GS1); o
      - "fuente::sku" si no hay EAN real pero sí SKU propio del sitio
        (combos/kits sin EAN, o un "ean" inventado por el sitio); o
      - "fuente::ean" como último recurso, si el "ean" no es válido
        pero tampoco hay SKU (así al menos queda acotado a ese sitio
        y no contamina otros productos que por casualidad compartan
        el mismo número).
    Devuelve None si no hay ningún dato utilizable.
    """
    ean = limpiar_ean(ean) or ""
    sku = str(sku).strip() if sku else ""
    fuente = str(fuente).strip() if fuente else ""

    if ean and es_ean_valido(ean):
        return ean
    if sku and fuente:
        return f"{fuente}::{sku}"
    if ean and fuente:
        return f"{fuente}::{ean}"
    return None
