"""Server MCP "origins": gli strumenti che Claude Code usa per vedere la partita, consultare le carte
e calcolare le probabilità. Avvio: python origins/server.py (lo fa Claude Code da .mcp.json)."""
from __future__ import annotations

from collections import Counter

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from origins import archetype, cervello, combat, deckproj, evaluate, lab, lessons, odds, originsmeta, rules, store  # noqa: E402
from origins.store import canonical, load, now, save  # noqa: E402

mcp = FastMCP("origins")


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=1)


def _stats(e: dict | None) -> str:
    """'costo 2 · 3⚔/2❤' (o il vecchio 'potere' per le carte salvate prima di attacco/vita)."""
    if not e:
        return "NON IN DB"
    if e.get("attacco") is not None or e.get("vita") is not None:
        st = f"{e.get('attacco', '?')}⚔/{e.get('vita', '?')}❤"
    elif e.get("potere") is not None:
        st = f"potere {e.get('potere')} (vecchio formato)"
    else:
        st = e.get("tipo") or "spell?"
    return f"costo {e.get('costo')} · {st}"


def _canon_list(names: list[str] | None) -> list[str]:
    return [canonical(n) for n in (names or []) if n]


# ======================= SCHERMO =======================

@mcp.tool()
def get_screen() -> list:
    """Cattura ADESSO la finestra di Origins TCG (o lo schermo intero) e restituisce l'immagine.
    Usalo all'inizio di ogni analisi di turno."""
    from origins import screen
    p = screen.latest_if_fresh()   # catturata dall'overlay un attimo fa, con l'overlay nascosto
    if p is None:
        p = screen.capture(load("config").get("titolo_finestra", "Origins"))
    return [f"Schermata del {now()}", Image(path=str(p))]


@mcp.tool()
def get_recent_screens(n: int = 2) -> list:
    """Restituisce le ultime n schermate già catturate (utile per vedere cosa è cambiato
    tra la fase di piazzamento e la rivelazione)."""
    from origins import screen
    out: list = []
    for p in screen.recent_history(max(1, min(n, 4))):
        out += [p.name, Image(path=str(p))]
    return out or ["Nessuna schermata in storico"]


@mcp.tool()
def list_scan_images() -> str:
    """Elenca le immagini in attesa in captures/scan (catturate con F9 dall'overlay) da leggere
    per costruire il database di carte/location/regole. Leggile con il tool Read."""
    from origins import screen
    files = sorted(p for p in screen.SCAN.glob("*.png"))
    return _j({"cartella": str(screen.SCAN), "immagini": [str(p) for p in files], "totale": len(files)})


@mcp.tool()
def archive_scan_images(paths: list[str]) -> str:
    """Sposta in captures/scan/fatte le immagini già elaborate, così non vengono rilette."""
    from origins import screen
    done = screen.SCAN / "fatte"
    done.mkdir(exist_ok=True)
    moved = 0
    for p in paths:
        src = Path(p)
        if src.exists() and src.parent == screen.SCAN:
            shutil.move(str(src), done / src.name)
            moved += 1
    return f"Archiviate {moved} immagini"


# ======================= CARTE E LOCATION =======================

@mcp.tool()
def upsert_cards(cards: list[dict], patch: str = "") -> str:
    """Aggiunge/aggiorna carte nel database. Ogni carta: {nome, leggendaria: bool, costo,
    attacco, vita (le due cifre ⚔/❤ delle creature; per le spell lasciale fuori), testo,
    tipo ("creatura" | "spell" | ...), potere_leggendario (solo leggendarie: cosa fa il potere/la carta
    che arriva a inizio partita), rarita, tag: [..], note}. Non usare più il campo 'potere'. Le differenze rispetto alla versione salvata vengono
    registrate nello storico con l'etichetta della patch."""
    return _j(store.upsert("cards", cards, patch or None))


@mcp.tool()
def upsert_locations(locations: list[dict], patch: str = "") -> str:
    """Aggiunge/aggiorna location: {nome, testo, rarita, note}."""
    return _j(store.upsert("locations", locations, patch or None))


@mcp.tool()
def get_card(name: str) -> str:
    """Scheda completa di una carta (tollera piccoli errori di lettura del nome)."""
    e = store.find("cards", name)
    return _j(e) if e else f"Carta '{name}' non trovata. Prova search_cards."


@mcp.tool()
def get_location(name: str) -> str:
    """Scheda di una location."""
    e = store.find("locations", name)
    return _j(e) if e else f"Location '{name}' non trovata."


@mcp.tool()
def search_cards(query: str = "", limit: int = 40) -> str:
    """Cerca carte per nome, testo, tag, costo... (query vuota = elenco)."""
    hits = store.search("cards", query, limit)
    return _j([{"nome": e["nome"], "statistiche": _stats(e), "leggendaria": e.get("leggendaria"),
                "testo": e.get("testo"), "potere_leggendario": e.get("potere_leggendario"), "tag": e.get("tag")}
               for e in hits])


@mcp.tool()
def card_pool_compact() -> str:
    """Tutte le carte in formato compatto (una riga per carta): da usare per il deckbuilding."""
    rows = []
    for e in load("cards"):
        leg = f" | potere leggendario: {e['potere_leggendario']}" if e.get("potere_leggendario") else ""
        rows.append(f"{'★ ' if e.get('leggendaria') else ''}{e['nome']} | {_stats(e)} | "
                    f"{e.get('testo', '')}{leg} | tag {','.join(e.get('tag') or [])}")
    locs = [f"{e['nome']} | {e.get('testo', '')}" for e in load("locations")]
    return f"CARTE ({len(rows)}):\n" + "\n".join(rows) + f"\n\nLOCATION ({len(locs)}):\n" + "\n".join(locs)


@mcp.tool()
def cards_to_check() -> str:
    """Carte con dati mancanti o nel vecchio formato (solo 'potere' invece di attacco/vita):
    sono quelle da ricatturare con F9 o da correggere."""
    out = []
    for e in load("cards"):
        why = []
        if e.get("costo") is None:
            why.append("costo mancante")
        if not e.get("testo") and e.get("tipo") != "creatura":
            why.append("testo mancante")
        if e.get("potere") is not None and e.get("attacco") is None:
            why.append("vecchio formato: solo 'potere', servono attacco e vita")
        elif e.get("tipo") in (None, "creatura") and (e.get("attacco") is None or e.get("vita") is None) \
                and e.get("tipo") != "spell":
            why.append("attacco/vita mancanti (o tipo non indicato)")
        if e.get("leggendaria") and not e.get("potere_leggendario"):
            why.append("potere leggendario mancante")
        if why:
            out.append({"nome": e["nome"], "problemi": why})
    return _j({"da_controllare": len(out), "totale": len(load("cards")), "carte": out})


@mcp.tool()
def database_status() -> str:
    """Quante carte/location/mazzi/archetipi ci sono, patch corrente e modalità."""
    cfg = load("config")
    cards = load("cards")
    return _j({
        "carte": len(cards), "leggendarie": sum(1 for c in cards if c.get("leggendaria")),
        "location": len(load("locations")), "miei_mazzi": len(load("decks")),
        "archetipi_avversari": len(load("meta")), "partite_registrate": len(load("matches")),
        "patch_corrente": cfg.get("patch_corrente"), "modalita": cfg.get("modalita"),
        "regole": {st: len(rules.get(stato=st)) for st in rules.STATI},
        "lezioni": {st: sum(1 for x in lessons.load() if x.get("stato") == st) for st in lessons.STATI},
        "regole_file": str(store.DATA / "regole.md"),
    })


# ======================= PATCH =======================

@mcp.tool()
def record_patch(label: str, date: str = "", notes: str = "") -> str:
    """Registra una nuova patch e la imposta come corrente. Poi aggiorna le carte cambiate con
    upsert_cards(patch=label): lo storico delle modifiche verrà salvato automaticamente."""
    patches = load("patches")
    patches.append({"patch": label, "data": date or now(), "note": notes})
    save("patches", patches)
    cfg = load("config")
    cfg["patch_corrente"] = label
    save("config", cfg)
    return f"Patch {label} registrata e impostata come corrente."


