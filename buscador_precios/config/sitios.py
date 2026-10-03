"""Sitios a consultar (VTEX, Coto, Paradineiro, Magento) y constantes de paginación."""

# -----------------------------------------------------------------------
# SITIOS VTEX
# "metodo_precio": "promo2u" (default, simula compra de 2 unidades para
#                  capturar promos de cantidad) o "css" (para sitios donde
#                  la API de simulación no refleja el precio real, como
#                  Josimar; en ese caso se lee el precio del HTML)
# "fallback_css": si la API de simulación dice "withoutStock" (y por eso
# "sales_channel": el número de canal de venta VTEX de la cuenta. La
#                  mayoría usa "1" por defecto, pero cada cuenta lo
#                  configura a su gusto (ej. Farmacity usa "4" — lo
#                  encontramos mirando la cookie vtex_segment del sitio).
#                  Si de golpe un sitio empieza a marcar "sin stock" de
#                  forma sospechosamente constante, vale la pena revisar
#                  esta cookie para confirmar el canal real.
# -----------------------------------------------------------------------
# "postal_code": código postal a usar en la simulación de compra.
#                Por defecto en None (no se manda el campo) en todos los
#                sitios, porque en varios casos (Farmacity, MasOnline)
#                mandarlo hace que VTEX busque stock de un depósito local
#                puntual y devuelva "sin stock"/"no se puede entregar",
#                aunque el producto sí esté disponible a nivel nacional
#                y la promo activa no se aplique por eso. Si algún sitio
#                necesita el código postal para calcular bien el precio
#                (poco común), se le puede poner acá puntualmente.
# -----------------------------------------------------------------------
SITIOS_VTEX = [
    {
        "sitio": "farmaonline",
        "dominio": "www.farmaonline.com",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmalife",
        "dominio": "www.farmalife.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmacity",
        "dominio": "www.farmacity.com",
        "metodo_precio": "promo2u",
        "fallback_css": False,
        "sales_channel": "4",
        "postal_code": None,
    },
    {
        "sitio": "masonline",
        "dominio": "www.masonline.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "perfumeriaspigmento",
        "dominio": "www.perfumeriaspigmento.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "farmaplus",
        "dominio": "www.farmaplus.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "josimar",
        "dominio": "www.josimar.com.ar",
        "metodo_precio": "css",
        "fallback_css": False,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        "sitio": "carrefour",
        "dominio": "www.carrefour.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
        "verificar_stock_catalogo": True,
    },
    {
        "sitio": "diaonline",
        "dominio": "diaonline.supermercadosdia.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "1",
        "postal_code": None,
    },
    {
        # Vea (Cencosud). Canal de venta 34 (cookie vtex_segment). El resto de la
        # config es la base de Carrefour, sin confirmar contra el sitio: revisar
        # en la primera corrida que no salga una fila de error.
        "sitio": "vea",
        "dominio": "www.vea.com.ar",
        "metodo_precio": "promo2u",
        "fallback_css": True,
        "sales_channel": "34",
        "postal_code": None,
    },
]

COTO_SEARCH_URL = (
    "https://api.coto.com.ar/api/v1/ms-digital-sitio-bff-web/api/v1/products/search/"
)
COTO_SEARCH_KEY = "key_r6xzz4IAoTWcipni"

PARADINEIRO_SEARCH_URL = "https://www.paradineirofarmacias.com.ar/shop"
PARADINEIRO_DOMINIO = "https://www.paradineirofarmacias.com.ar"

PRODUCTOS_POR_PAGINA_VTEX = 40
MAX_PAGINAS_VTEX = 3

# -----------------------------------------------------------------------
# SITIOS MAGENTO (Maxiconsumo, y cualquier otro sitio Magento que se
# sume más adelante).
#
# A diferencia de VTEX, acá el precio final ya viene calculado en el
# HTML del listado de búsqueda (no hace falta simular checkout). Cada
# producto trae dos precios: "unitario por bulto cerrado" (con
# descuento, pero exige comprar el pack/caja cerrada) y "unitario"
# suelto (más caro). Se guarda el de bulto cerrado como precio final,
# con la misma lógica que las promos 2x1 en VTEX: el mejor precio
# disponible.
#
# OJO: la ruta /catalogsearch/result/ de Maxiconsumo da error 500 si se
# le manda el parámetro product_list_limit (probado). Sin ese parámetro
# trae 12 productos por página; se pagina con &p=2, &p=3, etc.
#
# Maxiconsumo NO expone EAN en el listado de búsqueda (se revisó el
# HTML completo: no hay ean/gtin/barcode/upc ni datos estructurados
# schema.org/Product). Por eso estos productos se guardan con
# "ean": None y se identifica cada producto por su SKU interno de
# Magento en la columna "sku" de la hoja.
# -----------------------------------------------------------------------
SITIOS_MAGENTO = [
    {
        "sitio": "maxiconsumo",
        "dominio": "www.maxiconsumo.com",
        "sucursal": "sucursal_villa_dominico",
    },
]

MAX_PAGINAS_MAGENTO = 5  # 5 páginas x 12 = hasta 60 productos por término
PRODUCTOS_POR_PAGINA_MAGENTO = 12  # tamaño de página fijo de Maxiconsumo
