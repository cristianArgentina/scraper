"""
Script de DIAGNÓSTICO v2 para Maxiconsumo (no persiste nada en Sheets).

La v1 dio 500 en TODOS los términos, incluso "sedal" (sin espacios), lo
que sugiere que no es un problema de encoding sino de:
  a) falta de cookies de sesión (Magento a veces necesita que primero
     "entres" a la home para que te asigne sucursal/store view), o
  b) el parámetro product_list_limit no es válido en esa ruta, o
  c) la ruta /catalogsearch/result/ no es la correcta para este sitio.

Este script prueba varias combinaciones para aislar la causa, y en cada
intento guarda el HTML de respuesta (aunque sea el de error) para poder
leer el mensaje real.

Requisitos:
    pip3 install requests beautifulsoup4 --break-system-packages

Uso:
    python3 test_maxiconsumo.py sedal
"""

import re
import sys
import json

import requests
from bs4 import BeautifulSoup

DOMINIO = "www.maxiconsumo.com"
SUCURSAL = "sucursal_moreno"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}


def parsear_precio_ar(texto: str):
    match = re.search(r"([\d.]+,\d{2}|[\d.]+)", texto)
    if not match:
        return None
    limpio = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def guardar_debug(nombre, resp):
    with open(nombre, "w", encoding="utf-8") as f:
        f.write(f"<!-- status_code: {resp.status_code} -->\n")
        f.write(f"<!-- headers: {dict(resp.headers)} -->\n")
        f.write(f"<!-- cookies recibidas: {dict(resp.cookies)} -->\n")
        f.write(resp.text)


def intentar(session, url, nombre_debug, label):
    print(f"\n  [{label}] GET {url}")
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"    [ERROR de conexión] {e}")
        return None

    print(f"    Status: {resp.status_code} | Largo: {len(resp.text)} caracteres")
    guardar_debug(nombre_debug, resp)
    print(f"    Guardado en: {nombre_debug}")

    if resp.status_code == 200 and len(resp.text) > 500:
        return resp
    return None


def buscar(termino: str):
    print(f"\n=== Buscando '{termino}' ===")

    session = requests.Session()

    # Paso 0: pisar la home primero para que el sitio asigne cookies de
    # sesión / sucursal, por si la ruta de búsqueda las necesita.
    print("\n  [paso 0] Visitando la home para conseguir cookies...")
    try:
        home = session.get(
            f"https://{DOMINIO}/{SUCURSAL}/", headers=HEADERS, timeout=20
        )
        print(
            f"    Home status: {home.status_code} | "
            f"Cookies obtenidas: {list(session.cookies.get_dict().keys())}"
        )
    except requests.RequestException as e:
        print(f"    [ERROR visitando la home] {e}")

    termino_url = termino.replace(" ", "+")
    slug = termino.replace(" ", "_")

    intentos = [
        (
            f"https://{DOMINIO}/{SUCURSAL}/catalogsearch/result/?q={termino_url}",
            f"debug_maxiconsumo_{slug}_A_con_sucursal.html",
            "A: con sucursal, sin product_list_limit",
        ),
        (
            f"https://{DOMINIO}/{SUCURSAL}/catalogsearch/result/"
            f"?q={termino_url}&product_list_limit=96",
            f"debug_maxiconsumo_{slug}_B_con_limit.html",
            "B: con sucursal, con product_list_limit",
        ),
        (
            f"https://{DOMINIO}/catalogsearch/result/?q={termino_url}",
            f"debug_maxiconsumo_{slug}_C_sin_sucursal.html",
            "C: sin sucursal en la URL",
        ),
        (
            f"https://{DOMINIO}/{SUCURSAL}/catalogsearch/result/index/?q={termino_url}",
            f"debug_maxiconsumo_{slug}_D_index.html",
            "D: con /index/ explícito",
        ),
    ]

    resp_ok = None
    for url, nombre_debug, label in intentos:
        resp = intentar(session, url, nombre_debug, label)
        if resp is not None:
            resp_ok = resp
            print(f"\n  >>> Este intento ({label}) dio 200 con contenido. Sigo con este.")
            break

    if resp_ok is None:
        print(
            "\n[SIN SUERTE] Ninguna de las 4 variantes dio 200 con contenido. "
            "Mandame los 4 archivos debug_maxiconsumo_*.html que se generaron "
            "(tienen el status code, los headers y el cuerpo de la respuesta "
            "en las primeras líneas como comentario) para ver el error real "
            "que está devolviendo el servidor."
        )
        return

    parsear_y_mostrar(resp_ok.text, termino)


