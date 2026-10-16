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

from origins import lessons, store

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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        d = Path(sys.argv[2]) if len(sys.argv) > 2 else max((LOGS / "partite").glob("*/"), default=None)
        print(replay_html(Path(d)))
    else:
        print(stats_html())
    sys.stdout.flush()
