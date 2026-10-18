"""Simulatore di combattimento di Origins TCG (regole confermate da Daniele, vedi rules_get).

- Le corsie si risolvono da sinistra a destra (la "freccia").
- In una corsia ogni creatura colpisce la creatura nello slot di fronte; se lo slot di fronte è vuoto
  colpisce la barrier, a meno che dall'altra parte ci sia un Defender vivo, che assorbe il colpo
  (Defender difende sempre e più volte).
- I colpi di una corsia sono simultanei; il danno resta sulle creature; a vita 0 muoiono.
- Una barrier a 0 viene distrutta: si rigenera a 40 (rinforzata) e il danno in eccesso si perde.
- Vince chi arriva per primo a 2 barrier distrutte. Se entrambi ci arrivano nella stessa corsia
  il risultato è segnalato come "da verificare" (regola non ancora confermata).
- Effetti alla rivelazione: quelli riconosciuti (danni alla barrier, danni alla creatura di fronte, +A/+V) li applica
  apply_reveal; gli altri non sono simulati e i danni diretti alle barrier si passano a parte (danni_diretti).
"""
from __future__ import annotations

import copy
import re

from origins import store

LANES = ["sinistra", "centro", "destra"]
LANE_ALIASES = {"sinistra": 0, "sx": 0, "left": 0, "0": 0, "centro": 1, "ce": 1, "center": 1, "1": 1,
                "destra": 2, "dx": 2, "right": 2, "2": 2}


def lane_index(x) -> int:
    if isinstance(x, int):
        return max(0, min(2, x))
    return LANE_ALIASES.get(str(x).strip().lower(), 0)


def _keywords(e: dict) -> set[str]:
    words = " ".join([e.get("testo") or ""] + list(e.get("tag") or [])).lower()
    return {k for k in ("defender", "move") if k in words}


# effetti "On Reveal" riconosciuti nel testo delle carte (in inglese, come nel gioco). Si possono anche scrivere a mano
# nel campo "effetti" della carta: [{"tipo": "danno_barrier" | "danno_fronte" | "potenzia", "valore": 3, "vita": 0}]
_ENEMY = r"(?:the\s+)?(?:enemy|opposing|opponent'?s?)"
_FX = [
    ("danno_barrier", re.compile(r"on reveal\s*:?\s*deal\s+(\d+)\s+damage\s+to\s+" + _ENEMY + r"\s+barrier", re.I)),
    # solo la creatura DI FRONTE (non "enemy creatures", non "the one with the highest attack")
    ("danno_fronte", re.compile(r"on reveal\s*:?\s*deal\s+(\d+)\s+damage\s+to\s+" + _ENEMY +
                                r"\s+(?:creature|unit|minion)\s+(?:in front(?: of (?:it|this))?|opposite|across)", re.I)),
    # solo la carta stessa: "On Reveal: gain +2/+1" o "this creature gets +2/+1"
    ("potenzia", re.compile(r"on reveal\s*:?\s*(?:this (?:creature|unit|card)\s+)?(?:gain|gains|get|gets)\s*"
                            r"\+(\d+)\s*/\s*\+(\d+)", re.I)),
]


def effects(e: dict) -> list[dict]:
    """Gli effetti alla rivelazione che il simulatore sa applicare (dal campo 'effetti' o dal testo)."""
    if isinstance(e.get("effetti"), list):
        return [x for x in e["effetti"] if isinstance(x, dict) and x.get("tipo")]
    text = e.get("testo") or ""
    out = []
    for kind, rx in _FX:
        m = rx.search(text)
        if not m:
            continue
        end = text.find(".", m.end())
        sentence = text[m.start(): end if end != -1 else len(text)].lower()
        if re.search(r"\bfor each\b|\bif\b|\bwhen\b|\bunless\b|\brandom|\ball\b|\beach\b|\bother\b|\ballies\b|"
                     r"\bhighest\b|\blowest\b|\bstrongest\b|\bweakest\b|\bcreatures\b", sentence):
            continue  # effetto con condizioni: meglio non simularlo che simularlo sbagliato
        if kind == "potenzia":
            out.append({"tipo": kind, "valore": int(m.group(1)), "vita": int(m.group(2))})
        else:
            out.append({"tipo": kind, "valore": int(m.group(1))})
    return out


