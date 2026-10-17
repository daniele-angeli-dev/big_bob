"""Contatori della partita (carte nel mazzo e in mano, per entrambi) e stima di chi sta vincendo.

Contatori: se il gioco mostra il numero di carte nel mazzo lo usiamo (è la fonte più affidabile); altrimenti lo
calcoliamo dalle carte uscite dal mazzo. Le carte CREATE da effetti (carta del potere leggendario, carte generate da
Spellbook e simili) non sono uscite dal mazzo: vanno nelle liste "create" e non si contano.

Stima: una barra stile scacchi. Subito dopo ogni update_match c'è una stima rapida fatta coi numeri (barrier,
barrier distrutte, creature in campo, previsione del combattimento, carte in mano); dopo la risposta live Claude
la rifinisce con set_match_eval, ragionando anche su carte e location.
"""
from __future__ import annotations

import math
from collections import Counter

from origins import combat, store

DECK_SIZE = 25


def _subtract(a: Counter, b: Counter) -> Counter:
    out = Counter(a)
    for k, v in b.items():
        if k in out:
            out[k] = max(0, out[k] - v)
    return +out


def seen_mine(m: dict) -> Counter:
    """Le MIE carte uscite dal mazzo (in mano, giocate, scartate), senza quelle create da effetti."""
    seen = Counter(m.get("mia_mano", []) + m.get("miei_giocati", []) + m.get("miei_scartati", []))
    return _subtract(seen, Counter(m.get("miei_creati", [])))


def seen_opp(m: dict) -> Counter:
    """Le carte dell'avversario viste uscire dal suo mazzo (giocate, scartate), senza quelle create da effetti."""
    seen = Counter(m.get("avv_giocati", []) + m.get("avv_scartati", []))
    return _subtract(seen, Counter(m.get("avv_creati", [])))


def counters(m: dict) -> dict:
    """{'mio_mazzo', 'mia_mano', 'avv_mazzo', 'avv_mano'} con 'stimato' quando non letto dallo schermo."""
    my_hand = len(m.get("mia_mano") or [])
    my_deck_calc = max(0, DECK_SIZE - sum(seen_mine(m).values()))
    my_vis = m.get("mazzo_rimasto_visibile")
    opp_hand = m.get("avv_mano")
    opp_out = sum(seen_opp(m).values()) + (opp_hand or 0)
    opp_deck_calc = max(0, DECK_SIZE - opp_out) if opp_hand is not None or opp_out else None
    opp_vis = m.get("avv_mazzo_visibile")
    return {
        "mio_mazzo": my_vis if isinstance(my_vis, int) else my_deck_calc,
        "mio_mazzo_stimato": not isinstance(my_vis, int),
        "mia_mano": my_hand,
        "avv_mazzo": opp_vis if isinstance(opp_vis, int) else opp_deck_calc,
        "avv_mazzo_stimato": not isinstance(opp_vis, int),
        "avv_mano": opp_hand,
        "mie_create": len(m.get("miei_creati") or []),
        "avv_create": len(m.get("avv_creati") or []),
    }


def _fractions(vals, reinf) -> list[float]:
    vals = vals or [20, 20, 20]
    reinf = reinf or [False, False, False]
    out = []
    for i in range(3):
        v = vals[i] if i < len(vals) and isinstance(vals[i], (int, float)) else 20
        mx = 40 if (i < len(reinf) and reinf[i]) or v > 20 else 20
        out.append(max(0.0, min(1.0, v / mx)))
    return out


FATTORI = ("campo", "mano", "barrier")
LIVELLI = {"vantaggio": 1, "parità": 0, "parita": 0, "pari": 0, "svantaggio": -1}


def _sign(x: float, soglia: float) -> int:
    return 1 if x > soglia else (-1 if x < -soglia else 0)


