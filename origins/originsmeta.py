"""Meta della community da OriginsMeta (https://originsmeta.com): mazzi pubblicati, mazzi da torneo,
statistiche delle partite (winrate per leggendaria, archetipo, carta, matchup) e valori delle carte.

Gira sul PC di Daniele (dentro BIG-BOB), senza Claude e senza consumare il suo abbonamento:
- scarica solo pagine pubbliche ammesse dal robots.txt del sito, una al secondo, identificandosi come BIG-BOB;
- riscarica un mazzo solo se è nuovo, se la sua scheda nell'elenco è cambiata o se è vecchio di 3 giorni;
- non dipende dalla grafica del sito: riconosce le carte dai link /cards/<slug> e dalle immagini /cards/sm/<slug>,
  i campi (winrate, partite, versione, archetipo…) dal testo vicino, e legge le tabelle delle statistiche così
  come sono.

python -m origins.originsmeta            sincronizza (se l'ultima è di più di 12 ore fa)
python -m origins.originsmeta --forza    sincronizza adesso
python -m origins.originsmeta --salva-pagine   salva anche l'HTML in logs/originsmeta/ (per correggere il parser)
"""
from __future__ import annotations

import gzip
import hashlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from origins import store  # noqa: E402
else:
    from . import store

BASE = "https://originsmeta.com"
LANG = "en"
USER_AGENT = "BIG-BOB/1.0 (assistente personale per Origins TCG; uso privato, 1 richiesta al secondo)"
DELAY = 1.1               # secondi tra una richiesta e l'altra
REFETCH_DAYS = 3          # un mazzo invariato si riscarica comunque dopo 3 giorni
SYNC_EVERY_HOURS = 12
FONTE = "originsmeta"

PAGES = {
    "carte": f"/{LANG}/cards",
    "location": f"/{LANG}/locations",
    "mazzi": f"/{LANG}/decks",
    "tornei": f"/{LANG}/decks/tournament",
    "statistiche": f"/{LANG}/analytics",
    "piu_giocati": f"/{LANG}/tier-list/most-played",
}
ARCHETIPI = ["Swarm / go wide", "Big / big bodies", "Evil / big bodies", "Midrange", "Aggro", "Combo", "Control",
             "Discard", "Swarm", "Big", "Tempo", "Ramp"]

DECK_RE = re.compile(r"^(?:https?://(?:www\.)?originsmeta\.com)?/[a-z]{2}/decks/(community|tournament)/([a-z0-9][a-z0-9-]*)/?(?:[?#].*)?$")
CARD_HREF_RE = re.compile(r"^(?:https?://(?:www\.)?originsmeta\.com)?/[a-z]{2}/cards/([a-z0-9][a-z0-9-]*)/?(?:[?#].*)?$")
CARD_IMG_RE = re.compile(r"/cards/(?:[a-z0-9_-]+/)?([a-z0-9][a-z0-9-]*)\.(?:webp|png|jpe?g|avif)", re.I)
USER_RE = re.compile(r"^(?:https?://(?:www\.)?originsmeta\.com)?/[a-z]{2}/u/([^/?#]+)/?$")

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
        "wbr"}
BLOCK = {"p", "div", "section", "article", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
         "header", "footer", "nav", "main", "aside", "br", "dd", "dt", "dl", "figure", "figcaption", "blockquote",
         "thead", "tbody", "details", "summary", "form", "label", "button"}
SKIP = {"script", "style", "noscript", "template", "svg"}


# ======================================================================= mini DOM

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent: "Node | None"):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def text(self, sep_blocks: bool = True) -> str:
        out: list[str] = []

        def walk(n: Node):
            for c in n.children:
                if isinstance(c, str):
                    out.append(c)
                elif c.tag in SKIP:
                    continue
                elif c.tag == "img":
                    alt = c.attrs.get("alt") or ""
                    if alt and not out[-1:] == [alt]:
                        out.append(" ")
                elif sep_blocks and c.tag in BLOCK:
                    out.append("\n")
                    walk(c)
                    out.append("\n")
                elif c.tag in ("td", "th"):
                    out.append(" | ")
                    walk(c)
                else:  # elementi in linea affiancati (<span>8</span><span>4/4</span>) non vanno incollati
                    out.append(" ")
                    walk(c)
                    out.append(" ")
        walk(self)
        raw = "".join(out).replace("\xa0", " ")
        lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip(" |") for ln in raw.split("\n")]
        return "\n".join(ln for ln in lines if ln)

    def tokens(self) -> list[str]:
        """I pezzi di testo dell'elemento, uno per nodo di testo."""
        out: list[str] = []

        def walk(n: Node):
            for c in n.children:
                if isinstance(c, str):
                    t = re.sub(r"\s+", " ", c.replace("\xa0", " ")).strip()
                    if t:
                        out.append(t)
                elif c.tag not in SKIP:
                    walk(c)
        walk(self)
        return out

    def inline(self) -> str:
        return re.sub(r"\s+", " ", self.text(sep_blocks=False)).strip()

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag in ("script",):
            self._in_script = True
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if self._in_script:
            self.scripts.append(data)
        self.cur.children.append(data)


def parse_html(html: str) -> tuple[Node, list[str]]:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root, b.scripts


# ======================================================================= utilità

