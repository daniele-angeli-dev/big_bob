"""Cervello comune: ciò che imparano tutti i BIG-BOB, messo insieme su un server (Cloudflare Worker + D1, in cloud/).

Cosa si INVIA (solo se l'impostazione "Contribuisci" è attiva, in forma anonima):
  - le regole del regolamento ricostruito (testo, stato, fino a 3 prove), non quelle di base rimaste invariate;
  - le lezioni (testo, tipo, stato, carte, quante volte viste);
  - i testi di carte e location verificati sullo schermo (non quelli presi da OriginsMeta);
  - le partite finite: leggendarie, risultato, round, le tue 13 carte e le carte avversarie viste.
  Niente nomi, account, email, schermate o chiavi: chi invia è un codice casuale generato qui (data/cervello_stato.json)
  e il server ne salva solo un hash. Si invia solo ciò che è cambiato dall'ultimo invio.

Cosa si RICEVE (se "Usa la conoscenza comune" è attiva): regole e lezioni con quanti giocatori le hanno viste e
confermate, testi di carte concordi tra più giocatori, mazzi avversari più visti, winrate per leggendaria e matchup.
Resta separato in data/cervello.json: il tuo regolamento e le tue lezioni non vengono toccati. Le sole cose che si
uniscono ai tuoi dati sono i testi delle carte (solo su carte prese da OriginsMeta, mai su quelle verificate da te)
e i mazzi avversari nel meta (pesano nelle probabilità sulla mano avversaria).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from origins import store

# Indirizzo del server comune (pubblicato con pubblica_cervello.bat). Si può cambiare con "cervello_url" in config.json.
DEFAULT_URL = "https://bigbob-cervello.angeli-daniele01.workers.dev"
TIMEOUT = 15
SYNC_EVERY_HOURS = 3
FONTE = "cervello"
CAMPI_CARTA = ("nome", "testo", "costo", "attacco", "vita", "tipo", "rarita", "potere", "leggendaria",
               "potere_leggendario", "tag", "regola")
SOGLIA_REGOLE = 0.62
SOGLIA_LEZIONI = 0.6

STATE_FILE = "cervello_stato.json"
KNOW_FILE = "cervello.json"


# =========================================================================== configurazione e stato

def config() -> dict:
    cfg = store.load("config")
    return {"url": (cfg.get("cervello_url") or DEFAULT_URL).rstrip("/"),
            "contribuisci": cfg.get("cervello_contribuisci", True),
            "usa": cfg.get("cervello_usa", True)}


def enabled() -> bool:
    return bool(config()["url"])


def _path(name):
    return store.DATA / name


def _load_json(name, default):
    p = _path(name)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:  # noqa: BLE001
        return default


def _save_json(name, data) -> None:
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def load_state() -> dict:
    st = _load_json(STATE_FILE, {})
    if not re.fullmatch(r"[a-f0-9]{32}", st.get("install", "")):
        st["install"] = secrets.token_hex(16)
        _save_json(STATE_FILE, st)
    st.setdefault("inviati", {})
    return st


_KCACHE: dict = {}


def knowledge() -> dict:
    """L'ultima conoscenza comune scaricata ({} se non c'è o se l'uso è spento). Riletta solo quando il file cambia:
    update_match la consulta a ogni round."""
    if not config()["usa"]:
        return {}
    p = _path(KNOW_FILE)
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _KCACHE.get("key") != key:
        _KCACHE.clear()
        _KCACHE.update(key=key, data=_load_json(KNOW_FILE, {}))
    return _KCACHE["data"]


def _index() -> dict:
    """Indice delle lezioni comuni per carta (slug → posizioni), con i token già calcolati. Ricostruito solo quando
    cambia la conoscenza scaricata."""
    k = knowledge()
    if _KCACHE.get("idx_for") is k and "idx" in _KCACHE:
        return _KCACHE["idx"]
    by_card: dict[str, list[int]] = {}
    lez = k.get("lezioni") or []
    for i, x in enumerate(lez):
        for c in x.get("carte") or []:
            by_card.setdefault(store.slug(c), []).append(i)
    idx = {"by_card": by_card, "generali": [i for i, x in enumerate(lez) if not x.get("carte")]}
    _KCACHE.update(idx=idx, idx_for=k)
    return idx


# =========================================================================== testo (come cloud/src/merge.js)

STOP = set(("che per con non una uno del della delle dei degli dal dalla dai dalle nel nella nei nelle sul "
            "sulla sui sulle alla alle allo agli all gli the and for with from that this poi anche come quando sempre solo "
            "sono essere viene vengono piu suo sua suoi sue tuo tua tue tuoi mio mia miei mie quella quello quelle quelli "
            "questa questo queste questi ogni dopo prima cosa cui chi hai hanno essa esso loro").split())


def tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFD", str(text or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    out = {w for w in t.split() if w.isdigit() or (len(w) >= 3 and w not in STOP)}
    return sorted(out)


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _numbers(toks) -> str:
    return ",".join(sorted(w for w in toks if w.isdigit()))


def rule_score(a: str, b: str, same_category: bool = False) -> float:
    ta, tb = tokens(a), tokens(b)
    if _numbers(ta) != _numbers(tb):
        return 0.0
    return _jaccard(ta, tb) + (0.05 if same_category else 0)


def lesson_score(a: str, ca: list[str], b: str, cb: list[str]) -> float:
    sa, sb = {store.slug(c) for c in ca or []}, {store.slug(c) for c in cb or []}
    if sa and sb and not sa & sb:
        return 0.0
    overlap = len(sa & sb) / len(sa | sb) if (sa or sb) else 1.0
    ta, tb = tokens(a), tokens(b)
    if _numbers(ta) != _numbers(tb):
        return 0.0
    return 0.5 * overlap + 0.5 * _jaccard(ta, tb)


def anonymize(text: str, limit: int = 400) -> str:
    """Toglie nomi del giocatore, link ed email dai testi prima dell'invio."""
    t = str(text or "")
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", t)
    names = {"Daniele"} | {n.strip() for n in str(store.load("config").get("nome_giocatore") or "").split(",") if n.strip()}
    for n in names:
        t = re.sub(rf"\b{re.escape(n)}\b", "il giocatore", t, flags=re.I)
    t = re.sub(r"[A-Za-z]:\\[^\s]+|/home/[^\s]+|/Users/[^\s]+", "", t)  # percorsi di file
    return re.sub(r"\s+", " ", t).strip()[:limit]


