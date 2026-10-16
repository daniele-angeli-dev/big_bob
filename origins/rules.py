"""Regolamento ricostruito: ogni regola ha uno stato, delle fonti e delle prove.

Stati: domanda (non sappiamo) · ipotesi · probabile · confermata · smentita
Il file leggibile data/regole.md viene rigenerato a ogni modifica.
"""
from __future__ import annotations

from origins import store

STATI = {"domanda": "⬜", "ipotesi": "❓", "probabile": "🟡", "confermata": "✅", "smentita": "❌"}
CATEGORIE = ["struttura", "risorse", "turno", "rivelazione", "corsie", "vittoria", "leggendaria",
             "parole chiave", "location", "altro"]

# Regole confermate da Daniele nell'intervista (ottobre 2026): vengono con BIG-BOB, anche in un'installazione nuova.
SEED = [
    ("struttura", "Mazzo: 13 carte diverse = 12 normali in doppia copia + 1 leggendaria in copia singola (25 carte). "
                  "La leggendaria è nel mazzo come le altre", "confermata", "Daniele"),
    ("leggendaria", "La leggendaria dell'avversario è visibile fin dall'inizio della partita", "confermata", "Daniele"),
    ("leggendaria", "Dopo la mano iniziale arriva in mano la carta del potere leggendario", "confermata", "Daniele"),
    ("struttura", "Si gioca su 3 corsie; ogni corsia ha una location con una regola propria", "confermata", "Daniele"),
    ("location", "Le location si rivelano una per round: sinistra, poi centro, poi destra; ruotano tra le partite",
     "confermata", "Daniele"),
    ("vittoria", "Ogni giocatore ha una barrier da 20 in ciascuna delle 3 corsie", "confermata", "Daniele"),
    ("vittoria", "Una barrier a 0 si rigenera a 40 e il danno in eccesso non passa", "confermata", "Daniele"),
    ("vittoria", "Vince chi distrugge per primo 2 barrier avversarie (vale anche distruggere 2 volte la stessa)",
     "confermata", "Daniele"),
    ("vittoria", "Se entrambi arrivano a 2 barrier distrutte nello stesso round, chi vince?", "domanda", ""),
    ("risorse", "Mana: 2 al round 1, poi +1 a round fino a 10. Il mana non speso non si accumula", "confermata",
     "Daniele"),
    ("risorse", "Mano iniziale di 4 carte con mulligan libero (Keep or Replace)", "confermata", "Daniele"),
    ("risorse", "Si pesca 1 carta a round; massimo 10 carte in mano: le eccedenti vengono scartate e attivano gli "
                "effetti \"when discarded\"", "confermata", "Daniele"),
    ("risorse", "Fatica: a mazzo vuoto, a ogni pescata mancata TUTTE le tue barrier prendono 1, poi 2, poi 3… danni",
     "confermata", "Daniele"),
    ("turno", "Turni simultanei: entrambi i giocatori giocano le carte, poi si rivelano", "confermata", "Daniele"),
    ("turno", "Timer del round: 90 secondi", "confermata", "Daniele"),
    ("struttura", "Una partita dura circa 7 minuti", "probabile", "pagina Steam"),
    ("rivelazione", "Chi rivela per primo è casuale al round 1, poi si alterna", "confermata", "Daniele"),
    ("rivelazione", "Le carte si attivano nell'ordine in cui sono state giocate", "confermata", "Daniele"),
    ("corsie", "Le spell non occupano spazi nelle corsie", "confermata", "Daniele"),
    ("corsie", "Quanti spazi (slot) ha ogni corsia per lato?", "domanda", ""),
    ("vittoria", "Combattimento: ogni creatura attacca quella di fronte, o la barrier se lo spazio di fronte è vuoto",
     "confermata", "Daniele"),
    ("vittoria", "I colpi sono simultanei e il danno resta sulle creature (conta la vita residua)", "confermata",
     "Daniele"),
    ("vittoria", "Il combattimento si risolve da sinistra a destra, seguendo la freccia", "confermata", "Daniele"),
    ("parole chiave", "Defender: difende sempre, e più volte nello stesso combattimento", "confermata", "Daniele"),
    ("parole chiave", "Move: sposta la creatura in qualsiasi spazio libero", "confermata", "Daniele"),
    ("parole chiave", "Quali altre parole chiave esistono (Snipe, Shield, Trample, Deathtouch, First Strike, "
                      "Rebirth…) e cosa fa esattamente ciascuna?", "domanda", ""),
]


