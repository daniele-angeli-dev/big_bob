"""Test del controller (logica della finestra) con un Claude Code finto: python tests/test_controller.py"""
import shutil
import sys
import os as _os
_os.environ["BIGBOB_NO_SYNC"] = "1"
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from origins import screen, store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp
screen.SCAN = tmp / "scan"
screen.SCAN.mkdir()
screen.RECORDINGS = tmp / "registrazioni"  # le registrazioni del test non devono finire tra quelle vere
from origins import spazio  # noqa: E402
spazio.LOGS, spazio.CAPTURES = tmp / "logs", tmp  # la pulizia del test non tocca i dati veri
shot = tmp / "shot.png"
Image.new("RGB", (32, 20), "purple").save(shot)


def fake_capture(title="Origins", folder=None, prefix=""):
    dst = (folder or tmp) / (f"{prefix}{time.time_ns()}.png")
    shutil.copy(shot, dst)
    return dst


screen.capture = fake_capture
screen.last_source = "finestra 'test'"

import controller  # noqa: E402

controller.ROOT = tmp  # diario in una cartella temporanea


class FakeSession(controller.ClaudeSession):
    def _cmd(self):
        return [sys.executable, str(ROOT / "tests" / "fake_claude.py")]


class FakeUI:
    def __init__(self):
        self.events, self.vis, self.hides = [], True, 0
        self.idle = threading.Event()

    def emit(self, ev):
        self.events.append(ev)
        if ev["type"] == "busy" and not ev["value"]:
            self.idle.set()

    def hide(self):
        self.vis, self.hides = False, self.hides + 1

    def show(self):
        self.vis = True

    def is_visible(self):
        return self.vis

    def rect(self):
        return (0, 0, 10, 10)

    def of(self, t):
        return [e for e in self.events if e["type"] == t]


def wait(ui, fn, *a):
    ui.idle.clear()
    fn(*a)
    assert ui.idle.wait(20), "timeout"


# --- parser della risposta live ---
p = controller.parse_live("R4 · mana 5\n▶ Giocata: Little John a destra — chiudi la destra\n⚠ Brides 41%\n🎴 Marian 12%\n"
                          "👁 Avversario: Garlic 33%\n📍 Centro: spell -1\nnota")
assert p["mossa"] == "Little John a destra" and p["perche"] == "chiudi la destra", p
assert p["minacce"] == ["Brides 41%"] and p["pescate"] == ["Marian 12%"] and p["avv_mano"] == ["Garlic 33%"]
assert p["location"] == ["Centro: spell -1"] and p["altro"] == ["nota"], p
assert controller.parse_live("solo testo") is None

# --- controller con sessione persistente ---
ui = FakeUI()
c = controller.Controller(ui)
c.claude = "fake"
c.session = FakeSession("fake", tmp)
c.readers = {}  # i lettori veri non partono nei test (quelli finti più sotto)
c.start()
store.save("match", {"turno": 4, "mana": 5, "barrier_mie": [20, 8, 20], "barrier_avv": [12, 20, 31],
                     "rinforzate_avv": [False, False, True], "distrutte_da_me": 1, "distrutte_a_me": 0,
                     "rivela_prima": "io", "mio_mazzo": "Test"})

wait(ui, c.new_match, "Test")
assert c.journal_dir is not None and (c.journal_dir / "diario.md").exists()
pid1 = c.session.proc.pid

wait(ui, c.analyze)
time.sleep(0.3)
assert not [e for e in ui.events if e.get("role") == "lesson"], "al primo round non c'è niente da confrontare"
ans = ui.of("answer")[-1]
assert ans["parsed"]["mossa"] == "Little John a destra, Marian al centro", ans
assert "img=True" in ans["text"], "la schermata deve essere allegata all'analisi"
time.sleep(1.2)  # apprendimento in background, poi il contesto riparte pulito con un processo già acceso
assert c._session_free.wait(10) and c.session.proc and c.session.proc.pid != pid1 and c.session.alive(), \
    "dopo ogni round una sessione nuova (senza le immagini dei round prima), già accesa per il prossimo F8"
assert ui.hides >= 2 and ui.vis, "la finestra si nasconde durante la cattura e ricompare"

