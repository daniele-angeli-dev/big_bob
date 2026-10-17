"""Cronologia delle partite per il libro (scheda PARTITE): l'elenco delle partite e, per ognuna, richiesta per
richiesta, la schermata inviata, la mossa suggerita da BIG-BOB e quello che è stato giocato davvero dopo.

Fonti:
- logs/partite/<AAAAMMGG-hhmmss>/diario.md: il diario scritto dalla finestra (richieste, schermate NN.png, risposte,
  fotogrammi dell'osservatore, lezioni, segnalazioni);
- data/matches_log.json: le partite chiuse con FINE (risultato, mazzi, carte, e da ottobre 2026 lo "storico" con la
  fotografia di ogni round salvata da update_match, da cui si ricavano le carte giocate tra una richiesta e l'altra).
"""
from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from origins import store

LOGS = store.ROOT / "logs"
MAX_PARTITE = 120


def journals_dir() -> Path:
    return LOGS / "partite"


# ============================================================================ diario

REQ_RE = re.compile(r"^## #(\d+) · (\d\d:\d\d:\d\d) · (.*?)(?: · schermata (\S+\.png))?\s*$")


def parse_journal(d: Path) -> dict | None:
    f = d / "diario.md"
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("# Partita"):
        return None  # richieste fatte senza NUOVA: non è una partita
    head, _, rest = text.partition("\n## ")
    mh = re.search(r"# Partita del (\d\d/\d\d/\d{4} \d\d:\d\d)", head)
    deck = re.search(r"^Mazzo:\s*(.+)$", head, re.M)
    mode = re.search(r"^Modalità:\s*([^·\n]+)", head, re.M)
    out = {"id": d.name, "dir": d, "inizio": None, "mazzo": deck.group(1).strip() if deck else "",
           "modalita": mode.group(1).strip() if mode else "", "richieste": [], "segnalazioni": [], "lezioni": []}
    if mh:
        try:
            out["inizio"] = datetime.strptime(mh.group(1), "%d/%m/%Y %H:%M")
        except ValueError:
            pass
    if not rest:
        return out
    blocks = re.split(r"\n(?=## #\d+ · |### )", "## " + rest)
    for b in blocks:
        b = b.strip()
        if b.startswith("## #"):
            first, _, body = b.partition("\n")
            m = REQ_RE.match(first)
            if not m:
                continue
            r = {"n": int(m.group(1)), "ora": m.group(2), "etichetta": m.group(3).strip(), "schermata": m.group(4),
                 "osservatore": [], "strumenti": "", "tempo": None, "risposta": ""}
            obs = re.search(r"^Osservatore: \d+ fotogrammi allegati \(([^)]*)\)", body, re.M)
            if obs:
                r["osservatore"] = [x.strip() for x in obs.group(1).split(",") if x.strip()]
            st = re.search(r"^Strumenti:\s*(.*)$", body, re.M)
            if st:
                r["strumenti"] = st.group(1).strip()
            tm = re.search(r"^Tempo totale:\s*([\d.]+)s", body, re.M)
            if tm:
                r["tempo"] = float(tm.group(1))
            ans = re.sub(r"^(Osservatore:.*|Strumenti:.*|Tempo totale:.*)$", "", body, flags=re.M).strip()
            r["risposta"] = ans
            out["richieste"].append(r)
        elif b.startswith("### 📚"):
            out["lezioni"].append(b.lstrip("# ").strip())
        elif b.startswith("### ❌"):
            out["segnalazioni"].append(b.lstrip("# ").strip())
    return out


def journals() -> list[dict]:
    root = journals_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir():
            j = parse_journal(d)
            if j:
                out.append(j)
        if len(out) >= MAX_PARTITE:
            break
    return out


