"""Pilota automatico (solo allenamento e creazione, mai ranked): BIG-BOB gioca al posto di Daniele.

Claude, nella risposta live, aggiunge una riga che inizia con 🤖 e descrive le azioni sulla schermata che ha appena
visto, con coordinate in percentuale (0-100) della schermata:
    🤖 trascina 31.5,88.0 > 42.0,55.5 ; trascina 60.2,89.1 > 50.0,40.0 ; clicca 91.0,92.5
    🤖 niente
Qui le coordinate diventano pixel dello schermo (con la regione del gioco catturata in quel momento) e le azioni si
eseguono con il mouse di Windows. Sicurezza:
- se muovi il mouse mentre il pilota lavora, si ferma subito (e si spegne);
- F12 lo spegne;
- agisce solo se la finestra del gioco è ancora dove era nella schermata e i punti cadono dentro di essa;
- al massimo MAX_AZIONI azioni per risposta e MAX_PER_ROUND risposte con azioni per round.
"""
from __future__ import annotations

import re
import sys
import time

WIN = sys.platform == "win32"
MAX_AZIONI = 10
MAX_PER_ROUND = 2
_NUM = r"(\d{1,3}(?:[.,]\d+)?)"
_PT = rf"{_NUM}\s*[,;/ ]\s*{_NUM}"
DRAG_RE = re.compile(rf"(?:trascina|drag)\s*\(?\s*{_PT}\s*\)?\s*(?:>|->|→|a|to)\s*\(?\s*{_PT}\s*\)?", re.I)
CLICK_RE = re.compile(rf"(?:clicca|click|premi)\s*\(?\s*{_PT}\s*\)?", re.I)


def _f(x: str) -> float:
    return max(0.0, min(100.0, float(x.replace(",", "."))))


def parse(text: str) -> list[dict] | None:
    """Le azioni della riga 🤖 (None se la riga non c'è, [] se dice 'niente')."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("🤖")), None)
    if line is None:
        return None
    body = line.lstrip("🤖").strip()
    out: list[dict] = []
    for part in re.split(r"\s*;\s*|\s+\|\s+", body):
        m = DRAG_RE.search(part)
        if m:
            out.append({"tipo": "trascina", "da": (_f(m.group(1)), _f(m.group(2))), "a": (_f(m.group(3)), _f(m.group(4)))})
            continue
        m = CLICK_RE.search(part)
        if m:
            out.append({"tipo": "clicca", "a": (_f(m.group(1)), _f(m.group(2)))})
    return out[:MAX_AZIONI]


def to_screen(pt: tuple[float, float], region: tuple[int, int, int, int]) -> tuple[int, int]:
    """Da percentuale della schermata a pixel dello schermo (region = left, top, width, height della cattura)."""
    left, top, w, h = region
    x = left + round(pt[0] / 100 * (w - 1))
    y = top + round(pt[1] / 100 * (h - 1))
    return x, y


def describe(actions: list[dict]) -> str:
    parts = []
    for a in actions:
        if a["tipo"] == "trascina":
            parts.append(f"trascina {a['da'][0]:.1f},{a['da'][1]:.1f} > {a['a'][0]:.1f},{a['a'][1]:.1f}")
        else:
            parts.append(f"clicca {a['a'][0]:.1f},{a['a'][1]:.1f}")
    return " ; ".join(parts) or "niente"


class Interrotto(Exception):
    """Daniele ha mosso il mouse (o ha premuto F12): il pilota si ferma."""


class Mouse:
    """Mouse di Windows (SetCursorPos + mouse_event). Fuori da Windows non fa nulla (serve ai test)."""

    TOLL = 25  # pixel: se il cursore non è dove l'ho messo, l'ha spostato Daniele

    def __init__(self, stop=lambda: False):
        self.stop = stop
        self.last: tuple[int, int] | None = None

    def pos(self) -> tuple[int, int] | None:
        if not WIN:
            return self.last
        import ctypes
        from ctypes import wintypes
        p = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def _check(self) -> None:
        if self.stop():
            raise Interrotto("pilota spento")
        cur = self.pos()
        if self.last and cur and (abs(cur[0] - self.last[0]) > self.TOLL or abs(cur[1] - self.last[1]) > self.TOLL):
            raise Interrotto("hai mosso il mouse")

    def move(self, x: int, y: int) -> None:
        self._check()
        if WIN:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        self.last = (int(x), int(y))

    def button(self, down: bool) -> None:
        if WIN:
            import ctypes
            ctypes.windll.user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)  # LEFTDOWN / LEFTUP

    def click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.08)
        self.button(True)
        time.sleep(0.06)
        self.button(False)

    def drag(self, a: tuple[int, int], b: tuple[int, int], steps: int = 18) -> None:
        """Trascinamento con movimento graduale: i giochi Unity riconoscono il trascinamento solo se il mouse si muove
        davvero con il tasto premuto."""
        self.move(*a)
        time.sleep(0.1)
        self.button(True)
        try:
            time.sleep(0.12)
            for i in range(1, steps + 1):
                t = i / steps
                e = t * t * (3 - 2 * t)
                self.move(round(a[0] + (b[0] - a[0]) * e), round(a[1] + (b[1] - a[1]) * e))
                time.sleep(0.016)
            time.sleep(0.12)
        finally:
            self.button(False)


def inside(p: tuple[int, int], region: tuple[int, int, int, int]) -> bool:
    left, top, w, h = region
    return left <= p[0] < left + w and top <= p[1] < top + h


def run(actions: list[dict], region: tuple[int, int, int, int], mouse: Mouse | None = None,
        pause: float = 0.45) -> list[str]:
    """Esegue le azioni; restituisce cosa ha fatto (per il diario). Interrotto se Daniele prende il mouse."""
    mouse = mouse or Mouse()
    mouse.last = mouse.pos()
    done = []
    for a in actions:
        if a["tipo"] == "trascina":
            p, q = to_screen(a["da"], region), to_screen(a["a"], region)
            if not (inside(p, region) and inside(q, region)):
                done.append(f"saltata (fuori dal gioco): {describe([a])}")
                continue
            mouse.drag(p, q)
            done.append(f"trascinata da {p} a {q}")
        else:
            p = to_screen(a["a"], region)
            if not inside(p, region):
                done.append(f"saltato (fuori dal gioco): {describe([a])}")
                continue
            mouse.click(*p)
            done.append(f"cliccato {p}")
        time.sleep(pause)  # il tempo al gioco di posare la carta e aggiornare la mano
    return done


def overlaps(points: list[tuple[int, int]], rect) -> bool:
    """True se un punto cade sulla finestra di BIG-BOB (che è sopra al gioco: il clic finirebbe su di lei)."""
    if not rect:
        return False
    x, y, w, h = rect
    return any(x <= p[0] < x + w and y <= p[1] < y + h for p in points)


def points(actions: list[dict], region) -> list[tuple[int, int]]:
    pts = []
    for a in actions:
        if a["tipo"] == "trascina":
            pts.append(to_screen(a["da"], region))
        pts.append(to_screen(a["a"], region))
    return pts
