"""Archivio JSON locale: carte, location, mazzi, meta (mazzi avversari), patch, stato partita."""
from __future__ import annotations

import json
import re
import time
from difflib import get_close_matches
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

FILES = {
    "cards": DATA / "cards.json",
    "locations": DATA / "locations.json",
    "decks": DATA / "decks.json",
    "meta": DATA / "meta.json",
    "patches": DATA / "patches.json",
    "match": DATA / "match_current.json",
    "matches": DATA / "matches_log.json",
    "rules": DATA / "rules.json",
    "lessons": DATA / "lessons.json",
    "originsmeta": DATA / "originsmeta.json",
    "projects": DATA / "progetti_mazzo.json",
    "config": ROOT / "config.json",
}

DEFAULTS = {
    "cards": [], "locations": [], "decks": [], "meta": [], "patches": [], "match": {}, "matches": [], "rules": [], "lessons": [], "originsmeta": {}, "projects": [],
    "config": {"modalita": "allenamento", "modello_live": "sonnet", "hotkey_analisi": "f8",
               "hotkey_scan": "f9", "titolo_finestra": "Origins", "patch_corrente": "",
               "max_thinking_live": 4000, "apprendimento_live": True, "voce": True,
               "apri_claude_code_all_avvio": False, "connessione": "abbonamento",
               "controlla_aggiornamenti": True, "meta_originsmeta": True, "progetto_mazzo": "",
               "osservatore": True, "barra_vantaggio": True, "cervello_url": "", "cervello_contribuisci": True,
               "cervello_usa": True, "invisibile_catture": True},
}


def load(kind: str):
    p = FILES[kind]
    if not p.exists():
        return json.loads(json.dumps(DEFAULTS[kind]))
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save(kind: str, data) -> None:
    """Scrittura atomica. Il file temporaneo ha un nome per processo e thread (BIG-BOB e il server MCP possono scrivere
    lo stesso file insieme) e la sostituzione si ritenta se Windows lo tiene aperto un istante."""
    import os
    import threading
    import time as _time
    p = FILES[kind]
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for attempt in range(8):
        try:
            tmp.replace(p)
            return
        except PermissionError:
            if attempt == 7:
                raise
            _time.sleep(0.05 * (attempt + 1))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


# ---------------- carte / location ----------------

TRACKED_FIELDS = ("costo", "attacco", "vita", "potere", "testo", "leggendaria", "potere_leggendario",
                  "rarita", "tipo", "tag")


def upsert(kind: str, items: list[dict], patch: str | None = None) -> dict:
    """Inserisce o aggiorna carte/location. Registra lo storico delle modifiche per patch."""
    db = load(kind)
    by_id = {e["id"]: e for e in db}
    added, changed, unchanged = [], [], []
    patch = patch or load("config").get("patch_corrente") or "sconosciuta"
    for it in items:
        if not it.get("nome"):
            continue
        it = dict(it)
        it["id"] = slug(it["nome"])
        old = by_id.get(it["id"])
        if old is None:
            it["aggiunta"] = now()
            it["patch_introduzione"] = patch
            it.setdefault("storico", [])
            by_id[it["id"]] = it
            added.append(it["nome"])
            continue
        # un testo corretto a mano (da Daniele o da Claude) su una carta presa da OriginsMeta diventa "verificata":
        # le sincronizzazioni successive non lo sovrascrivono più
        if it.get("testo") and not it.get("fonte") and old.get("fonte") == "originsmeta" and it["testo"] != old.get("testo"):
            it["fonte"] = "verificata"
        diffs = []
        for k in TRACKED_FIELDS:
            # riempire un campo vuoto è completare i dati, non una modifica di bilanciamento
            if k in it and it[k] is not None and old.get(k) not in (None, "", []) and old.get(k) != it[k]:
                diffs.append({"campo": k, "prima": old.get(k), "dopo": it[k]})
        for k, v in it.items():
            if v is not None and k not in ("storico",):
                old[k] = v
        if diffs:
            old.setdefault("storico", []).append({"patch": patch, "data": now(), "modifiche": diffs})
            old["aggiornata"] = now()
            changed.append({"nome": old["nome"], "modifiche": diffs})
        else:
            unchanged.append(old["nome"])
    save(kind, sorted(by_id.values(), key=lambda e: e["nome"].lower()))
    return {"aggiunte": added, "modificate": changed, "invariate": len(unchanged), "totale": len(by_id)}


_FIND_CACHE: dict = {}


def _index(kind: str) -> tuple[dict, list[str]]:
    """Indice per id del database, riletto solo quando il file cambia: find viene chiamata migliaia di volte (ricerca
    della mossa, probabilità) e rileggere tutto il file ogni volta era la parte lenta."""
    p = FILES[kind]
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(p), None, None)
    hit = _FIND_CACHE.get(kind)
    if hit and hit[0] == key:
        return hit[1], hit[2]
    db = load(kind)
    by_id = {e["id"]: e for e in db if isinstance(e, dict) and "id" in e}
    _FIND_CACHE[kind] = (key, by_id, list(by_id))
    return by_id, list(by_id)


def find(kind: str, name: str) -> dict | None:
    by_id, ids = _index(kind)
    sid = slug(name)
    e = by_id.get(sid)
    if e is None:
        ver = _FIND_CACHE.get(kind, (None,))[0]
        close = _CLOSE_CACHE.get((kind, sid, ver))
        if close is None:
            m = get_close_matches(sid, ids, n=1, cutoff=0.75)
            close = m[0] if m else ""
            if len(_CLOSE_CACHE) > 3000:
                _CLOSE_CACHE.clear()
            _CLOSE_CACHE[(kind, sid, ver)] = close
        e = by_id.get(close) if close else None
    return dict(e) if e is not None else None  # copia: chi la modifica non tocca l'indice


