"""Consumi di Claude: somma il costo delle risposte per giorno, utile quando BIG-BOB è collegato con una chiave API
(pagamento a consumo). Con l'abbonamento non si paga a consumo e il contatore non si mostra.

Claude Code riporta in ogni risultato il costo totale della sessione (crescente): qui si somma solo la differenza
rispetto al risultato precedente dello stesso processo.
"""
from __future__ import annotations

import time

from origins import store


def _path():
    return store.DATA / "consumi.json"


def _load() -> dict:
    import json
    p = _path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    import json
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(p)


def add(usd: float) -> None:
    if not usd or usd <= 0:
        return
    d = _load()
    day = time.strftime("%Y-%m-%d")
    d.setdefault("giorni", {})
    d["giorni"][day] = round(d["giorni"].get(day, 0.0) + usd, 6)
    _save(d)


def add_from_result(ev: dict, session) -> float:
    """Dal messaggio 'result' di Claude Code: aggiunge il costo di questa risposta (differenza dal totale precedente)."""
    total = ev.get("total_cost_usd")
    if not isinstance(total, (int, float)):
        return 0.0
    pid = getattr(getattr(session, "proc", None), "pid", None)
    last_pid, last = getattr(session, "_cost_pid", None), getattr(session, "_cost_total", 0.0)
    if pid != last_pid:  # processo nuovo: il totale riparte da zero
        last = 0.0
    delta = max(0.0, total - last) if total >= last else total
    session._cost_pid, session._cost_total = pid, total
    add(delta)
    return delta


def summary() -> dict:
    d = _load().get("giorni", {})
    today = time.strftime("%Y-%m-%d")
    month = today[:7]
    return {"oggi": round(d.get(today, 0.0), 2), "mese": round(sum(v for k, v in d.items() if k.startswith(month)), 2)}


def visible() -> bool:
    """Il contatore si vede solo con il collegamento a chiave API."""
    cfg = store.load("config")
    return cfg.get("connessione") == "api" and bool(cfg.get("api_key"))
