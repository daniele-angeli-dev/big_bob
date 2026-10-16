"""Laboratorio: mulligan e simulazioni in solitario (Monte Carlo) di un mazzo.

Ipotesi (dal regolamento ricostruito): mano iniziale 4, mulligan libero (le carte cambiate tornano nel
mazzo e si ripescano), 1 pescata a round dal round 1, mana 2 al round 1 poi +1 fino a 10, non si accumula.
La carta del potere leggendario non è nel mazzo e non è simulata.
"""
from __future__ import annotations

import itertools
import random

from origins import odds, store

HAND, DRAW_PER_ROUND, MANA_R1, MANA_MAX = 4, 1, 2, 10


def _rules():
    r = store.load("config").get("regole", {})
    return (r.get("mano_iniziale", HAND), r.get("pescate_per_turno", DRAW_PER_ROUND))


def _info(name: str) -> dict:
    e = store.find("cards", name) or {}
    return {"nome": e.get("nome", name), "costo": e.get("costo") if isinstance(e.get("costo"), (int, float)) else 99,
            "atk": e.get("attacco") or 0, "hp": e.get("vita") or 0}


def mana_at(r: int) -> int:
    return min(MANA_MAX, MANA_R1 + r - 1)


def best_spend(hand: list[dict], mana: int) -> tuple[int, list[int]]:
    """Massimo mana spendibile con le carte in mano (piccolo zaino; a parità più carte)."""
    best = (0, 0, [])
    n = len(hand)
    for k in range(1, min(n, 6) + 1):
        for comb in itertools.combinations(range(n), k):
            c = sum(hand[i]["costo"] for i in comb)
            if c <= mana and (c, k) > best[:2]:
                best = (c, k, list(comb))
    return best[0], best[2]


def _deck_list(legendary: str, cards: list[str]) -> list[dict]:
    full = odds.deck_counts(store.canonical(legendary), [store.canonical(c) for c in cards])
    return [_info(n) for n, k in full.items() for _ in range(k)]


def mulligan_eval(legendary: str, cards: list[str], hand: list[str], sims: int = 1100, rounds: int = 3,
                  seed: int = 7) -> dict:
    """Valuta tutte le scelte keep/replace della mano iniziale: probabilità di avere una giocata nei
    round 1..rounds e mana medio speso."""
    rnd = random.Random(seed)
    deck = _deck_list(legendary, cards)
    hand_i = [_info(store.canonical(h)) for h in hand]
    # togli dal mazzo le carte della mano
    pool = deck[:]
    for h in hand_i:
        for k, d in enumerate(pool):
            if d["nome"] == h["nome"]:
                pool.pop(k)
                break
    results = []
    for mask in range(1 << len(hand_i)):
        keep = [h for i, h in enumerate(hand_i) if mask >> i & 1]
        back = [h for i, h in enumerate(hand_i) if not mask >> i & 1]
        play = [0] * rounds
        spent = 0.0
        for _ in range(sims):
            d = pool + back
            rnd.shuffle(d)
            cur = keep + d[:len(back)]
            d = d[len(back):]
            for r in range(1, rounds + 1):
                cur = cur + d[:DRAW_PER_ROUND]
                d = d[DRAW_PER_ROUND:]
                s, idx = best_spend(cur, mana_at(r))
                if s > 0:
                    play[r - 1] += 1
                spent += s
                cur = [c for i, c in enumerate(cur) if i not in idx]
        results.append({"tieni": [h["nome"] for h in keep], "cambia": [h["nome"] for h in back],
                        "p_giocata_per_round": [round(p / sims, 3) for p in play],
                        "mana_medio_speso_r1_r%d" % rounds: round(spent / sims, 2)})
    key = "mana_medio_speso_r1_r%d" % rounds
    results.sort(key=lambda x: (-(sum(x["p_giocata_per_round"]) + x[key] / 10), len(x["cambia"])))
    return {"mano": [h["nome"] for h in hand_i], "migliori": results[:3],
            "tenere_tutto": next(x for x in results if not x["cambia"]),
            "ipotesi": "mulligan libero, carte cambiate rimescolate nel mazzo, 1 pescata a round, mana 2,3,4…"}


def deck_lab(legendary: str, cards: list[str], games: int = 2000, rounds: int = 6, seed: int = 11) -> dict:
    """Partite in solitario: giocata ogni round, mana sfruttato, attacco in campo per round."""
    rnd = random.Random(seed)
    deck = _deck_list(legendary, cards)
    hand_n, _ = _rules()
    play = [0] * rounds
    full_use = [0] * rounds
    spent = [0.0] * rounds
    board_atk = [0.0] * rounds
    leg_seen = [0] * rounds
    for _ in range(games):
        d = deck[:]
        rnd.shuffle(d)
        hand, d = d[:hand_n], d[hand_n:]
        # mulligan semplice: cambia le carte che costano più del mana del round 3
        back = [c for c in hand if c["costo"] > mana_at(3)]
        if back:
            hand = [c for c in hand if c["costo"] <= mana_at(3)]
            d = d + back
            rnd.shuffle(d)
            hand, d = hand + d[:len(back)], d[len(back):]
        atk = 0
        seen_leg = False
        for r in range(1, rounds + 1):
            hand, d = hand + d[:DRAW_PER_ROUND], d[DRAW_PER_ROUND:]
            m = mana_at(r)
            s, idx = best_spend(hand, m)
            if s:
                play[r - 1] += 1
            if s == m:
                full_use[r - 1] += 1
            spent[r - 1] += s
            atk += sum(hand[i]["atk"] for i in idx)
            board_atk[r - 1] += atk
            seen_leg = seen_leg or any(c["nome"] == store.canonical(legendary) for c in hand)
            leg_seen[r - 1] += seen_leg
            hand = [c for i, c in enumerate(hand) if i not in idx]
    g = float(games)
    return {
        "mazzo": f"{store.canonical(legendary)} + {len(cards)} carte",
        "round": list(range(1, rounds + 1)),
        "mana": [mana_at(r) for r in range(1, rounds + 1)],
        "p_almeno_una_giocata": [round(x / g, 3) for x in play],
        "p_mana_tutto_usato": [round(x / g, 3) for x in full_use],
        "mana_medio_speso": [round(x / g, 2) for x in spent],
        "attacco_in_campo_medio": [round(x / g, 1) for x in board_atk],
        "p_leggendaria_pescata_entro": [round(x / g, 3) for x in leg_seen],
        "ipotesi": "nessuna creatura muore, giocata che massimizza il mana speso; utile per confrontare mazzi, "
                   "non per prevedere le partite",
    }
