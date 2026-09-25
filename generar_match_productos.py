"""
Genera / actualiza la hoja "Match_Productos" a partir de los datos crudos
de "Precios_Log_Lineas".

Qué hace:
    1. Lee todas las filas de Precios_Log_Lineas.
    2. Por cada fila calcula un identificador:
         - "ean:<valor>"            si la fila tiene EAN
         - "sku:<sitio>:<valor>"    si no tiene EAN pero sí SKU
         - None                     si no tiene ninguno de los dos
    3. Las filas CON identificador se vuelcan a "Match_Productos"
       (columnas: identificador | nombre_detectado | linea | sitios | grupo_id).
       Si ya existe una fila con el mismo (identificador, nombre_detectado),
       no se duplica: solo se le agrega el sitio nuevo a la columna "sitios".
    4. Las filas SIN identificador se cuentan y se listan (deduplicadas por
       linea+producto+sitio) en la hoja "Sin_Identificador", para revisar
       más adelante con otro script.
    5. Al final imprime un resumen por consola.

La columna "grupo_id" la deja intacta si ya existe (la escribe/edita el
script unificar_grupos.py, no este).

Requisitos:
    pip3 install gspread google-auth --break-system-packages

Uso:
    python3 generar_match_productos.py
"""

import os
import json

import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------
# CONFIGURACIÓN (mismos valores que buscador_precios.py)
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"

NOMBRE_HOJA_LOG = "Precios_Log_Lineas"
NOMBRE_HOJA_MATCH = "Match_Productos"
NOMBRE_HOJA_SIN_ID = "Sin_Identificador"

ENCABEZADOS_MATCH = ["identificador", "nombre_detectado", "linea", "sitios", "grupo_id"]
ENCABEZADOS_SIN_ID = ["linea", "producto", "sitio", "url", "veces_visto"]


# -----------------------------------------------------------------------
# CREDENCIALES
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

    return Credentials.from_service_account_file(
        RUTA_CREDENCIALES,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )


def obtener_o_crear_hoja(planilla, nombre, encabezados, filas=2000):
    try:
        hoja = planilla.worksheet(nombre)
    except gspread.exceptions.WorksheetNotFound:
        print(f"[INFO] Creando pestaña '{nombre}'...")
        hoja = planilla.add_worksheet(title=nombre, rows=filas, cols=len(encabezados))
        hoja.append_row(encabezados)
    return hoja


def limpiar(valor):
    if valor is None:
        return ""
    return str(valor).strip()


# -----------------------------------------------------------------------
# IDENTIFICADOR
# -----------------------------------------------------------------------
def construir_identificador(ean, sku, sitio):
    ean = limpiar(ean)
    sku = limpiar(sku)
    sitio = limpiar(sitio).lower()

    if ean:
        return f"ean:{ean}"

    if sku and sitio:
        return f"sku:{sitio}:{sku}"

    return None


# -----------------------------------------------------------------------
# LECTURA DE Precios_Log_Lineas
# -----------------------------------------------------------------------
def leer_filas_log(planilla):
    hoja = planilla.worksheet(NOMBRE_HOJA_LOG)
    valores = hoja.get_all_values()

    if not valores:
        return [], {}

    encabezados = [limpiar(v).lower() for v in valores[0]]

    indice = {
        "linea": encabezados.index("linea") if "linea" in encabezados else -1,
        "producto": encabezados.index("producto") if "producto" in encabezados else -1,
        "sitio": encabezados.index("sitio") if "sitio" in encabezados else -1,
        "url": encabezados.index("url") if "url" in encabezados else -1,
        "ean": encabezados.index("ean") if "ean" in encabezados else -1,
        "sku": encabezados.index("sku") if "sku" in encabezados else -1,
    }

    faltantes = [clave for clave, i in indice.items() if i == -1 and clave in ("linea", "producto", "sitio")]
    if faltantes:
        raise RuntimeError(
            f"A '{NOMBRE_HOJA_LOG}' le faltan columnas obligatorias: {faltantes}"
        )

    return valores[1:], indice


def valor_de(fila, indice, clave):
    i = indice.get(clave, -1)
    if i == -1 or i >= len(fila):
        return ""
    return limpiar(fila[i])