@mcp.tool()
def patch_changes(label: str = "") -> str:
    """Tutte le modifiche alle carte in una patch (default: patch corrente) + note della patch."""
    label = label or load("config").get("patch_corrente", "")
    changes = []
    for e in load("cards") + load("locations"):
        for h in e.get("storico", []):
            if h["patch"] == label:
                real = [m for m in h["modifiche"] if m.get("prima") not in (None, "", [])
                        and not (m.get("campo") == "potere")]
                if real:
                    changes.append({"nome": e["nome"], "modifiche": real})
    new = [e["nome"] for e in load("cards") if e.get("patch_introduzione") == label]
    notes = [p for p in load("patches") if p["patch"] == label]
    changed = {c["nome"].lower() for c in changes}
    stale = [{"id": x["id"], "lezione": x["lezione"]} for x in lessons.load()
             if changed & {c.lower() for c in x.get("carte", [])} and x.get("stato") != "smentita"]
    return _j({"patch": label, "note": notes, "carte_nuove": new, "modifiche": changes,
               "lezioni_da_riverificare": stale})


# ======================= MAZZI =======================

@mcp.tool()
def save_deck(name: str, legendary: str, cards: list[str], note: str = "") -> str:
    """Salva un mio mazzo: 1 leggendaria + 12 carte (ciascuna entra in doppia copia: 25 totali)."""
    return _j(store.save_deck(name, legendary, cards, note))


@mcp.tool()
def validate_deck(legendary: str, cards: list[str]) -> str:
    """Controlla che un mazzo sia legale e che tutte le carte esistano nel database."""
    return _j(store.validate_deck(legendary, cards))


@mcp.tool()
def list_decks() -> str:
    """I miei mazzi salvati."""
    return _j(load("decks"))


@mcp.tool()
def deck_curve(legendary: str, cards: list[str]) -> str:
    """Curva dei costi, attacco/vita totali e probabilità di avere in mano carte a costo basso
    nella mano iniziale (usa la dimensione mano da rules)."""
    full = odds.deck_counts(canonical(legendary), _canon_list(cards))
    curve: dict = {}
    atk = hp = creatures = 0
    for c, n in full.items():
        e = store.find("cards", c) or {}
        cost = e.get("costo")
        curve[str(cost)] = curve.get(str(cost), 0) + n
        if isinstance(e.get("attacco"), (int, float)) and isinstance(e.get("vita"), (int, float)):
            atk += e["attacco"] * n
            hp += e["vita"] * n
            creatures += n
    rules_n = load("config").get("regole", {})
    hand = rules_n.get("mano_iniziale", 4)
    mana0 = rules_n.get("mana_iniziale", 2)
    res = {"curva_costi": dict(sorted(curve.items(), key=lambda kv: (kv[0] == "None", kv[0].zfill(3)))),
           "creature": creatures, "attacco_totale": atk, "vita_totale": hp, "carte": sum(full.values())}
    cheap = sum(n for c, n in full.items()
                if isinstance((store.find("cards", c) or {}).get("costo"), (int, float))
                and store.find("cards", c)["costo"] <= mana0)
    res[f"p_almeno_una_giocabile_al_round_1_(costo<={mana0})_in_mano_iniziale_{hand}"] = \
        round(odds.p_at_least_one(25, cheap, hand), 4)
    res["nota"] = "Senza contare il mulligan, che è libero e alza questa probabilità."
    return _j(res)


# ======================= PARTITA IN CORSO =======================

@mcp.tool()
def start_match(my_deck: str, opponent_legendary: str = "") -> str:
    """Inizia il tracciamento di una nuova partita con uno dei miei mazzi salvati."""
    d = store.get_deck(my_deck)
    if not d:
        return f"Mazzo '{my_deck}' non trovato. Mazzi: {[x['nome'] for x in load('decks')]}"
    m = {"mio_mazzo": d["nome"], "leggendaria_mia": d["leggendaria"], "carte_mie": d["carte"],
         "turno": 0, "mia_mano": [], "miei_giocati": [], "miei_scartati": [],
         "avv_leggendaria": canonical(opponent_legendary) if opponent_legendary else "",
         "avv_giocati": [], "avv_scartati": [], "avv_mano": None, "location": [], "note": [],
         "viste_in_mano": [], "prima_giocata": {}, "inizio": now(), **deckproj.tag_match(d["nome"])}
    save("match", m)
    if m.get("progetto"):  # il pannello LABORATORIO segue il mazzo che stai giocando
        deckproj.set_options(m["progetto"], attivo=True)
    out = _j(m)
    if m.get("progetto"):
        out += (f"\n\nQuesta partita è un TEST del progetto «{m['progetto']}» v{m['versione']} (modalità creazione "
                "mazzo): consiglia le mosse come in allenamento.")
    return out


def _added(old: list[str], new: list[str]) -> list[str]:
    """Le carte di new in più rispetto a old (per conteggio)."""
    from collections import Counter
    co = Counter(old)
    out = []
    for card, n in Counter(new).items():
        out += [card] * max(0, n - co.get(card, 0))
    return out


def _register_new(m: dict, key: str, cards: list[str]) -> None:
    """Carte giocate DA QUANDO hai risposto l'ultima volta: si SOMMANO alla lista (una seconda copia giocata dopo che
    la prima è morta conta due). Dentro lo stesso round non si contano due volte (due F8 nello stesso round)."""
    turn = str(m.get("turno"))
    per_turn = m.setdefault("aggiunte_round", {}).setdefault(key, {})
    already = per_turn.get(turn) or []
    extra = _added(already, cards)
    per_turn[turn] = already + extra
    m[key] = (m.get(key) or []) + extra


def _who(v) -> str | None:
    """'io' / 'avversario' da come Claude lo scrive (io, me, Daniele, tu, avv, opponent, ...)."""
    s = str(v or "").strip().lower()
    if not s:
        return None
    if s.startswith(("avv", "opp", "nemico", "lui", "loro", "enemy")):
        return "avversario"
    if s.startswith(("io", "me", "mio", "tu", "daniele", "player", "giocatore", "you", "i ", "noi")) or s == "i":
        return "io"
    return None


def reveal_order(m: dict) -> tuple[str | None, bool]:
    """(chi rivela prima in QUESTO round, dedotto?). Si alterna ogni round (regola confermata): dall'ultima volta che
    l'ho letto sullo schermo lo deduco, invece di mostrare il valore vecchio (che dopo un round è sempre sbagliato)."""
    rd = m.get("rivela_prima_letta")
    turn = m.get("turno")
    if not rd or rd.get("chi") not in ("io", "avversario"):
        return None, False
    if rd.get("turno") == turn or not isinstance(turn, int) or not isinstance(rd.get("turno"), int):
        return rd["chi"], False
    same = (turn - rd["turno"]) % 2 == 0
    return (rd["chi"] if same else ("avversario" if rd["chi"] == "io" else "io")), True


def _merge_max(old: list[str], new: list[str]) -> list[str]:
    """Unione per conteggio massimo: ["A","B"] + ["B","B","C"] → ["A","B","B","C"]."""
    from collections import Counter
    co, cn = Counter(old), Counter(new)
    out = list(old)
    for card, n in cn.items():
        out += [card] * max(0, n - co.get(card, 0))
    return out


