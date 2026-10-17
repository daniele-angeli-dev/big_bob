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


def identify(m: dict, meta: list[dict] | None = None, top: int = 3) -> dict:
    """Mazzi più probabili dell'avversario e tipo, dalle carte viste nella partita m."""
    from origins import evaluate
    meta = meta if meta is not None else store.load("meta")
    leg = (m.get("avv_leggendaria") or "").strip()
    seen = [c for c in evaluate.seen_opp(m) if store.slug(c) != store.slug(leg)]
    cands = [a for a in meta if a.get("carte") and (not leg or store.slug(a.get("leggendaria", "")) == store.slug(leg))]
    out = {"leggendaria": leg or None, "carte_viste": len(seen), "mazzi": [], "tipi": {}, "tipo": None}
    if not cands:
        if len(seen) >= 3:
            t = curve_type(seen)
            out["tipo"] = {**t, "p": None, "da": "curva delle carte viste (nessun mazzo del meta per questa leggendaria)"}
            out["contro"] = CONTRO.get(t["etichetta"], CONTRO.get(t["base"], ""))
        return out
    scored = []
    for a in cands:
        pool = {store.slug(c) for c in a["carte"]}
        miss = [c for c in seen if store.slug(c) not in pool]
        scored.append((math.log(_prior(a)) + len(miss) * math.log(FUORI_LISTA), a, miss))
    mx = max(s for s, _, _ in scored)
    tot = sum(math.exp(s - mx) for s, _, _ in scored)
    post = sorted(((math.exp(s - mx) / tot, a, miss) for s, a, miss in scored), key=lambda x: -x[0])
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
            "viste": ident.get("carte_viste", 0)}
