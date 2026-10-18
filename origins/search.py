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

TIME_LIMIT = 1.2   # secondi
MAX_CREATURE = 3   # creature giocate nello stesso round, al massimo
MIN_SLOTS = 3  # solo se il campo non dice quanti spazi ci sono (i lettori scrivono tutti gli slot, anche vuoti)


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
    seen = max([len(l["mie"]) for l in lanes] + [0])
    if seen:
        return seen
    try:
        return int(store.load("config").get("slot_per_corsia") or MIN_SLOTS)
    except (TypeError, ValueError):
        return MIN_SLOTS


def _free(lanes: list[dict], n_slots: int) -> list[tuple[int, int]]:
    out = []
    for i, lane in enumerate(lanes):
        for k in range(n_slots):
            if k >= len(lane["mie"]) or lane["mie"][k] is None:
                out.append((i, k))
    return out


_W = {"t": 0.0, "w": None}


def _weights() -> dict:
    """Pesi del punteggio (tarati dalle partite, vedi origins/tuning.py), riletti al massimo ogni 30 secondi."""
    if _W["w"] is None or time.time() - _W["t"] > 30:
        from origins import tuning
        _W.update(t=time.time(), w=tuning.weights())
    return _W["w"]


def score(res: dict, before: dict) -> float:
    """Punteggio della corsa a 2 barrier: alto = meglio per Daniele."""
    W = _weights()
    s = 0.0
    w = res.get("vincitore") or ""
    if w.startswith("VINCI TU"):
        s += 1000
    elif w.startswith("VINCE L'AVVERSARIO"):
        s -= 1000
    s += W["distrutta_da_te"] * (res["distrutte_da_te"] - before["by"]) - W["distrutta_a_te"] * (res["distrutte_a_te"] - before["to"])
    for i in range(3):
        bo, ao = before["bo"][i], res["barrier_avv"][i]
        if ao < bo:  # danno senza distruggerla: vale di più se la barrier era già bassa
            s += W["chiusura"] * (bo - ao) / max(bo, 1)
        bm, am = before["bm"][i], res["barrier_tue"][i]
        if am < bm:
            s -= W["rischio"] * (bm - am) / max(bm, 1)
    for lane in res["sopravvissuti"].values():
        for u in lane["mie"]:
            a, h = _stats(u)
            s += W["campo"] * (a + h)
        for u in lane["avv"]:
            a, h = _stats(u)
            s -= W["campo"] * (a + h)
    return round(s, 1)


def _stats(text: str) -> tuple[int, int]:
    try:
        a, h = text.rsplit(" ", 1)[1].split("/")
        return int(a), int(h)
    except (ValueError, IndexError):
        return 0, 0


def _play(lanes, plays, side="mie", mods: dict | None = None):
    """Applica le giocate [(carta, corsia, slot)] e restituisce (corsie, danni diretti, note). mods = modificatori
    delle location per le creature che entrano (quelle già in campo li hanno già nei numeri letti)."""
    lanes = copy.deepcopy(lanes)
    direct, notes = [], []
    for card, i, k in plays:
        combat.place(lanes, side, card, i, k + 1)
        if mods and i in mods:
            u = lanes[i][side][k]
            if u:
                u["atk"] += mods[i][0]
                u["hp"] += mods[i][1]
        d, n = combat.apply_reveal(lanes, side, i, k, card)
        direct += d
        notes += n
    return lanes, direct, notes


def _both(lanes0, mine, theirs, first: str, mods):
    """Le due giocate nell'ordine di rivelazione: chi rivela prima applica prima i suoi effetti."""
    order = [("avv", theirs), ("mie", mine)] if first == "avversario" else [("mie", mine), ("avv", theirs)]
    lanes, direct = lanes0, []
    for side, plays in order:
        lanes, d, _ = _play(lanes, plays, side, mods)
        direct += d
    return lanes, direct


_CACHE: dict = {}
_STATS = {"hit": 0, "miss": 0}


