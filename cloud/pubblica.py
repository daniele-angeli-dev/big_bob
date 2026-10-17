"""Pubblica (o aggiorna) il cervello comune sul TUO account Cloudflare. Si lancia con pubblica_cervello.bat.

Cosa fa, in ordine (si può rilanciare quando vuoi: rifà solo ciò che serve):
  1. controlla Node.js (serve per lo strumento di Cloudflare, "wrangler") e installa wrangler in cloud/;
  2. ti fa accedere a Cloudflare dal browser (solo la prima volta);
  3. crea il database "bigbob-cervello" (D1) se non c'è e ci crea le tabelle;
  4. genera la chiave di amministrazione e il "sale" degli hash (restano in config.json, sul tuo PC);
  5. pubblica il Worker e scrive l'indirizzo in config.json, così il tuo BIG-BOB è subito collegato.

Piano gratuito di Cloudflare: 100.000 richieste al giorno e 5 GB di database, molto più di quanto serve.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CLOUD = Path(__file__).resolve().parent
ROOT = CLOUD.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

DB_NAME = "bigbob-cervello"
WIN = os.name == "nt"


def step(n, text):
    print(f"\n[{n}/5] {text}")


def die(text):
    print("\n  ✗ " + text)
    input("\nPremi Invio per chiudere…")
    sys.exit(1)


def tool(name):
    return shutil.which(name + ".cmd") if WIN and shutil.which(name + ".cmd") else shutil.which(name)


def run(args, capture=True, input_text=None, check=True):
    """Esegue un comando in cloud/. Con capture=False l'utente vede e risponde direttamente (login, domande)."""
    if capture:
        p = subprocess.run(args, cwd=CLOUD, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           input=input_text)
        if check and p.returncode != 0:
            die(f"Comando non riuscito: {' '.join(args[1:4])}…\n{(p.stderr or p.stdout)[-1500:]}")
        return p
    p = subprocess.run(args, cwd=CLOUD)
    if check and p.returncode != 0:
        die(f"Comando non riuscito: {' '.join(args[1:4])}…")
    return p


def json_in(text, kind="["):
    """Il primo JSON valido nell'output (wrangler a volte stampa avvisi come "▲ [WARNING]" prima)."""
    dec = json.JSONDecoder()
    i = text.find(kind)
    while i != -1:
        try:
            return dec.raw_decode(text[i:])[0]
        except ValueError:
            i = text.find(kind, i + 1)
    raise ValueError("nessun JSON")


def wrangler(*args, **kw):
    return run([NODE, str(CLOUD / "node_modules" / "wrangler" / "bin" / "wrangler.js"), *args], **kw)


# ----------------------------------------------------------------------------------------------- 1. Node e wrangler
step(1, "Node.js e lo strumento di Cloudflare")
NODE, NPM = shutil.which("node"), tool("npm")
if not NODE or not NPM:
    print("  Node.js non è installato: serve solo per pubblicare il server (BIG-BOB non lo usa).")
    winget = shutil.which("winget")
    if WIN and winget and input("  Lo installo adesso con winget? [S/n] ").strip().lower() in ("", "s", "si", "sì", "y"):
        subprocess.run([winget, "install", "-e", "--id", "OpenJS.NodeJS.LTS", "--accept-source-agreements",
                        "--accept-package-agreements"])
        die("Node.js installato. Chiudi questa finestra e rilancia pubblica_cervello.bat (serve una finestra nuova).")
    die("Installa Node.js LTS da https://nodejs.org e rilancia pubblica_cervello.bat.")
print("  Node.js", run([NODE, "--version"]).stdout.strip())
if not (CLOUD / "node_modules" / "wrangler").exists():
    print("  Installo wrangler (una volta sola, un minuto)…")
    run([NPM, "install", "--no-audit", "--no-fund"], capture=False)
print("  wrangler", wrangler("--version").stdout.strip().splitlines()[-1])

# ----------------------------------------------------------------------------------------------- 2. accesso
step(2, "Accesso a Cloudflare")
who = wrangler("whoami", "--json", check=False)
if who.returncode != 0:
    print("  Si apre il browser: accedi (o crea un account gratuito) e premi Allow.")
    wrangler("login", capture=False)
    who = wrangler("whoami", "--json", check=False)
    if who.returncode != 0:
        die("Accesso non riuscito. Rilancia lo script e completa l'accesso nel browser.")
