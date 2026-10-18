"""Cervello comune (lato BIG-BOB): python tests/test_cervello.py
Dati temporanei e server finto (nessuna rete). Con BIGBOB_CERVELLO_URL=http://127.0.0.1:8787 prova anche un server
vero (es. `npx wrangler dev` in cloud/)."""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

os.environ["BIGBOB_NO_SYNC"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import cervello, lessons, report, rules  # noqa: E402
from origins import server as srv  # noqa: E402

report.LOGS = tmp / "logs"
cervello.DEFAULT_URL = ""  # il test non deve mai toccare il server vero
FAILED = []


def check(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        FAILED.append(msg)


def call(name, **kw):
    res = asyncio.run(srv.mcp.call_tool(name, kw))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


class Resp(io.BytesIO):
    def __init__(self, data, headers=None, gz=False):
        import gzip
        raw = json.dumps(data).encode()
        super().__init__(gzip.compress(raw) if gz else raw)
        self.headers = {**(headers or {}), **({"content-encoding": "gzip"} if gz else {})}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeServer:
    """Risponde come il Worker: registra i contributi e restituisce la conoscenza preparata."""

    def __init__(self, know):
        self.know, self.posts, self.gets, self.etag = know, [], 0, '"v1"'

    def open(self, req, timeout=None):
        if req.get_method() == "POST":
            body = json.loads(req.data)
            self.posts.append(body)
            # Cloudflare comprime anche le risposte alle POST (accept-encoding: gzip)
            return Resp({"ok": True, "ricevuti": {k: len(body.get(k, [])) for k in ("regole", "lezioni")}}, gz=True)
        self.gets += 1
        if req.get_header("If-none-match") == self.etag:
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        return Resp(self.know, {"etag": self.etag})


# ------------------------------------------------------------------ dati locali
store.upsert("cards", [
    {"nome": "Marian", "costo": 3, "attacco": 2, "vita": 4, "testo": "testo dal sito", "fonte": "originsmeta"},
    {"nome": "Little John", "costo": 4, "attacco": 4, "vita": 5, "testo": "On Reveal: verificato da me"},
    {"nome": "Garlic", "costo": 2, "testo": "dal sito", "fonte": "originsmeta"},
], "0.7")
rules.load()  # crea il regolamento di base

print("1. spento finché non c'è l'indirizzo")
check(not cervello.enabled(), "senza indirizzo è spento")
check(cervello.sync(force=True).get("saltato"), "sync saltato")
check(len(cervello.load_state()["install"]) == 32, "codice anonimo generato")

print("2. cosa si invia")
cfg = store.load("config")
cfg["cervello_url"] = "http://finto"
store.save("config", cfg)
p = cervello.pending()
check(p["regole"] == [], "le regole di base invariate non si inviano")
rules.upsert(testo="Ogni corsia ha 3 slot per lato", categoria="corsie", stato="confermata", fonte="Daniele",
             prova="visto da Daniele al round 2, vedi C:\\Users\\dani\\foto.png")
rules.upsert(id="R009", testo="Se entrambi arrivano a 2 barrier nello stesso round è pareggio", stato="probabile",
             fonte="partita", prova="partita del 12/10")
lessons.record("Daniele ha visto che Dracula con 3 mana gioca Brides al centro", "mossa_avversaria",
               ["Brides of Dracula"], fonte="partita")
store.save("matches", [{"inizio": "2026-10-16 20:00", "fine": "2026-10-16 20:07", "leggendaria_mia": "Robin Hood",
                        "carte_mie": ["Marian"] * 2, "avv_leggendaria": "Dracula", "avv_giocati": ["Garlic", "Bat"],
                        "avv_scartati": ["Spellbook page"], "avv_creati": ["Spellbook page"], "turno": 7,
                        "risultato": "vittoria"},
                       {"inizio": "2026-10-16 21:00", "leggendaria_mia": "Robin Hood", "risultato": ""}])
rules.upsert(testo="Shield blocca il primo danno subito", categoria="parole chiave", stato="confermata",
             fonte="cervello comune")
lessons.record("Contro Dracula tieni Garlic per il round 5", "mossa_avversaria", ["Garlic"], fonte="cervello comune")
lessons.record("Conviene tenere sempre Garlic in mano", "strategia", ["Garlic"], fonte="Daniele (opinione)")
p = cervello.pending()
check(not any("tenere sempre Garlic" in x["testo"] for x in p["lezioni"]), "le opinioni non confermate restano locali")
check(len(p["regole"]) == 2, f"2 regole nuove o cambiate, non quella presa dal cervello ({len(p['regole'])})")
check(len(p["lezioni"]) == 1, "la lezione presa dal cervello comune non torna indietro come voto")
r = next(x for x in p["regole"] if "slot" in x["testo"])
check("Daniele" not in json.dumps(p, ensure_ascii=False), "il nome del giocatore non viene inviato")
check("Users" not in r["prove"][0], f"percorsi tolti dalle prove: {r['prove']}")
check([c["nome"] for c in p["carte"]] == ["Little John"], "solo le carte verificate sullo schermo")
check(len(p["partite"]) == 1 and p["partite"][0]["avv_carte"] == ["Bat", "Garlic"],
      f"partite finite, senza le carte create: {p['partite']}")

print("3. invio e reinvio")
fake = FakeServer({})
out = cervello.send(opener=fake)
check(out.get("inviati", {}).get("regole") == 2 and len(fake.posts) == 1, f"inviato: {out}")
check(fake.posts[0]["install"] == cervello.load_state()["install"], "con il codice anonimo")
check(cervello.send(opener=fake).get("niente_di_nuovo"), "niente di nuovo al secondo invio")
rules.upsert(id="R027", stato="probabile")
out = cervello.send(opener=fake)
check(out["inviati"]["regole"] == 1 and len(fake.posts[-1]["regole"]) == 1, "solo la regola cambiata")
cfg = store.load("config")
cfg["cervello_contribuisci"] = False
store.save("config", cfg)
rules.upsert(id="R027", stato="confermata")
check(cervello.send(opener=fake).get("saltato"), "contributi spenti: non invia")
cfg["cervello_contribuisci"] = True
store.save("config", cfg)

print("4. ricezione e unione")
KNOW = {
    "api": 1, "creato": "2026-10-17T10:00:00Z", "giocatori": 5, "soglia_conferma": 2, "partite": 40,
    "regole": [
        {"id": "C1", "categoria": "corsie", "testo": "Ogni corsia ha 3 slot per lato", "stato": "confermata",
         "giocatori": 4, "conferme": 4, "smentite": 0, "prove": []},
        {"id": "C2", "categoria": "parole chiave", "testo": "Shield blocca il primo danno subito", "stato": "confermata",
         "giocatori": 3, "conferme": 3, "smentite": 0, "prove": ["round 4"]},
    ],
    "lezioni": [
        {"id": "CL1", "tipo": "mossa_avversaria", "testo": "Contro Dracula tieni Garlic per il round 5", "carte": ["Garlic"],
         "stato": "confermata", "sostengono": 3, "giocatori": 3, "volte": 6},
        {"id": "CL2", "tipo": "mossa_avversaria", "testo": "Il giocatore ha visto che Dracula con 3 mana gioca Brides al centro",
         "carte": ["Brides of Dracula"], "stato": "confermata", "sostengono": 2, "giocatori": 2, "volte": 3},
        {"id": "CL3", "tipo": "strategia", "testo": "Lezione sbagliata", "carte": [], "stato": "smentita",
         "sostengono": 0, "giocatori": 2, "volte": 0},
    ],
    "carte": [
        {"chiave": "marian", "nome": "Marian", "giocatori": 3,
         "campi": {"testo": {"valore": "On Reveal: +2 vita a una creatura", "giocatori": 3, "concorde": True}}},
        {"chiave": "little-john", "nome": "Little John", "giocatori": 2,
         "campi": {"testo": {"valore": "altro testo", "giocatori": 2, "concorde": True}}},
        {"chiave": "garlic", "nome": "Garlic", "giocatori": 1,
         "campi": {"testo": {"valore": "uno solo", "giocatori": 1, "concorde": False}}},
        {"chiave": "bat", "nome": "Bat", "giocatori": 2,
         "campi": {"testo": {"valore": "Flying", "giocatori": 2, "concorde": True},
                   "costo": {"valore": 1, "giocatori": 2, "concorde": True}}},
    ],
    "location": [],
    "mazzi_avversari": [{"leggendaria": "Dracula", "partite": 30, "giocatori": 4, "winrate_contro": 45,
                         "carte": [{"nome": n, "freq": f} for n, f in
                                   [("Garlic", 0.9), ("Bat", 0.8), ("Brides of Dracula", 0.7), ("Renfield", 0.5),
                                    ("Rara", 0.1)]]}],
    "leggendarie": [{"leggendaria": "Robin Hood", "partite": 20, "giocatori": 3, "winrate": 55}],
    "matchup": [{"mia": "Robin Hood", "avv": "Dracula", "partite": 8, "winrate": 50}],
}
fake = FakeServer(KNOW)
out = cervello.download(opener=fake)
check(out.get("scaricato") and out["carte_aggiornate"] == 1 and out["carte_aggiunte"] == 1, f"scaricato: {out}")
cards = {c["nome"]: c for c in store.load("cards")}
check(cards["Marian"]["testo"].startswith("On Reveal: +2") and cards["Marian"]["fonte"] == "cervello",
      "testo di Marian (preso dal sito) corretto dal cervello")
check(cards["Little John"]["testo"] == "On Reveal: verificato da me", "la carta verificata da me non si tocca")
check(cards["Garlic"]["testo"] == "dal sito", "un solo giocatore non basta")
check(cards["Bat"]["costo"] == 1, "carta mancante aggiunta")
meta = [a for a in store.load("meta") if a.get("fonte") == "cervello"]
check(len(meta) == 1 and "Rara" not in meta[0]["carte"] and len(meta[0]["carte"]) == 4, f"mazzo avversario nel meta: {meta}")
cervello.download(opener=fake)
check(len([a for a in store.load("meta") if a.get("fonte") == "cervello"]) == 1, "nessun doppione nel meta")
out = cervello.download(opener=fake)
check(out.get("invariato"), "304: niente da riscaricare")

print("5. Claude li vede")
rg = json.loads(call("rules_get"))
mine = next(r for r in rg if r["id"] == "R027")
check(mine.get("cervello_comune", {}).get("id") == "C1", "la mia regola è annotata con il cervello comune")
check(not any(r["id"] == "C2" for r in rg), "C2 l'ho già (adottata): non si ripete")
check(not any(r["id"] == "C1" for r in rg), "niente doppioni")
lg = json.loads(call("lessons_get"))
ids = [x["id"] for x in lg]
check("CL2" not in ids and "CL3" not in ids and "CL1" not in ids, f"lezioni comuni senza doppioni (anche CL1, adottata) e smentite: {ids}")
check("C2" not in [r["id"] for r in json.loads(call("rules_get"))], "regola già adottata: niente doppione")
lessons.review("L002", elimina=True)
summ = srv._lessons_summary({"avv_giocati": ["Garlic"], "mia_mano": [], "avv_leggendaria": "Dracula"})
check("🌐CL1" in summ, "in partita le lezioni comuni arrivano con update_match")
cc = json.loads(call("cervello_comune"))
check(cc["giocatori"] == 5 and cc["matchup"][0]["winrate"] == 50, "strumento cervello_comune")
html = report.brain_body()
check("Cervello comune" in html and "Contro Dracula" in html, "pagina Studio: sezione cervello comune")
cfg = store.load("config")
cfg["cervello_usa"] = False
store.save("config", cfg)
check(cervello.knowledge() == {} and "spento" in report.brain_body(), "uso spento: niente conoscenza comune")
cfg["cervello_usa"] = True
store.save("config", cfg)

print("5b. un errore nell'invio non blocca la ricezione, e l'esito resta scritto")
_orig_send = cervello.send
cervello.send = lambda opener=None: (_ for _ in ()).throw(ValueError("dati strani"))
out = cervello.sync(force=True, opener=FakeServer(KNOW))
cervello.send = _orig_send
check("dati strani" in out["invio"]["errore"] and ("scaricato" in out["ricezione"] or "invariato" in out["ricezione"]),
      f"ricezione fatta lo stesso: {out}")
st = cervello.status()
check(st["ultimo_esito"]["ok"] is False and "dati strani" in st["ultimo_esito"]["errore"], "esito salvato")
check("problema" in cervello.summary_line() or "dati strani" in cervello.summary_line(out), "e mostrato nella riga")

class Down:
    def open(self, req, timeout=None):
        raise urllib.error.URLError("timed out")
out = cervello.sync(force=True, opener=Down())
check(out["invio"].get("errore") and out["ricezione"].get("errore") and "timed out" in cervello.summary_line(out),
      f"server irraggiungibile: errore chiaro ({cervello.summary_line(out)})")

print("5c. scarico incrementale, patch, conferme incrociate, contrasti")
old_k = {"creato": "2026-10-01T00:00:00Z", "regole": [{"id": "C1", "testo": "a"}, {"id": "C2", "testo": "b"}],
         "lezioni": [{"id": "CL1", "testo": "x"}], "carte": [{"chiave": "marian"}], "location": [], "giocatori": 2}
delta = {"delta": True, "creato": "2026-10-02T00:00:00Z", "giocatori": 3,
         "ids": {"regole": ["C1"], "lezioni": ["CL1", "CL2"], "carte": ["marian"], "location": []},
         "regole": [], "lezioni": [{"id": "CL2", "testo": "nuova"}, {"id": "CL1", "testo": "x2"}], "carte": [],
         "location": []}
mk = cervello.merge_delta(old_k, delta)
check([r["id"] for r in mk["regole"]] == ["C1"] and [x["testo"] for x in mk["lezioni"]] == ["x2", "nuova"]
      and mk["giocatori"] == 3 and "delta" not in mk and mk["carte"] == [{"chiave": "marian"}], f"delta: {mk}")
store.upsert("cards", [{"nome": "Garlic", "costo": 2, "attacco": 1, "vita": 3}], "0.7")
store.upsert("cards", [{"nome": "Garlic", "costo": 3}], "0.8")  # cambiata in una patch dopo
check(cervello._stale({"carte": ["Garlic"], "agg": "2026-01-01T00:00:00Z"}), "voce votata prima che la carta cambiasse")
check(not cervello._stale({"carte": ["Garlic"], "agg": "2099-01-01T00:00:00Z"}), "voce votata dopo: valida")
cfg = store.load("config")
cfg["patch_corrente"] = "0.8"
store.save("config", cfg)
check(cervello._patch_weight({"patch": "0.7"}) < 1 and cervello._patch_weight({"patch": "0.8"}) == 1, "peso per patch")
store.save("lessons", [{"id": "L050", "tipo": "mossa_avversaria", "lezione": "Se Dracula ha 3 mana aspettati Brides al centro",
                        "carte": ["Brides of Dracula"], "stato": "ipotesi", "volte": 1, "prove": [{"fonte": "partita R3"}]}])
kn = {"lezioni": [{"id": "CL9", "tipo": "mossa_avversaria", "testo": "Se Dracula ha 3 mana aspettati Brides al centro",
                   "carte": ["Brides of Dracula"], "stato": "confermata", "sostengono": 3}], "regole": []}
cc = cervello.cross_confirm(kn)
l50 = lessons.load()[0]
check(cc["lezioni"] == ["L050"] and l50["stato"] == "confermata" and l50["confermata_da_cervello"] == "CL9",
      f"conferma incrociata: {cc}")
pl = [x for x in cervello._lessons_payload() if x["cid"] == "L050"]
check(pl and pl[0]["stato"] == "ipotesi", "al server va il tuo voto (ipotesi), non quello degli altri: niente eco")

check(not cervello.same_polarity("Il danno in eccesso passa alla barrier", "Il danno in eccesso non passa alla barrier")
      and cervello.same_polarity("Defender difende sempre", "Defender difende sempre e più volte"), "negazioni")
store.upsert("cards", [{"nome": "Bat", "costo": 1, "attacco": 1, "vita": 1}], "0.8")
store.upsert("cards", [{"nome": "Bat", "costo": 2}], "0.9")
check(cervello._stale({"carte": ["Bat"], "voto": "2000-01-01T00:00:00.000Z"})
      and not cervello._stale({"carte": ["Bat"], "voto": "2999-01-01T00:00:00.000Z"}), "date UTC e locali confrontate bene")

print("6. stesso testo, stesse regole di unione del server")
check(cervello.tokens("Una barrier a 0 si rigenera a 40 e il danno in eccesso non passa") ==
      ["0", "40", "barrier", "danno", "eccesso", "passa", "rigenera"], "tokens come merge.js")
check(cervello.rule_score("Una barrier a 0 si rigenera a 40", "Una barrier a 0 si rigenera a 20") == 0,
      "numeri diversi = regole diverse")

srv_url = os.environ.get("BIGBOB_CERVELLO_URL")
if srv_url:
    print("7. server vero:", srv_url)
    cfg = store.load("config")
    cfg["cervello_url"] = srv_url
    store.save("config", cfg)
    st = cervello.load_state()
    st["inviati"] = {}
    st.pop("etag", None)
    cervello._save_json(cervello.STATE_FILE, st)
    out = cervello.sync(force=True, opener=__import__("urllib.request").request.build_opener(
        __import__("urllib.request").request.ProxyHandler({})))
    check("errore" not in out["invio"] and out["invio"]["inviati"]["regole"] >= 2, f"invio: {out['invio']}")
    check(out["ricezione"].get("scaricato") or out["ricezione"].get("invariato"), f"ricezione: {out['ricezione']}")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFALLITI:", len(FAILED))
sys.exit(1 if FAILED else 0)