def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace("−", "-").replace("%", "").replace("+", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
        s = s.replace(",", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    v = _num(s)
    return int(v) if v is not None else None


def img_src(n: Node) -> str:
    src = n.attrs.get("src") or n.attrs.get("data-src") or ""
    if not src and n.attrs.get("srcset"):
        src = n.attrs["srcset"].split(",")[0].split()[0]
    if "/_next/image" in src and "url=" in src:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)
        src = q.get("url", [src])[0]
    return urllib.parse.unquote(src)


def card_ref(n: Node) -> str | None:
    """Slug della carta a cui rimanda un link o un'immagine, se è una carta."""
    if n.tag == "a":
        m = CARD_HREF_RE.match(n.attrs.get("href", ""))
        return m.group(1) if m else None
    if n.tag in ("img", "source"):
        m = CARD_IMG_RE.search(img_src(n))
        return m.group(1).lower() if m else None
    return None


def deck_href(n: Node) -> tuple[str, str] | None:
    if n.tag != "a":
        return None
    m = DECK_RE.match(n.attrs.get("href", ""))
    return (m.group(1), m.group(2)) if m else None


def deck_url(kind: str, slug: str) -> str:
    return f"{BASE}/{LANG}/decks/{kind}/{slug}"


def title_from_slug(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split("-"))


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


# ======================================================================= campi dal testo

def parse_fields(text: str) -> dict:
    """Winrate, partite, valutazione, versione, archetipo, data: dal testo di una scheda o di una pagina."""
    out: dict = {}
    t = text
    m = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*[·•|/-]\s*(\d+)\b", t)
    if m:
        out["winrate"], out["partite"] = _num(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(?:win\s*rate|winrate|WR)\D{0,25}?(\d{1,3}(?:[.,]\d+)?)\s*%", t, re.I) or \
            re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:win\s*rate|winrate|WR)", t, re.I)
        if m:
            out["winrate"] = _num(m.group(1))
        g = re.search(r"(\d+)\s+(?:recorded\s+|tracked\s+)?(?:games|partite|matches)\b", t, re.I)
        if g:
            out["partite"] = int(g.group(1))
    rec = re.search(r"\b(\d+)\s*[–-]\s*(\d+)\b\s*\(?\s*(\d+)?\s*(?:games|partite)?", t)
    if rec and "partite" not in out and re.search(r"record|W\s*[–-]\s*L", t, re.I):
        out["vinte"], out["perse"] = int(rec.group(1)), int(rec.group(2))
        out["partite"] = out["vinte"] + out["perse"]
    m = re.search(r"★\s*(\d(?:[.,]\d)?)\s*\(\s*(\d+)\s*\)", t)
    if m:
        out["rating"], out["voti"] = _num(m.group(1)), int(m.group(2))
    m = re.search(r"\bDemo\b(?:\s*[·•-]\s*\d{1,2}\s+[A-Z][a-z]{2,8})?", t)
    v = re.search(r"(?:patch|version|versione|game version|v\.?)\s*(\d+\.\d+(?:\.\d+)?)", t, re.I) or \
        re.search(r"(?<![★\d.])\b(0\.\d+(?:\.\d+)?)\b(?!\s*%)", t)
    if v:
        out["versione"] = v.group(1)
    elif m:
        out["versione"] = re.sub(r"\s+", " ", m.group(0))
    for a in ARCHETIPI:  # prima il nome del tag scritto come nel sito (maiuscola), poi qualunque forma
        if re.search(r"(?<![\w/])" + re.escape(a) + r"(?![\w/])", t):
            out["archetipo"] = a
            break
    else:
        for a in ARCHETIPI:
            if re.search(r"\b" + re.escape(a) + r"\b", t, re.I):
                out["archetipo"] = a
                break
    m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", t)
    if m:
        out["data"] = m.group(1)
    else:
        m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                      r"\s+(\d{1,2}),?\s+(20\d\d)\b", t)
        if m:
            mon = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                   "November", "December"].index(m.group(1)) + 1
            out["data"] = f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return out


# ======================================================================= carte del sito

def parse_cards_page(html: str) -> dict[str, dict]:
    """{slug: {nome, tipo, costo, attacco, vita, leggendaria}} dalla pagina /cards."""
    root, _ = parse_html(html)
    links = [n for n in root.iter() if n.tag == "a" and CARD_HREF_RE.match(n.attrs.get("href", ""))]
    out: dict[str, dict] = {}
    for a in links:
        slug = CARD_HREF_RE.match(a.attrs["href"]).group(1)
        box = _own_box(a, lambda n: CARD_HREF_RE.match(n.attrs.get("href", "")) if n.tag == "a" else None,
                       key=lambda m: m.group(1), mine=slug)
        txt = box.inline()
        name = ""
        for im in a.iter():
            if im.tag == "img" and im.attrs.get("alt"):
                name = im.attrs["alt"].strip()
                break
        if not name:
            for h in box.iter():
                if h.tag in ("h2", "h3", "h4", "strong", "b") and h.inline():
                    name = h.inline()
                    break
        name = re.sub(r"^\s*★\s*|\s*\((?:Legendary|Leggendaria)\)\s*$", "", name or title_from_slug(slug)).strip()
        e = out.setdefault(slug, {"slug": slug, "nome": name})
        if "★" in txt or re.search(r"\bLegendary\b|\bLeggendaria\b", txt):
            e["leggendaria"] = True
        m = re.search(r"(?:Mana|Cost|Costo)\s*(\d+)", txt, re.I)
        if m:
            e["costo"] = int(m.group(1))
        m = re.search(r"(?<![\d/.,])(\d+)\s*/\s*(\d+)(?![\d/.,])", _strip_votes(txt))
        if m:
            e["attacco"], e["vita"] = int(m.group(1)), int(m.group(2))
        if re.search(r"Created card|Token|Carta creata", txt, re.I):
            e["tipo"] = "creata"
        elif re.search(r"\bSpell\b|\bMagia\b", txt):
            e["tipo"] = "spell"
        elif re.search(r"\bUnit\b|\bCreatura\b", txt):
            e["tipo"] = "creatura"
        rest = _card_text(box.tokens(), name)
        if rest:
            e["testo"] = rest
    return out


def _strip_votes(t: str) -> str:
    return re.sub(r"[\d.,]+\s*/\s*10\b(?:\s*[·•]\s*\d+\s*votes?)?", " ", t)


_NOT_TEXT = [r"★?\s*(?:Legendary|Leggendaria)?\s*", r"(?:Mana|Cost|Costo)?\s*\d+", r"\d+\s*(?:Power|Health)",
             r"\d+\s*Power,?\s*\d+\s*Health", r"\d+\s*/\s*\d+", r"[\d.,]+\s*/\s*10(?:\s*[·•]\s*\d+\s*votes?)?",
             r"[·•]?\s*\d+\s*votes?", r"\(?(?:Legendary|Leggendaria)\)?",
             r"(?:Created card|Unit|Spell|Legendary|Evil|Good|Neutral|Mana|Power|Health|Cost)"]


