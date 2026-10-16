"""Test rapidi: python tests/test_core.py  (usa una cartella dati temporanea, non tocca i tuoi dati)."""
import asyncio
import json
import shutil
import sys
import tempfile
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import odds, store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp


def close(a, b, eps=1e-4):
    assert abs(a - b) < eps, (a, b)


# --- ipergeometrica ---
close(odds.p_at_least_one(25, 2, 5), 1 - comb(23, 5) / comb(25, 5))
close(odds.p_at_least_one(25, 1, 1), 1 / 25)
close(sum(odds.p_exactly(20, 4, 6, k) for k in range(5)), 1.0)
assert odds.p_at_least_one(3, 3, 1) == 1.0 and odds.p_at_least_one(10, 0, 5) == 0.0

# --- database carte con storico patch ---
cards = [{"nome": "Robin Hood", "leggendaria": True, "costo": 5, "attacco": 6, "vita": 8, "tipo": "creatura",
          "testo": "Leggendaria di prova", "potere_leggendario": "Bullseye gratis a inizio partita"}]
cards += [{"nome": f"Carta {i}", "leggendaria": False, "costo": i % 6, "attacco": i % 6 + 1, "vita": 2,
           "tipo": "creatura", "testo": ""} for i in range(1, 15)]
r = store.upsert("cards", cards, "1.0")
assert len(r["aggiunte"]) == 15
r = store.upsert("cards", [{"nome": "Carta 3", "attacco": 9}], "1.1")
assert r["modificate"][0]["modifiche"][0] == {"campo": "attacco", "prima": 4, "dopo": 9}
assert store.find("cards", "carta 3")["attacco"] == 9
store.upsert("cards", [{"nome": "Vecchia", "costo": 1, "potere": 2, "testo": "x"}])
r = store.upsert("cards", [{"nome": "Carta 4", "rarita": "comune"}], "1.1")   # campo vuoto riempito
assert r["modificate"] == [], r
assert store.find("cards", "Robin Hod")["nome"] == "Robin Hood"   # tolleranza errori lettura

# --- mazzo ---
deck_cards = [f"Carta {i}" for i in range(1, 13)]
v = store.validate_deck("Robin Hood", deck_cards)
assert v["valido"], v
assert not store.validate_deck("Robin Hood", deck_cards[:11])["valido"]
store.save_deck("Test", "Robin Hood", deck_cards)

# --- partita simulata tramite i tool MCP ---
import origins.server as srv  # noqa: E402


def call(name, **kw):
    res = asyncio.run(srv.mcp.call_tool(name, kw))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


call("start_match", my_deck="Test", opponent_legendary="Robin Hood")
call("update_match", turn=2, my_hand=["Carta 1", "Carta 1", "Carta 2", "Carta 3"],
     my_played=["Carta 4"], opp_played=["Carta 13"], opp_hand_size=4)
v = call("update_match", mana=3, my_barriers=[20, 8, 40], opp_barriers=[12, 20, 20], my_destroyed=0,
         opp_destroyed=1, reveals_first="io", my_deck_left=19)
assert '"barrier_mie": [' in v and "Il gioco mostra 19" in v, v   # il tracciamento dice 20
assert "⚠" not in call("update_match", my_deck_left=20)
o = json.loads(call("my_draw_odds", draws=1, cards=["Carta 2", "Carta 5"]))
assert o["carte_nel_mazzo"] == 20, o
close(o["gruppo"]["p_almeno_una"], 3 / 20)       # 1 copia di Carta 2 + 2 di Carta 5
assert all(e["carta"] != "Carta 1" for e in o["per_carta"])  # entrambe le copie già in mano

# meta: due archetipi di Robin Hood
store.record_opponent("Robin Hood", ["Carta 13", "Carta 14", "Carta 1"], "vittoria")
store.save("meta", store.load("meta") + [{"nome": "RH alt", "leggendaria": "Robin Hood",
                                           "carte": ["Carta 5", "Carta 6"], "volte_visto": 3,
                                           "vittorie_mie": 0, "sconfitte_mie": 0}])
h = json.loads(call("opponent_hand_odds"))
assert [a["nome"] for a in h["archetipi_compatibili"]] == ["Robin Hood #1"], h  # RH alt incompatibile (Carta 13)
c14 = next(e for e in h["per_carta"] if e["carta"] == "Carta 14")
close(c14["p_in_mano"], odds.p_at_least_one(24, 2, 4))
call("end_match", result="vittoria")
rh1 = next(a for a in store.meta_summary() if a["nome"] == "Robin Hood #1")
assert rh1["volte_visto"] == 2 and rh1["mio_winrate_contro"] == 1.0, rh1

# --- tool immagine (cattura simulata) ---
from PIL import Image as PILImage  # noqa: E402
from origins import screen  # noqa: E402

