"""Analisi della partita round per round, come la "Game Review" dei motori di scacchi, ed esercizi dagli errori.

Durante la partita update_match salva lo stato di ogni round (campo, mano, mana, barrier, location, chi rivela prima,
carte avversarie probabili). A fine partita BIG-BOB, per ogni round:
1. ricostruisce cosa ha giocato davvero Daniele (le creature comparse nel campo del round dopo);
2. cerca la mossa migliore con la ricerca di BIG-BOB e valuta con gli STESSI criteri la mossa giocata (stesse mani
   avversarie campionate, stesso valore del round dopo);
3. classifica la mossa in base al punteggio perso: migliore, buona, imprecisione, errore, errore grave.
Il punteggio è quello della corsa a 2 barrier di search.score: circa 25 punti = una barrier avversaria portata da
piena a 0, 80 = una barrier distrutta. Le magie non sono simulate: i round con magie giocate non si classificano.

Gli errori (imprecisione grave in su) diventano esercizi "trova la mossa", come i puzzle di tattica degli scacchi.
"""
from __future__ import annotations

import copy
import math
from collections import Counter

from origins import combat, store

CLASSI = [(3, "migliore"), (10, "buona"), (25, "imprecisione"), (50, "errore"), (10 ** 9, "errore grave")]
SIMBOLO = {"migliore": "★", "buona": "✓", "imprecisione": "?!", "errore": "?", "errore grave": "??"}
STATO_KEYS = ("turno", "campo", "mia_mano", "mana", "barrier_mie", "barrier_avv", "distrutte_da_me", "distrutte_a_me",
              "location", "rivela_prima", "rinforzate_mie", "rinforzate_avv", "miei_giocati", "miei_scartati",
              "avv_giocati", "leggendaria_mia", "carte_mie")


def classify(loss: float) -> str:
    return next(name for lim, name in CLASSI if loss <= lim)


def capture(m: dict) -> None:
    """Salva lo stato del round in m['stati_round'] (in update_match). Nello stesso round si aggiorna finché Daniele
    non ha giocato niente: l'ultimo stato prima delle giocate è quello su cui ha deciso."""
    t = m.get("turno")
    if not isinstance(t, int):
        return
    stati = m.setdefault("stati_round", {})
    prev = stati.get(str(t))
    if prev and len(m.get("miei_giocati") or []) > len(prev.get("miei_giocati") or []):
        return
    st = {k: copy.deepcopy(m.get(k)) for k in STATO_KEYS if m.get(k) is not None}
    try:
        from origins import archetype
        pr = archetype.predict(m)
        st["avv_probabili"] = [{"carta": x["carta"], "p_mano": x.get("p_mano")}
                               for x in (pr.get("giocabili") or pr.get("carte") or []) if x.get("giocabile", True)][:8]
        st["p_giocabile"] = pr.get("p_giocabile")
    except Exception:  # noqa: BLE001
        pass
    st.pop("carte_mie", None)  # il mazzo è già nella partita
    stati[str(t)] = st


def _creature(name: str) -> bool:
    e = store.find("cards", name) or {}
    t = str(e.get("tipo") or "").lower()
    return e.get("attacco") is not None and "spell" not in t and "magia" not in t


def played(s: dict, n: dict) -> dict:
    """Cosa ha giocato Daniele tra lo stato s (inizio round) e n (round dopo): {'giocate': [(carta, corsia, slot)],
    'magie': [...], 'verificabile': bool, 'nota'}."""
    diff = Counter((n.get("miei_giocati") or [])) - Counter((s.get("miei_giocati") or []))
    spells = [c for c in diff.elements() if not _creature(c)]
    want = Counter({c: k for c, k in diff.items() if _creature(c)})
    before, after = combat.normalize_board(s.get("campo")), combat.normalize_board(n.get("campo"))
    plays = []
    for i in range(3):
        row_b, row_a = before[i]["mie"], after[i]["mie"]
        for k, u in enumerate(row_a):
            if not u:
                continue
            was = row_b[k]["nome"] if k < len(row_b) and row_b[k] else None
            if was == u["nome"]:
                continue
            if want.get(u["nome"], 0) > 0:
                want[u["nome"]] -= 1
                plays.append((u["nome"], i, k))
    if +want:
        return {"giocate": plays, "magie": spells, "verificabile": False,
                "nota": "creature giocate e morte nello stesso round: posizione sconosciuta"}
    if spells:
        return {"giocate": plays, "magie": spells, "verificabile": False, "nota": "magie giocate: effetto non simulato"}
    return {"giocate": plays, "magie": [], "verificabile": True, "nota": ""}