def _card_text(tokens: list[str], name: str) -> str:
    """Il testo della carta: i pezzi di testo che non sono nome, mana, statistiche, tipo o voti."""
    keep = []
    nm = (name or "").lower()
    for t in tokens:
        tt = t.replace("★", "").strip()
        base = re.sub(r"\s*\((?:Legendary|Leggendaria)\)\s*$", "", tt).strip().lower()
        if not tt or base == nm:
            continue
        if any(re.fullmatch(p, tt, re.I) for p in _NOT_TEXT):
            continue
        keep.append(tt)
    text = re.sub(r"\s+", " ", " ".join(keep)).strip(" ·•|-")
    return text if len(text) >= 6 else ""


def _own_box(node: Node, matcher, key, mine) -> Node:
    """Il contenitore più grande che contiene questo elemento e nessun altro elemento dello stesso tipo."""
    box = node
    for anc in node.ancestors():
        if anc.tag in ("#root", "body", "html", "main"):
            break
        others = False
        for n in anc.iter():
            m = matcher(n)
            if m and key(m) != mine:
                others = True
                break
        if others:
            break
        box = anc
    return box


# ======================================================================= location

def parse_locations_page(html: str) -> dict[str, dict]:
    """{slug: {nome, testo}}: ogni location è un titolo seguito dalla sua regola."""
    root, _ = parse_html(html)
    body = next((n for n in root.iter() if n.tag == "main"), None) or root
    lines = body.text().split("\n")
    heads = {n.inline() for n in body.iter() if n.tag in ("h2", "h3", "h4") and n.inline()}
    out: dict[str, dict] = {}
    for i, ln in enumerate(lines):
        if ln not in heads or len(ln) > 45:
            continue
        for nxt in lines[i + 1:i + 4]:
            if nxt in heads:
                break
            if len(nxt) >= 12 and " " in nxt and nxt.rstrip().endswith((".", "!", ")")):
                name = ln.strip().strip("“”")
                out[store.slug(name)] = {"nome": name, "testo": nxt.strip()}
                break
    return out


# ======================================================================= elenco dei mazzi

def parse_deck_list(html: str) -> dict:
    """Mazzi elencati in /decks o /decks/tournament: {url: {campi della scheda}} + totale dichiarato."""
    root, _ = parse_html(html)
    matcher = deck_href
    seen: dict[str, dict] = {}
    for a in root.iter():
        d = deck_href(a)
        if not d:
            continue
        url = deck_url(*d)
        if url in seen:
            continue
        box = _own_box(a, matcher, key=lambda m: m, mine=d)
        txt = box.text()
        name = ""
        for h in box.iter():
            if h.tag in ("h2", "h3", "h4") and h.inline():
                name = h.inline()
                break
        if not name:
            name = a.inline() or title_from_slug(re.sub(r"-[0-9a-f]{4}$", "", d[1]))
        entry = {"url": url, "tipo": "torneo" if d[0] == "tournament" else "community", "nome": name,
                 "hash_scheda": _hash(txt), **parse_fields(txt)}
        for u in box.iter():
            if u.tag == "a":
                m = USER_RE.match(u.attrs.get("href", ""))
                if m:
                    entry["autore"] = u.inline() or m.group(1)
                    entry["autore_url"] = m.group(1)
                    break
        refs = [r for r in (card_ref(n) for n in box.iter()) if r]
        if refs:
            entry["carte_scheda"] = list(dict.fromkeys(refs))
        desc = [ln for ln in txt.split("\n") if len(ln) > 30 and ln != name]
        if desc:
            entry["descrizione_breve"] = desc[0][:300]
        seen[url] = entry
    m = re.search(r"(\d+)\s+(?:results|risultati|decks|mazzi)\b", root.text(), re.I)
    return {"mazzi": seen, "totale_dichiarato": int(m.group(1)) if m else None}


def parse_user_page(html: str) -> list[str]:
    root, _ = parse_html(html)
    return list(dict.fromkeys(deck_url(*d) for d in (deck_href(a) for a in root.iter()) if d))


# ======================================================================= pagina di un mazzo

def split_decks(refs: list[str], is_legendary) -> list[dict]:
    """Divide la sequenza di carte di una pagina in mazzi: leggendaria + 12 carte normali.

    Le carte prima della prima leggendaria vengono assegnate a quella (alcune pagine mostrano la leggendaria
    dopo la lista). I mazzi incompleti si tengono solo se non ce n'è nessuno completo."""
    seq = [r for i, r in enumerate(refs) if i == 0 or r != refs[i - 1]]
    decks: list[dict] = []
    cur: dict | None = None
    pending: list[str] = []
    for r in seq:
        if is_legendary(r):
            if cur and cur["leggendaria"] == r:
                continue
            if cur is None and pending:
                cur = {"leggendaria": r, "carte": list(dict.fromkeys(pending))[:12]}
                pending = []
                if len(cur["carte"]) >= 12:
                    decks.append(cur)
                    cur = None
                continue
            if cur and len(cur["carte"]) == 0:
                cur["leggendaria"] = r
                continue
            cur = {"leggendaria": r, "carte": []}
            decks.append(cur)
        else:
            if cur is None:
                pending.append(r)
            elif len(cur["carte"]) < 12 and r not in cur["carte"]:
                cur["carte"].append(r)
    if cur is not None and cur not in decks:
        decks.append(cur)
    complete = [d for d in decks if len(d["carte"]) == 12]
    if complete:
        return complete
    if not decks and len(set(pending)) >= 1:
        return [{"leggendaria": None, "carte": list(dict.fromkeys(pending))[:12]}]
    return sorted(decks, key=lambda d: -len(d["carte"]))[:1]