def _key(m, lanes, direct):
    """Firma di una posizione: come la tabella delle trasposizioni dei motori di scacchi, lo stesso campo raggiunto con
    giocate diverse (o in ordine diverso) si simula una volta sola."""
    try:
        return (tuple(tuple((u["nome"], u["atk"], u["hp"], tuple(u["kw"])) if u else None for u in ln[side])
                      for ln in lanes for side in ("mie", "avv")),
                tuple(tuple(sorted((k, v) for k, v in d.items() if isinstance(v, (int, float, str)))) for d in direct),
                tuple(m.get("barrier_mie") or ()), tuple(m.get("barrier_avv") or ()),
                m.get("distrutte_da_me") or 0, m.get("distrutte_a_me") or 0)
    except (TypeError, KeyError, AttributeError):
        return None


def _sim(m, lanes, direct):
    k = _key(m, lanes, direct)
    hit = _CACHE.get(k) if k is not None else None  # get: un'altra ricerca (analisi a fine partita) può svuotarla
    if hit is not None:
        _STATS["hit"] += 1
        return hit
    _STATS["miss"] += 1
    res = combat.simulate(lanes, m.get("barrier_mie"), m.get("barrier_avv"), m.get("distrutte_da_me") or 0,
                          m.get("distrutte_a_me") or 0, direct)
    if k is not None:
        if len(_CACHE) > 50000:
            _CACHE.clear()
        _CACHE[k] = res
    return res


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


MC_SAMPLES = 24      # mani avversarie campionate per ogni mossa candidata
LOOKAHEAD = 0.45     # quanto pesa il round dopo (una buona preparazione vale, ma meno di un risultato adesso)


def _sample_hands(opp_cards: list[dict], mana: int | None, n: int, seed: int = 11) -> list[list[str]]:
    """Mani avversarie plausibili: ogni carta compare con la sua probabilità di essere in mano (dalla previsione sul
    mazzo stimato). Solo le creature che può pagare, al massimo due per round."""
    import random
    rnd = random.Random(seed)
    cards = [c for c in opp_cards if c.get("carta") and _is_creature(_card(c["carta"]))
             and _cost(_card(c["carta"])) is not None and (mana is None or _cost(_card(c["carta"])) <= mana)]
    out = []
    for _ in range(n):
        hand = [c["carta"] for c in cards if rnd.random() < float(c.get("p_mano") or 0)]
        out.append(hand)
    return out


def _opp_best(m, lanes0, my_plays, hand, n_slots, before, first, mods, mana) -> tuple[float, dict | None, list]:
    """La giocata migliore per l'avversario con questa mano (fino a 2 creature, una alla volta nello spazio che fa più
    male): ritorna (punteggio per Daniele, risultato, giocate avversarie)."""
    plays: list = []
    spent = 0
    lanes, direct = _both(lanes0, my_plays, [], first, mods)
    res = _sim(m, lanes, direct)
    best_sc = score(res, before)
    for card in sorted(hand, key=lambda c: -((_card(c).get("attacco") or 0) + (_card(c).get("vita") or 0)))[:2]:
        cost = _cost(_card(card)) or 0
        if mana is not None and spent + cost > mana:
            continue
        cand = None
        for i in range(3):
            for k in range(n_slots):
                if any(p[1] == i and p[2] == k for p in plays):
                    continue
                row = lanes0[i]["avv"]
                if k < len(row) and row[k] is not None:
                    continue
                try_plays = plays + [(card, i, k)]
                ln, dr = _both(lanes0, my_plays, try_plays, first, mods)
                r = _sim(m, ln, dr)
                sc = score(r, before)
                if cand is None or sc < cand[0]:
                    cand = (sc, r, try_plays)
        if cand and cand[0] < best_sc:
            best_sc, res, plays = cand
            spent += cost
    return best_sc, res, plays