# =========================================================================== cosa inviare

def _seed_unchanged(r: dict) -> bool:
    from origins import rules
    seeds = {f"R{i:03d}": (testo, stato) for i, (_c, testo, stato, _f) in enumerate(rules.SEED, 1)}
    s = seeds.get(r.get("id"))
    return bool(s) and r.get("testo") == s[0] and r.get("stato") == s[1] and not r.get("prove")


def _rules_payload() -> list[dict]:
    from origins import rules
    send_seeds = bool(store.load("config").get("cervello_regole_base"))  # solo per chi ha fatto l'intervista
    out = []
    for r in rules.load():
        if not send_seeds and _seed_unchanged(r):
            continue
        if _only_from_brain(r.get("fonti"), r.get("prove")):
            continue  # presa dal cervello comune senza prove tue: rimandarla sarebbe un voto falso
        prove = [anonymize(p.get("nota", ""), 300) for p in (r.get("prove") or [])[-3:] if p.get("nota")]
        rstato = r.get("stato") or "ipotesi"
        if rstato == "confermata" and r.get("confermata_da_cervello"):
            rstato = "probabile"  # confermata dagli altri, non da te
        out.append({"cid": r["id"], "categoria": r.get("categoria") or "altro", "testo": anonymize(r["testo"]),
                    "stato": rstato, "prove": [p for p in prove if p]})
    return out


def _only_from_brain(fonti, prove) -> bool:
    mine = [f for f in (fonti or []) if f and "cervello" not in str(f).lower()]
    mine += [p for p in (prove or []) if "cervello" not in str(p.get("fonte") or "").lower()]
    return not mine and bool(fonti or prove)


