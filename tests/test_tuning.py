"""Proposte di effetti, taratura dei pesi e calibrazione della barra: python tests/test_tuning.py (dati temporanei)."""
import os
import random
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

from origins import combat, evaluate, proposals, search, tuning  # noqa: E402

store.upsert("cards", [{"nome": "Vampire Bat", "costo": 2, "attacco": 2, "vita": 1, "tipo": "creatura",
                        "testo": "On Reveal: gain +1/+1"}])

# --- proposte di effetti
r = proposals.propose("vampire bat", [{"tipo": "danno_barrier", "valore": 2}], "R3: barrier prevista 18, reale 16")
assert r["id"] == "E001" and "2 di danno alla barrier" in r["effetto"], r
assert proposals.propose("Vampire Bat", [{"tipo": "danno_barrier", "valore": 2}])["volte"] == 2
assert "errore" in proposals.propose("Vampire Bat", [{"tipo": "vola", "valore": 2}])
assert "errore" in proposals.propose("Carta inesistente", [{"tipo": "potenzia", "valore": 1}])
assert combat.effects(store.find("cards", "Vampire Bat")) == [{"tipo": "potenzia", "valore": 1, "vita": 1}]
assert len(proposals.pending()) == 1
d = proposals.decide("E001", True)
assert d["stato"] == "confermata"
fx = combat.effects(store.find("cards", "Vampire Bat"))
assert {"tipo": "potenzia", "valore": 1, "vita": 1} in fx and {"tipo": "danno_barrier", "valore": 2} in fx, fx
assert "confermato da Daniele" in store.find("cards", "Vampire Bat")["note"]
assert "errore" in proposals.decide("E001", False)  # già decisa
r2 = proposals.propose("Vampire Bat", [{"tipo": "danno_fronte", "valore": 1}])
assert proposals.decide(r2["id"], False)["stato"] == "scartata"
assert not proposals.pending()
print("proposte di effetti ok")

# --- taratura: senza dati restano i pesi di partenza
assert tuning.weights() == tuning.DEFAULT
assert tuning.calibrate(70) == 70
rng = random.Random(3)
for g in range(30):
    won = g % 2 == 0
    for t in range(1, 6):
        # chi vince ha le barrier avversarie più basse e un campo migliore
        bo = [max(1, 20 - t * (4 if won else 1) - rng.randint(0, 3)) for _ in range(3)]
        bm = [max(1, 20 - t * (1 if won else 4) - rng.randint(0, 3)) for _ in range(3)]
        m = {"id": f"g{g}", "turno": t, "barrier_avv": bo, "barrier_mie": bm,
             "distrutte_da_me": 0, "distrutte_a_me": 0}
        tuning.record_round(m)
    res = tuning.record_result({"id": f"g{g}"}, won)
w = tuning.weights()
assert res["pesi"] and res["pesi"]["partite"] == 30, res
assert w["chiusura"] == tuning.DEFAULT["chiusura"]  # scala ancorata alla chiusura
assert all(v >= 0 for v in w.values()), w
assert res["calibrazione"], res
# la stima rapida è troppo prudente su questi dati: la calibrazione la allarga
assert tuning.calibrate(80) > 80 and tuning.calibrate(20) < 20, (tuning.calibrate(80), tuning.calibrate(20))
h = evaluate.heuristic({"barrier_avv": [5, 5, 5], "barrier_mie": [18, 18, 18]})
assert h["fonte"] == "stima rapida calibrata", h
assert evaluate.heuristic({"barrier_avv": [5, 5, 5], "barrier_mie": [18, 18, 18]}, raw=True)["fonte"] == "stima rapida"
search._W["w"] = None
assert search._weights() == w
rep = tuning.report()
assert rep["fasce"] and rep["calibrazione"]
print("taratura e calibrazione ok")

# --- ricerca: giocata forzata e cache delle posizioni
store.upsert("cards", [{"nome": "Ariete", "costo": 3, "attacco": 5, "vita": 3, "tipo": "creatura"},
                       {"nome": "Topo", "costo": 1, "attacco": 1, "vita": 1, "tipo": "creatura"},
                       {"nome": "Orso", "costo": 3, "attacco": 3, "vita": 5, "tipo": "creatura"}])
empty = {k: {"mie": [None, None], "avv": [None, None]} for k in ("sinistra", "centro", "destra")}
s1 = {"turno": 1, "mana": 3, "mia_mano": ["Ariete", "Topo"], "campo": empty, "barrier_mie": [20, 20, 20],
      "barrier_avv": [20, 4, 20], "distrutte_da_me": 0, "distrutte_a_me": 0, "miei_giocati": []}
