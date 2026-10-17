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
assert c.session.proc.pid == pid1, "il processo Claude deve restare acceso tra un F8 e l'altro"
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
assert len(list(c.journal_dir.glob("*.png"))) >= 2

c.toggle_mode()
assert ui.of("state")[-1]["mode"] == "ranked"
c.toggle_mode()

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
for i in range(9):
    c._observe(None, float(i % 5) + 2.5)
    time.sleep(0.01)
assert len(c.obs_frames) == 9 and all(f["path"].suffix == ".jpg" for f in c.obs_frames)
picked = c._take_obs_frames()
assert len(picked) == 6 and picked == sorted(picked, key=lambda p: p.name) and c.obs_frames == []
for i in range(3):
    c._observe(None, 3.0)
wait(ui, c.analyze)
diario = (c.journal_dir / "diario.md").read_text(encoding="utf-8")
assert "Osservatore: 3 fotogrammi allegati" in diario and c.obs_frames == [], "allegati all'F8 e poi azzerati"

# cronologia: domanda su una mossa dal libro (sessione a parte, con la schermata)
from origins import history  # noqa: E402
history.LOGS = tmp / "logs"
pid = history.latest_id()
assert pid, "il diario della partita di prova deve comparire nella cronologia"
c.history_session = FakeSession("fake", tmp)
ans = c.history_ask(pid, 0, "Dove l'ho persa?")
assert ans.startswith("Risposta libera"), ans
req = next((r for r in history.journals()[0]["richieste"] if r.get("schermata")), None)
if req:
    ans = c.history_ask(pid, req["n"], "Perché questa mossa?")
    assert "img=True" in ans, ans
assert "Non trovo" in c.history_ask("inesistente", 1, "?")
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
