"""Cattura dello schermo: finestra del gioco (se trovata) o monitor principale."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "captures"
HISTORY = CAPTURES / "storico"
SCAN = CAPTURES / "scan"
RECORDINGS = CAPTURES / "registrazioni"
for d in (CAPTURES, HISTORY, SCAN, RECORDINGS):
    d.mkdir(parents=True, exist_ok=True)

MAX_WIDTH = 1600   # abbastanza per leggere i testi delle carte, senza sprecare token
HISTORY_KEEP = 40

if sys.platform == "win32":
    try:  # coordinate corrette con lo scaling di Windows (125%, 150%...)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


EXCLUDE = ("big-bob", "claude", "cmd.exe", "powershell", "terminal", "esplora", "explorer",
           "chrome", "edge", "firefox", "opera", "brave", "discord")
FRESH_SECONDS = 20  # get_screen riusa la cattura fatta dall'overlay se è più recente di così
last_source = "nessuna cattura"
last_region = None  # (left, top, width, height) in pixel dello schermo dell'ultima cattura: serve al pilota automatico


def list_windows() -> list[dict]:
    """Tutte le finestre visibili (per la diagnosi)."""
    if sys.platform != "win32":
        return []
    import pygetwindow as gw
    out = []
    for w in gw.getAllWindows():
        if w.title.strip() and w.width > 100 and w.height > 100:
            out.append({"titolo": w.title, "x": w.left, "y": w.top, "w": w.width, "h": w.height,
                        "minimizzata": w.isMinimized})
    return out


def _game_region(title: str):
    """Restituisce (left, top, width, height, titolo) della finestra del gioco, o None.
    Il confronto sul titolo non distingue maiuscole/minuscole."""
    if sys.platform != "win32":
        return None
    try:
        import pygetwindow as gw
    except ImportError:
        return None
    t = title.lower()
    wins = [w for w in gw.getAllWindows()
            if t in w.title.lower() and w.width > 300 and w.height > 300 and not w.isMinimized
            and not any(x in w.title.lower() for x in EXCLUDE)]
    if not wins:
        return None
    w = max(wins, key=lambda w: w.width * w.height)
    return (max(w.left, 0), max(w.top, 0), w.width, w.height, w.title)


_region_cache: dict = {"t": 0.0, "title": None, "region": None}


def game_window(title: str):
    """(hwnd, (left, top, width, height)) della finestra del gioco, o None."""
    if sys.platform != "win32":
        return None
    try:
        import pygetwindow as gw
    except ImportError:
        return None
    t = title.lower()
    wins = [w for w in gw.getAllWindows()
            if t in w.title.lower() and w.width > 300 and w.height > 300 and not w.isMinimized
            and not any(x in w.title.lower() for x in EXCLUDE)]
    if not wins:
        return None
    w = max(wins, key=lambda w: w.width * w.height)
    return getattr(w, "_hWnd", None), (max(w.left, 0), max(w.top, 0), w.width, w.height)


def _game_region_cached(title: str, max_age: float = 2.0):
    """Come _game_region, ma rilegge l'elenco delle finestre al massimo ogni max_age secondi: l'osservatore cattura
    3 volte al secondo e l'elenco delle finestre è la parte lenta."""
    c = _region_cache
    if c["title"] != title or time.time() - c["t"] > max_age:
        c.update(t=time.time(), title=title, region=_game_region(title))
    return c["region"]


def grab_fast(title: str = "Origins", mask=None) -> Image.Image:
    """Cattura per l'osservatore: alla risoluzione piena (i ritagli restano leggibili), senza ridimensionare (lento),
    con la finestra del gioco rilevata al massimo ogni 2 secondi. mask = zona da annerire (se BIG-BOB non è
    invisibile alle catture)."""
    global last_source
    import mss
    from PIL import ImageDraw
    with mss.mss() as sct:
        region = _game_region_cached(title)
        if region:
            l, t, w, h, name = region
            mon = {"left": l, "top": t, "width": w, "height": h}
            last_source = f"finestra '{name}'"
        else:
            mon = sct.monitors[1]
            last_source = f"schermo intero (nessuna finestra con '{title}' nel titolo)"
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if mask:
        sx, sy = img.width / mon["width"], img.height / mon["height"]
        ml, mt, mw, mh = mask
        rl, rt = mon["left"], mon["top"]
        ImageDraw.Draw(img).rectangle(((ml - rl) * sx, (mt - rt) * sy, (ml - rl + mw) * sx, (mt - rt + mh) * sy),
                                      fill=(0, 0, 0))
    return img