def _txt(plays) -> str:
    return " + ".join(f"{c} {combat.LANES[i]} slot {k + 1}" for c, i, k in plays) or "nessuna creatura"


def _mv_txt(mv: dict) -> str:
    return " + ".join(f"{g['carta']} {g['corsia']} slot {g['slot']}" for g in mv["giocate"]) or "nessuna creatura"


def _win_pct(st: dict) -> int | None:
    try:
        from origins import evaluate
        return evaluate.heuristic(st).get("pct")
    except Exception:  # noqa: BLE001
        return None


def analyze(entry: dict, time_limit: float = 0.6) -> dict | None:
    """La revisione di una partita del registro (con 'stati_round'): None se non c'è niente da analizzare."""
    from origins import search
    stati = entry.get("stati_round") or {}
    turns = sorted(int(t) for t in stati)
    if len(turns) < 2:
        return None
    base = {"leggendaria_mia": entry.get("leggendaria_mia"), "carte_mie": entry.get("carte_mie")}
    rows = []
    for t in turns:
        s = {**base, **stati[str(t)]}
        row = {"turno": t, "pct": _win_pct(s)}
        nxt = stati.get(str(t + 1))
        if nxt is None or not s.get("mia_mano"):
            rows.append(row)
            continue
        p = played(s, nxt)
        row["giocata"] = _txt(p["giocate"]) + (" + magie " + ", ".join(p["magie"]) if p["magie"] else "")
        opp, pr = s.get("avv_probabili") or [], s.get("p_giocabile")
        try:
            best = search.search(s, opp, pr, top=3, time_limit=time_limit)
        except Exception:  # noqa: BLE001
            rows.append(row)
            continue
        if not best.get("mosse"):
            rows.append(row)
            continue
        top = best["mosse"][0]
        row["migliore"] = _mv_txt(top)
        row["alternative"] = [{"testo": _mv_txt(mv), "punteggio": mv["punteggio"]} for mv in best["mosse"]]
        if not p["verificabile"]:
            row["nota"] = p["nota"]
            rows.append(row)
            continue
        same = sorted(p["giocate"]) == sorted((g["carta"], combat.LANES.index(g["corsia"]), g["slot"] - 1)
                                              for g in top["giocate"])
        if same:
            mine = top["punteggio"]
        else:
            try:
                f = search.search(s, opp, pr, top=1, time_limit=time_limit, forced=p["giocate"])
                mine = f["mosse"][0]["punteggio"] if f.get("mosse") else None
            except Exception:  # noqa: BLE001
                mine = None
        if mine is None:
            rows.append(row)
            continue
        loss = max(0.0, round(top["punteggio"] - mine, 1))
        row.update(punteggio_migliore=top["punteggio"], punteggio_giocata=mine, perdita=loss, classe=classify(loss),
                   stato={k: s.get(k) for k in ("campo", "mia_mano", "mana", "barrier_mie", "barrier_avv",
                                                "distrutte_da_me", "distrutte_a_me", "location", "rivela_prima")},
                   avv_probabili=opp[:5])
        if mine > top["punteggio"]:
            row["nota"] = "la tua mossa vale più di quella trovata dalla ricerca"
        rows.append(row)
    graded = [r for r in rows if r.get("classe")]
    counts = Counter(r["classe"] for r in graded)
    acc = round(100 * sum(math.exp(-r["perdita"] / 30) for r in graded) / len(graded)) if graded else None
    # momento decisivo: la mossa che è costata di più, o il round in cui la stima è cambiata di più
    worst = max(graded, key=lambda r: r["perdita"], default=None)
    swing = None
    for a, b in zip(rows, rows[1:]):
        if isinstance(a.get("pct"), (int, float)) and isinstance(b.get("pct"), (int, float)):
            d = b["pct"] - a["pct"]
            if swing is None or abs(d) > abs(swing["delta"]):
                swing = {"turno": a["turno"], "delta": d}
    decisive = None
    if worst and worst["perdita"] > 25:
        decisive = {"turno": worst["turno"], "motivo": f"{worst['classe']}: giocata {worst['giocata']}, "
                                                        f"meglio {worst['migliore']} (−{worst['perdita']} punti)"}
    elif swing and abs(swing["delta"]) >= 15:
        decisive = {"turno": swing["turno"], "motivo": f"la stima di vittoria è passata da "
                    f"{next(r['pct'] for r in rows if r['turno'] == swing['turno'])}% a "
                    f"{next(r['pct'] for r in rows if r['turno'] == swing['turno']) + swing['delta']}% dopo questo round"}
    return {"round": rows, "precisione": acc, "conteggi": dict(counts), "momento_decisivo": decisive,
            "data": store.now()}


