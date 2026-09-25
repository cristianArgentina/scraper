"""
Recorre "Match_Productos", agrupa identificadores que probablemente sean
el mismo producto (misma línea + nombre parecido) y pide por consola que
el usuario elija el nombre canónico ("grupo_id") para todo el grupo.

Cómo agrupa:
    - Solo compara identificadores DENTRO de la misma línea (columna
      "linea"), para no mezclar productos de líneas distintas.
    - Compara los nombres detectados de cada identificador con
      difflib.SequenceMatcher. Si dos identificadores comparten al menos
      un par de nombres con similitud >= UMBRAL_SIMILITUD, se consideran
      candidatos a ser el mismo producto (unión por Union-Find).
    - Un identificador puede tener más de un "nombre_detectado" (si el
      texto varía levemente entre lecturas): se usan TODOS sus nombres
      para comparar.
    - ANTES de unir dos identificadores por similitud de texto, se
      extrae la cantidad de cada nombre (número + unidad: ml, cc, g,
      kg, l, un, etc). Si ambos nombres tienen una cantidad detectada y
      son DISTINTAS (ej. "400ml" vs "200ml"), la unión se bloquea sin
      importar cuán parecido sea el resto del texto — porque un cambio
      de contenido/tamaño es, para nosotros, un producto distinto. Si
      no se puede detectar cantidad en alguno de los dos nombres, no se
      bloquea (se deja decidir por similitud de texto nomás).

Qué hace con la decisión del usuario:
    - Si el usuario confirma el cluster: escribe el mismo texto en la
      columna "grupo_id" para TODAS las filas (todos los identificadores)
      de ese cluster.
    - Si el usuario lo saltea: no toca nada, se puede correr el script de
      nuevo más adelante y va a volver a aparecer.
    - Los clusters donde TODOS los identificadores ya tienen el mismo
      grupo_id (no vacío) se consideran ya resueltos y no se preguntan de
      nuevo.
    - Cada decisión se guarda en el Sheet al toque (no al final), para no
      perder trabajo si se corta a la mitad (Ctrl+C).

Requisitos:
    pip3 install gspread google-auth --break-system-packages

Uso:
    python3 unificar_grupos.py
"""

import os
import re
import json
from difflib import SequenceMatcher

import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------
# CONFIGURACIÓN
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"

NOMBRE_HOJA_MATCH = "Match_Productos"

UMBRAL_SIMILITUD = 0.90  # 0-1. Más alto = más estricto (menos falsos positivos).


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


def limpiar(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def similitud(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# -----------------------------------------------------------------------
# CANTIDADES (número + unidad: ml, cc, g, kg, l, un, etc)
#
# Dos nombres casi idénticos que solo difieren en la cantidad
# ("... 400 ml" vs "... 200 ml") son, para nosotros, PRODUCTOS
# DISTINTOS, aunque el texto sea 95% igual. Por eso esto no se resuelve
# con el umbral de similitud (subirlo no alcanza), sino con una regla
# aparte que compara cantidades explícitamente.
# -----------------------------------------------------------------------
PATRON_CANTIDAD = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ml|cc|grs?|g|kgs?|kg|lts?|l|un|u)\b",
    re.IGNORECASE,
)

# Fallback para cuando el tamaño va como número suelto, sin unidad
# explícita en el nombre (ej. líneas como "Nivea Creme 150" / "... 400",
# o "Cicatricure 400" / "Cicatricure 60"). Solo se usa si PATRON_CANTIDAD
# no encontró nada, para no pisar la detección con unidad (más confiable).
PATRON_NUMERO_SUELTO = re.compile(r"\b(\d{2,4})\b")

# Unidades equivalentes: se normalizan al mismo bucket para no marcar
# como "cantidad distinta" algo que en realidad es la misma unidad
# escrita de otra forma (400ml == 400cc).
NORMALIZACION_UNIDADES = {
    "cc": "ml",
    "ml": "ml",
    "gr": "g",
    "grs": "g",
    "g": "g",
    "kg": "kg",
    "kgs": "kg",
    "l": "l",
    "lt": "l",
    "lts": "l",
    "u": "un",
    "un": "un",
}


def extraer_cantidades(nombre):
    """
    Devuelve un set de tuplas (numero_normalizado, unidad_normalizada)
    encontradas en el nombre. Ej: "Sedal 340 ml" -> {("340", "ml")}
    """
    encontrados = set()
    for match in PATRON_CANTIDAD.finditer(nombre or ""):
        numero = match.group(1).replace(",", ".").lstrip("0") or "0"
        unidad = NORMALIZACION_UNIDADES.get(match.group(2).lower(), match.group(2).lower())
        encontrados.add((numero, unidad))

    if not encontrados:
        for match in PATRON_NUMERO_SUELTO.finditer(nombre or ""):
            numero = match.group(1).lstrip("0") or "0"
            encontrados.add((numero, ""))  # unidad vacía = "número suelto"

    return encontrados


