"""Todo lo que habla con Google Sheets: credenciales, log de precios e imágenes."""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

from config.settings import (
    NOMBRE_HOJA_IMAGENES,
    NOMBRE_HOJA_LOG,
    RUTA_CREDENCIALES,
    SPREADSHEET_ID,
)
from core.ean import clave_imagen
from imagenes import NUEVAS_IMAGENES, es_url_imagen_valida


# -----------------------------------------------------------------------
# GOOGLE SHEETS
# -----------------------------------------------------------------------


def obtener_credenciales_google():

    credenciales_json = os.environ.get("GOOGLE_CREDENTIALS")

    if credenciales_json:
        datos = json.loads(credenciales_json)

        return Credentials.from_service_account_info(
            datos,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )

    # Ejecución local
    return Credentials.from_service_account_file(
        RUTA_CREDENCIALES,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )


def escribir_en_google_sheets(filas: list):

    creds = obtener_credenciales_google()

    cliente = gspread.authorize(creds)

    planilla = cliente.open_by_key(SPREADSHEET_ID)

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_LOG)

    except gspread.exceptions.WorksheetNotFound:

        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_LOG, rows=2000, cols=10)

        hoja.append_row(
            [
                "fecha",
                "linea",
                "producto",
                "sitio",
                "precio",
                "disponibilidad",
                "error",
                "url",
                "ean",
                "sku",
            ]
        )

    filas_para_subir = [
        [
            f["fecha"],
            f["linea"],
            f["producto"],
            f["sitio"],
            f["precio"],
            f["disponibilidad"],
            f["error"],
            f["url"],
            f.get("ean"),
            f.get("sku"),
        ]
        for f in filas
    ]

    hoja.append_rows(filas_para_subir, value_input_option="USER_ENTERED")

    print(
        f"\n{len(filas_para_subir)} filas subidas a la pestaña "
        f"'{NOMBRE_HOJA_LOG}' del Google Sheet."
    )


def cargar_cache_imagenes(planilla):
    """
    Lee una sola vez la pestaña Imagenes_Productos.

    Devuelve:
        {
            "CLAVE": {
                "imageurl": "...",
                "fuente": "...",
                "ean": "...",
                "sku": "...",
            }
        }

    CLAVE es el EAN, o "sitio::sku" cuando el producto no tiene EAN
    (ver clave_imagen()).

    Si la hoja no existe, la crea. Si existe pero es "vieja" (sin las
    columnas sku/sitio, de antes de este cambio), se le agregan esas
    columnas al final sin tocar los datos existentes.
    """

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_IMAGENES)

    except gspread.exceptions.WorksheetNotFound:

        print(f"[IMAGENES] Creando pestaña '{NOMBRE_HOJA_IMAGENES}'...")

        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_IMAGENES, rows=2000, cols=5)

        hoja.append_row(["ean", "imageurl", "fuente", "sku", "sitio"])

        return {}

    valores = hoja.get_all_values()

    if not valores:
        return {}

    encabezados = [str(x).strip().lower() for x in valores[0]]

    try:
        indice_ean = encabezados.index("ean")
        indice_imagen = encabezados.index("imageurl")
    except ValueError:
        print(
            f"[IMAGENES] La hoja '{NOMBRE_HOJA_IMAGENES}' "
            "no tiene los encabezados esperados."
        )
        return {}

    indice_fuente = encabezados.index("fuente") if "fuente" in encabezados else None

    # Columnas nuevas (pueden no existir todavía en una hoja vieja).
    # "sitio" guarda el mismo valor que "fuente" para las filas de
    # combos/kits sin EAN; se guarda aparte para no depender de que
    # "fuente" siempre coincida textualmente con el nombre del sitio.
    indice_sku = encabezados.index("sku") if "sku" in encabezados else None
    indice_sitio = encabezados.index("sitio") if "sitio" in encabezados else None

    if indice_sku is None or indice_sitio is None:
        asegurar_columnas_sku_sitio(hoja, encabezados)

    cache = {}

    for fila in valores[1:]:

        if len(fila) <= indice_ean:
            continue

        ean = str(fila[indice_ean]).strip()

        imageurl = ""

        if len(fila) > indice_imagen:
            imageurl = str(fila[indice_imagen]).strip()

        if not es_url_imagen_valida(imageurl):
            continue

        fuente = ""

        if indice_fuente is not None and len(fila) > indice_fuente:
            fuente = str(fila[indice_fuente]).strip()

        sku = ""
        if indice_sku is not None and len(fila) > indice_sku:
            sku = str(fila[indice_sku]).strip()

        sitio = ""
        if indice_sitio is not None and len(fila) > indice_sitio:
            sitio = str(fila[indice_sitio]).strip()

        # Para filas viejas sin columna "sitio", usamos "fuente" como
        # sitio (en la práctica siempre fue el nombre del sitio).
        clave = clave_imagen(ean, sku, sitio or fuente)

        if not clave:
            continue

        cache[clave] = {
            "imageurl": imageurl,
            "fuente": fuente,
            "ean": ean,
            "sku": sku,
        }

    print(f"[IMAGENES] {len(cache)} productos con imagen ya almacenados.")

    return cache


