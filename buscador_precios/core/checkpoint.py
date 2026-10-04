"""
Guardado parcial de una corrida en un archivo local (JSON Lines).

Cada vez que un sitio termina una línea, sus filas se agregan al archivo
en el momento. Si la corrida se corta (error, Ctrl+C, corte de luz, falla
al subir a Google Sheets), lo ya calculado no se pierde y se puede
reanudar con REANUDAR=ultima, repitiendo solo lo que faltó.

Tipos de registro (una línea JSON cada uno, el último de cada clave gana):
    {"tipo": "inicio",   "fecha": "2026-10-04 13:28"}
    {"tipo": "unidad",   "sitio": ..., "linea": ..., "ok": bool, "filas": [...]}
    {"tipo": "imagenes", "items": [...]}
    {"tipo": "filas_subidas"}      # las filas ya están en Google Sheets
    {"tipo": "imagenes_subidas"}   # las imágenes ya están en Google Sheets

Una "unidad" es un par (sitio, línea). Si terminó con una fila de error
(ok=False), al reanudar se vuelve a intentar.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from config.settings import DIRECTORIO_CORRIDAS, ZONA_HORARIA
from imagenes import copiar_nuevas_imagenes, restaurar_imagenes


def _unidad_ok(filas):
    """Una unidad falló si alguna fila es de error (sin producto)."""
    return not any(f.get("producto") is None and f.get("error") for f in filas)


class Corrida:
    def __init__(self, ruta, fecha):
        self.ruta = Path(ruta)
        self.fecha = fecha
        self.unidades = {}  # (sitio, linea) -> {"ok": bool, "filas": [...]}
        self.imagenes = []
        self.filas_subidas = False
        self.imagenes_subidas = False
        self._idx_imagenes = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Creación / carga
    # ------------------------------------------------------------------
    @classmethod
    def nueva(cls, fecha):
        DIRECTORIO_CORRIDAS.mkdir(parents=True, exist_ok=True)
        sello = datetime.now(ZONA_HORARIA).strftime("%Y%m%d_%H%M%S")
        corrida = cls(DIRECTORIO_CORRIDAS / f"corrida_{sello}.jsonl", fecha)
        corrida._escribir({"tipo": "inicio", "fecha": fecha})
        return corrida

    @classmethod
    def cargar(cls, ruta):
        ruta = Path(ruta)
        if not ruta.is_file():
            raise SystemExit(f"REANUDAR: no existe el archivo {ruta}")

        corrida = cls(ruta, None)
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                try:
                    reg = json.loads(linea)
                except ValueError:
                    continue  # última línea cortada por una caída: se ignora

                tipo = reg.get("tipo")
                if tipo == "inicio":
                    corrida.fecha = reg["fecha"]
                elif tipo == "unidad":
                    corrida.unidades[(reg["sitio"], reg["linea"])] = {
                        "ok": reg["ok"],
                        "filas": reg["filas"],
                    }
                elif tipo == "imagenes":
                    corrida.imagenes.extend(reg["items"])
                elif tipo == "filas_subidas":
                    corrida.filas_subidas = True
                elif tipo == "imagenes_subidas":
                    corrida.imagenes_subidas = True

        if corrida.fecha is None:
            raise SystemExit(f"REANUDAR: {ruta} no tiene encabezado, está dañado")

        # Las imágenes que aún no se subieron vuelven a la lista de
        # pendientes; las ya subidas solo se marcan como conocidas.
        restaurar_imagenes(
            corrida.imagenes, pendientes_de_subir=not corrida.imagenes_subidas
        )
        corrida._idx_imagenes = copiar_nuevas_imagenes(0)[1]
        return corrida

    @classmethod
    def ultima_pendiente(cls):
        """Archivo de la corrida más reciente que todavía no terminó de subirse."""
        archivos = sorted(DIRECTORIO_CORRIDAS.glob("corrida_*.jsonl"), reverse=True)
        for ruta in archivos:
            texto = ruta.read_text(encoding="utf-8")
            if '"tipo": "filas_subidas"' not in texto or (
                '"tipo": "imagenes_subidas"' not in texto
            ):
                return ruta
        raise SystemExit(
            f"REANUDAR: no hay corridas pendientes en {DIRECTORIO_CORRIDAS}"
        )

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def unidad_completa(self, sitio, linea):
        u = self.unidades.get((sitio, linea))
        return bool(u and u["ok"])

    def filas_de(self, sitio, linea):
        return self.unidades[(sitio, linea)]["filas"]

    # ------------------------------------------------------------------
    # Escritura (segura entre hilos)
    # ------------------------------------------------------------------
    def registrar_unidad(self, sitio, linea, filas):
        """Guarda las filas de (sitio, línea) y las imágenes nuevas hasta ahora."""
        with self._lock:
            self._escribir_sin_lock(
                {
                    "tipo": "unidad",
                    "sitio": sitio,
                    "linea": linea,
                    "ok": _unidad_ok(filas),
                    "filas": filas,
                }
            )
            self._volcar_imagenes_sin_lock()

    def volcar_imagenes(self):
        with self._lock:
            self._volcar_imagenes_sin_lock()

    def marcar_filas_subidas(self):
        self.filas_subidas = True
        self._escribir({"tipo": "filas_subidas"})

    def marcar_imagenes_subidas(self):
        self.imagenes_subidas = True
        self._escribir({"tipo": "imagenes_subidas"})

    def _volcar_imagenes_sin_lock(self):
        items, self._idx_imagenes = copiar_nuevas_imagenes(self._idx_imagenes)
        if items:
            self._escribir_sin_lock({"tipo": "imagenes", "items": items})

    def _escribir(self, registro):
        with self._lock:
            self._escribir_sin_lock(registro)

    def _escribir_sin_lock(self, registro):
        with open(self.ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