assert w["distrutta_da_te"] == tuning.DEFAULT["distrutta_da_te"], "senza barrier distrutte nei dati il peso non cambia"
r = search.search(s1, [], 0)
assert any(g["carta"] == "Ariete" and g["corsia"] == "centro" for g in r["mosse"][0]["giocate"]), r["mosse"][0]
assert search.search(s1, [{"carta": "Orso", "p_mano": 0.7}], 0.7)["cache"]["riusate"] > 0
f = search.search(s1, [], 0, forced=[("Topo", 0, 0)])
assert f["mosse"][0]["giocate"] == [{"carta": "Topo", "corsia": "sinistra", "slot": 1}]
assert f["mosse"][0]["punteggio"] < r["mosse"][0]["punteggio"] and not f["dominante"]
print("ricerca forzata e cache ok")

# --- analisi della partita (revisione come i motori di scacchi) ed esercizi
from origins import report, review  # noqa: E402
b2 = {k: {"mie": [None, None], "avv": [None, None]} for k in ("sinistra", "centro", "destra")}
b2["sinistra"]["mie"] = ["Topo 1/1", None]
s2 = {**s1, "turno": 2, "mana": 4, "mia_mano": ["Ariete"], "campo": b2, "barrier_avv": [19, 4, 20], "miei_giocati": ["Topo"]}
b3 = {k: {"mie": list(v["mie"]), "avv": [None, None]} for k, v in b2.items()}
b3["centro"]["mie"] = ["Ariete 5/3", None]
s3 = {**s2, "turno": 3, "mana": 5, "mia_mano": [], "campo": b3, "barrier_avv": [18, 40, 20], "distrutte_da_me": 1,
      "miei_giocati": ["Topo", "Ariete"]}
mm = {"id": "rv1", "turno": 2, "campo": empty}
for st in (s1, s2, s3):
    mm.update(st)
    review.capture(mm)
assert sorted(mm["stati_round"]) == ["1", "2", "3"]
rv = review.analyze({"stati_round": mm["stati_round"], "leggendaria_mia": "", "carte_mie": []}, time_limit=0.3)
r1 = next(x for x in rv["round"] if x["turno"] == 1)
assert r1["giocata"] == "Topo sinistra slot 1" and r1["classe"] in ("errore", "errore grave"), r1
r2 = next(x for x in rv["round"] if x["turno"] == 2)
assert r2["classe"] == "migliore", r2
assert rv["precisione"] is not None and rv["momento_decisivo"]["turno"] == 1, rv
assert review.classify(0) == "migliore" and review.classify(30) == "errore" and review.classify(99) == "errore grave"
log = [{"id": "rv1", "risultato": "vittoria", "inizio": store.now(), "fine": store.now(), "mio_mazzo": "Test",
        "avv_leggendaria": "Dracula", "stati_round": mm["stati_round"],
        "storico": [{"ora": "10:00:00", "turno": t, "barrier_mie": [20, 20, 20], "barrier_avv": st["barrier_avv"],
                     "distrutte_da_me": st["distrutte_da_me"], "distrutte_a_me": 0} for t, st in ((1, s1), (2, s2), (3, s3))]}]
store.save("matches", log)
assert review.review_pending(time_limit=0.3) == 1 and review.review_pending() == 0
pz = review.puzzles()
assert pz and pz[0]["soluzione"].startswith("Ariete centro") and pz[0]["giocata"] in pz[0]["opzioni"], pz
from origins import history  # noqa: E402
m_log = store.load("matches")[0]
html_rv = history.review_html(m_log)
assert "PRECISIONE" in html_rv and "<svg" in html_rv and "Momento decisivo, round 1" in html_rv, html_rv[:300]
ex = report.exercises_body()
assert "Trova la mossa" in ex and "data-ok='1'" in ex
w = report.week_stats()
assert w["partite"] == 1 and w["precisione"] == m_log["revisione"]["precisione"] and "errore" in "".join(w["errori"]), w
assert "Questa settimana" in report.week_body()
report.LOGS = tmp / "logs"
page = report.library_html("esercizi").read_text(encoding="utf-8")
assert "ESERCIZI" in page and "PRECISIONE MOSSE" in page and "detto contro vero" in page
print("revisione, esercizi e report settimanale ok")

shutil.rmtree(tmp)
print("TUTTO OK")
