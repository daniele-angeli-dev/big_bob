"""Ricerca della mossa: BIG-BOB prova tutte le giocate possibili prima di chiedere al coach.

Per il round in corso:
1. elenca le giocate legali: insiemi di carte della mano che puoi pagare con il mana, e per ogni creatura gli spazi
   liberi del tuo lato (le magie non occupano spazi: si contano nel mana, il loro effetto lo valuta il coach);
2. simula il combattimento di ognuna (con gli effetti alla rivelazione riconosciuti, vedi combat.effects);
3. per le migliori prova la risposta più dannosa dell'avversario con le carte che probabilmente ha in mano e può
   pagare (dalla previsione sul suo mazzo), creatura per creatura e spazio per spazio;
4. ordina per un punteggio che misura la corsa a 2 barrier distrutte: vittoria, barrier distrutte, quanto avvicini a
   0 le barrier avversarie (quelle quasi a zero valgono di più), quanto rischi le tue, il campo che resta.
Il risultato (le 3 migliori con i numeri) va nel risultato di update_match: il coach sceglie e spiega, senza fare
conti a mente e senza chiamare simulate_combat. C'è un tempo massimo: oltre, usa quello che ha già valutato.
"""
from __future__ import annotations

import copy
import itertools
import time

from origins import combat, store

TIME_LIMIT = 0.9   # secondi
MAX_CREATURE = 3   # creature giocate nello stesso round, al massimo
MIN_SLOTS = 2


def _card(name: str) -> dict:
    return store.find("cards", name) or {}


def _cost(e: dict) -> int | None:
    c = e.get("costo")
    return int(c) if isinstance(c, (int, float)) else None


def _is_creature(e: dict) -> bool:
    t = str(e.get("tipo") or "").lower()
    if t:
        return t.startswith(("creat", "unit", "minion", "leggend")) or (e.get("attacco") is not None and "spell" not in t
                                                                         and "magia" not in t)
    return e.get("attacco") is not None


def _slots(lanes: list[dict]) -> int:
    return max([MIN_SLOTS] + [len(l["mie"]) for l in lanes])


def _free(lanes: list[dict], n_slots: int) -> list[tuple[int, int]]:
    out = []
    for i, lane in enumerate(lanes):
        for k in range(n_slots):
            if k >= len(lane["mie"]) or lane["mie"][k] is None:
                out.append((i, k))
    return out


def score(res: dict, before: dict) -> float:
    """Punteggio della corsa a 2 barrier: alto = meglio per Daniele."""
    s = 0.0
    w = res.get("vincitore") or ""
    if w.startswith("VINCI TU"):
        s += 1000
    elif w.startswith("VINCE L'AVVERSARIO"):
        s -= 1000
    s += 80 * (res["distrutte_da_te"] - before["by"]) - 90 * (res["distrutte_a_te"] - before["to"])
    for i in range(3):
        bo, ao = before["bo"][i], res["barrier_avv"][i]
        if ao < bo:  # danno senza distruggerla: vale di più se la barrier era già bassa
            s += 25 * (bo - ao) / max(bo, 1)
        bm, am = before["bm"][i], res["barrier_tue"][i]
        if am < bm:
            s -= 28 * (bm - am) / max(bm, 1)
    for lane in res["sopravvissuti"].values():
        for u in lane["mie"]:
            a, h = _stats(u)
            s += 0.6 * (a + h)
        for u in lane["avv"]:
            a, h = _stats(u)
            s -= 0.6 * (a + h)
    return round(s, 1)


def _stats(text: str) -> tuple[int, int]:
    try:
        a, h = text.rsplit(" ", 1)[1].split("/")
        return int(a), int(h)
    except (ValueError, IndexError):
        return 0, 0


def _play(lanes, plays, side="mie"):
    """Applica le giocate [(carta, corsia, slot)] e restituisce (corsie, danni diretti, note)."""
    lanes = copy.deepcopy(lanes)
    direct, notes = [], []
    for card, i, k in plays:
        combat.place(lanes, side, card, i, k + 1)
        d, n = combat.apply_reveal(lanes, side, i, k, card)
        direct += d
        notes += n
    return lanes, direct, notes


