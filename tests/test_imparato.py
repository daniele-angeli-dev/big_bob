"""Pagina "Cosa ho imparato": python tests/test_imparato.py (nessuna rete, dati finti)."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import report, screen  # noqa: E402

report.LOGS = tmp / "logs"
screen.RECORDINGS = tmp / "registrazioni"

# due partite: nella prima impara, nella seconda niente
store.save("matches", [
    {"inizio": "2026-10-16 18:00", "fine": "2026-10-16 18:09", "mio_mazzo": "Sniper", "avv_leggendaria": "Dracula",
     "risultato": "vittoria", "note_finali": "Chiusa la destra al round 6"},
    {"inizio": "2026-10-16 18:30", "fine": "2026-10-16 18:38", "mio_mazzo": "Sniper", "avv_leggendaria": "Merlin",
     "risultato": "sconfitta"},
])
store.save("lessons", [
    {"id": "L001", "tipo": "mossa_avversaria", "lezione": "Se Dracula ha 3+ mana aspettati Brides al centro",
     "carte": ["Brides of Dracula"], "stato": "confermata", "volte": 2, "creata": "2026-10-16 18:04",
     "prove": [{"data": "2026-10-16 18:04", "fonte": "partita", "accaduto": "Brides al centro", "perche": "barrier bassa"},
               {"data": "2026-10-16 18:12", "fonte": "partita", "accaduto": "di nuovo", "perche": ""}],
     "ultima": "2026-10-16 18:12"},
    {"id": "L002", "tipo": "interazione", "lezione": "Defender para anche lo Snipe",
     "carte": ["Marian"], "stato": "ipotesi", "volte": 1, "creata": "2026-10-16 20:55",
     "prove": [{"data": "2026-10-16 20:55", "fonte": "osservazione 20261016-200000", "accaduto": "", "perche": ""}]},
    {"id": "L003", "tipo": "strategia", "lezione": "Vecchia idea sbagliata", "carte": [], "stato": "smentita",
     "volte": 1, "creata": "2026-10-15 10:00", "ultima": "2026-10-15 11:00",
     "prove": [{"data": "2026-10-15 10:00", "fonte": "Daniele"}]},
])
store.save("rules", [
    {"id": "R001", "categoria": "vittoria", "testo": "Vince chi distrugge 2 barrier", "stato": "confermata",
     "fonti": ["Daniele"], "prove": []},
    {"id": "R020", "categoria": "corsie", "testo": "Ogni corsia ha 3 slot per lato", "stato": "probabile",
     "fonti": ["osservazione 20261016-200000"], "creata": "2026-10-16 20:56",
     "prove": [{"data": "2026-10-16 20:56", "fonte": "osservazione 20261016-200000", "nota": "fotogramma 0042"}]},
    {"id": "R021", "categoria": "corsie", "testo": "Quanti spazi ha ogni corsia?", "stato": "domanda", "fonti": [],
     "prove": []},
])
store.save("cards", [
    {"id": "nuova", "nome": "Carta Nuova", "testo": "On Reveal: pesca", "aggiunta": "2026-10-16 18:05",
     "fonte": ""},
    {"id": "roo", "nome": "Roo", "aggiunta": "2026-10-16 17:10", "fonte": "originsmeta",
     "storico": [{"patch": "0.7 (OriginsMeta)", "data": "2026-10-16 17:10",
                  "modifiche": [{"campo": "costo", "prima": 3, "dopo": 2}]}]},
    {"id": "mummy", "nome": "Mummy", "aggiunta": "2026-10-16 17:10", "fonte": "originsmeta"},
])
# una registrazione studiata e una ancora da studiare
done = screen.RECORDINGS / "20261016-200000"
done.mkdir(parents=True)
(done / "0001_x.png").write_bytes(b"")
(done / "ELABORATA").write_text("2026-10-16 20:58\nScoperti gli slot per corsia; Defender e Snipe.", encoding="utf-8")
todo = screen.RECORDINGS / "20261016-213000"
todo.mkdir()
(todo / "0001_x.png").write_bytes(b"")

out = report.learned_html()
h = out.read_text(encoding="utf-8")
sec = [x.split("</section>")[0] for x in h.split("<section class='sess")]
by = {s.split("<h3>")[1].split("<small>")[0]: s for s in sec[1:]}
m1 = next(v for k, v in by.items() if "Dracula" in k)
m2 = next(v for k, v in by.items() if "Merlin" in k)
rec = next(v for k, v in by.items() if "20261016-200000" in k)
rec2 = next(v for k, v in by.items() if "20261016-213000" in k)
assert "NUOVA LEZIONE" in m1 and "CONFERMATA" in m1 and "Brides" in m1, m1
assert "CARTA NUOVA" in m1 and "Carta Nuova" in m1, "la carta letta dallo schermo durante la partita"
assert "1 lezione nuova" in m1 and "Chiusa la destra" in m1
assert "Niente di nuovo" in m2, "una partita senza sorprese lo dice"
assert "Defender para anche lo Snipe" in rec and "slot per lato" in rec and "Scoperti gli slot" in rec, rec
assert "Non ancora studiata" in rec2 and "/impara-regole" in rec2
assert "importate da OriginsMeta" in h and "costo 3→2" in h, "aggiornamenti dal sito in un blocco a parte"
assert "Brides" not in by.get("Studio e aggiornamenti", ""), "le lezioni della partita non finiscono tra gli altri"
assert "SMENTITA" in h and "Vecchia idea" in h
assert h.index("20261016-213000") < h.index("Merlin") < h.index("Dracula"), "dal più recente"
assert "Quanti spazi" in h and "DOMANDE APERTE" in h
assert "class='sess first'><h3>Registrazione 20261016-213000" in h, "in cima la cosa più recente"
assert "1 lezione nuova · 1 sul regolamento" in rec, rec
assert rec.count("Ogni corsia ha 3 slot") == 1, "regola nuova mostrata una volta sola"
old_day = h.split("2026-10-15")[1]
assert "1 lezione nuova · 1 smentita" in old_day

# database vuoto: la pagina si genera e invita a giocare
for k in ("matches", "lessons", "rules", "cards"):
    store.FILES[k].unlink()
shutil.rmtree(screen.RECORDINGS)
store.FILES["rules"] = tmp / "vuoto_rules.json"
h = report.learned_html().read_text(encoding="utf-8")
assert "COSA HO IMPARATO" in h

shutil.rmtree(tmp, ignore_errors=True)
print("IMPARATO OK")
