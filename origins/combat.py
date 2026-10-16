"""Simulatore di combattimento di Origins TCG (regole confermate da Daniele, vedi rules_get).

- Le corsie si risolvono da sinistra a destra (la "freccia").
- In una corsia ogni creatura colpisce la creatura nello slot di fronte; se lo slot di fronte è vuoto
  colpisce la barrier, a meno che dall'altra parte ci sia un Defender vivo, che assorbe il colpo
  (Defender difende sempre e più volte).
- I colpi di una corsia sono simultanei; il danno resta sulle creature; a vita 0 muoiono.
- Una barrier a 0 viene distrutta: si rigenera a 40 (rinforzata) e il danno in eccesso si perde.
- Vince chi arriva per primo a 2 barrier distrutte. Se entrambi ci arrivano nella stessa corsia
  il risultato è segnalato come "da verificare" (regola non ancora confermata).
- Gli effetti speciali (On Reveal, ecc.) non sono simulati: i danni diretti alle barrier si passano
  a parte (danni_diretti) e vengono applicati prima del combattimento.
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
    return {"barrier_tue": bm, "barrier_avv": bo, "distrutte_da_te": by_me, "distrutte_a_te": to_me,
            "vincitore": winner, "eventi": log, "sopravvissuti": survivors}


def summary(res: dict, title: str = "") -> str:
    head = f"{title}: " if title else ""
    out = [f"{head}barrier tue {res['barrier_tue']} · avv {res['barrier_avv']} · distrutte tu {res['distrutte_da_te']}"
           f" / avv {res['distrutte_a_te']}" + (f" · {res['vincitore']}" if res["vincitore"] else "")]
    out += [f"  - {e}" for e in res["eventi"]]
    return "\n".join(out)
