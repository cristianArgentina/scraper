"""Líneas de producto a buscar (con sus filtros incluir/excluir)."""

# -----------------------------------------------------------------------
# LÍNEAS DE PRODUCTO A BUSCAR
# "busqueda": término (o LISTA de términos) tal como se usaría en la
#             barra de búsqueda del sitio. Si es una lista, se buscan
#             todos y se combinan los resultados sin duplicar productos
#             (útil para unificar líneas relacionadas, ej. DiabetTX y
#             Goicoechea, en una sola consulta/fila por producto).
# "incluir": lista de patrones (palabras o regex) — el producto SOLO se
#            guarda si su nombre contiene al menos uno. Filtra ruido de
#            búsquedas difusas (ej. en Coto, buscar "...400" a veces trae
#            productos de otras marcas que no tienen nada que ver).
# "excluir": lista de patrones (palabras o regex) — si el nombre contiene
#            alguno, se descarta. Los patrones son regex (case-insensitive),
#            así que "200\\s*ml" matchea "200ml", "200 ml", "x 200 ml", etc.

LINEAS = [
    {
        "nombre": "Dove Bond Repair",
        "busqueda": "dove-bond-repair",
        "busqueda_por_sitio": {
            "perfumeriaspigmento": "bond-repair",
            "maxidescuento": "bond",
            "maxiconsumo": "dove repair",
        },
        "incluir": ["bond"],
        # SKU 22781 en Maxiconsumo: "ACONDICIONADOR DOVE REPAIR 250 ML".
        # El nombre no dice "bond" pero es el producto de la línea Bond
        # Repair (nombre incompleto/mal cargado de ese lado). Se fuerza
        # la inclusión puntual sin aflojar el filtro para el resto.
        "incluir_sku_por_sitio": {"maxiconsumo": {"22781", "11097"}},
        "excluir": [r"200\s*(ml|cc)", r"193\s*(ml|cc)", r"385\s*(ml|cc)"],
    },
    {
        "nombre": "Dove UV Repair",
        "busqueda": "dove-uv-repair",
        "busqueda_por_sitio": {
            "perfumeriaspigmento": "uv-repair",
            "maxidescuento": "uv repair",
        },
        "incluir": [
            r"uv\s*repair",
            r"reparaci[oó]n\s*y\s*brillo",
            r"repair.*uv\s*glow",
        ],
        "excluir": [r"200\s*(ml|cc)"],
    },
    {
        "nombre": "Extraordinario",
        "busqueda": "extraordinario",
        "incluir": ["elvive", "extraordinario"],
        "excluir": ["coco", "rizos", "libro", r"200\s*(ml|cc)", r"750\s*(ml|cc)"],
    },
    {
        "nombre": "Dream Liso",
        "busqueda": "dream-liso",
        "busqueda_por_sitio": {"paradineiro": "dream liso"},        
        "incluir": ["elvive", r"dream\s*liso"],
        "excluir": [r"200\s*(ml|cc)", r"750\s*(ml|cc)"],
    },
    {
        "nombre": "Cicatricure",
        "busqueda": ["cicatricure-400", "cicatricure-age-care", "cicatricure-gel-60"],
        "busqueda_por_sitio": {"maxidescuento": "cicatricure", "paradineiro": "cicatricure"},
        "incluir": ["cicatricur"],
        "excluir": [
            r"\bporcelana\b",
            r"\bcontorno\b",
            r"\bpeeling\b",
            r"\bblur\b",
            r"gold lift",
            r"regene-?plast",
            r"reparaci[oó]n epid[eé]rmica",
        ],
    },
    {
        "nombre": "DiabetTX / Goicoechea 400",
        "busqueda": ["diabettx-400", "goicoechea-400"],
        "busqueda_por_sitio": {"maxidescuento": ["diabettx", "goicoechea"], "paradineiro": "goicoechea"},
        "incluir": ["diabettx", "goicoechea"],
        "excluir": [],
    },
    {
        "nombre": "Nivea Creme 150",
        "busqueda": "nivea-creme-150",
        "busqueda_por_sitio": {"maxidescuento": "creme lata", "paradineiro": "creme lata"},
        "incluir": [r"(?=.*creme)(?=.*150)"],
        "excluir": [],
    },
    {
        "nombre": "Sedal",
        "busqueda": "sedal",
        "incluir": ["sedal"],
        # 650ml y 190ml existen como presentaciones de Sedal y no se
        # quieren (confirmado). El resto de tamaños (300ml, 340ml, etc.)
        # sí quedan.
        "excluir": [
            r"650\s*(ml|cc)",
            r"190\s*(ml|cc)",
            r"doy\s*p",
            r"(shampoo|acondicionador).*\b300\s*(ml|cc)",
        ],
    },
]
