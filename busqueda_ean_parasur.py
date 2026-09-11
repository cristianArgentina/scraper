import requests
import re


def inspeccionar_html_paradineiro(url_busqueda):
    """
    Descarga una página de búsqueda de Paradineiro y muestra
    fragmentos del HTML relacionados con EAN / GTIN / códigos.
    Función temporal de diagnóstico.
    """
    print("\n" + "=" * 80)
    print("INSPECCIÓN HTML PARADINEIRO")
    print("=" * 80)
    print("URL:", url_busqueda)

    try:
        resp = requests.get(
            url_busqueda,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            },
            timeout=20
        )

        print("\nStatus:", resp.status_code)
        print("Tamaño HTML:", len(resp.text), "caracteres")

        if resp.status_code != 200:
            print("ERROR: la página no respondió correctamente.")
            return

        html = resp.text

        # Guardamos el HTML completo para poder revisarlo si hace falta
        archivo = "paradineiro_debug.html"

        with open(archivo, "w", encoding="utf-8") as f:
            f.write(html)

        print("HTML guardado en:", archivo)

        # Palabras interesantes para localizar
        patrones = [
            r"\bean\b",
            r"\bean13\b",
            r"\bgtin\b",
            r"\bgtin13\b",
            r"\bgtin-13\b",
            r"\bbarcode\b",
            r"\bbar-code\b",
            r"\bc[oó]digo de barras\b",
            r"\bproductid\b",
            r"\bsku\b",
        ]

        encontrados = []

        print("\n" + "-" * 80)
        print("COINCIDENCIAS EN HTML")
        print("-" * 80)

        for patron in patrones:
            coincidencias = list(
                re.finditer(
                    patron,
                    html,
                    re.IGNORECASE
                )
            )

            if coincidencias:
                print(
                    f"\nPatrón {patron!r}: "
                    f"{len(coincidencias)} coincidencia(s)"
                )

                for match in coincidencias[:10]:
                    inicio = max(0, match.start() - 250)
                    fin = min(len(html), match.end() + 500)

                    fragmento = html[inicio:fin]

                    print("\n>>>")
                    print(fragmento)
                    print("<<<")

                    encontrados.append(fragmento)

        if not encontrados:
            print(
                "\nNo se encontraron referencias evidentes "
                "a EAN / GTIN / código de barras."
            )

        print("\n" + "=" * 80)
        print("FIN DE INSPECCIÓN")
        print("=" * 80)

    except Exception as e:
        print("\nERROR:", repr(e))

if __name__ == "__main__":
    inspeccionar_html_paradineiro(
        "https://www.paradineirofarmacias.com.ar/shop?s=extraordinario"
    )