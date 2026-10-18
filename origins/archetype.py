"""Riconoscimento del mazzo avversario: dalle carte che gioca, confrontate con i mazzi del meta (OriginsMeta, le tue
partite, il cervello comune), quale lista sta usando e che tipo di mazzo è.

Tipi di base: Aggro, Midrange, Control, Combo. Il Midrange può pendere verso l'aggro o verso il control; in più ci
sono i sottotipi del meta (Swarm, Tempo, Big, Ramp, Discard…).

Modello: ogni mazzo candidato (stessa leggendaria) parte da un peso a priori (quante volte visto, peso della lista
community); ogni carta avversaria vista moltiplica per 1 se è nella lista, per FUORI_LISTA se non c'è (una carta
diversa può essere una variante: abbassa molto, ma non esclude). Il tipo di un mazzo viene dal tag del sito; se manca
lo stimo dalla curva (costo medio, quante magie, quanto sono grosse le creature).
"""
from __future__ import annotations

import math

from origins import store

FUORI_LISTA = 0.08  # quanto pesa una carta vista che non è nella lista (varianti, tech card)
MIN_P = 0.01

BASE = ("Aggro", "Midrange", "Control", "Combo")

# tag di OriginsMeta → (tipo di base, inclinazione per il midrange, sottotipo)
TAG = {
    "aggro": ("Aggro", "", ""),
    "swarm / go wide": ("Aggro", "", "Swarm"),
    "swarm": ("Aggro", "", "Swarm"),
    "tempo": ("Midrange", "aggro", "Tempo"),
    "midrange": ("Midrange", "", ""),
    "big / big bodies": ("Midrange", "control", "Big"),
    "evil / big bodies": ("Midrange", "control", "Big"),
    "big": ("Midrange", "control", "Big"),
    "ramp": ("Control", "", "Ramp"),
    "control": ("Control", "", ""),
    "discard": ("Combo", "", "Discard"),
    "combo": ("Combo", "", ""),
}

CONTRO = {
    "Aggro": "difendi presto: blocca le corsie dove attacca, scambia le creature e non lasciare spazi vuoti; "
             "regge poco sul lungo, quindi il tempo gioca per te",
    "Midrange (aggro)": "tieni le corsie coperte nei primi round, poi vinci gli scambi con creature più grosse",
    "Midrange": "vince gli scambi di valore: scegli 1-2 corsie dove essere più forte invece di difendere tutto",
    "Midrange (control)": "metti pressione presto, prima che le sue creature grosse prendano il controllo",
    "Control": "pressione su più corsie e presto, senza mettere tutto in una sola (ha rimozioni); "
               "sul lungo è favorito",
    "Combo": "chiudi in fretta e tieni una risposta per il suo pezzo chiave; non dargli round tranquilli",
}


def label(base: str, lean: str = "") -> str:
    return f"{base} ({lean})" if base == "Midrange" and lean else base


def deck_type(deck: dict) -> dict:
    """{'base', 'inclinazione', 'sottotipo', 'etichetta', 'da'} per un mazzo del meta."""
    tag = (deck.get("archetipo") or deck.get("tipo_mazzo") or "").strip().lower()
    if tag in TAG:
        base, lean, sub = TAG[tag]
        return {"base": base, "inclinazione": lean, "sottotipo": sub, "etichetta": label(base, lean),
                "da": "tag del sito"}
    return {**curve_type(deck.get("carte") or []), "da": "curva"}


def curve_type(cards: list[str]) -> dict:
    """Tipo stimato dalla curva quando il mazzo non ha un tag."""
    costs, spells, bodies = [], 0, []
    for c in dict.fromkeys(cards):
        e = store.find("cards", c) or {}
        if isinstance(e.get("costo"), (int, float)):
            costs.append(e["costo"])
        if str(e.get("tipo", "")).lower().startswith("spell"):
            spells += 1
        elif isinstance(e.get("attacco"), (int, float)) and isinstance(e.get("vita"), (int, float)):
            bodies.append(e["attacco"] + e["vita"])
    if len(costs) < 3:
        return {"base": "Midrange", "inclinazione": "", "sottotipo": "", "etichetta": "Midrange", "incerto": True}
    avg = sum(costs) / len(costs)
    share_spells = spells / max(1, len(set(cards)))
    if avg <= 2.8 and share_spells < 0.4:
        base, lean = "Aggro", ""
    elif avg >= 4.3 or share_spells >= 0.45:
        base, lean = "Control", ""
    else:
        base, lean = "Midrange", "aggro" if avg < 3.5 else "control"
    return {"base": base, "inclinazione": lean, "sottotipo": "", "etichetta": label(base, lean),
            "costo_medio": round(avg, 1)}


