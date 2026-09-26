"""
Rellenar EAN/SKU históricos por URL de producto.

Problema que resuelve:
    Versiones viejas de buscador_precios.py no guardaban "ean" ni "sku".
    Este script recorre la pestaña Precios_Log_Lineas, agrupa las filas
    por "url" y, cuando encuentra que otra fila con la MISMA url sí tiene
    ean y/o sku cargado, copia ese valor a las filas que lo tienen vacío.

    Si para una misma url hay valores DISTINTOS de ean o sku entre filas
    (dato sucio / la url cambió de producto con el tiempo), NO se
    modifica nada para ese grupo: se reporta como conflicto para que lo
    revises a mano.

Es un script independiente: no importa ni modifica buscador_precios.py.
Solo necesita las mismas credenciales de Google que ya usás.

Requisitos:
    pip3 install gspread google-auth --break-system-packages

Uso:
    # 1) Modo simulación (no escribe nada, solo te muestra qué haría)
    python3 rellenar_identificadores.py

    # 2) Modo real (aplica los cambios en el Sheet)
    python3 rellenar_identificadores.py --aplicar
"""

import argparse
import json
import os

import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------
# CONFIGURACIÓN — debe coincidir con buscador_precios.py
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"
NOMBRE_HOJA_LOG = "Precios_Log_Lineas"

# Columnas que se intentan completar por URL. Podés sacar "sku" de esta
# lista si por ahora solo te interesa sanar el EAN, o viceversa.
COLUMNAS_A_COMPLETAR = ["ean", "sku"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def obtener_credenciales_google():
    credenciales_json = os.environ.get("GOOGLE_CREDENTIALS")
    if credenciales_json:
        datos = json.loads(credenciales_json)
        return Credentials.from_service_account_info(datos, scopes=SCOPES)
    return Credentials.from_service_account_file(RUTA_CREDENCIALES, scopes=SCOPES)


def vacio(valor) -> bool:
    return valor is None or str(valor).strip() == ""


def main():
    parser = argparse.ArgumentParser(
        description="Propaga ean/sku a filas históricas usando la url como clave."
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Escribe los cambios en el Sheet. Sin esta bandera, solo simula.",
    )
    args = parser.parse_args()

    creds = obtener_credenciales_google()
    cliente = gspread.authorize(creds)
    planilla = cliente.open_by_key(SPREADSHEET_ID)
    hoja = planilla.worksheet(NOMBRE_HOJA_LOG)

    valores = hoja.get_all_values()
    if not valores:
        print("La hoja está vacía.")
        return

    encabezados = [h.strip().lower() for h in valores[0]]
    filas = valores[1:]  # datos, sin encabezado (fila 1 = índice 0 = fila real 2)

    try:
        idx_url = encabezados.index("url")
    except ValueError:
        print("[ERROR] No encontré una columna 'url' en el encabezado.")
        return

    columnas_idx = {}
    for col in COLUMNAS_A_COMPLETAR:
        if col in encabezados:
            columnas_idx[col] = encabezados.index(col)
        else:
            print(f"[AVISO] No encontré columna '{col}', se ignora.")

    if not columnas_idx:
        print("No hay columnas para completar. Revisá COLUMNAS_A_COMPLETAR.")
        return

    # -------------------------------------------------------------
    # 1) Para cada columna (ean, sku), armar url -> set de valores
    #    no vacíos vistos en cualquier fila.
    # -------------------------------------------------------------
    valores_por_url = {col: {} for col in columnas_idx}  # col -> {url: set(valores)}

    for fila in filas:
        url = fila[idx_url].strip() if idx_url < len(fila) else ""
        if not url:
            continue
        for col, idx in columnas_idx.items():
            valor = fila[idx] if idx < len(fila) else ""
            if not vacio(valor):
                valores_por_url[col].setdefault(url, set()).add(str(valor).strip())

    # -------------------------------------------------------------
    # 2) Determinar, por columna y url, si hay un valor único (candidato
    #    a propagar) o un conflicto (varios valores distintos).
    # -------------------------------------------------------------
    candidato = {col: {} for col in columnas_idx}   # col -> {url: valor}
    conflictos = {col: {} for col in columnas_idx}  # col -> {url: set(valores)}

    for col, mapa in valores_por_url.items():
        for url, vistos in mapa.items():
            if len(vistos) == 1:
                candidato[col][url] = next(iter(vistos))
            else:
                conflictos[col][url] = vistos

    # -------------------------------------------------------------
    # 3) Recorrer filas de nuevo y armar la lista de celdas a
    #    actualizar (fila vacía + candidato único disponible para esa url).
    # -------------------------------------------------------------
    actualizaciones = []  # (numero_fila_real, col_letra_o_idx, valor, nombre_col)
    filas_con_conflicto_pendiente = set()

    for i, fila in enumerate(filas):
        numero_fila_real = i + 2  # +1 por encabezado, +1 porque gspread es 1-indexed
        url = fila[idx_url].strip() if idx_url < len(fila) else ""
        if not url:
            continue

        for col, idx in columnas_idx.items():
            valor_actual = fila[idx] if idx < len(fila) else ""
            if not vacio(valor_actual):
                continue  # ya tiene dato, no tocar

            if url in conflictos[col]:
                filas_con_conflicto_pendiente.add((numero_fila_real, url, col))
                continue

            if url in candidato[col]:
                actualizaciones.append(
                    (numero_fila_real, idx + 1, candidato[col][url], col, url)
                )

    # -------------------------------------------------------------
    # 4) Reporte
    # -------------------------------------------------------------
    print(f"Filas de datos analizadas: {len(filas)}")
    print(f"Celdas a completar: {len(actualizaciones)}\n")

    for numero_fila, _idx_col, valor, col, url in actualizaciones:
        print(f"  fila {numero_fila}: {col} = '{valor}'   (url: {url})")

    if filas_con_conflicto_pendiente:
        print(f"\n[CONFLICTOS] {len(filas_con_conflicto_pendiente)} fila(s) con url "
              f"que tiene valores distintos en otras filas — no se tocan:")
        urls_vistas = set()
        for _num, url, col in filas_con_conflicto_pendiente:
            clave = (url, col)
            if clave in urls_vistas:
                continue
            urls_vistas.add(clave)
            print(f"  {col} en conflicto para url: {url}")
            print(f"    valores encontrados: {conflictos[col][url]}")

    if not actualizaciones:
        print("\nNada para completar. No se hicieron cambios.")
        return

    if not args.aplicar:
        print(
            "\n[SIMULACIÓN] No se escribió nada. "
            "Corré con --aplicar para escribir estos valores en el Sheet."
        )
        return

    # -------------------------------------------------------------
    # 5) Aplicar cambios reales, en un solo batch
    # -------------------------------------------------------------
    celdas = [
        gspread.Cell(row=numero_fila, col=col_idx, value=valor)
        for numero_fila, col_idx, valor, _col, _url in actualizaciones
    ]
    hoja.update_cells(celdas, value_input_option="USER_ENTERED")
    print(f"\n[LISTO] Se escribieron {len(celdas)} celdas en '{NOMBRE_HOJA_LOG}'.")


if __name__ == "__main__":
    main()