_CLOSE_CACHE: dict = {}


def search(kind: str, query: str = "", limit: int = 50) -> list[dict]:
    db = load(kind)
    if not query:
        return db[:limit]
    q = query.lower()
    hits = [e for e in db if q in json.dumps(e, ensure_ascii=False).lower()]
    if not hits:
        ids = get_close_matches(slug(query), [e["id"] for e in db], n=5, cutoff=0.5)
        hits = [e for e in db if e["id"] in ids]
    return hits[:limit]


def canonical(name: str, kind: str = "cards") -> str:
    """Restituisce il nome ufficiale della carta se riconosciuto (anche con piccoli errori di lettura)."""
    e = find(kind, name)
    return e["nome"] if e else name


# ---------------- mazzi ----------------

def validate_deck(legendary: str, cards: list[str]) -> dict:
    problems = []
    leg = find("cards", legendary)
    if not leg:
        problems.append(f"Leggendaria '{legendary}' non presente nel database")
    elif leg.get("leggendaria") is False:
        problems.append(f"'{leg['nome']}' non risulta leggendaria")
    names = []
    for c in cards:
        e = find("cards", c)
        if not e:
            problems.append(f"Carta '{c}' non presente nel database")
            names.append(c)
        else:
            if e.get("leggendaria"):
                problems.append(f"'{e['nome']}' è leggendaria: va solo come leggendaria del mazzo")
            names.append(e["nome"])
    if len(set(n.lower() for n in names)) != len(names):
        problems.append("Carte duplicate nella lista (ogni carta è già in doppia copia automaticamente)")
    if len(names) != 12:
        problems.append(f"Servono 12 carte normali + 1 leggendaria, ne hai {len(names)}")
    return {"valido": not problems, "problemi": problems,
            "leggendaria": leg["nome"] if leg else legendary, "carte": names}


def save_deck(name: str, legendary: str, cards: list[str], note: str = "") -> dict:
    v = validate_deck(legendary, cards)
    decks = [d for d in load("decks") if slug(d["nome"]) != slug(name)]
    decks.append({"nome": name, "leggendaria": v["leggendaria"], "carte": v["carte"], "note": note,
                  "salvato": now(), "patch": load("config").get("patch_corrente", "")})
    save("decks", decks)
    return {"salvato": name, "validazione": v}


def get_deck(name: str) -> dict | None:
    for d in load("decks"):
        if slug(d["nome"]) == slug(name):
            return d
    return None


# ---------------- meta (mazzi avversari) ----------------

def record_opponent(legendary: str, cards_seen: list[str], result: str = "", archetype: str = "",
                    community: bool = False) -> dict:
    """Unisce le carte viste all'archetipo più compatibile della stessa leggendaria, o ne crea uno."""
    meta = load("meta")
    leg = canonical(legendary)
    seen = [canonical(c) for c in cards_seen if c and slug(c) != slug(leg)]
    seen = list(dict.fromkeys(seen))
    target = None
    if archetype:
        target = next((a for a in meta if slug(a["nome"]) == slug(archetype)), None)
    if target is None:
        best, best_score = None, -1
        for a in meta:
            if slug(a.get("leggendaria", "")) != slug(leg):
                continue
            pool = {slug(c) for c in a["carte"]}
            overlap = sum(1 for c in seen if slug(c) in pool)
            new = len(seen) - overlap
            if len(pool) + new <= 12 and overlap >= best_score:
                best, best_score = a, overlap
        target = best
    if target is None:
        target = {"nome": archetype or f"{leg} #{sum(1 for a in meta if slug(a.get('leggendaria','')) == slug(leg)) + 1}",
                  "leggendaria": leg, "carte": [], "volte_visto": 0, "vittorie_mie": 0, "sconfitte_mie": 0,
                  "community": 0, "creato": now()}
        meta.append(target)
    for c in seen:
        if slug(c) not in {slug(x) for x in target["carte"]} and len(target["carte"]) < 12:
            target["carte"].append(c)
    if community:
        target["community"] = target.get("community", 0) + 1
        target["ultimo"] = now()
        target["completo"] = len(target["carte"]) == 12
        save("meta", meta)
        return target
    target["volte_visto"] = target.get("volte_visto", 0) + 1
    if result.lower().startswith("v"):
        target["vittorie_mie"] = target.get("vittorie_mie", 0) + 1
    elif result.lower().startswith("s") or result.lower().startswith("p"):
        target["sconfitte_mie"] = target.get("sconfitte_mie", 0) + 1
    target["ultimo"] = now()
    target["completo"] = len(target["carte"]) == 12
    save("meta", meta)
    return target


def meta_summary(include_originsmeta: bool = False) -> list[dict]:
    """Archetipi avversari. Le liste importate da OriginsMeta sono escluse (si leggono con community_decks)."""
    meta = [a for a in load("meta") if include_originsmeta or a.get("fonte") != "originsmeta"]
    tot = sum(a["volte_visto"] for a in meta) or 1
    out = []
    for a in sorted(meta, key=lambda a: -a["volte_visto"]):
        g = a["vittorie_mie"] + a["sconfitte_mie"]
        out.append({"nome": a["nome"], "leggendaria": a["leggendaria"], "diffusione": round(a["volte_visto"] / tot, 3),
                    "volte_visto": a["volte_visto"], "community": a.get("community", 0),
                    "carte_note": f"{len(a['carte'])}/12",
                    "mio_winrate_contro": round(a["vittorie_mie"] / g, 3) if g else None,
                    "carte": a["carte"]})
    return out