@mcp.tool()
def update_match(turn: int | None = None, my_hand: list[str] | None = None,
                 my_played: list[str] | None = None, my_discarded: list[str] | None = None,
                 opp_legendary: str | None = None, opp_played: list[str] | None = None,
                 opp_discarded: list[str] | None = None, opp_hand_size: int | None = None,
                 locations: list[str] | None = None, mana: int | None = None,
                 my_barriers: list[int] | None = None, opp_barriers: list[int] | None = None,
                 my_destroyed: int | None = None, opp_destroyed: int | None = None,
                 reveals_first: str | None = None, my_deck_left: int | None = None,
                 my_reinforced: list[bool] | None = None, opp_reinforced: list[bool] | None = None,
                 board: dict | None = None, my_created: list[str] | None = None,
                 opp_created: list[str] | None = None, opp_deck_left: int | None = None, note: str = "",
                 correct_lists: bool = False, my_played_new: list[str] | None = None,
                 opp_played_new: list[str] | None = None, my_hand_size: int | None = None) -> str:
    """Aggiorna lo stato della partita con ciò che vedi sullo schermo e restituisce già le probabilità
    (mia prossima pescata, pescata giocabile, mano avversaria): NON serve chiamare anche my_draw_odds o
    opponent_hand_odds, che restano per domande specifiche (es. "entro 2 round"). Le liste di carte sono lo stato
    COMPLETO attuale (non incrementi): le carte con 2 copie vanno ripetute (es. ["Lupo","Lupo"]).
    my_barriers / opp_barriers: vita delle 3 barrier da sinistra a destra (es. [20, 8, 40]).
    my_destroyed / opp_destroyed: quante barrier ha distrutto l'avversario a me / io a lui.
    my_reinforced / opp_reinforced: quali delle 3 barrier sono rinforzate (max 40), es. [false, false, true].
    board: le creature IN CAMPO per corsia e slot, con le statistiche ATTUALI lette dallo schermo (il danno resta):
      {"sinistra": {"mie": ["Friar Tuck 4/5", null], "avv": [null, "Brides of Dracula 3/3"]}, "centro": {...},
       "destra": {...}}  — stesso ordine di slot da entrambe le parti: il primo elemento è lo slot 1, di fronte
      allo slot 1 avversario; null = vuoto. Con Daniele gli slot si chiamano sempre 1, 2, 3 (mai 0).
      Con board la risposta include la PREVISIONE DEL COMBATTIMENTO se nessuno gioca altro.
    reveals_first: "io" o "avversario" (chi rivela per primo in questo round, se lo schermo lo mostra). Basta leggerlo
      una volta: BIG-BOB lo deduce nei round dopo (si alterna) e lo scrive nella risposta.
    my_deck_left / opp_deck_left: carte rimaste nel mio mazzo / in quello avversario se il gioco le mostra (sono la
      fonte più affidabile per i contatori).
    my_created / opp_created: lista COMPLETA delle carte arrivate NON dal mazzo (la carta del potere leggendario,
      carte generate da Spellbook o da altri effetti, token): non contano come pescate dal mazzo. Le carte pescate in
      più da effetti invece vanno normalmente in mano/giocate (vengono dal mazzo).
    my_played_new / opp_played_new: le carte giocate DA QUANDO hai risposto l'ultima volta (questo round, anche quelle
      viste solo nei fotogrammi dell'osservatore e poi morte o risolte), con le copie ripetute: si SOMMANO a quelle già
      registrate, quindi la seconda copia di una carta giocata dopo che la prima è sparita conta. È il modo giusto di
      registrare le giocate; nello stesso round ripeterle non le conta due volte.
    my_played / opp_played / *_discarded / *_created: liste complete; si uniscono a quelle registrate senza mai
      toglierne (una carta giocata non torna nel mazzo), ma una carta con 2 copie conta 2 solo se la ripeti.
      correct_lists=true sostituisce invece le liste con quelle che passi (solo per correggere un errore di lettura).
    opp_hand_size / my_hand_size: quante carte in mano ha l'avversario / ho io, contate sullo schermo (se non le passi
      BIG-BOB le stima dall'ultimo numero letto: +1 pescata a round, -1 per carta giocata)."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva: usa start_match."
    import copy as _copy
    old_m = _copy.deepcopy(m)
    upd = {"turno": turn, "mia_mano": my_hand, "miei_giocati": my_played, "miei_scartati": my_discarded,
           "avv_giocati": opp_played, "avv_scartati": opp_discarded, "miei_creati": my_created,
           "avv_creati": opp_created}
    grow_only = {"miei_giocati", "miei_scartati", "avv_giocati", "avv_scartati", "miei_creati", "avv_creati"}
    _before = {k: list(m.get(k) or []) for k in grow_only}
    for k, v in upd.items():
        if v is None:
            continue
        v = _canon_list(v) if isinstance(v, list) else v
        if k in grow_only and isinstance(v, list) and not correct_lists:
            v = _merge_max(m.get(k) or [], v)  # le carte giocate non tornano nel mazzo: si somma, non si sostituisce
        m[k] = v
        if k in grow_only and isinstance(v, list):  # anche ciò che arriva dalle liste complete conta come "già visto"
            per_turn = m.setdefault("aggiunte_round", {}).setdefault(k, {})
            t = str(m.get("turno"))
            per_turn[t] = (per_turn.get(t) or []) + _added(_before.get(k, []), v)
    for key, new in (("miei_giocati", my_played_new), ("avv_giocati", opp_played_new)):
        if isinstance(new, list) and new:
            _register_new(m, key, _canon_list(new))
    if my_deck_left is not None or opp_deck_left is not None:
        seen_decks = m.setdefault("mazzi_visti", {})
        for side, val in (("mio", my_deck_left), ("avv", opp_deck_left)):
            if isinstance(val, int) and 0 <= val <= 40:
                seen_decks[side] = {"turno": m.get("turno"), "carte": val}
                try:
                    evaluate.learn_offset(m, side, val)
                except Exception:  # noqa: BLE001
                    pass
    # per il laboratorio dei mazzi: carte passate dalla mano e round della prima giocata
    m["viste_in_mano"] = list(dict.fromkeys((m.get("viste_in_mano") or []) + (m.get("mia_mano") or [])))
    first = m.setdefault("prima_giocata", {})
    for c in m.get("miei_giocati") or []:
        first.setdefault(c, m.get("turno"))
    if locations is not None:
        m["location"] = [canonical(x, "locations") for x in locations]
    extra = {"mana": mana, "barrier_mie": my_barriers, "barrier_avv": opp_barriers,
             "distrutte_a_me": my_destroyed, "distrutte_da_me": opp_destroyed,
             "mazzo_rimasto_visibile": my_deck_left,
             "rinforzate_mie": my_reinforced, "rinforzate_avv": opp_reinforced, "campo": board,
             "avv_mazzo_visibile": opp_deck_left}
    for k, v in extra.items():
        if v is not None:
            m[k] = v
    if _who(reveals_first):
        m["rivela_prima_letta"] = {"turno": m.get("turno"), "chi": _who(reveals_first)}
    m["rivela_prima"], m["rivela_prima_dedotta"] = reveal_order(m)
    if opp_legendary:
        m["avv_leggendaria"] = canonical(opp_legendary)
    if opp_hand_size is not None:
        m["avv_mano"] = opp_hand_size
        m["avv_mano_letta"] = {"turno": m.get("turno"), "mano": opp_hand_size,
                               "uscite": len(m.get("avv_giocati") or []) + len(m.get("avv_scartati") or [])}
    if my_hand is not None or my_hand_size is not None:
        n = my_hand_size if isinstance(my_hand_size, int) else len(my_hand or [])
        m["mia_mano_letta"] = {"turno": m.get("turno"), "mano": n,
                               "uscite": len(m.get("miei_giocati") or []) + len(m.get("miei_scartati") or [])}
    if opp_hand_size is None and m.get("avv_mano_letta"):
        m["avv_mano"] = evaluate.counters(m)["avv_mano"]  # stimata: le probabilità sulla mano usano questa
    if note:
        m.setdefault("note", []).append(f"R{m.get('turno')}: {note}")
    m["aggiornato"] = now()
    # fotografia del round: serve alla cronologia (cosa è stato giocato tra una richiesta e l'altra)
    import time as _t
    snap = {"ora": _t.strftime("%H:%M:%S"), "turno": m.get("turno")}
    for k in ("miei_giocati", "miei_scartati", "avv_giocati", "avv_scartati", "mia_mano", "barrier_mie", "barrier_avv",
              "distrutte_da_me", "distrutte_a_me", "avv_mano", "mana"):
        v = m.get(k)
        snap[k] = list(v) if isinstance(v, list) else v
    m["storico"] = (m.get("storico") or [])[-59:] + [snap]
    # nuovo round: com'è andato quello prima (utilità delle lezioni mostrate, verifica del simulatore, sorprese)
    sorprese = []
    if isinstance(m.get("turno"), int) and isinstance(old_m.get("turno"), int) and m["turno"] > old_m["turno"]:
        from origins import verify
        try:
            shown = (old_m.get("lezioni_mostrate") or {})
            good = verify.round_good(old_m, m)
            if good is not None and shown.get("turno") == old_m.get("turno"):
                lessons.mark_outcome(shown.get("ids") or [], good)
            vc = verify.check(old_m, m)
            if vc:
                m["verifiche"] = (m.get("verifiche") or [])[-19:] + [vc]
                if vc["differenze"]:
                    sorprese.append(f"combattimento del round {vc['turno']} diverso dal previsto: "
                                    + "; ".join(vc["differenze"]) + " (effetto di carta o regola non simulata?)")
        except Exception:  # noqa: BLE001
            pass
    # previsione delle carte avversarie: prima controllo com'è andata quella del round scorso, poi ne faccio una nuova
    try:
        chk = archetype.check_previous(m)
        if chk:
            m["previsioni"] = (m.get("previsioni") or [])[-39:] + [chk]
            if chk.get("sorprese"):
                sorprese.append(f"l'avversario ha giocato carte non previste nel round {chk.get('turno')}: "
                                + ", ".join(chk["sorprese"]))
        pr = archetype.predict(m)
        m["previsione"] = {"turno": m.get("turno"), "viste": dict(evaluate.seen_opp(m)),
                           "carte": [x["carta"] for x in (pr.get("giocabili") or pr.get("carte") or [])[:4]]}
    except Exception:  # noqa: BLE001
        pass
    if sorprese:
        prev_s = m.get("sorprese_round") or {}
        voci = (prev_s.get("voci") or []) if prev_s.get("turno") == m.get("turno") else []
        m["sorprese_round"] = {"turno": m.get("turno"), "voci": list(dict.fromkeys(voci + sorprese))}
    save("match", m)
    view = _match_view(m)
    if my_deck_left is not None:
        full = odds.deck_counts(m["leggendaria_mia"], m["carte_mie"])
        seen = dict(evaluate.seen_mine(m))
        calc = sum(odds.remaining_deck(full, seen).values())
        if calc != my_deck_left:
            view += (f"\n⚠ Il gioco mostra {my_deck_left} carte nel mazzo ma dal tracciamento ne risultano {calc}: "
                     "probabilmente manca una carta in mano/campo/scarti, o un effetto ha aggiunto/rimosso carte.")
    return ("Stato aggiornato.\n" + view + _counters_summary(m) + _locations_summary(m) + _combat_summary(m)
            + _moves_summary(m) + "\n\n" + _odds_summary(m) + _lessons_summary(m) + _surprise_summary(m))


def _counters_summary(m: dict) -> str:
    c = evaluate.counters(m)
    ev = evaluate.heuristic(m)
    est = lambda flag, how: f" (stimato: {how})" if flag else ""  # noqa: E731
    reg = lambda k: ", ".join(f"{n}×{v}" if v > 1 else n for n, v in Counter(m.get(k) or []).items()) or "nessuna"  # noqa: E731
    who, guess = m.get("rivela_prima"), m.get("rivela_prima_dedotta")
    first = (f"\nRIVELA PRIMA: {'tu' if who == 'io' else 'avversario'}"
             + (" (dedotto dall'alternanza: se lo schermo dice altro passa reveals_first)" if guess else "")) if who else (
        "\nRIVELA PRIMA: non so (passa reveals_first quando lo schermo lo mostra)")
    return (f"\n\nCONTATORI: tu mazzo {c['mio_mazzo']}{est(c['mio_mazzo_stimato'], c['mio_mazzo_come'])}"
            f" · mano {c['mia_mano']}{est(c['mia_mano_stimata'], c['mia_mano_come'])}"
            f" | avversario mazzo {c['avv_mazzo'] if c['avv_mazzo'] is not None else '?'}"
            f"{est(c['avv_mazzo_stimato'], c['avv_mazzo_come'])}"
            f" · mano {c['avv_mano'] if c['avv_mano'] is not None else '?'}{est(c['avv_mano_stimata'], c['avv_mano_come'])}"
            f"\nGIOCATE REGISTRATE (se ne manca una passala in *_played_new): tue {reg('miei_giocati')}"
            f" | avversario {reg('avv_giocati')}"
            f"{first}\nSTIMA RAPIDA: vinci al {ev['pct']}% ({ev['motivo']})")


@mcp.tool()
def set_match_eval(mia_percentuale: int, motivo: str = "", campo: str = "", mano: str = "", barrier: str = "") -> str:
    """Salva la tua stima di chi sta vincendo (la barra sopra le barrier nella finestra): mia_percentuale = probabilità
    che Daniele vinca (1-99), motivo = mezza riga. Ragiona su barrier e barrier distrutte, campo, carte in mano e mazzo,
    location e carte probabili dell'avversario. campo / mano / barrier: "vantaggio", "parità" o "svantaggio" di Daniele
    su quel fronte (la finestra li mostra sotto la barra; tieni conto anche di effetti e qualità delle carte, non solo
    dei numeri); vuoto = lascia la stima rapida."""
    return _j(evaluate.save_eval(mia_percentuale, motivo, {"campo": campo, "mano": mano, "barrier": barrier}))


def _locations_summary(m: dict) -> str:
    locs = m.get("location") or []
    if not locs:
        return ""
    rows = []
    for i, name in enumerate(locs[:3]):
        if not name:
            continue
        e = store.find("locations", name)
        lane = combat.LANES[i] if i < 3 else "?"
        rows.append(f"- {lane}: {e['nome']} — {e.get('testo', '')}" if e else
                    f"- {lane}: {name} — NUOVA, non in database: leggi la regola dallo schermo e salvala con upsert_locations")
    return "\n\nLOCATION IN GIOCO:\n" + "\n".join(rows) if rows else ""


def _combat_summary(m: dict) -> str:
    if not m.get("campo"):
        return ""
    lanes = combat.normalize_board(m["campo"])
    res = combat.simulate(lanes, m.get("barrier_mie"), m.get("barrier_avv"), m.get("distrutte_da_me") or 0,
                          m.get("distrutte_a_me") or 0)
    board = combat.board_lines(lanes)
    return ("\n\nCAMPO (slot numerati da 1):\n" + "\n".join(board) if board else "") + \
        "\n\nPREVISIONE COMBATTIMENTO (se nessuno gioca altro; effetti On Reveal esclusi):\n" + combat.summary(res)


def _surprise_summary(m: dict) -> str:
    sr = m.get("sorprese_round") or {}
    if sr.get("turno") != m.get("turno") or not sr.get("voci"):
        return ""
    return "\n\nSORPRESE DEL ROUND PRIMA (materiale per le lezioni): " + " · ".join(sr["voci"])


def _moves_summary(m: dict) -> str:
    """MOSSE CALCOLATE: la ricerca della mossa (solo allenamento e creazione: in ranked BIG-BOB non suggerisce)."""
    from origins import search
    if load("config").get("modalita") == "ranked" or not m.get("mia_mano"):
        return ""
    try:
        pr = archetype.predict(m)
        opp = [x for x in (pr.get("giocabili") or pr.get("carte") or []) if x.get("giocabile", True)]
        r = search.search(m, opp, pr.get("p_giocabile"))
        m["ricerca"] = {"turno": m.get("turno"), "mosse": r.get("mosse", [])[:3]}
        save("match", m)
        rows = search.lines(r)
    except Exception as e:  # noqa: BLE001
        return f"\n\nMOSSE CALCOLATE: non disponibili ({e})"
    return ("\n\n" + "\n".join(rows)) if rows else ""


def _lessons_summary(m: dict) -> str:
    """Lezioni già imparate che riguardano le carte in gioco adesso: entrano nel ragionamento senza altre chiamate."""
    cards = (m.get("mia_mano", []) + m.get("miei_giocati", []) + m.get("avv_giocati", []) + m.get("avv_scartati", [])
             + [m.get("avv_leggendaria") or "", m.get("leggendaria_mia") or ""] + (m.get("location") or []))
    rel = lessons.relevant(cards, limit=3, m=m)
    if rel:  # per il punteggio di utilità: quali lezioni erano davanti al coach in questo round
        m["lezioni_mostrate"] = {"turno": m.get("turno"), "ids": [x["id"] for x in rel]}
        save("match", m)
    def _u(x):
        u = lessons.utility(x)
        return f", utile {round(u * 100)}%" if u is not None else ""
    rows = [f"- {x['id']} {'✅' if x['stato'] == 'confermata' else '❓'} {x['lezione']} (vista {x.get('volte', 1)}×{_u(x)})"
            for x in rel]
    try:  # lezioni del cervello comune che non hai ancora (🌐 = di altri giocatori)
        comm = cervello.lessons_view(cards, limit=2 if rel else 3)
    except Exception:  # noqa: BLE001
        comm = []
    rows += [f"- 🌐{x['id']} {'✅' if x['stato'] == 'confermata' else '❓'} {x['testo']} "
             f"({x.get('sostengono', 1)} giocatori)" for x in comm]
    if not rows:
        return ""
    return "\n\nLEZIONI GIÀ IMPARATE (tienine conto; ❓ = ipotesi; 🌐 = cervello comune):\n" + "\n".join(rows)


def _odds_summary(m: dict, top: int = 6) -> str:
    """Probabilità già calcolate sullo stato appena salvato (evita altre chiamate e numeri vecchi)."""
    lines = ["PROBABILITÀ (calcolate sullo stato aggiornato):"]
    full = odds.deck_counts(m["leggendaria_mia"], m["carte_mie"])
    seen = dict(evaluate.seen_mine(m))
    mine = odds.my_draw_odds(full, seen, 1)
    rem_n = mine["carte_nel_mazzo"]
    per = ", ".join(f"{e['carta']} {round(e['p'] * 100)}%" for e in mine["per_carta"][:top])
    lines.append(f"- Mia prossima pescata ({rem_n} carte nel mazzo): {per or 'mazzo vuoto'}")
    mana = m.get("mana")
    if isinstance(mana, int) and rem_n:
        rem = odds.remaining_deck(full, seen)
        playable = sum(k for c, k in rem.items()
                       if isinstance((store.find("cards", c) or {}).get("costo"), (int, float))
                       and store.find("cards", c)["costo"] <= mana + 1)
        lines.append(f"- Pescata giocabile al prossimo round (costo ≤{mana + 1}): "
                     f"{round(odds.p_at_least_one(rem_n, playable, 1) * 100)}%")
    try:
        pr = archetype.predict(m)
    except Exception:  # noqa: BLE001
        pr = {}
    if m.get("avv_mano") is not None and pr.get("carte"):
        pass  # la mano avversaria è nella PREVISIONE qui sotto (dal mazzo stimato, con le varianti)
    elif m.get("avv_mano") is not None:
        seen_o = dict(evaluate.seen_opp(m))
        o = odds.opponent_hand_odds(load("meta"), m.get("avv_leggendaria") or None, seen_o, m["avv_mano"])
        arch = ", ".join(f"{a['nome']} {round(a['peso'] * 100)}%" for a in o.get("archetipi_compatibili", [])[:3])
        hand = ", ".join(f"{e['carta']} {round(e['p_in_mano'] * 100)}%" for e in o.get("per_carta", [])[:top])
        lines.append(f"- Mano avversaria ({m['avv_mano']} carte): {hand or 'nessun dato'}")
        if arch:
            lines.append(f"- Archetipi compatibili: {arch}")
        if o.get("avviso"):
            lines.append(f"- Nota: {o['avviso']}")
    else:
        lines.append("- Mano avversaria: passa opp_hand_size per avere le probabilità")
    try:
        ident = archetype.identify(m)
        line = archetype.summary(ident)
        if line:
            lines.append(f"\nMAZZO AVVERSARIO (dalle carte viste confrontate con i mazzi del meta): {line}")
            lines += archetype.predict_lines(pr)
        last = (m.get("previsioni") or [None])[-1]
        if last and last.get("turno") != m.get("turno"):
            ok = ", ".join(f"{c} ✓" for c in last["azzeccate"])
            ko = ", ".join(f"{c} ✗" for c in last["sorprese"])
            lines.append(f"- Previsione del round {last.get('turno')}: avevo previsto {', '.join(last['previste']) or 'niente'}"
                         f" → ha giocato {', '.join(x for x in (ok, ko) if x)}"
                         + (" (le ✗ sono sorprese: se insegnano qualcosa, registra una lezione nel turno di "
                            "apprendimento)" if last["sorprese"] else ""))
        if line and ident.get("contro"):
            lines.append(f"- Come giocarci contro (solo in allenamento/creazione): {ident['contro']}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"- Mazzo avversario non stimato: {e}")
    return "\n".join(lines)


def _match_view(m: dict) -> str:
    def info(names):
        out = []
        for n in names:
            e = store.find("cards", n)
            out.append(f"{n} ({_stats(e)})")
        return out
    return _j({"round": m.get("turno"), "mana": m.get("mana"), "rivela_prima": m.get("rivela_prima"),
               "barrier_mie": m.get("barrier_mie"), "barrier_avv": m.get("barrier_avv"),
               "distrutte_a_me": m.get("distrutte_a_me"), "distrutte_da_me": m.get("distrutte_da_me"),
               "mia_mano": info(m.get("mia_mano", [])), "miei_giocati": info(m.get("miei_giocati", [])),
               "avv_leggendaria": m.get("avv_leggendaria"), "avv_giocati": info(m.get("avv_giocati", [])),
               "avv_mano": m.get("avv_mano"), "location": m.get("location")})


@mcp.tool()
def get_match() -> str:
    """Stato completo della partita in corso."""
    m = load("match")
    return _j(m) if m else "Nessuna partita attiva."


@mcp.tool()
def my_draw_odds(draws: int = 1, cards: list[str] | None = None) -> str:
    """Probabilità ESATTE di pescare ciascuna carta del mio mazzo nelle prossime `draws` pescate,
    e (se passi `cards`) di pescare almeno una carta del gruppo. Usa lo stato partita."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    full = odds.deck_counts(m["leggendaria_mia"], m["carte_mie"])
    seen = dict(evaluate.seen_mine(m))
    return _j(odds.my_draw_odds(full, seen, draws, _canon_list(cards) or None))


