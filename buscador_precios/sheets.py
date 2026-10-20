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


# ---------------------------------------------------------------------------
# REEMPLAZO de escribir_en_google_sheets() en tu módulo de Google Sheets.
#
# Pegá estas definiciones en lugar de la función actual. No necesita imports
# nuevos (usa `gspread`, que ya importás). El resto del módulo (imágenes,
# credenciales, etc.) queda igual.
#
# Qué hace distinto: en vez de agregar siempre todas las filas, compara cada
# lectura con la última registrada para ese (sitio + sku):
#   - si precio, disponibilidad y error son iguales -> NO agrega fila, solo
#     actualiza "fecha_ultima_escritura" de la fila existente;
#   - si algo cambió (o el producto es nuevo)       -> agrega fila nueva.
# ---------------------------------------------------------------------------

COL_ULTIMA_ESCRITURA = "fecha_ultima_escritura"

ENCABEZADOS_LOG = [
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
    COL_ULTIMA_ESCRITURA,
]

COLUMNAS_OBLIGATORIAS = ("sitio", "sku", "url", "precio", "disponibilidad", "error")


def _texto(valor):
    """Normaliza a texto comparable (la hoja puede devolver 8133249 o 8133249.0)."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _precio(valor):
    """Normaliza precio: número redondeado a 2 decimales, o texto si no se puede."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    s = str(valor).strip().replace("$", "").replace(" ", "")
    if "," in s:  # formato AR: 7.852,95
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return s


def _clave(sitio, sku, url):
    """Identifica 'un producto en un comercio'. Usa la url si no hay sku."""
    identificador = _texto(sku) or _texto(url)
    # lstrip("0"): Sheets guarda "0123" como número 123; así ambos lados coinciden
    return (_texto(sitio), identificador.lstrip("0"))


def _firma(precio, disponibilidad, error):
    """Lo que, si cambia, convierte una lectura en 'nueva'."""
    return (_precio(precio), _texto(disponibilidad), _texto(error))


def escribir_en_google_sheets(filas: list):

    creds = obtener_credenciales_google()

    cliente = gspread.authorize(creds)

    planilla = cliente.open_by_key(SPREADSHEET_ID)

    try:
        hoja = planilla.worksheet(NOMBRE_HOJA_LOG)

    except gspread.exceptions.WorksheetNotFound:

        hoja = planilla.add_worksheet(
            title=NOMBRE_HOJA_LOG, rows=2000, cols=len(ENCABEZADOS_LOG)
        )

        hoja.append_row(ENCABEZADOS_LOG)

    # Se lee con valores "crudos" para que los precios vengan como números
    # y no como texto formateado ("7852,95").
    valores = hoja.get_all_values(value_render_option="UNFORMATTED_VALUE")

    if not valores:
        hoja.append_row(ENCABEZADOS_LOG)
        valores = [list(ENCABEZADOS_LOG)]

    encabezados = [str(x).strip().lower() for x in valores[0]]

    # Hoja vieja sin la columna nueva: se agrega al final del encabezado
    if COL_ULTIMA_ESCRITURA not in encabezados:
        encabezados.append(COL_ULTIMA_ESCRITURA)
        if hoja.col_count < len(encabezados):
            hoja.resize(cols=len(encabezados))
        hoja.update_cell(1, len(encabezados), COL_ULTIMA_ESCRITURA)

    posicion = {nombre: i for i, nombre in enumerate(encabezados)}

    faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c not in posicion]
    if faltantes:
        raise RuntimeError(
            f"La hoja '{NOMBRE_HOJA_LOG}' no tiene las columnas: {faltantes}"
        )

    def celda(fila, nombre):
        i = posicion[nombre]
        return fila[i] if i < len(fila) else ""

    # Última lectura conocida de cada (sitio, sku): (nro_de_fila, firma).
    # Se asume que la hoja está en orden cronológico (la última aparición gana).
    ultimo = {}

    for nro_fila, fila in enumerate(valores[1:], start=2):
        k = _clave(celda(fila, "sitio"), celda(fila, "sku"), celda(fila, "url"))
        ultimo[k] = (
            nro_fila,
            _firma(
                celda(fila, "precio"),
                celda(fila, "disponibilidad"),
                celda(fila, "error"),
            ),
        )

    col_ultima = posicion[COL_ULTIMA_ESCRITURA] + 1  # 1-based para A1
    filas_nuevas = []
    actualizaciones = []

    for f in filas:

        k = _clave(f["sitio"], f.get("sku"), f["url"])
        firma = _firma(f["precio"], f["disponibilidad"], f["error"])
        previo = ultimo.get(k)

        if previo and previo[1] == firma:
            # Repetida: solo se extiende la "fecha de última escritura".
            # previo[0] is None => ya se agregó en esta misma corrida.
            if previo[0] is not None:
                actualizaciones.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(previo[0], col_ultima),
                        "values": [[f["fecha"]]],
                    }
                )
            continue

        datos = {
            "fecha": f["fecha"],
            "linea": f["linea"],
            "producto": f["producto"],
            "sitio": f["sitio"],
            "precio": f["precio"],
            "disponibilidad": f["disponibilidad"],
            "error": f["error"],
            "url": f["url"],
            "ean": f.get("ean"),
            "sku": f.get("sku"),
            COL_ULTIMA_ESCRITURA: f["fecha"],
        }

        filas_nuevas.append([datos.get(col, "") for col in encabezados])
        ultimo[k] = (None, firma)

    if actualizaciones:
        hoja.batch_update(actualizaciones, value_input_option="USER_ENTERED")

    if filas_nuevas:
        hoja.append_rows(filas_nuevas, value_input_option="USER_ENTERED")

    print(
        f"\nPestaña '{NOMBRE_HOJA_LOG}': {len(filas_nuevas)} filas nuevas "
        f"(precio/disponibilidad cambió o producto nuevo), "
        f"{len(actualizaciones)} lecturas repetidas (solo se actualizó "
        f"'{COL_ULTIMA_ESCRITURA}')."
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
