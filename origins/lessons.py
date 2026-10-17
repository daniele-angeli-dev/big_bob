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


def record(lezione: str, tipo: str = "strategia", carte: list[str] | None = None, situazione: str = "",
           accaduto: str = "", perche: str = "", fonte: str = "", id: str = "", stato: str = "") -> dict:
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
        best = max(ls, key=lambda a: _similar(a, tipo, cards, lezione), default=None)
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
    target["volte"] = target.get("volte", 0) + 1
    target["prove"] = (target.get("prove", []) + [prova])[-8:]
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


def relevant(cards: list[str], limit: int = 4) -> list[dict]:
    """Le lezioni più utili per le carte in gioco adesso (confermate prima, poi le più viste)."""
    cs = {c.lower() for c in cards if c}
    scored = []
    for a in load():
        if a.get("stato") == "smentita":
            continue
        hit = len(cs & {c.lower() for c in a.get("carte", [])})
        if not hit and a.get("carte"):
            continue
        if not a.get("carte") and a.get("tipo") != "strategia":
            continue
        score = hit * 2 + (3 if a["stato"] == "confermata" else 0) + min(a.get("volte", 1), 5) * 0.5
        scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:limit]]


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
