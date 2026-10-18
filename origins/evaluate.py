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


MANO_INIZIALE = 4


OFFSET_KEY = "contatori_offset_r1"  # nuova chiave: le correzioni imparate con la vecchia base (senza la pescata del
# round 1) si sommerebbero alla base nuova


def draw_offset(side: str) -> int:
    """Correzione imparata dai contatori letti sullo schermo (es. pescate extra fisse): 0 se non si sa."""
    try:
        v = int((store.load("config").get(OFFSET_KEY) or {}).get(side, 0))
        return max(-2, min(3, v))
    except (TypeError, ValueError):
        return 0


def _out_by_rules(turn, side: str) -> int:
    """Carte uscite dal mazzo come minimo secondo le regole: mano iniziale + una pescata a round, ANCHE al round 1
    (Daniele: senza la pescata del round 1 i mazzi risultavano sempre con una carta in più del valore vero)."""
    t = turn if isinstance(turn, int) and turn > 0 else 1
    return MANO_INIZIALE + t + draw_offset(side)


def _deck_estimate(m: dict, side: str, out_tracked: int | None) -> tuple[int | None, bool, str]:
    """(carte nel mazzo, stimato?, come). Le fonti, dalla più affidabile:
    1. il numero letto sullo schermo in QUESTO round;
    2. l'ultimo numero letto in un round precedente, meno una pescata per ogni round passato;
    3. il massimo tra le carte uscite secondo le regole (mano iniziale + 1 a round) e quelle viste uscire.
    Le stime 2 e 3 sono "almeno": si prende quella con più carte uscite (le pescate extra le alzano)."""
    turn = m.get("turno")
    vis = (m.get("mazzi_visti") or {}).get(side)
    if vis and vis.get("turno") == turn and isinstance(vis.get("carte"), int):
        return vis["carte"], False, "letto sullo schermo"
    outs = [(_out_by_rules(turn, side), "regole (4 iniziali + 1 a round, dal round 1)")]
    if out_tracked is not None:
        outs.append((out_tracked, "carte viste uscire"))
    if vis and isinstance(vis.get("carte"), int) and isinstance(vis.get("turno"), int) and isinstance(turn, int):
        outs.append((DECK_SIZE - vis["carte"] + max(0, turn - vis["turno"]), f"letto al round {vis['turno']} + pescate"))
    out, how = max(reversed(outs), key=lambda x: x[0])  # a parità vale la fonte più concreta (numero letto)
    return max(0, DECK_SIZE - out), True, how


MANO_MAX = 10


def _hand(m: dict, side: str, fallback: int | None) -> tuple[int | None, bool, str]:
    """(carte in mano, stimato?, come). Letto sullo schermo in questo round, altrimenti dall'ultimo numero letto:
    +1 pescata per ogni round passato, -1 per ogni carta giocata o scartata da allora (massimo 10)."""
    rd = m.get("mia_mano_letta" if side == "mio" else "avv_mano_letta")
    turn = m.get("turno")
    if not rd or not isinstance(rd.get("mano"), int):
        return fallback, False, ""
    if rd.get("turno") == turn:
        return rd["mano"], False, "letto sullo schermo"
    keys = ("miei_giocati", "miei_scartati") if side == "mio" else ("avv_giocati", "avv_scartati")
    out_now = sum(len(m.get(k) or []) for k in keys)
    rounds = max(0, turn - rd["turno"]) if isinstance(turn, int) and isinstance(rd.get("turno"), int) else 0
    est = rd["mano"] + rounds - max(0, out_now - (rd.get("uscite") or 0))
    return max(0, min(MANO_MAX, est)), True, f"letto al round {rd['turno']}, +1 a round, -1 per carta giocata"


def counters(m: dict) -> dict:
    """{'mio_mazzo', 'mia_mano', 'avv_mazzo', 'avv_mano'} con 'stimato' quando non letto dallo schermo in questo round."""
    my_hand, my_hand_est, my_hand_how = _hand(m, "mio", len(m.get("mia_mano") or []))
    # la carta del potere leggendario arriva in mano senza uscire dal mazzo: se Claude non l'ha segnata tra le
    # carte create, ne tolgo una dal conto (altrimenti il mazzo risulterebbe sempre con una carta in meno)
    my_out = sum(seen_mine(m).values()) - (0 if m.get("miei_creati") else 1)
    mine, mine_est, mine_how = _deck_estimate(m, "mio", max(0, my_out))
    opp_hand, opp_hand_est, opp_hand_how = _hand(m, "avv", m.get("avv_mano"))
    opp_out = None
    if opp_hand is not None or seen_opp(m):
        opp_out = max(0, sum(seen_opp(m).values()) + (opp_hand or 0) - (0 if m.get("avv_creati") else 1))
    opp, opp_est, opp_how = _deck_estimate(m, "avv", opp_out)
    return {
        "mio_mazzo": mine, "mio_mazzo_stimato": mine_est, "mio_mazzo_come": mine_how,
        "mia_mano": my_hand, "mia_mano_stimata": my_hand_est, "mia_mano_come": my_hand_how,
        "avv_mazzo": opp, "avv_mazzo_stimato": opp_est, "avv_mazzo_come": opp_how,
        "avv_mano": opp_hand, "avv_mano_stimata": opp_hand_est, "avv_mano_come": opp_hand_how,
        "mie_create": len(m.get("miei_creati") or []),
        "avv_create": len(m.get("avv_creati") or []),
    }


def learn_offset(m: dict, side: str, visible: int) -> None:
    """Quando il gioco mostra il numero di carte nel mazzo, imparo come si pesca (es. se anche al round 1):
    tengo la correzione più piccola osservata nei primi round (le pescate extra da effetti la alzerebbero)."""
    turn = m.get("turno")
    if not isinstance(turn, int) or turn < 1 or turn > 4 or not isinstance(visible, int):
        return
    obs = (DECK_SIZE - visible) - (MANO_INIZIALE + turn)
    if not -2 <= obs <= 3:
        return
    cfg = store.load("config")
    offs = dict(cfg.get(OFFSET_KEY) or {})
    seen = dict(cfg.get(OFFSET_KEY + "_visti") or {})
    prev = seen.get(side)
    seen[side] = obs if prev is None else min(prev, obs)
    if offs.get(side) != seen[side]:
        offs[side] = seen[side]
        cfg[OFFSET_KEY] = offs
    cfg[OFFSET_KEY + "_visti"] = seen
    store.save("config", cfg)


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


def heuristic(m: dict, raw: bool = False) -> dict:
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
    fonte = "stima rapida"
    if not raw:
        # calibrata sui risultati veri delle partite di Daniele (origins/tuning.py), quando ce ne sono abbastanza
        try:
            from origins import tuning
            cal = tuning.calibrate(pct)
            if cal != pct:
                pct, fonte = cal, "stima rapida calibrata"
        except Exception:  # noqa: BLE001
            pass
    return {"pct": int(round(max(3, min(97, pct)))), "motivo": ", ".join(parts) or "partita in equilibrio",
            "fonte": fonte, "fattori": f}


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
