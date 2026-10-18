"""Taratura automatica dalle partite di Daniele.

1. Pesi della ricerca della mossa (search.score): a ogni round BIG-BOB registra i "fattori" dello stato (quanto sono
   vicine a 0 le barrier di ciascuno, barrier distrutte, valore del campo) e a fine partita il risultato. Con abbastanza
   partite stima con una regressione logistica quanto ogni fattore conta davvero per vincere, e i pesi del punteggio si
   spostano verso quei valori (sempre mescolati con quelli di partenza: poche partite non devono stravolgerli).
2. Barra di vantaggio: a ogni round si salva la percentuale data, a fine partita il risultato. Con abbastanza dati si
   calcola una correzione (scala di Platt) così che "70%" voglia dire davvero vincere circa 7 volte su 10.
"""
from __future__ import annotations

import json
import math

from origins import store

DEFAULT = {"chiusura": 25.0, "rischio": 28.0, "distrutta_da_te": 80.0, "distrutta_a_te": 90.0, "campo": 0.6}
MIN_PARTITE = 12
FILE = "taratura.json"


def _path():
    return store.DATA / FILE


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"campioni": [], "valutazioni": [], "pesi": None, "calibrazione": None}


def save(d: dict) -> None:
    _path().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def features(m: dict) -> list[float] | None:
    """[progresso sulle barrier avversarie, rischio sulle tue, distrutte da te, distrutte a te, campo] per uno stato."""
    bo, bm = m.get("barrier_avv"), m.get("barrier_mie")
    if not (isinstance(bo, list) and isinstance(bm, list) and len(bo) == len(bm) == 3):
        return None
    def closeness(bs):
        return sum(max(0.0, 1 - (b / (40 if b > 20 else 20))) for b in bs if isinstance(b, (int, float))) / 3
    field = 0.0
    if m.get("campo"):
        from origins import combat
        try:
            for ln in combat.normalize_board(m["campo"]):
                field += sum(u["atk"] + u["hp"] for u in ln["mie"] if u) - sum(u["atk"] + u["hp"] for u in ln["avv"] if u)
        except Exception:  # noqa: BLE001
            field = 0.0
    return [closeness(bo), closeness(bm), float(m.get("distrutte_da_me") or 0), float(m.get("distrutte_a_me") or 0),
            field / 20.0]


def _mid(m: dict) -> str:
    return str(m.get("id") or m.get("inizio"))


def record_round(m: dict) -> None:
    f = features(m)
    if f is None:
        return
    d = load()
    d["campioni"].append({"partita": _mid(m), "f": f, "esito": None})
    d["campioni"] = d["campioni"][-4000:]
    try:
        from origins import evaluate
        ev = evaluate.heuristic(m, raw=True).get("pct")  # la stima rapida non corretta: è lei che si calibra
    except Exception:  # noqa: BLE001
        ev = None
    if isinstance(ev, (int, float)) and 1 < ev < 99:
        d["valutazioni"].append({"partita": _mid(m), "pct": ev, "esito": None})
        d["valutazioni"] = d["valutazioni"][-4000:]
    save(d)


def record_result(m: dict, won: bool) -> dict:
    """A fine partita: etichetta i campioni della partita e ricalcola pesi e calibrazione."""
    d = load()
    for key in ("campioni", "valutazioni"):
        for x in d[key]:
            if x["partita"] == _mid(m) and x["esito"] is None:
                x["esito"] = 1 if won else 0
    d["pesi"] = fit_weights(d["campioni"])
    d["calibrazione"] = fit_calibration(d["valutazioni"])
    save(d)
    return {"pesi": d["pesi"], "calibrazione": d["calibrazione"]}


