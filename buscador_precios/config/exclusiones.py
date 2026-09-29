"""
Exclusiones de productos.

- EXCLUIR_GLOBAL: patrones regex sobre el NOMBRE (se define acá).
- EAN / SKU excluidos: se leen de exclusiones.json, para poder editarlos
  sin tocar código Python.
"""

import json
from pathlib import Path

RUTA_JSON = Path(__file__).with_name("exclusiones.json")

# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# EXCLUSIÓN GLOBAL: patrones que se descartan en TODAS las líneas, sin
# importar cuál sea (productos que nunca interesan independientemente
# de la línea de marca que se esté buscando).
# -----------------------------------------------------------------------
EXCLUIR_GLOBAL = [
    r"agua micelar",
    r"antitranspirante",
    r"\btalco\b",
    r"porcelana",
    r"jab[oó]n",
    r"manchas",
    r"limpieza",
    r"\bcover\b",
    r"multiprop[oó]sito",
    r"\bcoo\b",
    r"excellence",
]


def _cargar_json():
    with open(RUTA_JSON, encoding="utf-8") as f:
        return json.load(f)


def _como_set(codigos):
    return {str(c).strip() for c in codigos if str(c).strip()}


_datos = _cargar_json()

# Códigos que se excluyen en todos los comercios (se unen todos los grupos).
EAN_EXCLUIDOS = set()
for _grupo, _codigos in _datos.get("ean_globales", {}).items():
    if _grupo.startswith("_"):
        continue
    EAN_EXCLUIDOS |= _como_set(_codigos)

# Códigos que se excluyen solo en el comercio indicado.
EAN_EXCLUIDOS_POR_COMERCIO = {
    comercio: _como_set(codigos)
    for comercio, codigos in _datos.get("ean_por_comercio", {}).items()
    if not comercio.startswith("_")
}

# SKU internos excluidos por comercio (para sitios sin EAN, como Maxiconsumo).
SKU_EXCLUIDOS_POR_COMERCIO = {
    comercio: _como_set(codigos)
    for comercio, codigos in _datos.get("sku_por_comercio", {}).items()
    if not comercio.startswith("_")
}