def parsear_y_mostrar(html, termino):
    soup = BeautifulSoup(html, "html.parser")

    items = soup.select("li.product-item")
    metodo = "li.product-item"

    if not items:
        items = soup.select("li.item.product.product-item")
        metodo = "li.item.product.product-item"

    if not items:
        candidatos = []
        for li in soup.find_all("li"):
            a = li.find("a", href=re.compile(r"-\d+\.html$"))
            if a:
                candidatos.append(li)
        items = candidatos
        metodo = "fallback: <li> con <a href=...-NUMERO.html>"

    print(f"\nMétodo de selección usado: {metodo}")
    print(f"Cantidad de items encontrados: {len(items)}")

    if not items:
        print(
            "[SIN RESULTADOS] La página cargó bien (200) pero no se "
            "encontró ningún producto con los selectores probados."
        )
        return

    productos = []
    for li in items:
        a_tag = (
            li.find("a", class_="product-item-link")
            or li.find("a", href=re.compile(r"-\d+\.html$"))
            or li.find("a", href=True)
        )
        if not a_tag:
            continue

        nombre = a_tag.get_text(strip=True)
        link = a_tag.get("href", "")
        texto = li.get_text(" ", strip=True)

        sku_match = re.search(r"\bSKU\s*(\d+)", texto, re.IGNORECASE)
        sku_id = sku_match.group(1) if sku_match else None

        texto_lower = texto.lower()
        sin_stock = "agotado" in texto_lower or "sin stock" in texto_lower

        precio_bulto = None
        match_bulto = re.search(
            r"Precio unitario por bulto cerrado\s*\$\s*([\d.,]+)\s*\$\s*([\d.,]+)",
            texto,
            re.IGNORECASE,
        )
        if match_bulto:
            precio_bulto = parsear_precio_ar(match_bulto.group(2))
        else:
            match_bulto_simple = re.search(
                r"Precio unitario por bulto cerrado\s*\$\s*([\d.,]+)",
                texto,
                re.IGNORECASE,
            )
            if match_bulto_simple:
                precio_bulto = parsear_precio_ar(match_bulto_simple.group(1))

        precio_unitario = None
        match_unitario = re.search(
            r"Precio unitario\s*\$\s*([\d.,]+)", texto, re.IGNORECASE
        )
        if match_unitario:
            precio_unitario = parsear_precio_ar(match_unitario.group(1))

        img_tag = a_tag.find("img") or li.find("img")
        imagen_url = None
        if img_tag:
            imagen_url = img_tag.get("src") or img_tag.get("data-src")

        productos.append(
            {
                "nombre": nombre,
                "sku": sku_id,
                "link": link,
                "precio_bulto_cerrado": precio_bulto,
                "precio_unitario_suelto": precio_unitario,
                "sin_stock": sin_stock,
                "imagen": imagen_url,
                "texto_crudo_del_item": texto[:300],
            }
        )

    print("\n--- Primeros 10 productos parseados ---")
    for p in productos[:10]:
        print(
            f"- {p['nombre']} | SKU={p['sku']} | "
            f"bulto=${p['precio_bulto_cerrado']} | "
            f"unidad=${p['precio_unitario_suelto']} | "
            f"sin_stock={p['sin_stock']}"
        )

    faltantes_sku = sum(1 for p in productos if p["sku"] is None)
    faltantes_precio = sum(
        1
        for p in productos
        if p["precio_bulto_cerrado"] is None and p["precio_unitario_suelto"] is None
    )

    print(f"\nTotal productos parseados: {len(productos)}")
    print(f"Productos sin SKU detectado: {faltantes_sku}")
    print(f"Productos sin ningún precio detectado: {faltantes_precio}")

    nombre_json = f"resultados_maxiconsumo_{termino.replace(' ', '_')}.json"
    with open(nombre_json, "w", encoding="utf-8") as f:
        json.dump(productos, f, ensure_ascii=False, indent=2)
    print(f"\nResultados completos guardados en: {nombre_json}")

    if faltantes_sku > 0 or faltantes_precio > 0:
        print(
            "\n[AVISO] Hay productos sin SKU y/o sin precio. Mirá "
            f"'texto_crudo_del_item' en {nombre_json} y pasámelo."
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        terminos = sys.argv[1:]
    else:
        terminos = ["sedal", "cicatricure", "dove bond repair"]

    for t in terminos:
        buscar(t)