def _logistic(X, y, l2=1.0, iters=400, lr=0.3):
    n, k = len(X), len(X[0])
    w, b = [0.0] * k, 0.0
    for _ in range(iters):
        gw, gb = [0.0] * k, 0.0
        for xi, yi in zip(X, y):
            z = b + sum(a * c for a, c in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            e = p - yi
            gb += e
            for j in range(k):
                gw[j] += e * xi[j]
        b -= lr * gb / n
        for j in range(k):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
    return w, b


def fit_weights(samples: list[dict]) -> dict | None:
    lab = [s for s in samples if s.get("esito") is not None]
    games = {s["partita"] for s in lab}
    if len(games) < MIN_PARTITE:
        return None
    w, _ = _logistic([s["f"] for s in lab], [s["esito"] for s in lab])
    # coefficienti → pesi del punteggio, con il segno atteso; peso relativo rispetto alla chiusura
    coef = {"chiusura": w[0], "rischio": -w[1], "distrutta_da_te": w[2], "distrutta_a_te": -w[3], "campo": w[4]}
    if coef["chiusura"] <= 0.05:
        return None  # i dati non dicono niente di sensato: restano i pesi di partenza
    scale = DEFAULT["chiusura"] / coef["chiusura"]
    learned = {k: max(0.0, v * scale) for k, v in coef.items()}
    # un fattore che nelle partite non è quasi mai cambiato (es. nessuna barrier distrutta) non ha niente da insegnare:
    # la regressione lo porterebbe verso 0 solo per mancanza di dati, quindi resta il peso di partenza
    keys = ["chiusura", "rischio", "distrutta_da_te", "distrutta_a_te", "campo"]
    informative = {}
    for j, k in enumerate(keys):
        vals = [round(s["f"][j], 2) for s in lab]
        mode = max(set(vals), key=vals.count)
        informative[k] = sum(1 for v in vals if v != mode) >= 20
    trust = min(0.6, len(games) / 100)  # al massimo 60% di peso ai dati, e solo con tante partite
    out = {k: round(DEFAULT[k] * (1 - trust) + learned[k] * trust, 2) if informative[k] else DEFAULT[k]
           for k in DEFAULT}
    # distruggere una barrier è la condizione di vittoria: non deve mai valere meno di portarne una da piena a 0
    for k in ("distrutta_da_te", "distrutta_a_te"):
        out[k] = max(out[k], 2 * out["chiusura"])
    out["partite"] = len(games)
    return out


def weights() -> dict:
    p = load().get("pesi")
    return {k: (p or {}).get(k, v) for k, v in DEFAULT.items()}


def fit_calibration(evals: list[dict]) -> dict | None:
    lab = [e for e in evals if e.get("esito") is not None]
    if len({e["partita"] for e in lab}) < MIN_PARTITE:
        return None
    X = [[math.log(max(0.01, min(0.99, e["pct"] / 100)) / max(0.01, 1 - min(0.99, e["pct"] / 100)))] for e in lab]
    w, b = _logistic(X, [e["esito"] for e in lab], l2=0.1)
    return {"a": round(w[0], 3), "b": round(b, 3), "campioni": len(lab)}


def calibrate(pct: float) -> float:
    c = load().get("calibrazione")
    if not c or not isinstance(pct, (int, float)):
        return pct
    p = max(0.01, min(0.99, pct / 100))
    z = c["a"] * math.log(p / (1 - p)) + c["b"]
    return round(100 / (1 + math.exp(-z)))


def report() -> dict:
    d = load()
    lab = [e for e in d["valutazioni"] if e.get("esito") is not None]
    bins = []
    for lo in range(0, 100, 20):
        xs = [e for e in lab if lo <= e["pct"] < lo + 20 or (lo == 80 and e["pct"] == 100)]
        if xs:
            bins.append({"da": lo, "a": lo + 20, "detto": round(sum(e["pct"] for e in xs) / len(xs)),
                         "vero": round(100 * sum(e["esito"] for e in xs) / len(xs)), "n": len(xs)})
    return {"pesi": weights(), "pesi_tarati": d.get("pesi"), "calibrazione": d.get("calibrazione"), "fasce": bins}