def cantidades_compatibles(nombres_a, nombres_b):
    """
    True si existe al menos un par (nombre de A, nombre de B) cuyas
    cantidades no entran en conflicto: o comparten alguna cantidad, o no
    se pudo detectar cantidad en alguno de los dos (no hay suficiente
    información para bloquear).

    False solo cuando TODOS los nombres de ambos lados tienen cantidad
    detectada y NINGÚN par coincide (ej. uno siempre dice 400ml y el
    otro siempre 200ml).
    """
    hubo_par_con_datos = False

    for na in nombres_a:
        cant_a = extraer_cantidades(na)
        for nb in nombres_b:
            cant_b = extraer_cantidades(nb)

            if not cant_a or not cant_b:
                return True  # falta info en algún lado: no bloqueamos

            hubo_par_con_datos = True
            if cant_a & cant_b:
                return True  # comparten al menos una cantidad

    # Si llegamos acá, todos los pares tenían cantidad y ninguno coincidió.
    return not hubo_par_con_datos


# -----------------------------------------------------------------------
# UNION-FIND (para armar los clusters)
# -----------------------------------------------------------------------
class UnionFind:
    def __init__(self, elementos):
        self.padre = {e: e for e in elementos}

    def encontrar(self, x):
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unir(self, a, b):
        ra, rb = self.encontrar(a), self.encontrar(b)
        if ra != rb:
            self.padre[ra] = rb


# -----------------------------------------------------------------------
# CARGA DE DATOS
# -----------------------------------------------------------------------
def cargar_match_productos(hoja):
    """
    Devuelve:
        registros: {identificador: {"nombres": set(...), "linea": str,
                                     "sitios": str, "grupo_id": str,
                                     "filas": [num_fila, ...]}}
        (un identificador puede ocupar varias filas si tiene más de un
         nombre_detectado distinto)
    """
    valores = hoja.get_all_values()

    if not valores:
        return {}

    encabezados = [limpiar(v).lower() for v in valores[0]]

    i_id = encabezados.index("identificador")
    i_nombre = encabezados.index("nombre_detectado")
    i_linea = encabezados.index("linea")
    i_sitios = encabezados.index("sitios") if "sitios" in encabezados else -1
    i_grupo = encabezados.index("grupo_id") if "grupo_id" in encabezados else -1

    if i_grupo == -1:
        raise RuntimeError(
            f"La hoja '{NOMBRE_HOJA_MATCH}' no tiene columna 'grupo_id'. "
            "Corré primero generar_match_productos.py."
        )

    registros = {}

    for num_fila, fila in enumerate(valores[1:], start=2):
        identificador = fila[i_id].strip() if i_id < len(fila) else ""
        if not identificador:
            continue

        nombre = fila[i_nombre].strip() if i_nombre < len(fila) else ""
        linea = fila[i_linea].strip() if i_linea < len(fila) else ""
        sitios = fila[i_sitios].strip() if 0 <= i_sitios < len(fila) else ""
        grupo_id = fila[i_grupo].strip() if i_grupo < len(fila) else ""

        if identificador not in registros:
            registros[identificador] = {
                "nombres": set(),
                "linea": linea,
                "sitios": set(),
                "grupo_id": "",
                "filas": [],
            }

        reg = registros[identificador]
        if nombre:
            reg["nombres"].add(nombre)
        if sitios:
            reg["sitios"].update(s.strip() for s in sitios.split(",") if s.strip())
        if grupo_id:
            # si hay varias filas con distinto grupo_id ya cargado (no
            # debería pasar en uso normal), nos quedamos con el último no vacío
            reg["grupo_id"] = grupo_id
        if not reg["linea"]:
            reg["linea"] = linea
        reg["filas"].append(num_fila)

    return registros


