"""Spazio su disco: BIG-BOB salva molte immagini (schermate degli F8, fotogrammi dell'osservatore, registrazioni);
qui si tiene solo ciò che serve, così la cartella non cresce senza limiti.

Regole (le applica cleanup(), all'avvio e a fine partita):
1. Osservatore, partite finite: restano solo le immagini allegate a Claude (quelle che la cronologia mostra); gli
   altri fotogrammi servivano solo durante la partita.
2. Osservatore, partite oltre le 30 più recenti: si cancella tutta la cartella.
3. Registrazioni già studiate (ELABORATA) da più di 7 giorni: si cancellano i fotogrammi, resta il riassunto.
4. Limite complessivo (config "spazio_max_mb", 800 MB): se lo si supera si tolgono le schermate delle partite più
   vecchie; il diario (testo, mosse, risposte, domande) resta sempre.
5. Il registro bigbob.log ruota da solo a 5 MB (app.py).
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
CAPTURES = ROOT / "captures"
IMG = (".png", ".jpg", ".jpeg")
OBS_KEEP_MATCHES = 30
REC_KEEP_DAYS = 7
DEFAULT_MAX_MB = 800


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def usage() -> dict:
    """MB usati per zona."""
    zones = {"partite": LOGS / "partite", "registrazioni": CAPTURES / "registrazioni",
             "schermate": CAPTURES / "storico", "scansioni": CAPTURES / "scan", "video": CAPTURES / "video"}
    out = {k: round(_size(p) / 1e6, 1) if p.exists() else 0.0 for k, p in zones.items()}
    out["totale"] = round(sum(out.values()), 1)
    return out


def _matches() -> list[Path]:
    root = LOGS / "partite"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []


def _attached(match: Path) -> set[str]:
    """Le immagini dell'osservatore allegate a Claude, lette dal diario."""
    try:
        text = (match / "diario.md").read_text(encoding="utf-8")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        if line.startswith("Osservatore:"):
            names.update(re.findall(r"[\w-]+\.jpg", line))
    return names


def cleanup(active: Path | None = None, max_mb: int | None = None) -> dict:
    """Applica le regole qui sopra; active = cartella della partita in corso (non si tocca). Restituisce il resoconto."""
    if max_mb is None:
        try:
            from origins import store
            max_mb = int(store.load("config").get("spazio_max_mb") or DEFAULT_MAX_MB)
        except Exception:  # noqa: BLE001
            max_mb = DEFAULT_MAX_MB
    rep = {"fotogrammi_tolti": 0, "cartelle_osservatore_tolte": 0, "registrazioni_alleggerite": 0,
           "schermate_tolte": 0, "mb_liberati": 0.0}
    freed = 0
    active = active.resolve() if active else None
    matches = [m for m in _matches() if m.resolve() != active]
    old_obs = set(matches[:-OBS_KEEP_MATCHES]) if len(matches) > OBS_KEEP_MATCHES else set()
    for m in matches:
        obs = m / "osservatore"
        if not obs.is_dir():
            continue
        if m in old_obs:
            freed += _size(obs)
            shutil.rmtree(obs, ignore_errors=True)
            rep["cartelle_osservatore_tolte"] += 1
            continue
        keep = _attached(m)
        for f in obs.iterdir():
            if f.suffix.lower() in IMG and f.name not in keep:
                try:
                    freed += f.stat().st_size
                    f.unlink()
                    rep["fotogrammi_tolti"] += 1
                except OSError:
                    continue
    rec_root = CAPTURES / "registrazioni"
    if rec_root.exists():
        for d in rec_root.iterdir():
            mark = d / "ELABORATA"
            try:
                if d.is_dir() and mark.exists() and time.time() - mark.stat().st_mtime > REC_KEEP_DAYS * 86400:
                    imgs = [f for f in d.iterdir() if f.suffix.lower() in IMG]
                    if imgs:
                        for f in imgs:
                            freed += f.stat().st_size
                            f.unlink(missing_ok=True)
                        rep["registrazioni_alleggerite"] += 1
            except OSError:
                continue
    # limite complessivo: via le schermate delle partite più vecchie (il diario resta)
    total = usage()["totale"] * 1e6
    for m in matches:
        if total <= max_mb * 1e6:
            break
        for f in sorted(m.rglob("*")):
            if f.is_file() and f.suffix.lower() in IMG:
                try:
                    s = f.stat().st_size
                    f.unlink()
                    freed += s
                    total -= s
                    rep["schermate_tolte"] += 1
                except OSError:
                    continue
    rep["mb_liberati"] = round(freed / 1e6, 1)
    return rep