def _prior(a: dict) -> float:
    return a.get("volte_visto", 0) + 0.5 * (a.get("community") or 0) + 1


def _posterior(cands: list[dict], seen: list[str]) -> list[tuple[float, dict, list[str]]]:
    """[(probabilità, mazzo, carte viste fuori lista)] dal più probabile."""
    scored = []
    for a in cands:
        pool = {store.slug(c) for c in a["carte"]}
        miss = [c for c in seen if store.slug(c) not in pool]
        scored.append((math.log(_prior(a)) + len(miss) * math.log(FUORI_LISTA), a, miss))
    mx = max(s for s, _, _ in scored)
    tot = sum(math.exp(s - mx) for s, _, _ in scored)
    return sorted(((math.exp(s - mx) / tot, a, miss) for s, a, miss in scored), key=lambda x: -x[0])


def _candidates(m: dict, meta: list[dict]) -> tuple[str, list[str], list[dict]]:
    from origins import evaluate
    leg = (m.get("avv_leggendaria") or "").strip()
    seen = [c for c in evaluate.seen_opp(m) if store.slug(c) != store.slug(leg)]
    cands = [a for a in meta if a.get("carte") and (not leg or store.slug(a.get("leggendaria", "")) == store.slug(leg))]
    return leg, seen, cands


def _identify(m: dict, meta: list[dict] | None = None, top: int = 3) -> dict:
    """Mazzi più probabili dell'avversario e tipo, dalle carte viste nella partita m."""
    meta = meta if meta is not None else store.load("meta")
    leg, seen, cands = _candidates(m, meta)
    out = {"leggendaria": leg or None, "carte_viste": len(seen), "mazzi": [], "tipi": {}, "tipo": None}
    if not cands:
        if len(seen) >= 3:
            t = curve_type(seen)
            out["tipo"] = {**t, "p": None, "da": "curva delle carte viste (nessun mazzo del meta per questa leggendaria)"}
            out["contro"] = CONTRO.get(t["etichetta"], CONTRO.get(t["base"], ""))
        return out
    post = _posterior(cands, seen)
    tipi: dict[str, float] = {}
    for p, a, _ in post:
        t = deck_type(a)
        tipi[t["etichetta"]] = tipi.get(t["etichetta"], 0) + p
    for p, a, miss in post[:top]:
        if p < MIN_P and out["mazzi"]:
            break
        t = deck_type(a)
        pool_seen = {store.slug(c) for c in seen}
        out["mazzi"].append({
            "nome": a.get("nome"), "p": round(p, 3), "tipo": t["etichetta"], "sottotipo": t.get("sottotipo") or None,
            "fonte": a.get("fonte") or "tue partite",
            "carte_in_comune": len(seen) - len(miss), "fuori_lista": miss[:5],
            "da_aspettarsi": [c for c in a["carte"] if store.slug(c) not in pool_seen][:6],
        })
    best_label = max(tipi, key=tipi.get)
    best = post[0][1]
    bt = deck_type(best)
    out["tipi"] = {k: round(v, 3) for k, v in sorted(tipi.items(), key=lambda kv: -kv[1])}
    out["tipo"] = {"etichetta": best_label, "p": round(tipi[best_label], 3),
                   "sottotipo": bt.get("sottotipo") if bt["etichetta"] == best_label else None,
                   "da": bt.get("da")}
    out["contro"] = CONTRO.get(best_label, CONTRO.get(best_label.split(" ")[0], ""))
    if not seen:
        out["nota"] = "nessuna carta avversaria vista: stima solo dalla leggendaria e dalla diffusione nel meta"
    return out


