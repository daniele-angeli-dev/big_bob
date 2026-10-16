"""Test di simulatore, mulligan, laboratorio, location e meta community: python tests/test_sim.py"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import combat, lab, odds, store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

store.upsert("cards", [
    {"nome": "Robin Hood", "leggendaria": True, "costo": 5, "attacco": 6, "vita": 8, "tipo": "creatura"},
    {"nome": "Friar Tuck", "costo": 3, "attacco": 4, "vita": 5, "tipo": "creatura"},
    {"nome": "Marian", "costo": 2, "attacco": 3, "vita": 4, "tipo": "creatura"},
    {"nome": "Brides of Dracula", "costo": 3, "attacco": 3, "vita": 3, "tipo": "creatura"},
    {"nome": "Wall", "costo": 2, "attacco": 0, "vita": 9, "tipo": "creatura", "testo": "Defender"},
    {"nome": "Giant", "costo": 6, "attacco": 25, "vita": 9, "tipo": "creatura"},
] + [{"nome": f"Filler {i}", "costo": i % 5 + 1, "attacco": 2, "vita": 2, "tipo": "creatura"} for i in range(10)])
store.upsert("locations", [{"nome": "Sherwood Forest", "testo": "Le creature qui hanno +1 attacco"}])

L = combat.normalize_board


def sim(board, bm=(20, 20, 20), bo=(20, 20, 20), by=0, to=0, direct=None):
    return combat.simulate(L(board), list(bm), list(bo), by, to, direct)


# colpo alla barrier con slot di fronte vuoto
r = sim({"sinistra": {"mie": ["Friar Tuck"], "avv": [None]}}, bo=(12, 20, 20))
assert r["barrier_avv"] == [8, 20, 20], r
# blocco: colpi simultanei, il danno resta
r = sim({"centro": {"mie": ["Marian"], "avv": ["Brides of Dracula"]}})
assert r["barrier_avv"] == [20, 20, 20] and r["sopravvissuti"]["centro"] == {"mie": ["Marian 3/1"], "avv": []}, r
# statistiche attuali lette dallo schermo hanno la precedenza
r = sim({"centro": {"mie": ["Marian 3/1"], "avv": ["Brides of Dracula"]}})
assert r["sopravvissuti"]["centro"] == {"mie": [], "avv": []}, r
# Defender assorbe i colpi diretti alla barrier, anche più di uno
r = sim({"destra": {"mie": ["Friar Tuck", "Marian"], "avv": [None, None, "Wall"]}})
assert r["barrier_avv"] == [20, 20, 20] and r["sopravvissuti"]["destra"]["avv"] == ["Wall 0/2"], r
# barrier distrutta: si rinforza a 40, il danno in eccesso si perde
r = sim({"sinistra": {"mie": ["Giant"], "avv": [None]}}, bo=(10, 20, 20))
assert r["barrier_avv"][0] == 40 and r["distrutte_da_te"] == 1 and r["vincitore"] is None, r
# seconda barrier = vittoria; vince chi arriva prima seguendo la freccia (sinistra prima di destra)
r = sim({"sinistra": {"mie": ["Giant"], "avv": [None]}, "destra": {"mie": [None], "avv": ["Giant"]}},
        bm=(20, 20, 5), bo=(5, 20, 20), by=1, to=1)
assert r["vincitore"].startswith("VINCI TU") and "sinistra" in r["vincitore"], r
# entrambi a 2 nella stessa corsia: segnalato come da verificare, non indovinato
r = sim({"centro": {"mie": ["Giant"], "avv": ["Wall"]}}, bm=(20, 4, 20), bo=(20, 4, 20), by=1, to=1,
        direct=None)
r2 = sim({"centro": {"mie": ["Giant", None], "avv": [None, "Giant"]}}, bm=(20, 4, 20), bo=(20, 4, 20), by=1, to=1)
assert "da verificare" in r2["vincitore"], r2
# danni diretti (On Reveal) prima del combattimento
r = sim({}, bm=(20, 8, 20), direct=[{"corsia": "centro", "bersaglio": "mia", "danno": 4, "nota": "Brides"}])
assert r["barrier_tue"][1] == 4, r

# mulligan e laboratorio
deck = ["Friar Tuck", "Marian", "Brides of Dracula", "Wall", "Giant"] + [f"Filler {i}" for i in range(7)]
m = lab.mulligan_eval("Robin Hood", deck, ["Giant", "Robin Hood", "Marian", "Wall"], sims=300)
best = m["migliori"][0]
assert "Giant" in best["cambia"] and "Marian" in best["tieni"], best
d = lab.deck_lab("Robin Hood", deck, games=300)
assert len(d["p_almeno_una_giocata"]) == 6 and d["mana"][:3] == [2, 3, 4], d

# strumenti MCP
import origins.server as srv  # noqa: E402


def call(name, **kw):
    res = asyncio.run(srv.mcp.call_tool(name, kw))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


store.save_deck("Test", "Robin Hood", deck)
call("start_match", my_deck="Test", opponent_legendary="Dracula")
out = call("update_match", turn=4, mana=5, my_barriers=[20, 8, 20], opp_barriers=[12, 20, 31],
           opp_reinforced=[False, False, True], opp_destroyed=1, my_destroyed=0, opp_hand_size=4,
           locations=["Sherwood Forest", "Tempio Ignoto"],
           board={"sinistra": {"mie": ["Friar Tuck 4/5"], "avv": [None]},
                  "centro": {"mie": [None], "avv": ["Brides of Dracula 3/3"]}})
assert "PREVISIONE COMBATTIMENTO" in out and "12→8" in out and "8→5" in out, out
assert "Sherwood Forest — Le creature qui hanno +1 attacco" in out and "Tempio Ignoto — NUOVA" in out, out
s = call("simulate_combat", scenari=[{"nome": "Marian al centro", "mie": [{"carta": "Marian", "corsia": "centro"}]},
                                     {"nome": "Troppo caro", "mie": [{"carta": "Giant", "corsia": "destra"}]}])
assert "Marian al centro" in s and "barrier tue [20, 8, 20]" in s and "costo 6 > mana 5" in s, s
mu = json.loads(call("mulligan_advice", hand=["Giant", "Marian", "Wall", "Filler 1"]))
assert mu["migliori"] and "tenere_tutto" in mu
dl = json.loads(call("deck_lab", decks=["Test"], games=200))
assert "Test" in dl
call("note_round", round=4, consiglio_seguito=True, esito="bene: centro salvato")
assert store.load("match")["rounds"][0]["consiglio_seguito"] is True

# meta community: pesa nelle probabilità ma non come partita giocata
a = json.loads(call("record_opponent_deck", legendary="Dracula", cards_seen=["Brides of Dracula", "Wall"],
                    archetype="Dracula Wall", fonte="community"))
assert a["community"] == 1 and a["volte_visto"] == 0, a
w = odds.opponent_hand_odds(store.load("meta"), "Dracula", {}, 4)
assert w["archetipi_compatibili"][0]["nome"] == "Dracula Wall", w

shutil.rmtree(tmp)

# gli slot si contano da 1 (come li vede Daniele); 0 viene trattato come 1
L = combat.normalize_board({"centro": {"mie": [None, "Marian 3/1"], "avv": []}})
assert combat.place(L, "mie", "Wall 0/2", "centro", 1) == "" and L[1]["mie"][0]["nome"] == "Wall"
assert "slot 2" in combat.place(L, "mie", "Wall 0/2", "centro", 2)
combat.place(L, "avv", "Wall 0/2", "sinistra", 3)
assert len(L[0]["avv"]) == 3 and L[0]["avv"][2]["nome"] == "Wall"
lines = combat.board_lines(L)
assert any("slot 1 Wall" in x and "slot 2 Wall" in x for x in lines) and not any("slot 0" in x for x in lines), lines

print("SIMULAZIONI OK")
