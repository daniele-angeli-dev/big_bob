"""Test dell'importazione da OriginsMeta con pagine finte (nessuna connessione): python tests/test_originsmeta.py"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from origins import store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
for k, p in store.FILES.items():
    store.FILES[k] = tmp / p.name
store.DATA = tmp

from origins import odds, originsmeta as om  # noqa: E402

LEG = {"robin-hood": ("Robin Hood", 8, "4/4"), "van-helsing": ("Van Helsing", 4, "3/4"),
       "three-not-so-little-pigs": ("Three Not So Little Pigs", 7, "3/3"), "merlin": ("Merlin", 5, "5/5")}
NORMAL = ["Bullseye", "Stroke of Midnight", "Baby Bear", "Roo", "Rumple", "Ali Baba", "Big Bad Wolf", "Jekyll",
          "Marian", "Galahad", "Guy of Gisborne", "Obliterate", "Mind Palace", "Spellbook", "Glinda", "Mummy",
          "Three Blind Mice", "Mouse", "Sandman", "Golden Egg", "Trash for Treasure", "Dark Omen", "Bagheera",
          "Defense Matrix", "Shahrazad", "Forbidden Knowledge", "Impundulu"]
SPELLS = {"Bullseye", "Stroke of Midnight", "Obliterate", "Mind Palace", "Spellbook", "Trash for Treasure",
          "Dark Omen", "Defense Matrix", "Forbidden Knowledge"}


def sl(n):
    return store.slug(n)


def img(slug, w=96):
    return f'<img alt="" src="/_next/image?url=%2Fcards%2Fsm%2F{slug}.webp&amp;w={w}&amp;q=75">'


def card_tile(name, cost, stats=None, leg=False, text="On Reveal: draw a card.", created=False):
    s = sl(name)
    st = f'<span>{stats.split("/")[0]} Power, {stats.split("/")[1]} Health</span><b>{stats}</b>' if stats else ""
    kind = "Created card" if created else ("Spell" if not stats else "Unit")
    title = f"★{name} (Legendary)" if leg else name
    return (f'<a href="/en/cards/{s}" class="tile"><div><img alt="{name}" src="/cards/sm/{s}.webp">'
            f'<h3>{title}</h3><span>Mana {cost}</span>{st}<p>{text}</p><span>{kind}</span>'
            f'{"<span>Legendary</span>" if leg else ""}<span>Good</span><small>8.5/10 · 2 votes</small></div></a>')


def page(main):
    return (f'<!DOCTYPE html><html><head><title>x</title><script>self.__next_f.push([1,"{{}}"])</script></head>'
            f'<body><nav><a href="/en/cards/merlin">Merlin</a><a href="/en/decks">Decks</a></nav>'
            f'<main>{main}</main><footer><a href="/en/cards/roo">Roo</a></footer></body></html>')


cards_html = page("<h1>Cards</h1><p>144 results</p><div class='grid'>" + "".join(
    [card_tile(n, c, s, leg=True, text="Snipe 3. On Reveal: deal 2 damage to all enemies.") for n, c, s in LEG.values()]
    + [card_tile(n, 1 if n in SPELLS else 2, None if n in SPELLS else "2/2") for n in NORMAL]
    + [card_tile("Bagheera", 2, "1/1"), card_tile("Garlic", 1, None, created=True),
       card_tile("Huck Finn", 2, "3/2", text="When discarded: deal 2 damage to a random enemy barrier.")]) + "</div>")

SNIPER = ["Bullseye", "Stroke of Midnight", "Baby Bear", "Roo", "Rumple", "Ali Baba", "Big Bad Wolf", "Jekyll",
          "Marian", "Galahad", "Guy of Gisborne", "Obliterate"]
VH = ["Mind Palace", "Spellbook", "Glinda", "Mummy", "Sandman", "Golden Egg", "Trash for Treasure", "Dark Omen",
      "Defense Matrix", "Shahrazad", "Forbidden Knowledge", "Impundulu"]
PIGS = ["Baby Bear", "Roo", "Three Blind Mice", "Mouse", "Golden Egg", "Big Bad Wolf", "Bagheera", "Mummy",
        "Sandman", "Ali Baba", "Rumple", "Glinda"]


def list_tile(kind, slug, name, leg, archetype, wr, version, date, author, desc, rating=""):
    return (f'<article class="deck"><a href="/en/decks/{kind}/{slug}"><h3>{name}</h3></a>'
            f'<div><a href="/en/u/{author}">{author}</a><span>Creator</span></div>'
            f'<div><span>{archetype}</span>{rating}<span>{wr}</span><span>{version}</span><time>{date}</time></div>'
            f'<p>{desc}</p><div class="icons">{img(sl(leg), 48)}</div></article>')


decks_html = page("<h1>Community decks</h1><p>3 results</p><div>" +
                  list_tile("community", "sniper-e4a2", "SNIPER", "Robin Hood", "Midrange", "88% · 16", "0.7",
                            "2026-10-15", "robip-origins", "Focus one barrier, then snipe a second one to 10.") +
                  list_tile("community", "van-helsing-control-c220", "Van Helsing Control", "Van Helsing", "Control",
                            "74% · 19", "0.7", "2026-10-08", "coachcrono", "Pure control: win on resources, then heal.",
                            '<span>★5.0 (1)</span>') +
                  list_tile("community", "old-pigs-1111", "Old Pigs", "Three Not So Little Pigs", "Aggro", "—",
                            "Demo · 21 Sep", "2026-09-22", "sbardi", "Early pressure with piglets and beasts.") +
                  "</div>")


def deck_page(name, leg, cards, extra=""):
    rows = "".join(f'<tr><td><a href="/en/cards/{sl(c)}">{img(sl(c))}</a></td><td>{c}</td><td>Unit</td>'
                   f'<td>2</td></tr>' for c in cards)
    return page(f'<h1>{name}</h1><a href="/en/u/robip-origins">robip-origins</a><span>Midrange</span>'
                f'<p>Created October 15, 2026 · Patch 0.7 · 88% over 16 recorded games</p>'
                f'<div class="leg"><a href="/en/cards/{sl(leg)}"><img src="/cards/md/{sl(leg)}.webp" alt="{leg}"></a></div>'
                f'<table><tr><th>Card</th><th>Name</th><th>Type</th><th>Mana</th></tr>{rows}</table>'
                f'<h2>Game plan</h2><p>Focus on one barrier and destroy it, then use Snipe to bring a second one to 10.</p>'
                f'<h2>Mulligan</h2><ul><li>Keep Rumple and the 2-mana cards to pressure early.</li></ul>'
                f'<h2>Empty</h2>{extra}'
                f'<section><h2>Similar decks</h2><a href="/en/decks/community/old-pigs-1111"><h3>Old Pigs</h3>'
                f'{img("three-not-so-little-pigs")}{img("roo")}{img("mouse")}</a></section>')


# pagina che mostra le carte solo come testo (nessun link o immagine): si ricade sui nomi nel testo
vh_text_only = page("<h1>Van Helsing Control</h1><p>Legendary: Van Helsing</p><ul>" +
                    "".join(f"<li>{c} ×2</li>" for c in VH) + "</ul><p>Stabilize and win on resources late.</p>")

tour_html = page("<h1>Line-up Crimson Cup Practice</h1><p>Patch 0.7</p>" + "".join(
    f'<h2>{t}</h2><a href="/en/cards/{sl(lg)}">{img(sl(lg))}</a>' + "".join(img(sl(c)) for c in cs)
    for t, lg, cs in [("A · Pigs", "Three Not So Little Pigs", PIGS), ("B · Van", "Van Helsing", VH),
                      ("C · Robin", "Robin Hood", SNIPER)]))
tour_list = page('<div>' + list_tile("tournament", "line-up-crimson-f313", "Line-up Crimson Cup Practice",
                                     "Robin Hood", "Control", "—", "0.7", "2026-10-05", "robip-origins",
                                     "Three decks for the practice tournament.") + '</div>')

analytics_html = page(
    "<h1>Analytics</h1><p>Meta snapshot: 1,332 games · updated every 5 minutes</p>"
    "<h2>Legendaries</h2><table><tr><th>Legendary</th><th>Win rate</th><th>95% range</th><th>Cautious</th>"
    "<th>Games</th><th>W–L</th><th>Play share</th></tr>"
    "<tr><td>★Van Helsing</td><td>62.3%</td><td>57%–68%</td><td>56.7%</td><td>302</td><td>188–114</td><td>14.4%</td></tr>"
    "<tr><td>★Three Not So Little Pigs</td><td>58.5%</td><td>53%–63%</td><td>53.4%</td><td>366</td><td>214–152</td><td>17.4%</td></tr>"
    "<tr><td>★Robin Hood</td><td>59.9%</td><td>53%–66%</td><td>53.3%</td><td>217</td><td>130–87</td><td>10.3%</td></tr>"
    "<tr><td>★Merlin</td><td>43.0%</td><td>36%–50%</td><td>36.0%</td><td>179</td><td>77–102</td><td>8.5%</td></tr></table>"
    "<h2>Archetypes</h2><table><tr><th>Archetype</th><th>Win rate</th><th>Games</th><th>Share</th></tr>"
    "<tr><td>Discard</td><td>76.3%</td><td>93</td><td>7%</td></tr><tr><td>Control</td><td>66.9%</td><td>426</td><td>32%</td></tr>"
    "<tr><td>Midrange</td><td>57.8%</td><td>453</td><td>34%</td></tr></table>"
    "<h2>Cards</h2><table><tr><th>#</th><th>Card</th><th>Win rate in deck</th><th>Games</th><th>Win rate when played</th>"
    "<th>Games played</th><th>Play effect</th><th>Avg. round</th></tr>"
    "<tr><td>1</td><td>Golden Egg</td><td>62.9%</td><td>590</td><td>70.9%</td><td>388</td><td>+8.0</td><td>4.1</td></tr>"
    "<tr><td>2</td><td>Baby Bear</td><td>66.6%</td><td>583</td><td>70.1%</td><td>412</td><td>+3.6</td><td>3.5</td></tr>"
    "<tr><td>3</td><td>Mind Palace</td><td>70.3%</td><td>387</td><td>80.2%</td><td>101</td><td>+9.9</td><td>4.6</td></tr></table>"
    "<h2>Matchups</h2><table><tr><th></th><th>Van Helsing</th><th>Robin Hood</th><th>Merlin</th></tr>"
    "<tr><td>Van Helsing</td><td>—</td><td>55.0%</td><td>61.2%</td></tr>"
    "<tr><td>Robin Hood</td><td>45.0%</td><td>—</td><td>58.1%</td></tr>"
    "<tr><td>Merlin</td><td>38.8%</td><td>41.9%</td><td>—</td></tr></table>")
most_html = page("<h1>Most played</h1><p>49 decks</p><table><tr><th>#</th><th>Card</th><th>Type</th><th>Cost</th>"
                 "<th>Decks</th><th>Share</th></tr><tr><td>1</td><td>Merlin</td><td>Unit</td><td>5</td><td>8</td><td>16%</td></tr>"
                 "<tr><td>2</td><td>Van Helsing</td><td>Unit</td><td>4</td><td>6</td><td>12%</td></tr>"
                 "<tr><td>3</td><td>Robin Hood</td><td>Unit</td><td>8</td><td>4</td><td>8%</td></tr></table>")

SITE = {
    "/en/cards": cards_html, "/en/decks": decks_html, "/en/decks/tournament": tour_list,
    "/en/decks/community/sniper-e4a2": deck_page("SNIPER", "Robin Hood", SNIPER),
    "/en/decks/community/van-helsing-control-c220": vh_text_only,
    "/en/decks/community/old-pigs-1111": deck_page("Old Pigs", "Three Not So Little Pigs", PIGS[:9]),
    "/en/decks/tournament/line-up-crimson-f313": tour_html,
    "/en/analytics": analytics_html, "/en/tier-list/most-played": most_html,
}
requested = []


def opener(url):
    path = url.replace(om.BASE, "")
    requested.append(path)
    if path not in SITE:
        raise OSError(f"404 {path}")
    return SITE[path]


# ---- database di BIG-BOB: Roo con un costo diverso dal sito, Huck Finn assente
store.upsert("cards", [{"nome": "Roo", "costo": 3, "attacco": 2, "vita": 2, "tipo": "creatura"},
                       {"nome": "Robin Hood", "costo": 8, "attacco": 4, "vita": 4, "leggendaria": True,
                        "tipo": "creatura"}])
store.save("meta", [{"nome": "Dracula aggro", "leggendaria": "Dracula", "carte": ["Bat"], "volte_visto": 3,
                     "vittorie_mie": 1, "sconfitte_mie": 2}])

rep = om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=opener))
assert rep["ok"], rep
st = om.load_state()

# carte del sito
sc = st["carte_sito"]
assert sc["robin-hood"]["leggendaria"] and sc["robin-hood"]["costo"] == 8 and sc["robin-hood"]["attacco"] == 4
assert sc["bagheera"]["costo"] == 2 and sc["bagheera"]["vita"] == 1 and sc["garlic"]["tipo"] == "creata"
assert sc["huck-finn"]["testo"].startswith("When discarded: deal 2 damage"), sc["huck-finn"]
assert "Mana" not in sc["huck-finn"]["testo"] and "votes" not in sc["huck-finn"]["testo"]
# carte mancanti aggiunte, quelle esistenti mai sovrascritte, token esclusi, differenze segnalate
db = {c["nome"]: c for c in store.load("cards")}
assert "Huck Finn" in db and db["Huck Finn"]["fonte"] == "originsmeta" and db["Huck Finn"]["attacco"] == 3
assert "Garlic" not in db
assert db["Roo"]["costo"] == 3, "una carta già presente non va sovrascritta"
assert {"carta": "Roo", "campo": "costo", "database": 3, "originsmeta": 2} in rep["differenze_carte"], rep["differenze_carte"]

# mazzi
m = st["mazzi"]
sn = m[om.BASE + "/en/decks/community/sniper-e4a2"]
assert sn["completo"] and sn["leggendaria"] == "Robin Hood" and sn["carte"] == SNIPER, sn["carte"]
assert sn["winrate"] == 88 and sn["partite"] == 16 and sn["versione"] == "0.7" and sn["archetipo"] == "Midrange"
assert sn["autore"] == "robip-origins" and sn["data"] == "2026-10-15"
assert "Focus on one barrier" in sn["guida"] and "## Mulligan" in sn["guida"] and "Empty" not in sn["guida"], sn["guida"]
assert "Similar decks" not in sn["guida"]
vh = m[om.BASE + "/en/decks/community/van-helsing-control-c220"]
assert vh["completo"] and vh["leggendaria"] == "Van Helsing" and sorted(vh["carte"]) == sorted(VH), vh
assert vh["rating"] == 5.0 and vh["voti"] == 1 and vh["archetipo"] == "Control"
old = m[om.BASE + "/en/decks/community/old-pigs-1111"]
assert not old["completo"] and old["versione"].startswith("Demo") and "Old Pigs" in rep["incompleti"]
tour = [e for u, e in m.items() if "/tournament/" in u]
assert len(tour) == 3 and all(e["completo"] for e in tour), tour
assert {e["leggendaria"] for e in tour} == {"Three Not So Little Pigs", "Van Helsing", "Robin Hood"}
pigs = next(e for e in tour if e["leggendaria"].startswith("Three"))
assert pigs["carte"] == PIGS and pigs["nome"].endswith("· A")

# statistiche
an = st["statistiche"]["statistiche"]
assert an["campione"] == 1332, an["campione"]
it = an["interpretate"]
vhs = next(r for r in it["leggendarie"]["righe"] if r["nome"] == "Van Helsing")
assert vhs["winrate"] == 62.3 and vhs["partite"] == 302 and vhs["quota"] == 14.4 and vhs["winrate_prudente"] == 56.7
assert vhs["record"] == "188–114"
assert it["archetipi"]["righe"][0] == {"nome": "Discard", "winrate": 76.3, "partite": 93, "quota": 7}
mp = next(r for r in it["carte"]["righe"] if r["nome"] == "Mind Palace")
assert mp["winrate"] == 70.3 and mp["winrate_giocata"] == 80.2 and mp["effetto"] == 9.9 and mp["round_medio"] == 4.6, mp
assert it["matchup"]["griglia"]["robin hood"]["merlin"] == 58.1
pg = st["statistiche"]["piu_giocati"]["interpretate"]
assert pg["leggendarie"]["righe"][0]["nome"] == "Merlin"

# collegamento al meta e alle probabilità sulla mano avversaria
meta = store.load("meta")
assert any(a["nome"] == "Dracula aggro" and a["volte_visto"] == 3 for a in meta), "il meta di Daniele resta"
om_decks = [a for a in meta if a.get("fonte") == "originsmeta"]
assert len(om_decks) == rep["mazzi_in_meta"] == 5, [a["nome"] for a in om_decks]
o = odds.opponent_hand_odds(meta, "Robin Hood", {"Marian": 1}, 4)
assert any(c["carta"] == "Obliterate" and c["p_in_mano"] > 0 for c in o["per_carta"]), o
assert all("OriginsMeta" in a["nome"] for a in o["archetipi_compatibili"])
store.summary = om.summary_line(rep)
assert "5 mazzi" in om.summary_line(rep) or "mazzi" in om.summary_line(rep)

# seconda sincronizzazione: niente pagine dei mazzi invariati, meta non duplicato
requested.clear()
rep2 = om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=opener))
deck_pages = [p for p in requested if p.count("/") >= 4]
assert deck_pages == ["/en/decks/community/old-pigs-1111"], deck_pages  # solo l'incompleto si riprova
assert len([a for a in store.load("meta") if a.get("fonte") == "originsmeta"]) == 5
assert om.sync(force=False, fetcher=om.Fetcher(delay=0, opener=opener))["saltato"]

# un mazzo cambiato nell'elenco viene riscaricato; uno sparito resta finché non scade
SITE["/en/decks"] = decks_html.replace("88% · 16", "90% · 20")
requested.clear()
om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=opener))
assert "/en/decks/community/sniper-e4a2" in requested
assert om.load_state()["mazzi"][om.BASE + "/en/decks/community/sniper-e4a2"]["partite"] == 20

# letture per gli strumenti
d = om.decks(legendary="robin hood")
assert d["mazzi"] and all(x["leggendaria"] == "Robin Hood" for x in d["mazzi"])
assert om.deck("sniper")["guida"]
s = om.stats()
assert "leggendarie" in s["statistiche"]["tabelle_riconosciute"]
assert om.stats("matchup")["statistiche.matchup"]["griglia"]

# sito irraggiungibile: errore chiaro, dati precedenti intatti
before = json.dumps(om.load_state()["mazzi"], sort_keys=True)
bad = om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=lambda u: (_ for _ in ()).throw(OSError("offline"))))
assert not bad["ok"] and bad["errori"]
assert json.dumps(om.load_state()["mazzi"], sort_keys=True) == before
assert "non aggiornato" in om.summary_line(bad)
st_bad = om.load_state()
st_bad["ultimo_sync_ts"] = 0
store.save("originsmeta", st_bad)
om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=lambda u: (_ for _ in ()).throw(OSError("offline"))))
assert om.due(), "dopo un errore di rete si riprova al prossimo avvio"
# una volta al giorno: ieri sera -> sì, stamattina -> no (anche se sono passate molte ore)
import time as _t
lt = _t.localtime()
midnight = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
assert om.due({"ultimo_sync_ts": midnight - 60}), "sincronizzato ieri alle 23:59: oggi va rifatto"
assert not om.due({"ultimo_sync_ts": midnight + 60}), "sincronizzato oggi a mezzanotte e un minuto: basta così"
assert om.due({}), "mai sincronizzato"

# ---- sito completo (60+ carte): il database si aggiorna da solo, con lo storico della patch
store.upsert("cards", [{"nome": "Glinda", "costo": 4, "attacco": 2, "vita": 3, "tipo": "creatura",
                        "testo": "Testo corretto a mano da Daniele."}])
fillers = "".join(card_tile(f"Filler {i}", 3, "2/2") for i in range(40))
SITE["/en/cards"] = cards_html.replace("</div></main>", fillers + "</div></main>").replace(
    "Huck Finn", "Huck Finn").replace('<span>Mana 2</span><span>2 Power, 2 Health</span><b>2/2</b><p>On Reveal: draw a card.</p>',
                                      '<span>Mana 2</span><span>2 Power, 2 Health</span><b>2/2</b><p>On Reveal: draw a card.</p>', 1)
SITE["/en/locations"] = page("<h1>Locations</h1><p>44 locations</p>" + "".join(
    f"<div><h2>{n}</h2><p>{r}</p><div><span>Damage</span><span>Barriers</span></div></div>" for n, r in
    [("\u201cHuman\u201d Cannon", "When you play a character here, destroy it and deal damage equal to its power to the opponent's barrier."),
     ("Amplifying Amphitheatre", "ALL damage here is doubled."), ("Anti-Magic Vault", "Characters here lose all abilities."),
     ("Arcane Leyline", "Both players get +2 mana this round."), ("Ballroom", "After combat, return a random character here to it's owner's hand for both players."),
     ("Blessed Grounds", "When a Good character is played here, it gets Shield."), ("Ashen Grove", "When you play a character here, discard your rightmost card then draw a card."),
     ("Crypt", "Characters here get +1 power."), ("Dock", "Spells cost 1 less here."), ("Forge", "After combat, characters here get +1/+1."),
     ("Garden", "Heal 2 to your barrier here at the end of the round.")]))
store.upsert("locations", [{"nome": "Dock", "testo": "Le spell costano 1 in meno qui (letta da me).", "rarita": "comune"}])
rep3 = om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=opener))
db = {c["nome"]: c for c in store.load("cards")}
assert db["Roo"]["costo"] == 2, "con il sito completo il costo si aggiorna"
assert db["Roo"]["storico"][-1]["modifiche"] == [{"campo": "costo", "prima": 3, "dopo": 2}], db["Roo"]["storico"]
assert any(c["carta"] == "Roo" for c in rep3["carte_cambiate"]) and rep3["patch"]
assert any(x.get("fonte") == "originsmeta" for x in store.load("patches"))
assert db["Glinda"]["testo"] == "Testo corretto a mano da Daniele.", "il testo scritto da Daniele resta"
assert db["Glinda"]["attacco"] == 2 and db["Glinda"]["costo"] == 2, db["Glinda"]  # numeri dal sito
assert "Filler 7" in db and db["Filler 7"]["attacco"] == 2
assert not rep3["differenze_carte"], rep3["differenze_carte"]
assert "carte cambiate" in om.summary_line(rep3)
locs = {x["nome"]: x for x in store.load("locations")}
assert len(locs) == 11 and locs["Amplifying Amphitheatre"]["testo"] == "ALL damage here is doubled."
assert "Human" in "".join(locs) and locs["Dock"]["testo"].endswith("(letta da me)."), "la location già scritta resta"
assert len(rep3["location_aggiunte"]) == 10
# una seconda volta non cambia nulla
rep4 = om.sync(force=True, fetcher=om.Fetcher(delay=0, opener=opener))
assert not rep4["carte_cambiate"] and not rep4["carte_aggiunte"] and not rep4["location_aggiunte"]
assert len(store.load("cards")[0].get("storico", [])) <= 1

# strumenti di Claude Code
try:
    from origins import server
except ImportError:  # libreria mcp assente: salto solo questa parte
    server = None
if server:
    fn = lambda f: getattr(f, "fn", f)  # noqa: E731
    cd = json.loads(fn(server.community_decks)(leggendaria="Van Helsing"))
    assert cd["mazzi"][0]["leggendaria"] == "Van Helsing"
    assert "Mulligan" in fn(server.community_deck)("SNIPER")
    assert "62.3" in fn(server.community_stats)("leggendarie")
    mr = json.loads(fn(server.meta_report)())
    assert mr["originsmeta"]["liste_per_leggendaria"]["Robin Hood"] >= 2
    assert all("OriginsMeta" not in a["nome"] for a in mr["avversari_di_daniele"])

shutil.rmtree(tmp, ignore_errors=True)
print("ORIGINSMETA OK")
