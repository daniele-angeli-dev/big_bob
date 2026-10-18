"""Lezioni apprese dalle partite: ciò che BIG-BOB non aveva previsto, capito e messo per iscritto.

Ogni lezione: una frase pratica ("la prossima volta…"), le carte coinvolte, il tipo, lo stato
(ipotesi → confermata dopo 2 osservazioni o conferma di Daniele; smentita) e le prove.
Le lezioni simili vengono fuse: una seconda osservazione rafforza quella esistente.
Il file leggibile data/lezioni.md viene rigenerato a ogni modifica.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from origins import store

TIPI = {
    "mossa_avversaria": "Mosse e piani avversari",
    "interazione": "Interazioni tra carte e location",
    "errore_coach": "Errori dei miei consigli",
    "mossa_vincente": "Mosse che hanno funzionato meglio del previsto",
    "strategia": "Strategia generale",
}
STATI = {"ipotesi": "❓", "confermata": "✅", "smentita": "❌"}
CONFERMA_DOPO = 2  # osservazioni indipendenti per passare da ipotesi a confermata


def load() -> list[dict]:
    return store.load("lessons")


def save(ls: list[dict]) -> None:
    store.save("lessons", ls)
    render(ls)


def _norm_cards(cards: list[str] | None) -> list[str]:
    out = []
    for c in cards or []:
        if c and c.strip():
            out.append(store.canonical(c.strip()))
    return list(dict.fromkeys(out))


def _similar(a: dict, tipo: str, cards: list[str], text: str) -> float:
    if a.get("tipo") != tipo or a.get("stato") == "smentita":
        return 0.0
    ca, cb = {c.lower() for c in a.get("carte", [])}, {c.lower() for c in cards}
    if ca and cb and not (ca & cb):
        return 0.0
    overlap = len(ca & cb) / max(1, len(ca | cb)) if (ca or cb) else 1.0
    txt = SequenceMatcher(None, a.get("lezione", "").lower(), text.lower()).ratio()
    return 0.5 * overlap + 0.5 * txt


COND_KEYS = ("corsia", "mana_min", "mana_max", "round_min", "round_max", "tipo_avversario", "leggendaria_avversaria",
             "mia_leggendaria")


def clean_conditions(c: dict | None) -> dict:
    """Condizioni in cui la lezione vale (servono a richiamarla solo quando serve)."""
    out = {}
    for k, v in (c or {}).items():
        if k not in COND_KEYS or v in (None, "", []):
            continue
        if k.endswith(("_min", "_max")):
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                continue
        else:
            out[k] = str(v).strip()
    return out


def record(lezione: str, tipo: str = "strategia", carte: list[str] | None = None, situazione: str = "",
           accaduto: str = "", perche: str = "", fonte: str = "", id: str = "", stato: str = "",
           condizioni: dict | None = None) -> dict:
    if tipo not in TIPI:
        raise ValueError(f"tipo deve essere uno di {list(TIPI)}")
    if stato and stato not in STATI:
        raise ValueError(f"stato deve essere uno di {list(STATI)}")
    if not lezione.strip() and not id:
        raise ValueError("serve il testo della lezione")
    ls = load()
    cards = _norm_cards(carte)
    target = next((x for x in ls if x["id"].lower() == id.lower()), None) if id else None
    if target is None and not id:
        cond_new = clean_conditions(condizioni)
        same_sit = [a for a in ls if not cond_new or (a.get("condizioni") or {}) == cond_new]  # situazioni diverse
        best = max(same_sit, key=lambda a: _similar(a, tipo, cards, lezione), default=None)
        if best is not None and _similar(best, tipo, cards, lezione) >= 0.62:
            target = best
    prova = {"data": store.now(), "fonte": fonte or "partita", "situazione": situazione,
             "accaduto": accaduto, "perche": perche}
    if target is None:
        num = max((int(x["id"][1:]) for x in ls if x["id"][1:].isdigit()), default=0) + 1
        target = {"id": f"L{num:03d}", "tipo": tipo, "lezione": lezione.strip(), "carte": cards,
                  "stato": "ipotesi", "volte": 0, "prove": [], "creata": store.now(),
                  "patch": store.load("config").get("patch_corrente", "")}
        ls.append(target)
        azione = "nuova"
    else:
        azione = "rafforzata"
        if lezione.strip() and len(lezione.strip()) > len(target["lezione"]) * 0.6:
            target["lezione"] = lezione.strip()  # la formulazione più recente è di solito la più precisa
        target["carte"] = list(dict.fromkeys(target.get("carte", []) + cards))
    cond = clean_conditions(condizioni)
    if cond:
        target["condizioni"] = {**(target.get("condizioni") or {}), **cond}
    target["volte"] = target.get("volte", 0) + 1
    target["prove"] = (target.get("prove", []) + [prova])[-8:]
    if "cervello" not in str(prova.get("fonte") or "").lower():
        target.pop("confermata_da_cervello", None)  # ora c'è una prova tua: il voto che mandi è il tuo
    target["ultima"] = store.now()
    # le opinioni non dimostrate non confermano una lezione: servono fatti (partite, verifiche) o la parola di Daniele
    # su un fatto del gioco; così una risposta compiacente non diventa una lezione «confermata» per tutti
    facts = sum(1 for p in target["prove"] if "opinion" not in str(p.get("fonte") or "").lower())
    if stato:
        target["stato"] = stato
    elif target["stato"] == "ipotesi" and (facts >= CONFERMA_DOPO or (fonte or "").strip().lower() == "daniele"):
        target["stato"] = "confermata"
    save(ls)
    return {"azione": azione, "lezione": target}


def review(id: str, stato: str = "", lezione: str = "", elimina: bool = False) -> dict:
    ls = load()
    t = next((x for x in ls if x["id"].lower() == id.lower()), None)
    if t is None:
        raise ValueError(f"lezione {id} non trovata")
    if elimina:
        ls.remove(t)
        save(ls)
        return {"eliminata": id}
    if stato:
        if stato not in STATI:
            raise ValueError(f"stato deve essere uno di {list(STATI)}")
        t["stato"] = stato
    if lezione:
        t["lezione"] = lezione
    t["ultima"] = store.now()
    save(ls)
    return {"aggiornata": t}


def context(m: dict | None) -> dict:
    """La situazione della partita per confrontarla con le condizioni delle lezioni."""
    if not m:
        return {}
    ctx = {"mana": m.get("mana"), "round": m.get("turno"), "leggendaria_avversaria": m.get("avv_leggendaria"),
           "mia_leggendaria": m.get("leggendaria_mia"), "tipo_avversario": m.get("tipo_avversario_stimato")}
    if not ctx["tipo_avversario"]:
        try:
            from origins import archetype
            ctx["tipo_avversario"] = (archetype.identify(m).get("tipo") or {}).get("etichetta")
        except Exception:  # noqa: BLE001
            pass
    return ctx


def fits(cond: dict | None, ctx: dict) -> tuple[bool, int]:
    """(la lezione vale qui?, quante condizioni sono soddisfatte). Una condizione che non si può verificare non esclude."""
    if not cond or not ctx:
        return True, 0
    ok = 0
    for k, v in cond.items():
        if k in ("mana_min", "mana_max", "round_min", "round_max"):
            cur = ctx.get("mana" if k.startswith("mana") else "round")
            if not isinstance(cur, int):
                continue
            if (k.endswith("_min") and cur < v) or (k.endswith("_max") and cur > v):
                return False, 0
            ok += 1
        elif k in ("tipo_avversario", "leggendaria_avversaria", "mia_leggendaria"):
            cur = ctx.get(k)
            if not cur:
                continue
            if store.slug(str(v)) not in store.slug(str(cur)) and store.slug(str(cur)) not in store.slug(str(v)):
                return False, 0
            ok += 1
    return True, ok


def utility(a: dict) -> float | None:
    """Quanto è stata utile: frazione dei round andati bene quando era mostrata (None se visto troppo poco)."""
    good, bad = a.get("round_buoni", 0), a.get("round_cattivi", 0)
    if good + bad < 4:
        return None
    return (good + 1) / (good + bad + 2)


def relevant(cards: list[str], limit: int = 4, m: dict | None = None) -> list[dict]:
    """Le lezioni più utili adesso: carte in gioco, condizioni soddisfatte (mana, round, tipo di mazzo avversario,
    leggendarie), confermate prima, poi le più viste e quelle che si sono dimostrate utili. Quelle che si sono
    dimostrate inutili (molti round andati male quando erano mostrate) non escono più in partita."""
    cs = {c.lower() for c in cards if c}
    ctx = context(m)
    scored = []
    for a in load():
        if a.get("stato") == "smentita":
            continue
        hit = len(cs & {c.lower() for c in a.get("carte", [])})
        if not hit and a.get("carte"):
            continue
        if not a.get("carte") and a.get("tipo") != "strategia" and not a.get("condizioni"):
            continue
        good, n_cond = fits(a.get("condizioni"), ctx)
        if not good:
            continue
        u = utility(a)
        if u is not None and u < 0.3 and a.get("round_buoni", 0) + a.get("round_cattivi", 0) >= 8:
            continue
        score = hit * 2 + n_cond * 1.5 + (3 if a["stato"] == "confermata" else 0) + min(a.get("volte", 1), 5) * 0.5
        if u is not None:
            score += (u - 0.5) * 4
        scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:limit]]


def mark_outcome(ids: list[str], good: bool) -> None:
    """Esito del round in cui queste lezioni erano mostrate (per il punteggio di utilità)."""
    if not ids:
        return
    ls = load()
    key = "round_buoni" if good else "round_cattivi"
    changed = False
    for a in ls:
        if a["id"] in ids:
            a[key] = a.get(key, 0) + 1
            changed = True
    if changed:
        save(ls)


def tidy() -> dict:
    """Riordino: unisce le lezioni quasi uguali (stesso tipo, carte in comune, testo simile) in una sola, tenendo
    tutte le prove. Senza Claude: è un conto sui testi, si fa a fine partita."""
    ls = load()
    merged = []
    keep: list[dict] = []
    for a in sorted(ls, key=lambda x: (x.get("stato") != "confermata", -x.get("volte", 0))):
        if a.get("stato") == "smentita":
            keep.append(a)
            continue
        twin = next((k for k in keep if k.get("stato") != "smentita"
                     and (k.get("condizioni") or {}) == (a.get("condizioni") or {})  # situazioni diverse: restano due
                     and _similar(k, a.get("tipo"), a.get("carte", []), a.get("lezione", "")) >= 0.72), None)
        if twin is None:
            keep.append(a)
            continue
        twin["carte"] = list(dict.fromkeys(twin.get("carte", []) + a.get("carte", [])))
        twin["prove"] = (twin.get("prove", []) + a.get("prove", []))[-8:]
        twin["volte"] = twin.get("volte", 0) + a.get("volte", 0)
        for k in ("round_buoni", "round_cattivi"):
            twin[k] = twin.get(k, 0) + a.get(k, 0)
        if a.get("stato") == "confermata":
            twin["stato"] = "confermata"
        merged.append(f"{a['id']} → {twin['id']}")
    if merged:
        order = {x["id"]: i for i, x in enumerate(ls)}
        save(sorted(keep, key=lambda x: order.get(x["id"], 0)))
    return {"unite": merged}


def render(ls: list[dict] | None = None) -> str:
    ls = ls if ls is not None else load()
    lines = ["# Lezioni di BIG-BOB", "",
             "Generato automaticamente: per correggere o eliminare usa /lezioni in Claude Code.", "",
             "Legenda: " + " · ".join(f"{v} {k}" for k, v in STATI.items()), ""]
    for tipo, titolo in TIPI.items():
        rs = [x for x in ls if x.get("tipo") == tipo]
        if not rs:
            continue
        lines.append(f"## {titolo}")
        for x in sorted(rs, key=lambda x: (x["stato"] != "confermata", -x.get("volte", 0))):
            carte = ", ".join(x.get("carte", [])) or "—"
            lines.append(f"- `{x['id']}` {STATI.get(x['stato'], '?')} {x['lezione']}  "
                         f"_(carte: {carte}; vista {x.get('volte', 1)} volte)_")
        lines.append("")
    text = "\n".join(lines)
    (store.DATA / "lezioni.md").write_text(text, encoding="utf-8")
    return text
