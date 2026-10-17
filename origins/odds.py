"""Calcolo probabilità esatto (ipergeometrica) per Origins TCG.

Regole di mazzo note:
- 13 carte diverse: 12 carte normali in doppia copia + 1 leggendaria in copia singola = 25 carte.

Tutte le funzioni sono deterministiche: Claude non "stima" i numeri, li legge da qui.
"""
from __future__ import annotations

from math import comb
from typing import Iterable

DECK_SIZE = 25
NORMAL_COPIES = 2
LEGENDARY_COPIES = 1


def p_at_least_one(population: int, successes: int, draws: int) -> float:
    """P(almeno 1 successo) pescando `draws` carte da `population` che ne contiene `successes`."""
    if successes <= 0 or draws <= 0 or population <= 0:
        return 0.0
    draws = min(draws, population)
    if successes >= population:
        return 1.0
    if population - successes < draws:
        return 1.0
    return 1.0 - comb(population - successes, draws) / comb(population, draws)


def p_exactly(population: int, successes: int, draws: int, k: int) -> float:
    """P(esattamente k successi)."""
    draws = min(max(draws, 0), population)
    if k < 0 or k > successes or k > draws or draws - k > population - successes:
        return 0.0
    return comb(successes, k) * comb(population - successes, draws - k) / comb(population, draws)


def p_at_least(population: int, successes: int, draws: int, k: int) -> float:
    """P(almeno k successi)."""
    return sum(p_exactly(population, successes, draws, i) for i in range(k, successes + 1))


