import csv
import os
import re
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

# Patrones de disponibilidad que se consideran "sin stock".
# Se comparan en minúsculas, así que no importan mayúsculas/minúsculas.
# startswith cubre tanto "withoutStock" como
# "withoutStock (verificado en HTML)" con un solo patrón.
PATRONES_SIN_STOCK = [
    "withoutstock",
    "sin_stock",
]


# ============================================================
# UTILIDAD
# ============================================================

def es_disponibilidad_sin_stock(valor: str) -> bool:
    valor = (valor or "").strip().lower()
    if not valor:
        return False
    return any(valor.startswith(patron) for patron in PATRONES_SIN_STOCK)


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
    print(" LIMPIEZA DE HISTÓRICO DE PRECIOS SIN STOCK")
    print("==========================================\n")

    print("Patrones de disponibilidad que se eliminarán:")

    for patron in PATRONES_SIN_STOCK:
        print(f"  - {patron}*")

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

    if "disponibilidad" not in encabezados:
        print("\nERROR: no encontré la columna 'disponibilidad'.")
        print("Encabezados encontrados:")
        print(encabezados)
        return

    indice_disponibilidad = encabezados.index("disponibilidad")

    # Columnas opcionales, solo para mostrar mejor el resumen.
    indice_linea = encabezados.index("linea") if "linea" in encabezados else None
    indice_producto = encabezados.index("producto") if "producto" in encabezados else None
    indice_sitio = encabezados.index("sitio") if "sitio" in encabezados else None

    filas_a_eliminar = []
    filas_a_guardar_backup = []

    # --------------------------------------------------------
    # Buscar filas
    # --------------------------------------------------------

    for numero_fila, fila in enumerate(valores[1:], start=2):

        if len(fila) <= indice_disponibilidad:
            continue

        disponibilidad = fila[indice_disponibilidad]

        if es_disponibilidad_sin_stock(disponibilidad):

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

        print("\nNo hay filas sin stock para eliminar.")
        return

    # Mostrar distribución por sitio (si existe la columna)
    if indice_sitio is not None:

        cantidades_sitio = {}

        for fila in filas_a_guardar_backup:

            sitio = (
                fila[indice_sitio]
                if len(fila) > indice_sitio
                else "(sin sitio)"
            ).strip() or "(sin sitio)"

            cantidades_sitio[sitio] = cantidades_sitio.get(sitio, 0) + 1

        print("\nDistribución por sitio:")

        for sitio in sorted(cantidades_sitio):
            print(f"  {sitio}: {cantidades_sitio[sitio]} filas")

    # Mostrar distribución por valor exacto de disponibilidad
    cantidades_disp = {}

    for fila in filas_a_guardar_backup:

        disp = (
            fila[indice_disponibilidad]
            if len(fila) > indice_disponibilidad
            else ""
        ).strip() or "(vacío)"

        cantidades_disp[disp] = cantidades_disp.get(disp, 0) + 1

    print("\nDistribución por valor de disponibilidad:")

    for disp in sorted(cantidades_disp):
        print(f"  '{disp}': {cantidades_disp[disp]} filas")

    # Mostrar algunos ejemplos de producto/sitio para verificar a ojo
    print("\nEjemplos (hasta 10):")

    for fila in filas_a_guardar_backup[:10]:

        producto = (
            fila[indice_producto]
            if indice_producto is not None and len(fila) > indice_producto
            else "(sin producto)"
        )

        sitio = (
            fila[indice_sitio]
            if indice_sitio is not None and len(fila) > indice_sitio
            else "(sin sitio)"
        )

        disp = (
            fila[indice_disponibilidad]
            if len(fila) > indice_disponibilidad
            else ""
        )

        print(f"  [{sitio}] {producto} -> '{disp}'")

    # --------------------------------------------------------
    # Backup local
    # --------------------------------------------------------

    fecha_backup = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    nombre_backup = (
        f"backup_filas_sin_stock_{fecha_backup}.csv"
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