def text_refs(text: str, names_index: dict[str, str]) -> list[str]:
    """Slug delle carte nominate nel testo, in ordine (i nomi più lunghi vincono: «Three Blind Mice» non è «Mouse»)."""
    taken: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for name in sorted(names_index, key=len, reverse=True):
        for m in re.finditer(r"(?<![\w'])" + re.escape(name) + r"(?![\w'])", text, re.I):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((a, names_index[name]))
    return [s for _, s in sorted(hits)]


def parse_deck_page(html: str, is_legendary, names_index: dict[str, str] | None = None) -> dict:
    root, scripts = parse_html(html)
    body = next((n for n in root.iter() if n.tag == "main"), None) or \
        next((n for n in root.iter() if n.tag == "body"), root)

    def excluded(n: Node) -> bool:
        return any(a.tag in ("nav", "footer", "aside") for a in n.ancestors())

    refs = []
    for n in body.iter():
        r = card_ref(n)
        if r and not excluded(n):
            # le carte dentro un link a UN ALTRO mazzo (mazzi simili in fondo) non sono di questo
            if any(deck_href(a) for a in n.ancestors()):
                continue
            refs.append(r)
    decks = split_decks(refs, is_legendary)
    h1 = next((n.inline() for n in body.iter() if n.tag == "h1" and n.inline()), "")
    full = body.text()
    if names_index and not any(len(d["carte"]) == 12 for d in decks):
        # nessun link/immagine riconoscibile: cerco i nomi delle carte nel testo, nell'ordine della pagina
        by_text = split_decks(text_refs(full, names_index), is_legendary)
        if sum(len(d["carte"]) for d in by_text) > sum(len(d["carte"]) for d in decks):
            decks = by_text
    head = full[:2500]
    out = {"nome": h1, **parse_fields(head), "mazzi": decks}
    for u in body.iter():
        if u.tag == "a" and not excluded(u):
            m = USER_RE.match(u.attrs.get("href", ""))
            if m:
                out["autore"] = u.inline() or m.group(1)
                out["autore_url"] = m.group(1)
                break
    # guida: titoli e paragrafi del contenuto principale, nell'ordine della pagina
    parts: list[str] = []
    for n in body.iter():
        if excluded(n) or any(deck_href(a) for a in n.ancestors()):
            continue
        if n.tag in ("h2", "h3", "h4"):
            t = n.inline()
            if t and len(t) < 90:
                parts.append(f"\n## {t}")
        elif n.tag in ("p", "li", "blockquote"):
            if any(a.tag in ("p", "li", "blockquote") for a in n.ancestors()):
                continue
            t = n.inline()
            if len(t) >= 25 and not CARD_IMG_RE.search(t):
                parts.append(("- " if n.tag == "li" else "") + t)
    guide = "\n".join(parts).strip()
    guide = re.sub(r"\n## [^\n]+\s*(?=\n## )", "", guide)        # titoli senza testo sotto
    guide = re.sub(r"(?:\s*\n## [^\n]+)+\s*$", "", guide)        # titoli finali senza testo
    out["guida"] = guide[:6000]
    out["hash_pagina"] = _hash(full)
    return out


# ======================================================================= tabelle delle statistiche

def parse_tables(html: str) -> dict:
    """Tutte le tabelle della pagina con il titolo che le precede, più il testo (per le parti non in tabella)."""
    root, _ = parse_html(html)
    tables = []
    last_heading = ""
    for n in root.iter():
        if n.tag in ("h1", "h2", "h3", "h4"):
            last_heading = n.inline() or last_heading
        if n.tag == "table":
            rows = []
            for tr in n.iter():
                if tr.tag != "tr":
                    continue
                cells = [c.inline() for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables.append({"titolo": last_heading, "colonne": rows[0], "righe": rows[1:]})
    body = next((n for n in root.iter() if n.tag == "main"), None) or root
    return {"tabelle": tables, "testo": body.text()[:40000]}


def interpret(tables: list[dict], legendaries: set[str], card_names: set[str]) -> dict:
    """Riconosce le tabelle note: leggendarie, archetipi, carte, mazzi, matchup."""
    low_leg = {x.lower() for x in legendaries}
    low_cards = {x.lower() for x in card_names}
    low_arch = {a.lower() for a in ARCHETIPI}
    res: dict = {}

    def clean(c: str) -> str:
        return re.sub(r"^\s*[#\d.]*\s*★?\s*", "", c).strip().lower()

    for t in tables:
        firsts = [clean(r[0]) if r else "" for r in t["righe"]]
        # se la prima colonna è una posizione (#), il nome è nella seconda
        if t["righe"] and all(re.fullmatch(r"#?\d+", (r[0] or "").strip()) for r in t["righe"] if r):
            firsts = [clean(r[1]) if len(r) > 1 else "" for r in t["righe"]]
            name_col = 1
        else:
            name_col = 0
        heads = [clean(h) for h in t["colonne"]]
        n_leg = sum(1 for f in firsts if f in low_leg)
        if n_leg >= 3 and sum(1 for h in heads if h in low_leg) >= 3:
            grid = {}
            for r in t["righe"]:
                row = clean(r[0])
                for h, v in zip(t["colonne"][1:], r[1:]):
                    val = _num(v.split()[0]) if v and re.match(r"[\d.,]+", v.strip()) else None
                    if val is not None:
                        grid.setdefault(row, {})[clean(h)] = val
            res["matchup"] = {"titolo": t["titolo"], "griglia": grid}
            continue
        kind = None
        if n_leg >= 3 and n_leg >= len(firsts) * 0.6:
            kind = "leggendarie"
        elif sum(1 for f in firsts if any(f.startswith(a) for a in low_arch)) >= 3:
            kind = "archetipi"
        elif sum(1 for f in firsts if f in low_cards) >= 3:
            kind = "carte"
        elif any(re.search(r"record|deck|mazz", h) for h in heads):
            kind = "mazzi"
        if not kind:
            continue
        rows = []
        for r in t["righe"]:
            e = {"nome": re.sub(r"^\s*★\s*", "", r[name_col]).strip() if len(r) > name_col else ""}
            for h, v in zip(t["colonne"], r):
                hl = h.lower()
                key = None
                if re.search(r"when played|quando giocata", hl):
                    key = "winrate_giocata" if "%" in v or "rate" in hl else "partite_giocata"
                elif re.search(r"effect|effetto", hl):
                    key = "effetto"
                elif re.search(r"cautious|prudente", hl):
                    key = "winrate_prudente"
                elif re.search(r"win\s*rate|winrate|\bwr\b|% vitt", hl):
                    key = "winrate"
                elif re.search(r"range|interval|95", hl):
                    key = "intervallo"
                elif re.search(r"share|play rate|quota|diffusione|usage", hl):
                    key = "quota"
                elif re.search(r"avg|average|round medio|media", hl):
                    key = "round_medio"
                elif re.search(r"w\s*[–-]\s*l|record", hl):
                    key = "record"
                elif re.search(r"games|partite|matches|decks|mazzi", hl):
                    key = "partite" if kind != "carte" or "partite" not in e else "partite_giocata"
                if not key or key in e:
                    continue
                e[key] = v if key in ("record", "intervallo") else (_num(v.split()[0]) if v.strip() else None)
            rows.append(e)
        if kind in res:  # più tabelle dello stesso tipo: tengo la più lunga
            if len(rows) <= len(res[kind]["righe"]):
                continue
        res[kind] = {"titolo": t["titolo"], "righe": rows}
    return res


# ======================================================================= rete

class Fetcher:
    def __init__(self, delay: float = DELAY, save_dir: Path | None = None, opener=None):
        self.delay, self.save_dir, self._last, self.count = delay, save_dir, 0.0, 0
        self._open = opener or self._urlopen

    @staticmethod
    def _urlopen(url: str) -> str:
        last = None
        for ua in (USER_AGENT, "Mozilla/5.0 (compatible; " + USER_AGENT + ")"):
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip",
                                                       "Accept": "text/html,application/xml",
                                                       "Accept-Language": "en"})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    return data.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:  # 403 dai filtri anti-bot: riprovo una volta con l'altra firma
                last = e
                if e.code != 403:
                    raise
        raise last

    def get(self, path: str) -> str:
        url = path if path.startswith("http") else BASE + path
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            html = self._open(url)
        finally:
            self._last = time.time()
            self.count += 1
        if self.save_dir:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-z0-9]+", "_", urllib.parse.urlparse(url).path.lower()).strip("_") or "home"
            (self.save_dir / f"{name}.html").write_text(html, encoding="utf-8")
        return html


