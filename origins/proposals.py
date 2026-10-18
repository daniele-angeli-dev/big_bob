"""Effetti di carta proposti dalle sorprese, confermati da Daniele con un clic.

Quando il combattimento reale non torna con quello simulato, nel turno di apprendimento Claude può proporre l'effetto
alla rivelazione che spiega la differenza (es. "Vampire Bat: On Reveal infligge 2 alla barrier di fronte"). La proposta
non cambia il database finché Daniele non la conferma: un effetto sbagliato falserebbe tutte le simulazioni.
"""
from __future__ import annotations

import json
import time

from origins import store

TIPI = {"danno_barrier": "danno alla barrier di fronte", "danno_fronte": "danno alla creatura di fronte",
        "potenzia": "si potenzia"}
FILE = "proposte_effetti.json"


def _path():
    return store.DATA / FILE


def load() -> list[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    _path().write_text(json.dumps(items[-200:], ensure_ascii=False, indent=1), encoding="utf-8")


def clean(effetti) -> list[dict]:
    out = []
    for x in effetti if isinstance(effetti, list) else [effetti]:
        if not isinstance(x, dict) or x.get("tipo") not in TIPI:
            continue
        try:
            v = int(x.get("valore", 0))
            hp = int(x.get("vita", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not (0 <= v <= 30 and 0 <= hp <= 30) or (v == 0 and hp == 0) or (x["tipo"] != "potenzia" and v == 0):
            continue
        out.append({"tipo": x["tipo"], "valore": v, **({"vita": hp} if x["tipo"] == "potenzia" else {})})
    return out


def describe(fx: list[dict]) -> str:
    parts = []
    for x in fx:
        if x["tipo"] == "potenzia":
            parts.append(f"alla rivelazione +{x['valore']}/+{x.get('vita', 0)}")
        else:
            parts.append(f"alla rivelazione {x['valore']} di {TIPI[x['tipo']]}")
    return ", ".join(parts)


def propose(carta: str, effetti, motivo: str = "") -> dict:
    card = store.find("cards", carta)
    if not card:
        return {"errore": f"carta '{carta}' non trovata nel database"}
    fx = clean(effetti)
    if not fx:
        return {"errore": "effetto non valido: tipo danno_barrier | danno_fronte | potenzia, valore intero 1-30 "
                          "(per potenzia anche vita)"}
    items = load()
    same = next((p for p in items if p["stato"] == "attesa" and p["carta"] == card["nome"] and p["effetti"] == fx), None)
    if same:
        same["volte"] = same.get("volte", 1) + 1  # la stessa proposta vista di nuovo: è un indizio più forte
        same["creata"] = time.time()  # torna fuori con i pulsanti (quelli di prima possono essere spariti dalla chat)
        _save(items)
        return {"id": same["id"], "gia_proposta": True, "volte": same["volte"]}
    n = max((int(p["id"][1:]) for p in items if str(p.get("id", "")).startswith("E") and p["id"][1:].isdigit()),
            default=0)
    pid = f"E{n + 1:03d}"  # il numero più alto + 1: il file tiene solo le ultime 200, len() ripeterebbe gli id
    items.append({"id": pid, "carta": card["nome"], "effetti": fx, "motivo": motivo.strip()[:300],
                  "stato": "attesa", "creata": time.time(), "data": store.now(), "volte": 1})
    _save(items)
    return {"id": pid, "carta": card["nome"], "effetto": describe(fx),
            "nota": "in attesa della conferma di Daniele (pulsante nella finestra)"}


def pending(since: float = 0.0) -> list[dict]:
    return [p for p in load() if p["stato"] == "attesa" and p.get("creata", 0) >= since]


def decide(pid: str, ok: bool) -> dict:
    items = load()
    p = next((x for x in items if x["id"] == pid), None)
    if not p:
        return {"errore": f"proposta {pid} non trovata"}
    if p["stato"] != "attesa":
        return {"errore": f"proposta {pid} già {p['stato']}"}
    p["stato"] = "confermata" if ok else "scartata"
    p["decisa"] = store.now()
    if ok:
        from origins import combat
        card = store.find("cards", p["carta"]) or {"nome": p["carta"]}
        cur = combat.effects(card)  # anche quelli letti dal testo: il campo 'effetti' li sostituisce tutti
        tipi = {x["tipo"] for x in p["effetti"]}
        merged = [x for x in cur if x.get("tipo") not in tipi] + p["effetti"]
        note = (card.get("note") or "").strip()
        add = f"effetto {describe(p['effetti'])} confermato da Daniele ({store.now()[:10]})"
        store.upsert("cards", [{"nome": card["nome"], "effetti": merged,
                                "note": (note + " · " if note else "") + add}])
    _save(items)
    return {"id": pid, "stato": p["stato"], "carta": p["carta"], "effetto": describe(p["effetti"])}
