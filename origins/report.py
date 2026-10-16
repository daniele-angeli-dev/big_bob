"""Pagine HTML locali: statistiche personali e replay di una partita (dal diario).

python -m origins.report stats           -> logs/statistiche.html
python -m origins.report replay <cartella> -> logs/partite/<cartella>/replay.html
"""
from __future__ import annotations

import html
import re
import sys
from collections import defaultdict
from pathlib import Path

from origins import deckproj, lessons, rules, store

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

CSS = """
:root{--bg:#24104F;--panel:#3A1A78;--line:#6B4BB0;--text:#fff;--dim:#D9CCFF;--teal:#1FD6C4;--orange:#FF8A3D;--yellow:#FFD23F}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:'Bahnschrift SemiCondensed',Bahnschrift,'Segoe UI',sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-family:Impact,'Arial Narrow Bold',sans-serif;font-style:italic;color:var(--yellow);letter-spacing:1px;margin:0 0 4px;font-size:34px}
h2{font-size:15px;letter-spacing:2px;color:var(--dim);margin:28px 0 10px;text-transform:uppercase}
.sub{color:var(--dim);margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.tile{background:var(--panel);border-radius:10px;padding:14px}
.tile b{display:block;font-family:Impact,sans-serif;font-size:34px;font-weight:400}
.tile span{color:var(--dim);font-size:13px;letter-spacing:1px}
.bars{background:var(--panel);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:8px}
.bar{display:grid;grid-template-columns:minmax(120px,220px) 1fr 120px;gap:10px;align-items:center;font-size:14px}
.track{height:14px;background:var(--bg);border-radius:0 4px 4px 0;position:relative}
.fill{height:14px;background:var(--teal);border-radius:0 4px 4px 0}
.fifty{position:absolute;top:-3px;bottom:-3px;left:50%;width:1px;background:var(--dim);opacity:.6}
.val{color:var(--dim);text-align:right;white-space:nowrap}
table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;overflow:hidden;font-size:14px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--dim);font-weight:600}
.empty{color:var(--dim);background:var(--panel);border-radius:10px;padding:14px}
.round{background:var(--panel);border-radius:10px;padding:14px;margin-bottom:14px;display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:14px}
.round img{width:100%;border-radius:6px;display:block}
.round pre{white-space:pre-wrap;font-family:inherit;margin:0;font-size:14px;line-height:1.4}
.meta{color:var(--dim);font-size:13px;margin-bottom:6px}
.learn{white-space:pre-wrap;border-left:4px solid var(--teal);padding:6px 10px;background:#14405A;border-radius:6px;margin-top:8px;font-size:14px}
.flag{white-space:pre-wrap;border-left:4px solid var(--orange);padding:6px 10px;background:#5A1630;border-radius:6px;margin-top:8px;font-size:14px}
.sess{background:var(--panel);border-radius:10px;padding:14px 16px;margin-bottom:12px}
.sess.first{border:2px solid var(--yellow)}
.sess h3{margin:0;font-size:17px;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline}
.sess h3 small{color:var(--dim);font-weight:400;font-size:13px}
.sess .sum{color:var(--dim);font-size:13px;margin:4px 0 10px}
.sess .none{color:var(--dim);font-style:italic;font-size:14px}
.sess ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.sess li{display:grid;grid-template-columns:104px 1fr;gap:10px;align-items:start;font-size:14px;line-height:1.4}
.sess li .why{color:var(--dim);font-size:13px;margin-top:2px}
.sess li .cards{color:var(--yellow);font-size:12px;margin-top:2px}
.bd{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:700;letter-spacing:.8px;text-align:center}
.bd.new{background:var(--teal);color:var(--bg)}.bd.up{background:#14405A;color:#7DEDE2}
.bd.ok{background:var(--yellow);color:var(--bg)}.bd.ko{background:#5A1630;color:#FFB3C1}
.bd.rule{background:var(--orange);color:var(--bg)}.bd.card{background:#4B2A93;color:#fff}
.note{background:#14405A;border-radius:6px;padding:8px 10px;font-size:14px;margin-bottom:10px;white-space:pre-wrap}
td.st{white-space:nowrap}
@media (max-width:720px){.sess li{grid-template-columns:1fr}}
.ver{background:var(--panel);border-radius:10px;padding:12px 14px;margin-bottom:10px;display:grid;grid-template-columns:70px minmax(0,1fr) minmax(160px,260px);gap:12px;align-items:center}
.ver.cur{border:2px solid var(--teal)}
.ver .vn{font-family:Impact,sans-serif;font-size:28px;color:var(--yellow)}
.ver .chg{font-size:14px}.ver .chg .out{color:#FF9CB0}.ver .chg .in{color:#7DEDE2}
.ver .why{color:var(--dim);font-size:13px;margin-top:3px}
.ci{position:relative;height:16px;background:var(--bg);border-radius:4px}
.ci .rng{position:absolute;top:3px;bottom:3px;background:#14405A;border-radius:3px}
.ci .pt{position:absolute;top:-2px;width:4px;height:20px;background:var(--teal);border-radius:2px;margin-left:-2px}
.ci .fifty{position:absolute;top:-3px;bottom:-3px;left:50%;width:1px;background:var(--dim);opacity:.5}
.cival{color:var(--dim);font-size:12px;margin-top:4px;text-align:right}
tr.weak td{background:#5A1630}
.deck{display:flex;flex-wrap:wrap;gap:6px}.deck span{background:var(--panel);border-radius:6px;padding:5px 9px;font-size:14px}
.deck span.lg{background:var(--yellow);color:var(--bg);font-weight:700}
@media (max-width:720px){.ver{grid-template-columns:1fr}}
@media (max-width:720px){.round{grid-template-columns:1fr}.bar{grid-template-columns:110px 1fr 90px}}
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='it'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{CSS}</style>"
            f"</head><body><main>{body}</main></body></html>")


def _bars(rows: list[tuple[str, int, int]]) -> str:
    """rows: (etichetta, vittorie, partite) -> barre del winrate con linea al 50%."""
    if not rows:
        return "<div class='empty'>Ancora nessuna partita registrata.</div>"
    out = ["<div class='bars' role='list'>"]
    for label, w, g in sorted(rows, key=lambda r: (-r[2], r[0])):
        pct = w / g * 100 if g else 0
        tip = f"{label}: {w} vinte su {g} ({pct:.0f}%)"
        out.append(f"<div class='bar' role='listitem' title='{html.escape(tip)}'><div>{html.escape(label)}</div>"
                   f"<div class='track'><div class='fill' style='width:{pct:.1f}%'></div><div class='fifty'></div></div>"
                   f"<div class='val'>{pct:.0f}% · {w}/{g}</div></div>")
    out.append("</div>")
    return "".join(out)


def _times() -> list[float]:
    out = []
    for d in (LOGS / "partite").glob("*/diario.md"):
        out += [float(x) for x in re.findall(r"Tempo totale: ([\d.]+)s", d.read_text(encoding="utf-8"))]
    return out


def stats_html() -> Path:
    log = store.load("matches")
    games = [m for m in log if m.get("risultato")]
    wins = [m for m in games if str(m["risultato"]).lower().startswith("v")]
    by_deck: dict = defaultdict(lambda: [0, 0])
    by_arch: dict = defaultdict(lambda: [0, 0])
    by_loc: dict = defaultdict(lambda: [0, 0])
    followed = [0, 0, 0]  # seguito, seguito e andato bene, rounds annotati
    for m in games:
        win = str(m["risultato"]).lower().startswith("v")
        for key, bucket in ((m.get("mio_mazzo") or "?", by_deck),
                            (m.get("archetipo_avversario") or m.get("avv_leggendaria") or "?", by_arch)):
            bucket[key][0] += win
            bucket[key][1] += 1
        for loc in set(m.get("location") or []):
            by_loc[loc][0] += win
            by_loc[loc][1] += 1
        for r in m.get("rounds") or []:
            followed[2] += 1
            if r.get("consiglio_seguito"):
                followed[0] += 1
                if str(r.get("esito", "")).lower().startswith("bene"):
                    followed[1] += 1
    times = _times()
    ls = lessons.load()
    tiles = [
        (str(len(games)), "PARTITE"),
        (f"{len(wins) / len(games) * 100:.0f}%" if games else "–", "WINRATE"),
        (f"{sum(times) / len(times):.0f} s" if times else "–", "RISPOSTA MEDIA"),
        (f"{sum(1 for t in times if t > 40) / len(times) * 100:.0f}%" if times else "–", "RISPOSTE OLTRE 40 s"),
        (f"{followed[0] / followed[2] * 100:.0f}%" if followed[2] else "–", "CONSIGLI SEGUITI"),
        (f"{followed[1] / followed[0] * 100:.0f}%" if followed[0] else "–", "…E ANDATI BENE"),
        (str(sum(1 for x in ls if x.get("stato") == "confermata")), "LEZIONI CONFERMATE"),
    ]
    body = ["<h1>BIG-BOB · STATISTICHE</h1>",
            f"<p class='sub'>{len(games)} partite registrate · aggiornato {store.now()}</p>",
            "<div class='tiles'>" + "".join(f"<div class='tile'><b>{v}</b><span>{k}</span></div>" for v, k in tiles)
            + "</div>",
            "<h2>Winrate per mio mazzo</h2>", _bars([(k, v[0], v[1]) for k, v in by_deck.items()]),
            "<h2>Winrate contro archetipo avversario</h2>", _bars([(k, v[0], v[1]) for k, v in by_arch.items()]),
            "<h2>Winrate per location in gioco</h2>", _bars([(k, v[0], v[1]) for k, v in by_loc.items()])]
    if games:
        rows = "".join(
            f"<tr><td>{html.escape(str(m.get('fine', '')))}</td><td>{html.escape(str(m.get('mio_mazzo', '')))}</td>"
            f"<td>{html.escape(str(m.get('archetipo_avversario') or m.get('avv_leggendaria') or ''))}</td>"
            f"<td>{html.escape(str(m.get('risultato', '')))}</td></tr>" for m in reversed(games[-30:]))
        body.append("<h2>Ultime partite</h2><table><thead><tr><th>Data</th><th>Mazzo</th><th>Avversario</th>"
                    f"<th>Risultato</th></tr></thead><tbody>{rows}</tbody></table>")
    out = LOGS / "statistiche.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page("BIG-BOB · statistiche", "".join(body)), encoding="utf-8")
    return out


def replay_html(journal_dir: Path) -> Path:
    text = (journal_dir / "diario.md").read_text(encoding="utf-8")
    head = text.split("\n## ", 1)[0]
    parts = re.split(r"\n(?=## #|### )", text)
    body = [f"<h1>RIVEDI LA PARTITA</h1><p class='sub'>{html.escape(head.replace('#', '').strip())}</p>"]
    for p in parts:
        p = p.strip()
        if p.startswith("## #"):
            first, _, rest = p.partition("\n")
            img = re.search(r"schermata (\S+\.png)", first)
            meta = re.findall(r"^(Strumenti:.*|Tempo totale:.*)$", rest, flags=re.M)
            answer = re.sub(r"^(Strumenti:.*|Tempo totale:.*)$", "", rest, flags=re.M).strip()
            body.append("<section class='round'><div>"
                        + (f"<img src='{img.group(1)}' alt='Schermata della richiesta'>" if img else "")
                        + f"</div><div><div class='meta'>{html.escape(first.lstrip('# '))}<br>"
                        + "<br>".join(html.escape(x) for x in meta) + f"</div><pre>{html.escape(answer)}</pre>")
            body.append("</div></section>")
        elif p.startswith("### 📚"):
            body.insert(len(body) - 1, f"<div class='learn'>{html.escape(p.lstrip('# '))}</div>")
        elif p.startswith("### ❌"):
            body.insert(len(body) - 1, f"<div class='flag'>{html.escape(p.lstrip('# '))}</div>")
    out = journal_dir / "replay.html"
    out.write_text(_page("BIG-BOB · replay", "".join(body)), encoding="utf-8")
    return out


# ---------------------------------------------------------------- cosa ho imparato

def _ts(x) -> float | None:
    import datetime as _dt
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y%m%d-%H%M%S", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(str(x).strip()[:19], fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def _learn_events() -> list[dict]:
    """Tutto ciò che BIG-BOB ha imparato, come eventi con data: lezioni, regole, carte e location nuove o cambiate."""
    ev: list[dict] = []
    for L in lessons.load():
        prove = L.get("prove") or []
        first_is_birth = len(prove) >= (L.get("volte") or 0)
        for i, p in enumerate(prove):
            if i == 0 and first_is_birth:
                az, cls = "NUOVA LEZIONE", "new"
            elif L.get("stato") == "confermata" and i == 1 and first_is_birth:
                az, cls = "CONFERMATA", "ok"
            else:
                az, cls = "RAFFORZATA", "up"
            why = " · ".join(x for x in (p.get("accaduto"), p.get("perche")) if x)
            ev.append({"t": _ts(p.get("data")), "data": p.get("data"), "badge": az, "cls": cls,
                       "testo": f"{L['lezione']} ({L['id']} {lessons.STATI.get(L.get('stato'), '')})",
                       "why": why, "carte": L.get("carte") or [], "fonte": p.get("fonte") or ""})
        if L.get("stato") == "smentita":
            ev.append({"t": _ts(L.get("ultima")), "data": L.get("ultima"), "badge": "SMENTITA", "cls": "ko",
                       "testo": f"{L['lezione']} ({L['id']})", "why": "una partita ha dimostrato che era sbagliata",
                       "carte": L.get("carte") or [], "fonte": ""})
    for r in rules.load():
        if r.get("creata") and not any(h for h in r.get("storico") or []):
            ev.append({"t": _ts(r["creata"]), "data": r["creata"], "badge": "REGOLA NUOVA", "cls": "rule",
                       "testo": f"{r['testo']} ({r['id']} {rules.STATI.get(r.get('stato'), '')})", "why": "",
                       "carte": [], "fonte": ", ".join(r.get("fonti") or [])})
        hist = r.get("storico") or []
        for i, h in enumerate(hist):
            after = hist[i + 1] if i + 1 < len(hist) else {"testo": r.get("testo"), "stato": r.get("stato")}
            change = []
            if h.get("stato") != after.get("stato"):
                change.append(f"{h.get('stato')} → {after.get('stato')}")
            if h.get("testo") != after.get("testo"):
                change.append(f"prima: «{h.get('testo')}»")
            ev.append({"t": _ts(h.get("data")), "data": h.get("data"),
                       "badge": "REGOLA SMENTITA" if after.get("stato") == "smentita" else "REGOLA AGGIORNATA",
                       "cls": "ko" if after.get("stato") == "smentita" else "rule",
                       "testo": f"{after.get('testo')} ({r['id']} {rules.STATI.get(after.get('stato'), '')})",
                       "why": " · ".join(change), "carte": [], "fonte": ", ".join(r.get("fonti") or [])})
        for p in r.get("prove") or []:
            if p.get("data") == r.get("creata") and not hist:
                continue  # è la prova con cui la regola è nata: già mostrata come REGOLA NUOVA
            if not hist or not any(h.get("data") == p.get("data") for h in hist):
                ev.append({"t": _ts(p.get("data")), "data": p.get("data"), "badge": "PROVA REGOLA", "cls": "up",
                           "testo": f"{r['testo']} ({r['id']})", "why": p.get("nota") or "", "carte": [],
                           "fonte": p.get("fonte") or ""})
    for kind, label in (("cards", "CARTA"), ("locations", "LOCATION")):
        site: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for c in store.load(kind):
            if c.get("aggiunta"):
                if c.get("fonte") == "originsmeta":
                    site[str(c["aggiunta"])[:10]].append((c["nome"], str(c["aggiunta"])))
                else:
                    ev.append({"t": _ts(c["aggiunta"]), "data": c["aggiunta"], "badge": f"{label} NUOVA",
                               "cls": "card", "testo": c["nome"] + (f" — {c['testo']}" if c.get("testo") else ""),
                               "why": "letta dallo schermo e salvata", "carte": [], "fonte": c.get("fonte") or ""})
            for h in c.get("storico") or []:
                mods = ", ".join(f"{m['campo']} {m['prima']}→{m['dopo']}" for m in h.get("modifiche") or [])
                ev.append({"t": _ts(h.get("data")), "data": h.get("data"), "badge": f"{label} CAMBIATA",
                           "cls": "card", "testo": f"{c['nome']}: {mods}", "why": f"patch {h.get('patch')}",
                           "carte": [], "fonte": "patch", "db": True})
        for day, items in site.items():
            names = [n for n, _ in items]
            ev.append({"t": max(_ts(t) or 0 for _, t in items), "data": day, "badge": f"{label} DAL SITO", "cls": "card",
                       "testo": f"{len(names)} {'carte' if kind == 'cards' else 'location'} importate da OriginsMeta",
                       "why": ", ".join(names[:12]) + ("…" if len(names) > 12 else ""), "carte": [],
                       "fonte": "originsmeta", "db": True})
    return [e for e in ev if e["t"] is not None]


def _sessions() -> list[dict]:
    """Partite (dal registro e quella in corso) e registrazioni elaborate, con la finestra di tempo di ciascuna."""
    ss: list[dict] = []
    log = store.load("matches")
    cur = store.load("match") if store.FILES["match"].exists() else {}
    matches = [m for m in log if m.get("inizio")] + ([dict(cur, in_corso=True)] if cur.get("inizio") else [])
    starts = sorted(_ts(m["inizio"]) for m in matches if _ts(m["inizio"]))
    for m in matches:
        t0 = _ts(m["inizio"])
        if t0 is None:
            continue
        nxt = next((s for s in starts if s > t0), None)
        end = _ts(m.get("fine")) if m.get("fine") else None
        t1 = (end + 20 * 60) if end else (nxt or 1e12)  # le lezioni di fine partita arrivano subito dopo
        if nxt:
            t1 = min(t1, nxt)
        opp = m.get("archetipo_avversario") or m.get("avv_leggendaria") or "avversario sconosciuto"
        res = m.get("risultato") or ("in corso" if m.get("in_corso") else "")
        ss.append({"kind": "partita", "t0": t0, "t1": t1, "titolo": f"Partita · {m.get('mio_mazzo') or '?'} contro {opp}",
                   "quando": str(m["inizio"]), "esito": res, "nota": m.get("note_finali") or ""})
    try:
        from origins import screen
        recs = screen.list_recordings() if screen.RECORDINGS.exists() else []
    except Exception:  # noqa: BLE001
        recs = []
    for r in recs:
        done = Path(r["cartella"]) / "ELABORATA"
        if not done.exists():
            t = _ts(r["nome"]) or 0
            import datetime as _dt
            ss.append({"kind": "registrazione", "t0": t, "t1": t,
                       "titolo": f"Registrazione {r['nome']}",
                       "quando": _dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "",
                       "esito": f"{r['fotogrammi']} fotogrammi · da studiare: in Claude Code scrivi /impara-regole",
                       "nota": "", "nome": r["nome"], "pending": True})
            continue
        first, _, summary = done.read_text(encoding="utf-8").partition("\n")
        t = _ts(first) or done.stat().st_mtime
        ss.append({"kind": "registrazione", "t0": t - 3 * 3600, "t1": t + 120, "titolo": f"Registrazione {r['nome']}",
                   "quando": f"studiata il {first.strip()}", "esito": f"{r['fotogrammi']} fotogrammi",
                   "nota": summary.strip(), "nome": r["nome"]})
    return ss


def learned_html() -> Path:
    events = sorted(_learn_events(), key=lambda e: e["t"], reverse=True)
    sessions = _sessions()
    groups: dict[int, list[dict]] = defaultdict(list)
    loose: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        target = None
        if not e.get("db"):
            for i, s in enumerate(sessions):  # prima la registrazione citata nella fonte, poi le finestre di tempo
                if s["kind"] == "registrazione" and s.get("nome") and s["nome"] in (e.get("fonte") or ""):
                    target = i
                    break
            if target is None:
                for kind in ("partita", "registrazione"):
                    target = next((i for i, s in enumerate(sessions) if s["kind"] == kind and not s.get("pending")
                                   and s["t0"] <= e["t"] <= s["t1"]), None)
                    if target is not None:
                        break
        if target is None:
            loose[str(e["data"])[:10]].append(e)
        else:
            groups[target].append(e)

    blocks = []
    for i, s in enumerate(sessions):
        blocks.append((s["t0"] if s["kind"] == "partita" else s["t1"], s, groups.get(i, [])))
    for day, evs in loose.items():
        blocks.append((max(e["t"] for e in evs), {"kind": "altro", "titolo": "Studio e aggiornamenti",
                                                  "quando": day, "esito": "Claude Code, interviste, video, sito",
                                                  "nota": ""}, evs))
    blocks.sort(key=lambda b: b[0], reverse=True)

    def item(e: dict) -> str:
        cards = f"<div class='cards'>{html.escape(', '.join(e['carte']))}</div>" if e.get("carte") else ""
        why = f"<div class='why'>{html.escape(e['why'])}</div>" if e.get("why") else ""
        return (f"<li><span class='bd {e['cls']}'>{html.escape(e['badge'])}</span><div>{html.escape(e['testo'])}"
                f"{why}{cards}</div></li>")

    out_blocks = []
    for n, (_, s, evs) in enumerate(blocks[:40]):
        cat = {"new": 0, "up": 0, "ko": 0, "rule": 0, "card": 0}
        for e in evs:
            b = e["badge"]
            key = ("rule" if ("REGOLA" in b and "SMENTITA" not in b) else "ko" if "SMENTITA" in b
                   else "new" if b == "NUOVA LEZIONE" else "up" if b in ("RAFFORZATA", "CONFERMATA") else "card")
            cat[key] += 1
        bits = []
        if cat["new"]:
            bits.append("1 lezione nuova" if cat["new"] == 1 else f"{cat['new']} lezioni nuove")
        if cat["up"]:
            bits.append(f"{cat['up']} rafforzat{'a' if cat['up'] == 1 else 'e'} o confermat{'a' if cat['up'] == 1 else 'e'}")
        if cat["ko"]:
            bits.append(f"{cat['ko']} smentit{'a' if cat['ko'] == 1 else 'e'}")
        if cat["rule"]:
            bits.append(f"{cat['rule']} sul regolamento")
        if cat["card"]:
            bits.append(f"{cat['card']} su carte e location")
        head = (f"<h3>{html.escape(s['titolo'])}<small>{html.escape(str(s['quando']))}"
                + (f" · {html.escape(str(s['esito']))}" if s.get("esito") else "") + "</small></h3>")
        if evs:
            summ = f"<div class='sum'>Ha imparato: {html.escape(' · '.join(bits))}</div>"
            body = "<ul>" + "".join(item(e) for e in sorted(evs, key=lambda e: e["t"])) + "</ul>"
        elif s.get("pending"):
            summ, body = "", "<div class='none'>Non ancora studiata.</div>"
        else:
            summ = ""
            body = ("<div class='none'>Niente di nuovo: nessuna sorpresa da annotare in questa "
                    + ("partita" if s["kind"] == "partita" else "registrazione") + ".</div>")
        note = f"<div class='note'>{html.escape(s['nota'])}</div>" if s.get("nota") else ""
        out_blocks.append(f"<section class='sess{' first' if n == 0 else ''}'>{head}{summ}{note}{body}</section>")

    ls = lessons.load()
    rs = rules.load()
    cnt = lambda xs, st: sum(1 for x in xs if x.get("stato") == st)  # noqa: E731
    tiles = [(str(len(ls)), "LEZIONI"), (str(cnt(ls, "confermata")), "CONFERMATE ✅"), (str(cnt(ls, "ipotesi")), "DA VERIFICARE ❓"),
             (str(cnt(ls, "smentita")), "SMENTITE ❌"), (f"{cnt(rs, 'confermata')}/{len(rs)}", "REGOLE CONFERMATE"),
             (str(cnt(rs, "domanda")), "DOMANDE APERTE"), (str(len(store.load("cards"))), "CARTE NEL DATABASE")]
    body = ["<h1>COSA HO IMPARATO</h1>",
            f"<p class='sub'>Le novità di BIG-BOB partita per partita e registrazione per registrazione · aggiornato {store.now()}</p>",
            "<div class='tiles'>" + "".join(f"<div class='tile'><b>{v}</b><span>{k}</span></div>" for v, k in tiles) + "</div>",
            "<h2>Partita per partita</h2>",
            "".join(out_blocks) or "<div class='empty'>Ancora niente: gioca una partita (o studia una registrazione con "
                                   "/impara-regole) e qui vedrai cosa ha imparato.</div>"]
    live = [x for x in ls if x.get("stato") != "smentita"]
    if live:
        order = {"confermata": 0, "ipotesi": 1}
        rows = "".join(
            f"<tr><td class='st'>{lessons.STATI.get(x.get('stato'), '')} {html.escape(x['id'])}</td>"
            f"<td>{html.escape(x['lezione'])}</td><td>{html.escape(', '.join(x.get('carte') or []))}</td>"
            f"<td>{html.escape(lessons.TIPI.get(x.get('tipo'), x.get('tipo', '')))}</td><td>{x.get('volte', 0)}</td></tr>"
            for x in sorted(live, key=lambda x: (order.get(x.get("stato"), 2), -(x.get("volte") or 0))))
        body.append("<h2>Tutte le lezioni in uso</h2><table><thead><tr><th>Stato</th><th>Lezione</th><th>Carte</th>"
                    f"<th>Tipo</th><th>Viste</th></tr></thead><tbody>{rows}</tbody></table>")
    qs = [r for r in rs if r.get("stato") in ("domanda", "ipotesi")]
    if qs:
        body.append("<h2>Ancora da scoprire</h2><table><tbody>" + "".join(
            f"<tr><td class='st'>{rules.STATI.get(r['stato'], '')} {html.escape(r['id'])}</td><td>{html.escape(r['testo'])}</td></tr>"
            for r in qs) + "</tbody></table>")
    out = LOGS / "imparato.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page("BIG-BOB · cosa ho imparato", "".join(body)), encoding="utf-8")
    return out


# ---------------------------------------------------------------- laboratorio (creazione mazzo)

def lab_html(name: str = "") -> Path:
    p = deckproj.get(name)
    if p is None:
        raise ValueError("nessun progetto di mazzo")
    st = deckproj.status(p)
    cur = st["statistiche_versione_attuale"]
    e = html.escape
    conf = st.get("confronto") or {}
    tiles = [(f"v{st['versione_attuale']}", "VERSIONE ATTUALE"),
             (f"{cur['partite']}/{cur['partite_obiettivo']}", "PARTITE DI TEST"),
             (f"{cur['winrate']}%" if cur["winrate"] is not None else "–",
              f"WINRATE (±{cur['margine']})" if cur["margine"] else "WINRATE"),
             (str(st["partite_mancanti"]), "PARTITE MANCANTI"),
             (f"{conf['p_migliore']}%" if conf.get("p_migliore") is not None else "–",
              f"MIGLIORE DELLA v{conf['contro_versione']}" if conf else "CONFRONTO")]
    body = [f"<h1>LABORATORIO · {e(p['nome'].upper())}</h1>",
            f"<p class='sub'>{e(p.get('obiettivo') or 'Mazzo creato da BIG-BOB')} · creato {e(p['creato'])} · "
            f"{e(p.get('stato') or '')} · aggiornato {store.now()}</p>",
            "<div class='tiles'>" + "".join(f"<div class='tile'><b>{v}</b><span>{k}</span></div>" for v, k in tiles)
            + "</div>",
            f"<h2>A che punto siamo</h2><div class='note'>{e(st['consiglio'])}"
            + (f"\nMiglioria proposta: {e(deckproj.instructions(p['proposta']))} {e(p['proposta']['motivo'])}"
               if p.get("proposta") else "") + "</div>",
            "<h2>Mazzo attuale</h2><div class='deck'>"
            + f"<span class='lg'>★ {e(st['mazzo']['leggendaria'])}</span>"
            + "".join(f"<span>{e(c)} ×2</span>" for c in st["mazzo"]["carte"]) + "</div>"]

    body.append("<h2>Versioni</h2>")
    for i, v in enumerate(reversed(st["versioni"])):
        chg = ""
        if v["tolte"] or v["messe"]:
            chg = (" ".join(f"<span class='out'>− {e(x)}</span>" for x in v["tolte"]) + " "
                   + " ".join(f"<span class='in'>+ {e(x)}</span>" for x in v["messe"]))
        else:
            chg = "Versione iniziale"
        if v["partite"]:
            lo, hi = v["intervallo_95"]
            ci = (f"<div class='ci' title='winrate {v['winrate']}%, intervallo al 95% {lo}–{hi}%'>"
                  f"<div class='fifty'></div><div class='rng' style='left:{lo}%;width:{max(hi - lo, 1)}%'></div>"
                  f"<div class='pt' style='left:{v['winrate']}%'></div></div>"
                  f"<div class='cival'>{v['vinte']}V {v['perse']}S · {v['winrate']}% (95%: {lo}–{hi}%) · "
                  f"{v['partite']}/{v['partite_obiettivo']} partite</div>")
        else:
            ci = f"<div class='cival'>ancora nessuna partita · servono {v['partite_obiettivo']}</div>"
        body.append(f"<div class='ver{' cur' if i == 0 else ''}'><div class='vn'>v{v['v']}</div>"
                    f"<div><div class='chg'>{chg}</div><div class='why'>{e(v['motivo'] or '')}</div></div>"
                    f"<div>{ci}</div></div>")

    weak = st["punti_deboli"]
    body.append("<h2>Punti deboli della versione attuale</h2>" + (
        "<ul>" + "".join(f"<li>{e(w)}</li>" for w in weak) + "</ul>" if weak else
        "<div class='empty'>Nessun punto debole evidente dai numeri" + (" (ancora poche partite)" if cur["partite"] < 5
                                                                         else "") + ".</div>"))
    weak_cards = {w.split(":")[0] for w in weak}
    src, src_label = cur, "Carte nella versione attuale"
    if not cur["partite"]:  # versione appena nata: mostro i dati dell'ultima versione giocata
        prev_v = next((v for v in reversed(p["versioni"][:-1]) if deckproj.matches_of(p, v["v"])), None)
        if prev_v:
            src = deckproj.version_stats(p, prev_v)
            src_label = f"Carte nella v{prev_v['v']} (l'ultima con partite: la v{cur['v']} non ne ha ancora)"
    rows = []
    for c, s_ in sorted(src["carte"].items(), key=lambda kv: (not kv[1]["leggendaria"], kv[1]["costo"] or 0, kv[0])):
        fmt = lambda x, suf="": "–" if x is None else f"{x}{suf}"  # noqa: E731
        rows.append(f"<tr class='{'weak' if c in weak_cards else ''}'><td>{'★ ' if s_['leggendaria'] else ''}{e(c)}</td>"
                    f"<td>{fmt(s_['costo'])}</td><td>{s_['pescata']}</td><td>{s_['giocata']}</td>"
                    f"<td>{fmt(s_['winrate_giocata'], '%')}</td><td>{fmt(s_['winrate_non_giocata'], '%')}</td>"
                    f"<td>{fmt(s_['round_medio'])}</td></tr>")
    body.append(f"<h2>{e(src_label)}</h2><table><thead><tr><th>Carta</th><th>Costo</th><th>Pescata</th>"
                "<th>Giocata</th><th>Winrate se giocata</th><th>Winrate se non giocata</th><th>Round medio</th></tr>"
                f"</thead><tbody>{''.join(rows)}</tbody></table>")
    allm = deckproj.matches_of(p)
    by_opp: dict = defaultdict(lambda: [0, 0])
    for m in allm:
        by_opp[m.get("avv_leggendaria") or "?"][0] += str(m.get("risultato", "")).lower().startswith("v")
        by_opp[m.get("avv_leggendaria") or "?"][1] += 1
    body.append("<h2>Contro le leggendarie (tutte le versioni)</h2>" + _bars([(k, v[0], v[1]) for k, v in by_opp.items()]))
    if allm:
        rows = "".join(f"<tr><td>{e(str(m.get('fine', '')))}</td><td>v{m.get('versione')}</td>"
                       f"<td>{e(str(m.get('avv_leggendaria') or ''))}</td><td>{e(str(m.get('risultato', '')))}</td></tr>"
                       for m in reversed(allm[-40:]))
        body.append("<h2>Partite di test</h2><table><thead><tr><th>Data</th><th>Versione</th><th>Avversario</th>"
                    f"<th>Risultato</th></tr></thead><tbody>{rows}</tbody></table>")
    body.append("<p class='sub' style='margin-top:18px'>Con poche partite il winrate oscilla molto: la barra mostra "
                "l'intervallo in cui sta probabilmente il valore vero (95%). Per questo BIG-BOB guarda anche le carte, "
                "i matchup e le lezioni prima di cambiare il mazzo.</p>")
    out = LOGS / "laboratorio.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(f"BIG-BOB · laboratorio {p['nome']}", "".join(body)), encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "laboratorio":
        print(lab_html(sys.argv[2] if len(sys.argv) > 2 else ""))
    elif len(sys.argv) > 1 and sys.argv[1] == "imparato":
        print(learned_html())
    elif len(sys.argv) > 1 and sys.argv[1] == "replay":
        d = Path(sys.argv[2]) if len(sys.argv) > 2 else max((LOGS / "partite").glob("*/"), default=None)
        print(replay_html(Path(d)))
    else:
        print(stats_html())
    sys.stdout.flush()