def review_pending(limit: int = 5, time_limit: float = 0.6) -> int:
    """Analizza le ultime partite del registro senza revisione (in background, a fine partita). Ritorna quante."""
    log = store.load("matches")
    todo = [m.get("id") or m.get("inizio") for m in log[-30:]
            if m.get("stati_round") and not m.get("revisione")][-limit:]
    done = {}
    for mid in todo:
        if store.FILES["match"].exists() and store.load("match"):
            break  # è iniziata una partita: la ricerca live ha la precedenza, si riprende alla fine
        entry = next((m for m in log if (m.get("id") or m.get("inizio")) == mid), None)
        if entry is None:
            continue
        rv = analyze(entry, time_limit)
        done[mid] = rv or {"round": [], "precisione": None, "conteggi": {}, "momento_decisivo": None,
                           "data": store.now(), "vuota": True}
    if not done:
        return 0
    log = store.load("matches")  # riletto: nel frattempo può essere finita un'altra partita
    for m in log:
        k = m.get("id") or m.get("inizio")
        if k in done and not m.get("revisione"):
            m["revisione"] = done[k]
    store.save("matches", log)
    return len(done)


def puzzles(limit: int = 30) -> list[dict]:
    """Esercizi 'trova la mossa' dai round classificati errore / errore grave / imprecisione grave (perdita ≥ 15)."""
    out = []
    for m in reversed(store.load("matches")):
        rv = m.get("revisione") or {}
        for r in rv.get("round") or []:
            if not r.get("classe") or r.get("perdita", 0) < 15 or not r.get("stato"):
                continue
            opts = [a["testo"] for a in r.get("alternative") or []]
            if r.get("giocata") and r["giocata"] not in opts:
                opts.append(r["giocata"])
            opts = list(dict.fromkeys(opts))
            if len(opts) < 2:
                continue
            out.append({"id": f"{m.get('id') or store.slug(str(m.get('inizio')))}-{r['turno']}",
                        "partita": f"{m.get('mio_mazzo', '?')} vs {m.get('avv_leggendaria') or '?'}",
                        "data": str(m.get("inizio", ""))[:10], "turno": r["turno"], "stato": r["stato"],
                        "avv_probabili": r.get("avv_probabili") or [], "opzioni": opts, "soluzione": r["migliore"],
                        "giocata": r["giocata"], "perdita": r["perdita"], "classe": r["classe"]})
            if len(out) >= limit:
                return out
    return out
