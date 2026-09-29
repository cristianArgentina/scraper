"""Caché de búsquedas en memoria (vale solo durante una corrida)."""

# -----------------------------------------------------------------------
# CACHÉ DE BÚSQUEDAS
# Si dos líneas piden el mismo término al mismo sitio (ej. las 3 líneas
# de Cicatricure comparten los mismos 3 términos), la segunda vez se
# reutiliza el resultado ya obtenido en vez de volver a pedirlo por red.
# Clave: (tipo_sitio, identificador_sitio, término) -> lista de productos
# crudos (antes de aplicar incluir/excluir de cada línea).
# -----------------------------------------------------------------------
CACHE_BUSQUEDA = {}