def _lessons_payload() -> list[dict]:
    from origins import lessons
    out = []
    for x in lessons.load():
        if not x.get("lezione") or _only_from_brain(None, x.get("prove")):
            continue
        prove = x.get("prove") or []
        if prove and all("opinion" in str(p.get("fonte") or "").lower() for p in prove) and x.get("stato") != "confermata":
            continue  # solo opinioni non ancora confermate da una partita: restano qui, non vanno a tutti
        volte = sum(1 for p in x.get("prove") or [] if "cervello" not in str(p.get("fonte") or "").lower())
        stato = x.get("stato") or "ipotesi"
        if stato == "confermata" and x.get("confermata_da_cervello"):
            stato = "ipotesi"  # confermata dagli altri, non da te: il tuo voto resta ipotesi (niente eco)
        out.append({"cid": x["id"], "tipo": x.get("tipo") or "strategia", "testo": anonymize(x.get("lezione", "")),
                    "stato": stato, "carte": list(x.get("carte") or [])[:12],
                    "volte": max(1, min(int(x.get("volte") or 1), volte or 1))})
    return out


def _cards_payload(kind: str) -> list[dict]:
    out = []
    for c in store.load(kind):
        if c.get("fonte") in ("originsmeta", FONTE):
            continue  # presa dal sito o dal cervello stesso: non è una verifica sullo schermo
        item = {k: c[k] for k in CAMPI_CARTA if c.get(k) not in (None, "", [])}
        if item.get("nome") and len(item) > 1:
            out.append(item)
    return out


def match_cid(m: dict) -> str:
    raw = f"{m.get('inizio')}|{m.get('leggendaria_mia')}|{m.get('avv_leggendaria')}|{m.get('fine')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _matches_payload() -> list[dict]:
    from origins import evaluate
    patch = store.load("config").get("patch_corrente", "")
    out = []
    for m in store.load("matches")[-200:]:
        res = (m.get("risultato") or "").lower()
        if not res[:1] in ("v", "s", "p"):
            continue
        out.append({"cid": match_cid(m), "data": (m.get("inizio") or "")[:10], "patch": m.get("patch") or patch,
                    "mia_leggendaria": m.get("leggendaria_mia") or "", "avv_leggendaria": m.get("avv_leggendaria") or "",
                    "risultato": res, "round": m.get("turno") or 0, "mie_carte": list(m.get("carte_mie") or [])[:13],
                    "avv_carte": sorted(evaluate.seen_opp(m))[:25]})
    return out