# -----------------------------------------------------------------------
# ARMADO DE CLUSTERS
# -----------------------------------------------------------------------
def armar_clusters(registros):
    """
    Devuelve: {linea: [ [identificador, identificador, ...], ... ]}
    Cada lista interna es un cluster (grupo de identificadores que
    probablemente son el mismo producto).
    """
    por_linea = {}
    for identificador, datos in registros.items():
        por_linea.setdefault(datos["linea"], []).append(identificador)

    clusters_por_linea = {}

    for linea, ids in por_linea.items():
        uf = UnionFind(ids)

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a, id_b = ids[i], ids[j]
                nombres_a = registros[id_a]["nombres"]
                nombres_b = registros[id_b]["nombres"]

                mejor = 0.0
                for na in nombres_a:
                    for nb in nombres_b:
                        mejor = max(mejor, similitud(na, nb))

                if mejor >= UMBRAL_SIMILITUD and cantidades_compatibles(
                    nombres_a, nombres_b
                ):
                    uf.unir(id_a, id_b)

        grupos = {}
        for identificador in ids:
            raiz = uf.encontrar(identificador)
            grupos.setdefault(raiz, []).append(identificador)

        # Solo nos interesan los clusters con más de un identificador
        # (los de un solo elemento no necesitan unificación).
        clusters_por_linea[linea] = [g for g in grupos.values() if len(g) > 1]

    return clusters_por_linea


def cluster_ya_resuelto(cluster, registros):
    grupo_ids = {registros[i]["grupo_id"] for i in cluster}
    return len(grupo_ids) == 1 and "" not in grupo_ids


# -----------------------------------------------------------------------
# INTERACCIÓN POR CONSOLA
# -----------------------------------------------------------------------
def preguntar_decision(cluster, registros):
    """
    Muestra el cluster al usuario y devuelve:
        - el texto elegido como grupo_id (string), o
        - None si el usuario decide saltear.
    """
    print("\n" + "=" * 70)
    print(f"Línea: {registros[cluster[0]]['linea']}")
    print("Posible mismo producto en estos identificadores:\n")

    opciones = []  # nombres candidatos, en orden, para permitir elegir por número

    for identificador in cluster:
        datos = registros[identificador]
        sitios_txt = ", ".join(sorted(datos["sitios"])) or "?"
        grupo_actual = datos["grupo_id"] or "(sin grupo_id)"
        print(f"  - {identificador}  [{sitios_txt}]  grupo_id actual: {grupo_actual}")
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

    print("\nOpciones:")
    for idx, nombre in enumerate(opciones, start=1):
        print(f"  [{idx}] {nombre}")
    print("  [t] escribir un nombre canónico distinto")
    print("  [s] saltear (no unificar este cluster)")

    while True:
        respuesta = input("Elegí una opción: ").strip().lower()

        if respuesta == "s":
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
# GUARDADO
# -----------------------------------------------------------------------
def guardar_grupo_id(hoja, cluster, registros, grupo_id, encabezados_col_grupo):
    celdas = []
    for identificador in cluster:
        for num_fila in registros[identificador]["filas"]:
            celdas.append(
                gspread.Cell(row=num_fila, col=encabezados_col_grupo, value=grupo_id)
            )
        registros[identificador]["grupo_id"] = grupo_id

    if celdas:
        hoja.update_cells(celdas, value_input_option="USER_ENTERED")


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
    col_grupo_id = encabezados_lower.index("grupo_id") + 1  # 1-indexed para gspread

    registros = cargar_match_productos(hoja)
    print(f"[INFO] {len(registros)} identificadores cargados de '{NOMBRE_HOJA_MATCH}'.")

    clusters_por_linea = armar_clusters(registros)

    total_clusters = sum(len(c) for c in clusters_por_linea.values())
    print(f"[INFO] {total_clusters} clusters candidatos encontrados (similitud >= {UMBRAL_SIMILITUD}).")

    pendientes = 0
    ya_resueltos = 0
    unificados_ahora = 0
    salteados = 0

    for linea, clusters in clusters_por_linea.items():
        for cluster in clusters:
            if cluster_ya_resuelto(cluster, registros):
                ya_resueltos += 1
                continue

            pendientes += 1
            decision = preguntar_decision(cluster, registros)

            if decision is None:
                salteados += 1
                continue

            guardar_grupo_id(hoja, cluster, registros, decision, col_grupo_id)
            unificados_ahora += 1
            print(f"  -> Guardado grupo_id = '{decision}' para {len(cluster)} identificadores.")

    print("\n=== RESUMEN ===")
    print(f"Clusters ya resueltos previamente: {ya_resueltos}")
    print(f"Clusters pendientes revisados:     {pendientes}")
    print(f"  - Unificados en esta corrida:    {unificados_ahora}")
    print(f"  - Salteados:                     {salteados}")
    print("\nListo. Corré este script de nuevo cuando aparezcan identificadores nuevos.")


if __name__ == "__main__":
    main()
