"""Registro de scrapers. Para sumar un comercio: crear su clase y agregarla acá."""

from config.sitios import SITIOS_MAGENTO, SITIOS_VTEX
from scrapers.coto import ScraperCoto
from scrapers.magento import ScraperMagento
from scrapers.paradineiro import ScraperParadineiro
from scrapers.vtex import ScraperVtex


def construir_scrapers():
    """Lista de scrapers en el orden en que se consultan para cada línea."""
    return (
        [ScraperVtex(cfg) for cfg in SITIOS_VTEX]
        + [ScraperCoto(), ScraperParadineiro()]
        + [ScraperMagento(cfg) for cfg in SITIOS_MAGENTO]
    )