def summary(ident: dict) -> str:
    """Una riga per update_match e per la finestra."""
    t = ident.get("tipo")
    if not t:
        return ""
    pct = f" {round(t['p'] * 100)}%" if t.get("p") is not None else " (stima dalla curva)"
    sub = f", {t['sottotipo']}" if t.get("sottotipo") else ""
    parts = [f"tipo {t['etichetta']}{sub}{pct}"]
    if ident.get("mazzi"):
        d = ident["mazzi"][0]
        parts.insert(0, f"{d['nome']} {round(d['p'] * 100)}%")
        if d.get("da_aspettarsi"):
            parts.append("aspettati " + ", ".join(d["da_aspettarsi"][:4]))
    return " · ".join(parts)


def short(ident: dict) -> dict | None:
    """Per la finestra: {'tipo', 'p', 'mazzo', 'p_mazzo'}."""
    t = ident.get("tipo")
    if not t:
        return None
    d = (ident.get("mazzi") or [None])[0]
    return {"tipo": t["etichetta"] + (f" · {t['sottotipo']}" if t.get("sottotipo") else ""),
            "p": round(t["p"] * 100) if t.get("p") is not None else None,
            "mazzo": d["nome"] if d else None, "p_mazzo": round(d["p"] * 100) if d else None,
            "viste": ident.get("carte_viste", 0), "probabili": ident.get("probabili") or []}


# ============================================================================ previsione delle carte avversarie

PIANO = {
    "Aggro": "riempie in fretta le corsie con creature economiche e punta la tua barrier più bassa o una corsia vuota",
    "Midrange (aggro)": "mette pressione con creature medie fin dai primi round e cerca scambi favorevoli",
    "Midrange": "occupa le corsie con creature solide e cerca di vincere gli scambi, senza fretta",
    "Midrange (control)": "si difende nei primi round e cala creature grosse dal round 5-6",
    "Control": "trattiene magie e rimozioni per rispondere a ciò che giochi; le minacce grosse arrivano a fine partita",
    "Combo": "rallenta e cerca i pezzi della combo, poi prova a chiudere tutto in un round",
}
DANNO_RE = ("damage", "danni", "danno", "destroy", "distrugg", "deal ")


def _card(name: str) -> dict:
    return store.find("cards", name) or {}


def _danger(e: dict) -> float:
    att = e.get("attacco") if isinstance(e.get("attacco"), (int, float)) else 0
    txt = str(e.get("testo") or "").lower()
    return att + (3 if any(k in txt for k in DANNO_RE) else 0)


def _target(m: dict, label: str) -> str:
    """La tua corsia più esposta, per i mazzi che spingono (aggro / midrange aggro)."""
    if not label.startswith(("Aggro", "Midrange (aggro)", "Midrange")):
        return ""
    from origins import combat
    vals = m.get("barrier_mie") or []
    if len(vals) < 3 or not all(isinstance(v, (int, float)) for v in vals[:3]):
        return ""
    names = ["sinistra", "centro", "destra"]
    blockers = [0, 0, 0]
    if m.get("campo"):
        try:
            lanes = combat.normalize_board(m["campo"])
            blockers = [sum(1 for u in ln["mie"] if u) for ln in lanes[:3]]
        except Exception:  # noqa: BLE001
            pass
    i = min(range(3), key=lambda k: (vals[k] + 8 * blockers[k], k))
    return f"la tua corsia {names[i]} (barrier {vals[i]}{', nessun blocco' if not blockers[i] else ''})"


def _card_rounds() -> dict[str, float]:
    """Round medio in cui ogni carta viene giocata (statistiche di OriginsMeta), se disponibile."""
    try:
        from origins import originsmeta
        st = originsmeta.load_state().get("statistiche") or {}
        rows = []
        for key in ("statistiche", "piu_giocati"):
            rows += (((st.get(key) or {}).get("interpretate") or {}).get("carte") or {}).get("righe") or []
        return {store.slug(r["nome"]): float(r["round_medio"]) for r in rows
                if r.get("nome") and isinstance(r.get("round_medio"), (int, float)) and 0 < r["round_medio"] < 20}
    except Exception:  # noqa: BLE001
        return {}


def _timing(cost, mana, avg_round, turn, label: str) -> float:
    """Quanto è probabile che una carta che ha in mano venga giocata proprio ora (0-1): conta quanto il costo sfrutta
    il mana del round, il round in cui di solito si gioca (OriginsMeta) e il tipo di mazzo."""
    w = 1.0
    if isinstance(cost, (int, float)) and isinstance(mana, int):
        spread = 2.5 if label.startswith("Aggro") else 1.6
        w *= math.exp(-((mana - cost) ** 2) / (2 * spread ** 2))
        if label.startswith("Aggro") and cost <= 3:
            w = max(w, 0.8)  # l'aggro gioca le carte economiche appena può
    if isinstance(turn, int):  # round tipico sconosciuto = valore medio, così chi "è nel suo round" passa davanti
        w *= math.exp(-((turn - avg_round) ** 2) / (2 * 2.0 ** 2)) if avg_round else 0.6
    return w