# secondo round: risposta subito, poi apprendimento in background
t = time.time()
wait(ui, c.analyze)
assert time.time() - t < 3, "la risposta live non deve aspettare l'apprendimento"
assert c.learning or not c._session_free.is_set() or [e for e in ui.events if e.get("role") == "lesson"]
wait(ui, c.chat, "quante carte ho?")   # deve aspettare la fine dell'apprendimento, non saltarlo
assert "img=False" in ui.of("answer")[-1]["text"], "le domande in chat non allegano la schermata"
les = [e for e in ui.events if e.get("role") == "lesson"]
assert les and les[-1]["text"] == "Dracula tiene Brides per il centro", les
assert ui.of("learning")

# lettura veloce: due lettori in parallelo, update_match fatto da BIG-BOB, il coach pensa solo alla mossa
class FakeReader(controller.ReaderSession):
    def _cmd(self):
        return [sys.executable, str(ROOT / "tests" / "fake_claude.py")]


c._session_free.wait(10)
c.readers = {"mio": FakeReader("fake", tmp), "avv": FakeReader("fake", tmp)}
m0 = store.load("match")
m0.update({"carte_mie": ["Marian", "Little John", "Friar Tuck"], "leggendaria_mia": "Robin Hood",
           "avv_leggendaria": "Dracula"})
store.save("match", m0)
t = time.time()
wait(ui, c.analyze)
ans = ui.of("answer")[-1]
assert "letto=si" in ans["text"] and "img=True" in ans["text"], ans
assert "recenti=si" in ans["text"], "il coach riceve i consigli dei round prima (il contesto riparte pulito)"
m1 = store.load("match")
assert m1["turno"] == 5 and m1["mia_mano"] == ["Marian", "Little John"] and "Bat" in m1["avv_giocati"], m1
assert m1["campo"]["sinistra"] == {"mie": ["Friar Tuck 4/3", None], "avv": ["Bat 2/1", None]}, m1["campo"]
assert m1["rivela_prima"] == "avversario" and m1["avv_mano"] == 4
diario = (c.journal_dir / "diario.md").read_text(encoding="utf-8")
assert "Lettura veloce:" in diario and "update_match:" in diario, diario[-600:]
c._session_free.wait(10)
c.readers = {}

hud = [e for e in ui.of("hud") if e["match"]][-1]["match"]
assert hud["avv"][2] == {"v": 31, "max": 40, "rinf": True} and hud["mie"][1]["max"] == 20, hud

c.scan()
time.sleep(0.5)
assert len(list(screen.SCAN.glob("*.png"))) == 1 and ui.of("flash")

c.flag("mana letto male")
time.sleep(0.3)
diario = (c.journal_dir / "diario.md").read_text(encoding="utf-8")
assert "Apprendimento" in diario and "Dracula tiene Brides" in diario, diario
assert "SEGNALAZIONE" in diario and "mana letto male" in diario and "token generati: 42" in diario, diario
assert len(list(c.journal_dir.glob("*.jpg"))) >= 2

c.toggle_mode()
assert ui.of("state")[-1]["mode"] == "ranked"
c.toggle_mode()

# AUTO spento: le analisi automatiche ancora in coda non partono (niente catture né finestra che lampeggia)
hides0, req0 = ui.hides, c.req_n
c.set_auto(True)
c._q.put(("analyze", True)); c._q.put(("analyze", True))
c.set_auto(False)
time.sleep(0.8)
assert c.req_n == req0 and ui.hides == hides0, "dopo AUTO spento nessuna cattura"
c.auto_on = False
c._do_analyze(True)
assert c.req_n == req0 and ui.hides == hides0, "anche un'analisi automatica già estratta dalla coda si ferma"

# REGISTRA con la finestra visibile: fotogrammi senza nascondere BIG-BOB
screen.grab_masked = lambda title, mask=None, max_width=1024: Image.new("RGB", (320, 180), (20, 90, 20))
c.rec_dir, c.rec_on, c.rec_count = screen.new_recording(), True, 0
ui.vis = True
h0 = ui.hides
c._do_record_frame()
assert ui.hides == h0 and len(list(c.rec_dir.glob("0001_*.jpg"))) == 1, "registrazione senza lampeggio"
c.rec_on = False