_LOC_BUFF = re.compile(r"(?:creatures?|units?)\s+(?:here|in this lane|at this location)\s+(?:get|gain|have)\s*"
                       r"\+(\d+)\s*/\s*\+(\d+)", re.I)
_LOC_ATK = re.compile(r"(?:creatures?|units?)\s+(?:here|in this lane|at this location)\s+(?:get|gain|have)\s*"
                      r"\+(\d+)\s+(?:attack|power)", re.I)


def location_mods(names: list | None) -> dict[int, tuple[int, int, str]]:
    """Modificatori delle location per corsia: {corsia: (attacco, vita, nome)} per le creature che entrano lì.
    Dal campo 'effetti' della location ([{"tipo": "potenzia_corsia", "valore": 1, "vita": 0}]) o dal testo, solo
    nella forma semplice "creatures here get +1/+1" (le regole con condizioni no)."""
    out = {}
    for i, name in enumerate((names or [])[:3]):
        if not name:
            continue
        e = store.find("locations", name) or {}
        fx = [x for x in (e.get("effetti") or []) if isinstance(x, dict) and x.get("tipo") == "potenzia_corsia"]
        if fx:
            out[i] = (int(fx[0].get("valore") or 0), int(fx[0].get("vita") or 0), e.get("nome", name))
            continue
        text = " ".join(str(e.get(k) or "") for k in ("testo", "regola"))
        if re.search(r"\bif\b|\bwhen\b|\bfor each\b|\bunless\b|\benemy\b|\byour\b", text, re.I):
            continue
        m = _LOC_BUFF.search(text)
        if m:
            out[i] = (int(m.group(1)), int(m.group(2)), e.get("nome", name))
            continue
        m = _LOC_ATK.search(text)
        if m:
            out[i] = (int(m.group(1)), 0, e.get("nome", name))
    return out


def apply_reveal(lanes: list[dict], side: str, i: int, k: int, card: str) -> tuple[list[dict], list[str]]:
    """Applica gli effetti alla rivelazione della carta appena messa (corsia i, slot k): ritorna (danni diretti alle
    barrier da passare a simulate, note di cosa è stato simulato)."""
    e = store.find("cards", card) or {}
    direct, notes = [], []
    enemy = "avv" if side == "mie" else "mie"
    for fx in effects(e):
        v = int(fx.get("valore") or 0)
        if fx["tipo"] == "danno_barrier" and v:
            direct.append({"corsia": i, "bersaglio": "avv" if side == "mie" else "mia", "danno": v,
                           "nota": f"{e.get('nome', card)} alla rivelazione"})
            notes.append(f"{e.get('nome', card)}: {v} danni alla barrier")
        elif fx["tipo"] == "danno_fronte" and v:
            row = lanes[i][enemy]
            if k < len(row) and row[k]:
                row[k]["hp"] -= v
                notes.append(f"{e.get('nome', card)}: {v} danni a {row[k]['nome']}")
                if row[k]["hp"] <= 0:
                    row[k] = None
        elif fx["tipo"] == "potenzia":
            u = lanes[i][side][k] if k < len(lanes[i][side]) else None
            if u:
                u["atk"] += v
                u["hp"] += int(fx.get("vita") or 0)
                notes.append(f"{u['nome']}: +{v}/+{int(fx.get('vita') or 0)}")
    return direct, notes


