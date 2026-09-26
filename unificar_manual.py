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
def pedir_identificadores(registros):
    """
    Pide identificadores separados por coma hasta conseguir un conjunto
    válido (2 o más, todos existentes en 'registros'), o hasta que el
    usuario decide terminar con una línea vacía.

    Devuelve la lista de identificadores (sin duplicados, en el orden
    ingresado), o None si el usuario quiere salir.
    """
    while True:
        print("\nIngresá los identificadores a unificar, separados por coma")
        print("(ej: ean:7791293050577, sku:maxiconsumo:11094)")
        print("Dejá vacío y Enter para terminar.")
        linea = input("> ").strip()

        if not linea:
            return None

        crudos = [p.strip() for p in linea.split(",") if p.strip()]

        faltantes = [i for i in crudos if i not in registros]
        if faltantes:
            print("  ⚠️  No encontrado en Match_Productos:")
            for f in faltantes:
                print(f"      - {f}")
            print(
                "  Revisá que estén bien escritos (copiá y pegá de la columna "
                "'identificador')."
            )
            continue

        vistos = set()
        identificadores = []
        for i in crudos:
            if i not in vistos:
                vistos.add(i)
                identificadores.append(i)

        if len(identificadores) < 2:
            print("  ⚠️  Necesitás al menos 2 identificadores distintos.")
            continue

        return identificadores


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
