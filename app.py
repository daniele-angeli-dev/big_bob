"""BIG-BOB · finestra in stile Arena (HTML in WebView2, già incluso in Windows 11).

Avvio: avvia_BIG-BOB.bat. Se la finestra HTML non può partire (libreria o WebView2 mancanti),
si apre automaticamente la finestra classica (overlay.py), così BIG-BOB è sempre disponibile.

Tasti: F8 analizza · F9 cattura per scansione · F10 mostra/nasconde.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(filename=ROOT / "logs" / "bigbob.log", level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bigbob")
if sys.stderr is None:  # pythonw non ha console
    sys.stderr = open(ROOT / "logs" / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115
if sys.stdout is None:
    sys.stdout = sys.stderr

from origins import store, winutil  # noqa: E402

WIDTH, HEIGHT = 440, 760


class WebUI:
    """Adattatore tra il controller e la finestra pywebview."""

    def __init__(self) -> None:
        self.window = None
        self._loaded = threading.Event()
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._visible = True

    def attach(self, window) -> None:
        self.window = window

    def on_ready(self) -> None:
        with self._lock:
            pending, self._buffer = self._buffer, []
            self._loaded.set()
        for ev in pending:
            self.emit(ev)

    def emit(self, ev: dict) -> None:
        if not self._loaded.is_set() or self.window is None:
            with self._lock:
                if not self._loaded.is_set():
                    self._buffer.append(ev)
                    return
        js = "window.BB && BB.push(%s)" % json.dumps(ev, ensure_ascii=False)
        with self._lock:
            self.window.evaluate_js(js)

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()
            self._visible = False

    def show(self) -> None:
        if self.window is not None:
            self.window.show()
            self.window.on_top = True
            self._visible = True

    def is_visible(self) -> bool:
        return self._visible

    def quit(self) -> None:
        try:
            if self.window is not None:
                self.window.destroy()
        finally:
            os._exit(0)

    def rect(self):
        try:
            w = self.window
            return (w.x, w.y, w.width, w.height)
        except Exception:  # noqa: BLE001
            return None


class Api:
    """Metodi chiamati dalla pagina HTML (window.pywebview.api.<nome>)."""

    def __init__(self, ctrl, ui: WebUI) -> None:
        self._c = ctrl
        self._ui = ui

    def ready(self):
        self._ui.on_ready()
        self._c.emit_state()

    def analyze(self):
        self._c.analyze()

    def chat(self, text):
        self._c.chat(text)

    def scan(self):
        self._c.scan()

    def new_match(self, deck):
        self._c.new_match(deck)

    def end_match(self, result):
        self._c.end_match(result)

    def flag(self, note):
        self._c.flag(note)

    def toggle_mode(self):
        self._c.toggle_mode()

    def set_auto(self, on):
        self._c.set_auto(on)

    def set_record(self, on):
        self._c.set_record(on)

    def set_voice(self, on):
        self._c.set_voice(on)

    def open_stats(self):
        self._c.open_stats()

    def open_replay(self):
        self._c.open_replay()

    def toggle_visibility(self):
        self._c.toggle_visibility()

    def get_settings(self):
        self._c.get_settings()

    def save_settings(self, vals):
        self._c.save_settings(vals or {})

    def claude_login(self):
        self._c.claude_login()

    def claude_test(self):
        self._c.claude_test()

    def check_updates(self):
        self._c.check_updates()

    def sync_meta(self):
        self._c.sync_meta()

    def apply_update(self):
        self._c.apply_update()

    def open_terminal(self):
        self._c.say(winutil.open_claude_terminal(ROOT), "dim")

    def quit(self):
        log.info("chiusura richiesta dalla finestra")
        try:
            self._ui.window.destroy()
        finally:
            os._exit(0)


def register_hotkeys(ctrl) -> bool:
    cfg = store.load("config")
    try:
        import keyboard
        keyboard.add_hotkey(cfg.get("hotkey_analisi", "f8"), ctrl.analyze)
        keyboard.add_hotkey(cfg.get("hotkey_scan", "f9"), ctrl.scan)
        keyboard.add_hotkey("f10", ctrl.toggle_visibility)
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("scorciatoie non registrate")
        ctrl.say(f"Scorciatoie globali non attive ({e}): usa i pulsanti F8 e F9.", "warn")
        return False


def run_web() -> None:
    import webview

    from controller import Controller

    ui = WebUI()
    ctrl = Controller(ui)
    api = Api(ctrl, ui)
    from ui.render import page
    html = page()

    x = y = None
    try:
        scr = webview.screens[0]
        x, y = max(0, scr.width - WIDTH - 20), 50
    except Exception:  # noqa: BLE001
        pass

    window = webview.create_window(
        "BIG-BOB", html=html, js_api=api, width=WIDTH, height=HEIGHT, x=x, y=y,
        min_size=(380, 560), frameless=True, easy_drag=False, on_top=True, resizable=True,
        background_color="#24104F", text_select=True, focus=True)
    ui.attach(window)

    def on_start():
        ctrl.start()
        register_hotkeys(ctrl)
        try:
            window.events.shown.wait(10)
            winutil.set_window_icon("BIG-BOB", ROOT / "ui" / "bigbob.ico")
        except Exception:  # noqa: BLE001
            log.exception("icona finestra")
        if store.load("config").get("apri_claude_code_all_avvio", True):
            ctrl.say(winutil.open_claude_terminal(ROOT) + " Lo usi per /scansiona, /mazzo, /lezioni… "
                     "(si spegne con apri_claude_code_all_avvio: false in config.json)", "dim")
        # se l'evento pywebviewready non arriva (rarissimo), sblocca comunque gli eventi
        threading.Timer(4.0, lambda: (not ui._loaded.is_set()) and ui.on_ready()).start()

    webview.start(on_start, gui="edgechromium", debug=os.environ.get("BIGBOB_DEBUG") == "1")


def run_classic(reason: str) -> None:
    log.warning("Avvio della finestra classica: %s", reason)
    import overlay
    ov = overlay.Overlay()
    ov._say(f"Finestra classica (la nuova grafica non è partita: {reason}). "
            "Rilancia installa.bat; i dettagli sono in logs/bigbob.log.", "warn")
    ov.run()


if __name__ == "__main__":
    if not winutil.single_instance():
        # BIG-BOB è già aperto: lo riporta in primo piano invece di aprirne un secondo
        winutil.focus_window("BIG-BOB")
        sys.exit(0)
    if "--classica" in sys.argv:
        run_classic("richiesta dall'utente")
    else:
        try:
            run_web()
        except Exception as e:  # noqa: BLE001
            log.exception("finestra HTML non avviata")
            run_classic(f"{type(e).__name__}: {e}")
