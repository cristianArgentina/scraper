#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DIAGNÓSTICO CARREFOUR DESDE GOOGLE SHEETS

- SOLO LECTURA.
- NO modifica Google Sheets.
- NO consulta Carrefour.
- Analiza la pestaña Precios_Log_Lineas.
- Detecta automáticamente las columnas.
- Soporta EAN y SKU.
- Se concentra en registros de Carrefour + Sedal.
"""

import os
import sys
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURACIÓN
# ============================================================

# Si tu script principal usa otra ruta, cambiá solamente esto.
SERVICE_ACCOUNT_FILE = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"

# Si tu script principal tiene el ID directamente configurado,
# reemplazalo acá.
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"

WORKSHEET_NAME = "Precios_Log_Lineas"

COMERCIO = "carrefour"
BUSQUEDA = "sedal"

# Cantidad máxima de registros individuales que mostramos
MAX_REGISTROS = 300


# ============================================================
# UTILIDADES
# ============================================================

def normalizar(valor):
    if valor is None:
        return ""

    return str(valor).strip()


def normalizar_lower(valor):
    return normalizar(valor).lower()


def mostrar(valor):
    valor = normalizar(valor)

    if not valor:
        return "(vacío)"

    return valor


def contiene(valor, texto):
    return texto.lower() in normalizar_lower(valor)


def imprimir_separador(caracter="=", cantidad=80):
    print(caracter * cantidad)


def buscar_columna(headers, candidatos):
    """
    Busca una columna tolerando mayúsculas, minúsculas,
    espacios, guiones y underscores.
    """

    normalizados = {}

    for i, h in enumerate(headers):
        limpio = re.sub(r"[\s_\-]+", "", normalizar_lower(h))
        normalizados[limpio] = i

    for candidato in candidatos:
        limpio = re.sub(r"[\s_\-]+", "", normalizar_lower(candidato))

        if limpio in normalizados:
            return normalizados[limpio]

    return None


def valor_fila(row, indice):
    if indice is None:
        return ""

    if indice >= len(row):
        return ""

    return normalizar(row[indice])


# ============================================================
# CONEXIÓN
# ============================================================

def conectar():

    print()
    imprimir_separador()
    print("CONEXIÓN A GOOGLE SHEETS")
    imprimir_separador()

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print()
        print("ERROR: no se encontró el archivo de credenciales:")
        print(f"  {SERVICE_ACCOUNT_FILE}")
        print()
        print("Si tu script principal usa otro nombre/ruta,")
        print("modificá SERVICE_ACCOUNT_FILE al comienzo del diagnóstico.")
        sys.exit(1)

    if SPREADSHEET_ID == "PEGAR_AQUI_EL_SPREADSHEET_ID":
        print()
        print("ERROR: todavía no configuraste SPREADSHEET_ID.")
        print()
        print("Copiá el mismo SPREADSHEET_ID que utiliza tu script principal.")
        sys.exit(1)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)

    print("OK: conexión establecida.")
    print(f"Hoja: {spreadsheet.title}")
    print(f"Pestaña: {WORKSHEET_NAME}")

    return worksheet


# ============================================================
# DETECCIÓN DE COLUMNAS
# ============================================================

def detectar_columnas(headers):

    candidatos = {

        "fecha": [
            "fecha",
            "date",
            "fecha_lectura",
            "fecha_actualizacion",
            "timestamp",
        ],

        "comercio": [
            "comercio",
            "sitio",
            "merchant",
            "retail",
            "tienda",
        ],

        "nombre": [
            "nombre",
            "producto",
            "product",
            "nombre_producto",
        ],

        "ean": [
            "ean",
            "EAN",
        ],

        "sku": [
            "sku",
            "SKU",
            "itemId",
            "item_id",
        ],

        "precio": [
            "precio",
            "price",
            "precio_actual",
        ],

        "disponibilidad": [
            "disponibilidad",
            "disponible",
            "available",
            "availability",
        ],

        "error": [
            "error",
            "mensaje_error",
            "error_message",
        ],

        "url": [
            "url",
            "url_producto",
            "link",
            "product_url",
        ],

        "sitio_web": [
            "sitio_web",
            "website",
            "web",
        ],

        "busqueda": [
            "busqueda",
            "búsqueda",
            "search",
            "termino_busqueda",
            "linea",
        ],
    }

    columnas = {}

    for nombre, posibles in candidatos.items():
        columnas[nombre] = buscar_columna(headers, posibles)

    return columnas


def imprimir_columnas(headers, columnas):

    imprimir_separador()
    print("COLUMNAS DETECTADAS")
    imprimir_separador()

    for nombre, indice in columnas.items():

        if indice is None:
            print(f"  {nombre:20} -> NO ENCONTRADA")

        else:
            print(
                f"  {nombre:20} -> "
                f"columna {indice + 1}: {headers[indice]}"
            )

    print()


# ============================================================
# FILTRADO
# ============================================================

def es_carrefour(row, columnas):

    comercio = valor_fila(
        row,
        columnas["comercio"]
    ).lower()

    sitio = valor_fila(
        row,
        columnas["sitio_web"]
    ).lower()

    return (
        COMERCIO in comercio
        or COMERCIO in sitio
    )


def es_sedal(row, columnas):

    nombre = valor_fila(
        row,
        columnas["nombre"]
    )

    busqueda = valor_fila(
        row,
        columnas["busqueda"]
    )

    return (
        contiene(nombre, BUSQUEDA)
        or contiene(busqueda, BUSQUEDA)
    )


# ============================================================
# RESUMEN GENERAL
# ============================================================

def analizar_general(rows, columnas):

    imprimir_separador()
    print("RESUMEN GENERAL DE LA HOJA")
    imprimir_separador()

    print(f"Filas de datos analizadas: {len(rows)}")

    carrefour = [
        row for row in rows
        if es_carrefour(row, columnas)
    ]

    print(f"Registros de Carrefour: {len(carrefour)}")

    sedal = [
        row for row in carrefour
        if es_sedal(row, columnas)
    ]

    print(f"Registros Carrefour + Sedal: {len(sedal)}")

    print()


# ============================================================
# REGISTROS CARREFOUR + SEDAL
# ============================================================

def obtener_registros(rows, columnas):

    registros = []

    for numero_fila, row in enumerate(rows, start=2):

        if not es_carrefour(row, columnas):
            continue

        if not es_sedal(row, columnas):
            continue

        registros.append({
            "fila": numero_fila,
            "fecha": valor_fila(row, columnas["fecha"]),
            "comercio": valor_fila(row, columnas["comercio"]),
            "nombre": valor_fila(row, columnas["nombre"]),
            "ean": valor_fila(row, columnas["ean"]),
            "sku": valor_fila(row, columnas["sku"]),
            "precio": valor_fila(row, columnas["precio"]),
            "disponibilidad": valor_fila(
                row,
                columnas["disponibilidad"]
            ),
            "error": valor_fila(row, columnas["error"]),
            "url": valor_fila(row, columnas["url"]),
            "busqueda": valor_fila(row, columnas["busqueda"]),
        })

    return registros


# ============================================================
# VALORES DE DISPONIBILIDAD
# ============================================================

def analizar_disponibilidad(registros):

    imprimir_separador()
    print("VALORES REALES DE DISPONIBILIDAD")
    imprimir_separador()

    contador = Counter(
        r["disponibilidad"]
        if r["disponibilidad"]
        else "(vacío)"
        for r in registros
    )

    if not contador:
        print("No hay registros.")
        return

    for valor, cantidad in contador.most_common():

        print(
            f"  {valor:35} -> {cantidad}"
        )

    print()


# ============================================================
# EAN / SKU
# ============================================================

def analizar_identificadores(registros):

    imprimir_separador()
    print("ANÁLISIS DE EAN Y SKU")
    imprimir_separador()

    total = len(registros)

    con_ean = sum(
        bool(r["ean"])
        for r in registros
    )

    sin_ean = total - con_ean

    con_sku = sum(
        bool(r["sku"])
        for r in registros
    )

    sin_sku = total - con_sku

    ambos = sum(
        bool(r["ean"]) and bool(r["sku"])
        for r in registros
    )

    ninguno = sum(
        not r["ean"] and not r["sku"]
        for r in registros
    )

    print(f"Total registros:        {total}")
    print(f"Con EAN:                {con_ean}")
    print(f"Sin EAN:                {sin_ean}")
    print(f"Con SKU:                {con_sku}")
    print(f"Sin SKU:                {sin_sku}")
    print(f"Con EAN + SKU:          {ambos}")
    print(f"Sin EAN ni SKU:         {ninguno}")

    print()


# ============================================================
# EAN REPETIDOS
# ============================================================

def analizar_ean_repetidos(registros):

    imprimir_separador()
    print("EAN REPETIDOS")
    imprimir_separador()

    grupos = defaultdict(list)

    for r in registros:

        ean = r["ean"]

        if ean:
            grupos[ean].append(r)

    repetidos = {
        ean: items
        for ean, items in grupos.items()
        if len(items) > 1
    }

    if not repetidos:
        print("No hay EAN repetidos dentro de los registros analizados.")
        print()
        return

    print(
        f"EAN repetidos encontrados: {len(repetidos)}"
    )
    print()

    for ean, items in repetidos.items():

        print(f"EAN: {ean}")
        print(f"  Registros: {len(items)}")

        nombres = sorted(
            set(
                r["nombre"]
                for r in items
                if r["nombre"]
            )
        )

        for nombre in nombres:
            print(f"  Producto: {nombre}")

        skus = sorted(
            set(
                r["sku"]
                for r in items
                if r["sku"]
            )
        )

        if skus:
            print(
                f"  SKU(s): {', '.join(skus)}"
            )

        print()


# ============================================================
# SKU REPETIDOS
# ============================================================

def analizar_sku_repetidos(registros):

    imprimir_separador()
    print("SKU REPETIDOS")
    imprimir_separador()

    grupos = defaultdict(list)

    for r in registros:

        sku = r["sku"]

        if sku:
            grupos[sku].append(r)

    repetidos = {
        sku: items
        for sku, items in grupos.items()
        if len(items) > 1
    }

    if not repetidos:
        print("No hay SKU repetidos dentro de los registros analizados.")
        print()
        return

    print(
        f"SKU repetidos encontrados: {len(repetidos)}"
    )
    print()

    for sku, items in repetidos.items():

        print(f"SKU: {sku}")

        eans = sorted(
            set(
                r["ean"]
                for r in items
                if r["ean"]
            )
        )

        nombres = sorted(
            set(
                r["nombre"]
                for r in items
                if r["nombre"]
            )
        )

        print(
            f"  EAN(s): {', '.join(eans) if eans else '(ninguno)'}"
        )

        for nombre in nombres:
            print(f"  Producto: {nombre}")

        print()


# ============================================================
# REGISTROS SIN EAN
# ============================================================

def analizar_sin_ean(registros):

    imprimir_separador()
    print("REGISTROS SIN EAN")
    imprimir_separador()

    lista = [
        r for r in registros
        if not r["ean"]
    ]

    print(f"Total: {len(lista)}")
    print()

    for r in lista[:MAX_REGISTROS]:

        print(
            f"Fila {r['fila']} | "
            f"SKU={mostrar(r['sku'])} | "
            f"Producto={mostrar(r['nombre'])} | "
            f"Precio={mostrar(r['precio'])} | "
            f"Disponibilidad={mostrar(r['disponibilidad'])}"
        )

    if len(lista) > MAX_REGISTROS:
        print()
        print(
            f"... se muestran solamente los primeros "
            f"{MAX_REGISTROS}"
        )

    print()


# ============================================================
# REGISTROS SIN SKU
# ============================================================

def analizar_sin_sku(registros):

    imprimir_separador()
    print("REGISTROS SIN SKU")
    imprimir_separador()

    lista = [
        r for r in registros
        if not r["sku"]
    ]

    print(f"Total: {len(lista)}")
    print()

    for r in lista[:MAX_REGISTROS]:

        print(
            f"Fila {r['fila']} | "
            f"EAN={mostrar(r['ean'])} | "
            f"Producto={mostrar(r['nombre'])} | "
            f"Precio={mostrar(r['precio'])}"
        )

    if len(lista) > MAX_REGISTROS:
        print()
        print(
            f"... se muestran solamente los primeros "
            f"{MAX_REGISTROS}"
        )

    print()


# ============================================================
# ERRORES
# ============================================================

def analizar_errores(registros):

    imprimir_separador()
    print("ERRORES REGISTRADOS")
    imprimir_separador()

    lista = [
        r for r in registros
        if r["error"]
    ]

    print(f"Registros con error: {len(lista)}")
    print()

    contador = Counter(
        r["error"]
        for r in lista
    )

    for error, cantidad in contador.most_common():

        print(f"{cantidad}x")
        print(f"  {error}")
        print()


# ============================================================
# PRODUCTOS / EAN / SKU
# ============================================================

def analizar_productos(registros):

    imprimir_separador()
    print("PRODUCTOS IDENTIFICADOS")
    imprimir_separador()

    grupos = {}

    for r in registros:

        clave = (
            r["ean"]
            or r["sku"]
            or r["nombre"]
        )

        if clave not in grupos:
            grupos[clave] = []

        grupos[clave].append(r)

    print(
        f"Identificadores/productos distintos: {len(grupos)}"
    )
    print()

    for clave, items in grupos.items():

        ultimo = items[-1]

        print(
            f"ID={clave} | "
            f"EAN={mostrar(ultimo['ean'])} | "
            f"SKU={mostrar(ultimo['sku'])} | "
            f"Precio={mostrar(ultimo['precio'])} | "
            f"Disponibilidad={mostrar(ultimo['disponibilidad'])}"
        )

        print(
            f"    {mostrar(ultimo['nombre'])}"
        )

    print()


# ============================================================
# ÚLTIMOS REGISTROS
# ============================================================

def analizar_ultimos(registros):

    imprimir_separador()
    print("ÚLTIMOS REGISTROS CARREFOUR + SEDAL")
    imprimir_separador()

    # No asumimos que las fechas siempre están en formato ISO.
    # Primero intentamos ordenarlas como texto.
    ordenados = sorted(
        registros,
        key=lambda r: r["fecha"]
    )

    ordenados = ordenados[-MAX_REGISTROS:]

    for r in ordenados:

        print(
            f"Fila {r['fila']} | "
            f"Fecha={mostrar(r['fecha'])}"
        )

        print(
            f"  Producto:       {mostrar(r['nombre'])}"
        )

        print(
            f"  EAN:            {mostrar(r['ean'])}"
        )

        print(
            f"  SKU:            {mostrar(r['sku'])}"
        )

        print(
            f"  Precio:         {mostrar(r['precio'])}"
        )

        print(
            f"  Disponibilidad: {mostrar(r['disponibilidad'])}"
        )

        if r["error"]:
            print(
                f"  ERROR:          {r['error']}"
            )

        if r["url"]:
            print(
                f"  URL:            {r['url']}"
            )

        print()


# ============================================================
# TABLA RESUMIDA
# ============================================================

def imprimir_tabla(registros):

    imprimir_separador()
    print("TABLA RESUMIDA")
    imprimir_separador()

    print(
        f"{'FILA':>5} | "
        f"{'FECHA':19} | "
        f"{'EAN':15} | "
        f"{'SKU':15} | "
        f"{'PRECIO':12} | "
        f"{'DISPONIBILIDAD':20}"
    )

    print("-" * 100)

    for r in registros[-MAX_REGISTROS:]:

        fecha = r["fecha"][:19]

        ean = r["ean"][:15]
        sku = r["sku"][:15]
        precio = r["precio"][:12]
        disponibilidad = r["disponibilidad"][:20]

        print(
            f"{r['fila']:>5} | "
            f"{fecha:19} | "
            f"{ean:15} | "
            f"{sku:15} | "
            f"{precio:12} | "
            f"{disponibilidad:20}"
        )

    print()


# ============================================================
# MAIN
# ============================================================

def main():

    inicio = datetime.now()

    imprimir_separador()
    print("DIAGNÓSTICO CARREFOUR DESDE GOOGLE SHEETS")
    imprimir_separador()

    print()
    print("IMPORTANTE:")
    print("  - Este programa es SOLO LECTURA.")
    print("  - No modifica Google Sheets.")
    print("  - No consulta Carrefour.")
    print("  - Analiza solamente los datos ya registrados.")
    print()

    worksheet = conectar()

    print()
    imprimir_separador()
    print("LECTURA DE LA HOJA")
    imprimir_separador()

    values = worksheet.get_all_values()

    if not values:

        print("ERROR: la hoja está vacía.")
        return

    headers = values[0]
    rows = values[1:]

    print(
        f"Columnas encontradas: {len(headers)}"
    )

    print(
        f"Filas de datos: {len(rows)}"
    )

    print()

    columnas = detectar_columnas(headers)

    imprimir_columnas(
        headers,
        columnas
    )

    # --------------------------------------------------------
    # Verificación mínima
    # --------------------------------------------------------

    if columnas["comercio"] is None:
        print()
        print(
            "ADVERTENCIA: no pude detectar la columna "
            "'comercio'/'sitio'."
        )

    if columnas["nombre"] is None:
        print()
        print(
            "ADVERTENCIA: no pude detectar la columna "
            "'nombre'/'producto'."
        )

    if (
        columnas["ean"] is None
        and columnas["sku"] is None
    ):
        print()
        print(
            "ADVERTENCIA: no se detectó ni EAN ni SKU."
        )

    # --------------------------------------------------------
    # Análisis
    # --------------------------------------------------------

    analizar_general(
        rows,
        columnas
    )

    registros = obtener_registros(
        rows,
        columnas
    )

    imprimir_separador()
    print("REGISTROS ENCONTRADOS PARA CARREFOUR + SEDAL")
    imprimir_separador()

    print(
        f"Total: {len(registros)}"
    )

    print()

    analizar_disponibilidad(
        registros
    )

    analizar_identificadores(
        registros
    )

    analizar_ean_repetidos(
        registros
    )

    analizar_sku_repetidos(
        registros
    )

    analizar_sin_ean(
        registros
    )

    analizar_sin_sku(
        registros
    )

    analizar_errores(
        registros
    )

    analizar_productos(
        registros
    )

    imprimir_tabla(
        registros
    )

    analizar_ultimos(
        registros
    )

    # --------------------------------------------------------
    # Final
    # --------------------------------------------------------

    fin = datetime.now()
    duracion = fin - inicio

    imprimir_separador()
    print("DIAGNÓSTICO TERMINADO")
    imprimir_separador()

    print()
    print(f"Duración: {duracion}")
    print()
    print("NO SE MODIFICÓ NINGÚN DATO.")
    print()

    print(
        "Pegame acá TODA la salida, especialmente:"
    )

    print(
        "  1. COLUMNAS DETECTADAS"
    )

    print(
        "  2. RESUMEN GENERAL"
    )

    print(
        "  3. VALORES REALES DE DISPONIBILIDAD"
    )

    print(
        "  4. ANÁLISIS DE EAN Y SKU"
    )

    print(
        "  5. EAN REPETIDOS"
    )

    print(
        "  6. SKU REPETIDOS"
    )

    print(
        "  7. PRODUCTOS IDENTIFICADOS"
    )

    print(
        "  8. ÚLTIMOS REGISTROS"
    )

    print()


if __name__ == "__main__":
    main()