def make_unit(spec) -> dict | None:
    """'Marian', 'Marian 3/1', {'nome':..,'atk':..,'hp':..} -> unità con statistiche correnti."""
    if spec in (None, "", "-", "vuoto"):
        return None
    if isinstance(spec, dict):
        name = spec.get("nome") or spec.get("carta") or "?"
        atk, hp = spec.get("atk", spec.get("attacco")), spec.get("hp", spec.get("vita"))
        kw = set(k.lower() for k in spec.get("kw", []) or [])
    else:
        m = re.match(r"^\s*(.+?)\s+(\d+)\s*/\s*(\d+)\s*$", str(spec))
        name, atk, hp = (m.group(1), int(m.group(2)), int(m.group(3))) if m else (str(spec).strip(), None, None)
        kw = set()
    e = store.find("cards", name) or {}
    unit = {"nome": e.get("nome", name),
            "atk": int(atk if atk is not None else (e.get("attacco") or 0)),
            "hp": int(hp if hp is not None else (e.get("vita") or 1)),
            "kw": sorted(kw | _keywords(e)), "nota_db": "" if e else "non in database"}
    return unit


def normalize_board(board) -> list[dict]:
    """Accetta {'sinistra': {'mie': [...], 'avv': [...]}, ...} o una lista di 3 corsie."""
    lanes = [{"mie": [], "avv": []} for _ in range(3)]
    if not board:
        return lanes
    items = board.items() if isinstance(board, dict) else enumerate(board)
    for key, lane in items:
        i = lane_index(key)
        for side in ("mie", "avv"):
            lanes[i][side] = [make_unit(s) for s in (lane or {}).get(side, [])]
    for lane in lanes:  # stessi slot da entrambe le parti
        n = max(len(lane["mie"]), len(lane["avv"]))
        for side in ("mie", "avv"):
            lane[side] += [None] * (n - len(lane[side]))
    return lanes


def place(lanes: list[dict], side: str, card, lane, slot=None) -> str:
    """Mette una carta in una corsia. slot si conta da 1 come lo vede Daniele (slot 1, 2, 3); se manca, il primo
    libero. Ritorna una nota se qualcosa non va."""
    i = lane_index(lane)
    unit = make_unit(card)
    row = lanes[i][side]
    if slot is None:
        k = next((k for k, u in enumerate(row) if u is None), len(row))
    else:
        k = max(int(slot), 1) - 1
    other = "avv" if side == "mie" else "mie"
    while len(row) <= k:
        row.append(None)
        lanes[i][other].append(None)
    note = ""
    if row[k] is not None:
        note = f"slot {k + 1} di {LANES[i]} era occupato da {row[k]['nome']}: sostituito nella simulazione"
    row[k] = unit
    return note


def board_lines(lanes: list[dict]) -> list[str]:
    """Il campo con gli slot numerati da 1 (slot 1 di fronte a slot 1)."""
    out = []
    for i, lane in enumerate(lanes):
        if not any(lane["mie"]) and not any(lane["avv"]):
            continue
        def side(row):
            return ", ".join(f"slot {k + 1} {u['nome']} {u['atk']}/{u['hp']}" if u else f"slot {k + 1} vuoto"
                             for k, u in enumerate(row)) or "vuoto"
        out.append(f"- {LANES[i]}: tu [{side(lane['mie'])}] · avv [{side(lane['avv'])}]")
    return out


def _hit_target(defenders: list[dict], front: dict | None):
    if front is not None:
        return front
    return defenders[0] if defenders else None


