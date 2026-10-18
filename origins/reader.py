"""Lettura veloce della schermata con due "lettori" in parallelo (sottoagenti), prima del ragionamento sulla mossa.

Perché: nella risposta live la parte lenta non è pensare la mossa ma trascrivere la schermata in update_match (tanti
token da scrivere) e il giro in più dello strumento. Qui due sessioni piccole e senza strumenti (nessun CLAUDE.md,
nessun server, nessun ragionamento esteso) leggono in parallelo:
- lettore "mio": round, mana, la mia mano, le mie creature in campo, le mie barrier, location, chi rivela prima;
- lettore "avversario": le sue creature, le sue barrier, quante carte ha in mano e, dai fotogrammi dell'osservatore,
  cosa è stato giocato da entrambi da quando ho risposto l'ultima volta.
Ognuno riceve lo STATO REGISTRATO del round prima e scrive solo un JSON (i campi che vede). BIG-BOB unisce i due JSON
e chiama update_match direttamente in Python; poi il coach riceve il risultato già pronto e pensa solo alla mossa.
Se una lettura fallisce si torna al giro normale (il coach legge la schermata da solo).
"""
from __future__ import annotations

import json
import re

LANES = ("sinistra", "centro", "destra")

SYSTEM = ("Sei un lettore di schermate del gioco di carte Origins TCG. Trascrivi esattamente ciò che vedi, in JSON, "
          "senza commenti e senza ragionamenti. Non indovinare: se un valore non si legge, ometti il campo.")

COMMON = (
    "La partita ha 3 corsie (sinistra, centro, destra). In basso c'è il lato di Daniele (\"mie\"), in alto "
    "l'avversario (\"avv\"). Ogni creatura si scrive \"Nome A/V\" con attacco e vita ATTUALI (il danno resta). Gli slot "
    "di ogni corsia vanno da sinistra a destra, null se vuoto, stesso numero di slot da entrambe le parti. "
    "I nomi delle carte restano in inglese, come nel gioco. Rispondi SOLO con un oggetto JSON valido.\n"
)

MINE = (
    "[LETTORE · lato di Daniele] Leggi dall'ULTIMA immagine (la schermata attuale) solo questi campi:\n"
    '{"fase": "gioco" | "mulligan" | "animazione" | "fine" | "altro", "turn": int, "mana": int,\n'
    ' "my_hand": ["Nome", ...] (tutte le carte in mano, le copie ripetute), "my_hand_size": int,\n'
    ' "mie": {"sinistra": [...slot], "centro": [...], "destra": [...]},\n'
    ' "my_barriers": [sx, centro, dx], "my_reinforced": [bool, bool, bool], "my_destroyed": int,\n'
    ' "my_deck_left": int (solo se il numero è scritto), "reveals_first": "io" | "avversario" (solo se è indicato),\n'
    ' "locations": ["Nome sx", "Nome centro", "Nome dx"] (null per quelle non ancora rivelate),\n'
    ' "risultato": "vittoria" | "sconfitta" (solo se la fase è "fine")}\n'
)

BOXES = (
    'Aggiungi anche "riquadri": per ogni corsia e lato, il rettangolo di ogni slot del campo (anche vuoto) in '
    'PERCENTUALE dell\'immagine: {"sinistra": {"mie": [[x, y, larghezza, altezza], ...], "avv": [...]}, "centro": ..., '
    '"destra": ...}. Serve a BIG-BOB per imparare dove sono gli spazi.\n'
)

CLASSIFY = (
    "[LETTORE · che schermata è] Guarda l'immagine del gioco Origins TCG e rispondi SOLO con un JSON: "
    '{"fase": "mulligan" (scelta della mano iniziale, Keep/Replace) | "gioco" (partita in corso) | "fine" (schermata '
    'di vittoria o sconfitta) | "menu" | "altro", "risultato": "vittoria" | "sconfitta" (solo se fine), '
    '"leggendaria_avversaria": "Nome" (solo se si legge)}'
)

ZONE = {"mio": (0.33, 1.0), "avv": (0.0, 0.67)}  # parte verticale della schermata che serve a ogni lettore


def zone_crop(img, side: str, zones: dict | None = None):
    """Solo la parte di schermata che serve a quel lettore (meno immagine da leggere = risposta più rapida). Le due zone
    si sovrappongono al centro, dove stanno corsie, location e barrier."""
    y0, y1 = (zones or ZONE).get(side, (0.0, 1.0))
    return img.crop((0, int(img.height * y0), img.width, int(img.height * y1)))