# BIG-BOB invisibile alle catture: niente zona nera e l'F8 non nasconde la finestra
from origins import winutil as _wu  # noqa: E402
_wu.exclude_from_capture = lambda title="BIG-BOB", on=True: True
c.apply_capture_exclusion()
assert c.capture_excluded and c._capture_mask() is None, "invisibile: nessuna maschera"
masks = []
screen.grab_masked = lambda title, mask=None, max_width=1024: masks.append(mask) or Image.new("RGB", (320, 180))
_cap = screen.capture
screen.capture = lambda title, folder=None: Path(tmp / "f8.png")
h0 = ui.hides
c.hidden_capture()
c._do_record_frame() if c.rec_on else None
assert ui.hides == h0, "F8 senza far sparire la finestra"
_wu.exclude_from_capture = lambda title="BIG-BOB", on=True: False  # Windows vecchio: si torna alla maschera
c.apply_capture_exclusion()
assert not c.capture_excluded and c._capture_mask() == (0, 0, 10, 10)
c.hidden_capture()
assert ui.hides == h0 + 1, "senza esclusione l'F8 nasconde la finestra come prima"
screen.capture = _cap

c.set_auto(True)
c.set_record(True)
time.sleep(0.4)
assert c.rec_on and c.auto_on
wait(ui, c.end_match, "vittoria")
assert "segnalazioni=si" in ui.of("answer")[-1]["text"], "a fine partita le segnalazioni ✕ diventano lezioni"
assert not c.rec_on and not c.auto_on, "a fine partita si fermano registrazione e analisi automatica"
assert ui.of("answer")[-1]["parsed"] is None, "il riepilogo finale è testo, non una mossa"
assert any(e.get("what") == "Analizzo la partita" for e in ui.of("busy")), "caricamento con la scritta giusta"
assert ui.of("clear"), "la vecchia mossa sparisce"

# nuova partita = nuovo processo e nuova sessione
wait(ui, c.new_match, "Test")
assert c.session.proc.pid != pid1 and c.live_n == 0 and c.flags == []

# processo morto a metà partita: riparte da solo
c.session.proc.kill()
c.session.proc.wait()
time.sleep(0.3)
wait(ui, c.analyze)
assert ui.of("answer")[-1]["parsed"]["mossa"], "dopo un crash deve ripartire"

# osservatore: fotogrammi tra un F8 e l'altro, allegati al successivo (al massimo 6, i più diversi, in ordine)
from PIL import Image as _Im
screen.grab_masked = lambda title, mask=None, max_width=1024: _Im.new("RGB", (320, 180), (90, 20, 20))
c.obs_frames = []
for i in range(14):
    c._observe(None, float(i % 5) + 2.5)
    time.sleep(0.01)
assert len(c.obs_frames) == 14 and all(f["path"].suffix == ".jpg" for f in c.obs_frames)
picked = c._take_obs_frames()
assert 1 <= len(picked) <= 2 and c.obs_frames == [], "la stessa animazione non si allega 14 volte"
# tanti momenti diversi: senza doppioni e, oltre 10, affiancati in fogli numerati (al massimo 10 immagini)
c.obs_frames = []
for i in range(26):
    c._observe(None, 5.0)
c._obs_flush()
with c._obs_lock:
    for i, f in enumerate(c.obs_frames):  # 26 eventi distinti: zone diverse, a 2 s di distanza
        f["t"], f["bbox"] = 1000 + 2 * i, (0.05 * (i % 4), 0.1, 0.05 * (i % 4) + 0.04, 0.2)
picked = c._take_obs_frames()
moments = sum(len(f.get("foglio") or [f]) for f in picked)
assert len(picked) <= 10 and moments == 26 and any(f.get("foglio") for f in picked), (len(picked), moments)
assert all(Path(f["path"]).exists() for f in picked) and picked == sorted(picked, key=lambda f: f["t"])
# una zona cambiata: si salva anche il ritaglio ad alta risoluzione con la sua posizione
from origins import observer as _obs  # noqa: E402
big = _Im.new("RGB", (1600, 900), (30, 20, 60))
a_sig = _obs.signature(big)
big2 = big.copy()
big2.paste((250, 250, 250), (1250, 650, 1450, 850))  # una carta compare in basso a destra
loc, _g, grid = _obs.cell_diff(_obs.signature(big2), a_sig)
assert loc > c.OBS_LOCAL_T, loc
c._observe_img(big2, grid, loc, True)
c._obs_flush()
f = c.obs_frames[-1]
assert f["path"].name.endswith("_zona.jpg") and f["zona"] == "in basso a destra" and f["movimento"], f
assert _Im.open(f["path"]).width < 700, "il ritaglio contiene solo la zona cambiata"
for i in range(2):
    c._observe(None, 3.0)
