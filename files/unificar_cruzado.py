"""
unificar_cruzado.py

Segunda pasada sobre "Match_Productos", pensada para los casos que
unificar_grupos.py no ataca: conectar identificadores que todavía no
tienen grupo_id (típicamente SKU sin EAN -p.ej. combos armados-) con:

    a) otros SKU de OTROS sitios (mismo combo vendido en otro lado), o
    b) identificadores/grupos ya armados en otros sitios (p.ej. un
       producto que en Maxiconsumo aparece con EAN y ese EAN ya forma
       parte de un grupo_id armado desde otra fuente).

Se corre DESPUÉS de unificar_grupos.py, sobre la misma hoja
"Match_Productos", y usa las mismas columnas (solo completa grupo_id
donde falte). Requiere estar en la misma carpeta que
unificar_grupos.py porque importa sus funciones.

-----------------------------------------------------------------------
Diferencia clave con unificar_grupos.py
-----------------------------------------------------------------------
unificar_grupos.py compara CUALQUIER par de identificadores de la
misma línea, sin mirar de dónde viene cada uno. Eso está bien para lo
que ya resolvió, pero abre la puerta a falsos positivos si se lo usa
para este caso nuevo: dos identificadores del MISMO sitio con nombre
parecido casi siempre son productos DISTINTOS (variantes, sabores,
tamaños), no el mismo producto con dos códigos.

Este script asume que "identificador" tiene uno de estos formatos:
    ean:<codigo>
    sku:<sitio>:<codigo>
(si no matchea ninguno, se trata como tipo "otro" y no se cruza con
nada, para no arriesgar una unión sin base).

Con tipo y sitio ya identificados, aplica esta regla de seguridad
antes de considerar dos identificadores como candidatos:

    - Mismo tipo (sku-sku o ean-ean) Y comparten al menos un sitio
      -> SE BLOQUEA. No se unen automáticamente, sin importar cuán
         parecido sea el nombre. La excepción real (mismo producto con
         2 EAN por un cambio leve de packaging) se resuelve a mano:
         no va a aparecer como cluster acá, hay que unificarla
         directamente en el Sheet.

    - Tipo distinto (sku vs ean), aunque compartan sitio -> NO se
      bloquea. Es normal que un sitio liste el mismo producto con su
      SKU interno Y con su EAN; ese es justamente uno de los casos que
      queremos poder emparejar.

    - Mismo tipo pero sitios distintos (o uno de los dos sin sitio
      registrado) -> NO se bloquea. Es el caso "SKU de un combo en el
      sitio A" vs "SKU de ese mismo combo en el sitio B", o "EAN visto
      en Maxiconsumo" vs "EAN visto en otro sitio ya agrupado".

Además, por default, el script NO intenta fusionar dos identificadores
que ya tienen grupo_id distinto y no vacío (dos grupos que un humano
ya confirmó como separados en una corrida anterior). Esto se puede
desactivar con PERMITIR_FUSIONAR_GRUPOS_YA_DISTINTOS = True si en algún
momento se quiere revisar también esos casos.

Requisitos / uso: iguales a unificar_grupos.py.

    python3 unificar_cruzado.py
"""

import gspread

from unificar_grupos import (
    SPREADSHEET_ID,
    NOMBRE_HOJA_MATCH,
    obtener_credenciales_google,
    limpiar,
    similitud,
    extraer_cantidades,
    cantidades_compatibles,
    UnionFind,
    cargar_match_productos,
    guardar_grupo_id,
)

# -----------------------------------------------------------------------
# CONFIGURACIÓN
# -----------------------------------------------------------------------
UMBRAL_SIMILITUD_CRUZADO = 0.75  # se puede afinar aparte del umbral original
PERMITIR_FUSIONAR_GRUPOS_YA_DISTINTOS = False


# -----------------------------------------------------------------------
# TIPO Y SITIO A PARTIR DEL IDENTIFICADOR
# -----------------------------------------------------------------------
def parsear_identificador(identificador):
    """
    "ean:7791293050577"      -> ("ean", None, "7791293050577")
    "sku:maxiconsumo:11094"  -> ("sku", "maxiconsumo", "11094")
    cualquier otra cosa      -> ("otro", None, identificador)
    """
    partes = identificador.split(":")

    if len(partes) >= 2 and partes[0].lower() == "ean":
        return "ean", None, partes[1]

    if len(partes) >= 3 and partes[0].lower() == "sku":
        return "sku", partes[1], partes[2]

    return "otro", None, identificador


