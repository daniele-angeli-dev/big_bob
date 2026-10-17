"""Cronologia delle partite (libro → PARTITE): python tests/test_history.py (dati temporanei, niente rete)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["BIGBOB_NO_SYNC"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import history, report  # noqa: E402

history.LOGS = tmp / "logs"
report.LOGS = tmp / "logs"
FAILED = []


def check(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        FAILED.append(msg)


# un diario come quello scritto dalla finestra, con due richieste e le schermate
d = history.journals_dir() / "20261017-201500"
(d / "osservatore").mkdir(parents=True)
for n in (1, 2, 3):
    Image.new("RGB", (64, 36), (40 * n, 20, 90)).save(d / f"0{n}.png")
Image.new("RGB", (64, 36), "red").save(d / "osservatore" / "obs-001.jpg")
(d / "diario.md").write_text("""# Partita del 17/10/2026 20:15
Mazzo: Sherwood
Modalità: allenamento · modello: sonnet

## #1 · 20:15:10 · Nuova partita · Sherwood · schermata 01.png

Strumenti: start_match
Tempo totale: 4.2s · token generati: 80

Pronto.

## #2 · 20:16:40 · AUTO · schermata 02.png

Osservatore: 1 fotogrammi allegati (obs-001.jpg)

Strumenti: 0.5s update_match
Tempo totale: 9.1s · token generati: 120

▶ Little John a destra, Marian al centro
perché: chiudi la destra, proteggi il centro
⚠ Brides of Dracula 41%

### 📚 Imparato tra un round e l'altro
L001 nuova

## #3 · 20:18:05 · AUTO · schermata 03.png

Strumenti: update_match
Tempo totale: 8.0s · token generati: 90

▶ Friar Tuck a sinistra
perché: copri la sinistra scoperta

### ❌ SEGNALAZIONE dopo richiesta #3 (20:18:30)
mossa sbagliata
""", encoding="utf-8")
store.save("matches", [{
    "inizio": "2026-10-17 20:15", "fine": "2026-10-17 20:22", "mio_mazzo": "Sherwood", "leggendaria_mia": "Robin Hood",
    "carte_mie": ["Little John", "Marian", "Friar Tuck"], "avv_leggendaria": "Dracula", "risultato": "vittoria",
    "turno": 3, "tipo_avversario": "Aggro", "miei_giocati": ["Little John", "Marian", "Marian"],
    "avv_giocati": ["Bat", "Garlic", "Bat"], "avv_scartati": [],
    "storico": [
        {"ora": "20:16:45", "turno": 1, "miei_giocati": [], "avv_giocati": [], "barrier_mie": [20, 20, 20]},
        {"ora": "20:18:10", "turno": 2, "miei_giocati": ["Little John", "Marian"], "avv_giocati": ["Bat", "Garlic"],
         "barrier_mie": [20, 18, 20], "barrier_avv": [20, 20, 14]},
    ]}])

print("1. diario e collegamento")
js = history.journals()
check(len(js) == 1 and len(js[0]["richieste"]) == 3, "diario letto: 3 richieste")
check(js[0]["richieste"][1]["osservatore"] == ["obs-001.jpg"] and js[0]["segnalazioni"] and js[0]["lezioni"],
      "fotogrammi dell'osservatore, segnalazioni e lezioni")
pairs = history.link(store.load("matches"), js)
check(len(pairs) == 1 and pairs[0][0] and pairs[0][1], "partita collegata al diario dall'orario e dal mazzo")

print("2. round per round")
rs = history.rounds(*pairs[0])
r2, r3 = rs[1], rs[2]
check(r2["mossa"] == "Little John a destra, Marian al centro" and r2["perche"].startswith("chiudi"), "mossa suggerita")
check(r2["giocate"] == ["Little John", "Marian"] and r2["avv_giocate"] == ["Bat", "Garlic"],
      f"carte giocate dopo il consiglio: {r2['giocate']} / {r2['avv_giocate']}")
check(r2["seguito"] == "sì", "consiglio seguito")
check(r3["giocate"] == ["Marian"] and r3["seguito"] == "no", f"ultima richiesta confrontata con la fine: {r3['giocate']}")

print("2b. due consigli nello stesso round, mulligan e carte fuori tracciamento")
mm = {"carte_mie": ["Little John", "Marian", "Robin"], "leggendaria_mia": "Robin Hood", "turno": 3,
      "miei_giocati": ["Marian", "Robin Hood"],
      "storico": [{"ora": "10:00:05", "turno": 0, "miei_giocati": []},
                  {"ora": "10:01:05", "turno": 1, "miei_giocati": []},
                  {"ora": "10:01:40", "turno": 1, "miei_giocati": []},
                  {"ora": "10:02:30", "turno": 2, "miei_giocati": ["Marian"]},
                  {"ora": "10:03:30", "turno": 3, "miei_giocati": ["Marian", "Robin Hood"]}]}
jj = {"richieste": [{"ora": "10:00:00", "risposta": "▶ Tieni Marian, Little John · cambia Robin"},
                    {"ora": "10:01:00", "risposta": "▶ Little John al centro"},
                    {"ora": "10:01:35", "risposta": "▶ Marian al centro\nperché: meglio"},
                    {"ora": "10:02:25", "risposta": "▶ Robin Hood a destra"}]}
rr = history.rounds(mm, jj)
check(rr[0]["seguito"] is None, "il mulligan non è un consiglio di giocata")
check(rr[1]["seguito"] is None and rr[1].get("superato") and rr[2]["seguito"] == "sì",
      f"due consigli nello stesso round: conta l'ultimo ({[r['seguito'] for r in rr]})")
check(rr[3]["seguito"] == "sì", "Robin Hood non fa scattare anche Robin")
check([r for r in rr if r["seguito"] and r.get("conta")] == [rr[2], rr[3]], "nel conto: un consiglio per round")

print("3. pagina")
path = report.library_html("partite", match="20261017-201500")
page = path.read_text(encoding="utf-8")
check("data-tab='partite'" in page and "data-match='20261017-201500'" in page, "si apre sulla partita")
check("CONSIGLIO SEGUITO" in page and "GIOCATA DIVERSA" in page and "Little John a destra" in page, "badge e mosse")
check("data-shot='partite/20261017-201500/02.png'" in page and " src='partite" not in page,
      "schermate caricate su richiesta (non incorporate tutte nella pagina)")
check(page.count("form class='ask'") == 4, "una domanda per ogni richiesta + una per la partita")
img = history.image_data("partite/20261017-201500/02.png")
check(img and img.startswith("data:image/jpeg;base64,"), "schermata come immagine per la finestra")
check(history.image_data("../config.json") is None and history.image_data("partite/../../x.png") is None,
      "niente file fuori dal diario")

print("4. domande")
ctx, shot = history.question_context("20261017-201500", 2)
check("RICHIESTA #2" in ctx and "Little John a destra" in ctx and "giocato: Little John, Marian" in ctx
      and shot and shot.name == "02.png", "contesto e schermata della richiesta")
ctx0, shot0 = history.question_context("20261017-201500", 0)
check("Cronologia" in ctx0 and shot0 is None, "domanda sull'intera partita")
empty = history.body()
check("mtile" in empty, "elenco partite")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFALLITI:", len(FAILED))
sys.exit(1 if FAILED else 0)