OPP = (
    "[LETTORE · lato avversario e cosa è successo] Dall'ULTIMA immagine (la schermata attuale) leggi il lato "
    "dell'avversario; dalle immagini prima (fotogrammi e ritagli presi da quando BIG-BOB ha risposto l'ultima volta, "
    "in ordine di tempo) ricostruisci le carte giocate da entrambi, anche se poi distrutte o scartate:\n"
    '{"avv": {"sinistra": [...slot], "centro": [...], "destra": [...]},\n'
    ' "opp_barriers": [sx, centro, dx], "opp_reinforced": [bool, bool, bool], "opp_destroyed": int,\n'
    ' "opp_hand_size": int, "opp_deck_left": int (solo se scritto),\n'
    ' "opp_played_new": ["Nome", ...] (carte giocate dall\'avversario da allora, creature e magie, copie ripetute),\n'
    ' "my_played_new": ["Nome", ...] (carte giocate da Daniele da allora),\n'
    ' "opp_discarded": ["Nome", ...], "opp_created": ["Nome", ...] (carte create da effetti, non dal mazzo)}\n'
    "Una creatura già nello STATO REGISTRATO non è \"giocata da allora\": conta solo quelle nuove.\n"
)


def known_cards(m: dict, predicted: list[str] | None = None) -> str:
    mine = sorted(set((m.get("carte_mie") or []) + [m.get("leggendaria_mia") or ""]) - {""})
    opp = sorted(set((m.get("avv_giocati") or []) + (predicted or []) + [m.get("avv_leggendaria") or ""]) - {""})
    out = ""
    if mine:
        out += "Carte del mazzo di Daniele (usa questi nomi): " + ", ".join(mine) + "\n"
    if opp:
        out += "Carte dell'avversario già viste o probabili: " + ", ".join(opp[:30]) + "\n"
    return out


def previous_state(m: dict) -> str:
    """Lo stato registrato, compatto, per i lettori (così riconoscono cosa è nuovo)."""
    keep = {k: m.get(k) for k in ("turno", "mana", "mia_mano", "barrier_mie", "barrier_avv", "distrutte_da_me",
                                  "distrutte_a_me", "avv_mano", "location", "campo") if m.get(k) not in (None, [], {})}
    return "STATO REGISTRATO (round precedente o ultima lettura): " + json.dumps(keep, ensure_ascii=False) + "\n"


def prompt(side: str, m: dict, predicted: list[str] | None = None, cropped: bool = False, boxes: bool = False) -> str:
    note = ("L'immagine attuale è solo una parte della schermata (" + ("la metà bassa: il tuo lato e le corsie"
            if side == "mio" else "la metà alta: il lato avversario e le corsie") + "): leggi ciò che c'è.\n") if cropped else ""
    return (MINE if side == "mio" else OPP) + COMMON + note + (BOXES if boxes else "") + known_cards(m, predicted) \
        + previous_state(m)


