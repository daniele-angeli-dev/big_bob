"""Riconoscimento del mazzo avversario: python tests/test_archetype.py (dati temporanei, niente rete)."""
import asyncio
import json
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

from origins import archetype, odds  # noqa: E402
from origins import server as srv  # noqa: E402

FAILED = []


def check(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        FAILED.append(msg)


def call(name, **kw):
    res = asyncio.run(srv.mcp.call_tool(name, kw))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


# carte: le "Rapida" costano poco, le "Lenta" tanto, le "Magia" sono spell
cards = [{"nome": "Dracula", "leggendaria": True, "costo": 5, "attacco": 4, "vita": 4, "tipo": "creatura"},
         {"nome": "Robin Hood", "leggendaria": True, "costo": 5, "attacco": 4, "vita": 4, "tipo": "creatura"}]
cards += [{"nome": f"Rapida {i}", "costo": 1 + i % 3, "attacco": 2, "vita": 1, "tipo": "creatura"} for i in range(1, 13)]
cards += [{"nome": f"Lenta {i}", "costo": 4 + i % 3, "attacco": 5, "vita": 6, "tipo": "creatura"} for i in range(1, 9)]
cards += [{"nome": f"Magia {i}", "costo": 3 + i % 2, "tipo": "spell"} for i in range(1, 9)]
store.upsert("cards", cards, "0.7")
AGGRO = [f"Rapida {i}" for i in range(1, 13)]
CONTROL = [f"Lenta {i}" for i in range(1, 7)] + [f"Magia {i}" for i in range(1, 7)]
MID = [f"Rapida {i}" for i in range(1, 7)] + [f"Lenta {i}" for i in range(3, 9)]
meta = [
    {"nome": "Bat Swarm (OriginsMeta)", "leggendaria": "Dracula", "carte": AGGRO, "fonte": "originsmeta",
     "archetipo": "Swarm / go wide", "community": 2, "volte_visto": 0},
    {"nome": "Night Control (OriginsMeta)", "leggendaria": "Dracula", "carte": CONTROL, "fonte": "originsmeta",
     "archetipo": "Control", "community": 2, "volte_visto": 0},
    {"nome": "Dracula #1", "leggendaria": "Dracula", "carte": MID, "volte_visto": 1},
    {"nome": "Sherwood (OriginsMeta)", "leggendaria": "Robin Hood", "carte": AGGRO, "archetipo": "Aggro"},
]
store.save("meta", meta)


def match(seen, leg="Dracula", hand=4):
    return {"avv_leggendaria": leg, "avv_giocati": seen, "avv_scartati": [], "avv_mano": hand,
            "leggendaria_mia": "Robin Hood", "carte_mie": AGGRO, "mia_mano": [], "miei_giocati": [],
            "miei_scartati": [], "turno": 3}


print("1. tipi")
check(archetype.deck_type(meta[0])["etichetta"] == "Aggro" and archetype.deck_type(meta[0])["sottotipo"] == "Swarm",
      "tag Swarm → Aggro, sottotipo Swarm")
check(archetype.deck_type({"archetipo": "Tempo"})["etichetta"] == "Midrange (aggro)", "Tempo → Midrange (aggro)")
check(archetype.deck_type({"archetipo": "Big / big bodies"})["etichetta"] == "Midrange (control)", "Big → Midrange (control)")
check(archetype.curve_type(AGGRO)["base"] == "Aggro", "curva bassa → Aggro")
check(archetype.curve_type(CONTROL)["base"] == "Control", "curva alta con magie → Control")
check(archetype.deck_type(meta[2])["etichetta"].startswith("Midrange"), "senza tag: Midrange dalla curva")

print("2. riconoscimento")
i0 = archetype.identify(match([]))
check(i0["mazzi"] and i0.get("nota"), f"senza carte viste: solo diffusione ({i0['mazzi'][0]['nome']})")
i1 = archetype.identify(match(["Rapida 1", "Rapida 9", "Rapida 11"]))
check(i1["mazzi"][0]["nome"] == "Bat Swarm (OriginsMeta)" and i1["tipo"]["etichetta"] == "Aggro"
      and i1["tipo"]["p"] > 0.9, f"carte rapide → Bat Swarm, Aggro: {archetype.summary(i1)}")
i2 = archetype.identify(match(["Lenta 1", "Magia 2", "Magia 5", "Rapida 12"]))
check(i2["mazzi"][0]["nome"] == "Night Control (OriginsMeta)" and i2["mazzi"][0]["fuori_lista"] == ["Rapida 12"],
      f"una carta fuori lista non esclude il mazzo giusto: {archetype.summary(i2)}")
check("Control" in archetype.summary(i2) and i2["contro"], "riassunto e consiglio contro")
i3 = archetype.identify(match(["Rapida 2", "Lenta 4"]))
check(i3["mazzi"][0]["nome"] == "Dracula #1", f"carte miste → il mazzo midrange visto da te: {archetype.summary(i3)}")
i4 = archetype.identify(match(["Lenta 1", "Lenta 2", "Magia 1"], leg="Frankenstein"))
check(not i4["mazzi"] and i4["tipo"]["etichetta"] == "Control", "leggendaria senza mazzi nel meta: tipo dalla curva")
check(archetype.short(i1)["p"] > 90 and archetype.short(i1)["mazzo"] == "Bat Swarm (OriginsMeta)", "per la finestra")

print("3. probabilità sulla mano con una variante")
o = odds.opponent_hand_odds(meta, "Dracula", {"Lenta 1": 1, "Magia 2": 1, "Rapida 12": 1}, 4)
check(o.get("per_carta") and o["archetipi_compatibili"][0]["nome"] == "Night Control (OriginsMeta)"
      and "variante" in o.get("avviso", ""), f"usa la lista più simile invece di arrendersi: {o.get('avviso')}")
o = odds.opponent_hand_odds(meta, "Dracula", {"Lenta 1": 1}, 4)
check([a["nome"] for a in o["archetipi_compatibili"]] == ["Night Control (OriginsMeta)"] and "avviso" not in o,
      "con liste compatibili resta il calcolo esatto")

print("4. strumenti")
store.save("decks", [{"nome": "Test", "leggendaria": "Robin Hood", "carte": AGGRO}])
call("start_match", my_deck="Test", opponent_legendary="Dracula")
out = call("update_match", turn=3, opp_played=["Lenta 1", "Magia 2", "Magia 5"], opp_hand_size=4)
check("MAZZO AVVERSARIO" in out and "Night Control" in out and "Come giocarci contro" in out,
      "update_match mostra mazzo e tipo avversario")
od = json.loads(call("opponent_deck"))
check(od["tipo"]["etichetta"] == "Control", "strumento opponent_deck")
call("end_match", result="vittoria")
last = store.load("matches")[-1]
check(last.get("tipo_avversario") == "Control" and last.get("mazzo_avversario_stimato") == "Night Control (OriginsMeta)",
      "la partita salva tipo e mazzo avversario")

print("5. previsione delle carte avversarie")
m = match(["Lenta 1", "Magia 2"], hand=4)
m.update({"mana": 5, "barrier_mie": [20, 6, 20]})
pr = archetype.predict(m)
names = [x["carta"] for x in pr["carte"]]
check(pr["tipo"] == "Control" and all(n.startswith(("Lenta", "Magia")) for n in names),
      f"carte probabili dal mazzo stimato: {names}")
check(all(x["costo"] <= 5 for x in pr["giocabili"]) and pr["giocabili"], f"giocabili con 5 mana: {pr['giocabili']}")
check(0.5 < pr["p_giocabile"] <= 1, f"probabilità di avere una giocata: {pr['p_giocabile']}")
check(pr["minaccia"] and pr["minaccia"]["carta"].startswith("Lenta"), f"minaccia: {pr['minaccia']}")
check(pr["piano"] and "rimozioni" in pr["piano"] and pr["bersaglio"] == "", "piano tipico del Control, senza bersaglio")
_orig = archetype._card_rounds
archetype._card_rounds = lambda: {"lenta-3": 2.0, "magia-1": 6.0, "lenta-4": 9.0}  # round medio da OriginsMeta
pt = archetype.predict({**m, "turno": 6})
archetype._card_rounds = _orig
check(pt["giocabili"][0]["carta"] == "Magia 1", f"il round tipico conta: {[x['carta'] for x in pt['giocabili']]}")
pa = archetype.predict({**match(["Rapida 1", "Rapida 2"], hand=3), "mana": 2, "barrier_mie": [20, 6, 20]})
check(pa["tipo"] == "Aggro" and "centro" in pa["bersaglio"], f"Aggro punta la corsia più bassa: {pa['bersaglio']}")
check(all((x["costo"] or 0) <= 2 for x in pa["giocabili"]), "solo carte da 2 mana")
lines = archetype.predict_lines(pr)
check(lines[0].startswith("PREVISIONE AVVERSARIO") and any("Minaccia principale" in x for x in lines), "righe per update_match")
check(archetype.predict(match([], hand=None))["carte"] == [], "senza carte in mano note: niente percentuali")

print("6. previsione verificata round per round")
call("start_match", my_deck="Test", opponent_legendary="Dracula")
call("update_match", turn=3, mana=4, opp_played=["Lenta 1"], opp_hand_size=4)
prev = store.load("match")["previsione"]
check(prev["carte"] and prev["turno"] == 3, f"previsione salvata: {prev['carte']}")
out = call("update_match", turn=4, mana=5, opp_played=["Lenta 1", prev["carte"][0], "Rapida 7"], opp_hand_size=3)
pv = store.load("match")["previsioni"][-1]
check(pv["azzeccate"] == [prev["carte"][0]] and pv["sorprese"] == ["Rapida 7"], f"confronto: {pv}")
check("Previsione del round 3" in out and "Rapida 7 ✗" in out and "PREVISIONE AVVERSARIO" in out, "update_match lo dice")
check("SORPRESE DEL ROUND PRIMA" in out and "Rapida 7" in out.split("SORPRESE DEL ROUND PRIMA")[1],
      "la carta non prevista diventa una sorpresa da cui imparare")
import controller as _ctl  # noqa: E402
hud = _ctl.Controller._opp_deck(store.load("match"))
check(hud and len(hud["probabili"]) >= 1 and "p" in hud["probabili"][0], f"finestra: {hud and hud['probabili']}")
call("end_match", result="sconfitta")
from origins import report  # noqa: E402
report.LOGS = tmp / "logs"
check("CARTE AVVERSARIE PREVISTE" in report.stats_body(), "statistiche: precisione delle previsioni")

print("7. contatori: seconda copia e mano stimata")
call("start_match", my_deck="Test", opponent_legendary="Dracula")
call("update_match", turn=2, opp_played_new=["Rapida 1"], opp_hand_size=5, my_hand=["Rapida 2", "Rapida 3"])
call("update_match", turn=2, opp_played_new=["Rapida 1"])  # secondo F8 nello stesso round: non conta due volte
check(store.load("match")["avv_giocati"] == ["Rapida 1"], "stesso round: una copia sola")
call("update_match", turn=4, opp_played=["Rapida 1"], opp_played_new=["Rapida 1"])  # la prima è morta, gioca la seconda
check(store.load("match")["avv_giocati"] == ["Rapida 1", "Rapida 1"], "seconda copia in un round dopo: contata")
call("update_match", turn=5, opp_played=["Rapida 1", "Rapida 4"])
check(store.load("match")["avv_giocati"].count("Rapida 1") == 2, "le liste complete non tolgono copie")
from origins import evaluate  # noqa: E402
c = evaluate.counters(store.load("match"))
# letta 5 al round 2 con 1 carta uscita; ora round 5 (+3) e 3 carte uscite (+2) → 6
check(c["avv_mano"] == 6 and c["avv_mano_stimata"], f"mano avversaria stimata: {c['avv_mano']} ({c['avv_mano_come']})")
check(c["mia_mano"] == 5 and c["mia_mano_stimata"], f"mia mano stimata: {c['mia_mano']}")
out = call("update_match", turn=5, opp_hand_size=4, my_hand_size=3)
c = evaluate.counters(store.load("match"))
check(c["avv_mano"] == 4 and not c["avv_mano_stimata"] and c["mia_mano"] == 3, "letta sullo schermo vince")
check("GIOCATE REGISTRATE" in out and "Rapida 1×2" in out, "update_match mostra le giocate registrate")
call("end_match", result="vittoria")

print("8. chi rivela prima")
call("start_match", my_deck="Test", opponent_legendary="Dracula")
call("update_match", turn=1, reveals_first="Daniele")
check(store.load("match")["rivela_prima"] == "io", "'Daniele' = io")
out = call("update_match", turn=2)
m = store.load("match")
check(m["rivela_prima"] == "avversario" and m["rivela_prima_dedotta"] and "dedotto" in out, "round dopo: si alterna")
call("update_match", turn=5)
check(store.load("match")["rivela_prima"] == "io", "round 5: 4 round dopo il primo, di nuovo io")
call("update_match", turn=6, reveals_first="opponent")
m = store.load("match")
check(m["rivela_prima"] == "avversario" and not m["rivela_prima_dedotta"], "letto sullo schermo vince")
call("end_match", result="vittoria")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFALLITI:", len(FAILED))
sys.exit(1 if FAILED else 0)
