#!/usr/bin/env python3
"""
Lee una hoja de Google Sheets con las columnas:
    ean | imageurl | fuente | sku | sitio
Para cada fila con imageurl:
  1. descarga la imagen
  2. la redimensiona y comprime a WebP (pensada para cards de ~5 por fila)
  3. la guarda en un clon local de tu repo de GitHub y hace commit + push
  4. escribe la URL pública resultante en la columna `imageurlopt`

Es idempotente: las filas que ya tienen imageurlopt se saltean, y si la imagen
ya existe en el repo no se vuelve a descargar.
"""
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import gspread
import requests
from gspread.utils import rowcol_to_a1
from PIL import Image, ImageOps

# ----------------------------- Configuración -----------------------------
SHEET_ID = os.environ["SHEET_ID"]                       # ID de la planilla (está en la URL)
WORKSHEET = os.getenv("WORKSHEET", "")                  # nombre de la pestaña ("" = la primera)
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS", "service_account.json")

GITHUB_REPO = os.environ["GITHUB_REPO"]                 # "usuario/repo"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]               # token con permiso de escritura al repo
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
IMAGES_DIR = os.getenv("IMAGES_DIR", "img/productos")   # carpeta dentro del repo
CLONE_DIR = Path(os.getenv("CLONE_DIR", "./_repo_clone"))

# URL pública final. Placeholders: {repo} {branch} {path}
PUBLIC_URL_TEMPLATE = os.getenv(
    "PUBLIC_URL_TEMPLATE",
    "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}",
)

MAX_SIZE = int(os.getenv("MAX_SIZE", "500"))            # px del lado mayor (cards ~250px x2 retina)
WEBP_QUALITY = int(os.getenv("WEBP_QUALITY", "80"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))         # commit + push + escritura en sheet cada N imágenes
OPT_COL = os.getenv("OPT_COL", "imageurlopt")           # nombre de la columna nueva
# -------------------------------------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ImageOptimizer/1.0)"}


def run(*cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def ensure_clone():
    if (CLONE_DIR / ".git").exists():
        run("git", "fetch", "origin", GITHUB_BRANCH, cwd=CLONE_DIR)
        run("git", "checkout", GITHUB_BRANCH, cwd=CLONE_DIR)
        run("git", "pull", "--rebase", "origin", GITHUB_BRANCH, cwd=CLONE_DIR)
    else:
        url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        run("git", "clone", "--branch", GITHUB_BRANCH, url, str(CLONE_DIR))
    (CLONE_DIR / IMAGES_DIR).mkdir(parents=True, exist_ok=True)


def commit_and_push(message):
    run("git", "add", IMAGES_DIR, cwd=CLONE_DIR)
    if not run("git", "status", "--porcelain", cwd=CLONE_DIR).stdout.strip():
        return
    run("git", "-c", "user.name=image-optimizer", "-c", "user.email=bot@localhost",
        "commit", "-m", message, cwd=CLONE_DIR)
    try:
        run("git", "push", "origin", GITHUB_BRANCH, cwd=CLONE_DIR)
    except subprocess.CalledProcessError:
        run("git", "pull", "--rebase", "origin", GITHUB_BRANCH, cwd=CLONE_DIR)
        run("git", "push", "origin", GITHUB_BRANCH, cwd=CLONE_DIR)


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("_")


def optimize(data):
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)  # nunca agranda
    out = io.BytesIO()
    img.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


def public_url(filename):
    path = f"{IMAGES_DIR}/{filename}".replace("\\", "/")
    return PUBLIC_URL_TEMPLATE.format(repo=GITHUB_REPO, branch=GITHUB_BRANCH, path=path)


def get_worksheet():
    gc = gspread.service_account(filename=GOOGLE_CREDS)
    sh = gc.open_by_key(SHEET_ID)
    return sh.worksheet(WORKSHEET) if WORKSHEET else sh.get_worksheet(0)


def flush(ws, pending, col, label):
    """Hace push de lo nuevo y recién entonces escribe las URLs en la hoja."""
    if not pending:
        return
    commit_and_push(f"Optimized product images ({label})")
    ws.batch_update(
        [{"range": rowcol_to_a1(row, col), "values": [[url]]} for row, url in pending],
        value_input_option="RAW",
    )
    print(f"  -> {len(pending)} filas actualizadas en la hoja")


def main():
    ws = get_worksheet()
    rows = ws.get_all_values()
    if not rows:
        sys.exit("La hoja está vacía")

    header = [h.strip().lower() for h in rows[0]]
    for required in ("imageurl", "ean"):
        if required not in header:
            sys.exit(f"Falta la columna '{required}' en la hoja")
    i_url, i_ean = header.index("imageurl"), header.index("ean")
    i_sku = header.index("sku") if "sku" in header else None

    if OPT_COL.lower() in header:
        i_opt = header.index(OPT_COL.lower())
    else:
        i_opt = len(header)
        if i_opt + 1 > ws.col_count:
            ws.add_cols(i_opt + 1 - ws.col_count)
        ws.update_cell(1, i_opt + 1, OPT_COL)
    col = i_opt + 1  # 1-based

    ensure_clone()
    done = {}       # filename -> url (misma imagen usada en varias filas)
    pending = []    # (fila, url) del lote actual
    processed = 0

    for n, row in enumerate(rows[1:], start=2):
        get = lambda i: row[i].strip() if i is not None and i < len(row) else ""
        img_url, existing = get(i_url), get(i_opt)
        if not img_url or existing:
            continue
        if not img_url.lower().startswith(("http://", "https://")):
            print(f"[fila {n}] imageurl inválida, se saltea")
            continue

        base = safe_name(get(i_ean)) or safe_name(get(i_sku))
        if not base:
            print(f"[fila {n}] sin ean ni sku, se saltea")
            continue
        filename = f"{base}.webp"

        if filename in done:
            pending.append((n, done[filename]))
            continue

        target = CLONE_DIR / IMAGES_DIR / filename
        try:
            if not target.exists():
                resp = requests.get(img_url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                target.write_bytes(optimize(resp.content))
                print(f"[fila {n}] {filename} ({target.stat().st_size // 1024} KB)")
            else:
                print(f"[fila {n}] {filename} ya existía en el repo")
        except Exception as exc:  # la fila queda vacía y se reintenta en la próxima corrida
            print(f"[fila {n}] ERROR {img_url}: {exc}")
            continue

        done[filename] = public_url(filename)
        pending.append((n, done[filename]))
        processed += 1

        if processed % BATCH_SIZE == 0:
            flush(ws, pending, col, f"lote hasta fila {n}")
            pending = []

    flush(ws, pending, col, "lote final")
    print("Listo.")


if __name__ == "__main__":
    main()
