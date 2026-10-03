"""
Buscador de precios por LÍNEA DE PRODUCTO (no por SKU individual).

En vez de mantener una lista de URLs/SKUs producto por producto, este
script busca cada línea de marca (ej. "dove bond repair") en cada sitio
y descubre automáticamente todos los productos de esa línea que vende
ese sitio, con su precio final (incluyendo promos de 2x1 / llevando 2
cuando existen).

Requisitos:
    pip3 install requests beautifulsoup4 gspread google-auth --break-system-packages

Estructura:
    config/      -> líneas, sitios, exclusiones (exclusiones.json), settings
    core/        -> http, parsing, ean, filtros, cache
    scrapers/    -> un scraper por comercio (interfaz común en base.py)
    pipeline.py  -> filtrado, precio, descartes e imágenes (igual para todos)
    imagenes.py  -> manejo de imágenes
    sheets.py    -> Google Sheets

Uso:
    python3 buscador_precios.py
"""

import os

from datetime import datetime

import gspread

from config.lineas import LINEAS
from config.settings import SPREADSHEET_ID, ZONA_HORARIA
from imagenes import CACHE_IMAGENES
from pipeline import procesar_linea_en_scraper
from scrapers import construir_scrapers
from sheets import (
    cargar_cache_imagenes,
    escribir_en_google_sheets,
    guardar_nuevas_imagenes,
    obtener_credenciales_google,
)


def main():
    fecha = datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M")
    filas = []

    # -------------------------------------------------------------------
    # CARGAR IMÁGENES EXISTENTES
    # -------------------------------------------------------------------
    try:
        creds = obtener_credenciales_google()
        cliente = gspread.authorize(creds)
        planilla = cliente.open_by_key(SPREADSHEET_ID)

        CACHE_IMAGENES.update(cargar_cache_imagenes(planilla))

    except Exception as e:
        print(
            f"[AVISO] No se pudo cargar la caché de imágenes: "
            f"{type(e).__name__}: {e}"
        )
        planilla = None

    # -------------------------------------------------------------------
    # RECORRER LÍNEAS x COMERCIOS
    # -------------------------------------------------------------------
    scrapers = construir_scrapers()

    for linea in LINEAS:
        print(f"\n=== Línea: {linea['nombre']} ===")

        for scraper in scrapers:
            filas.extend(procesar_linea_en_scraper(linea, scraper, fecha))

    # -------------------------------------------------------------------
    # GUARDAR RESULTADOS
    # -------------------------------------------------------------------
    # Para pruebas: SIN_GUARDAR=1 muestra todo por consola y no escribe nada
    # en Google Sheets (ni precios ni imágenes).
    if os.environ.get("SIN_GUARDAR") == "1":
        print(
            f"\n[SIN_GUARDAR] {len(filas)} filas calculadas, no se guardó nada en Sheets."
        )
        return
    try:
        escribir_en_google_sheets(filas)
    except Exception as e:
        print(f"\n[ERROR subiendo a Google Sheets]: {type(e).__name__}: {e}")

    try:
        if planilla is None:
            creds = obtener_credenciales_google()
            cliente = gspread.authorize(creds)
            planilla = cliente.open_by_key(SPREADSHEET_ID)

        guardar_nuevas_imagenes(planilla)

    except Exception as e:
        print(f"\n[ERROR guardando imágenes]: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