def _next_round_value(m, res, played: list[str], n_slots, mods, budget_s: float) -> tuple[float, str]:
    """Il round dopo: con il campo e le barrier come escono da questo combattimento, la mano senza le carte giocate e
    un mana in più, quanto vale la mia giocata migliore (senza risposta avversaria: è una stima della preparazione)."""
    t0 = time.time()
    mana = (m.get("mana") or 0) + 1 if isinstance(m.get("mana"), int) else None
    hand = list(m.get("mia_mano") or [])
    for c in played:
        if c in hand:
            hand.remove(c)
    nxt = {**m, "campo": res["campo"], "barrier_mie": res["barrier_tue"], "barrier_avv": res["barrier_avv"],
           "distrutte_da_me": res["distrutte_da_te"], "distrutte_a_me": res["distrutte_a_te"],
           "mia_mano": hand, "mana": min(10, mana) if mana else mana}
    lanes0 = combat.normalize_board(nxt["campo"])
    before = {"by": nxt["distrutte_da_me"], "to": nxt["distrutte_a_me"], "bo": list(nxt["barrier_avv"]),
              "bm": list(nxt["barrier_mie"])}
    sets, _ = candidates(nxt)
    free = _free(lanes0, n_slots)
    best, what = 0.0, ""
    for cards in sets[:40]:
        for spots in itertools.islice(itertools.permutations(free, len(cards)), 30):
            if time.time() - t0 > budget_s:
                return best, what
            plays = [(c, i, k) for c, (i, k) in zip(cards, spots)]
            ln, dr, _ = _play(lanes0, plays, "mie", mods)
            sc = score(_sim(nxt, ln, dr), before)
            if sc > best:
                best, what = sc, " + ".join(f"{c} {combat.LANES[i]}" for c, i, _ in plays)
    return best, what


MC_BATCH = 6  # campioni per giro: tutte le mosse candidate avanzano insieme (approfondimento iterativo)