def _start(m: dict) -> datetime | None:
    try:
        return datetime.strptime(str(m.get("inizio"))[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def link(matches: list[dict], js: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """Coppie (partita registrata, diario), dalla più recente. Il collegamento è il campo 'diario' della partita;
    per le partite più vecchie il diario iniziato poco prima di start_match con lo stesso mazzo."""
    by_id = {j["id"]: j for j in js}
    used: set[str] = set()
    pairs: list[tuple[dict | None, dict | None]] = []
    for m in reversed(matches[-MAX_PARTITE:]):
        j = by_id.get(m.get("diario") or "")
        if j is None:
            st = _start(m)
            best, bd = None, None
            for c in js:
                if c["id"] in used or c["inizio"] is None or st is None:
                    continue
                delta = (st - c["inizio"]).total_seconds()
                if not -90 <= delta <= 25 * 60:
                    continue
                score = abs(delta) - (600 if c["mazzo"] and store.slug(c["mazzo"]) == store.slug(m.get("mio_mazzo", "")) else 0)
                if bd is None or score < bd:
                    best, bd = c, score
            j = best
        if j is not None:
            used.add(j["id"])
        pairs.append((m, j))
    for j in js:  # partite iniziate con NUOVA ma mai chiuse con FINE
        if j["id"] not in used:
            pairs.append((None, j))
    key = lambda p: (p[1]["inizio"] if p[1] and p[1]["inizio"] else (_start(p[0]) if p[0] else None)) or datetime.min  # noqa: E731
    pairs.sort(key=key, reverse=True)
    return pairs[:MAX_PARTITE]


# ============================================================================ round per round

def _secs(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def _diff(after: list | None, before: list | None) -> list[str]:
    c = Counter(after or [])
    c.subtract(Counter(before or []))
    return [k for k, v in c.items() for _ in range(max(0, v))]


def suggestion(answer: str) -> dict:
    mossa = perche = ""
    for line in answer.splitlines():
        s = line.strip()
        if s.startswith("▶") and not mossa:
            mossa = s.lstrip("▶").strip()
            if " — " in mossa:
                mossa, perche = (x.strip() for x in mossa.split(" — ", 1))
        elif s.lower().startswith(("perché:", "perche:")) and mossa and not perche:
            perche = s.split(":", 1)[1].strip()
    return {"mossa": mossa, "perche": perche}


def rounds(m: dict | None, j: dict | None) -> list[dict]:
    """Per ogni richiesta del diario: suggerimento, carte giocate dopo (tu e avversario), barrier."""
    reqs = (j or {}).get("richieste") or []
    snaps = [s for s in (m or {}).get("storico") or [] if s.get("ora")]
    final = None
    if m:
        final = {k: m.get(k) for k in ("miei_giocati", "miei_scartati", "avv_giocati", "avv_scartati", "barrier_mie",
                                       "barrier_avv", "distrutte_da_me", "distrutte_a_me", "turno")}
    states = []
    for i, r in enumerate(reqs):
        t0 = _secs(r["ora"])
        t1 = _secs(reqs[i + 1]["ora"]) if i + 1 < len(reqs) else 10 ** 9
        mine = [s for s in snaps if t0 <= _secs(s["ora"]) < t1]
        states.append(mine[-1] if mine else None)
    my_cards = {store.slug(c): c for c in ((m or {}).get("carte_mie") or []) + [(m or {}).get("leggendaria_mia") or ""] if c}
    out = []
    for i, r in enumerate(reqs):
        sug = suggestion(r["risposta"])
        st = states[i]
        nxt = next((s for s in states[i + 1:] if s), None) or final
        row = {**r, **sug, "turno": (st or {}).get("turno"), "giocate": None, "avv_giocate": None, "seguito": None,
               "barrier": None}
        if st and nxt:
            row["giocate"] = _diff(nxt.get("miei_giocati"), st.get("miei_giocati")) + \
                _diff(nxt.get("miei_scartati"), st.get("miei_scartati"))
            row["avv_giocate"] = _diff((nxt.get("avv_giocati") or []) + (nxt.get("avv_scartati") or []),
                                       (st.get("avv_giocati") or []) + (st.get("avv_scartati") or []))
            row["barrier"] = {"mie": nxt.get("barrier_mie"), "avv": nxt.get("barrier_avv"),
                              "da_me": nxt.get("distrutte_da_me"), "a_me": nxt.get("distrutte_a_me")}
        if sug["mossa"] and row["giocate"] is not None:
            low = sug["mossa"].lower()
            wanted = {sid for sid, name in my_cards.items() if name.lower() in low}
            played = {store.slug(c) for c in row["giocate"]}
            if wanted:
                hit = len(wanted & played)
                row["seguito"] = "sì" if hit == len(wanted) else ("in parte" if hit else "no")
        out.append(row)
    return out


# ============================================================================ HTML

def _rel(j: dict, name: str, sub: str = "") -> str:
    return "/".join(x for x in ("partite", j["id"], sub, name) if x)


def _result(m: dict | None) -> tuple[str, str]:
    r = str((m or {}).get("risultato") or "").lower()
    if r.startswith("v"):
        return "V", "VITTORIA"
    if r.startswith("s"):
        return "S", "SCONFITTA"
    if r.startswith("p"):
        return "P", "PAREGGIO"
    return "–", "SENZA FINE"


def body(selected: str = "") -> str:
    e = html.escape
    pairs = link(store.load("matches"), journals())
    if not pairs:
        return ("<div class='empty' style='margin-top:14px'>Ancora nessuna partita. Premi NUOVA all'inizio di una partita e "
                "FINE alla fine: qui trovi la cronologia, con le schermate, le mosse suggerite e quelle giocate.</div>")
    tiles, details = [], []
    for m, j in pairs:
        pid = (j or {}).get("id") or store.slug(f"{(m or {}).get('inizio', '')}-{(m or {}).get('mio_mazzo', '')}")
        short, long = _result(m)
        when = (j["inizio"].strftime("%d/%m/%Y %H:%M") if j and j.get("inizio") else str((m or {}).get("inizio", ""))[:16])
        deck = (m or {}).get("mio_mazzo") or (j or {}).get("mazzo") or "?"
        opp = (m or {}).get("avv_leggendaria") or "avversario sconosciuto"
        typ = (m or {}).get("tipo_avversario")
        rs = rounds(m, j)
        n_live = sum(1 for r in rs if r["mossa"])
        follow = [r["seguito"] for r in rs if r["seguito"]]
        fol = f" · consigli seguiti {sum(1 for x in follow if x == 'sì')}/{len(follow)}" if follow else ""
        tiles.append(
            f"<button type='button' class='mtile r{short}' data-mid='{e(pid)}' "
            f"data-name='{e((deck + ' ' + opp + ' ' + (typ or '') + ' ' + when).lower())}' data-res='{short}'>"
            f"<span class='res'>{short}</span><span class='mi'><span class='nm'>{e(deck)} <i>vs</i> {e(opp)}"
            f"{(' · ' + e(typ)) if typ else ''}</span><span class='dt'>{e(when)} · {long}"
            f"{(' · round ' + str(m.get('turno'))) if m and m.get('turno') else ''} · {len(rs)} richieste{fol}</span></span></button>")
        details.append(_detail(pid, m, j, rs, when, deck, opp, typ, long))
    toolbar = ("<div class='toolbar'><label class='sr' for='mq'>Cerca</label>"
               "<input id='mq' type='search' placeholder='Cerca mazzo, leggendaria avversaria, data…'>"
               "<label class='sr' for='mr'>Risultato</label><select id='mr'><option value=''>Tutti i risultati</option>"
               "<option value='V'>Vittorie</option><option value='S'>Sconfitte</option><option value='P'>Pareggi</option>"
               "<option value='–'>Senza FINE</option></select></div>")
    return (f"<div id='mlist'>{toolbar}<div class='mgrid' id='mgrid'>{''.join(tiles)}</div></div>"
            + "".join(details) + "<div class='lightbox' id='lbox' hidden><img alt='Schermata ingrandita'></div>")


def _cards(lst) -> str:
    return ", ".join(html.escape(c) for c in lst) if lst else "niente"


def _detail(pid, m, j, rs, when, deck, opp, typ, long) -> str:
    e = html.escape
    parts = [f"<section class='matchd' id='m-{e(pid)}' hidden><button type='button' class='back' data-mback>← TUTTE LE PARTITE</button>",
             f"<h2 class='mh'>{e(deck)} <i>vs</i> {e(opp)}</h2>",
             f"<p class='sub'>{e(when)} · <b>{long}</b>{(' · avversario ' + e(typ)) if typ else ''}"
             f"{(' · lista stimata ' + e(m['mazzo_avversario_stimato'])) if m and m.get('mazzo_avversario_stimato') else ''}"
             f"{(' · modalità ' + e(j['modalita'])) if j and j.get('modalita') else ''}</p>"]
    if m and m.get("note_finali"):
        parts.append(f"<div class='note'>{e(m['note_finali'])}</div>")
    parts.append("<div class='askall'>" + _ask_box(pid, 0, "Chiedi qualcosa su tutta la partita: dove l'ho persa? "
                                                           "Cosa dovevo fare diversamente?") + "</div>")
    if not j:
        parts.append("<div class='empty'>Il diario di questa partita non c'è più (o è stata giocata prima della "
                     "cronologia): restano solo risultato e carte.</div>")
    if m and not m.get("storico") and j:
        parts.append("<div class='note'>Partita registrata prima della cronologia delle giocate: si vedono schermate e "
                     "suggerimenti, ma non le carte giocate round per round.</div>")
    for r in rs:
        shot = (f"<button type='button' class='shot' data-shot='{e(_rel(j, r['schermata']))}' "
                f"aria-label='Ingrandisci la schermata della richiesta {r['n']}'><span>schermata</span></button>"
                if j and r.get("schermata") else "<div class='noshot'>nessuna schermata</div>")
        obs = ""
        if j and r["osservatore"]:
            obs = ("<div class='obs'>" + "".join(
                f"<button type='button' class='shot mini' data-shot='{e(_rel(j, f, 'osservatore'))}' "
                f"aria-label='Fotogramma dell osservatore {e(f)}'><span></span></button>" for f in r["osservatore"][:6])
                + "</div>")
        head = f"#{r['n']} · {e(r['ora'])} · {e(r['etichetta'])}" + (f" · round {r['turno']}" if r.get("turno") is not None else "") \
            + (f" · risposta in {r['tempo']:.0f} s" if r.get("tempo") else "")
        info = [f"<div class='meta'>{head}</div>"]
        if r["mossa"]:
            info.append(f"<div class='sug'><span class='k'>SUGGERITA</span><b>▶ {e(r['mossa'])}</b>"
                        + (f"<div class='why'>{e(r['perche'])}</div>" if r["perche"] else "") + "</div>")
        if r["giocate"] is not None:
            badge = {"sì": "<span class='bd ok'>CONSIGLIO SEGUITO</span>",
                     "in parte": "<span class='bd up'>SEGUITO IN PARTE</span>",
                     "no": "<span class='bd ko'>GIOCATA DIVERSA</span>"}.get(r["seguito"] or "", "")
            info.append(f"<div class='play'><span class='k'>GIOCATA</span>{_cards(r['giocate'])} {badge}</div>")
            info.append(f"<div class='play opp'><span class='k'>AVVERSARIO</span>{_cards(r['avv_giocate'])}</div>")
            b = r.get("barrier") or {}
            if b.get("mie") or b.get("avv"):
                info.append(f"<div class='meta'>Dopo: barrier tue {e(str(b.get('mie') or '–'))} · avversarie "
                            f"{e(str(b.get('avv') or '–'))} · distrutte {b.get('da_me') or 0}-{b.get('a_me') or 0}</div>")
        if r["risposta"]:
            label = "Risposta completa" if r["mossa"] else "Risposta"
            info.append(f"<details{' open' if not r['mossa'] else ''}><summary>{label}</summary>"
                        f"<pre>{e(r['risposta'])}</pre></details>")
        info.append(_ask_box(pid, r["n"], "Perché questa mossa? Cosa sarebbe successo con un'altra?"))
        parts.append(f"<article class='rq'><div class='rq-img'>{shot}{obs}</div><div class='rq-txt'>{''.join(info)}</div></article>")
    for x in (j or {}).get("segnalazioni", []):
        parts.append(f"<div class='flag'>{e(x)}</div>")
    for x in (j or {}).get("lezioni", []):
        parts.append(f"<div class='learn'>{e(x)}</div>")
    parts.append("</section>")
    return "".join(parts)


def _ask_box(pid: str, n: int, placeholder: str) -> str:
    e = html.escape
    return (f"<form class='ask' data-mid='{e(pid)}' data-n='{n}'><label class='sr' for='q-{e(pid)}-{n}'>Domanda</label>"
            f"<input id='q-{e(pid)}-{n}' type='text' autocomplete='off' placeholder=\"{e(placeholder)}\">"
            "<button type='submit'>CHIEDI</button><div class='ans' aria-live='polite'></div></form>")


CSS = """
.mgrid{display:flex;flex-direction:column;gap:8px}
.mtile{display:flex;gap:12px;align-items:center;text-align:left;background:var(--panel);border:2px solid transparent;border-radius:10px;
  padding:10px 12px;color:#fff;font:inherit;cursor:pointer}
.mtile:hover{border-color:var(--teal)}.mtile:focus-visible,.shot:focus-visible{outline:3px solid var(--teal);outline-offset:2px}
.mtile .res{flex:0 0 40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-family:Impact,sans-serif;font-size:24px;background:var(--bg);color:var(--dim)}
.mtile.rV .res{background:var(--teal);color:var(--bg)}.mtile.rS .res{background:#5A1630;color:#FFB3C1}
.mtile .mi{display:flex;flex-direction:column;gap:3px;min-width:0}
.mtile .nm{font-size:16px;font-weight:700}.mtile i,.mh i{font-style:normal;color:var(--dim);font-weight:400}
.mtile .dt{font-size:13px;color:var(--dim)}
.matchd[hidden],#mlist[hidden],.lightbox[hidden]{display:none}
.mh{font-size:24px!important;letter-spacing:1px;color:var(--yellow)!important;text-transform:none!important;margin:6px 0 4px!important}
.rq{background:var(--panel);border-radius:10px;padding:12px;margin-bottom:10px;display:grid;
  grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:14px}
.shot{display:block;width:100%;padding:0;border:0;background:var(--bg);border-radius:6px;cursor:zoom-in;min-height:120px;
  background-size:cover;background-position:center;position:relative;aspect-ratio:16/9}
.shot span{position:absolute;inset:auto 6px 6px auto;font-size:11px;color:var(--dim)}
.shot.loaded span{display:none}.shot img{width:100%;height:100%;object-fit:contain;border-radius:6px;display:block}
.obs{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-top:6px}
.shot.mini{min-height:0;aspect-ratio:16/9}
.noshot{color:var(--dim);font-size:13px;background:var(--bg);border-radius:6px;padding:20px;text-align:center}
.sug,.play{font-size:14px;margin:6px 0;line-height:1.4}.sug b{font-size:15px}
.k{display:inline-block;font-size:11px;letter-spacing:1px;font-weight:700;color:var(--bg);background:var(--yellow);
  border-radius:4px;padding:1px 6px;margin-right:8px}
.play .k{background:var(--teal)}.play.opp .k{background:var(--orange)}
.sug .why{color:var(--dim);font-size:13px;margin-top:2px}
.rq details{margin-top:6px}.rq summary{cursor:pointer;color:var(--dim);font-size:13px}
.rq pre{white-space:pre-wrap;font-family:inherit;margin:6px 0 0;font-size:13px;line-height:1.4}
.lightbox{position:fixed;inset:0;background:rgba(10,4,30,.92);display:flex;align-items:center;justify-content:center;z-index:9;
  cursor:zoom-out;padding:20px}
.lightbox img{max-width:100%;max-height:100%;border-radius:8px}
.ask{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.ask input{flex:1 1 200px;min-width:0;background:var(--bg);border:2px solid var(--line);color:#fff;border-radius:8px;
  padding:7px 10px;font:inherit;font-size:14px}
.ask input:focus{outline:none;border-color:var(--teal)}
.ask button{background:var(--teal);color:var(--bg);border:0;border-radius:8px;padding:7px 14px;font:inherit;font-weight:700;
  letter-spacing:1px;cursor:pointer}.ask button:disabled{opacity:.5;cursor:wait}
.ans{flex-basis:100%;display:flex;flex-direction:column;gap:6px}
.ans .qa{background:var(--bg);border-left:4px solid var(--teal);border-radius:6px;padding:8px 10px;font-size:14px;line-height:1.45;white-space:pre-wrap}
.ans .qq{color:var(--dim);font-size:13px}.ans .wait{color:var(--dim);font-size:13px;font-style:italic}
.askall{background:var(--panel);border-radius:10px;padding:10px 12px;margin-bottom:12px}
@media (max-width:720px){.rq{grid-template-columns:1fr}}
"""

JS = """
(function(){
  var mlist = document.getElementById('mlist'); if (!mlist) return;
  var api = function(){ return window.pywebview && window.pywebview.api; };
  function load(btn, big){
    if (btn.dataset.loaded && !big) return Promise.resolve(btn.dataset.loaded);
    var a = api();
    var p = (a && a.history_image) ? a.history_image(btn.dataset.shot, big ? 1600 : 520) : Promise.resolve(btn.dataset.shot);
    return p.then(function(src){
      if (!src) return null;
      if (!big){ btn.dataset.loaded = src; var im = document.createElement('img'); im.alt = ''; im.src = src;
        btn.appendChild(im); btn.classList.add('loaded'); }
      return src; });
  }
  function listView(){ mlist.hidden = false; Array.prototype.forEach.call(document.querySelectorAll('.matchd'), function(x){ x.hidden = true; }); }
  window.openMatch = function(id){
    var sec = document.getElementById('m-' + id); if (!sec) return;
    mlist.hidden = true;
    Array.prototype.forEach.call(document.querySelectorAll('.matchd'), function(x){ x.hidden = x !== sec; });
    Array.prototype.forEach.call(sec.querySelectorAll('.shot'), function(b){ load(b, false); });
    window.scrollTo(0, 0);
  };
  Array.prototype.forEach.call(document.querySelectorAll('.mtile'), function(t){ t.addEventListener('click', function(){ window.openMatch(t.dataset.mid); }); });
  Array.prototype.forEach.call(document.querySelectorAll('[data-mback]'), function(b){ b.addEventListener('click', function(){ listView(); window.scrollTo(0, 0); }); });
  var lbox = document.getElementById('lbox');
  Array.prototype.forEach.call(document.querySelectorAll('.shot'), function(b){
    b.addEventListener('click', function(){ load(b, true).then(function(src){ if (!src) return;
      lbox.querySelector('img').src = src; lbox.hidden = false; }); }); });
  lbox.addEventListener('click', function(){ lbox.hidden = true; });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && !lbox.hidden) lbox.hidden = true; });
  var q = document.getElementById('mq'), r = document.getElementById('mr'), grid = document.getElementById('mgrid');
  function filter(){
    var v = q.value.trim().toLowerCase(), rv = r.value;
    Array.prototype.forEach.call(grid.children, function(t){
      t.hidden = !((!v || t.dataset.name.indexOf(v) >= 0) && (!rv || t.dataset.res === rv)); });
  }
  q.addEventListener('input', filter); r.addEventListener('change', filter);
  Array.prototype.forEach.call(document.querySelectorAll('form.ask'), function(f){
    f.addEventListener('submit', function(ev){
      ev.preventDefault();
      var inp = f.querySelector('input'), btn = f.querySelector('button'), out = f.querySelector('.ans');
      var q = inp.value.trim() || inp.placeholder, a = api();
      if (!a || !a.history_ask){ out.textContent = 'Apri questa pagina da BIG-BOB (icona del libro) per fare domande.'; return; }
      var box = document.createElement('div'); box.className = 'qa';
      var qq = document.createElement('div'); qq.className = 'qq'; qq.textContent = 'Tu: ' + q; box.appendChild(qq);
      var w = document.createElement('div'); w.className = 'wait'; w.textContent = 'BIG-BOB ci pensa…'; box.appendChild(w);
      out.appendChild(box); btn.disabled = true; inp.value = '';
      a.history_ask(f.dataset.mid, parseInt(f.dataset.n, 10), q).then(function(r){
        w.className = ''; w.textContent = r || 'Nessuna risposta.'; }, function(err){
        w.textContent = 'Non sono riuscito a rispondere: ' + (err && err.message || err); }).then(function(){ btn.disabled = false; inp.focus(); });
    });
  });
  var mid = document.body.dataset.match; if (mid) window.openMatch(mid);
})();
"""


def image_data(rel: str, size: int = 520) -> str | None:
    """Una schermata del diario come data URI JPEG (la finestra di BIG-BOB non legge i file)."""
    import base64
    import io
    root = journals_dir().resolve()
    p = (LOGS / rel).resolve()
    if root not in p.parents or not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        return None
    try:
        from PIL import Image
        im = Image.open(p).convert("RGB")
        im.thumbnail((max(200, min(int(size), 2000)),) * 2)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72, optimize=True)
        data = buf.getvalue()
    except Exception:  # noqa: BLE001
        data = p.read_bytes()
        return f"data:image/{'png' if p.suffix.lower() == '.png' else 'jpeg'};base64,{base64.b64encode(data).decode()}"
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def find(pid: str) -> tuple[dict | None, dict | None]:
    for m, j in link(store.load("matches"), journals()):
        if (j or {}).get("id") == pid or (not j and store.slug(f"{(m or {}).get('inizio', '')}-{(m or {}).get('mio_mazzo', '')}") == pid):
            return m, j
    return None, None


def question_context(pid: str, n: int) -> tuple[str, Path | None]:
    """Il contesto da dare a Claude per una domanda su una richiesta (n) o sull'intera partita (n = 0)."""
    m, j = find(pid)
    if m is None and j is None:
        raise ValueError("partita non trovata")
    rs = rounds(m, j)
    short, long = _result(m)
    lines = [f"Partita del {(j or {}).get('inizio') or (m or {}).get('inizio')}: mazzo {(m or {}).get('mio_mazzo') or (j or {}).get('mazzo')} "
             f"contro {(m or {}).get('avv_leggendaria') or '?'}"
             f"{(' (' + m['tipo_avversario'] + ')') if m and m.get('tipo_avversario') else ''}, risultato {long}."]
    if m:
        lines.append(f"Le mie 13 carte: {', '.join([m.get('leggendaria_mia') or ''] + list(dict.fromkeys(m.get('carte_mie') or [])))}")
        seen = list(dict.fromkeys((m.get("avv_giocati") or []) + (m.get("avv_scartati") or [])))
        lines.append(f"Carte avversarie viste in tutta la partita: {', '.join(seen) or 'nessuna'}")
    lines.append("\nCronologia (richiesta · round · mossa suggerita → cosa è stato giocato dopo):")
    for r in rs:
        lines.append(f"#{r['n']} {r['ora']} round {r.get('turno', '?')}: suggerita «{r['mossa'] or '—'}»"
                     f"{(' perché: ' + r['perche']) if r['perche'] else ''} → giocato: "
                     f"{', '.join(r['giocate']) if r['giocate'] is not None else 'non registrato'}; avversario: "
                     f"{', '.join(r['avv_giocate']) if r['avv_giocate'] is not None else 'non registrato'}"
                     f"{(' · barrier dopo: tue ' + str(r['barrier']['mie']) + ' avversarie ' + str(r['barrier']['avv'])) if r.get('barrier') else ''}")
    shot = None
    if n:
        r = next((x for x in rs if x["n"] == n), None)
        if r is None:
            raise ValueError("richiesta non trovata")
        lines.append(f"\nLA DOMANDA RIGUARDA LA RICHIESTA #{n} (round {r.get('turno', '?')}). La tua risposta di allora, "
                     f"completa:\n{r['risposta']}")
        if j and r.get("schermata") and (j["dir"] / r["schermata"]).exists():
            shot = j["dir"] / r["schermata"]
    return "\n".join(lines), shot


def latest_id() -> str:
    js = journals()
    return js[0]["id"] if js else ""

