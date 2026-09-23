import csv
import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURACIÓN
# ============================================================

RUTA_CREDENCIALES = (
    "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
)

SPREADSHEET_ID = (
    "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"
)

NOMBRE_HOJA = "Precios_Log_Lineas"

EAN_EXCLUIDOS = {  
    "10000701",    
    "10000575",    
    "10000720",    
    "10000719",    
    "10000715",
    "10000718",
    "10001095",
    "245878",
    "7509552902389",
    "7798140257516",
    "7798140256274",
}


# ============================================================
# GOOGLE
# ============================================================

def obtener_credenciales():

    credenciales_json = os.environ.get("GOOGLE_CREDENTIALS")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if credenciales_json:

        import json

        datos = json.loads(credenciales_json)

        return Credentials.from_service_account_info(
            datos,
            scopes=scopes,
        )

    return Credentials.from_service_account_file(
        RUTA_CREDENCIALES,
        scopes=scopes,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n==========================================")
    print(" LIMPIEZA DE HISTÓRICO DE PRECIOS")
    print("==========================================\n")

    print("EAN que serán eliminados:")

    for ean in sorted(EAN_EXCLUIDOS):
        print(f"  - {ean}")

    print()

    creds = obtener_credenciales()
    cliente = gspread.authorize(creds)

    planilla = cliente.open_by_key(SPREADSHEET_ID)

    hoja = planilla.worksheet(NOMBRE_HOJA)

    print(f"Hoja encontrada: {NOMBRE_HOJA}")

    # --------------------------------------------------------
    # Leer toda la hoja
    # --------------------------------------------------------

    valores = hoja.get_all_values()

    if not valores:
        print("\nLa hoja está vacía.")
        return

    encabezados = [
        str(valor).strip().lower()
        for valor in valores[0]
    ]

    if "ean" not in encabezados:
        print("\nERROR: no encontré la columna 'ean'.")
        print("Encabezados encontrados:")
        print(encabezados)
        return

    indice_ean = encabezados.index("ean")

    filas_a_eliminar = []
    filas_a_guardar_backup = []

    # --------------------------------------------------------
    # Buscar filas
    # --------------------------------------------------------

    for numero_fila, fila in enumerate(valores[1:], start=2):

        if len(fila) <= indice_ean:
            continue

        ean = str(
            fila[indice_ean]
        ).strip()

        if ean in EAN_EXCLUIDOS:

            filas_a_eliminar.append(numero_fila)
            filas_a_guardar_backup.append(fila)

    # --------------------------------------------------------
    # Resultado del análisis
    # --------------------------------------------------------

    print(
        f"\nFilas encontradas para eliminar: "
        f"{len(filas_a_eliminar)}"
    )

    if not filas_a_eliminar:

        print("\nNo hay filas con esos EAN.")
        return

    # Mostrar distribución
    cantidades = {}

    for fila in filas_a_guardar_backup:

        ean = str(
            fila[indice_ean]
        ).strip()

        cantidades[ean] = cantidades.get(ean, 0) + 1

    print("\nDistribución:")

    for ean in sorted(cantidades):
        print(
            f"  {ean}: "
            f"{cantidades[ean]} filas"
        )

    # --------------------------------------------------------
    # Backup local
    # --------------------------------------------------------

    fecha_backup = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    nombre_backup = (
        f"backup_filas_eliminadas_{fecha_backup}.csv"
    )

    with open(
        nombre_backup,
        "w",
        newline="",
        encoding="utf-8",
    ) as archivo:

        writer = csv.writer(archivo)

        writer.writerow(valores[0])

        writer.writerows(
            filas_a_guardar_backup
        )

    print(
        f"\nBackup creado: {nombre_backup}"
    )

    # --------------------------------------------------------
    # Confirmación
    # --------------------------------------------------------

    print(
        "\nATENCIÓN:"
        "\nSe van a eliminar esas filas "
        "PERMANENTEMENTE de Google Sheets."
    )

    confirmacion = input(
        "\nEscribí ELIMINAR para continuar: "
    ).strip()

    if confirmacion != "ELIMINAR":

        print(
            "\nOperación cancelada."
        )

        print(
            f"El backup quedó guardado en: "
            f"{nombre_backup}"
        )

        return

    # --------------------------------------------------------
    # Eliminar filas
    #
    # Se eliminan de abajo hacia arriba para que al borrar
    # una fila no cambien los números de las que todavía
    # tenemos pendientes.
    # --------------------------------------------------------

    print("\nEliminando filas...")

    for numero_fila in reversed(
        filas_a_eliminar
    ):

        hoja.delete_rows(
            numero_fila
        )

    print(
        f"\n✓ Se eliminaron "
        f"{len(filas_a_eliminar)} filas."
    )

    print(
        f"✓ Backup disponible en: "
        f"{nombre_backup}"
    )

    print(
        "\nLimpieza terminada correctamente."
    )


if __name__ == "__main__":
    main()