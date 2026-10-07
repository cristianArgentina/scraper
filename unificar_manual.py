"""
unificar_manual.py

Tercer script de la familia de unificación. A diferencia de
unificar_grupos.py y unificar_cruzado.py (que proponen clusters
automáticamente por similitud de nombre), acá el usuario indica A MANO
qué identificadores (EAN y/o SKU, dos o más) corresponden al mismo
producto -por ejemplo porque los vio en el frontend, comparando
comercios, y notó que son el mismo producto aunque los nombres sean
muy distintos entre sitios- y el script se limita a: mostrar los datos
de cada uno, ofrecer los nombres existentes (o el/los grupo_id ya
cargados) como opciones para elegir, o dejar escribir uno nuevo, y
guardar la decisión. Es la "válvula de escape" para los casos que los
otros dos scripts no van a detectar solos (nombres demasiado
distintos, abreviaturas raras, productos que el algoritmo separó por
error, etc.).

A propósito NO aplica ningún filtro de similitud, cantidad, ni de
sitio/tipo: esa validación ya la hizo el usuario a ojo. Sí avisa si los
identificadores elegidos ya tienen grupo_id distintos cargados entre
sí, para que un error de tipeo no termine juntando dos grupos que en
realidad eran productos distintos ya confirmados.

Requisitos / uso: iguales a los otros dos scripts. Correr desde la
misma carpeta (importa funciones de unificar_grupos.py).

    python3 unificar_manual.py

En cada iteración pide los identificadores separados por coma, por
ejemplo:

    ean:7791293050577, sku:maxiconsumo:11094

Enter con la línea vacía termina el script.
"""

import gspread
import re
import unicodedata

from unificar_grupos import (
    SPREADSHEET_ID,
    NOMBRE_HOJA_MATCH,
    obtener_credenciales_google,
    limpiar,
    extraer_cantidades,
    cargar_match_productos,
    guardar_grupo_id,
)


# -----------------------------------------------------------------------
# PEDIR IDENTIFICADORES AL USUARIO
# -----------------------------------------------------------------------
def normalizar_texto(texto):
    """Normaliza texto para comparar nombres de comercios sin importar
    mayúsculas, espacios, acentos o signos."""
    texto = str(texto).strip().lower()

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )

    return re.sub(r"[^a-z0-9]", "", texto)


def formatear_identificador_amigable(identificador):
    """
    Convierte el identificador interno al formato que ve el usuario
    en el frontend.

    ean:7791293050577
        -> EAN 7791293050577

    sku:maxiconsumo:28361
        -> SKU 28361 (Maxiconsumo)
    """
    identificador = str(identificador).strip()

    if identificador.lower().startswith("ean:"):
        return f"EAN {identificador[4:]}"

    match = re.match(
        r"^sku:([^:]+):(.+)$",
        identificador,
        re.IGNORECASE
    )

    if match:
        sitio = match.group(1)
        sku = match.group(2)

        # Para la mayoría de los comercios el ID interno ya coincide
        # con el nombre que muestra el frontend.
        nombre_comercio = sitio.replace("_", " ").replace("-", " ").strip()

        # Capitalización más agradable:
        nombre_comercio = nombre_comercio.title()

        return f"SKU {sku} ({nombre_comercio})"

    return identificador