@mcp.tool()
def opponent_hand_odds(top: int = 10) -> str:
    """Probabilità che l'avversario abbia in mano ciascuna carta, pesata sugli archetipi del meta
    registrati e sulle carte che ha già mostrato."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    if m.get("avv_mano") is None:
        return "Mi serve il numero di carte in mano all'avversario (update_match opp_hand_size)."
    seen = dict(evaluate.seen_opp(m))
    res = odds.opponent_hand_odds(load("meta"), m.get("avv_leggendaria") or None, seen, m["avv_mano"])
    res["per_carta"] = res["per_carta"][:top]
    for e in res["per_carta"]:
        c = store.find("cards", e["carta"])
        if c:
            e["statistiche"], e["testo"] = _stats(c), c.get("testo")
    return _j(res)


@mcp.tool()
def end_match(result: str, opponent_cards_seen: list[str] | None = None, notes: str = "") -> str:
    """Chiude la partita (result: 'vittoria'|'sconfitta'|'pareggio'), salva il log e registra
    il mazzo avversario nel meta."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    seen = list(dict.fromkeys(_canon_list(opponent_cards_seen) or (m.get("avv_giocati", []) + m.get("avv_scartati", []))))
    arch = None
    if m.get("avv_leggendaria"):
        arch = store.record_opponent(m["avv_leggendaria"], seen, result)
    try:
        ident = archetype.identify(m)
    except Exception:  # noqa: BLE001
        ident = {}
    log = load("matches")
    log.append({**m, "risultato": result, "note_finali": notes, "fine": now(),
                "archetipo_avversario": arch["nome"] if arch else None,
                "tipo_avversario": (ident.get("tipo") or {}).get("etichetta"),
                "mazzo_avversario_stimato": (ident.get("mazzi") or [{}])[0].get("nome")})
    save("matches", log)
    save("match", {})
    return _j({"salvata": True, "archetipo": arch})


