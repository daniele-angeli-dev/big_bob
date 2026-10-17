"""Piccoli aiuti per Windows: istanza unica, icona della finestra, terminale di Claude Code.
Su altri sistemi le funzioni non fanno nulla (così i test girano ovunque)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("bigbob")
WIN = sys.platform == "win32"
TERMINAL_TITLE = "BIG-BOB · Claude Code"
_mutex = None  # tenuto in vita finché BIG-BOB è aperto


def single_instance(name: str = "Local\\BIGBOB_istanza_unica") -> bool:
    """True se questa è l'unica istanza di BIG-BOB; False se ce n'è già una aperta."""
    global _mutex
    if not WIN:
        return True
    import ctypes
    k32 = ctypes.windll.kernel32
    _mutex = k32.CreateMutexW(None, False, name)
    return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _find(title: str):
    if not WIN:
        return None
    import ctypes
    return ctypes.windll.user32.FindWindowW(None, title) or None


WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004 e successivi


def exclude_from_capture(title: str = "BIG-BOB", on: bool = True) -> bool:
    """Rende la finestra invisibile alle catture dello schermo: sul monitor si vede, ma chi cattura lo schermo (BIG-BOB
    stesso, ma anche registrazioni e strumenti di cattura) vede quello che c'è sotto, cioè il gioco.
    Così le catture non devono più nascondere la finestra (niente lampeggi) e non hanno zone nere.
    Restituisce True se Windows l'ha accettato."""
    h = _find(title)
    if not h:
        return False
    try:
        import ctypes
        import sys
        if sys.getwindowsversion().build < 19041:  # prima della 2004 il valore non esiste
            return False
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
    except Exception:  # noqa: BLE001
        return False


def activate(hwnd) -> bool:
    """Porta in primo piano una finestra (il gioco, prima che il pilota automatico clicchi). True se ora è davanti."""
    if not WIN or not hwnd:
        return False
    import ctypes
    u = ctypes.windll.user32
    if u.GetForegroundWindow() == hwnd:
        return True
    u.ShowWindow(hwnd, 9)  # SW_RESTORE
    u.SetForegroundWindow(hwnd)
    return u.GetForegroundWindow() == hwnd


def focus_window(title: str = "BIG-BOB") -> bool:
    """Riporta in primo piano una finestra già aperta (anche se era nascosta con F10)."""
    h = _find(title)
    if not h:
        return False
    import ctypes
    u = ctypes.windll.user32
    u.ShowWindow(h, 5)   # SW_SHOW
    u.ShowWindow(h, 9)   # SW_RESTORE
    u.SetForegroundWindow(h)
    return True


def set_window_icon(title: str, ico: Path) -> bool:
    """Mette l'icona di BIG-BOB alla finestra (Alt+Tab e barra delle applicazioni)."""
    h = _find(title)
    if not h or not ico.exists():
        return False
    import ctypes
    u = ctypes.windll.user32
    for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
        hicon = u.LoadImageW(None, str(ico), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if hicon:
            u.SendMessageW(h, 0x80, which, hicon)  # WM_SETICON
    return True


def terminal_open() -> bool:
    if not WIN:
        return False
    try:
        import pygetwindow as gw
        return any(TERMINAL_TITLE.lower() in w.title.lower() for w in gw.getAllWindows())
    except Exception:  # noqa: BLE001
        return False


def open_claude_terminal(root: Path) -> str:
    """Apre (o riporta in primo piano) il terminale di Claude Code nella cartella di BIG-BOB."""
    if not WIN:
        return "Il terminale si apre solo su Windows."
    if terminal_open():
        try:
            import pygetwindow as gw
            w = next(w for w in gw.getAllWindows() if TERMINAL_TITLE.lower() in w.title.lower())
            if w.isMinimized:
                w.restore()
            w.activate()
        except Exception:  # noqa: BLE001
            pass
        return "Claude Code è già aperto."
    import configura
    exe = configura.find_claude() or "claude"
    try:
        if shutil.which("wt"):
            subprocess.Popen(["wt", "-w", "new", "--title", TERMINAL_TITLE, "--suppressApplicationTitle",
                              "-d", str(root), "cmd", "/k", exe])
        else:
            subprocess.Popen(f'start "{TERMINAL_TITLE}" cmd /k "{exe}"', shell=True, cwd=str(root))
        return "Claude Code aperto."
    except Exception as e:  # noqa: BLE001
        log.exception("apertura terminale")
        return f"Non riesco ad aprire Claude Code: {e}"