wait(ui, c.analyze)
diario = (c.journal_dir / "diario.md").read_text(encoding="utf-8")
assert "Osservatore: 3 immagini allegate" in diario and "_zona.jpg" in diario and c.obs_frames == [], \
    "allegati all'F8 (con il ritaglio) e poi azzerati"

# il ciclo dell'osservatore coglie anche un effetto che dura meno di un secondo (senza aspettare lo schermo fermo)
seq = [big] * 4 + [big2] * 2 + [big] * 6   # la carta compare per ~0,7 s e sparisce
it = iter(seq)
screen.grab_fast = lambda title, mask=None: next(it, big)
c.obs_frames, c.last_capture = [], 0
old_active = c._match_active
c._match_active = True
time.sleep(0.3 * (len(seq) + 4))
c._match_active = old_active
c._obs_flush()
zones = [f["zona"] for f in c.obs_frames]
assert any(z == "in basso a destra" for z in zones), f"effetto breve visto: {zones}"
c.obs_frames = []

# cronologia: domanda su una mossa dal libro (sessione a parte, con la schermata)
from origins import history, report  # noqa: E402
report.LOGS = tmp / "logs"
history.LOGS = tmp / "logs"
pid = history.latest_id()
assert pid, "il diario della partita di prova deve comparire nella cronologia"
c.history_session = FakeSession("fake", tmp)
ans = c.history_ask(pid, 0, "Dove l'ho persa?")
assert ans["risposta"].startswith("Risposta libera") and "❓" in ans["risposta"], ans
ans = c.history_ask(pid, 0, "Ti insegno una cosa: contro Dracula tengo Garlic")
assert "seguito=si" in ans["risposta"], "stessa conversazione: solo la domanda nuova"
assert ans["imparato"] == ["Lezione: Contro Dracula tieni Garlic per il centro"], ans
saved = history.load_qa(pid)
assert len(saved) == 2 and saved[1]["imparato"], "la conversazione resta nel diario della partita"
page = report.library_html("partite", match=pid).read_text(encoding="utf-8")
assert "Ti insegno una cosa" in page and "📚 Lezione: Contro Dracula" in page, "e si rivede riaprendo la pagina"
req = next((r for r in history.journals()[0]["richieste"] if r.get("schermata")), None)
if req:
    ans = c.history_ask(pid, req["n"], "Perché questa mossa?")
    assert "img=True" in ans["risposta"] and "seguito" not in ans["risposta"], ans
assert "Non trovo" in c.history_ask("inesistente", 1, "?")["risposta"]
c.history_session.close()

# Claude Code mancante: BIG-BOB lo installa da solo e apre l'accesso
import configura  # noqa: E402
calls = []
configura.install_claude = lambda log=print: calls.append("installa") or "C:/finto/claude.exe"
c.claude_login = lambda: calls.append("login")
c._session_free.wait(60)  # finisce l'apprendimento in background dell'ultimo F8
time.sleep(1)
c._session_free.wait(60)
old_session = c.session
c.claude, c.session = None, None
n = len(ui.events)
c._install_claude()
assert calls == ["installa", "login"] and c.claude == "C:/finto/claude.exe" and c.session is not None
assert any(e.get("call") == "claude_login" for e in ui.events[n:]), "pulsante ACCEDI A CLAUDE"
configura.install_claude = lambda log=print: None
c.claude, c.session = None, None
c._install_claude()
assert c.claude is None and any("installalo a mano" in str(e).lower() for e in ui.events[-3:])
c.session = old_session

c.stop()
shutil.rmtree(tmp, ignore_errors=True)
print("CONTROLLER OK")
