"""
Salida por consola ordenada cuando varios hilos imprimen a la vez.

Cada hilo fija un prefijo (ej. "[farmacity | Sedal]") y todo lo que
imprima con print() sale línea por línea con ese prefijo, sin mezclarse
con lo de otros hilos. No hace falta tocar los print() existentes.
"""

import sys
import threading

_local = threading.local()
_lock = threading.Lock()


class _StdoutPorHilo:
    def __init__(self, destino):
        self._destino = destino

    def write(self, texto):
        prefijo = getattr(_local, "prefijo", None)

        # Hilo sin prefijo (el principal): sale tal cual.
        if prefijo is None:
            with _lock:
                return self._destino.write(texto)

        # Hilo con prefijo: se acumula hasta tener líneas completas.
        buffer = getattr(_local, "buffer", "") + texto
        *lineas, resto = buffer.split("\n")
        _local.buffer = resto

        if lineas:
            with _lock:
                for linea in lineas:
                    self._destino.write(f"{prefijo} {linea}\n")
                self._destino.flush()

        return len(texto)

    def flush(self):
        with _lock:
            self._destino.flush()

    def __getattr__(self, nombre):
        return getattr(self._destino, nombre)


def instalar():
    """Reemplaza sys.stdout una sola vez (es seguro llamarla de nuevo)."""
    if not isinstance(sys.stdout, _StdoutPorHilo):
        sys.stdout = _StdoutPorHilo(sys.stdout)


def fijar_prefijo(prefijo):
    """Define el prefijo de las líneas que imprima el hilo actual."""
    _local.prefijo = prefijo


def vaciar_buffer():
    """Emite lo que haya quedado sin salto de línea al terminar el hilo."""
    if getattr(_local, "buffer", ""):
        sys.stdout.write("\n")