# ======================================================================= sincronizzazione

def load_state() -> dict:
    st = store.load("originsmeta")
    st.setdefault("mazzi", {})
    st.setdefault("carte_sito", {})
    st.setdefault("statistiche", {})
    return st


def due(state: dict | None = None, hours: float = SYNC_EVERY_HOURS) -> bool:
    state = state or load_state()
    last = state.get("ultimo_sync_ts") or 0
    return time.time() - last > hours * 3600


def sync(force: bool = False, fetcher: Fetcher | None = None, progress=lambda s: None,
         save_pages: bool = False, everything: bool = False) -> dict:
    """Scarica le novità da OriginsMeta e aggiorna data/originsmeta.json e il meta di BIG-BOB.
    force: anche se l'ultima sincronizzazione è recente. everything: riscarica anche i mazzi invariati."""
    state = load_state()
    if not force and not due(state):
        return {"ok": True, "saltato": True, "motivo": "sincronizzato da meno di 12 ore",
                "ultimo_sync": state.get("ultimo_sync")}
    f = fetcher or Fetcher(save_dir=(store.ROOT / "logs" / "originsmeta") if save_pages else None)
    report = {"ok": True, "nuovi": [], "aggiornati": [], "incompleti": [], "rimossi": [], "errori": [],
              "differenze_carte": []}
    t0 = time.time()

    # 1. carte del sito: nomi, leggendarie, costi e statistiche attuali
    progress("OriginsMeta: carte…")
    try:
        cards = parse_cards_page(f.get(PAGES["carte"]))
        if len(cards) >= 20:
            state["carte_sito"] = cards
    except Exception as e:  # noqa: BLE001
        report["errori"].append(f"carte: {e}")
    site_cards = state["carte_sito"]
    lv = latest_version(list(state["mazzi"].values()))
    cu = update_cards_from_site(site_cards, lv)
    report["carte_aggiunte"], report["carte_cambiate"] = cu["aggiunte"], cu["cambiate"]
    report["patch"] = cu["patch"]
    progress("OriginsMeta: location…")
    try:
        locs = parse_locations_page(f.get(PAGES["location"]))
        if len(locs) >= 10:
            state["location_sito"] = locs
        report["location_aggiunte"] = update_locations_from_site(locs)
    except Exception as e:  # noqa: BLE001
        report["errori"].append(f"location: {e}")
    db_cards = store.load("cards")
    db_leg = {store.slug(c["nome"]) for c in db_cards if c.get("leggendaria")}
    site_leg = {s for s, c in site_cards.items() if c.get("leggendaria")}

    def is_legendary(slug: str) -> bool:
        return slug in site_leg or slug in db_leg

    names_index = {c["nome"]: s for s, c in site_cards.items() if c.get("tipo") != "creata"}
    for c in db_cards:
        names_index.setdefault(c["nome"], store.slug(c["nome"]))

    # 2. elenchi dei mazzi
    listed: dict[str, dict] = {}
    for key in ("mazzi", "tornei"):
        progress(f"OriginsMeta: elenco {key}…")
        try:
            lst = parse_deck_list(f.get(PAGES[key]))
            listed.update(lst["mazzi"])
            if key == "mazzi" and lst["totale_dichiarato"] and \
                    sum(1 for u in lst["mazzi"] if "/community/" in u) < lst["totale_dichiarato"]:
                # l'elenco non li mostra tutti: completo dalle pagine degli autori
                for u in _users_from_sitemap(f):
                    for url in parse_user_page(f.get(f"/{LANG}/u/{u}")):
                        listed.setdefault(url, {"url": url, "tipo": "community"})
        except Exception as e:  # noqa: BLE001
            report["errori"].append(f"elenco {key}: {e}")
    if not listed:
        report["ok"] = False
        report["errori"].append("nessun mazzo trovato negli elenchi: il sito è cambiato o non è raggiungibile")

    # 3. pagine dei mazzi nuovi o cambiati
    now = time.time()
    for i, (url, card) in enumerate(listed.items(), 1):
        olds = [e for e in state["mazzi"].values() if (e.get("pagina") or e.get("url")) == url]
        old = olds[0] if olds else None
        stale = not old or old.get("hash_scheda") != card.get("hash_scheda") or \
            now - old.get("scaricato_ts", 0) > REFETCH_DAYS * 86400 or not all(e.get("completo") for e in olds)
        if not stale and not everything:
            for e in olds:
                if len(olds) == 1:
                    e.update({k: v for k, v in card.items() if v not in (None, "") and k != "carte_scheda"})
                e["visto_ts"] = now
            continue
        for e in olds:  # la pagina si rilegge da capo (un torneo può avere cambiato i suoi mazzi)
            state["mazzi"].pop(e["url"], None)
        progress(f"OriginsMeta: mazzo {i}/{len(listed)}…")
        try:
            page = parse_deck_page(f.get(url), is_legendary, names_index)
        except Exception as e:  # noqa: BLE001
            report["errori"].append(f"{url}: {e}")
            continue
        entries = _entries_from_page(url, card, page, site_cards, is_legendary)
        for e in entries:
            e["scaricato_ts"] = e["visto_ts"] = now
            e["scaricato"] = store.now()
            (report["aggiornati"] if old else report["nuovi"]).append(e["nome"])
            if not e["completo"]:
                report["incompleti"].append(e["nome"])
            state["mazzi"][e["url"]] = e

    # mazzi spariti dal sito (cancellati dagli autori): fuori dopo 2 sincronizzazioni senza vederli
    if listed:
        for url, e in list(state["mazzi"].items()):
            base = e.get("pagina") or url.split("#")[0]
            if base not in listed and now - e.get("visto_ts", now) > 2 * SYNC_EVERY_HOURS * 3600:
                report["rimossi"].append(e.get("nome", url))
                del state["mazzi"][url]

    # 4. statistiche delle partite e carte più giocate
    names_leg = {c["nome"] for c in site_cards.values() if c.get("leggendaria")} | \
        {c["nome"] for c in db_cards if c.get("leggendaria")}
    names_cards = {c["nome"] for c in site_cards.values()} | {c["nome"] for c in db_cards}
    for key in ("statistiche", "piu_giocati"):
        progress(f"OriginsMeta: {key.replace('_', ' ')}…")
        try:
            raw = parse_tables(f.get(PAGES[key]))
            raw["interpretate"] = interpret(raw["tabelle"], names_leg, names_cards)
            raw["campione"] = _sample_size(raw["testo"])
            raw["scaricato"] = store.now()
            state["statistiche"][key] = raw
        except Exception as e:  # noqa: BLE001
            report["errori"].append(f"{key}: {e}")

    report["differenze_carte"] = card_differences(site_cards, db_cards)
    if report["ok"]:  # se il sito non risponde, al prossimo avvio si riprova
        state["ultimo_sync"] = store.now()
        state["ultimo_sync_ts"] = time.time()
    state["esito"] = {k: (v if not isinstance(v, list) else v[:40]) for k, v in report.items()}
    store.save("originsmeta", state)
    report["mazzi_in_meta"] = apply_to_meta(state)
    report["totale_mazzi"] = len(state["mazzi"])
    report["completi"] = sum(1 for e in state["mazzi"].values() if e.get("completo"))
    report["richieste"] = f.count
    report["secondi"] = round(time.time() - t0)
    return report


