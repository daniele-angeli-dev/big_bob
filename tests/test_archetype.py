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

shutil.rmtree(tmp, ignore_errors=True)
print("\nFALLITI:", len(FAILED))
sys.exit(1 if FAILED else 0)