def _digest(item) -> str:
    return hashlib.sha1(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def pending(st: dict | None = None) -> dict:
    """Ciò che è nuovo o cambiato dall'ultimo invio, per tipo."""
    st = st or load_state()
    sent = st.get("inviati", {})
    groups = {"regole": _rules_payload(), "lezioni": _lessons_payload(), "carte": _cards_payload("cards"),
              "location": _cards_payload("locations"), "partite": _matches_payload()}
    out = {}
    for k, items in groups.items():
        fresh = []
        for it in items:
            key = f"{k}:{it.get('cid') or store.slug(it.get('nome', ''))}"
            if sent.get(key) != _digest(it):
                fresh.append(it)
        out[k] = fresh
    return out


# =========================================================================== rete

def _request(url: str, body: dict | None = None, headers: dict | None = None, opener=None):
    from origins import updates
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    h = {"content-type": "application/json", "user-agent": f"BIG-BOB/{updates.installed_version()}",
         "accept-encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    op = opener or urllib.request.build_opener()
    return op.open(req, timeout=TIMEOUT)


def _read(r) -> bytes:
    """Il corpo della risposta, decompresso se il server l'ha mandato con gzip (lo chiediamo noi con
    accept-encoding, e Cloudflare comprime anche le risposte alle POST)."""
    raw = r.read() or b""
    if (getattr(r, "headers", None) and (r.headers.get("content-encoding") or "").lower() == "gzip") \
            or raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw


LIMITI = {"regole": 300, "lezioni": 300, "carte": 400, "location": 120, "partite": 100}


def send(opener=None) -> dict:
    """Invia ciò che è cambiato. Restituisce {'inviati': {...}} o {'errore': ...}."""
    cfg = config()
    if not cfg["url"]:
        return {"saltato": "server non configurato"}
    if not cfg["contribuisci"]:
        return {"saltato": "contributi spenti"}
    from origins import updates
    st = load_state()
    todo = pending(st)
    if not any(todo.values()):
        return {"inviati": {}, "niente_di_nuovo": True}
    total = {k: 0 for k in todo}
    while any(todo.values()):
        chunk = {k: v[:LIMITI[k]] for k, v in todo.items()}
        todo = {k: v[LIMITI[k]:] for k, v in todo.items()}
        body = {"install": st["install"], "versione": updates.installed_version(),
                "patch": store.load("config").get("patch_corrente", ""), **chunk}
        try:
            with _request(cfg["url"] + "/v1/contributi", body, opener=opener) as r:
                json.loads(_read(r) or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(_read(e) or b"{}").get("errore") or str(e)
            except Exception:  # noqa: BLE001
                msg = str(e)
            _save_json(STATE_FILE, st)
            return {"errore": msg, "codice": e.code, "inviati": total}
        except Exception as e:  # noqa: BLE001
            _save_json(STATE_FILE, st)
            return {"errore": str(e), "inviati": total}
        for k, items in chunk.items():
            for it in items:
                st["inviati"][f"{k}:{it.get('cid') or store.slug(it.get('nome', ''))}"] = _digest(it)
            total[k] += len(items)
    st["ultimo_invio"] = store.now()
    _save_json(STATE_FILE, st)
    return {"inviati": total}


def download(opener=None) -> dict:
    cfg = config()
    if not cfg["url"]:
        return {"saltato": "server non configurato"}
    if not cfg["usa"]:
        return {"saltato": "uso spento"}
    st = load_state()
    have = _path(KNOW_FILE).exists()
    headers = {"if-none-match": st["etag"]} if st.get("etag") and have else {}
    old = _load_json(KNOW_FILE, {}) if have else {}
    url = cfg["url"] + "/v1/conoscenza"
    if old.get("creato"):  # solo ciò che è cambiato dall'ultimo scarico
        url += "?da=" + urllib.parse.quote(old["creato"])
    try:
        with _request(url, headers=headers, opener=opener) as r:
            data = json.loads(_read(r))
            etag = r.headers.get("etag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            st["ultimo_download"] = store.now()
            _save_json(STATE_FILE, st)
            return {"invariato": True, **apply()}
        return {"errore": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"errore": str(e)}
    if isinstance(data, dict) and data.get("delta"):
        data = merge_delta(old, data)
    if not isinstance(data, dict) or "regole" not in data:
        return {"errore": "risposta non valida"}
    _save_json(KNOW_FILE, data)
    st["etag"] = etag
    st["ultimo_download"] = store.now()
    _save_json(STATE_FILE, st)
    return {"scaricato": True, "giocatori": data.get("giocatori"), **apply(data)}


def merge_delta(old: dict, delta: dict) -> dict:
    """Applica uno scarico incrementale: le voci cambiate sostituiscono le vecchie, quelle non più presenti (in 'ids')
    spariscono, le statistiche arrivano sempre intere."""
    out = {k: v for k, v in delta.items() if k not in ("delta", "ids", "regole", "lezioni", "carte", "location")}
    ids = delta.get("ids") or {}
    for key, idk in (("regole", "id"), ("lezioni", "id"), ("carte", "chiave"), ("location", "chiave")):
        cur = {x.get(idk): x for x in old.get(key) or []}
        for x in delta.get(key) or []:
            cur[x.get(idk)] = x
        keep = ids.get(key)
        items = [cur[i] for i in keep if i in cur] if isinstance(keep, list) else list(cur.values())
        out[key] = items
    return out


def due() -> bool:
    st = _load_json(STATE_FILE, {})
    last = st.get("ultimo_sync_ts") or 0
    return time.time() - last > SYNC_EVERY_HOURS * 3600


def sync(force: bool = False, opener=None) -> dict:
    """Invia (se attivo) e poi scarica. Senza force, al massimo una volta ogni SYNC_EVERY_HOURS ore."""
    if not enabled():
        return {"saltato": "server non configurato"}
    if not force and not due():
        return {"saltato": "fatto da poco"}
    import logging
    log = logging.getLogger("bigbob")
    t0 = time.time()
    out = {}
    for key, fn in (("invio", send), ("ricezione", download)):  # un errore nell'invio non blocca la ricezione
        try:
            out[key] = fn(opener)
        except Exception as e:  # noqa: BLE001
            log.exception("cervello comune: %s", key)
            out[key] = {"errore": f"{type(e).__name__}: {e}"}
    out["secondi"] = round(time.time() - t0, 1)
    st = load_state()
    errs = [f"{k}: {v['errore']}" for k, v in out.items() if isinstance(v, dict) and v.get("errore")]
    st["ultimo_esito"] = {"quando": store.now(), "ok": not errs, "errore": "; ".join(errs)[:300] or None,
                          "secondi": out["secondi"]}
    if "errore" not in out["ricezione"]:
        st["ultimo_sync_ts"] = time.time()
    _save_json(STATE_FILE, st)
    return out


# =========================================================================== unione con i dati locali

def apply(data: dict | None = None) -> dict:
    """Unisce ai dati locali le sole cose sicure: testi di carte/location concordi e mazzi avversari nel meta."""
    data = data if data is not None else knowledge()
    if not data:
        return {"carte_aggiornate": 0, "carte_aggiunte": 0, "mazzi": 0}
    rep = {"carte_aggiornate": 0, "carte_aggiunte": 0, "mazzi": 0}
    for kind, key in (("cards", "carte"), ("locations", "location")):
        db = store.load(kind)
        by_id = {e.get("id") or store.slug(e.get("nome", "")): e for e in db}
        changed = False
        for c in data.get(key) or []:
            campi = {k: v["valore"] for k, v in (c.get("campi") or {}).items() if v.get("concorde")}
            if not campi or not c.get("nome"):
                continue
            cid = store.slug(c["nome"])
            old = by_id.get(cid)
            if old is None:
                new = {"id": cid, "nome": c["nome"], **{k: v for k, v in campi.items() if k in CAMPI_CARTA},
                       "fonte": FONTE, "aggiunta": store.now(),
                       "note": f"dal cervello comune ({c.get('giocatori')} giocatori)"}
                db.append(new)
                by_id[cid] = new
                rep["carte_aggiunte"] += 1
                changed = True
                continue
            if old.get("fonte") not in ("originsmeta", FONTE):
                continue  # verificata da te: vince la tua
            for f in ("testo", "regola"):
                if f in campi and campi[f] != old.get(f):
                    old.setdefault("storico", []).append({"data": store.now(), "patch": "cervello comune",
                                                          f: old.get(f)})
                    old[f] = campi[f]
                    old["fonte"] = FONTE
                    rep["carte_aggiornate"] += 1
                    changed = True
        if changed:
            store.save(kind, db)
    meta = [a for a in store.load("meta") if a.get("fonte") != FONTE]
    for d in data.get("mazzi_avversari") or []:
        carte = [c["nome"] for c in d.get("carte", []) if c.get("freq", 0) >= 0.3][:12]
        if len(carte) < 4:
            continue
        meta.append({"nome": f"{d['leggendaria']} (cervello comune)", "leggendaria": store.canonical(d["leggendaria"]),
                     "carte": [store.canonical(c) for c in carte], "volte_visto": 0, "vittorie_mie": 0,
                     "sconfitte_mie": 0, "community": round(min(3.0, 0.5 + d.get("partite", 0) / 15), 2),
                     "fonte": FONTE, "partite": d.get("partite"), "giocatori": d.get("giocatori"),
                     "winrate_contro": d.get("winrate_contro"), "completo": len(carte) == 12,
                     "ultimo": data.get("creato", "")[:16].replace("T", " "), "creato": store.now()})
        rep["mazzi"] += 1
    store.save("meta", meta)
    try:
        cc = cross_confirm(data)
        rep["confermate_incrociate"] = len(cc["lezioni"]) + len(cc["regole"])
    except Exception:  # noqa: BLE001
        rep["confermate_incrociate"] = 0
    return rep


# =========================================================================== letture per gli strumenti

def _label(x: dict) -> str:
    n = x.get("giocatori", 0)
    return f"{x.get('stato')} · {n} giocator{'e' if n == 1 else 'i'}"


def rules_view(local: list[dict]) -> tuple[dict, list[dict]]:
    """(annotazioni per id locale, regole comuni che non hai). Le regole comuni hanno id 'C…'."""
    k = knowledge()
    comm = k.get("regole") or []
    notes, used = {}, set()
    for r in local:
        best, score = None, 0.0
        for c in comm:
            s = rule_score(r.get("testo", ""), c.get("testo", ""), c.get("categoria") == r.get("categoria"))
            if s > score:
                best, score = c, s
        if best and score >= SOGLIA_REGOLE:
            notes[r["id"]] = {"id": best["id"], "stato": best["stato"], "giocatori": best.get("giocatori"),
                              "conferme": best.get("conferme"), "smentite": best.get("smentite")}
            used.add(best["id"])
    extra = [c for c in comm if c["id"] not in used]
    return notes, extra


def _when(text: str):
    """Data come istante assoluto: quelle del server sono in UTC ("…Z"), quelle locali sono ora del PC."""
    from datetime import datetime, timezone
    t = str(text or "").strip()
    if not t:
        return None
    try:
        if t.endswith("Z") or "+" in t[10:]:
            return datetime.fromisoformat(t.replace("Z", "+00:00"))
        return datetime.fromisoformat(t.replace(" ", "T")).astimezone(timezone.utc)
    except ValueError:
        return None


def _stale(item: dict) -> bool:
    """Una voce comune è superata se una sua carta è cambiata (statistiche o testo, in una patch) dopo l'ultimo voto."""
    agg = _when(item.get("voto") or item.get("agg"))  # "voto" = ultimo voto (server nuovo)
    if agg is None:
        return False
    for c in item.get("carte") or []:
        e = store.find("cards", c) or {}
        for h in e.get("storico") or []:
            when = _when(h.get("data"))
            if when and when > agg and str(h.get("patch") or "") not in ("cervello comune", ""):
                return True
    return False


NEG = {"non", "not", "no", "mai", "never", "nessun", "nessuna", "senza", "without", "cannot", "can't", "doesn't",
       "don't", "isn't"}


def _negated(text: str) -> bool:
    words = re.findall(r"[a-zà-ù']+", str(text or "").lower())
    return sum(1 for w in words if w in NEG) % 2 == 1


def same_polarity(a: str, b: str) -> bool:
    """Le parole simili non bastano: "il danno passa" e "il danno non passa" sono regole opposte."""
    return _negated(a) == _negated(b)


def _patch_weight(item: dict) -> float:
    """Peso per patch: una voce votata in una patch diversa da quella attuale conta meno."""
    cur = str(store.load("config").get("patch_corrente") or "")
    p = str(item.get("patch") or "")
    if not p or not cur:
        return 1.0
    return 1.0 if store.slug(p).startswith(store.slug(cur)) or store.slug(cur).startswith(store.slug(p)) else 0.6


def _covered(local: list[dict]) -> set:
    """Le lezioni comuni che hai già (calcolato una volta per versione delle due raccolte)."""
    k = knowledge()
    try:
        lm = store.FILES["lessons"].stat().st_mtime_ns
    except OSError:
        lm = None
    key = (id(k), lm, len(local))
    if _KCACHE.get("cov_key") == key:
        return _KCACHE["cov"]
    cov = set()
    for x in k.get("lezioni") or []:
        if any(lesson_score(x["testo"], x.get("carte", []), y.get("lezione", ""), y.get("carte", [])) >= SOGLIA_LEZIONI
               for y in local):
            cov.add(x["id"])
    _KCACHE.update(cov=cov, cov_key=key)
    return cov


def lessons_view(cards: list[str] | None = None, limit: int = 4, local: list[dict] | None = None) -> list[dict]:
    """Lezioni comuni utili: escluse le smentite, quelle che hai già e quelle superate da una patch (una carta è
    cambiata dopo i voti); le altre pesate per carte in comune, conferme, giocatori e patch."""
    from origins import lessons
    k = knowledge()
    lez = k.get("lezioni") or []
    local = local if local is not None else lessons.load()
    covered = _covered(local)
    if cards is not None:
        idx = _index()
        cs = {store.slug(c) for c in cards if c}
        hits: dict[int, int] = {}
        for c in cs:
            for i in idx["by_card"].get(c, []):
                hits[i] = hits.get(i, 0) + 1
        for i in idx["generali"]:
            if lez[i].get("tipo") == "strategia":
                hits.setdefault(i, 0)
        cand = [(hits[i], lez[i]) for i in hits]
    else:
        cand = [(0, x) for x in lez]
    scored = []
    for hit, x in cand:
        if x.get("stato") not in ("confermata", "ipotesi") or x["id"] in covered or _stale(x):
            continue
        sc = (hit * 2 + (3 if x["stato"] == "confermata" else 0) + min(x.get("sostengono", 1), 5)) * _patch_weight(x)
        scored.append((sc, x))
    scored.sort(key=lambda t: -t[0])
    return [x for _, x in scored[:limit]]


def contrasts() -> list[dict]:
    """Regole tue in contrasto con il cervello comune (tu confermata e gli altri smentita, o il contrario): da
    verificare con un esperimento contro il bot."""
    from origins import rules
    notes, _ = rules_view(rules.load())
    out = []
    for r in rules.load():
        n = notes.get(r["id"])
        if not n:
            continue
        mine, theirs = r.get("stato"), n.get("stato")
        if (mine == "confermata" and theirs == "smentita") or (mine == "smentita" and theirs == "confermata"):
            out.append({"id": r["id"], "testo": r.get("testo"), "tuo": mine, "comune": theirs,
                        "giocatori": n.get("giocatori"), "comune_id": n.get("id")})
    return out


def cross_confirm(data: dict | None = None) -> dict:
    """Conferme incrociate: una tua lezione o regola ancora ipotesi che il cervello comune ha confermato (2+ giocatori)
    diventa confermata, con la prova "cervello comune". Il voto che mandi al server resta il tuo (non si rimbalza)."""
    from origins import lessons, rules
    k = data if data is not None else knowledge()
    rep = {"lezioni": [], "regole": []}
    comm_l = [x for x in k.get("lezioni") or [] if x.get("stato") == "confermata" and (x.get("sostengono") or 0) >= 2]
    if comm_l:
        ls = lessons.load()
        changed = False
        for y in ls:
            if y.get("stato") != "ipotesi":
                continue
            for x in comm_l:
                if lesson_score(x["testo"], x.get("carte", []), y.get("lezione", ""), y.get("carte", [])) >= SOGLIA_LEZIONI \
                        and same_polarity(x["testo"], y.get("lezione", "")):
                    y["stato"] = "confermata"
                    y["confermata_da_cervello"] = x["id"]
                    y.setdefault("prove", []).append({"data": store.now(), "fonte": "cervello comune",
                                                      "situazione": f"{x['id']}: {x.get('sostengono')} giocatori"})
                    rep["lezioni"].append(y["id"])
                    changed = True
                    break
        if changed:
            lessons.save(ls)
    comm_r = [x for x in k.get("regole") or [] if x.get("stato") == "confermata" and (x.get("giocatori") or 0) >= 2]
    if comm_r:
        rs = rules.load()
        changed = False
        for r in rs:
            if r.get("stato") not in ("ipotesi", "probabile", "domanda"):
                continue
            for c in comm_r:
                if rule_score(r.get("testo", ""), c.get("testo", ""), c.get("categoria") == r.get("categoria")) >= SOGLIA_REGOLE \
                        and same_polarity(r.get("testo", ""), c.get("testo", "")):
                    r["stato"] = "confermata"
                    r["confermata_da_cervello"] = c["id"]
                    r.setdefault("fonti", []).append("cervello comune")
                    rep["regole"].append(r["id"])
                    changed = True
                    break
        if changed:
            rules.save(rs)
    return rep


def status() -> dict:
    cfg, st, k = config(), _load_json(STATE_FILE, {}), _load_json(KNOW_FILE, {})
    return {"attivo": bool(cfg["url"]), "contribuisci": cfg["contribuisci"], "usa": cfg["usa"],
            "ultimo_esito": st.get("ultimo_esito"),
            "giocatori": k.get("giocatori"), "regole": len(k.get("regole") or []),
            "lezioni": len(k.get("lezioni") or []), "partite": k.get("partite"),
            "aggiornato": (k.get("creato") or "")[:16].replace("T", " "), "ultimo_invio": st.get("ultimo_invio"),
            "ultimo_download": st.get("ultimo_download")}


def summary_line(rep: dict | None = None) -> str:
    s = status()
    if not s["attivo"]:
        return "Cervello comune non ancora configurato."
    esito = s.get("ultimo_esito") or {}
    if not s["giocatori"]:
        base = ("Cervello comune: ultima sincronizzazione non riuscita" if esito.get("errore") and not rep
                else "Cervello comune collegato: ancora nessun dato.")
    else:
        base = (f"Cervello comune: {s['giocatori']} giocatori · {s['regole']} regole · {s['lezioni']} lezioni · "
                f"{s['partite'] or 0} partite")
    if rep:
        inv = (rep.get("invio") or {}).get("inviati") or {}
        n = sum(inv.values())
        if n:
            base += f" · inviati {n} elementi"
        err = (rep.get("invio") or {}).get("errore") or (rep.get("ricezione") or {}).get("errore")
        if err:
            base += f" · problema: {err}"
    elif esito.get("errore"):
        base += f" · ultimo problema ({esito.get('quando')}): {esito['errore']}"
    return base


# =========================================================================== amministrazione (solo Daniele)

def admin(command: str, body: dict | None = None, opener=None) -> dict:
    cfg = store.load("config")
    key, url = cfg.get("cervello_admin_key"), config()["url"]
    if not key or not url:
        return {"errore": "manca la chiave di amministrazione o l'indirizzo (pubblica_cervello.bat li imposta)"}
    try:
        with _request(f"{url}/v1/admin/{command}", body if body is not None else ({} if command != "panoramica" else None),
                      {"authorization": f"Bearer {key}"}, opener=opener) as r:
            return json.loads(_read(r))
    except urllib.error.HTTPError as e:
        return {"errore": f"HTTP {e.code}", "dettagli": (_read(e) or b"")[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"errore": str(e)}


def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m origins.cervello", description="Cervello comune di BIG-BOB")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stato")
    sub.add_parser("sync")
    sub.add_parser("da-inviare")
    a = sub.add_parser("admin", help="panoramica | ricalcola | regola ID | lezione ID | nascondi carta NOME | "
                                     "mostra carta NOME | banna HASH")
    a.add_argument("comando")
    a.add_argument("arg", nargs="*")
    a.add_argument("--testo", default="")
    a.add_argument("--nascondi", action="store_true")
    a.add_argument("--unisci-in", default="")
    a.add_argument("--motivo", default="")
    ns = ap.parse_args(argv)
    if ns.cmd == "stato":
        out = status()
    elif ns.cmd == "sync":
        out = sync(force=True)
    elif ns.cmd == "da-inviare":
        out = {k: len(v) for k, v in pending().items()}
    else:
        body = None
        if ns.comando in ("regola", "lezione"):
            body = {"id": ns.arg[0] if ns.arg else ""}
            if ns.testo:
                body["testo"] = ns.testo
            if ns.nascondi:
                body["nascosta"] = True
            if ns.unisci_in:
                body["unisci_in"] = ns.unisci_in
        elif ns.comando in ("nascondi", "mostra"):
            body = {"tipo": ns.arg[0] if ns.arg else "", "chiave": " ".join(ns.arg[1:]), "motivo": ns.motivo}
        elif ns.comando == "banna":
            body = {"contributore": ns.arg[0] if ns.arg else ""}
        elif ns.comando == "ricalcola":
            body = {}
        out = admin(ns.comando, body)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
