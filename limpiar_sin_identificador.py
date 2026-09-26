"""
Limpieza interactiva de productos sin identificador.

Recorre la pestaña "Sin_Identificador" (el listado de productos que
quedaron sin ean/sku) y, uno por uno, pregunta por consola si querés
eliminarlo. Si confirmás, borra TODAS las filas de la pestaña
Precios_Log_Lineas cuyo "producto" coincida EXACTAMENTE con ese nombre
(puede haber varias: distintos sitios, distintas fechas).

Al confirmar el borrado de un producto, también se quita esa fila de
"Sin_Identificador", así la próxima corrida solo te muestra lo que
falta revisar. Si preferís que NO se toque Sin_Identificador, corré
con --no-limpiar-lista.

Es un script independiente: no importa ni modifica buscador_precios.py.

Requisitos:
    pip3 install gspread google-auth --break-system-packages

Uso:
    python3 limpiar_sin_identificador.py
    python3 limpiar_sin_identificador.py --no-limpiar-lista
"""

import argparse
import json
import os
import time

import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------
# CONFIGURACIÓN — debe coincidir con buscador_precios.py
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"
NOMBRE_HOJA_LOG = "Precios_Log_Lineas"
NOMBRE_HOJA_SIN_ID = "Sin_Identificador"

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


def columna_producto(encabezados, nombre_hoja):
    """Encuentra el índice de la columna 'producto'. Si la hoja tiene una
    sola columna (listado simple, sin encabezado de nombre), usa esa."""
    enc_norm = [h.strip().lower() for h in encabezados]
    if "producto" in enc_norm:
        return enc_norm.index("producto")
    if len(encabezados) == 1:
        return 0
    raise ValueError(
        f"No encontré columna 'producto' en '{nombre_hoja}' y tiene más de "
        f"una columna, así que no puedo adivinar cuál usar."
    )


def agrupar_en_rangos(numeros_fila):
    """Convierte {5, 6, 7, 20} -> [(5, 7), (20, 20)] (rangos contiguos,
    inclusive, 1-indexados) para minimizar la cantidad de sub-requests."""
    ordenados = sorted(numeros_fila)
    rangos = []
    inicio = fin = ordenados[0]
    for n in ordenados[1:]:
        if n == fin + 1:
            fin = n
        else:
            rangos.append((inicio, fin))
            inicio = fin = n
    rangos.append((inicio, fin))
    return rangos


def borrar_filas_por_lote(planilla, hoja, numeros_fila, tam_lote=200):
    """Borra filas usando un único batch_update por lote (en vez de un
    delete_rows por fila), agrupando en rangos contiguos y yendo de
    mayor a menor índice. Reintenta con backoff si la API responde 429."""
    if not numeros_fila:
        return

    rangos = agrupar_en_rangos(numeros_fila)
    rangos.sort(key=lambda r: r[0], reverse=True)  # de abajo hacia arriba

    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": hoja.id,
                    "dimension": "ROWS",
                    "startIndex": inicio - 1,
                    "endIndex": fin,
                }
            }
        }
        for inicio, fin in rangos
    ]

    for i in range(0, len(requests), tam_lote):
        lote = requests[i : i + tam_lote]
        intento = 0
        while True:
            try:
                planilla.batch_update({"requests": lote})
                break
            except gspread.exceptions.APIError as e:
                codigo = e.response.status_code if e.response is not None else None
                intento += 1
                if codigo == 429 and intento <= 5:
                    espera = 2**intento
                    print(f"    [cuota excedida, reintento en {espera}s...]")
                    time.sleep(espera)
                    continue
                raise
        if i + tam_lote < len(requests):
            time.sleep(1)  # margen extra entre lotes grandes


