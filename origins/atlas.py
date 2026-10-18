"""Atlante delle carte: BIG-BOB impara da solo che aspetto hanno le carte sul campo.

Ogni tanto (una lettura su CALIBRA_OGNI) il lettore del lato avversario riceve la schermata intera e scrive anche i
rettangoli degli spazi del campo. Da lì BIG-BOB:
- impara dove sono gli spazi (mediana dei rettangoli visti: la grafica del gioco non si sposta);
- ritaglia ogni carta letta e ne salva un'impronta (dHash 16×16 dell'immagine) con il nome.
Nelle letture successive ritaglia gli stessi spazi, confronta le impronte e, se il nome riconosciuto è diverso da quello
scritto dal lettore, lo segnala nei controlli della lettura (un nome letto male cambia probabilità e simulazioni).
Per sostituire del tutto i lettori servirebbe leggere anche i numeri di attacco e vita (che cambiano con i danni):
per ora l'atlante controlla e corregge i NOMI.
"""
from __future__ import annotations

import json
import statistics

from PIL import Image

from origins import store

CALIBRA_OGNI = 6
MAX_PER_CARTA = 6
SOGLIA = 48          # bit diversi su 256 per dire "è la stessa carta"
LANES = ("sinistra", "centro", "destra")


def _dir():
    d = store.DATA / "atlante"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(name, default):
    p = _dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (OSError, ValueError):
        return default


def _save(name, data) -> None:
    (_dir() / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def dhash(img: Image.Image, size: int = 16) -> int:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(size):
        row = px[r * (size + 1):(r + 1) * (size + 1)]
        for c in range(size):
            bits = (bits << 1) | (1 if row[c] > row[c + 1] else 0)
    return bits


def _dist(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _crop(img: Image.Image, box) -> Image.Image | None:
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    l, t = int(img.width * x / 100), int(img.height * y / 100)
    r, b = int(img.width * (x + w) / 100), int(img.height * (y + h) / 100)
    if r - l < 8 or b - t < 8:
        return None
    return img.crop((l, t, r, b))


def _name(unit) -> str | None:
    if not unit or not isinstance(unit, str):
        return None
    parts = unit.rsplit(" ", 1)
    return parts[0] if len(parts) == 2 and "/" in parts[1] else unit


def learn(img: Image.Image, boxes: dict, board: dict) -> int:
    """Impara spazi e impronte da una lettura con i rettangoli. Ritorna quante carte ha aggiunto."""
    if not isinstance(boxes, dict) or not isinstance(board, dict):
        return 0
    slots = _load("spazi.json", {})
    prints = _load("impronte.json", [])
    added = 0
    for lane in LANES:
        for side in ("mie", "avv"):
            rects = ((boxes.get(lane) or {}).get(side) or [])
            units = ((board.get(lane) or {}).get(side) or [])
            for k, rect in enumerate(rects):
                if not isinstance(rect, list) or len(rect) != 4:
                    continue
                key = f"{lane}:{side}:{k}"
                slots.setdefault(key, [])
                slots[key] = (slots[key] + [rect])[-15:]
                name = _name(units[k]) if k < len(units) else None
                crop = _crop(img, rect)
                if name and crop is not None:
                    same = [p for p in prints if p["nome"] == name]
                    if len(same) >= MAX_PER_CARTA:
                        prints.remove(same[0])
                    prints.append({"nome": name, "h": format(dhash(crop), "x")})
                    added += 1
    _save("spazi.json", slots)
    _save("impronte.json", prints[-2000:])
    return added


def slot_rects() -> dict:
    """{chiave: rettangolo mediano} degli spazi visti almeno 2 volte."""
    out = {}
    for key, rects in _load("spazi.json", {}).items():
        if len(rects) >= 2:
            out[key] = [statistics.median(r[i] for r in rects) for i in range(4)]
    return out


def recognize(img: Image.Image) -> dict:
    """{chiave spazio: (nome, distanza)} per gli spazi in cui l'impronta somiglia a una carta conosciuta."""
    prints = [(p["nome"], int(p["h"], 16)) for p in _load("impronte.json", [])]
    if not prints:
        return {}
    out = {}
    for key, rect in slot_rects().items():
        crop = _crop(img, rect)
        if crop is None:
            continue
        h = dhash(crop)
        name, d = min(((n, _dist(h, ph)) for n, ph in prints), key=lambda x: x[1])
        if d <= SOGLIA:
            out[key] = (name, d)
    return out


def check(img: Image.Image, board: dict) -> list[str]:
    """Nomi del campo che l'atlante riconosce diversamente da come li ha scritti il lettore."""
    seen = recognize(img)
    warn = []
    for key, (name, d) in seen.items():
        lane, side, k = key.split(":")
        units = ((board.get(lane) or {}).get(side) or [])
        k = int(k)
        written = _name(units[k]) if k < len(units) else None
        if written and store.slug(written) != store.slug(name):
            warn.append(f"campo {lane} {'tuo' if side == 'mie' else 'avversario'} slot {k + 1}: letto «{written}», "
                        f"l'immagine somiglia a «{name}»")
    return warn


def stats() -> dict:
    prints = _load("impronte.json", [])
    return {"carte": len({p["nome"] for p in prints}), "impronte": len(prints), "spazi": len(slot_rects())}