def grab(title: str = "Origins") -> Image.Image:
    return grab_with_region(title)[0]


def grab_with_region(title: str = "Origins"):
    """Come grab, ma restituisce anche la regione catturata (left, top, width, height) in pixel reali."""
    global last_source, last_region
    import mss
    with mss.mss() as sct:
        region = _game_region(title)
        if region:
            l, t, w, h, name = region
            mon = {"left": l, "top": t, "width": w, "height": h}
            last_source = f"finestra '{name}'"
        else:
            mon = sct.monitors[1]
            last_source = f"schermo intero (nessuna finestra con '{title}' nel titolo)"
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    reg = (mon["left"], mon["top"], mon["width"], mon["height"])
    last_region = reg
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, int(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    return img, reg


def capture(title: str = "Origins", folder: Path | None = None, prefix: str = "") -> Path:
    """Cattura e salva. Ritorna il percorso del file salvato."""
    img = grab(title)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    if folder is None:
        latest = CAPTURES / "ultimo.png"
        img.save(latest)
        hist = HISTORY / f"{stamp}.png"
        img.save(hist)
        files = sorted(HISTORY.glob("*.png"))
        for old in files[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)
        return latest
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{prefix}{stamp}.png"
    img.save(p)
    return p


def latest_if_fresh() -> Path | None:
    """L'ultima cattura dell'overlay, se recente (fatta con l'overlay nascosto)."""
    p = CAPTURES / "ultimo.png"
    if p.exists() and time.time() - p.stat().st_mtime < FRESH_SECONDS:
        return p
    return None


def thumbnail_signature(title: str = "Origins", size=(96, 54), mask=None):
    """Miniatura in scala di grigi per rilevare cambi di schermata (modalità auto).
    mask = (left, top, width, height) in pixel dello schermo da ignorare (es. l'overlay)."""
    from PIL import ImageDraw
    img, (rl, rt, rw, rh) = grab_with_region(title)
    img = img.convert("L")
    if mask:
        sx, sy = img.width / rw, img.height / rh
        ml, mt, mw, mh = mask
        box = ((ml - rl) * sx, (mt - rt) * sy, (ml - rl + mw) * sx, (mt - rt + mh) * sy)
        ImageDraw.Draw(img).rectangle(box, fill=0)
    return img.resize(size)


def grab_masked(title: str = "Origins", mask=None, max_width: int = 1024) -> Image.Image:
    """Cattura del gioco SENZA nascondere BIG-BOB: la zona coperta dalla sua finestra diventa nera.
    Serve all'osservatore, che guarda la partita tra un F8 e l'altro senza far lampeggiare la finestra."""
    from PIL import ImageDraw
    img, (rl, rt, rw, rh) = grab_with_region(title)
    if mask:
        sx, sy = img.width / rw, img.height / rh
        ml, mt, mw, mh = mask
        ImageDraw.Draw(img).rectangle(((ml - rl) * sx, (mt - rt) * sy, (ml - rl + mw) * sx, (mt - rt + mh) * sy),
                                      fill=(0, 0, 0))
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
    return img


def recent_history(n: int = 3) -> list[Path]:
    return sorted(HISTORY.glob("*.png"))[-n:]


def new_recording() -> Path:
    d = RECORDINGS / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_empty_recordings(min_age_s: float = 120) -> int:
    """Toglie le registrazioni vuote (avviate e fermate senza fotogrammi, o lasciate da vecchi collaudi)."""
    import shutil
    n = 0
    if not RECORDINGS.exists():
        return 0
    for d in RECORDINGS.iterdir():
        try:
            if d.is_dir() and not frames_in(d) and not (d / "ELABORATA").exists() \
                    and time.time() - d.stat().st_mtime > min_age_s:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError:
            continue
    return n


def frames_in(d: Path) -> list[Path]:
    """I fotogrammi di una registrazione (JPEG dalle versioni nuove, PNG dalle vecchie)."""
    return sorted(p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))


def list_recordings() -> list[dict]:
    out = []
    for d in sorted(p for p in RECORDINGS.iterdir() if p.is_dir()):
        frames = frames_in(d)
        out.append({"nome": d.name, "cartella": str(d), "fotogrammi": len(frames),
                    "elaborata": (d / "ELABORATA").exists()})
    return out