def _seed() -> list[dict]:
    out = []
    for i, (cat, testo, stato, fonte) in enumerate(SEED, 1):
        out.append({"id": f"R{i:03d}", "categoria": cat, "testo": testo, "stato": stato,
                    "fonti": [fonte] if fonte else [], "prove": [], "aggiornata": store.now()})
    return out


def load() -> list[dict]:
    if not store.FILES["rules"].exists():
        rules = _seed()
        save(rules)
        return rules
    return store.load("rules")


def save(rules: list[dict]) -> None:
    store.save("rules", rules)
    render(rules)


def render(rules: list[dict] | None = None) -> str:
    rules = rules if rules is not None else load()
    lines = ["# Regolamento di Origins TCG (ricostruito)", "",
             "Generato automaticamente da rules.json: non modificarlo a mano, usa Claude Code.", "",
             "Legenda: " + " · ".join(f"{v} {k}" for k, v in STATI.items()), ""]
    cats = CATEGORIE + sorted({r["categoria"] for r in rules} - set(CATEGORIE))
    for cat in cats:
        rs = [r for r in rules if r["categoria"] == cat]
        if not rs:
            continue
        lines.append(f"## {cat.capitalize()}")
        for r in sorted(rs, key=lambda r: list(STATI).index(r["stato"]) if r["stato"] in STATI else 9):
            fonti = ", ".join(r.get("fonti") or []) or "—"
            n = len(r.get("prove") or [])
            lines.append(f"- `{r['id']}` {STATI.get(r['stato'], '?')} {r['testo']}  "
                         f"_(fonti: {fonti}{f'; {n} prove' if n else ''})_")
        lines.append("")
    text = "\n".join(lines)
    (store.DATA / "regole.md").write_text(text, encoding="utf-8")
    return text


def get(categoria: str = "", stato: str = "") -> list[dict]:
    rs = load()
    if categoria:
        rs = [r for r in rs if r["categoria"].lower() == categoria.lower()]
    if stato:
        rs = [r for r in rs if r["stato"] == stato]
    return rs


def upsert(testo: str = "", categoria: str = "", stato: str = "", fonte: str = "", prova: str = "",
           id: str = "") -> dict:
    """Crea una regola nuova (senza id) o aggiorna quella con l'id dato."""
    if stato and stato not in STATI:
        raise ValueError(f"stato deve essere uno di {list(STATI)}")
    rules = load()
    r = next((x for x in rules if x["id"].lower() == id.lower()), None) if id else None
    if r is None:
        if not testo:
            raise ValueError("Per una regola nuova serve il testo")
        num = max((int(x["id"][1:]) for x in rules if x["id"][1:].isdigit()), default=0) + 1
        r = {"id": f"R{num:03d}", "categoria": categoria or "altro", "testo": testo,
             "stato": stato or "ipotesi", "fonti": [], "prove": [], "creata": store.now()}
        rules.append(r)
        azione = "creata"
    else:
        azione = "aggiornata"
        prima = {k: r.get(k) for k in ("testo", "stato")}
        if testo:
            r["testo"] = testo
        if stato:
            r["stato"] = stato
        if categoria:
            r["categoria"] = categoria
        if prima != {k: r.get(k) for k in ("testo", "stato")}:
            r.setdefault("storico", []).append({"data": store.now(), **prima})
    if fonte and fonte not in r["fonti"]:
        r["fonti"].append(fonte)
    if prova:
        r["prove"].append({"data": store.now(), "fonte": fonte, "nota": prova})
    r["aggiornata"] = store.now()
    save(rules)
    return {"azione": azione, "regola": r}
