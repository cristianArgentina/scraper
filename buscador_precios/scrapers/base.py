"""
Interfaz común de todos los scrapers.

Cada fuente (un sitio VTEX, Coto, Paradineiro, un sitio Magento) es una
subclase de Scraper. El pipeline (pipeline.py) trabaja solo contra esta
interfaz, así que sumar un comercio nuevo = crear una clase nueva y
agregarla en scrapers/__init__.py, sin tocar nada más.

Los productos que devuelve buscar() son dicts con estas claves:
    nombre, sku_id, ean, url, imageurl
y, según la fuente, también: precio, disponibilidad (y otras propias).
"""


class Scraper:
    # Nombre del comercio tal como se guarda en la columna "sitio".
    nombre = ""

    # Pausa extra después de cada producto (para fuentes que hacen un
    # pedido de red por producto, como la simulación de precio de VTEX).
    pausa_por_producto = False

    # Pausa después de terminar de procesar una línea en este sitio.
    pausa_tras_sitio = False

    def termino(self, linea):
        """Término(s) de búsqueda a usar para esta línea en este sitio."""
        return linea.get("busqueda_por_sitio", {}).get(self.nombre, linea["busqueda"])

    def buscar(self, linea):
        """Devuelve (lista_de_productos, error). error es None si salió bien."""
        raise NotImplementedError

    def aplica_incluir(self, linea):
        """True si el filtro 'incluir' de la línea debe aplicarse acá."""
        return True

    def pre_descarte(self, prod):
        """Motivo (str) por el que se descarta el producto antes de pedir
        su precio, o None si sigue adelante."""
        return None

    def obtener_precio(self, prod):
        """Devuelve {"precio", "disponibilidad", "error"(opcional)}.
        Por defecto usa el precio que ya vino en el listado."""
        return {
            "precio": prod.get("precio"),
            "disponibilidad": prod.get("disponibilidad"),
            "error": "",
        }

    def imagen(self, prod):
        """URL de imagen a registrar para este producto (o None)."""
        return prod.get("imageurl")
