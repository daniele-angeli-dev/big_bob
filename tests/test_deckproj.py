"""Modalità CREAZIONE MAZZO: python tests/test_deckproj.py (dati temporanei, nessuna rete, niente Claude)."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["BIGBOB_NO_SYNC"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import deckproj, report  # noqa: E402
from origins import server as srv  # noqa: E402

report.LOGS = tmp / "logs"

cards = [{"nome": "Robin Hood", "leggendaria": True, "costo": 8, "attacco": 4, "vita": 4, "tipo": "creatura"},
         {"nome": "Dracula", "leggendaria": True, "costo": 4, "attacco": 3, "vita": 2, "tipo": "creatura"}]
cards += [{"nome": f"Carta {i}", "leggendaria": False, "costo": 1 + i % 6, "attacco": 2, "vita": 2,
           "tipo": "creatura"} for i in range(1, 17)]
store.upsert("cards", cards, "0.7")
DECK = [f"Carta {i}" for i in range(1, 13)]


def call(name, **kw):
    res = asyncio.run(srv.mcp.call_tool(name, kw))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


def play(result, played, hand=(), opp="Dracula", rounds=6, deck="Sniper Lab"):
    """Una partita di test completa attraverso gli strumenti veri (start/update/end)."""
    call("start_match", my_deck=deck, opponent_legendary=opp)
    for t in range(1, rounds + 1):
        call("update_match", turn=t, my_hand=list(hand), my_played=played[:t], my_destroyed=0, opp_destroyed=0)
    call("end_match", result=result)


# ---- creazione: progetto valido, mazzo salvato con lo stesso nome, partite obiettivo
bad = json.loads(call("deck_project_start", nome="Rotto", leggendaria="Robin Hood", carte=DECK[:11]))
assert bad["errore"] and bad["problemi"]
r = json.loads(call("deck_project_start", nome="Sniper Lab", leggendaria="Robin Hood", carte=DECK, obiettivo="Robin Hood",
                    motivo="Snipe su una barrier", fonti=["SNIPER (OriginsMeta)"], partite=6))
assert r["versione"] == 1 and r["partite_di_test"] == 6 and store.get_deck("Sniper Lab")
assert "TEST del progetto" in call("start_match", my_deck="Sniper Lab", opponent_legendary="Dracula")
store.save("match", {})

# ---- 6 partite: Carta 12 sempre in mano ma mai giocata, Carta 11 giocata solo nelle sconfitte
for i in range(6):
    win = i < 4
    played = [f"Carta {k}" for k in range(1, 6)] + ([] if win else ["Carta 11"])
    play("vittoria" if win else "sconfitta", played, hand=["Carta 12"], opp="Dracula" if i % 2 else "Merlin")
st = json.loads(call("deck_project_status"))
cur = st["statistiche_versione_attuale"]
assert cur["partite"] == 6 and cur["vinte"] == 4 and st["partite_mancanti"] == 0, st
assert cur["intervallo_95"][0] < cur["winrate"] < cur["intervallo_95"][1] and cur["margine"] == 40
assert cur["carte"]["Carta 12"]["pescata"] == 6 and cur["carte"]["Carta 12"]["giocata"] == 0
assert cur["carte"]["Carta 11"]["winrate_giocata"] == 0 and cur["carte"]["Carta 1"]["round_medio"] == 1
assert cur["carte"]["Carta 5"]["round_medio"] == 5
assert any(w.startswith("Carta 12") and "resta in mano" in w for w in st["punti_deboli"]), st["punti_deboli"]
assert "Test della versione finito" in st["consiglio"]
assert cur["contro"]["Merlin"]["partite"] == 3

# ---- miglioria: proposta valida e non valida, applicazione = v2, mazzo salvato aggiornato
assert "errore" in json.loads(call("deck_project_propose", togli=["Gandalf il Grigio"], metti=["Carta 13"], motivo="x"))
assert "errore" in json.loads(call("deck_project_propose", togli=["Carta 12"], metti=["Carta 1"], motivo="doppia"))
pr = json.loads(call("deck_project_propose", togli=["Carta 12"], metti=["Carta 13"], motivo="Carta 12 resta in mano"))
assert pr["proposta"]["partite"] == 8 and "togli Carta 12 ×2 e metti Carta 13 ×2" in pr["nel_gioco"]
s = deckproj.summary()
assert s["proposta"] and s["mancanti"] == 0
ap = json.loads(call("deck_project_apply"))
assert ap["versione"] == 2 and ap["partite_di_test"] == 8
assert "Carta 13" in store.get_deck("Sniper Lab")["carte"] and "Carta 12" not in store.get_deck("Sniper Lab")["carte"]
assert deckproj.summary()["proposta"] is None and deckproj.summary()["mancanti"] == 8

# ---- v2: 6 vittorie su 6 -> confronto netto in anticipo (prima delle 8 partite)
for i in range(6):
    play("vittoria", [f"Carta {k}" for k in range(1, 6)] + ["Carta 13"])
st = json.loads(call("deck_project_status"))
assert st["versione_attuale"] == 2 and st["confronto"]["contro_versione"] == 1
assert st["confronto"]["p_migliore"] >= 90 and st["valutazione_anticipata"] and st["partite_mancanti"] == 0, st
assert [v["partite"] for v in st["versioni"]] == [6, 6], "ogni partita conta per la sua versione"
assert st["versioni"][1]["tolte"] == ["Carta 12"] and st["versioni"][1]["messe"] == ["Carta 13"]

# ---- v3 peggiore -> il consiglio è tornare indietro; revert crea v4 con le carte della v2
json.loads(call("deck_project_propose", togli=["Carta 13"], metti=["Carta 14"], motivo="prova"))
deckproj.apply()
for i in range(6):
    play("sconfitta", [f"Carta {k}" for k in range(1, 6)])
st = deckproj.status(deckproj.active())
assert st["confronto"]["netto"] == "peggiore" and "torna indietro" in st["consiglio"], st
rv = json.loads(call("deck_project_revert", versione=2, motivo="la v3 perde"))
assert rv["versione"] == 4 and "Carta 13" in store.get_deck("Sniper Lab")["carte"]

# ---- partita con un altro mazzo: non conta per il progetto
store.save_deck("Altro", "Dracula", DECK)
play("vittoria", ["Carta 1"], deck="Altro")
assert all(m.get("progetto") is None for m in store.load("matches") if m.get("mio_mazzo") == "Altro")
assert json.loads(call("deck_project_list"))[0]["versione"] == 4

# ---- pagina delle statistiche del mazzo
h = report.lab_html().read_text(encoding="utf-8")
assert "LABORATORIO · SNIPER LAB" in h and "v4" in h and "− Carta 12" in h and "+ Carta 13" in h
assert "Carte nella v3 (l&#x27;ultima con partite" in h or "Carte nella v3 (l'ultima con partite" in h, \
    "la v4 non ha partite: si vedono le carte della v3"
assert "Contro le leggendarie" in h and "Partite di test" in h
assert h.count("class='ver") == 4

# ---- controller: modalità a tre stati, pannello, applica, mazzo del progetto per primo in NUOVA
import controller  # noqa: E402


class UI:
    def __init__(self):
        self.ev = []

    def emit(self, e):
        self.ev.append(e)

    def hide(self): pass
    def show(self): pass
    def is_visible(self): return True
    def rect(self): return None


from origins import spazio  # noqa: E402
spazio.LOGS, spazio.CAPTURES = tmp / "logs", tmp  # la pulizia del test non tocca i dati veri
ui = UI()
c = controller.Controller(ui)
c.readers = {}  # niente lettori veri nei test
cfg = store.load("config")
cfg["modalita"] = "allenamento"
store.save("config", cfg)
c.toggle_mode()
c.toggle_mode()
assert store.load("config")["modalita"] == "creazione"
st_ev = [e for e in ui.ev if e["type"] == "state"][-1]
assert st_ev["mode"] == "creazione" and st_ev["lab"]["nome"] == "Sniper Lab" and st_ev["lab"]["v"] == 4
assert st_ev["decks"][0] == "Sniper Lab"
c.toggle_mode()
assert store.load("config")["modalita"] == "allenamento"
deckproj.propose("Sniper Lab", ["Carta 1"], ["Carta 15"], "più spinta")
ui.ev.clear()
c._lab_after("fine")
assert [e["label"] for e in ui.ev if e["type"] == "action"] == ["APPLICA MIGLIORIA", "STATISTICHE DEL MAZZO"]
c.lab_apply()
assert any(e["type"] == "say" and "Versione 5" in e["text"] and "Carta 15 ×2" in e["text"] for e in ui.ev)

# le pagine si aprono dentro l'app (finestra di BIG-BOB), non nel browser
opened = []
ui.show_html = lambda html_, title: opened.append(html_) or True
c.open_lab()
c.open_learned()
c.open_stats()
c.open_library("mazzi")
import re as _re
tabs = [(_re.search(r"data-tab='(\w+)'", x).group(1), _re.search(r"data-deck='([^']*)'", x).group(1)) for x in opened]
assert tabs == [("mazzi", "sniper-lab"), ("studio", ""), ("statistiche", ""), ("mazzi", "")], tabs
assert all("<html" in x and "file:" not in x for x in opened), "dati passati direttamente alla finestra, niente file"
# RIVEDI LA PARTITA apre la partita nella scheda PARTITE; le schermate arrivano su richiesta come anteprime leggere
from origins import history as _hist
_hist.LOGS = tmp / "logs"
jd = _hist.journals_dir() / "20261017-100000"; jd.mkdir(parents=True)
from PIL import Image as _Im
_Im.new("RGB", (1920, 1080), (40, 20, 80)).save(jd / "01.png")
(jd / "diario.md").write_text("# Partita del 17/10/2026 10:00\nMazzo: Sniper Lab\n\n## #1 · 10:00:05 · Analisi round · "
                              "schermata 01.png\nStrumenti: x\n\nrisposta", encoding="utf-8")
c.journal_dir = jd
opened.clear()
c.open_replay()
assert "data-tab='partite'" in opened[0] and "data-match='20261017-100000'" in opened[0], "si apre sulla partita"
assert "src='01.png'" not in opened[0] and len(opened[0]) < 300_000, "le schermate non sono incorporate tutte"
img = c.history_image("partite/20261017-100000/01.png")
assert img.startswith("data:image/jpeg;base64,") and len(img) < 120_000, "schermata come anteprima leggera"

# la finestra del libro: tre schede, un riquadro per ogni mazzo salvato, scheda di dettaglio per ciascuno
h = report.library_html("mazzi", "Sniper Lab").read_text(encoding="utf-8")
for t in ("MAZZI", "STATISTICHE", "STUDIO"):
    assert f">{t}</button>" in h, t
assert h.index(">MAZZI</button>") < h.index(">STATISTICHE</button>") < h.index(">STUDIO</button>")
assert "data-deck='sniper-lab'" in h and "id='t-studio'" in h and "id='t-statistiche'" in h
assert "Studio delle registrazioni" in h and "Cosa ho imparato" in h
assert h.count("class='dtile'") == len(store.load("decks")) == 2
assert "IN CREAZIONE · v5" in h, "il mazzo del laboratorio ha la sua etichetta"
assert "id='d-sniper-lab'" in h and "id='d-altro'" in h and "← TUTTI I MAZZI" in h
altro = h.split("id='d-altro'")[1].split("</section>")[0]
assert "Carte giocate" in altro and "Ultime partite" in altro and "Contro le leggendarie" in altro
sniper = h.split("id='d-sniper-lab'")[1]
assert "Versioni" in sniper and "LABORATORIO ·" not in sniper.split("</section>")[0][:400], "niente doppio titolo"
assert "data-games='1'" in h and "<script>" in h
store.save("decks", [])
assert "Ancora nessun mazzo salvato" in report.library_html().read_text(encoding="utf-8")
# STUDIO: pulsante nella scheda; con una partita in corso lo studio parte a fine partita
from origins import screen, usage, originsmeta as om  # noqa: E402
screen.RECORDINGS = tmp / "registrazioni"
rec = screen.RECORDINGS / "20261017-140000"
rec.mkdir(parents=True)
(rec / "0001_x.png").write_bytes(b"x")
assert "data-api='study_recordings'" in report.studio_body() and "1 registrazione da studiare" in report.studio_body()
started = []
c._run_study = lambda n: started.append(n)
c._match_active = True
c.study_recordings()
assert c._study_after_match and not started, "in partita: aspetta la fine"
c._match_active = False
c.study_recordings()
time.sleep(0.2)
assert started == [1]
(rec / "ELABORATA").write_text("2026-10-17 14:30\nfatto", encoding="utf-8")
assert "Nessuna registrazione da studiare" in report.studio_body()

# consumi: solo con chiave API, somma la differenza tra i totali di Claude Code
class _S:  # finta sessione
    pass
fs = _S()
fs.proc = _S(); fs.proc.pid = 1
usage.add_from_result({"total_cost_usd": 0.30}, fs)
usage.add_from_result({"total_cost_usd": 0.35}, fs)
assert usage.summary()["oggi"] == 0.35
fs.proc.pid = 2  # processo nuovo: il totale riparte
usage.add_from_result({"total_cost_usd": 0.10}, fs)
assert usage.summary()["oggi"] == 0.45
cfg = store.load("config"); cfg["connessione"] = "abbonamento"; store.save("config", cfg)
assert not usage.visible()
cfg["connessione"], cfg["api_key"] = "api", "sk-ant-x"; store.save("config", cfg)
assert usage.visible()
c.emit_state()
assert [e for e in ui.ev if e["type"] == "state"][-1]["consumi"]["oggi"] == 0.45
cfg["connessione"] = "abbonamento"; store.save("config", cfg)

# ORIGIN: pagina dei mazzi meta e collegamento solo verso originsmeta.com
store.save("originsmeta", {"ultimo_sync": "2026-10-17 09:00", "mazzi": {"https://originsmeta.com/en/decks/community/sniper-e4a2": {
    "nome": "SNIPER", "url": "https://originsmeta.com/en/decks/community/sniper-e4a2", "leggendaria": "Robin Hood",
    "archetipo": "Midrange", "versione": "0.7", "winrate": 88, "partite": 16, "carte": DECK, "completo": True,
    "guida": "## Mulligan\n- Tieni le carte da 2", "autore": "robip"}}, "statistiche": {}})
mh = report.meta_html().read_text(encoding="utf-8")
assert "ORIGIN · MAZZI META" in mh and "SNIPER" in mh and "data-api='open_site'" in mh and "VAI SU ORIGINSMETA.COM" in mh
assert "<li>Tieni le carte da 2</li>" in mh and "data-filter='leg'" in mh
import webbrowser as _wb  # noqa: E402
opened_urls = []
_wb.open = lambda u: opened_urls.append(u)
c.open_site("https://originsmeta.com/it")
c.open_site("https://example.com/phish")
assert opened_urls == ["https://originsmeta.com/it"], "si apre solo il sito di OriginsMeta"
ui.ev.clear()
c.open_origin()
assert opened[-1].startswith("<!doctype html") and "SNIPER" in opened[-1]

# tutorial: alla prima apertura sì, dopo «ho capito» no
c.emit_state()
assert [e for e in ui.ev if e["type"] == "state"][-1]["tutorial"] is True
c.tutorial_done()
c.emit_state()
assert [e for e in ui.ev if e["type"] == "state"][-1]["tutorial"] is False

# creare un mazzo: sessione a parte senza tetto al ragionamento; il limite dei 40 s solo in partita
lab_s = controller.ClaudeSession("claude", ROOT, live=False)
live_s = controller.ClaudeSession("claude", ROOT)
cfg = store.load("config"); cfg["max_thinking_live"] = 4000; store.save("config", cfg)
assert "MAX_THINKING_TOKENS" not in lab_s._env() and live_s._env()["MAX_THINKING_TOKENS"] == "4000"
# due progetti: se ne crei un altro e poi torni a giocare il primo, le partite vanno al progetto del mazzo scelto e il
# pannello lo segue; dal pannello si può anche cambiare a mano
v_prima = deckproj.current(deckproj.get("Sniper Lab"))["v"]
r2 = json.loads(call("deck_project_start", nome="Secondo Lab", leggendaria="Robin Hood", carte=DECK))
assert r2.get("creato") == "Secondo Lab" and deckproj.active()["nome"] == "Secondo Lab"
names = [x["nome"] for x in deckproj.summary()["progetti"]]
assert "Sniper Lab" in names and "Secondo Lab" in names, names
_sp = deckproj.current(deckproj.get("Sniper Lab"))
store.save_deck("Sniper Lab", _sp["leggendaria"], _sp["carte"])  # (un test più su ha riscritto l'elenco dei mazzi)
call("start_match", my_deck="Sniper Lab", opponent_legendary="Dracula")
assert store.load("match")["progetto"] == "Sniper Lab" and store.load("match")["versione"] == v_prima
assert deckproj.active()["nome"] == "Sniper Lab", "il pannello segue il mazzo che stai giocando"
c.lab_select("Secondo Lab")
assert deckproj.active()["nome"] == "Secondo Lab"
call("start_match", my_deck="Secondo Lab", opponent_legendary="Dracula")
assert store.load("match")["versione"] == 1
c.stop()

shutil.rmtree(tmp, ignore_errors=True)
print("LABORATORIO OK")
