"""
Buscador de precios por LÍNEA DE PRODUCTO (no por SKU individual).

En vez de mantener una lista de URLs/SKUs producto por producto, este
script busca cada línea de marca (ej. "dove bond repair") en cada sitio
y descubre automáticamente todos los productos de esa línea que vende
ese sitio, con su precio final (incluyendo promos de 2x1 / llevando 2
cuando existen).

Requisitos:
    pip3 install requests beautifulsoup4 gspread google-auth --break-system-packages

Estructura:
    config/      -> líneas, sitios, exclusiones (exclusiones.json), settings
    core/        -> http, parsing, ean, filtros, cache, logs, checkpoint
    scrapers/    -> un scraper por comercio (interfaz común en base.py)
    pipeline.py  -> filtrado, precio, descartes e imágenes (igual para todos)
    (los comercios se consultan en paralelo: un hilo por sitio, que recorre
     todas las líneas en orden; core/logs.py ordena la salida por consola)
    imagenes.py  -> manejo de imágenes
    sheets.py    -> Google Sheets

Uso:
    python3 buscador_precios.py

Variables de entorno opcionales:
    SOLO_SITIOS=vea,coto   consulta solo esos sitios
    SIN_GUARDAR=1          prueba: no escribe en Sheets ni guarda avance
    REANUDAR=ultima        retoma la última corrida que quedó sin subir
                           (o REANUDAR=corridas/corrida_XXXX.jsonl): repite solo
                           lo que falló o faltó y sube lo pendiente. El avance de
                           cada corrida se guarda en corridas/ a medida que se
                           resuelve cada sitio/línea.
"""

import os
import threading

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import gspread

from config.lineas import LINEAS
from config.settings import SPREADSHEET_ID, ZONA_HORARIA
from core.checkpoint import Corrida
from core.logs import fijar_prefijo, vaciar_buffer
from core.logs import instalar as instalar_logs_por_hilo
from imagenes import CACHE_IMAGENES
from pipeline import procesar_linea_en_scraper
from scrapers import construir_scrapers
from sheets import (
    cargar_cache_imagenes,
    escribir_en_google_sheets,
    guardar_nuevas_imagenes,
    obtener_credenciales_google,
)


def _recorrer_lineas_en_sitio(scraper, lineas, fecha, corrida, detener):
    """Trabajo de un hilo: todas las líneas en UN sitio. Devuelve una lista
    de filas por línea (misma posición que en `lineas`).

    Cada línea terminada se guarda enseguida en el archivo de la corrida. Al
    reanudar, las que ya habían salido bien se reutilizan sin volver a pedirlas."""
    filas_por_linea = []

    for linea in lineas:
        if detener.is_set():  # Ctrl+C: no se arranca otra línea
            break

        fijar_prefijo(f"[{scraper.nombre} | {linea['nombre']}]")

        if corrida and corrida.unidad_completa(scraper.nombre, linea["nombre"]):
            print("  (ya procesada en la corrida anterior, se reutiliza)")
            filas_por_linea.append(corrida.filas_de(scraper.nombre, linea["nombre"]))
            continue

        filas = procesar_linea_en_scraper(linea, scraper, fecha)

        if corrida:
            try:
                corrida.registrar_unidad(scraper.nombre, linea["nombre"], filas)
            except OSError as e:
                # Un problema de disco no debe frenar la búsqueda.
                print(f"  [AVISO] no se pudo guardar el avance: {e}")

        filas_por_linea.append(filas)

    vaciar_buffer()
    return filas_por_linea


def _abrir_corrida(sin_guardar):
    """Devuelve (corrida, fecha). Con REANUDAR=ultima (o una ruta) retoma una
    corrida anterior; con SIN_GUARDAR=1 no se guarda ningún archivo."""
    reanudar = os.environ.get("REANUDAR")

    if reanudar:
        if sin_guardar or os.environ.get("SOLO_SITIOS"):
            raise SystemExit(
                "REANUDAR no se combina con SIN_GUARDAR ni con SOLO_SITIOS "
                "(se subirían datos incompletos)."
            )
        ruta = Corrida.ultima_pendiente() if reanudar == "ultima" else reanudar
        corrida = Corrida.cargar(ruta)
        hechas = sum(1 for u in corrida.unidades.values() if u["ok"])
        print(
            f"[REANUDAR] {corrida.ruta.name}: {hechas} combinaciones sitio/línea "
            f"ya resueltas; se repite solo lo que faltó o falló."
        )
        return corrida, corrida.fecha

    fecha = datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M")
    return (None if sin_guardar else Corrida.nueva(fecha)), fecha