def search(m: dict, opp_cards: list[dict] | None = None, p_reply: float | None = None, top: int = 3,
           time_limit: float = TIME_LIMIT, forced: list[tuple[str, int, int]] | None = None) -> dict:
    """{'mosse': [...], 'valutate': n, 'magie': [...], 'note': str}. opp_cards = carte avversarie giocabili con
    probabilità ({'carta', 'p_mano'}), p_reply = probabilità che giochi almeno una carta.
    forced = una giocata precisa [(carta, corsia 0-2, slot da 0)] da valutare con gli stessi criteri (serve
    all'analisi della partita: quanto valeva la mossa fatta davvero rispetto alla migliore)."""
    t0 = time.time()
    _CACHE.clear()
    _STATS.update(hit=0, miss=0)
    lanes0 = combat.normalize_board(m.get("campo") or {})
    n_slots = _slots(lanes0)
    before = {"by": m.get("distrutte_da_me") or 0, "to": m.get("distrutte_a_me") or 0,
              "bo": [b if isinstance(b, (int, float)) else 20 for b in (m.get("barrier_avv") or [20, 20, 20])],
              "bm": [b if isinstance(b, (int, float)) else 20 for b in (m.get("barrier_mie") or [20, 20, 20])]}
    sets, spells = candidates(m)
    free = _free(lanes0, n_slots)
    mods = combat.location_mods(m.get("location"))
    first = "avversario" if m.get("rivela_prima") == "avversario" else "io"
    mana = m.get("mana") if isinstance(m.get("mana"), int) else None
    evaluated: list[dict] = []
    n = 0
    stop = False
    if forced is not None:
        sets, stop = [], True
        lanes, direct, notes = _play(lanes0, list(forced), "mie", mods)
        evaluated.append({"giocate": list(forced), "res": _sim(m, lanes, direct), "note": notes, "lanes": lanes,
                          "direct": direct, "mana": sum(_cost(_card(c)) or 0 for c, _, _ in forced)})
        evaluated[0]["base"] = score(evaluated[0]["res"], before)
        n = 1
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
            lanes, direct, notes = _play(lanes0, plays, "mie", mods)
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
    samples = _sample_hands(opp_cards or [], mana, MC_SAMPLES)
    if replies and not any(samples):  # previsione senza probabilità: almeno le carte più probabili una per volta
        samples = [[c["carta"]] for c in replies]
    # le mani avversarie a giri di MC_BATCH per tutte le mosse insieme: se il tempo finisce, tutte le candidate sono
    # state messe alla prova sugli stessi campioni (come l'approfondimento iterativo dei motori di scacchi), invece
    # di avere le prime controllate a fondo e le ultime per niente
    acc = {id(ev): {"scores": [], "lost": [], "opp_win": [], "win": [], "worst": None} for ev in shortlist}
    for ev in shortlist:
        ev["controllata"] = not samples or not any(samples)
    timed_out = False
    for b0 in range(0, len(samples), MC_BATCH):
        for ev in shortlist:
            a = acc[id(ev)]
            for hand in samples[b0:b0 + MC_BATCH]:
                if time.time() - t0 > time_limit:
                    timed_out = True
                    break
                if not hand:
                    sc, res, plays = ev["base"], ev["res"], []
                else:
                    sc, res, plays = _opp_best(m, lanes0, ev["giocate"], hand, n_slots, before, first, mods, mana)
                    n += 1
                a["scores"].append(sc)
                a["lost"].append(res["distrutte_a_te"] > before["to"])
                a["opp_win"].append((res.get("vincitore") or "").startswith("VINCE L'AVVERSARIO"))
                a["win"].append((res.get("vincitore") or "").startswith("VINCI TU"))
                if plays and (a["worst"] is None or sc < a["worst"]["score"]):
                    c0, i0, k0 = plays[0]
                    a["worst"] = {"score": sc, "carta": " + ".join(p[0] for p in plays),
                                  "p": next((x.get("p_mano") for x in (opp_cards or []) if x.get("carta") == c0), None),
                                  "corsia": combat.LANES[i0], "slot": k0 + 1, "res": res}
            if timed_out:
                break
        if timed_out:
            break
    # tempo finito a metà giro: tutte le candidate si confrontano sullo stesso numero di mani (le stesse)
    common = min((len(acc[id(ev)]["scores"]) for ev in shortlist), default=0)
    for ev in shortlist:
        a = acc[id(ev)]
        for k in ("scores", "lost", "opp_win", "win"):
            a[k] = a[k][:common]
        scores, worst = a["scores"], a["worst"]
        k_s = len(scores)
        ev["controllata"] = bool(k_s) or not samples or not any(samples)
        mean = sum(scores) / k_s if k_s else ev["base"]
        ev["peggiore"] = worst
        ev["rischio"] = {"campioni": k_s, "perdi_barrier": round(sum(a["lost"]) / k_s, 2) if k_s else None,
                         "perdi_partita": round(sum(a["opp_win"]) / k_s, 2) if k_s else None,
                         "vinci_partita": round(sum(a["win"]) / k_s, 2) if k_s else None}
        # le mani campionate includono già "non gioca niente" con la sua probabilità
        ev["totale"] = round(mean if k_s else ev["base"] * (1 - pr) + (worst["score"] if worst else ev["base"]) * pr, 1)
    # il round dopo, solo per le migliori: una giocata che prepara la chiusura vale di più
    shortlist.sort(key=lambda x: (not x.get("controllata"), -x["totale"], -x["mana"]))
    for ev in shortlist[:4]:
        left = max(0.05, time_limit * 1.6 - (time.time() - t0))
        nv, what = _next_round_value(m, ev["res"], [c for c, _, _ in ev["giocate"]], n_slots, mods, min(0.12, left))
        ev["dopo"] = {"valore": round(nv, 1), "giocata": what}
        ev["totale"] = round(ev["totale"] + LOOKAHEAD * max(0.0, nv), 1)
    # le mosse non messe alla prova contro la risposta avversaria (tempo finito) vanno dopo quelle controllate: senza
    # la penalità della risposta sembrerebbero migliori di quello che sono
    shortlist.sort(key=lambda x: (not x.get("controllata"), -x["totale"], -x["mana"]))
    out = []
    for ev in shortlist[:top]:
        out.append({"giocate": [{"carta": c, "corsia": combat.LANES[i], "slot": k + 1} for c, i, k in ev["giocate"]],
                    "mana": ev["mana"], "punteggio": ev["totale"], "base": ev["base"],
                    "barrier_tue": ev["res"]["barrier_tue"], "barrier_avv": ev["res"]["barrier_avv"],
                    "distrutte": [ev["res"]["distrutte_da_te"], ev["res"]["distrutte_a_te"]],
                    "vincitore": ev["res"]["vincitore"], "effetti": ev["note"], "rischio": ev.get("rischio"),
                    "dopo": ev.get("dopo"),
                    "peggiore": ({k: v for k, v in ev["peggiore"].items() if k != "res"} | {
                        "barrier_tue": ev["peggiore"]["res"]["barrier_tue"],
                        "barrier_avv": ev["peggiore"]["res"]["barrier_avv"],
                        "distrutte": [ev["peggiore"]["res"]["distrutte_da_te"], ev["peggiore"]["res"]["distrutte_a_te"]],
                        "vincitore": ev["peggiore"]["res"]["vincitore"]}) if ev.get("peggiore") else None})
    dom = False
    if len(out) >= 1 and not spells:
        gap = out[0]["punteggio"] - (out[1]["punteggio"] if len(out) > 1 else -1e9)
        checked = shortlist[0].get("controllata") and (len(out) > 1 or not (opp_cards or []))
        dom = checked and gap >= max(15.0, abs(out[0]["punteggio"]) * 0.2) and not any(
            (store.find("cards", g["carta"]) or {}).get("testo") and not combat.effects(store.find("cards", g["carta"]))
            and "reveal" in str((store.find("cards", g["carta"]) or {}).get("testo", "")).lower()
            for g in out[0]["giocate"])
    return {"mosse": out, "valutate": n, "magie": spells, "secondi": round(time.time() - t0, 2),
            "p_risposta": round(pr, 2), "dominante": dom and forced is None,
            "cache": {"riusate": _STATS["hit"], "simulate": _STATS["miss"]}, "location": {combat.LANES[i]: v[2] for i, v in mods.items()},
            "rivela_prima": first}


