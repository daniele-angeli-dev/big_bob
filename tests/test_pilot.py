"""Pilota automatico: python tests/test_pilot.py (niente mouse vero: fuori da Windows le azioni non muovono nulla)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["BIGBOB_NO_SYNC"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import pilot  # noqa: E402

FAILED = []


def check(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        FAILED.append(msg)


print("1. lettura delle azioni")
a = pilot.parse("▶ Marian al centro\nperché: blocca\n🤖 trascina 31.5,88 > 42,55.5 ; clicca 91,92.5")
check(a == [{"tipo": "trascina", "da": (31.5, 88.0), "a": (42.0, 55.5)}, {"tipo": "clicca", "a": (91.0, 92.5)}], f"{a}")
check(pilot.parse("▶ passa\n🤖 niente") == [], "niente = nessuna azione")
check(pilot.parse("▶ Marian al centro") is None, "senza riga 🤖")
check(pilot.parse("🤖 trascina (10,5 / 20) → (30, 40) ; premi 120,50")[0]["da"] == (10.5, 20.0), "formati diversi")
check(pilot.parse("🤖 clicca 150,30")[0]["a"] == (100.0, 30.0), "valori fuori scala ridotti a 0-100")
check(len(pilot.parse("🤖 " + " ; ".join(["clicca 1,1"] * 30))) == pilot.MAX_AZIONI, "al massimo MAX_AZIONI")

print("2. coordinate")
reg = (100, 50, 1921, 1081)
check(pilot.to_screen((0, 0), reg) == (100, 50) and pilot.to_screen((100, 100), reg) == (2020, 1130), "angoli")
check(pilot.to_screen((50, 50), reg) == (1060, 590), "centro")
check(pilot.overlaps([(1500, 300)], (1400, 20, 460, 980)) and not pilot.overlaps([(200, 300)], (1400, 20, 460, 980)),
      "punti sopra la finestra di BIG-BOB")

print("3. esecuzione")


class FakeMouse(pilot.Mouse):
    def __init__(self, moved_after=None, stop=lambda: False):
        super().__init__(stop)
        self.log, self.n, self.moved_after = [], 0, moved_after

    def pos(self):
        self.n += 1
        if self.moved_after is not None and self.n > self.moved_after and self.last:
            return (self.last[0] + 200, self.last[1])  # Daniele sposta il mouse
        return self.last

    def button(self, down):
        self.log.append(("giù" if down else "su", self.last))


m = FakeMouse()
done = pilot.run(pilot.parse("🤖 trascina 10,90 > 50,50 ; clicca 95,95"), reg, m, pause=0)
check(len(done) == 2 and m.log[0] == ("giù", pilot.to_screen((10, 90), reg))
      and m.log[1] == ("su", pilot.to_screen((50, 50), reg)) and m.log[-1][0] == "su", f"trascina e clicca: {m.log}")
m = FakeMouse(moved_after=4)
try:
    pilot.run(pilot.parse("🤖 trascina 10,90 > 50,50 ; clicca 95,95"), reg, m, pause=0)
    check(False, "doveva fermarsi")
except pilot.Interrotto as e:
    check("mouse" in str(e) and m.log[-1][0] == "su", f"si ferma se muovi il mouse, senza lasciare il tasto premuto: {e}")
stop = {"v": False}
m = FakeMouse(stop=lambda: stop["v"])
stop["v"] = True
try:
    pilot.run(pilot.parse("🤖 clicca 50,50"), reg, m, pause=0)
    check(False, "doveva fermarsi con F12")
except pilot.Interrotto:
    check(True, "F12 lo ferma")

print("4. nel controller")
import controller  # noqa: E402


class UI:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)

    def is_visible(self):
        return True

    def rect(self):
        return (0, 0, 10, 10)

    def hide(self):
        pass

    def show(self):
        pass


from origins import spazio  # noqa: E402
spazio.LOGS, spazio.CAPTURES = tmp / "logs", tmp
controller.ROOT = tmp
ui = UI()
c = controller.Controller.__new__(controller.Controller)  # senza avviare Claude: servono solo i metodi del pilota
c.ui, c.busy, c.auto_on, c.pilot_on, c._pilot_stop, c._pilot_rounds = ui, True, False, False, False, {}
c._q = controller.queue.Queue()
c.journal_dir, c.rec_on, c.voice = None, False, type("V", (), {"available": lambda s: False})()
c.emit, c.say, c.status = ui.emit, (lambda t, r="bob": ui.events.append({"type": "say", "text": t})), (lambda t: None)
c.emit_state = lambda: None
cfg = store.load("config")
cfg["modalita"] = "ranked"
store.save("config", cfg)
c.set_pilot(True)
check(not c.pilot_on and any("ranked" in e.get("text", "") for e in ui.events), "in ranked non si accende")
cfg["modalita"] = "allenamento"
store.save("config", cfg)
c.set_pilot(True)
check(c.pilot_on and c.auto_on and any("termini di servizio" in e.get("text", "") for e in ui.events),
      "in allenamento si accende con AUTO e avvisa una volta dei rischi")
runs = []
c._pilot_exec = lambda actions, region: runs.append(actions)
c._shot_region = reg
store.save("match", {"turno": 4})
controller.threading.Thread = lambda target, args=(), **k: type("T", (), {"start": lambda s: target(*args)})()
for _ in range(3):
    c._pilot_after("▶ x\n🤖 clicca 50,50")
check(len(runs) == pilot.MAX_PER_ROUND, f"al massimo {pilot.MAX_PER_ROUND} giocate per round: {len(runs)}")
c.set_auto(False)
check(not c.pilot_on, "spegnere AUTO spegne il pilota")
c.pilot_on = True
c.toggle_mode()  # allenamento → ranked
check(not c.pilot_on, "passare a ranked spegne il pilota")
asked = []
c._ask = lambda prompt, **k: asked.append(prompt)
c._take_obs_frames = lambda: []
cfg = store.load("config")
cfg["modalita"] = "allenamento"
store.save("config", cfg)
c.pilot_on, c.auto_on = True, True
c._do_analyze(True)
check("[F8" in asked[-1] and "[AUTO" not in asked[-1] and "PILOTA AUTOMATICO ATTIVO" in asked[-1],
      "con il pilota anche l'analisi automatica è completa (niente risposta '—' a schermata ferma)")
c.pilot_on = False
c._do_analyze(True)
check("[AUTO" in asked[-1] and "PILOTA" not in asked[-1], "senza pilota resta il prompt AUTO")
check(pilot.selftest((0, 0, 100, 100))["ok"], "prova del mouse (fuori da Windows non fa nulla)")
p = controller.parse_live("▶ Marian al centro\n🤖 trascina 1,2 > 3,4")
check(p["mossa"] == "Marian al centro" and not any("🤖" in x or "trascina" in x for x in p["altro"]),
      "la riga 🤖 non finisce nella card")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFALLITI:", len(FAILED))
sys.exit(1 if FAILED else 0)
