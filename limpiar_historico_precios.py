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

# Códigos a eliminar. Pueden ser EAN (la mayoría de proveedores)
# o SKU (por ejemplo Maxiconsumo, que no tiene EAN).
# El script revisa ambas columnas y elimina la fila si matchea
# en cualquiera de las dos.
CODIGOS_EXCLUIDOS = {
      "245790",
      "7798140259107",
      "27426",
      "2907",
      "4764",
      "19288",
      "19287",      
      "16117",
      "4744",
      "2911",      
      "4739",
      "27427",
      "7898587774987",
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

    print("Códigos (EAN o SKU) que serán eliminados:")

    for codigo in sorted(CODIGOS_EXCLUIDOS):
        print(f"  - {codigo}")

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

    # La columna 'sku' es nueva (está a la derecha de 'ean') y
    # puede no existir en hojas viejas, así que es opcional.
    indice_sku = (
        encabezados.index("sku")
        if "sku" in encabezados
        else None
    )

    if indice_sku is None:
        print(
            "\nAVISO: no encontré la columna 'sku'. "
            "Sólo se va a filtrar por EAN."
        )

    filas_a_eliminar = []
    filas_a_guardar_backup = []
    matches_por_fila = []  # guarda si matcheó por 'ean', 'sku' o ambos

    # --------------------------------------------------------
    # Buscar filas
    # --------------------------------------------------------

    for numero_fila, fila in enumerate(valores[1:], start=2):

        ean = ""
        if len(fila) > indice_ean:
            ean = str(fila[indice_ean]).strip()

        sku = ""
        if indice_sku is not None and len(fila) > indice_sku:
            sku = str(fila[indice_sku]).strip()

        matcheo_ean = ean != "" and ean in CODIGOS_EXCLUIDOS
        matcheo_sku = sku != "" and sku in CODIGOS_EXCLUIDOS

        if matcheo_ean or matcheo_sku:

            filas_a_eliminar.append(numero_fila)
            filas_a_guardar_backup.append(fila)

            if matcheo_ean and matcheo_sku:
                matches_por_fila.append("ean+sku")
            elif matcheo_ean:
                matches_por_fila.append("ean")
            else:
                matches_por_fila.append("sku")

    # --------------------------------------------------------
    # Resultado del análisis
    # --------------------------------------------------------

    print(
        f"\nFilas encontradas para eliminar: "
        f"{len(filas_a_eliminar)}"
    )

    if not filas_a_eliminar:

        print("\nNo hay filas con esos códigos.")
        return

    # Mostrar distribución (por código y por columna de origen)
    cantidades = {}

    for fila, origen in zip(filas_a_guardar_backup, matches_por_fila):

        ean = str(fila[indice_ean]).strip() if len(fila) > indice_ean else ""
        sku = (
            str(fila[indice_sku]).strip()
            if indice_sku is not None and len(fila) > indice_sku
            else ""
        )

        codigo = ean if origen in ("ean", "ean+sku") else sku
        clave = f"{codigo} ({origen})"

        cantidades[clave] = cantidades.get(clave, 0) + 1

    print("\nDistribución:")

    for clave in sorted(cantidades):
        print(
            f"  {clave}: "
            f"{cantidades[clave]} filas"
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