def lines(r: dict) -> list[str]:
    """Le righe MOSSE CALCOLATE per update_match."""
    if not r or not r.get("mosse"):
        return []
    extra = []
    if r.get("location"):
        extra.append("location simulate: " + ", ".join(f"{k} {v}" for k, v in r["location"].items()))
    extra.append(f"rivela prima: {'avversario' if r.get('rivela_prima') == 'avversario' else 'tu'}")
    out = [f"MOSSE CALCOLATE (BIG-BOB ha simulato {r['valutate']} combattimenti in {r.get('secondi')}s; slot da 1; "
           "punteggio = corsa a 2 barrier: media su mani avversarie probabili + metà del valore del round dopo; "
           + "; ".join(extra) + "):"]
    for n, mv in enumerate(r["mosse"]):
        what = " + ".join(f"{g['carta']} {g['corsia']} slot {g['slot']}" for g in mv["giocate"]) or "nessuna creatura"
        line = (f"{chr(65 + n)}) {what} ({mv['mana']} mana) → barrier avv {mv['barrier_avv']} · tue {mv['barrier_tue']}"
                f" · distrutte {mv['distrutte'][0]}-{mv['distrutte'][1]}" + (f" · {mv['vincitore']}" if mv["vincitore"] else "")
                + f" · punteggio {mv['punteggio']}")
        if mv["effetti"]:
            line += " · effetti simulati: " + "; ".join(mv["effetti"])
        rk = mv.get("rischio") or {}
        if rk.get("campioni"):
            line += (f" · su {rk['campioni']} mani avversarie possibili: perdi una barrier "
                     f"{round(rk['perdi_barrier'] * 100)}%, perdi la partita {round(rk['perdi_partita'] * 100)}%")
        if (mv.get("dopo") or {}).get("giocata"):
            line += f" · round dopo: {mv['dopo']['giocata']} (valore {mv['dopo']['valore']})"
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