def _users_from_sitemap(f: Fetcher) -> list[str]:
    try:
        xml = f.get(f"/{LANG}/sitemap-community.xml")
    except Exception:  # noqa: BLE001
        return []
    return list(dict.fromkeys(re.findall(r"<loc>\s*https?://[^<]*/u/([^<\s/]+)\s*</loc>", xml)))


def _site_name(slug: str | None, site_cards: dict) -> str:
    if not slug:
        return ""
    c = site_cards.get(slug)
    return c["nome"] if c else title_from_slug(slug)


def _entries_from_page(url: str, card: dict, page: dict, site_cards: dict, is_legendary=lambda s: False) -> list[dict]:
    decks = page.get("mazzi") or [{"leggendaria": None, "carte": []}]
    multi = len(decks) > 1
    out = []
    for i, d in enumerate(decks):
        if not d.get("leggendaria") and not multi:
            # leggendaria non trovata nella pagina: la prendo dalla scheda dell'elenco
            d["leggendaria"] = next((r for r in card.get("carte_scheda") or [] if is_legendary(r)), None)
        names = [_site_name(s, site_cards) for s in d["carte"]]
        # i campi della scheda nell'elenco (brevi e ordinati) valgono più di quelli letti nella pagina intera
        e = {**{k: v for k, v in page.items() if k not in ("mazzi",) and v not in (None, "")},
             **{k: v for k, v in card.items() if k != "carte_scheda" and v not in (None, "")}}
        e["url"] = url + (f"#{i + 1}" if multi else "")
        e["pagina"] = url
        if multi:
            e["nome"] = f"{page.get('nome') or card.get('nome')} · {chr(65 + i)}"
        else:
            e["nome"] = card.get("nome") or page.get("nome") or url.rsplit("/", 1)[-1]
        e["leggendaria"] = _site_name(d["leggendaria"], site_cards) or None
        e["carte"] = names
        e["completo"] = bool(e["leggendaria"]) and len(names) == 12
        e["fonte"] = FONTE
        out.append(e)
    return out


def _sample_size(text: str) -> int | None:
    m = re.search(r"([\d.,]+)\s+(?:games|partite)\b", text, re.I)
    return _int(m.group(1)) if m else None