def sitios_de(identificador, registros):
    """
    Sitios asociados a un identificador: el sitio embebido en el propio
    identificador (si es sku:sitio:codigo) combinado con lo que haya
    cargado en la columna "sitios" del Sheet, por si el dato está ahí
    en vez de (o además de) en el identificador.
    """
    _tipo, sitio_embebido, _codigo = parsear_identificador(identificador)
    sitios = set(registros.get(identificador, {}).get("sitios", set()))
    if sitio_embebido:
        sitios.add(sitio_embebido)
    return sitios


def bloqueado_por_mismo_sitio(id_a, id_b, registros):
    """
    True si id_a e id_b son del mismo tipo (sku-sku o ean-ean) Y
    comparten al menos un sitio -> no se consideran candidatos
    automáticos (ver explicación al inicio del archivo).
    """
    tipo_a, _, _ = parsear_identificador(id_a)
    tipo_b, _, _ = parsear_identificador(id_b)

    if tipo_a != tipo_b:
        return False

    return bool(sitios_de(id_a, registros) & sitios_de(id_b, registros))


# -----------------------------------------------------------------------
# ARMADO DE CLUSTERS (misma idea que armar_clusters, con las reglas de
# bloqueo agregadas)
# -----------------------------------------------------------------------
def armar_clusters_cruzados(registros):
    por_linea = {}
    for identificador, datos in registros.items():
        por_linea.setdefault(datos["linea"], []).append(identificador)

    clusters_por_linea = {}

    for linea, ids in por_linea.items():
        uf = UnionFind(ids)

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a, id_b = ids[i], ids[j]

                if bloqueado_por_mismo_sitio(id_a, id_b, registros):
                    continue

                grupo_a = registros[id_a]["grupo_id"]
                grupo_b = registros[id_b]["grupo_id"]
                if (
                    not PERMITIR_FUSIONAR_GRUPOS_YA_DISTINTOS
                    and grupo_a
                    and grupo_b
                    and grupo_a != grupo_b
                ):
                    continue  # ya confirmados como grupos distintos antes

                nombres_a = registros[id_a]["nombres"]
                nombres_b = registros[id_b]["nombres"]

                mejor = 0.0
                for na in nombres_a:
                    for nb in nombres_b:
                        mejor = max(mejor, similitud(na, nb))

                if mejor >= UMBRAL_SIMILITUD_CRUZADO and cantidades_compatibles(
                    nombres_a, nombres_b
                ):
                    uf.unir(id_a, id_b)

        grupos = {}
        for identificador in ids:
            raiz = uf.encontrar(identificador)
            grupos.setdefault(raiz, []).append(identificador)

        clusters_por_linea[linea] = [g for g in grupos.values() if len(g) > 1]

    return clusters_por_linea


def cluster_ya_resuelto(cluster, registros):
    grupo_ids = {registros[i]["grupo_id"] for i in cluster}
    return len(grupo_ids) == 1 and "" not in grupo_ids


# -----------------------------------------------------------------------
# INTERACCIÓN POR CONSOLA
# -----------------------------------------------------------------------
def preguntar_decision_cruzado(cluster, registros):
    print("\n" + "=" * 70)
    print(f"Línea: {registros[cluster[0]]['linea']}")

    grupos_existentes = sorted(
        {registros[i]["grupo_id"] for i in cluster if registros[i]["grupo_id"]}
    )
    if len(grupos_existentes) > 1:
        print("\n⚠️  CONFLICTO: este cluster mezcla grupos YA CONFIRMADOS distintos:")
        for g in grupos_existentes:
            print(f"    - {g!r}")
        print("   Revisar con cuidado antes de confirmar.\n")

    print("Posible mismo producto en estos identificadores:\n")

    opciones = list(grupos_existentes)  # prioridad: nombres canónicos ya existentes

    for identificador in cluster:
        datos = registros[identificador]
        tipo, sitio_embebido, _codigo = parsear_identificador(identificador)
        sitios_txt = ", ".join(sorted(datos["sitios"])) or (sitio_embebido or "?")
        grupo_actual = datos["grupo_id"] or "(sin grupo_id)"
        print(
            f"  - {identificador}  [tipo={tipo}, sitios={sitios_txt}]  "
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

    clusters_por_linea = armar_clusters_cruzados(registros)

    total_clusters = sum(len(c) for c in clusters_por_linea.values())
    print(
        f"[INFO] {total_clusters} clusters cruzados candidatos "
        f"(similitud >= {UMBRAL_SIMILITUD_CRUZADO})."
    )

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
            decision = preguntar_decision_cruzado(cluster, registros)

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