def heuristic(m: dict) -> dict:
    """Stima rapida (senza Claude) della mia probabilità di vincere, in percentuale, con le voci che la spiegano e i tre
    fattori per la finestra (campo, mano, barrier: +1 vantaggio, 0 parità, -1 svantaggio, None = non si sa)."""
    by, to = m.get("distrutte_da_me") or 0, m.get("distrutte_a_me") or 0
    f: dict[str, int | None] = {"campo": None, "mano": None, "barrier": None}
    if by >= 2:
        return {"pct": 99, "motivo": "hai già distrutto 2 barrier", "fonte": "stima rapida", "fattori": {**f, "barrier": 1}}
    if to >= 2:
        return {"pct": 1, "motivo": "l'avversario ha già distrutto 2 barrier", "fonte": "stima rapida",
                "fattori": {**f, "barrier": -1}}
    mine = _fractions(m.get("barrier_mie"), m.get("rinforzate_mie"))
    opp = _fractions(m.get("barrier_avv"), m.get("rinforzate_avv"))
    score, parts = 0.0, []
    s = (by - to) * 1.2
    score += s
    sb = s
    if by or to:
        parts.append(f"barrier distrutte {by}-{to}")
    s = (min(mine) - min(opp)) * 1.0 + (sum(mine) - sum(opp)) / 3 * 0.6
    score += s
    sb += s
    f["barrier"] = _sign(sb, 0.15)
    if abs(s) > 0.1:
        parts.append("barrier avversarie più basse" if s > 0 else "le tue barrier sono più basse")
    if m.get("campo"):
        lanes = combat.normalize_board(m["campo"])
        bm = sum(u["atk"] + u["hp"] for ln in lanes for u in ln["mie"] if u)
        bo = sum(u["atk"] + u["hp"] for ln in lanes for u in ln["avv"] if u)
        s = (bm - bo) / (bm + bo + 6) * 0.8
        score += s
        sc = s
        if abs(s) > 0.1:
            parts.append("campo a tuo favore" if s > 0 else "campo a favore dell'avversario")
        try:
            res = combat.simulate(lanes, m.get("barrier_mie"), m.get("barrier_avv"), by, to)
            s = ((res["distrutte_da_te"] - by) - (res["distrutte_a_te"] - to)) * 0.8
            score += s
            sc += s
            if s:
                parts.append("il prossimo combattimento ti premia" if s > 0 else "il prossimo combattimento ti punisce")
        except Exception:  # noqa: BLE001
            pass
        f["campo"] = _sign(sc, 0.1)
    c = counters(m)
    if c["avv_mano"] is not None:
        s = (c["mia_mano"] - c["avv_mano"]) * 0.08
        f["mano"] = _sign(c["mia_mano"] - c["avv_mano"], 1)
        score += s
        if abs(c["mia_mano"] - c["avv_mano"]) >= 2:
            parts.append("più carte in mano" if s > 0 else "l'avversario ha più carte in mano")
    pct = 100 / (1 + math.exp(-score * 1.6))
    return {"pct": int(round(max(3, min(97, pct)))), "motivo": ", ".join(parts) or "partita in equilibrio",
            "fonte": "stima rapida", "fattori": f}


def current_eval(m: dict) -> dict:
    """La valutazione da mostrare: quella di Claude se è del round attuale, altrimenti la stima rapida."""
    v = m.get("valutazione") or {}
    h = heuristic(m)
    if v.get("pct") is not None and v.get("round") == m.get("turno"):
        f = dict(h.get("fattori") or {})
        f.update({k: x for k, x in (v.get("fattori") or {}).items() if k in FATTORI and x in (-1, 0, 1)})
        return {"pct": int(v["pct"]), "motivo": v.get("motivo", ""), "fonte": "BIG-BOB", "fattori": f}
    return h


def save_eval(pct: int, motivo: str = "", fattori: dict | None = None) -> dict:
    m = store.load("match")
    if not m:
        return {"errore": "nessuna partita attiva"}
    f = {}
    for k, val in (fattori or {}).items():
        lv = LIVELLI.get(str(val).strip().lower()) if not isinstance(val, int) else max(-1, min(1, val))
        if k in FATTORI and lv is not None:
            f[k] = lv
    m["valutazione"] = {"pct": max(1, min(99, int(pct))), "motivo": motivo.strip()[:200], "round": m.get("turno"),
                        "ora": store.now(), "fattori": f}
    store.save("match", m)
    return m["valutazione"]