def counts(names: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for n in names:
        out[n] = out.get(n, 0) + 1
    return out


def deck_counts(legendary: str, cards: list[str]) -> dict[str, int]:
    """Lista completa del mazzo (25 carte) a partire da leggendaria + 12 carte."""
    d = {c: NORMAL_COPIES for c in cards}
    if legendary:
        d[legendary] = LEGENDARY_COPIES
    return d


def remaining_deck(full: dict[str, int], seen: dict[str, int]) -> dict[str, int]:
    """Carte rimaste nel mazzo = mazzo completo - carte già viste (mano, campo, scarti)."""
    rem = {}
    for name, n in full.items():
        left = n - seen.get(name, 0)
        if left > 0:
            rem[name] = left
    return rem


def my_draw_odds(full: dict[str, int], seen: dict[str, int], draws: int = 1,
                 targets: list[str] | None = None) -> dict:
    """Probabilità di pescare ogni carta (o un gruppo di carte) nelle prossime `draws` pescate."""
    rem = remaining_deck(full, seen)
    n = sum(rem.values())
    per_card = sorted(
        ({"carta": c, "copie_nel_mazzo": k, "p": round(p_at_least_one(n, k, draws), 4)}
         for c, k in rem.items()),
        key=lambda x: -x["p"],
    )
    result = {"carte_nel_mazzo": n, "pescate": draws, "per_carta": per_card}
    unknown_seen = [c for c in seen if c not in full]
    if unknown_seen:
        result["avviso"] = f"Carte viste che non sono nella lista del mazzo (generate/rubate?): {unknown_seen}"
    if targets:
        k = sum(rem.get(t, 0) for t in targets)
        result["gruppo"] = {
            "carte": targets,
            "copie_totali": k,
            "p_almeno_una": round(p_at_least_one(n, k, draws), 4),
        }
    return result


def opponent_hand_odds(archetypes: list[dict], legendary: str | None, opp_seen: dict[str, int],
                       hand_size: int, cards_revealed: int | None = None) -> dict:
    """Probabilità che l'avversario abbia in mano ciascuna carta.

    archetypes: [{"nome", "leggendaria", "carte": [12 nomi], "volte_visto": int}]
    opp_seen: carte avversarie già rivelate (giocate/scartate) con conteggio.
    hand_size: carte in mano all'avversario.
    cards_revealed: carte uscite dal mazzo e non più in mano/mazzo (default = somma di opp_seen).

    Modello: si sceglie l'archetipo con prior = frequenza (smoothing +1), si scartano quelli
    incompatibili con le carte viste; poi per ogni carta P(in mano | nel mazzo) è ipergeometrica
    sulle carte non ancora viste (mano + mazzo) assumendo che la mano sia un sottoinsieme casuale.
    """
    revealed = cards_revealed if cards_revealed is not None else sum(opp_seen.values())
    unseen_total = max(DECK_SIZE - revealed, 0)

    def compatible(a: dict) -> bool:
        if legendary and a.get("leggendaria") and a["leggendaria"].lower() != legendary.lower():
            return False
        pool = {c.lower() for c in a.get("carte", [])} | {(a.get("leggendaria") or "").lower()}
        return all(c.lower() in pool for c in opp_seen)

    cands = [a for a in archetypes if compatible(a)]
    # prior: partite tue + metà peso per le liste della community (+1 di smoothing)
    weights = [a.get("volte_visto", 0) + 0.5 * a.get("community", 0) + 1 for a in cands]
    soft = False
    if not cands:  # nessuna lista contiene tutte le carte viste (varianti, tech card): uso le più simili
        same = [a for a in archetypes if a.get("carte") and (not legendary or not a.get("leggendaria")
                                                            or a["leggendaria"].lower() == legendary.lower())]
        for a in same:
            pool = {c.lower() for c in a.get("carte", [])} | {(a.get("leggendaria") or "").lower()}
            miss = sum(1 for c in opp_seen if c.lower() not in pool)
            cands.append(a)
            weights.append((a.get("volte_visto", 0) + 0.5 * a.get("community", 0) + 1) * (0.08 ** miss))
        soft = bool(cands)
    tot = sum(weights)
    if soft:
        keep = [(a, w) for a, w in zip(cands, weights) if w / tot >= 0.01]
        cands, weights = [a for a, _ in keep], [w for _, w in keep]
        tot = sum(weights)
    out = {
        "carte_non_viste_avversario": unseen_total,
        "mano_avversario": hand_size,
        "archetipi_compatibili": sorted(
            [{"nome": a.get("nome"), "peso": round(w / tot, 3)} for a, w in zip(cands, weights)],
            key=lambda x: -x["peso"]) if tot else [],
    }
    if soft:
        out["avviso"] = ("Nessuna lista contiene tutte le carte viste: uso le più simili (l'avversario gioca una "
                         "variante)")
    if not cands:
        out["avviso"] = ("Nessun archetipo registrato è compatibile con le carte viste: "
                         "probabilità basate solo sulle carte già viste (possibili seconde copie).")
        per = []
        for c, k in opp_seen.items():
            copies = LEGENDARY_COPIES if legendary and c.lower() == legendary.lower() else NORMAL_COPIES
            left = copies - k
            if left > 0:
                per.append({"carta": c, "p_in_mano": round(p_at_least_one(unseen_total, left, hand_size), 4),
                            "p_nel_mazzo": 1.0})
        out["per_carta"] = sorted(per, key=lambda x: -x["p_in_mano"])
        return out

    agg: dict[str, dict] = {}
    for a, w in zip(cands, weights):
        pw = w / tot
        full = deck_counts(a.get("leggendaria") or "", a.get("carte", []))
        seen_ci = {k.lower(): v for k, v in opp_seen.items()}
        for c, copies in full.items():
            left = copies - seen_ci.get(c.lower(), 0)
            if left <= 0:
                continue
            p_hand = p_at_least_one(unseen_total, left, hand_size)
            e = agg.setdefault(c, {"carta": c, "p_in_mano": 0.0, "p_nel_mazzo": 0.0})
            e["p_in_mano"] += pw * p_hand
            e["p_nel_mazzo"] += pw
    per = sorted(agg.values(), key=lambda x: -x["p_in_mano"])
    for e in per:
        e["p_in_mano"] = round(e["p_in_mano"], 4)
        e["p_nel_mazzo"] = round(e["p_nel_mazzo"], 4)
    out["per_carta"] = per
    return out