def parse_json(text: str) -> dict | None:
    """Il primo oggetto JSON nella risposta (anche dentro ```json ... ```)."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(t[start:i + 1])
                        return v if isinstance(v, dict) else None
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    return None


def _ints(v, n=3):
    if isinstance(v, list) and len(v) == n and all(isinstance(x, (int, float)) for x in v):
        return [int(x) for x in v]
    return None


def _bools(v, n=3):
    if isinstance(v, list) and len(v) == n:
        return [bool(x) for x in v]
    return None


def _names(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if isinstance(x, str) and x.strip()]
    return None


def _int(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def merge(mine: dict | None, opp: dict | None) -> tuple[dict, list[str]]:
    """Unisce le due letture negli argomenti di update_match. Restituisce (argomenti, avvisi)."""
    mine, opp = mine or {}, opp or {}
    args: dict = {}
    warn: list[str] = []
    for k in ("turn", "mana", "my_destroyed", "my_deck_left", "my_hand_size"):
        if _int(mine.get(k)) is not None:
            args[k] = _int(mine[k])
    for k in ("opp_destroyed", "opp_hand_size", "opp_deck_left"):
        if _int(opp.get(k)) is not None:
            args[k] = _int(opp[k])
    if _names(mine.get("my_hand")) is not None:
        args["my_hand"] = _names(mine["my_hand"])
    for src, k in ((mine, "my_barriers"), (opp, "opp_barriers")):
        if _ints(src.get(k)):
            args[k] = _ints(src[k])
    for src, k in ((mine, "my_reinforced"), (opp, "opp_reinforced")):
        if _bools(src.get(k)):
            args[k] = _bools(src[k])
    if mine.get("reveals_first") in ("io", "avversario"):
        args["reveals_first"] = mine["reveals_first"]
    if isinstance(mine.get("locations"), list) and len(mine["locations"]) == 3:
        locs = [x for x in mine["locations"] if isinstance(x, str) and x.strip()]
        if locs:
            args["locations"] = locs
    for k in ("opp_played_new", "my_played_new", "opp_discarded", "opp_created"):
        if _names(opp.get(k)):
            args[k] = _names(opp[k])
    board = {}
    for lane in LANES:
        a = (mine.get("mie") or {}).get(lane) if isinstance(mine.get("mie"), dict) else None
        b = (opp.get("avv") or {}).get(lane) if isinstance(opp.get("avv"), dict) else None
        if isinstance(a, list) or isinstance(b, list):
            a, b = list(a or []), list(b or [])
            n = max(len(a), len(b))
            board[lane] = {"mie": a + [None] * (n - len(a)), "avv": b + [None] * (n - len(b))}
    if board:
        args["board"] = board
    if not mine:
        warn.append("lato di Daniele non letto")
    if not opp:
        warn.append("lato avversario non letto")
    return args, warn


def usable(mine: dict | None, opp: dict | None) -> bool:
    """La lettura veloce vale solo in fase di gioco e se almeno il lato di Daniele è stato letto."""
    return bool(mine) and (mine.get("fase") in (None, "gioco")) and opp is not None


def check(before: dict, args: dict) -> list[str]:
    """Controllo di coerenza della lettura con lo stato di prima: le cose che non tornano arrivano al coach come avvisi
    (può guardare la schermata e correggere solo quel campo)."""
    warn: list[str] = []
    b = before or {}
    t_old, t_new = b.get("turno"), args.get("turn")
    if isinstance(t_old, int) and isinstance(t_new, int) and t_new < t_old:
        warn.append(f"round letto {t_new} ma prima era {t_old}")
    if isinstance(t_new, int) and isinstance(args.get("mana"), int):
        exp = min(10, t_new + 1)
        if args["mana"] != exp:
            warn.append(f"mana letto {args['mana']}, al round {t_new} di solito è {exp} (location o effetti?)")
    rd = b.get("mia_mano_letta") or {}
    hand = args.get("my_hand_size") if isinstance(args.get("my_hand_size"), int) else (
        len(args["my_hand"]) if isinstance(args.get("my_hand"), list) else None)
    if hand is not None and isinstance(rd.get("mano"), int) and isinstance(rd.get("turno"), int) \
            and isinstance(t_new, int) and t_new > rd["turno"]:
        exp = min(10, rd["mano"] + (t_new - rd["turno"]) - len(args.get("my_played_new") or []))
        if abs(hand - exp) >= 2:
            warn.append(f"in mano lette {hand} carte, dal round prima ne aspettavo circa {exp} (carta non letta o "
                        f"pescata extra?)")
    for key, old_key, reinf_key, who in (("my_barriers", "barrier_mie", "my_reinforced", "tua"),
                                         ("opp_barriers", "barrier_avv", "opp_reinforced", "avversaria")):
        new, old = args.get(key), b.get(old_key)
        if isinstance(new, list) and isinstance(old, list) and len(new) == len(old) == 3:
            for i in range(3):
                if isinstance(new[i], int) and isinstance(old[i], (int, float)) and new[i] > old[i] \
                        and new[i] != 40 and not (args.get(reinf_key) or [False] * 3)[i]:
                    warn.append(f"barrier {who} {LANES[i]} salita da {old[i]} a {new[i]}: lettura da controllare")
    oh_new, oh_old = args.get("opp_hand_size"), b.get("avv_mano")
    if isinstance(oh_new, int) and isinstance(oh_old, int) and oh_new > oh_old + 2:
        warn.append(f"mano avversaria letta {oh_new}, prima era {oh_old}")
    return warn