def preguntar_si_no(mensaje):
    while True:
        resp = input(f"{mensaje} [s/N/q=salir]: ").strip().lower()
        if resp in ("s", "si", "sí"):
            return True
        if resp in ("", "n", "no"):
            return False
        if resp in ("q", "quit", "salir"):
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Elimina del log histórico los productos confirmados en Sin_Identificador."
    )
    parser.add_argument(
        "--no-limpiar-lista",
        action="store_true",
        help="No borrar la fila de Sin_Identificador al confirmar un borrado.",
    )
    args = parser.parse_args()

    creds = obtener_credenciales_google()
    cliente = gspread.authorize(creds)
    planilla = cliente.open_by_key(SPREADSHEET_ID)

    hoja_log = planilla.worksheet(NOMBRE_HOJA_LOG)
    hoja_sin_id = planilla.worksheet(NOMBRE_HOJA_SIN_ID)

    valores_sin_id = hoja_sin_id.get_all_values()
    if not valores_sin_id:
        print(f"'{NOMBRE_HOJA_SIN_ID}' está vacía. Nada para hacer.")
        return

    encabezados_sin_id = valores_sin_id[0]
    filas_sin_id = valores_sin_id[1:]
    idx_prod_sin_id = columna_producto(encabezados_sin_id, NOMBRE_HOJA_SIN_ID)

    # Lista de (numero_fila_real_en_sin_id, nombre_producto), sin vacíos
    productos_a_revisar = []
    for i, fila in enumerate(filas_sin_id):
        nombre = fila[idx_prod_sin_id].strip() if idx_prod_sin_id < len(fila) else ""
        if nombre:
            productos_a_revisar.append((i + 2, nombre))  # +1 encabezado, +1 base 1

    if not productos_a_revisar:
        print(f"No hay productos listados en '{NOMBRE_HOJA_SIN_ID}'.")
        return

    valores_log = hoja_log.get_all_values()
    encabezados_log = [h.strip().lower() for h in valores_log[0]]
    idx_prod_log = encabezados_log.index("producto")
    filas_log = valores_log[1:]

    print(f"{len(productos_a_revisar)} producto(s) en '{NOMBRE_HOJA_SIN_ID}'.\n")

    filas_log_a_borrar = set()  # numeros de fila reales en hoja_log
    filas_sin_id_a_borrar = set()  # numeros de fila reales en hoja_sin_id

    for numero_fila_sin_id, nombre in productos_a_revisar:
        # Cuántas filas del log matchean exactamente ese nombre
        coincidencias = [
            i + 2
            for i, fila in enumerate(filas_log)
            if idx_prod_log < len(fila) and fila[idx_prod_log].strip() == nombre
        ]

        print(f'"{nombre}"  -> {len(coincidencias)} fila(s) en {NOMBRE_HOJA_LOG}')

        if not coincidencias:
            print("  (no encontrado en el log, se salta)\n")
            continue

        resp = preguntar_si_no("  ¿Eliminar este producto del histórico?")
        if resp is None:
            print("\nCancelado por el usuario. No se aplicó nada todavía.")
            break
        if resp:
            filas_log_a_borrar.update(coincidencias)
            if not args.no_limpiar_lista:
                filas_sin_id_a_borrar.add(numero_fila_sin_id)
            print(f"  -> marcado para borrar ({len(coincidencias)} fila(s)).\n")
        else:
            print("  -> se conserva.\n")

    if not filas_log_a_borrar:
        print("Nada para borrar. No se hicieron cambios.")
        return

    print(
        f"\nSe van a borrar {len(filas_log_a_borrar)} fila(s) de "
        f"'{NOMBRE_HOJA_LOG}'"
        + (
            f" y {len(filas_sin_id_a_borrar)} fila(s) de '{NOMBRE_HOJA_SIN_ID}'."
            if filas_sin_id_a_borrar
            else "."
        )
    )
    confirmacion_final = preguntar_si_no("Confirmar borrado definitivo")
    if not confirmacion_final:
        print("Cancelado. No se borró nada.")
        return

    print("Borrando en Precios_Log_Lineas...")
    borrar_filas_por_lote(planilla, hoja_log, filas_log_a_borrar)

    if filas_sin_id_a_borrar:
        print("Borrando en Sin_Identificador...")
        borrar_filas_por_lote(planilla, hoja_sin_id, filas_sin_id_a_borrar)

    print(
        f"[LISTO] Borradas {len(filas_log_a_borrar)} fila(s) de '{NOMBRE_HOJA_LOG}'"
        + (
            f" y {len(filas_sin_id_a_borrar)} de '{NOMBRE_HOJA_SIN_ID}'."
            if filas_sin_id_a_borrar
            else "."
        )
    )


if __name__ == "__main__":
    main()
