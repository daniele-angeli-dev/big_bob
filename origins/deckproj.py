"""Modalità CREAZIONE MAZZO: il laboratorio dove BIG-BOB crea un mazzo e lo migliora con le partite di test.

Un progetto ha delle versioni (v1, v2…): ogni miglioria (togli X, metti Y) crea una versione nuova, che viene
messa alla prova per un certo numero di partite. Le statistiche vengono dalle partite registrate con quel mazzo
(il registro delle partite tiene progetto e versione), quindi niente si conta due volte e niente si perde.

Statistiche per versione: vittorie/sconfitte con intervallo di confidenza al 95% (Wilson), confronto con la
versione precedente (probabilità che sia migliore, da due distribuzioni Beta), carte (pescata, giocata,
winrate quando giocata, round medio della prima giocata), matchup per leggendaria avversaria, punti deboli.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

from origins import store

PARTITE_DEFAULT = 10      # versione iniziale o cambio grande
PARTITE_PICCOLO = 8       # cambio di una sola carta
MIN_DECISIONE = 6         # prima di così poche partite non si chiude in anticipo
SOGLIA = 0.9              # probabilità oltre cui il confronto è "netto"


def load() -> list[dict]:
    return store.load("projects")


def save(ps: list[dict]) -> None:
    store.save("projects", ps)


def active() -> dict | None:
    ps = load()
    name = store.load("config").get("progetto_mazzo")
    p = next((x for x in ps if x["nome"] == name and x.get("stato") != "concluso"), None)
    return p or next((x for x in reversed(ps) if x.get("stato") != "concluso"), None)


def get(name: str = "") -> dict | None:
    if not name:
        return active()
    s = store.slug(name)
    return next((x for x in load() if store.slug(x["nome"]) == s), None) or \
        next((x for x in load() if s in store.slug(x["nome"])), None)


def current(p: dict) -> dict:
    return p["versioni"][-1]


def deck_name(p: dict) -> str:
    """Nome del mazzo salvato che segue sempre la versione attuale (è quello da scegliere con NUOVA)."""
    return p["nome"]


def _set_active(name: str) -> None:
    cfg = store.load("config")
    cfg["progetto_mazzo"] = name
    store.save("config", cfg)


# ------------------------------------------------------------------ creazione e versioni

def start(nome: str, leggendaria: str, carte: list[str], obiettivo: str = "", motivo: str = "",
          fonti: list[str] | None = None, partite: int | None = None) -> dict:
    v = store.validate_deck(leggendaria, carte)
    if not v["valido"]:
        return {"errore": "mazzo non valido", "problemi": v["problemi"]}
    ps = load()
    if any(store.slug(x["nome"]) == store.slug(nome) for x in ps):
        return {"errore": f"esiste già un progetto '{nome}': usa un altro nome o deck_project_change"}
    p = {"nome": nome, "obiettivo": obiettivo, "creato": store.now(), "stato": "in test",
         "versioni": [{"v": 1, "leggendaria": v["leggendaria"], "carte": v["carte"], "creata": store.now(),
                       "motivo": motivo or "versione iniziale", "fonti": fonti or [], "tolte": [], "messe": [],
                       "partite_obiettivo": int(partite or PARTITE_DEFAULT)}],
         "proposta": None}
    ps.append(p)
    save(ps)
    store.save_deck(deck_name(p), v["leggendaria"], v["carte"], note=f"progetto {nome} v1")
    _set_active(nome)
    return {"creato": nome, "versione": 1, "mazzo_da_scegliere_con_NUOVA": deck_name(p),
            "partite_di_test": p["versioni"][0]["partite_obiettivo"], "carte": v["carte"],
            "leggendaria": v["leggendaria"]}


def _swap(cards: list[str], out: list[str], inn: list[str]) -> tuple[list[str], list[str]]:
    probs = []
    names = list(cards)
    for c in out:
        e = store.canonical(c)
        hit = next((x for x in names if store.slug(x) == store.slug(e)), None)
        if hit is None:
            probs.append(f"'{c}' non è nel mazzo")
        else:
            names.remove(hit)
    for c in inn:
        names.append(store.canonical(c))
    return names, probs


def propose(nome: str, togli: list[str], metti: list[str], motivo: str, partite: int | None = None) -> dict:
    """Salva una miglioria da provare: Daniele la applica (nel gioco e con APPLICA) quando vuole."""
    ps = load()
    p = next((x for x in ps if store.slug(x["nome"]) == store.slug(nome)), None) if nome else None
    p = p or next((x for x in ps if x["nome"] == (active() or {}).get("nome")), None)
    if p is None:
        return {"errore": "nessun progetto attivo"}
    cur = current(p)
    names, probs = _swap(cur["carte"], togli, metti)
    v = store.validate_deck(cur["leggendaria"], names)
    if probs or not v["valido"] or len(togli) != len(metti):
        return {"errore": "miglioria non valida", "problemi": probs + v["problemi"]
                + ([] if len(togli) == len(metti) else ["togli e metti devono avere lo stesso numero di carte"])}
    p["proposta"] = {"togli": [store.canonical(x) for x in togli], "metti": [store.canonical(x) for x in metti],
                     "motivo": motivo, "data": store.now(), "da_versione": cur["v"],
                     "partite": int(partite) if partite else (PARTITE_PICCOLO if len(togli) == 1 else PARTITE_DEFAULT)}
    save(ps)
    return {"proposta": p["proposta"], "nel_gioco": instructions(p["proposta"])}


def instructions(prop: dict) -> str:
    out = ", ".join(f"{c} ×2" for c in prop["togli"])
    inn = ", ".join(f"{c} ×2" for c in prop["metti"])
    return f"Nel gioco togli {out} e metti {inn}."


def apply(nome: str = "") -> dict:
    ps = load()
    target = get(nome)
    p = next((x for x in ps if target and x["nome"] == target["nome"]), None)
    if p is None or not p.get("proposta"):
        return {"errore": "nessuna miglioria da applicare"}
    prop = p["proposta"]
    cur = current(p)
    names, _ = _swap(cur["carte"], prop["togli"], prop["metti"])
    nv = {"v": cur["v"] + 1, "leggendaria": cur["leggendaria"], "carte": names, "creata": store.now(),
          "motivo": prop["motivo"], "fonti": [], "tolte": prop["togli"], "messe": prop["metti"],
          "partite_obiettivo": prop.get("partite") or PARTITE_DEFAULT}
    p["versioni"].append(nv)
    p["proposta"] = None
    save(ps)
    store.save_deck(deck_name(p), nv["leggendaria"], names, note=f"progetto {p['nome']} v{nv['v']}")
    _set_active(p["nome"])
    return {"versione": nv["v"], "nel_gioco": instructions(prop), "partite_di_test": nv["partite_obiettivo"]}


def revert(nome: str, versione: int, motivo: str = "") -> dict:
    """Torna alle carte di una versione precedente (diventa una versione nuova, così lo storico resta)."""
    ps = load()
    target = get(nome)
    p = next((x for x in ps if target and x["nome"] == target["nome"]), None)
    if p is None:
        return {"errore": "progetto non trovato"}
    old = next((v for v in p["versioni"] if v["v"] == int(versione)), None)
    if old is None:
        return {"errore": f"versione {versione} non trovata"}
    cur = current(p)
    out = [c for c in cur["carte"] if c not in old["carte"]]
    inn = [c for c in old["carte"] if c not in cur["carte"]]
    p["proposta"] = {"togli": out, "metti": inn, "motivo": motivo or f"ritorno alla v{versione}",
                     "data": store.now(), "da_versione": cur["v"], "partite": PARTITE_PICCOLO}
    save(ps)
    return apply(p["nome"])


def set_options(nome: str = "", partite: int | None = None, stato: str = "", attivo: bool = False) -> dict:
    ps = load()
    target = get(nome)
    p = next((x for x in ps if target and x["nome"] == target["nome"]), None)
    if p is None:
        return {"errore": "progetto non trovato"}
    if partite:
        current(p)["partite_obiettivo"] = int(partite)
    if stato:
        p["stato"] = stato
    save(ps)
    if attivo:
        _set_active(p["nome"])
    return {"ok": True, "progetto": p["nome"], "stato": p["stato"], "partite_obiettivo": current(p)["partite_obiettivo"]}


# ------------------------------------------------------------------ statistiche

def wilson(w: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def p_better(w1: int, n1: int, w0: int, n0: int, sims: int = 20000, seed: int = 7) -> float:
    """Probabilità che la versione 1 abbia un winrate reale più alto della versione 0 (Beta(1+v, 1+s))."""
    rng = random.Random(seed)
    better = 0
    for _ in range(sims):
        if rng.betavariate(1 + w1, 1 + n1 - w1) > rng.betavariate(1 + w0, 1 + n0 - w0):
            better += 1
    return better / sims


def _win(m: dict) -> bool:
    return str(m.get("risultato", "")).lower().startswith("v")


def matches_of(p: dict, v: int | None = None) -> list[dict]:
    return [m for m in store.load("matches") if m.get("progetto") == p["nome"] and m.get("risultato")
            and (v is None or m.get("versione") == v)]


def version_stats(p: dict, ver: dict) -> dict:
    ms = matches_of(p, ver["v"])
    n, w = len(ms), sum(1 for m in ms if _win(m))
    lo, hi = wilson(w, n)
    deck = [ver["leggendaria"]] + ver["carte"]
    cards = {}
    for c in deck:
        drawn = played = win_played = win_not = n_not = 0
        rounds = []
        for m in ms:
            low = lambda xs: {x.lower() for x in xs or []}  # noqa: E731
            pl = low(m.get("miei_giocati"))
            seen = pl | low(m.get("viste_in_mano")) | low(m.get("mia_mano")) | low(m.get("miei_scartati"))
            if c.lower() in seen:
                drawn += 1
            if c.lower() in pl:
                played += 1
                win_played += _win(m)
                r = (m.get("prima_giocata") or {}).get(c)
                if isinstance(r, (int, float)):
                    rounds.append(r)
            else:
                n_not += 1
                win_not += _win(m)
        e = store.find("cards", c) or {}
        cards[c] = {"costo": e.get("costo"), "pescata": drawn, "giocata": played,
                    "winrate_giocata": round(win_played / played * 100) if played else None,
                    "winrate_non_giocata": round(win_not / n_not * 100) if n_not else None,
                    "round_medio": round(sum(rounds) / len(rounds), 1) if rounds else None,
                    "leggendaria": c == ver["leggendaria"]}
    opp: dict = defaultdict(lambda: [0, 0])
    for m in ms:
        k = m.get("avv_leggendaria") or "?"
        opp[k][0] += _win(m)
        opp[k][1] += 1
    adv = [r for m in ms for r in m.get("rounds") or []]
    followed = [r for r in adv if r.get("consiglio_seguito")]
    target = ver.get("partite_obiettivo") or PARTITE_DEFAULT
    return {"v": ver["v"], "partite": n, "vinte": w, "perse": n - w,
            "winrate": round(w / n * 100) if n else None,
            "intervallo_95": [round(lo * 100), round(hi * 100)] if n else None,
            "margine": round(1.96 * math.sqrt(0.25 / n) * 100) if n else None,
            "partite_obiettivo": target, "carte": cards,
            "contro": {k: {"vinte": a, "partite": b} for k, (a, b) in sorted(opp.items(), key=lambda x: -x[1][1])},
            "barrier_fatte": round(sum(m.get("distrutte_da_me") or 0 for m in ms) / n, 1) if n else None,
            "barrier_subite": round(sum(m.get("distrutte_a_me") or 0 for m in ms) / n, 1) if n else None,
            "consigli_seguiti": f"{len(followed)}/{len(adv)}" if adv else None}


def weaknesses(st: dict) -> list[str]:
    """Punti deboli che si vedono dai numeri (Claude li incrocia con lezioni, meta e statistiche del sito)."""
    out = []
    if not st["partite"]:
        return out
    overall = st["winrate"] or 0
    for c, s in st["carte"].items():
        if s["pescata"] >= 3 and s["giocata"] / s["pescata"] < 0.4:
            out.append(f"{c}: pescata in {s['pescata']} partite ma giocata solo in {s['giocata']} — resta in mano "
                       "(troppo cara o troppo situazionale)")
        if s["giocata"] >= 3 and s["winrate_giocata"] is not None and s["winrate_giocata"] <= overall - 20:
            out.append(f"{c}: quando la giochi vinci il {s['winrate_giocata']}% contro il {overall}% del mazzo")
        if s["round_medio"] and s["costo"] is not None and s["round_medio"] >= s["costo"] + 2.5 and s["giocata"] >= 3:
            out.append(f"{c}: costa {s['costo']} ma in media arriva al round {s['round_medio']} — entra tardi")
    for k, r in st["contro"].items():
        if r["partite"] >= 2 and r["vinte"] / r["partite"] <= 0.34:
            out.append(f"Contro {k}: {r['vinte']} vinte su {r['partite']}")
    if st["barrier_subite"] is not None and st["barrier_subite"] >= 1.6 and st["barrier_fatte"] is not None \
            and st["barrier_fatte"] < st["barrier_subite"]:
        out.append(f"Difesa: subisci in media {st['barrier_subite']} barrier distrutte e ne fai {st['barrier_fatte']}")
    return out


def status(p: dict) -> dict:
    vs = [version_stats(p, v) for v in p["versioni"]]
    cur = vs[-1]
    prev = next((s for s in reversed(vs[:-1]) if s["partite"]), None)
    verdict = None
    early = False
    if prev and cur["partite"]:
        pb = p_better(cur["vinte"], cur["partite"], prev["vinte"], prev["partite"])
        verdict = {"contro_versione": prev["v"], "p_migliore": round(pb * 100)}
        if cur["partite"] >= MIN_DECISIONE and (pb >= SOGLIA or pb <= 1 - SOGLIA):
            early = True
            verdict["netto"] = "migliore" if pb >= SOGLIA else "peggiore"
    left = 0 if early else max(0, cur["partite_obiettivo"] - cur["partite"])
    if left == 0:
        if verdict and verdict.get("netto") == "peggiore":
            consiglio = (f"La v{cur['v']} va peggio della v{prev['v']}: torna indietro (deck_project_revert) o prova "
                         "un'altra miglioria.")
        else:
            consiglio = "Test della versione finito: è il momento di valutare una miglioria."
    else:
        consiglio = f"Gioca ancora {left} partit{'a' if left == 1 else 'e'} con la v{cur['v']}."
    return {"progetto": p["nome"], "obiettivo": p.get("obiettivo"), "stato": p.get("stato"),
            "versione_attuale": cur["v"], "mazzo": {"leggendaria": p["versioni"][-1]["leggendaria"],
                                                     "carte": p["versioni"][-1]["carte"]},
            "partite_mancanti": left, "valutazione_anticipata": early, "confronto": verdict,
            "consiglio": consiglio, "punti_deboli": weaknesses(cur), "proposta": p.get("proposta"),
            "versioni": [{**{k: s[k] for k in ("v", "partite", "vinte", "perse", "winrate", "intervallo_95",
                                                 "margine", "partite_obiettivo")},
                          "motivo": p["versioni"][i]["motivo"], "tolte": p["versioni"][i]["tolte"],
                          "messe": p["versioni"][i]["messe"]} for i, s in enumerate(vs)],
            "statistiche_versione_attuale": cur,
            "nota": ("Con poche partite il winrate ha un margine ampio (±" + str(cur["margine"] or "?") + " punti): "
                     "per questo conta anche cosa dicono le carte, i matchup e le lezioni, non solo il risultato.")}


def summary(p: dict | None = None) -> dict | None:
    """Riassunto per la finestra (pannello LABORATORIO)."""
    p = p or active()
    if not p:
        return None
    st = status(p)
    cur = st["statistiche_versione_attuale"]
    return {"nome": p["nome"], "v": st["versione_attuale"], "partite": cur["partite"],
            "obiettivo": cur["partite_obiettivo"], "vinte": cur["vinte"], "perse": cur["perse"],
            "mancanti": st["partite_mancanti"], "confronto": st["confronto"],
            "proposta": (instructions(p["proposta"]) + " " + p["proposta"]["motivo"]) if p.get("proposta") else None,
            "deck": deck_name(p), "consiglio": st["consiglio"]}


def tag_match(deck: str) -> dict:
    """Se il mazzo della partita è quello di un progetto in test, la partita conta per la sua versione attuale."""
    for p in load():
        if p.get("stato") != "concluso" and store.slug(deck_name(p)) == store.slug(deck):
            return {"progetto": p["nome"], "versione": current(p)["v"]}
    return {}
