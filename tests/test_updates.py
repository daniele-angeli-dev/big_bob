"""Test di aggiornamenti, impostazioni e collegamento a Claude: python tests/test_updates.py
Usa repository Git temporanei: non tocca la tua installazione né GitHub."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not shutil.which("git"):
    print("AGGIORNAMENTI: git non installato, test saltato")
    sys.exit(0)

from origins import store, updates  # noqa: E402

tmp = Path(tempfile.mkdtemp())


def g(cwd, *a):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *a],
                       cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()


# "GitHub" finto con tre versioni
remote = tmp / "remote.git"
g(tmp, "init", "-q", "--bare", str(remote))
dev = tmp / "dev"
dev.mkdir()
g(dev, "init", "-q")
(dev / "app.py").write_text("v1")
(dev / "requirements.txt").write_text("a\n")
(dev / ".gitignore").write_text("data/\nconfig.json\nlogs/\n")
g(dev, "add", "-A")
g(dev, "commit", "-qm", "versione 1")
v1 = g(dev, "rev-parse", "HEAD")
(dev / "app.py").write_text("v2")
g(dev, "commit", "-qam", "Simulatore più veloce")
(dev / "requirements.txt").write_text("a\nb\n")
g(dev, "commit", "-qam", "Nuova libreria")
g(dev, "remote", "add", "origin", str(remote))
g(dev, "push", "-q", "origin", "HEAD:main")

# installazione fatta con l'installer: file della v1, nessun .git, VERSION scritto dall'installer
inst = tmp / "inst"
inst.mkdir()
(inst / "app.py").write_text("v1")
(inst / "requirements.txt").write_text("a\n")
(inst / "VERSION").write_text(v1 + "\n")
(inst / "data").mkdir()
(inst / "data" / "cards.json").write_text("[\"le mie carte\"]")
(inst / "config.json").write_text("{\"modello_live\": \"opus\"}")

updates.ROOT = inst
updates.REMOTE = str(remote)
updates.RESULT = inst / "logs" / "aggiornamento.json"

r = updates.check()
assert r["errore"] is None, r
assert r["disponibile"] and r["novita"] == ["Nuova libreria", "Simulatore più veloce"], r
assert (inst / "app.py").read_text() == "v1", "il controllo non deve cambiare i file"

import updater  # noqa: E402

updater.ROOT = inst
updater.LOG = inst / "logs" / "aggiornamento.log"
pip_calls = []
updater.run = lambda cmd, timeout=600: pip_calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
res = updater.update()
assert res["ok"], res
assert (inst / "app.py").read_text() == "v2" and (inst / "requirements.txt").read_text() == "a\nb\n"
assert any("pip" in c for cmd in pip_calls for c in cmd), "requirements cambiati: pip deve partire"
assert (inst / "data" / "cards.json").read_text() == "[\"le mie carte\"]", "i dati non si toccano"
assert json.loads((inst / "config.json").read_text())["modello_live"] == "opus", "la config non si tocca"
assert updates.check()["disponibile"] is False

# senza novità nei requirements pip non riparte
(dev / "app.py").write_text("v3")
g(dev, "commit", "-qam", "Solo codice")
g(dev, "push", "-q", "origin", "HEAD:main")
pip_calls.clear()
assert updater.update()["ok"] and not any("pip" in c for cmd in pip_calls for c in cmd)

# esito letto una sola volta all'avvio
updates.RESULT.parent.mkdir(exist_ok=True)
updates.RESULT.write_text(json.dumps({"ok": True, "da": "a", "a": "b"}))
assert updates.last_result()["ok"] and updates.last_result() is None

# accesso a GitHub mancante -> messaggio chiaro, nessuna richiesta di password
bad = tmp / "bad"
bad.mkdir()
updates.ROOT = bad
updates.REMOTE = "https://127.0.0.1:9/nessuno/repo.git"
r = updates.check()
assert r["errore"] and not r["disponibile"], r

# ---------------- impostazioni e collegamento
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp
import configura  # noqa: E402

cfg = configura.apply("haiku", "api", "sk-ant-segreta-1234")
assert cfg["modello_live"] == "haiku" and cfg["connessione"] == "api"
assert "segreta" not in json.dumps(configura.public(cfg))
try:
    configura.apply("gpt")
    raise AssertionError("modello non valido accettato")
except ValueError:
    pass

import controller  # noqa: E402

s = controller.ClaudeSession("claude", tmp)
os.environ["ANTHROPIC_API_KEY"] = "chiave-di-sistema"
assert s._env()["ANTHROPIC_API_KEY"] == "sk-ant-segreta-1234"
configura.apply(connessione="abbonamento")
assert "ANTHROPIC_API_KEY" not in s._env(), "con l'abbonamento una chiave di sistema non deve essere usata"
assert "--model" in s._cmd() and s._cmd()[s._cmd().index("--model") + 1] == "haiku"


class UI:
    def __init__(self):
        self.ev = []

    def emit(self, e):
        self.ev.append(e)

    def hide(self): pass
    def show(self): pass
    def is_visible(self): return True
    def rect(self): return None


ui = UI()
c = controller.Controller(ui)
c.save_settings({"modello_live": "sonnet", "connessione": "abbonamento", "voce": False, "max_thinking_live": "3000"})
cfg = store.load("config")
assert cfg["modello_live"] == "sonnet" and cfg["voce"] is False and cfg["max_thinking_live"] == 3000
assert cfg["api_key"] == "sk-ant-segreta-1234", "salvare senza chiave non deve cancellarla"
c.get_settings()
st = [e for e in ui.ev if e["type"] == "settings"][-1]
assert st["valori"]["api_key_impostata"] is True and "api_key" not in st["valori"]

shutil.rmtree(tmp, ignore_errors=True)
print("AGGIORNAMENTI OK")