def resolver_identificador_amigable(entrada, registros):
    """
    Convierte lo que escribe/pega el usuario al identificador interno.

    Acepta:

        EAN 7791293050577
        ean:7791293050577

        SKU 28361 (Maxiconsumo)
        sku:maxiconsumo:28361

    También intenta resolver el nombre del comercio aunque haya
    diferencias de mayúsculas, espacios, guiones o acentos.
    """

    entrada = str(entrada).strip()

    if not entrada:
        return None

    # ---------------------------------------------------------
    # 1. Ya viene en formato interno: lo dejamos pasar.
    # ---------------------------------------------------------
    if re.match(r"^ean:[^:]+$", entrada, re.IGNORECASE):
        candidato = entrada.lower()

        if candidato in registros:
            return candidato

        return None

    if re.match(r"^sku:[^:]+:.+$", entrada, re.IGNORECASE):
        candidato = entrada.lower()

        if candidato in registros:
            return candidato

        return None

    # ---------------------------------------------------------
    # 2. EAN amigable
    #    Ej: EAN 7791293050577
    # ---------------------------------------------------------
    match_ean = re.match(
        r"^ean\s*[:\-]?\s*(\d+)$",
        entrada,
        re.IGNORECASE
    )

    if match_ean:
        numero = match_ean.group(1)

        candidato = f"ean:{numero}".lower()

        if candidato in registros:
            return candidato

        # Por si los registros no están en minúsculas
        for identificador in registros:
            if str(identificador).lower() == candidato:
                return identificador

        return None

    # ---------------------------------------------------------
    # 3. SKU amigable
    #    Ej: SKU 28361 (Maxiconsumo)
    # ---------------------------------------------------------
    match_sku = re.match(
        r"^sku\s*[:\-]?\s*(.+?)\s*\(\s*(.+?)\s*\)\s*$",
        entrada,
        re.IGNORECASE
    )

    if match_sku:
        sku = match_sku.group(1).strip()
        comercio = match_sku.group(2).strip()

        comercio_normalizado = normalizar_texto(comercio)

        candidatos = []

        for identificador in registros:
            identificador_str = str(identificador).strip()

            match_interno = re.match(
                r"^sku:([^:]+):(.+)$",
                identificador_str,
                re.IGNORECASE
            )

            if not match_interno:
                continue

            sitio = match_interno.group(1)
            sku_interno = match_interno.group(2)

            # El SKU debe coincidir exactamente
            if sku_interno.lower() != sku.lower():
                continue

            sitio_normalizado = normalizar_texto(sitio)

            # Maxiconsumo == maxiconsumo
            # Farma Online == farmaonline
            # etc.
            if sitio_normalizado == comercio_normalizado:
                candidatos.append(identificador_str)

        if len(candidatos) == 1:
            return candidatos[0]

        if len(candidatos) > 1:
            return candidatos

        return None

    return None


def pedir_identificadores(registros):
    """
    Solicita identificadores de manera amigable.

    Se pueden pegar:
        EAN 7791293050577
        SKU 28361 (Maxiconsumo)

    Uno por línea o separados por coma.

    También sigue aceptando el formato interno anterior por
    compatibilidad.
    """

    print()
    print("─" * 70)
    print("IDENTIFICADORES")
    print("─" * 70)
    print("Pegá los identificadores tal como aparecen en el frontend.")
    print()
    print("Ejemplos:")
    print("  EAN 7791293050577")
    print("  SKU 28361 (Maxiconsumo)")
    print()
    print("Podés pegar varios, uno por línea o separados por coma.")
    print("No hace falta escribir ningún ':'")
    print()

    while True:
        entrada = input("Identificadores: ").strip()

        if not entrada:
            print("No se ingresaron identificadores.")
            continue

        # -----------------------------------------------------
        # Permitir varias líneas y también comas.
        # -----------------------------------------------------
        partes = []

        for linea in entrada.splitlines():
            partes.extend(linea.split(","))

        partes = [
            parte.strip()
            for parte in partes
            if parte.strip()
        ]

        identificadores = []

        for parte in partes:
            resultado = resolver_identificador_amigable(
                parte,
                registros
            )

            # No encontrado
            if resultado is None:
                print()
                print(f"⚠️  No encontré: {parte}")
                print(
                    "    Verificá que esté escrito igual que "
                    "en el frontend."
                )
                continue

            # Ambiguo
            if isinstance(resultado, list):
                print()
                print(f"⚠️  El identificador es ambiguo: {parte}")
                print("    Encontré varias coincidencias:")

                for candidato in resultado:
                    print(
                        f"      - "
                        f"{formatear_identificador_amigable(candidato)}"
                    )

                print(
                    "    Especificá mejor el comercio."
                )
                continue

            if resultado not in identificadores:
                identificadores.append(resultado)

        if identificadores:
            print()
            print("Identificadores reconocidos:")

            for identificador in identificadores:
                print(
                    f"  ✓ {formatear_identificador_amigable(identificador)}"
                )

            print()

            confirmar = input(
                "¿Son correctos? [Enter = sí / n = volver a ingresar]: "
            ).strip().lower()

            if confirmar in ("", "s", "si", "sí"):
                return identificadores

        else:
            print()
            print("No se pudo reconocer ningún identificador.")
            print("Intentá nuevamente.")