# ======================= META =======================

@mcp.tool()
def record_opponent_deck(legendary: str, cards_seen: list[str], result: str = "", archetype: str = "",
                         fonte: str = "") -> str:
    """Registra un mazzo avversario. fonte="community" per liste prese da Discord/tornei/video: contano come
    informazione sul meta (pesano nelle probabilità della mano avversaria) ma non come partite tue."""
    return _j(store.record_opponent(legendary, cards_seen, result, archetype,
                                    community=fonte.lower().startswith("comm")))


@mcp.tool()
def opponent_deck() -> str:
    """Che mazzo sta usando l'avversario: le liste del meta più simili alle carte che ha giocato (con probabilità,
    carte fuori lista e carte da aspettarsi) e il tipo (Aggro, Midrange aggro/control, Control, Combo; sottotipi
    Swarm, Tempo, Big, Ramp, Discard), con come giocarci contro. update_match ne mostra già il riassunto."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    return _j(archetype.identify(m, top=5))


@mcp.tool()
def meta_report() -> str:
    """Archetipi avversari incontrati da Daniele (diffusione, carte note, suo winrate contro ciascuno) e un
    riassunto delle liste di OriginsMeta per leggendaria (i dettagli con community_decks / community_stats)."""
    om = [a for a in load("meta") if a.get("fonte") == originsmeta.FONTE]
    by_leg: dict[str, int] = {}
    for a in om:
        by_leg[a["leggendaria"]] = by_leg.get(a["leggendaria"], 0) + 1
    st = originsmeta.load_state()
    return _j({"avversari_di_daniele": store.meta_summary(),
               "originsmeta": {"ultimo_sync": st.get("ultimo_sync"), "liste_per_leggendaria": by_leg,
                               "nota": "pesano nelle probabilità della mano avversaria; dettagli con community_decks"}})


# ======================= CREAZIONE MAZZO (laboratorio) =======================

@mcp.tool()
def deck_project_start(nome: str, leggendaria: str, carte: list[str], obiettivo: str = "", motivo: str = "",
                       fonti: list[str] | None = None, partite: int = 0) -> str:
    """Crea un progetto di mazzo (modalità CREAZIONE MAZZO) con la sua versione 1 e lo salva come mazzo con lo
    stesso nome: le partite giocate scegliendolo con NUOVA contano come partite di test di quella versione.
    motivo: perché queste carte (piano di gioco); fonti: i mazzi meta a cui ti sei ispirato (es. "SNIPER
    (OriginsMeta)"); partite: quante partite di test servono per valutare la v1 (0 = 10)."""
    return _j(deckproj.start(nome, leggendaria, carte, obiettivo, motivo, fonti, partite or None))


@mcp.tool()
def deck_project_status(nome: str = "") -> str:
    """Stato di un progetto di mazzo (vuoto = quello attivo): versioni con vittorie, winrate e intervallo al 95%,
    confronto con la versione precedente (probabilità che sia migliore), partite di test mancanti, statistiche delle
    carte (pescata, giocata, winrate quando giocata, round medio), matchup per leggendaria, punti deboli, miglioria
    in attesa."""
    p = deckproj.get(nome)
    return _j(deckproj.status(p)) if p else "Nessun progetto di mazzo: crealo con deck_project_start."


@mcp.tool()
def deck_project_propose(togli: list[str], metti: list[str], motivo: str, nome: str = "", partite: int = 0) -> str:
    """Propone una miglioria per la prossima versione (stesso numero di carte da togliere e mettere, nomi delle carte
    normali: ognuna vale 2 copie). motivo: quale punto debole risolve e perché (statistiche, lezioni, carte del meta).
    Daniele la applica con il pulsante APPLICA dopo aver cambiato il mazzo nel gioco (o chiedi deck_project_apply se
    te lo dice lui). partite: quante partite di test servono per valutarla (0 = 8 per una carta, 10 per di più)."""
    return _j(deckproj.propose(nome, togli, metti, motivo, partite or None))


@mcp.tool()
def deck_project_apply(nome: str = "") -> str:
    """Applica la miglioria proposta: nasce la versione successiva (solo quando Daniele conferma di averla fatta nel
    gioco)."""
    return _j(deckproj.apply(nome))


@mcp.tool()
def deck_project_revert(versione: int, nome: str = "", motivo: str = "") -> str:
    """Torna alle carte di una versione precedente (diventa una versione nuova, lo storico resta)."""
    return _j(deckproj.revert(nome, versione, motivo))


@mcp.tool()
def deck_project_options(nome: str = "", partite: int = 0, stato: str = "", attivo: bool = False) -> str:
    """Cambia le partite di test della versione attuale, lo stato ('in test' | 'concluso') o rende attivo il
    progetto."""
    return _j(deckproj.set_options(nome, partite or None, stato, attivo))


@mcp.tool()
def deck_project_list() -> str:
    """I progetti di mazzo con versione attuale, partite e stato."""
    out = []
    for p in deckproj.load():
        s = deckproj.summary(p)
        out.append({"nome": p["nome"], "stato": p.get("stato"), "versione": s["v"], "partite_versione": s["partite"],
                    "mancanti": s["mancanti"], "obiettivo": p.get("obiettivo")})
    return _j(out)


# ======================= ORIGINSMETA (meta della community) =======================

@mcp.tool()
def community_decks(leggendaria: str = "", archetipo: str = "", versione: str = "", ordina: str = "winrate",
                    limit: int = 15, min_partite: int = 0) -> str:
    """Mazzi pubblicati su OriginsMeta (community e tornei) con winrate e partite del loro tracker, valutazione,
    versione del gioco, autore, carte e descrizione breve. ordina: winrate | partite | rating | recenti.
    Per la guida completa di un mazzo usa community_deck."""
    return _j(originsmeta.decks(leggendaria, archetipo, versione, ordina, limit, min_partite))


@mcp.tool()
def community_deck(nome: str) -> str:
    """Un mazzo di OriginsMeta per nome o url, con la guida completa (piano di gioco, mulligan, matchup)."""
    d = originsmeta.deck(nome)
    return _j(d) if d else f"Mazzo '{nome}' non trovato tra quelli di OriginsMeta (prova community_decks)."


@mcp.tool()
def community_stats(sezione: str = "") -> str:
    """Statistiche delle partite registrate su OriginsMeta (solo patch attuale): sezione = leggendarie
    (winrate, intervallo, partite, quota), archetipi, carte (winrate nel mazzo / quando giocata, effetto, round
    medio), matchup (griglia leggendaria contro leggendaria), mazzi. Vuoto = tutto."""
    return _j(originsmeta.stats(sezione))


@mcp.tool()
def originsmeta_sync(forza: bool = True) -> str:
    """Scarica adesso da OriginsMeta mazzi, statistiche, carte e location (un minuto circa la prima volta).
    Aggiunge le carte e le location mancanti e applica come patch i cambiamenti di costo/attacco/vita."""
    rep = originsmeta.sync(force=forza)
    return originsmeta.summary_line(rep) + "\n" + _j({k: rep.get(k) for k in (
        "nuovi", "incompleti", "carte_aggiunte", "carte_cambiate", "location_aggiunte", "differenze_carte",
        "errori", "richieste", "secondi")})


@mcp.tool()
def match_history(last: int = 20) -> str:
    """Ultime partite: mazzo usato, avversario, risultato, note."""
    log = load("matches")[-last:]
    return _j([{k: x.get(k) for k in ("fine", "mio_mazzo", "avv_leggendaria", "archetipo_avversario",
                                       "risultato", "note_finali")} for x in log])


# ======================= REGOLE =======================

@mcp.tool()
def rules_get(categoria: str = "", stato: str = "") -> str:
    """Il regolamento ricostruito. Filtri opzionali: categoria (struttura, risorse, turno, rivelazione,
    corsie, vittoria, leggendaria, parole chiave, location, altro) e stato (domanda, ipotesi,
    probabile, confermata, smentita). Le 'domanda' sono le cose che non sappiamo ancora."""
    rs = rules.get(categoria, stato)
    out = [{k: r.get(k) for k in ("id", "categoria", "stato", "testo", "fonti")} | {"prove": len(r.get("prove", []))}
           for r in rs]
    try:
        notes, extra = cervello.rules_view(rules.load())
    except Exception:  # noqa: BLE001
        notes, extra = {}, []
    for r in out:
        if r["id"] in notes:
            r["cervello_comune"] = notes[r["id"]]
    extra = [c for c in extra if (not categoria or c.get("categoria", "").lower() == categoria.lower())
             and (not stato or c.get("stato") == stato)]
    for c in extra[:60]:
        out.append({"id": c["id"], "categoria": c.get("categoria"), "stato": c.get("stato"), "testo": c.get("testo"),
                    "fonti": ["cervello comune"], "giocatori": c.get("giocatori"), "conferme": c.get("conferme"),
                    "smentite": c.get("smentite"), "prove_esempio": c.get("prove", [])[:2]})
    return _j(out)


@mcp.tool()
def rules_upsert(testo: str = "", categoria: str = "", stato: str = "", fonte: str = "",
                 prova: str = "", id: str = "") -> str:
    """Aggiunge una regola (senza id) o aggiorna quella con l'id dato (es. per rispondere a una
    'domanda' riscrivi il testo come regola e cambia stato). fonte: Daniele | tutorial | osservazione
    <registrazione> | esperimento | partita. prova: cosa è stato visto, con turno e carte.
    Stato 'confermata' solo con conferma di Daniele, testo ufficiale del gioco o 2+ osservazioni."""
    try:
        return _j(rules.upsert(testo, categoria, stato, fonte, prova, id))
    except ValueError as e:
        return f"Errore: {e}"


@mcp.tool()
def list_recordings() -> str:
    """Registrazioni di partite (cartelle di fotogrammi salvati con 'Registra' nell'overlay)."""
    from origins import screen
    return _j(screen.list_recordings())


@mcp.tool()
def recording_frames(nome: str, da: int = 0, quanti: int = 10) -> str:
    """Percorsi dei fotogrammi di una registrazione, in ordine, a blocchi (da leggere con Read)."""
    from origins import screen
    d = screen.RECORDINGS / nome
    if not d.is_dir():
        return f"Registrazione '{nome}' non trovata"
    frames = screen.frames_in(d)
    return _j({"totale": len(frames), "da": da, "fotogrammi": [str(p) for p in frames[da:da + quanti]]})


@mcp.tool()
def mark_recording_done(nome: str, riassunto: str = "") -> str:
    """Segna una registrazione come elaborata (e salva il riassunto di ciò che si è imparato)."""
    from origins import screen
    d = screen.RECORDINGS / nome
    if not d.is_dir():
        return f"Registrazione '{nome}' non trovata"
    (d / "ELABORATA").write_text(f"{now()}\n{riassunto}", encoding="utf-8")
    return "Fatto"


@mcp.tool()
def legacy_rules_file() -> str:
    """Contenuto del vecchio data/rules.md (se esiste) da importare una volta nel regolamento;
    dopo l'import viene rinominato rules_vecchio.md."""
    p = store.DATA / "rules.md"
    if not p.exists():
        return "Nessun vecchio rules.md: niente da importare."
    text = p.read_text(encoding="utf-8")
    p.rename(store.DATA / "rules_vecchio.md")
    return "Contenuto del vecchio rules.md (ora rinominato rules_vecchio.md). Importa con rules_upsert le " \
           "informazioni verificate che non sono già nel regolamento:\n\n" + text


# ======================= SIMULAZIONI =======================

@mcp.tool()
def simulate_combat(scenari: list[dict]) -> str:
    """Simula il combattimento di fine round per 1-4 scenari, partendo dal campo salvato con update_match(board).
    Ogni scenario: {"nome": "A", "mie": [{"carta": "Marian", "corsia": "centro", "slot": 1}],
    (slot contati da 1 come nel CAMPO di update_match: 1, 2, 3; senza slot = primo libero),
    "avv": [{"carta": "Brides of Dracula", "corsia": "centro"}],
    "danni_diretti": [{"corsia": "centro", "bersaglio": "mia", "danno": 4, "nota": "Brides On Reveal"}]}.
    Usalo per confrontare 2-3 giocate candidate e la risposta peggiore dell'avversario, invece di fare i conti a mente.
    Gli effetti speciali delle carte non sono simulati: mettili in danni_diretti o ragionaci tu."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    base = combat.normalize_board(m.get("campo") or {})
    mana = m.get("mana")
    out = []
    for sc in scenari[:4]:
        lanes = combat.normalize_board(m.get("campo") or {})
        notes = []
        cost = 0
        for side in ("mie", "avv"):
            for p in sc.get(side, []) or []:
                n = combat.place(lanes, side, p.get("carta"), p.get("corsia", 0), p.get("slot"))
                if n:
                    notes.append(n)
                if side == "mie":
                    e = store.find("cards", p.get("carta", "")) or {}
                    cost += e.get("costo") or 0
        if isinstance(mana, int) and cost > mana:
            notes.append(f"ATTENZIONE: costo {cost} > mana {mana}")
        res = combat.simulate(lanes, m.get("barrier_mie"), m.get("barrier_avv"), m.get("distrutte_da_me") or 0,
                              m.get("distrutte_a_me") or 0, sc.get("danni_diretti"))
        out.append(combat.summary(res, sc.get("nome", "scenario")) + ("\n  note: " + "; ".join(notes) if notes else ""))
    if not out:
        out.append(combat.summary(combat.simulate(base, m.get("barrier_mie"), m.get("barrier_avv"),
                                                  m.get("distrutte_da_me") or 0, m.get("distrutte_a_me") or 0), "base"))
    return "\n\n".join(out)


@mcp.tool()
def mulligan_advice(hand: list[str]) -> str:
    """Consiglio sul mulligan per la mano iniziale (4 carte) del mazzo della partita in corso: valuta tutte le
    combinazioni tieni/cambia (probabilità di avere una giocata nei round 1-3 e mana speso). ~1 secondo."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva: serve start_match per conoscere il mazzo."
    return _j(lab.mulligan_eval(m["leggendaria_mia"], m["carte_mie"], hand))


@mcp.tool()
def deck_lab(decks: list[str] | None = None, legendary: str = "", cards: list[str] | None = None,
             games: int = 2000) -> str:
    """Laboratorio: simula migliaia di partite in solitario per uno o più mazzi (nomi dei mazzi salvati in decks,
    oppure legendary + 12 cards) e confronta giocate per round, mana sfruttato, attacco in campo, leggendaria."""
    todo = []
    for name in decks or []:
        d = store.get_deck(name)
        if d:
            todo.append((d["nome"], d["leggendaria"], d["carte"]))
    if legendary and cards:
        todo.append(("proposta", legendary, cards))
    if not todo:
        return "Indica decks (nomi salvati) oppure legendary + cards."
    out = {}
    for name, leg, cs in todo[:4]:
        out[name] = lab.deck_lab(leg, cs, games=max(200, min(games, 5000)))
    return _j(out)


@mcp.tool()
def note_round(round: int, consiglio_seguito: bool | None = None, esito: str = "") -> str:
    """Annota com'è andato un round (per le statistiche): se Daniele ha seguito il consiglio e com'è andata
    ('bene', 'male', 'neutro' + mezza riga). Usalo nel turno di apprendimento."""
    m = load("match")
    if not m:
        return "Nessuna partita attiva."
    rounds = [r for r in m.get("rounds", []) if r.get("round") != round]
    rounds.append({"round": round, "consiglio_seguito": consiglio_seguito, "esito": esito})
    m["rounds"] = sorted(rounds, key=lambda r: r["round"])
    save("match", m)
    return "Annotato."


# ======================= LEZIONI =======================

@mcp.tool()
def record_lesson(lezione: str, tipo: str, carte: list[str] | None = None, situazione: str = "",
                  accaduto: str = "", perche: str = "", fonte: str = "", id: str = "",
                  condizioni: dict | None = None) -> str:
    """Registra una lezione appresa da qualcosa che non avevi previsto.
    lezione: UNA frase pratica e generale, utile la prossima volta ("Se Dracula ha 3+ mana e il centro è
    sotto 10, aspettati Brides of Dracula lì: tieni un blocco al centro").
    tipo: mossa_avversaria | interazione | errore_coach | mossa_vincente | strategia.
    carte: le carte (e location) coinvolte, per ritrovarla quando tornano in gioco.
    situazione / accaduto / perche: la prova concreta (round, stato, cosa è successo, la spiegazione).
    fonte: "partita R<n>" | "Daniele" | "postpartita" | "video …". Lezioni simili vengono fuse e rafforzate;
    passa id per rafforzare esplicitamente una lezione esistente.
    condizioni (facoltative, servono a richiamarla solo quando vale): {"corsia": "centro", "mana_min": 3, "mana_max": 6,
    "round_min": 2, "round_max": 5, "tipo_avversario": "Aggro", "leggendaria_avversaria": "Dracula",
    "mia_leggendaria": "Robin Hood"}."""
    try:
        return _j(lessons.record(lezione, tipo, carte, situazione, accaduto, perche, fonte, id,
                                 condizioni=condizioni))
    except ValueError as e:
        return f"Errore: {e}"


@mcp.tool()
def lessons_get(carte: list[str] | None = None, tipo: str = "", stato: str = "") -> str:
    """Lezioni imparate. Con carte: solo quelle rilevanti per quelle carte. Filtri: tipo, stato."""
    if carte:
        ls = lessons.relevant(carte, limit=20)
    else:
        ls = lessons.load()
    if tipo:
        ls = [x for x in ls if x.get("tipo") == tipo]
    if stato:
        ls = [x for x in ls if x.get("stato") == stato]
    out = [{k: x.get(k) for k in ("id", "tipo", "stato", "lezione", "carte", "volte")} for x in ls]
    try:
        comm = cervello.lessons_view(carte if carte else None, limit=20)
    except Exception:  # noqa: BLE001
        comm = []
    for x in comm:
        if (tipo and x.get("tipo") != tipo) or (stato and x.get("stato") != stato):
            continue
        out.append({"id": x["id"], "tipo": x.get("tipo"), "stato": x.get("stato"), "lezione": x.get("testo"),
                    "carte": x.get("carte"), "volte": x.get("volte"), "giocatori": x.get("sostengono"),
                    "fonte": "cervello comune"})
    return _j(out)


@mcp.tool()
def cervello_comune(argomento: str = "") -> str:
    """Il cervello comune: ciò che hanno imparato tutti i giocatori di BIG-BOB (anonimo). argomento:
    "" = riassunto (giocatori, winrate per leggendaria, matchup, mazzi avversari più visti); "regole"; "lezioni";
    "carte" (testi concordi tra più giocatori); "mazzi" (carte più viste per leggendaria avversaria);
    "contrasti" (regole in cui tu e gli altri siete in contrasto netto: da verificare con /esperimento).
    Le regole e le lezioni comuni compaiono già in rules_get / lessons_get / update_match con id C… / CL…:
    una regola 'confermata' nel cervello comune è stata confermata da più giocatori diversi."""
    k = cervello.knowledge()
    if not k:
        return _j({"stato": cervello.summary_line(), "nota": "nessun dato scaricato (server non configurato, uso "
                                                          "spento o ancora nessuna sincronizzazione)"})
    a = argomento.lower().strip()
    head = {"giocatori": k.get("giocatori"), "aggiornato": k.get("creato"), "soglia_conferma": k.get("soglia_conferma"),
            "nota": "chi registra le partite sono i giocatori di BIG-BOB: confronta tra loro, non con il 50%"}
    if a.startswith("regol"):
        return _j({**head, "regole": k.get("regole", [])[:120]})
    if a.startswith("lezion"):
        return _j({**head, "lezioni": k.get("lezioni", [])[:120]})
    if a.startswith("cart") or a.startswith("loc"):
        return _j({**head, "carte": k.get("carte", [])[:200], "location": k.get("location", [])[:80]})
    if a.startswith("mazz"):
        return _j({**head, "mazzi_avversari": k.get("mazzi_avversari", [])})
    if a.startswith("contrast"):
        return _j({**head, "contrasti": cervello.contrasts()})
    return _j({**head, "partite": k.get("partite"), "giorni": k.get("giorni_partite"),
               "leggendarie": k.get("leggendarie", [])[:30], "matchup": k.get("matchup", [])[:60],
               "mazzi_avversari": [{x: d.get(x) for x in ("leggendaria", "partite", "giocatori", "winrate_contro")}
                                   for d in k.get("mazzi_avversari", [])[:30]],
               "regole": len(k.get("regole", [])), "lezioni": len(k.get("lezioni", []))})


@mcp.tool()
def lesson_review(id: str, stato: str = "", lezione: str = "", elimina: bool = False) -> str:
    """Conferma (stato="confermata"), smentisce (stato="smentita"), riformula o elimina una lezione.
    Da usare quando Daniele lo chiede o quando una partita dimostra che una lezione era sbagliata."""
    try:
        return _j(lessons.review(id, stato, lezione, elimina))
    except ValueError as e:
        return f"Errore: {e}"


# ======================= IMPOSTAZIONI =======================

@mcp.tool()
def get_settings() -> str:
    """Configurazione: modalità (allenamento/ranked), patch corrente, regole numeriche note."""
    return _j(load("config"))


@mcp.tool()
def set_rules_numbers(mano_iniziale: int | None = None, pescate_per_turno: int | None = None,
                      turni_max: int | None = None, altro: dict | None = None) -> str:
    """Salva i numeri chiave del regolamento scoperti dalle schermate (mano iniziale, pescate...)."""
    cfg = load("config")
    r = cfg.setdefault("regole", {})
    for k, v in {"mano_iniziale": mano_iniziale, "pescate_per_turno": pescate_per_turno,
                 "turni_max": turni_max}.items():
        if v is not None:
            r[k] = v
    if altro:
        r.update(altro)
    save("config", cfg)
    return _j(r)


# Sessione di partita: solo gli strumenti che servono in partita (meno contesto = risposte più rapide ed economiche).
# La sessione di creazione mazzi/studio e Claude Code nel terminale vedono tutto.
LIVE_TOOLS = {
    "get_screen", "update_match", "simulate_combat", "mulligan_advice", "get_card", "search_cards", "get_location",
    "start_match", "end_match", "get_match", "my_draw_odds", "opponent_hand_odds", "record_lesson", "lesson_review",
    "rules_get", "rules_upsert", "upsert_cards", "upsert_locations", "note_round", "set_match_eval", "list_decks",
    "save_deck", "validate_deck", "deck_project_status", "opponent_deck", "deck_project_propose", "community_stats", "community_decks",
}
if os.environ.get("BIGBOB_TOOLSET") == "live":
    for _name in [t.name for t in mcp._tool_manager.list_tools()]:
        if _name not in LIVE_TOOLS:
            mcp.remove_tool(_name)

if __name__ == "__main__":
    mcp.run()