def update_cards_from_site(site_cards: dict, version: str | None = None) -> dict:
    """Allinea il database delle carte a OriginsMeta.

    - carte mancanti: aggiunte (le carte create in partita, i token, restano fuori);
    - costo/attacco/vita/leggendaria diversi: aggiornati come patch, con lo storico (patch_changes li mostra e
      le lezioni su quelle carte vanno riverificate);
    - testo: riempito se manca; sostituito solo sulle carte che vengono da OriginsMeta (quelle che hai corretto
      tu o letto dalle schermate restano come sono).
    Se la pagina sembra letta male (meno di 60 carte con il costo) non cambia nulla delle carte esistenti."""
    db = {store.slug(c["nome"]): c for c in store.load("cards")}
    good = [sc for sc in site_cards.values() if sc.get("tipo") != "creata" and sc.get("costo") is not None]
    healthy = len(good) >= 60
    label = f"{version} (OriginsMeta)" if version else f"OriginsMeta {store.now()[:10]}"
    added, changed, items_new, items_upd = [], [], [], []
    for sc in good:
        cur = db.get(sc["slug"]) or db.get(store.slug(sc["nome"]))
        if cur is None:
            item = {"nome": sc["nome"], "costo": sc["costo"], "leggendaria": bool(sc.get("leggendaria")),
                    "tipo": sc.get("tipo") or ("creatura" if sc.get("attacco") is not None else "spell"),
                    "fonte": FONTE, "note": f"da OriginsMeta ({store.now()[:10]})"}
            if sc.get("attacco") is not None:
                item["attacco"], item["vita"] = sc["attacco"], sc["vita"]
            if sc.get("testo"):
                item["testo"] = sc["testo"]
            items_new.append(item)
            added.append(sc["nome"])
            continue
        if not healthy:
            continue
        upd = {"nome": cur["nome"]}
        for k in ("costo", "attacco", "vita"):
            if sc.get(k) is not None and _int(str(cur.get(k))) != sc[k]:
                upd[k] = sc[k]
        if sc.get("leggendaria") and not cur.get("leggendaria"):
            upd["leggendaria"] = True
        if sc.get("testo") and (not cur.get("testo") or (cur.get("fonte") == FONTE and cur.get("testo") != sc["testo"])):
            upd["testo"] = sc["testo"]
        if len(upd) > 1:
            if cur.get("fonte"):
                upd["fonte"] = cur["fonte"]
            items_upd.append(upd)
            diff = {k: (cur.get(k), v) for k, v in upd.items() if k not in ("nome", "testo")}
            if diff:
                changed.append({"carta": cur["nome"], "modifiche": diff})
    if items_new:
        store.upsert("cards", items_new, label)
    if items_upd:
        store.upsert("cards", items_upd, label)
        if changed:
            pt = store.load("patches")
            if not any(x.get("nome") == label for x in pt):
                pt.append({"nome": label, "data": store.now(), "note": "cambiamenti letti da OriginsMeta",
                           "fonte": FONTE})
                store.save("patches", pt)
    return {"aggiunte": added, "cambiate": changed, "patch": label if changed else None, "pagina_sana": healthy}


def update_locations_from_site(site_locs: dict) -> list[str]:
    if len(site_locs) < 10:  # pagina letta male: non tocco nulla
        return []
    db = {store.slug(x["nome"]): x for x in store.load("locations")}
    new, upd = [], []
    for s, sl in site_locs.items():
        cur = db.get(s)
        if cur is None:
            new.append({"nome": sl["nome"], "testo": sl["testo"], "fonte": FONTE})
        elif not cur.get("testo") or (cur.get("fonte") == FONTE and cur.get("testo") != sl["testo"]):
            upd.append({"nome": cur["nome"], "testo": sl["testo"], "fonte": cur.get("fonte") or FONTE})
    if new or upd:
        store.upsert("locations", new + upd)
    return [x["nome"] for x in new]


def card_differences(site_cards: dict, db_cards: list[dict]) -> list[dict]:
    """Carte il cui costo/attacco/vita nel database di BIG-BOB è diverso da quello su OriginsMeta."""
    by_slug = {store.slug(c["nome"]): c for c in db_cards}
    diffs = []
    for s, sc in site_cards.items():
        dc = by_slug.get(s) or by_slug.get(store.slug(sc["nome"]))
        if not dc or sc.get("tipo") == "creata":
            continue
        for k in ("costo", "attacco", "vita"):
            if sc.get(k) is None or dc.get(k) in (None, ""):
                continue
            if _int(str(dc.get(k))) != sc[k]:
                diffs.append({"carta": dc["nome"], "campo": k, "database": dc.get(k), "originsmeta": sc[k]})
    return diffs


# ======================================================================= collegamento al meta di BIG-BOB

def deck_weight(e: dict, latest_version: str | None) -> float:
    """Quanto pesa una lista community nelle probabilità sulla mano avversaria.
    Versione attuale 1, versioni vecchie 0.4; le liste con partite registrate valgono di più."""
    w = 1.0 if (not latest_version or e.get("versione") == latest_version) else 0.4
    return round(w * (1 + min(e.get("partite") or 0, 30) / 15), 2)


def latest_version(decks: list[dict]) -> str | None:
    dated = sorted((d for d in decks if d.get("versione") and d.get("data")), key=lambda d: d["data"])
    return dated[-1]["versione"] if dated else None


def apply_to_meta(state: dict | None = None) -> int:
    """Scrive i mazzi completi di OriginsMeta nel meta di BIG-BOB (sostituendo quelli della sincronizzazione
    precedente), con i nomi delle carte del database. Le tue partite e gli altri archetipi restano come sono."""
    state = state or load_state()
    decks = [e for e in state["mazzi"].values() if e.get("completo")]
    lv = latest_version(decks)
    meta = [a for a in store.load("meta") if a.get("fonte") != FONTE]
    for e in decks:
        meta.append({"nome": f"{e['nome']} (OriginsMeta)", "leggendaria": store.canonical(e["leggendaria"]),
                     "carte": [store.canonical(c) for c in e["carte"]], "volte_visto": 0, "vittorie_mie": 0,
                     "sconfitte_mie": 0, "community": deck_weight(e, lv), "fonte": FONTE, "url": e["url"],
                     "archetipo": e.get("archetipo"), "versione": e.get("versione"), "winrate": e.get("winrate"),
                     "partite": e.get("partite"), "autore": e.get("autore"), "completo": True,
                     "ultimo": e.get("scaricato") or store.now(), "creato": e.get("data") or store.now()})
    store.save("meta", meta)
    return len(decks)


