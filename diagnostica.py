"""Diagnosi di BIG-BOB: controlla librerie, finestra del gioco, cattura, tasti F9 e Claude Code.
Lancia diagnostica.bat con il gioco aperto e copia/manda il risultato."""
import importlib
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK, KO = "[OK]", "[!!]"
problemi = []


def riga(stato, testo):
    print(f"{stato} {testo}")
    if stato == KO:
        problemi.append(testo)


print("=== DIAGNOSTICA BIG-BOB ===")
print(f"Python {platform.python_version()} · {platform.platform()}")

# 1. librerie
for mod in ("mss", "PIL", "pygetwindow", "keyboard", "mcp", "webview"):
    try:
        importlib.import_module(mod)
        riga(OK, f"libreria {mod}")
    except Exception as e:  # noqa: BLE001
        riga(KO, f"libreria {mod} mancante ({e}) -> rilancia installa.bat")

# 2. amministratore
admin = False
try:
    import ctypes
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:  # noqa: BLE001
    pass
print(f"[..] Eseguito come amministratore: {'sì' if admin else 'no'}")

# 3. finestre
from origins import screen, store  # noqa: E402

titolo = store.load("config").get("titolo_finestra", "Origins")
print(f"\n--- Finestre aperte (cerco '{titolo}' nel titolo) ---")
try:
    wins = screen.list_windows()
    trovate = [w for w in wins if titolo.lower() in w["titolo"].lower()
               and not any(x in w["titolo"].lower() for x in screen.EXCLUDE)]
    for w in wins:
        segno = ">>" if w in trovate else "  "
        print(f" {segno} {w['titolo'][:70]!r}  {w['w']}x{w['h']}{'  (minimizzata)' if w['minimizzata'] else ''}")
    if trovate:
        riga(OK, "finestra del gioco trovata")
    else:
        riga(KO, f"nessuna finestra con '{titolo}' nel titolo: scrivi il titolo esatto del gioco "
                 "in config.json alla voce titolo_finestra")
except Exception as e:  # noqa: BLE001
    riga(KO, f"elenco finestre fallito: {e}")

# 4. cattura
print("\n--- Cattura ---")
try:
    p = screen.capture(titolo, ROOT / "captures", prefix="diagnostica-")
    from PIL import Image, ImageStat
    img = Image.open(p)
    luminosita = ImageStat.Stat(img.convert("L")).mean[0]
    riga(OK, f"cattura salvata: {p}  ({img.width}x{img.height}) da {screen.last_source}")
    if luminosita < 3:
        riga(KO, "la cattura è nera: imposta il gioco in finestra senza bordi (borderless), "
                 "non schermo intero esclusivo")
    print("     Apri quel file e controlla che si veda il gioco.")
except Exception as e:  # noqa: BLE001
    riga(KO, f"cattura fallita: {e}")

# 5. tasto F9
print("\n--- Tasti globali ---")
try:
    import keyboard
    preso = threading.Event()
    keyboard.add_hotkey("f9", preso.set)
    print("     CLICCA DENTRO LA FINESTRA DEL GIOCO e premi F9 entro 20 secondi...")
    preso.wait(20)
    keyboard.unhook_all_hotkeys()
    if preso.is_set():
        riga(OK, "F9 ricevuto anche con il gioco in primo piano")
    else:
        riga(KO, "F9 NON ricevuto dentro il gioco" + ("" if admin else
                 " -> riprova con tasto destro su diagnostica.bat > Esegui come amministratore"))
except Exception as e:  # noqa: BLE001
    riga(KO, f"tasti globali non disponibili: {e}")

# 6. Claude Code
print("\n--- Claude Code ---")
cl = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
riga(OK if cl else KO, f"comando claude: {cl or 'non trovato nel PATH'}")
riga(OK if (ROOT / ".mcp.json").exists() else KO,
     ".mcp.json presente" if (ROOT / ".mcp.json").exists() else ".mcp.json mancante -> rilancia installa.bat")

print("\n=== RISULTATO ===")
if problemi:
    print("Problemi trovati:")
    for x in problemi:
        print(" -", x)
else:
    print("Tutto a posto.")
time.sleep(0.2)