def main():
    # Para pruebas: SIN_GUARDAR=1 muestra todo por consola y no escribe nada
    # (ni en Google Sheets ni archivos de avance).
    sin_guardar = os.environ.get("SIN_GUARDAR") == "1"
    filas = []

    # -------------------------------------------------------------------
    # CARGAR IMÁGENES EXISTENTES
    # -------------------------------------------------------------------
    try:
        creds = obtener_credenciales_google()
        cliente = gspread.authorize(creds)
        planilla = cliente.open_by_key(SPREADSHEET_ID)

        CACHE_IMAGENES.update(cargar_cache_imagenes(planilla))

    except Exception as e:
        print(
            f"[AVISO] No se pudo cargar la caché de imágenes: "
            f"{type(e).__name__}: {e}"
        )
        planilla = None

    # Se abre después de cargar la caché de Sheets: al reanudar hace falta
    # saber qué imágenes ya estaban subidas.
    corrida, fecha = _abrir_corrida(sin_guardar)

    # -------------------------------------------------------------------
    # RECORRER LÍNEAS x COMERCIOS
    # -------------------------------------------------------------------
    scrapers = construir_scrapers()
    instalar_logs_por_hilo()

    # Un hilo por sitio, cada uno recorre todas las líneas en orden. Dentro
    # de un mismo sitio todo sigue siendo secuencial (mismas pausas de
    # siempre), así que a cada comercio se le pide igual de despacio; lo que
    # cambia es que los 12 comercios trabajan a la vez.
    detener = threading.Event()
    interrumpido = False

    with ThreadPoolExecutor(
        max_workers=max(1, len(scrapers)), thread_name_prefix="sitio"
    ) as pool:
        futuros = [
            pool.submit(
                _recorrer_lineas_en_sitio, scraper, LINEAS, fecha, corrida, detener
            )
            for scraper in scrapers
        ]
        try:
            resultados = [f.result() for f in futuros]
        except KeyboardInterrupt:
            # Cada hilo termina la línea en curso y se detiene; lo ya resuelto
            # queda guardado. (Un segundo Ctrl+C corta en seco.)
            detener.set()
            interrumpido = True
            print("\n[INTERRUMPIDO] terminando las líneas en curso...")

    if interrumpido:
        if corrida:
            print(
                f"Avance guardado en {corrida.ruta}\n"
                f"Para retomar:  REANUDAR=ultima python3 buscador_precios.py"
            )
        raise SystemExit(130)

    # Las filas se arman en el mismo orden de siempre (línea por línea y,
    # dentro de cada una, sitio por sitio), sin importar cuál terminó antes.
    for i_linea in range(len(LINEAS)):
        for filas_sitio in resultados:
            filas.extend(filas_sitio[i_linea])

    # -------------------------------------------------------------------
    # GUARDAR RESULTADOS
    # -------------------------------------------------------------------
    if corrida is None:
        print(
            f"\n[SIN_GUARDAR] {len(filas)} filas calculadas, no se guardó nada en Sheets."
        )
        return

    corrida.volcar_imagenes()
    pendiente = False

    if corrida.filas_subidas:
        print("\n[REANUDAR] las filas ya estaban subidas a Sheets, no se repiten.")
    else:
        try:
            escribir_en_google_sheets(filas)
            corrida.marcar_filas_subidas()
        except Exception as e:
            pendiente = True
            print(f"\n[ERROR subiendo a Google Sheets]: {type(e).__name__}: {e}")

    if corrida.imagenes_subidas:
        print("[REANUDAR] las imágenes ya estaban subidas a Sheets, no se repiten.")
    else:
        try:
            if planilla is None:
                creds = obtener_credenciales_google()
                cliente = gspread.authorize(creds)
                planilla = cliente.open_by_key(SPREADSHEET_ID)

            guardar_nuevas_imagenes(planilla)
            corrida.marcar_imagenes_subidas()

        except Exception as e:
            pendiente = True
            print(f"\n[ERROR guardando imágenes]: {type(e).__name__}: {e}")

    if pendiente:
        print(
            f"\nEl avance quedó guardado en {corrida.ruta}\n"
            f"Para reintentar solo lo que falta:  REANUDAR=ultima python3 buscador_precios.py"
        )


if __name__ == "__main__":
    main()