def _sim(m, lanes, direct):
    return combat.simulate(lanes, m.get("barrier_mie"), m.get("barrier_avv"), m.get("distrutte_da_me") or 0,
                           m.get("distrutte_a_me") or 0, direct)


def candidates(m: dict) -> tuple[list[list[str]], list[str]]:
    """Insiemi di creature giocabili (per mana) e magie giocabili, dalla mano."""
    mana = m.get("mana") if isinstance(m.get("mana"), int) else None
    hand = list(m.get("mia_mano") or [])
    creatures, spells = [], []
    for c in hand:
        e = _card(c)
        cost = _cost(e)
        if cost is None or (mana is not None and cost > mana):
            continue
        (creatures if _is_creature(e) else spells).append(e.get("nome") or c)
    sets = {()}
    for r in range(1, MAX_CREATURE + 1):
        for combo in itertools.combinations(sorted(creatures), r):
            if mana is None or sum(_cost(_card(c)) or 0 for c in combo) <= mana:
                sets.add(tuple(combo))
    return [list(s) for s in sorted(sets, key=lambda s: -sum(_cost(_card(c)) or 0 for c in s))], sorted(set(spells))


def search(m: dict, opp_cards: list[dict] | None = None, p_reply: float | None = None, top: int = 3,
           time_limit: float = TIME_LIMIT) -> dict:
    """{'mosse': [...], 'valutate': n, 'magie': [...], 'note': str}. opp_cards = carte avversarie giocabili con
    probabilità ({'carta', 'p_mano'}), p_reply = probabilità che giochi almeno una carta."""
    t0 = time.time()
    lanes0 = combat.normalize_board(m.get("campo") or {})
    n_slots = _slots(lanes0)
    before = {"by": m.get("distrutte_da_me") or 0, "to": m.get("distrutte_a_me") or 0,
              "bo": [b if isinstance(b, (int, float)) else 20 for b in (m.get("barrier_avv") or [20, 20, 20])],
              "bm": [b if isinstance(b, (int, float)) else 20 for b in (m.get("barrier_mie") or [20, 20, 20])]}
    sets, spells = candidates(m)
    free = _free(lanes0, n_slots)
    evaluated: list[dict] = []
    n = 0
    stop = False
    for cards in sets:
        if stop:
            break
        seen_layouts = set()
        for spots in itertools.permutations(free, len(cards)):
            if time.time() - t0 > time_limit * 0.6:
                stop = True
                break
            # stesse carte negli stessi spazi in ordine diverso = stessa giocata (l'ordine di attivazione lo sceglie
            # il coach)
            layout = tuple(sorted(zip(cards, spots)))
            if layout in seen_layouts:
                continue
            seen_layouts.add(layout)
            plays = [(c, i, k) for c, (i, k) in zip(cards, spots)]
            lanes, direct, notes = _play(lanes0, plays)
            res = _sim(m, lanes, direct)
            n += 1
            evaluated.append({"giocate": plays, "res": res, "base": score(res, before), "note": notes,
                              "lanes": lanes, "direct": direct,
                              "mana": sum(_cost(_card(c)) or 0 for c in cards)})
    if not evaluated:
        return {"mosse": [], "valutate": 0, "magie": spells, "note": "nessuna giocata valutabile"}
    evaluated.sort(key=lambda x: (-x["base"], -x["mana"]))
    # la risposta avversaria solo per le migliori (è la parte costosa)
    replies = [c for c in (opp_cards or []) if c.get("carta") and _is_creature(_card(c["carta"]))][:3]
    pr = p_reply if isinstance(p_reply, (int, float)) else (0.6 if replies else 0.0)
    shortlist, sigs = [], set()
    for ev in evaluated:  # varietà: due giocate con le stesse carte e lo stesso esito sono la stessa idea
        r = ev["res"]
        sig = (tuple(sorted(c for c, _, _ in ev["giocate"])), tuple(r["barrier_avv"]), tuple(r["barrier_tue"]),
               r["distrutte_da_te"], r["distrutte_a_te"])
        if sig in sigs:
            continue
        sigs.add(sig)
        shortlist.append(ev)
        if len(shortlist) >= 8:
            break
    for ev in shortlist:
        worst = None
        for rc in replies:
            if time.time() - t0 > time_limit:
                break
            for i in range(3):
                for k in range(n_slots):
                    row = ev["lanes"][i]["avv"]
                    if k < len(row) and row[k] is not None:
                        continue
                    lanes, direct, _ = _play(ev["lanes"], [(rc["carta"], i, k)], side="avv")
                    res = _sim(m, lanes, ev["direct"] + direct)
                    n += 1
                    sc = score(res, before)
                    if worst is None or sc < worst["score"]:
                        worst = {"score": sc, "carta": rc["carta"], "p": rc.get("p_mano"), "corsia": combat.LANES[i],
                                 "slot": k + 1, "res": res}
        ev["peggiore"] = worst
        ev["totale"] = round(ev["base"] * (1 - pr) + (worst["score"] if worst else ev["base"]) * pr, 1)
    shortlist.sort(key=lambda x: (-x["totale"], -x["mana"]))
    out = []
    for ev in shortlist[:top]:
        out.append({"giocate": [{"carta": c, "corsia": combat.LANES[i], "slot": k + 1} for c, i, k in ev["giocate"]],
                    "mana": ev["mana"], "punteggio": ev["totale"], "base": ev["base"],
                    "barrier_tue": ev["res"]["barrier_tue"], "barrier_avv": ev["res"]["barrier_avv"],
                    "distrutte": [ev["res"]["distrutte_da_te"], ev["res"]["distrutte_a_te"]],
                    "vincitore": ev["res"]["vincitore"], "effetti": ev["note"],
                    "peggiore": ({k: v for k, v in ev["peggiore"].items() if k != "res"} | {
                        "barrier_tue": ev["peggiore"]["res"]["barrier_tue"],
                        "barrier_avv": ev["peggiore"]["res"]["barrier_avv"],
                        "distrutte": [ev["peggiore"]["res"]["distrutte_da_te"], ev["peggiore"]["res"]["distrutte_a_te"]],
                        "vincitore": ev["peggiore"]["res"]["vincitore"]}) if ev.get("peggiore") else None})
    return {"mosse": out, "valutate": n, "magie": spells, "secondi": round(time.time() - t0, 2),
            "p_risposta": round(pr, 2)}