def _predict(m: dict, meta: list[dict] | None = None, top: int = 6) -> dict:
    """Cosa ha probabilmente in mano l'avversario e cosa può giocare in questo round, dal mazzo stimato."""
    from origins import odds
    meta = meta if meta is not None else store.load("meta")
    leg, seen, cands = _candidates(m, meta)
    ident = identify(m, meta)
    hand = m.get("avv_mano")
    mana = m.get("mana") if isinstance(m.get("mana"), int) else None
    out = {"mana": mana, "mano": hand, "carte": [], "giocabili": [], "p_giocabile": None, "minaccia": None,
           "piano": None, "bersaglio": "", "tipo": (ident.get("tipo") or {}).get("etichetta")}
    label = out["tipo"] or ""
    if label:
        out["piano"] = PIANO.get(label) or PIANO.get(label.split(" ")[0])
        out["bersaglio"] = _target(m, label)
    if not cands or not isinstance(hand, int) or hand <= 0:
        return out
    from origins import evaluate
    seen_ct = {store.slug(k): v for k, v in evaluate.seen_opp(m).items()}
    unseen = max(odds.DECK_SIZE - sum(seen_ct.values()), hand)
    agg: dict[str, dict] = {}
    p_play = 0.0
    for p, a, _ in _posterior(cands, seen):
        if p < MIN_P:
            continue
        full = odds.deck_counts(a.get("leggendaria") or leg, a["carte"])
        playable_left = 0
        for c, copies in full.items():
            left = copies - seen_ct.get(store.slug(c), 0)
            if left <= 0:
                continue
            e = _card(c)
            cost = e.get("costo") if isinstance(e.get("costo"), (int, float)) else None
            if mana is not None and cost is not None and cost <= mana:
                playable_left += left
            x = agg.setdefault(store.slug(c), {"carta": e.get("nome") or c, "p_mano": 0.0, "costo": cost,
                                               "attacco": e.get("attacco"), "vita": e.get("vita"),
                                               "tipo": e.get("tipo"), "pericolo": _danger(e)})
            x["p_mano"] += p * odds.p_at_least_one(unseen, left, hand)
        if mana is not None:
            p_play += p * odds.p_at_least_one(unseen, playable_left, hand)
    cards = sorted(agg.values(), key=lambda x: -x["p_mano"])
    rounds = _card_rounds()
    turn = m.get("turno") if isinstance(m.get("turno"), int) else None
    for x in cards:
        x["p_mano"] = round(x["p_mano"], 3)
        x["giocabile"] = (mana is not None and x["costo"] is not None and x["costo"] <= mana)
        x["round_medio"] = rounds.get(store.slug(x["carta"]))
        x["ora"] = round(x["p_mano"] * _timing(x["costo"], mana, x["round_medio"], turn, label), 3) \
            if x["giocabile"] else 0.0
    out["carte"] = cards[:top]
    out["tutte"] = [{k: x[k] for k in ("carta", "p_mano", "costo")} for x in cards if x["p_mano"] >= 0.03][:16]
    # le giocate più probabili adesso: in mano, giocabili, e "giuste" per il round e il tipo di mazzo
    out["giocabili"] = sorted([x for x in cards if x["giocabile"] and x["p_mano"] >= 0.1],
                              key=lambda x: -x["ora"])[:4]
    if mana is not None:
        out["p_giocabile"] = round(p_play, 3)
    threats = [x for x in cards if (x["giocabile"] or mana is None) and x["p_mano"] >= 0.15 and x["pericolo"] > 0]
    if threats:
        t = max(threats, key=lambda x: (x["ora"] or x["p_mano"] * 0.5) * x["pericolo"])
        out["minaccia"] = {"carta": t["carta"], "p_mano": t["p_mano"], "attacco": t["attacco"], "vita": t["vita"]}
    return out