# -----------------------------------------------------------------------
# MOSTRAR / PREGUNTAR
# -----------------------------------------------------------------------
def mostrar_grupo(identificadores, registros):
    """Imprime los datos del grupo elegido y devuelve la lista de
    opciones de nombre (grupo_id existentes primero, después nombres
    detectados)."""
    print("\n" + "=" * 70)

    grupos_existentes = sorted(
        {registros[i]["grupo_id"] for i in identificadores if registros[i]["grupo_id"]}
    )
    if len(grupos_existentes) > 1:
        print("⚠️  Estos identificadores ya tienen grupo_id DISTINTOS cargados:")
        for g in grupos_existentes:
            print(f"    - {g!r}")
        print("   Si confirmás, se van a unificar todos bajo el mismo nombre.\n")

    opciones = list(grupos_existentes)

    for identificador in identificadores:
        datos = registros[identificador]
        sitios_txt = ", ".join(sorted(datos["sitios"])) or "?"
        grupo_actual = datos["grupo_id"] or "(sin grupo_id)"
        print(
            f"  - {identificador}  [línea: {datos['linea']}, sitios: {sitios_txt}]  "
            f"grupo_id actual: {grupo_actual}"
        )
        for nombre in sorted(datos["nombres"]):
            if nombre not in opciones:
                opciones.append(nombre)
            cantidades = extraer_cantidades(nombre)
            etiqueta_cantidad = (
                f"  [{', '.join(f'{n} {u}' for n, u in sorted(cantidades))}]"
                if cantidades
                else "  [sin cantidad detectada]"
            )
            print(f"      · {nombre}{etiqueta_cantidad}")

    return opciones


def preguntar_decision_manual(identificadores, registros):
    opciones = mostrar_grupo(identificadores, registros)

    print("\nOpciones:")
    for idx, nombre in enumerate(opciones, start=1):
        print(f"  [{idx}] {nombre}")
    print("  [t] escribir un nombre canónico distinto")
    print("  [c] cancelar (no unificar este grupo)")

    while True:
        respuesta = input("Elegí una opción: ").strip().lower()

        if respuesta == "c":
            return None

        if respuesta == "t":
            texto = input("Escribí el nombre canónico: ").strip()
            if texto:
                return texto
            print("  (vacío, probá de nuevo)")
            continue

        if respuesta.isdigit():
            i = int(respuesta)
            if 1 <= i <= len(opciones):
                return opciones[i - 1]

        print("  Opción inválida.")


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------
def main():
    creds = obtener_credenciales_google()
    cliente = gspread.authorize(creds)
    planilla = cliente.open_by_key(SPREADSHEET_ID)

    hoja = planilla.worksheet(NOMBRE_HOJA_MATCH)

    valores_encabezado = hoja.row_values(1)
    encabezados_lower = [limpiar(v).lower() for v in valores_encabezado]
    col_grupo_id = encabezados_lower.index("grupo_id") + 1

    registros = cargar_match_productos(hoja)
    print(f"[INFO] {len(registros)} identificadores cargados de '{NOMBRE_HOJA_MATCH}'.")

    unificados = 0

    while True:
        identificadores = pedir_identificadores(registros)
        if identificadores is None:
            break

        decision = preguntar_decision_manual(identificadores, registros)
        if decision is None:
            print("  Cancelado.")
            continue

        guardar_grupo_id(hoja, identificadores, registros, decision, col_grupo_id)
        unificados += 1
        print(f"  -> Guardado grupo_id = '{decision}' para {len(identificadores)} identificadores.")

    print("\n=== RESUMEN ===")
    print(f"Grupos unificados manualmente: {unificados}")
    print("\nListo.")


if __name__ == "__main__":
    main()
