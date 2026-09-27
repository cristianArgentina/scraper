"""
reparar_imagenes.py

Script chico para completar imágenes faltantes en la pestaña
Imagenes_Productos SIN correr la búsqueda de precios completa.

Por qué es mucho más rápido que buscador_precios.py:
    Lo que tarda los ~25 minutos de la corrida diaria es la simulación
    de checkout de VTEX (obtener_precio_simulacion_promo_2u): una
    request por producto por sitio, con pausas entre cada una. Este
    script NO llama a esa función en ningún momento — solo busca
    productos (VTEX y Magento) y, si les falta imagen, la completa.
    No escribe nada en Precios_Log_Lineas.

Requisito: tiene que vivir en la misma carpeta que buscador_precios.py,
porque lo importa como módulo para reutilizar toda su configuración
(LINEAS, SITIOS_VTEX, SITIOS_MAGENTO) y sus funciones (búsqueda,
filtros, caché de imágenes, fallback de imagen de detalle, etc.), así
nunca queda desincronizado de la lógica del script diario.

Uso:
    python3 reparar_imagenes.py
"""

import buscador_precios as bp


def procesar_vtex(linea, planilla_no_usada=None):
    for sitio in bp.SITIOS_VTEX:
        termino = linea.get("busqueda_por_sitio", {}).get(
            sitio["sitio"], linea["busqueda"]
        )

        productos, error = bp.buscar_productos_vtex(sitio["dominio"], termino)

        if error:
            print(f"  [ERROR] {sitio['sitio']}: {error}")
            continue

        for prod in productos:
            if (
                linea.get("aplicar_incluir_en_vtex")
                and not bp.pasa_filtro_inclusion(
                    prod["nombre"], linea.get("incluir", [])
                )
                and not bp.incluido_por_sku_forzado(
                    prod.get("sku_id"), sitio["sitio"], linea
                )
            ):
                continue

            if not bp.pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                continue

            if bp.ean_excluido(prod.get("ean"), sitio["sitio"]):
                continue

            # Si ya tiene imagen cacheada, ni vale la pena mirarlo.
            clave = bp.clave_imagen(prod.get("ean"), prod.get("sku_id"), sitio["sitio"])
            if clave and clave in bp.CACHE_IMAGENES:
                continue

            imagen = prod.get("imageurl")

            if not imagen and prod.get("link"):
                imagen = bp.obtener_imagen_de_pagina(prod["link"])

            if imagen and (prod.get("ean") or prod.get("sku_id")):
                if bp.registrar_imagen(
                    prod.get("ean"), prod.get("sku_id"), imagen, sitio["sitio"]
                ):
                    print(f"  [OK] {sitio['sitio']}: {prod['nombre']}")

        bp.pausa_entre_pedidos()


def procesar_magento(linea):
    for sitio_m in bp.SITIOS_MAGENTO:
        productos, error = bp.buscar_productos_magento(
            sitio_m["dominio"], sitio_m["sucursal"], linea["busqueda"]
        )

        if error:
            print(f"  [ERROR] {sitio_m['sitio']}: {error}")
            continue

        for prod in productos:
            if not bp.pasa_filtro_inclusion(
                prod["nombre"], linea.get("incluir", [])
            ) and not bp.incluido_por_sku_forzado(
                prod.get("sku_id"), sitio_m["sitio"], linea
            ):
                continue

            if not bp.pasa_filtro_exclusion(prod["nombre"], linea["excluir"]):
                continue

            if bp.sku_excluido(prod.get("sku_id"), sitio_m["sitio"]):
                continue

            clave = bp.clave_imagen(None, prod.get("sku_id"), sitio_m["sitio"])
            if clave and clave in bp.CACHE_IMAGENES:
                continue

            imagen = prod.get("imageurl")

            if not imagen and prod.get("url"):
                imagen = bp.obtener_imagen_de_pagina(prod["url"])

            if imagen and prod.get("sku_id"):
                if bp.registrar_imagen(
                    None, prod.get("sku_id"), imagen, sitio_m["sitio"]
                ):
                    print(f"  [OK] {sitio_m['sitio']}: {prod['nombre']}")

        bp.pausa_entre_pedidos()


def main():
    creds = bp.obtener_credenciales_google()
    cliente = bp.gspread.authorize(creds)
    planilla = cliente.open_by_key(bp.SPREADSHEET_ID)

    bp.CACHE_IMAGENES.update(bp.cargar_cache_imagenes(planilla))
    print(f"[INFO] {len(bp.CACHE_IMAGENES)} imágenes ya en caché al arrancar.\n")

    for linea in bp.LINEAS:
        print(f"=== Línea: {linea['nombre']} ===")
        procesar_vtex(linea)
        procesar_magento(linea)

    bp.guardar_nuevas_imagenes(planilla)
    print("\nListo.")


if __name__ == "__main__":
    main()
