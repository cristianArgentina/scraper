"""Configuración general: credenciales, planilla, headers HTTP, zona horaria."""

from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")


# -----------------------------------------------------------------------
# CONFIGURACIÓN DE GOOGLE SHEETS
# -----------------------------------------------------------------------
RUTA_CREDENCIALES = "/home/cristian/Descargas/presupuesto-504401-fcb0abb1e8ff.json"
SPREADSHEET_ID = "1l_2L8rGgCy97uscp-m4mk-0jLLrOA3C9a4ueVGoWB84"
NOMBRE_HOJA_LOG = "Precios_Log_Lineas"  # pestaña nueva, separada de la anterior
NOMBRE_HOJA_IMAGENES = "Imagenes_Productos"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}