# -----------------------------------------------------------------------
# CARGA DEL ESTADO ACTUAL DE Match_Productos
# -----------------------------------------------------------------------
def cargar_match_existente(hoja_match):
    """
    Devuelve:
        pares_existentes: set de (identificador, nombre_detectado) ya
                           presentes, para no duplicar filas.
        filas_por_identificador: {identificador: {"fila": nro_de_fila_1indexed,
                                                    "sitios": set(...)}}
                                  usa la ÚLTIMA fila vista de ese identificador
                                  para saber dónde actualizar "sitios".
    """
    valores = hoja_match.get_all_values()

    pares_existentes = set()
    filas_por_identificador = {}

    if not valores:
        return pares_existentes, filas_por_identificador

    encabezados = [limpiar(v).lower() for v in valores[0]]

    i_id = encabezados.index("identificador")
    i_nombre = encabezados.index("nombre_detectado")
    i_sitios = encabezados.index("sitios")

    for num_fila, fila in enumerate(valores[1:], start=2):  # fila 1 = encabezado
        identificador = fila[i_id].strip() if i_id < len(fila) else ""
        nombre = fila[i_nombre].strip() if i_nombre < len(fila) else ""
        sitios_txt = fila[i_sitios].strip() if i_sitios < len(fila) else ""

        if not identificador:
            continue

        pares_existentes.add((identificador, nombre))

        sitios_set = {s.strip() for s in sitios_txt.split(",") if s.strip()}

        filas_por_identificador[(identificador, nombre)] = {
            "fila": num_fila,
            "sitios": sitios_set,
        }

    return pares_existentes, filas_por_identificador


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
def main():
    creds = obtener_credenciales_google()
    cliente = gspread.authorize(creds)
    planilla = cliente.open_by_key(SPREADSHEET_ID)

    filas_log, indice = leer_filas_log(planilla)

    hoja_match = obtener_o_crear_hoja(planilla, NOMBRE_HOJA_MATCH, ENCABEZADOS_MATCH)
    hoja_sin_id = obtener_o_crear_hoja(planilla, NOMBRE_HOJA_SIN_ID, ENCABEZADOS_SIN_ID)

    pares_existentes, filas_por_identificador = cargar_match_existente(hoja_match)

    filas_nuevas = []  # para append_rows al final
    actualizaciones_sitios = []  # [(num_fila, col_sitios(=4), nuevo_texto)]

    sin_identificador = {}  # (linea, producto, sitio) -> {"url":..., "veces":n}

    total_identificadas = 0
    total_sin_identificador = 0

    for fila in filas_log:
        linea = valor_de(fila, indice, "linea")
        producto = valor_de(fila, indice, "producto")
        sitio = valor_de(fila, indice, "sitio").lower()
        url = valor_de(fila, indice, "url")
        ean = valor_de(fila, indice, "ean")
        sku = valor_de(fila, indice, "sku")

        if not sitio or not producto:
            continue

        identificador = construir_identificador(ean, sku, sitio)

        if identificador is None:
            total_sin_identificador += 1
            clave = (linea, producto, sitio)
            if clave not in sin_identificador:
                sin_identificador[clave] = {"url": url, "veces": 0}
            sin_identificador[clave]["veces"] += 1
            continue

        total_identificadas += 1
        clave_par = (identificador, producto)

        if clave_par in pares_existentes:
            # ya existe esa fila exacta: solo asegurarnos de que el sitio
            # esté en la columna "sitios".
            info = filas_por_identificador.get(clave_par)
            if info is not None and sitio not in info["sitios"]:
                info["sitios"].add(sitio)
                nuevo_texto = ", ".join(sorted(info["sitios"]))
                actualizaciones_sitios.append((info["fila"], nuevo_texto))
            continue

        # fila nueva
        pares_existentes.add(clave_par)
        filas_nuevas.append(
            {
                "identificador": identificador,
                "nombre_detectado": producto,
                "linea": linea,
                "sitios": {sitio},
            }
        )
        # también la registramos para que, si vuelve a aparecer más abajo
        # en el mismo run con otro sitio, se actualice en memoria.
        filas_por_identificador[clave_par] = {
            "fila": None,  # se completa después del append
            "sitios": {sitio},
        }

    # ---------------------------------------------------------------
    # ESCRIBIR NUEVAS FILAS
    # ---------------------------------------------------------------
    if filas_nuevas:
        filas_para_subir = [
            [
                f["identificador"],
                f["nombre_detectado"],
                f["linea"],
                ", ".join(sorted(f["sitios"])),
                "",  # grupo_id vacío: lo completa unificar_grupos.py
            ]
            for f in filas_nuevas
        ]
        hoja_match.append_rows(filas_para_subir, value_input_option="USER_ENTERED")
        print(f"[MATCH] {len(filas_para_subir)} identificadores nuevos agregados.")
    else:
        print("[MATCH] No hay identificadores nuevos.")

    # ---------------------------------------------------------------
    # ACTUALIZAR COLUMNA "sitios" DE FILAS YA EXISTENTES
    # ---------------------------------------------------------------
    if actualizaciones_sitios:
        COL_SITIOS = 4  # D: identificador(A) nombre(B) linea(C) sitios(D) grupo_id(E)
        celdas = []
        for num_fila, nuevo_texto in actualizaciones_sitios:
            celdas.append(gspread.Cell(row=num_fila, col=COL_SITIOS, value=nuevo_texto))
        hoja_match.update_cells(celdas, value_input_option="USER_ENTERED")
        print(f"[MATCH] {len(actualizaciones_sitios)} filas actualizadas (nuevo sitio agregado).")

    # ---------------------------------------------------------------
    # REESCRIBIR "Sin_Identificador" (snapshot completo de esta corrida)
    # ---------------------------------------------------------------
    hoja_sin_id.clear()
    hoja_sin_id.append_row(ENCABEZADOS_SIN_ID)

    if sin_identificador:
        filas_sin_id = [
            [linea, producto, sitio, info["url"], info["veces"]]
            for (linea, producto, sitio), info in sorted(sin_identificador.items())
        ]
        hoja_sin_id.append_rows(filas_sin_id, value_input_option="USER_ENTERED")

    # ---------------------------------------------------------------
    # RESUMEN
    # ---------------------------------------------------------------
    print("\n=== RESUMEN ===")
    print(f"Filas de log procesadas:           {len(filas_log)}")
    print(f"Filas CON identificador:           {total_identificadas}")
    print(f"Filas SIN identificador:           {total_sin_identificador}")
    print(f"Productos únicos sin identificador: {len(sin_identificador)}")
    print(f"(detalle en la pestaña '{NOMBRE_HOJA_SIN_ID}')")


if __name__ == "__main__":
    main()