def predict_lines(pr: dict) -> list[str]:
    """Le righe della PREVISIONE per update_match."""
    if not pr:
        return []
    pc = lambda x: f"{round(x * 100)}%"  # noqa: E731
    lines = []
    head = "PREVISIONE AVVERSARIO (questo round" + (f", mana {pr['mana']}" if pr.get("mana") is not None else "") + \
        (f", {pr['mano']} carte in mano" if pr.get("mano") is not None else "") + "):"
    if pr.get("carte"):
        lines.append(head)
        lines.append("- In mano probabilmente: " + " · ".join(
            f"{x['carta']} {pc(x['p_mano'])}" + (f" (costo {x['costo']}{', giocabile' if x['giocabile'] else ''})"
                                               if x.get("costo") is not None else "") for x in pr["carte"]))
        if pr.get("p_giocabile") is not None:
            lines.append(f"- Può giocare almeno una carta da ≤{pr['mana']} questo round: {pc(pr['p_giocabile'])}"
                         + (f"; le giocate più probabili adesso (mana, round tipico, tipo di mazzo): "
                            f"{', '.join(x['carta'] for x in pr['giocabili'])}" if pr.get("giocabili") else ""))
        if pr.get("minaccia"):
            t = pr["minaccia"]
            stats = f" {t['attacco']}/{t['vita']}" if t.get("attacco") is not None and t.get("vita") is not None else ""
            lines.append(f"- Minaccia principale: {t['carta']}{stats} ({pc(t['p_mano'])} in mano)")
    elif pr.get("piano"):
        lines.append(head.replace("):", "): nessuna lista del meta per stimare le carte; solo il tipo di mazzo"))
    if pr.get("piano"):
        lines.append(f"- Piano tipico ({pr['tipo']}): {pr['piano']}"
                     + (f"; bersaglio probabile: {pr['bersaglio']}" if pr.get("bersaglio") else ""))
    return lines


def check_previous(m: dict) -> dict | None:
    """Confronta la previsione del round scorso con ciò che l'avversario ha giocato davvero (per imparare)."""
    prev = m.get("previsione")
    if not prev:
        return None
    from origins import evaluate
    now = evaluate.seen_opp(m)
    before = {k: v for k, v in (prev.get("viste") or {}).items()}
    played = []
    for k, v in now.items():
        played += [k] * max(0, v - before.get(k, 0))
    if not played:
        return None
    predicted = {store.slug(c) for c in prev.get("carte") or []}
    return {"turno": prev.get("turno"), "previste": prev.get("carte") or [], "giocate": played,
            "azzeccate": [c for c in played if store.slug(c) in predicted],
            "sorprese": [c for c in played if store.slug(c) not in predicted]}


# ---- memoria dei calcoli: update_match chiede identify/predict più volte con lo stesso stato (ricerca della mossa,
# probabilità, previsione); il calcolo sul meta è la parte lenta, quindi si fa una volta sola per stato
_MEMO: dict = {}


def _key(m: dict, meta, top) -> str | None:
    if meta is not None:
        return None  # meta passato a mano (test, simulazioni): niente memoria
    import json as _json
    mk = []
    for kind in ("meta", "cards"):
        try:
            st = store.FILES[kind].stat()
            mk.append((st.st_mtime_ns, st.st_size))
        except OSError:
            mk.append(None)
    fields = {k: m.get(k) for k in ("avv_leggendaria", "avv_giocati", "avv_scartati", "avv_creati", "avv_mano", "mana",
                                    "turno", "barrier_mie", "barrier_avv", "rinforzate_mie", "leggendaria_mia",
                                    "campo")}
    return _json.dumps([fields, mk, top, str(store.FILES["meta"])], sort_keys=True, default=str)


def _memo(name, fn, m, meta, top):
    import copy as _copy
    k = _key(m, meta, top)
    if k is None:
        return fn(m, meta, top)
    hit = _MEMO.get((name, k))
    if hit is None:
        hit = fn(m, meta, top)
        if len(_MEMO) > 64:
            _MEMO.clear()
        _MEMO[(name, k)] = hit
    return _copy.deepcopy(hit)


def identify(m: dict, meta: list[dict] | None = None, top: int = 3) -> dict:
    return _memo("identify", _identify, m, meta, top)


def predict(m: dict, meta: list[dict] | None = None, top: int = 6) -> dict:
    return _memo("predict", _predict, m, meta, top)
