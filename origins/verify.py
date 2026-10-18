"""Verifica del simulatore: il combattimento previsto torna con quello che è successo davvero?

Al round dopo (nuovo update_match) BIG-BOB ricostruisce il campo del round prima con le carte giocate in quel round
(quelle comparse nel campo nuovo, con le statistiche di base del database e gli effetti alla rivelazione riconosciuti),
simula il combattimento e confronta le barrier previste con quelle lette. Se non tornano, è una sorpresa da cui
imparare: di solito un effetto di carta o una regola che il simulatore non conosce.

Per non dare falsi allarmi la verifica si fa solo quando la ricostruzione è completa: nessuna magia giocata in quel
round (effetti sconosciuti) e tutte le creature giocate ancora visibili nel campo nuovo (nessuna morta in combattimento,
di cui non si saprebbe la posizione).
"""
from __future__ import annotations

from collections import Counter

from origins import combat, store


def _creature(name: str) -> bool:
    e = store.find("cards", name) or {}
    t = str(e.get("tipo") or "").lower()
    return e.get("attacco") is not None and "spell" not in t and "magia" not in t


def _names(row) -> list[str]:
    return [u["nome"] for u in row if u]


def check(old: dict, new: dict) -> dict | None:
    """{'turno', 'previste_tue', 'previste_avv', 'reali_tue', 'reali_avv', 'differenze': [...]} o None se non
    verificabile."""
    if not old.get("campo") or not new.get("campo"):
        return None
    t_old, t_new = old.get("turno"), new.get("turno")
    if not (isinstance(t_old, int) and isinstance(t_new, int) and t_new == t_old + 1):
        return None
    played_me = Counter(new.get("miei_giocati") or []) - Counter(old.get("miei_giocati") or [])
    played_opp = Counter(new.get("avv_giocati") or []) - Counter(old.get("avv_giocati") or [])
    if any(not _creature(c) for c in list(played_me) + list(played_opp)):
        return None  # una magia: effetto sconosciuto, la verifica non sarebbe affidabile
    before = combat.normalize_board(old["campo"])
    after = combat.normalize_board(new["campo"])
    lanes = combat.normalize_board(old["campo"])
    direct = []
    for side, played in (("mie", played_me), ("avv", played_opp)):
        left = Counter(played)
        for i in range(3):
            row_new, row_old = after[i][side], before[i][side]
            for k, u in enumerate(row_new):
                if not u:
                    continue
                was = row_old[k]["nome"] if k < len(row_old) and row_old[k] else None
                if was == u["nome"]:
                    continue
                if was is not None:
                    return None  # al suo posto c'era un'altra creatura: spostamenti che non so ricostruire
                if left.get(u["nome"], 0) <= 0:
                    return None  # una creatura nuova che non risulta giocata: spostata (Move) o letta male
                left[u["nome"]] -= 1
                combat.place(lanes, side, u["nome"], i, k + 1)  # statistiche di base (prima del combattimento)
                d, _ = combat.apply_reveal(lanes, side, i, k, u["nome"])
                direct += d
        if +left:
            return None  # qualche creatura giocata non è più visibile: è morta, non so dov'era
    res = combat.simulate(lanes, old.get("barrier_mie"), old.get("barrier_avv"), old.get("distrutte_da_me") or 0,
                          old.get("distrutte_a_me") or 0, direct)
    real_me, real_opp = new.get("barrier_mie"), new.get("barrier_avv")
    if not (isinstance(real_me, list) and isinstance(real_opp, list)):
        return None
    diffs = []
    for i in range(3):
        for who, pred, real in (("tua", res["barrier_tue"], real_me), ("avversaria", res["barrier_avv"], real_opp)):
            if i < len(real) and isinstance(real[i], (int, float)) and pred[i] != real[i]:
                diffs.append(f"barrier {who} {combat.LANES[i]}: prevista {pred[i]}, reale {real[i]}")
    return {"turno": t_old, "previste_tue": res["barrier_tue"], "previste_avv": res["barrier_avv"],
            "reali_tue": real_me, "reali_avv": real_opp, "differenze": diffs}


def round_good(old: dict, new: dict) -> bool | None:
    """Il round è andato bene per Daniele? Danno fatto (barrier avversarie, 20 per ogni distruzione) contro danno
    subito. None se non si può dire."""
    def dmg(before, after, destroyed_before, destroyed_after):
        if not (isinstance(before, list) and isinstance(after, list) and len(before) == len(after) == 3):
            return None
        tot = 20 * max(0, (destroyed_after or 0) - (destroyed_before or 0))
        for b, a in zip(before, after):
            if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a < b:
                tot += b - a
        return tot
    dealt = dmg(old.get("barrier_avv"), new.get("barrier_avv"), old.get("distrutte_da_me"), new.get("distrutte_da_me"))
    taken = dmg(old.get("barrier_mie"), new.get("barrier_mie"), old.get("distrutte_a_me"), new.get("distrutte_a_me"))
    if dealt is None or taken is None:
        return None
    return dealt >= taken