def lines(r: dict) -> list[str]:
    """Le righe MOSSE CALCOLATE per update_match."""
    if not r or not r.get("mosse"):
        return []
    out = [f"MOSSE CALCOLATE (BIG-BOB ha simulato {r['valutate']} combattimenti in {r.get('secondi')}s; slot da 1; "
           f"punteggio = corsa a 2 barrier, già pesato sulla risposta avversaria al {round(r['p_risposta'] * 100)}%):"]
    for n, mv in enumerate(r["mosse"]):
        what = " + ".join(f"{g['carta']} {g['corsia']} slot {g['slot']}" for g in mv["giocate"]) or "nessuna creatura"
        line = (f"{chr(65 + n)}) {what} ({mv['mana']} mana) → barrier avv {mv['barrier_avv']} · tue {mv['barrier_tue']}"
                f" · distrutte {mv['distrutte'][0]}-{mv['distrutte'][1]}" + (f" · {mv['vincitore']}" if mv["vincitore"] else "")
                + f" · punteggio {mv['punteggio']}")
        if mv["effetti"]:
            line += " · effetti simulati: " + "; ".join(mv["effetti"])
        out.append(line)
        w = mv.get("peggiore")
        if w:
            p = f" ({round(w['p'] * 100)}% in mano)" if isinstance(w.get("p"), (int, float)) else ""
            out.append(f"   risposta peggiore: {w['carta']}{p} {w['corsia']} slot {w['slot']} → barrier avv "
                       f"{w['barrier_avv']} · tue {w['barrier_tue']} · distrutte {w['distrutte'][0]}-{w['distrutte'][1]}"
                       + (f" · {w['vincitore']}" if w["vincitore"] else ""))
    if r.get("magie"):
        out.append("Magie giocabili (effetto non simulato, valutale tu e tieni conto del mana): " + ", ".join(r["magie"]))
    out.append("Le carte con effetti non riconosciuti sono simulate solo con attacco e vita: se un effetto cambia i "
               "numeri, ragionaci tu (o una simulate_combat).")
    return out
