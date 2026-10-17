"""Collaudo del cervello comune su un server vero (locale con `npx wrangler dev`, o pubblicato).

    python cloud/test/collaudo.py http://127.0.0.1:8787 <ADMIN_KEY>

Simula tre giocatori, controlla che le regole si uniscano, che il consenso funzioni e che l'amministrazione risponda.
Da usare solo su un database di prova: scrive dati finti.
"""
from __future__ import annotations

import json
import secrets
import sys
import urllib.error
import urllib.request

URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8787"
ADMIN = sys.argv[2] if len(sys.argv) > 2 else ""
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, admin=False, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"content-type": "application/json", "user-agent": "BIG-BOB collaudo"})
    if admin:
        req.add_header("authorization", "Bearer " + ADMIN)
    try:
        with NOPROXY.open(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def ok(cond, msg):
    print(("  ok  " if cond else "  NO  ") + msg)
    if not cond:
        ok.failed += 1


ok.failed = 0
players = [secrets.token_hex(16) for _ in range(3)]

print("1. tre giocatori inviano")
s, r = call("/v1/contributi", {"install": players[0], "versione": "test", "regole": [
    {"cid": "R027", "categoria": "corsie", "testo": "Ogni corsia ha 3 slot per lato", "stato": "confermata",
     "prove": ["round 2: 3 creature affiancate"]},
    {"cid": "R028", "categoria": "parole chiave", "testo": "Shield blocca il primo danno subito", "stato": "ipotesi"},
], "lezioni": [
    {"cid": "L001", "tipo": "mossa_avversaria", "testo": "Se Dracula ha 3+ mana aspettati Brides al centro",
     "carte": ["Brides of Dracula"], "stato": "ipotesi", "volte": 1},
], "carte": [{"nome": "Marian", "testo": "On Reveal: give +2 health", "costo": 3}],
    "partite": [{"cid": "m1", "risultato": "vittoria", "mia_leggendaria": "Robin Hood", "avv_leggendaria": "Dracula",
                 "avv_carte": ["Garlic", "Bat"], "round": 7}]})
ok(s == 200 and r["ricevuti"]["regole"] == 2, f"giocatore 1 → {s} {r}")
s, r = call("/v1/contributi", {"install": players[1], "regole": [
    {"cid": "R030", "categoria": "corsie", "testo": "Ogni corsia ha 3 slot per lato (visto più volte)",
     "stato": "confermata"},
    {"cid": "R031", "categoria": "parole chiave", "testo": "Shield blocca il primo danno subito", "stato": "smentita"},
], "lezioni": [
    {"cid": "L004", "tipo": "mossa_avversaria", "testo": "Se Dracula ha 3+ mana aspettati Brides of Dracula al centro",
     "carte": ["Brides of Dracula", "Dracula"], "stato": "confermata", "volte": 2},
], "carte": [{"nome": "Marian", "testo": "On Reveal:  give +2 health", "costo": 3}],
    "partite": [{"cid": "m1", "risultato": "sconfitta", "mia_leggendaria": "Robin Hood", "avv_leggendaria": "Dracula",
                 "avv_carte": ["Garlic"]},
                {"cid": "m2", "risultato": "vittoria", "mia_leggendaria": "Robin Hood", "avv_leggendaria": "Dracula",
                 "avv_carte": ["Garlic", "Brides of Dracula"]}]})
ok(s == 200 and r["ricevuti"]["nuove_regole"] == 0, f"giocatore 2 si unisce alle regole esistenti → {r}")
ok(r["ricevuti"]["nuove_lezioni"] == 0, "la lezione simile si unisce")
s, r = call("/v1/contributi", {"install": players[2], "regole": [
    {"cid": "R027", "categoria": "parole chiave", "testo": "Shield blocca il primo danno", "stato": "smentita"}]})
ok(s == 200, f"giocatore 3 → {r}")

print("2. reinvio dello stesso giocatore: aggiorna il voto, non duplica")
s, r = call("/v1/contributi", {"install": players[0], "regole": [
    {"cid": "R028", "categoria": "parole chiave", "testo": "Shield blocca il primo danno subito", "stato": "smentita"}],
    "partite": [{"cid": "m1", "risultato": "vittoria", "mia_leggendaria": "Robin Hood", "avv_leggendaria": "Dracula"}]})
ok(s == 200, "reinvio accettato")

print("3. ricalcolo e conoscenza")
s, r = call("/v1/admin/ricalcola", {}, admin=True)
ok(s == 200, f"ricalcolo → {r}")
s, k = call("/v1/conoscenza")
ok(s == 200 and k["giocatori"] == 3, f"conoscenza: {k.get('giocatori')} giocatori")
slot = next((x for x in k["regole"] if "slot" in x["testo"]), None)
ok(slot and slot["stato"] == "confermata" and slot["giocatori"] == 2, f"regola slot confermata da 2: {slot}")
shield = next((x for x in k["regole"] if "Shield" in x["testo"]), None)
ok(shield and shield["stato"] == "smentita" and shield["smentite"] == 3, f"regola Shield smentita da 3: {shield}")
les = k["lezioni"][0] if k["lezioni"] else None
ok(les and les["stato"] == "confermata" and les["giocatori"] == 2 and les["volte"] == 3, f"lezione: {les}")
mar = next((x for x in k["carte"] if x["chiave"] == "marian"), None)
ok(mar and mar["campi"]["testo"]["concorde"], f"testo di Marian concorde: {mar}")
ok(k["partite"] == 3, f"partite senza doppioni: {k['partite']}")
dr = k["mazzi_avversari"][0] if k["mazzi_avversari"] else None
ok(dr and dr["leggendaria"] == "Dracula" and dr["carte"][0]["nome"] == "Garlic", f"mazzo Dracula: {dr}")

print("4. 304 se non è cambiato niente")
req = urllib.request.Request(URL + "/v1/conoscenza", headers={"if-none-match": f'"{k["creato"]}"'})
try:
    NOPROXY.open(req, timeout=10)
    ok(False, "doveva rispondere 304")
except urllib.error.HTTPError as e:
    ok(e.code == 304, f"304 → {e.code}")

print("5. sicurezza e limiti")
s, r = call("/v1/admin/panoramica")
ok(s == 401, "admin senza chiave: 401")
s, r = call("/v1/admin/panoramica", admin=True)
ok(s == 200 and len(r["contributori"]) == 3, "panoramica admin")
s, r = call("/v1/contributi", {"install": "non-valido"})
ok(s == 400, "install non valido: 400")
codes = [call("/v1/contributi", {"install": secrets.token_hex(16)})[0] for _ in range(3)]
ok(429 in codes, f"troppi giocatori nuovi dallo stesso indirizzo: {codes}")
s, r = call("/v1/contributi", {"install": players[0], "regole": [{}] * 301})
ok(s == 400, "troppi elementi: 400")

print("6. moderazione")
s, r = call("/v1/admin/nascondi", {"tipo": "carta", "chiave": "Marian", "motivo": "prova"}, admin=True)
ok(s == 200, "carta nascosta")
call("/v1/admin/regola", {"id": shield["id"], "nascosta": True}, admin=True)
hashes = [c["hash"] for c in call("/v1/admin/panoramica", admin=True)[1]["contributori"]]
s, r = call("/v1/admin/banna", {"contributore": hashes[-1]}, admin=True)
ok(s == 200 and r["modificati"] == 1, "giocatore bloccato")
call("/v1/admin/ricalcola", {}, admin=True)
k = call("/v1/conoscenza")[1]
ok(not any(x["chiave"] == "marian" for x in k["carte"]), "Marian non compare più")
ok(not any("Shield" in x["testo"] for x in k["regole"]), "regola nascosta non compare")
ok(k["giocatori"] == 2, f"il bloccato non conta: {k['giocatori']}")

print("\nFALLITI:", ok.failed)
sys.exit(1 if ok.failed else 0)
