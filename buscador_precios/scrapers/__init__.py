"""Registro de scrapers. Para sumar un comercio: crear su clase y agregarla acá."""
import os

from config.sitios import SITIOS_MAGENTO, SITIOS_VTEX
from scrapers.coto import ScraperCoto
from scrapers.magento import ScraperMagento
from scrapers.paradineiro import ScraperParadineiro
from scrapers.vtex import ScraperVtex


def construir_scrapers():
    """Lista de scrapers en el orden en que se consultan para cada línea."""
    todos = (
        [ScraperVtex(cfg) for cfg in SITIOS_VTEX]
        + [ScraperCoto(), ScraperParadineiro()]
        + [ScraperMagento(cfg) for cfg in SITIOS_MAGENTO]
    )

    # Para pruebas: SOLO_SITIOS=vea  (o varios: SOLO_SITIOS=vea,coto)
    solo = os.environ.get("SOLO_SITIOS")
    if solo:
        pedidos = {x.strip() for x in solo.split(",") if x.strip()}
        desconocidos = pedidos - {sc.nombre for sc in todos}
        if desconocidos:
            raise SystemExit(f"SOLO_SITIOS: sitios inexistentes: {sorted(desconocidos)}")
        todos = [sc for sc in todos if sc.nombre in pedidos]

    return todos
