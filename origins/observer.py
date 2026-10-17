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
    # prima una riduzione veloce (media di blocchi interi), poi la miniatura: su una schermata 2560x1440 è ~10 volte
    # più rapido di un resize diretto
    k = max(1, min(img.width // (SIG_SIZE[0] * 4), img.height // (SIG_SIZE[1] * 4)))
    small = img.reduce(k) if k > 1 else img
    return small.convert("L").resize(SIG_SIZE, Image.BOX)


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


def _overlap(a, b) -> bool:
    if not a or not b:
        return a is None and b is None
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def events(frames: list[dict], gap: float = 1.5) -> list[list[dict]]:
    """Raggruppa i fotogrammi in "eventi": fotogrammi vicini nel tempo nella stessa zona dello schermo sono la stessa
    cosa che succede (un'animazione, una carta che compare e si gira)."""
    out: list[list[dict]] = []
    for f in frames:
        last = out[-1][-1] if out else None
        if last and f["t"] - last["t"] <= gap and _overlap(f.get("bbox"), last.get("bbox")):
            out[-1].append(f)
        else:
            out.append([f])
    return out


def keep_per_event(frames: list[dict]) -> list[dict]:
    """Di ogni evento tengo il momento di cambio più forte e l'ultimo fotogramma (lo stato finale, il più leggibile):
    i fotogrammi intermedi della stessa animazione non aggiungono informazioni."""
    kept = []
    for ev in events(frames):
        peak = max(ev, key=lambda f: f["score"])
        for f in ev:
            if f is peak or f is ev[-1]:
                kept.append(f)
    return kept


def plan(frames: list[dict], max_images: int = 10, per_sheet: int = 4) -> list[list[dict]]:
    """Come allegare i fotogrammi a un F8: gruppi in ordine di tempo, ognuno diventa un'immagine (un gruppo da 1 =
    il ritaglio da solo, da 2-4 = un foglio con i ritagli affiancati). Così Claude vede fino a max_images*per_sheet
    momenti invece di 10: prima si tolgono i doppioni della stessa animazione, poi, solo se servono, si affiancano."""
    kept = keep_per_event(frames)
    if len(kept) > max_images * per_sheet:
        kept = select(kept, max_images * per_sheet)
    if len(kept) <= max_images:
        return [[f] for f in kept]
    size = -(-len(kept) // max_images)  # arrotondato per eccesso, al massimo per_sheet
    return [kept[i:i + size] for i in range(0, len(kept), size)]


def sheet(images: list[Image.Image], labels: list[str], width: int = 1568) -> Image.Image:
    """Affianca 2-4 ritagli in un foglio (2 colonne), ognuno col suo numero in alto a sinistra."""
    from PIL import ImageDraw
    cols = 2 if len(images) > 1 else 1
    rows = -(-len(images) // cols)
    cw = width // cols
    ch = int(cw * 0.66)
    out = Image.new("RGB", (cw * cols, ch * rows), (12, 12, 12))
    d = ImageDraw.Draw(out)
    for i, (im, lab) in enumerate(zip(images, labels)):
        k = min((cw - 6) / im.width, (ch - 6) / im.height, 1.6)
        tile = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        x, y = (i % cols) * cw, (i // cols) * ch
        out.paste(tile, (x + (cw - tile.width) // 2, y + (ch - tile.height) // 2))
        d.rectangle((x, y, x + 12 + 9 * len(lab), y + 22), fill=(255, 210, 0))
        d.text((x + 6, y + 5), lab, fill=(0, 0, 0))
    return out


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