# ======================================================================= letture per gli strumenti

def decks(legendary: str = "", archetype: str = "", version: str = "", sort: str = "winrate",
          limit: int = 20, min_games: int = 0) -> dict:
    st = load_state()
    items = list(st["mazzi"].values())
    if legendary:
        items = [e for e in items if store.slug(e.get("leggendaria") or "") == store.slug(store.canonical(legendary))
                 or store.slug(legendary) in store.slug(e.get("leggendaria") or "")]
    if archetype:
        items = [e for e in items if archetype.lower() in (e.get("archetipo") or "").lower()]
    if version:
        items = [e for e in items if version.lower() in (e.get("versione") or "").lower()]
    if min_games:
        items = [e for e in items if (e.get("partite") or 0) >= min_games]
    keyf = {"winrate": lambda e: (-(e.get("winrate") or -1), -(e.get("partite") or 0)),
            "partite": lambda e: -(e.get("partite") or 0),
            "rating": lambda e: (-(e.get("rating") or 0), -(e.get("voti") or 0)),
            "recenti": lambda e: e.get("data") or ""}.get(sort, lambda e: 0)
    items.sort(key=keyf, reverse=(sort == "recenti"))
    compact = [{k: e.get(k) for k in ("nome", "leggendaria", "archetipo", "versione", "winrate", "partite",
                                      "rating", "voti", "autore", "data", "tipo", "completo", "carte",
                                      "descrizione_breve", "url")} for e in items[:limit]]
    return {"ultimo_sync": st.get("ultimo_sync"), "totale": len(items), "mazzi": compact,
            "nota": "Winrate dal tracker di OriginsMeta: chi registra vince in media più del 50%, quindi confronta "
                    "i mazzi tra loro, non con il 50%. Poche partite = numero poco affidabile."}


def deck(name_or_url: str) -> dict | None:
    st = load_state()
    if name_or_url in st["mazzi"]:
        return st["mazzi"][name_or_url]
    s = store.slug(name_or_url)
    best = [e for e in st["mazzi"].values() if store.slug(e.get("nome", "")) == s] or \
           [e for e in st["mazzi"].values() if s and s in store.slug(e.get("nome", ""))]
    return best[0] if best else None


def stats(section: str = "") -> dict:
    st = load_state()
    s = st["statistiche"]
    out = {"ultimo_sync": st.get("ultimo_sync")}
    for key in ("statistiche", "piu_giocati"):
        part = s.get(key) or {}
        interp = part.get("interpretate") or {}
        if section:
            if section in interp:
                out[f"{key}.{section}"] = interp[section]
            continue
        out[key] = {"campione_partite": part.get("campione"), "scaricato": part.get("scaricato"),
                    "tabelle_riconosciute": {k: (v.get("righe") or v.get("griglia")) for k, v in interp.items()}}
        if not interp and part.get("testo"):
            out[key]["testo"] = part["testo"][:12000]
    if not section:
        out["nota"] = ("Statistiche del tracker di OriginsMeta, solo patch attuale. I winrate di mazzi, archetipi e "
                       "carte vanno confrontati tra loro (chi registra vince più del 50%); quelli delle leggendarie e "
                       "dei matchup contano entrambi i giocatori.")
    return out


def summary_line(rep: dict) -> str:
    if rep.get("saltato"):
        return f"Meta OriginsMeta già aggiornato ({rep.get('ultimo_sync')})."
    if not rep.get("ok"):
        return "Meta OriginsMeta non aggiornato: " + "; ".join(rep.get("errori", [])[:2])
    parts = [f"{rep.get('totale_mazzi', 0)} mazzi ({rep.get('completi', 0)} con lista completa)"]
    if rep.get("nuovi"):
        parts.append(f"{len(rep['nuovi'])} nuovi: " + ", ".join(rep["nuovi"][:4]) + ("…" if len(rep["nuovi"]) > 4 else ""))
    st = load_state()["statistiche"].get("statistiche") or {}
    if st.get("campione"):
        parts.append(f"statistiche su {st['campione']} partite")
    if rep.get("carte_aggiunte"):
        parts.append(f"{len(rep['carte_aggiunte'])} carte aggiunte al database")
    if rep.get("location_aggiunte"):
        parts.append(f"{len(rep['location_aggiunte'])} location aggiunte")
    if rep.get("carte_cambiate"):
        ch = "; ".join(f"{c['carta']} " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in c["modifiche"].items())
                       for c in rep["carte_cambiate"][:4])
        parts.append(f"⚠ carte cambiate ({rep['patch']}): {ch}" + ("…" if len(rep["carte_cambiate"]) > 4 else ""))
    if rep.get("errori"):
        parts.append(f"{len(rep['errori'])} pagine non lette")
    return "Meta aggiornato da OriginsMeta: " + " · ".join(parts) + "."


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Sincronizza il meta da OriginsMeta")
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--tutto", action="store_true", help="riscarica anche i mazzi invariati")
    ap.add_argument("--salva-pagine", action="store_true")
    a = ap.parse_args()
    r = sync(force=a.forza or a.tutto, progress=lambda s: print(s, flush=True), save_pages=a.salva_pagine,
             everything=a.tutto)
    print(summary_line(r))
    if r.get("incompleti"):
        print("Liste incomplete:", ", ".join(r["incompleti"][:20]))
    for d in r.get("differenze_carte", [])[:30]:
        print(f"  {d['carta']}: {d['campo']} {d['database']} nel database, {d['originsmeta']} su OriginsMeta")
    for e in r.get("errori", [])[:10]:
        print("  errore:", e)