def simulate(lanes: list[dict], barriers_me, barriers_opp, destroyed_by_me: int = 0, destroyed_to_me: int = 0,
             direct: list[dict] | None = None) -> dict:
    lanes = copy.deepcopy(lanes)
    bm = [b if isinstance(b, (int, float)) else 20 for b in (barriers_me or [20, 20, 20])]
    bo = [b if isinstance(b, (int, float)) else 20 for b in (barriers_opp or [20, 20, 20])]
    by_me, to_me = destroyed_by_me or 0, destroyed_to_me or 0
    log, winner = [], None

    def damage_barrier(side, i, dmg, why):
        nonlocal by_me, to_me
        arr = bo if side == "avv" else bm
        before = arr[i]
        arr[i] -= dmg
        if arr[i] <= 0:
            arr[i] = 40
            if side == "avv":
                by_me += 1
            else:
                to_me += 1
            log.append(f"{LANES[i]}: barrier {'avversaria' if side == 'avv' else 'TUA'} DISTRUTTA ({before}→0, {why}); "
                       f"si rinforza a 40")
        else:
            log.append(f"{LANES[i]}: barrier {'avv' if side == 'avv' else 'tua'} {before}→{arr[i]} ({why})")

    for d in direct or []:
        i = lane_index(d.get("corsia", 0))
        side = "avv" if str(d.get("bersaglio", "avv")).startswith("avv") else "mie"
        damage_barrier(side, i, int(d.get("danno", 0)), d.get("nota") or "danno diretto")

    for i, lane in enumerate(lanes):
        start_me, start_opp = by_me, to_me
        incoming = {"mie": {}, "avv": {}}  # id(unit) -> danno
        barrier_hits = {"mie": [], "avv": []}
        for side, enemy in (("mie", "avv"), ("avv", "mie")):
            defenders = [u for u in lane[enemy] if u and "defender" in u["kw"] and u["hp"] > 0]
            for k, u in enumerate(lane[side]):
                if not u or u["hp"] <= 0 or u["atk"] <= 0:
                    continue
                front = lane[enemy][k] if k < len(lane[enemy]) and lane[enemy][k] and lane[enemy][k]["hp"] > 0 else None
                tgt = _hit_target(defenders, front)
                if tgt is not None:
                    incoming[enemy][id(tgt)] = incoming[enemy].get(id(tgt), 0) + u["atk"]
                    log.append(f"{LANES[i]}: {u['nome']} ({u['atk']}) colpisce {tgt['nome']}"
                               + (" [Defender]" if tgt is not front else ""))
                else:
                    barrier_hits[enemy].append((u["nome"], u["atk"]))
        for side in ("mie", "avv"):
            for k, u in enumerate(lane[side]):
                if u and id(u) in incoming[side]:
                    u["hp"] -= incoming[side][id(u)]
                    if u["hp"] <= 0:
                        log.append(f"{LANES[i]}: muore {u['nome']} ({'tua' if side == 'mie' else 'avversaria'})")
                        lane[side][k] = None
        for side in ("avv", "mie"):
            if barrier_hits[side]:
                tot = sum(a for _, a in barrier_hits[side])
                damage_barrier(side, i, tot, " + ".join(f"{n} {a}" for n, a in barrier_hits[side]))
        if winner is None:
            me_win, opp_win = by_me >= 2 > start_me, to_me >= 2 > start_opp
            if me_win and opp_win:
                winner = f"entrambi a 2 barrier nella corsia {LANES[i]}: esito da verificare (regola non confermata)"
            elif me_win:
                winner = f"VINCI TU (seconda barrier distrutta a {LANES[i]})"
            elif opp_win:
                winner = f"VINCE L'AVVERSARIO (seconda barrier distrutta a {LANES[i]})"
    survivors = {LANES[i]: {"mie": [f"{u['nome']} {u['atk']}/{u['hp']}" for u in lane["mie"] if u],
                            "avv": [f"{u['nome']} {u['atk']}/{u['hp']}" for u in lane["avv"] if u]}
                 for i, lane in enumerate(lanes)}
    after = {LANES[i]: {side: [f"{u['nome']} {u['atk']}/{u['hp']}" if u else None for u in lane[side]]
                        for side in ("mie", "avv")} for i, lane in enumerate(lanes)}
    return {"campo": after, "barrier_tue": bm, "barrier_avv": bo, "distrutte_da_te": by_me, "distrutte_a_te": to_me,
            "vincitore": winner, "eventi": log, "sopravvissuti": survivors}


def summary(res: dict, title: str = "") -> str:
    head = f"{title}: " if title else ""
    out = [f"{head}barrier tue {res['barrier_tue']} · avv {res['barrier_avv']} · distrutte tu {res['distrutte_da_te']}"
           f" / avv {res['distrutte_a_te']}" + (f" · {res['vincitore']}" if res["vincitore"] else "")]
    out += [f"  - {e}" for e in res["eventi"]]
    return "\n".join(out)
