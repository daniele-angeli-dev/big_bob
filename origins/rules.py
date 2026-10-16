"""Regolamento ricostruito: ogni regola ha uno stato, delle fonti e delle prove.

Stati: domanda (non sappiamo) · ipotesi · probabile · confermata · smentita
Il file leggibile data/regole.md viene rigenerato a ogni modifica.
"""
from __future__ import annotations

from origins import store

STATI = {"domanda": "⬜", "ipotesi": "❓", "probabile": "🟡", "confermata": "✅", "smentita": "❌"}
CATEGORIE = ["struttura", "risorse", "turno", "rivelazione", "corsie", "vittoria", "leggendaria",
             "parole chiave", "location", "altro"]

SEED = [
    ("struttura", "Mazzo: 13 carte diverse = 12 normali in doppia copia + 1 leggendaria in copia singola (25 carte)",
     "confermata", "Daniele"),
    ("struttura", "Si gioca su 3 corsie/location, ognuna con una regola propria", "probabile", "pagina Steam e stampa"),
    ("turno", "Turni simultanei: entrambi i giocatori piazzano le carte, poi vengono rivelate", "probabile",
     "pagina Steam e stampa"),
    ("struttura", "Una partita dura circa 7 minuti", "ipotesi", "pagina Steam"),
    ("risorse", "Pescare da mazzo vuoto infligge danno", "probabile", "stampa"),
    ("location", "Le location vengono da un pool di 100+ con rarità diverse che ne regolano la frequenza",
     "ipotesi", "stampa"),
    ("vittoria", "Come si vince la partita? (corsie vinte, punti vita, punteggio…)", "domanda", ""),
    ("vittoria", "Come si vince una singola corsia e cosa succede in caso di pareggio?", "domanda", ""),
    ("vittoria", "Esistono punti vita? A cosa si applica il danno da mazzo vuoto?", "domanda", ""),
    ("risorse", "Che risorsa serve per giocare le carte e come cresce turno dopo turno?", "domanda", ""),
    ("risorse", "Quante carte nella mano iniziale? C'è un mulligan?", "domanda", ""),
    ("risorse", "Quante carte si pescano a turno? C'è un limite di carte in mano?", "domanda", ""),
    ("turno", "Quanti turni dura una partita e cosa la fa finire?", "domanda", ""),
    ("turno", "Quanto dura il timer di un turno?", "domanda", ""),
    ("rivelazione", "In che ordine si rivelano le carte (chi rivela prima, priorità)?", "domanda", ""),
    ("rivelazione", "Quando si rivelano le location (tutte subito o una per turno)?", "domanda", ""),
    ("corsie", "Quante carte può ospitare una corsia?", "domanda", ""),
    ("corsie", "Le carte si possono spostare o ritirare dopo essere state giocate?", "domanda", ""),
    ("leggendaria", "Come entra in gioco la leggendaria (nel mazzo, in mano dall'inizio, abilità permanente)?",
     "domanda", ""),
    ("parole chiave", "Quali parole chiave esistono e cosa fa ciascuna?", "domanda", ""),
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
             "stato": stato or "ipotesi", "fonti": [], "prove": []}
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