def asegurar_columnas_sku_sitio(hoja, encabezados):
    """
    Si la pestaña Imagenes_Productos todavía no tiene las columnas
    "sku" y "sitio" (hoja creada antes de este cambio), las agrega al
    final del encabezado sin tocar ninguna fila de datos existente.
    """

    nuevos = list(encabezados)

    if "sku" not in nuevos:
        nuevos.append("sku")

    if "sitio" not in nuevos:
        nuevos.append("sitio")

    if nuevos == encabezados:
        return

    try:
        hoja.resize(cols=max(hoja.col_count, len(nuevos)))
        hoja.update("A1", [nuevos])
        print(
            f"[IMAGENES] Se agregaron columnas 'sku'/'sitio' a "
            f"'{NOMBRE_HOJA_IMAGENES}'."
        )
    except Exception as e:
        print(f"[AVISO] No se pudieron agregar columnas sku/sitio: {e}")


def guardar_nuevas_imagenes(planilla):
    """
    Guarda en Google Sheets únicamente las imágenes nuevas
    encontradas durante esta corrida.
    """

    if not NUEVAS_IMAGENES:
        print("[IMAGENES] No hay imágenes nuevas para guardar.")
        return

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_IMAGENES)
    except gspread.exceptions.WorksheetNotFound:
        hoja = planilla.add_worksheet(title=NOMBRE_HOJA_IMAGENES, rows=2000, cols=5)
        hoja.append_row(["ean", "imageurl", "fuente", "sku", "sitio"])

    encabezados = [str(x).strip().lower() for x in hoja.row_values(1)]

    if "sku" not in encabezados or "sitio" not in encabezados:
        asegurar_columnas_sku_sitio(hoja, encabezados)
        encabezados = [str(x).strip().lower() for x in hoja.row_values(1)]

    # Arma cada fila respetando el orden real de columnas de la hoja,
    # para no romper hojas viejas migradas con columnas en otro orden.
    valores_por_campo = {
        "ean": lambda item: item["ean"],
        "imageurl": lambda item: item["imageurl"],
        "fuente": lambda item: item["fuente"],
        "sku": lambda item: item["sku"],
        "sitio": lambda item: item.get("sitio", item["fuente"]),
    }

    filas = [
        [valores_por_campo.get(col, lambda item: "")(item) for col in encabezados]
        for item in NUEVAS_IMAGENES
    ]

    hoja.append_rows(filas, value_input_option="USER_ENTERED")

    print(
        f"[IMAGENES] {len(filas)} imágenes nuevas guardadas "
        f"en '{NOMBRE_HOJA_IMAGENES}'."
    )
