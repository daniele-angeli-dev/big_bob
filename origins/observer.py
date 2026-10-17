"""Osservatore: cosa è cambiato sullo schermo tra un F8 e l'altro.

Il controllo gira ogni ~0,35 s durante una partita. Invece di confrontare la media di tutta la schermata (che non vede
una carta che compare in un angolo) divide la miniatura in una griglia e guarda la cella che cambia di più. Salva un
fotogramma quando una zona cambia, sia a schermata ferma sia durante le animazioni (rivelazioni, magie, combattimento
che durano poco), e ne ritaglia la zona cambiata ad alta risoluzione: all'F8 Claude riceve i ritagli in ordine di
tempo, con orario e posizione, e legge i nomi delle carte invece di intuirli da un'immagine rimpicciolita.
"""
from __future__ import annotations

from PIL import Image, ImageChops

SIG_SIZE = (96, 54)
GRID = (12, 6)


def signature(img: Image.Image) -> Image.Image:
    return img.convert("L").resize(SIG_SIZE)


def cell_diff(a: Image.Image, b: Image.Image) -> tuple[float, float, list[list[float]]]:
    """(cambio della cella più cambiata, cambio medio, griglia dei cambi) tra due miniature (0-255)."""
    diff = ImageChops.difference(a, b)
    cells = diff.resize(GRID, Image.BOX)
    px = list(cells.getdata())
    grid = [px[r * GRID[0]:(r + 1) * GRID[0]] for r in range(GRID[1])]
    return float(max(px) if px else 0), float(sum(px) / len(px) if px else 0), grid


def changed_bbox(grid: list[list[float]], thr: float = 6.0) -> tuple[float, float, float, float] | None:
    """Rettangolo (x0, y0, x1, y1 in frazioni 0-1) che contiene le celle cambiate, con un margine di una cella."""
    cols, rows = GRID
    hit = [(c, r) for r in range(rows) for c in range(cols) if grid[r][c] > thr]
    if not hit:
        return None
    c0, c1 = max(0, min(c for c, _ in hit) - 1), min(cols, max(c for c, _ in hit) + 2)
    r0, r1 = max(0, min(r for _, r in hit) - 1), min(rows, max(r for _, r in hit) + 2)
    return c0 / cols, r0 / rows, c1 / cols, r1 / rows


def crop(img: Image.Image, bbox, max_side: int = 1000) -> Image.Image:
    x0, y0, x1, y1 = bbox
    part = img.crop((int(x0 * img.width), int(y0 * img.height), int(x1 * img.width), int(y1 * img.height)))
    if max(part.size) > max_side:
        k = max_side / max(part.size)
        part = part.resize((max(1, int(part.width * k)), max(1, int(part.height * k))), Image.LANCZOS)
    return part


def position_label(bbox) -> str:
    if not bbox:
        return "tutta la schermata"
    x0, y0, x1, y1 = bbox
    if (x1 - x0) * (y1 - y0) > 0.6:
        return "gran parte della schermata"
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = "a sinistra" if cx < 0.36 else ("a destra" if cx > 0.64 else "al centro")
    v = "in alto" if cy < 0.36 else ("in basso" if cy > 0.64 else "a metà altezza")
    return f"{v} {h}"


def select(frames: list[dict], k: int) -> list[dict]:
    """Al massimo k fotogrammi in ordine di tempo: il più cambiato di ogni tratto della sequenza (così nessun momento
    resta scoperto), poi i più cambiati tra gli altri."""
    if len(frames) <= k:
        return list(frames)
    n = len(frames)
    chosen = set()
    for b in range(k):
        part = range(b * n // k, (b + 1) * n // k)
        if len(part):
            chosen.add(max(part, key=lambda i: frames[i]["score"]))
    for i in sorted(range(n), key=lambda i: -frames[i]["score"]):
        if len(chosen) >= k:
            break
        chosen.add(i)
    return [frames[i] for i in sorted(chosen)]
