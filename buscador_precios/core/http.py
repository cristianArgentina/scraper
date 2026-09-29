"""Requests con reintentos y pausas entre pedidos."""

import random
import time

import requests


def request_con_reintentos(metodo: str, url: str, max_intentos: int = 3, **kwargs):
    """
    Hace un request con reintentos y backoff exponencial si el sitio
    devuelve 429 (too many requests) o algún error 5xx transitorio.
    Entre pedidos exitosos también espera un tiempo aleatorio corto para
    no generar un patrón de tráfico perfectamente regular.
    """
    for intento in range(1, max_intentos + 1):
        try:
            resp = requests.request(metodo, url, timeout=15, **kwargs)
        except requests.RequestException as e:
            if intento == max_intentos:
                raise
            time.sleep(2**intento)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if intento == max_intentos:
                return resp  # devolvemos igual, el llamador maneja el error
            espera = (2**intento) + random.uniform(0, 1)
            print(
                f"    [rate limit / error {resp.status_code}] esperando {espera:.1f}s y reintentando..."
            )
            time.sleep(espera)
            continue

        return resp

    return resp


def pausa_entre_pedidos():
    time.sleep(1 + random.uniform(0, 0.8))