fake = tmp / "fake.png"
PILImage.new("RGB", (64, 36), "red").save(fake)
screen.capture = lambda *a, **k: fake
res = asyncio.run(srv.mcp.call_tool("get_screen", {}))
content = res[0] if isinstance(res, tuple) else res
assert any(getattr(c, "type", "") == "image" for c in content), content

chk = json.loads(call("cards_to_check"))
assert [x["nome"] for x in chk["carte"]] == ["Vecchia"], chk
assert "9⚔/2❤" in call("search_cards", query="Carta 3")
c = json.loads(call("deck_curve", legendary="Robin Hood", cards=deck_cards))
assert c["carte"] == 25 and c["creature"] == 25 and c["vita_totale"] == 24 * 2 + 8, c
assert any(k.startswith("p_almeno_una_giocabile") for k in c), c

# --- regolamento ---
from origins import rules  # noqa: E402

st = json.loads(call("rules_get", stato="domanda"))
assert len(st) >= 10
qid = next(r["id"] for r in st if "mano iniziale" in r["testo"].lower())
r = json.loads(call("rules_upsert", id=qid, testo="Mano iniziale: 4 carte, nessun mulligan",
                    stato="confermata", fonte="Daniele", prova="risposta all'intervista"))
assert r["azione"] == "aggiornata" and r["regola"]["stato"] == "confermata" and r["regola"]["storico"]
r = json.loads(call("rules_upsert", testo="Le carte si rivelano da sinistra a destra", categoria="rivelazione",
                    stato="probabile", fonte="osservazione 20261015", prova="T2 fot. 0012"))
assert r["azione"] == "creata" and r["regola"]["id"].startswith("R")
assert call("rules_upsert", id=qid, stato="forse").startswith("Errore")
md = (tmp / "regole.md").read_text(encoding="utf-8")
assert "Mano iniziale: 4 carte" in md and "✅" in md and "🟡" in md
(tmp / "rules.md").write_text("vecchie note ✅", encoding="utf-8")
assert "vecchie note" in call("legacy_rules_file") and (tmp / "rules_vecchio.md").exists()
assert "Nessun vecchio" in call("legacy_rules_file")

# --- registrazioni ---
screen.RECORDINGS = tmp / "reg"
screen.RECORDINGS.mkdir()
d = screen.new_recording()
PILImage.new("RGB", (8, 8)).save(d / "0001_x.png")
lst = json.loads(call("list_recordings"))
assert lst[0]["fotogrammi"] == 1 and not lst[0]["elaborata"]
assert json.loads(call("recording_frames", nome=d.name))["totale"] == 1
call("mark_recording_done", nome=d.name, riassunto="ok")
assert json.loads(call("list_recordings"))[0]["elaborata"]

# --- lezioni ---
r = json.loads(call("record_lesson", lezione="Se Robin Hood ha 5 mana aspettati Carta 13 al centro",
                    tipo="mossa_avversaria", carte=["Robin Hod", "Carta 13"], accaduto="R4: Carta 13 al centro",
                    fonte="partita R4"))
assert r["azione"] == "nuova" and r["lezione"]["stato"] == "ipotesi" and r["lezione"]["carte"] == ["Robin Hood", "Carta 13"], r
lid = r["lezione"]["id"]
r = json.loads(call("record_lesson", lezione="Se Robin Hood ha 5 mana, aspettati Carta 13 al centro: tieni un blocco",
                    tipo="mossa_avversaria", carte=["Carta 13"], fonte="partita R6"))
assert r["azione"] == "rafforzata" and r["lezione"]["id"] == lid and r["lezione"]["stato"] == "confermata", r
r = json.loads(call("record_lesson", lezione="Carta 2 non si attiva se la corsia è piena", tipo="interazione",
                    carte=["Carta 2"], fonte="Daniele"))
assert r["lezione"]["stato"] == "confermata"  # insegnata da Daniele: subito confermata
assert call("record_lesson", lezione="x", tipo="boh").startswith("Errore")
call("start_match", my_deck="Test", opponent_legendary="Robin Hood")
out = call("update_match", turn=1, my_hand=["Carta 1"], opp_played=["Carta 13"], opp_hand_size=3)
assert "LEZIONI GIÀ IMPARATE" in out and lid in out and "Carta 2 non si attiva" not in out, out
json.loads(call("lesson_review", id=lid, stato="smentita"))
assert lid not in call("update_match", turn=2)
assert "❌" in (tmp / "lezioni.md").read_text(encoding="utf-8")
call("end_match", result="vittoria")

# --- sottotitoli video ---
from origins.video import vtt_to_text  # noqa: E402

vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nciao\n\n00:00:03.000 --> 00:00:05.000\nciao\nmondo\n"
assert vtt_to_text(vtt) == "[00:01] ciao mondo", vtt_to_text(vtt)

shutil.rmtree(tmp)
print("TUTTI I TEST OK")