try:
    me = json_in(who.stdout, "{")
    print("  Collegato come", me.get("email") or "(account Cloudflare)")
except Exception:  # noqa: BLE001
    print("  Collegato.")

# ----------------------------------------------------------------------------------------------- 3. database
step(3, "Database")


def find_db():
    out = wrangler("d1", "list", "--json").stdout
    try:
        dbs = json_in(out, "[")
    except ValueError:
        die("Non riesco a leggere l'elenco dei database:\n" + out[-800:])
    return next((d for d in dbs if d.get("name") == DB_NAME), None)


db = find_db()
if db is None:
    print(f"  Creo il database {DB_NAME}…")
    wrangler("d1", "create", DB_NAME)
    db = find_db()
    if db is None:
        die("Il database non risulta creato.")
db_id = db.get("uuid") or db.get("id") or db.get("database_id")
print("  Database", DB_NAME, db_id)
toml = (CLOUD / "wrangler.example.toml").read_text(encoding="utf-8").replace("__DATABASE_ID__", db_id)
(CLOUD / "wrangler.toml").write_text(toml, encoding="utf-8")
print("  Creo/aggiorno le tabelle…")
wrangler("d1", "execute", DB_NAME, "--remote", "--file", "schema.sql", "--yes")

# ----------------------------------------------------------------------------------------------- 4. segreti
step(4, "Chiavi")
cfg = store.load("config")
new_keys = False
if not cfg.get("cervello_admin_key"):
    cfg["cervello_admin_key"] = secrets.token_urlsafe(32)
    new_keys = True
if not cfg.get("cervello_sale"):  # non cambiarlo mai: cambierebbe il codice anonimo di tutti i giocatori
    cfg["cervello_sale"] = secrets.token_urlsafe(24)
    new_keys = True
store.save("config", cfg)
print("  Chiave di amministrazione e sale " + ("generati" if new_keys else "già presenti") +
      " (salvati solo in config.json, sul tuo PC)")

# ----------------------------------------------------------------------------------------------- 5. pubblicazione
step(5, "Pubblicazione")
fd, secrets_path = tempfile.mkstemp(suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump({"ADMIN_KEY": cfg["cervello_admin_key"], "SALE": cfg["cervello_sale"]}, f)
try:
    p = wrangler("deploy", "--secrets-file", secrets_path, check=False)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and "workers.dev" in out and "subdomain" in out.lower():
        print("  Cloudflare chiede di scegliere il tuo sottodominio workers.dev (es. il tuo nome): rispondi qui sotto.")
        p = run([NODE, str(CLOUD / "node_modules" / "wrangler" / "bin" / "wrangler.js"), "deploy", "--secrets-file",
                 secrets_path], capture=False, check=False)
        out = ""
    if p.returncode != 0:
        die("Pubblicazione non riuscita:\n" + out[-1500:])
finally:
    os.unlink(secrets_path)
m = re.search(r"https://[\w.-]+\.workers\.dev", out)
url = m.group(0) if m else ""
if not url:
    url = input("  Incolla l'indirizzo https://….workers.dev mostrato sopra: ").strip().rstrip("/")
print("  Pubblicato:", url)

ok = False
for _ in range(10):
    try:
        with urllib.request.urlopen(url + "/v1/stato", timeout=15) as r:
            ok = json.loads(r.read()).get("ok") is True
            break
    except Exception:  # noqa: BLE001
        time.sleep(3)
print("  Prova del server:", "risponde ✓" if ok else "non risponde ancora (può servire un minuto)")

cfg = store.load("config")
cfg["cervello_url"] = url
cfg["cervello_regole_base"] = True  # le regole di base vengono dalla tua intervista: le confermi tu
store.save("config", cfg)
(CLOUD / "indirizzo.txt").write_text(url + "\n", encoding="utf-8")

print("\n" + "=" * 70)
print("  FATTO. Il tuo BIG-BOB è già collegato al cervello comune.")
print("  Perché lo usino anche i tuoi amici, manda a Claude questo indirizzo:")
print("\n      " + url + "\n")
print("  verrà scritto nel programma e arriverà a tutti con il prossimo aggiornamento.")
print("=" * 70)
input("\nPremi Invio per chiudere…")
