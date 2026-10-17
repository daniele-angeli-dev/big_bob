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
PAGE_LOAD_WAIT = 60
if sys.stderr is None:  # pythonw non ha console
    sys.stderr = open(ROOT / "logs" / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115
if sys.stdout is None:
    sys.stdout = sys.stderr

from origins import store, winutil  # noqa: E402

WIDTH, HEIGHT = 440, 1000  # alta: la chat deve avere spazio sotto il pannello della partita


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

    PAGE_TIMEOUT = 12  # secondi: se la finestra delle pagine non si carica entro questo tempo apro il browser

    def show_html(self, html: str, title: str = "BIG-BOB", fallback=None) -> bool:
        """Mostra una pagina di BIG-BOB (mazzi, studio, statistiche, replay) in una sua finestra dentro l'app: i dati
        arrivano direttamente alla finestra, senza file e senza browser. La finestra si riusa.
        Se entro PAGE_TIMEOUT secondi la pagina non risulta caricata (finestra bloccata o rimasta vuota), la chiudo e
        chiamo fallback (che apre la stessa pagina nel browser)."""
        import time
        t0, loaded = time.time(), threading.Event()
        threading.Thread(target=self._show_page, args=(html, title, loaded), daemon=True, name="bb-pagina").start()

        def watchdog():
            ok = loaded.wait(self.PAGE_TIMEOUT)
            log.info("pagina «%s» %s in %.1f s", title, "caricata" if ok else "NON caricata", time.time() - t0)
            if ok or fallback is None:
                return
            w, self._page_window = getattr(self, "_page_window", None), None
            if w is not None:
                try:
                    w.destroy()
                except Exception:  # noqa: BLE001
                    pass
            try:
                fallback()
            except Exception:  # noqa: BLE001
                log.exception("apertura della pagina nel browser")
        threading.Thread(target=watchdog, daemon=True, name="bb-pagina-controllo").start()
        return True

    def _show_page(self, html: str, title: str, loaded: threading.Event) -> None:
        try:
            import webview
            url = None
            if len(html.encode("utf-8")) > 1_800_000:  # Windows accetta pagine dirette fino a ~2 MB: oltre uso un file
                f = ROOT / "logs" / "pagina.html"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(html, encoding="utf-8")
                url = f.resolve().as_uri()
            w = getattr(self, "_page_window", None)
            if w is not None:
                try:
                    w.load_url(url) if url else w.load_html(html)
                    w.set_title(title)
                    w.show()
                    w.restore()
                    if w.events.loaded.wait(PAGE_LOAD_WAIT):
                        loaded.set()
                    return
                except Exception:  # noqa: BLE001  (finestra chiusa nel frattempo)
                    log.exception("finestra delle pagine non riutilizzabile")
                    self._page_window = None
            width, height = 1060, 860
            try:
                scr = webview.screens[0]
                width, height = min(width, scr.width - 60), min(height, scr.height - 80)
            except Exception:  # noqa: BLE001
                pass
            w = webview.create_window(title, **({"url": url} if url else {"html": html}), width=width, height=height,
                                      js_api=getattr(self, "api", None), min_size=(420, 480),
                                      on_top=True, resizable=True, background_color="#24104F", text_select=True,
                                      focus=True)

            def closed():
                if self._page_window is w:
                    self._page_window = None
            try:
                w.events.closed += closed
            except Exception:  # noqa: BLE001
                pass
            self._page_window = w
            if w.events.loaded.wait(PAGE_LOAD_WAIT):
                loaded.set()
        except Exception:  # noqa: BLE001
            log.exception("finestra delle pagine")

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

    def create_deck(self, goal="", games=10):
        self._c.create_deck(goal, games)

    def lab_apply(self):
        self._c.lab_apply()

    def open_lab(self):
        self._c.open_lab()

    def open_library(self, tab="mazzi", deck=""):
        self._c.open_library(tab or "mazzi", deck or "")

    def open_origin(self):
        self._c.open_origin()

    def open_site(self, url="https://originsmeta.com/it"):
        self._c.open_site(url)

    def study_recordings(self):
        self._c.study_recordings()

    def tutorial_done(self):
        self._c.tutorial_done()

    def open_learned(self):
        self._c.open_learned()

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

    def sync_brain(self):
        self._c.sync_brain()

    def brain_consent(self, ok=True):
        self._c.brain_consent(bool(ok))

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


def _available_height(webview) -> int:
    """Altezza utile dello schermo (senza la barra delle applicazioni), nelle unità della finestra."""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            try:
                scale = (ctypes.windll.user32.GetDpiForSystem() or 96) / 96
            except Exception:  # noqa: BLE001
                scale = 1
            return int((rect.bottom - rect.top) / scale)
    except Exception:  # noqa: BLE001
        pass
    try:
        return int(webview.screens[0].height) - 60
    except Exception:  # noqa: BLE001
        return HEIGHT


def run_web() -> None:
    import webview

    from controller import Controller

    ui = WebUI()
    ctrl = Controller(ui)
    api = Api(ctrl, ui)
    ui.api = api  # anche la finestra delle pagine può chiedere cose a BIG-BOB (studia, aggiorna, apri il sito)
    from ui.render import page
    html = page()

    # al centro dello schermo (x/y non indicati: pywebview centra la finestra tenendo conto del ridimensionamento
    # di Windows); su schermi bassi la finestra si accorcia per starci tutta
    height = min(HEIGHT, max(560, _available_height(webview) - 24))

    window = webview.create_window(
        "BIG-BOB", html=html, js_api=api, width=WIDTH, height=height,
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
        cfg = store.load("config")
        if not cfg.get("terminale_v2"):  # da ottobre 2026 il terminale non si apre più da solo
            cfg["apri_claude_code_all_avvio"] = False
            cfg["terminale_v2"] = True
            store.save("config", cfg)
            ctrl.say("Il terminale di Claude Code non si apre più all'avvio: le risposte live non ne hanno bisogno. "
                     "Per /mazzo, /scansiona, /lezioni… premi >_ (o riattivalo in ⚙).", "dim")
        if cfg.get("apri_claude_code_all_avvio", False):
            ctrl.say(winutil.open_claude_terminal(ROOT) + " Lo usi per /scansiona, /mazzo, /lezioni… "
                     "(si spegne in ⚙ Impostazioni)", "dim")
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
