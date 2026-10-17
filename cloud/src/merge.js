// Logica pura del cervello comune (niente database qui, così si prova con node --test).
// La normalizzazione dei testi è identica a quella di origins/cervello.py: se cambi qui, cambia anche lì.

export const STATI_REGOLE = ["domanda", "ipotesi", "probabile", "confermata", "smentita"];
export const STATI_LEZIONI = ["ipotesi", "confermata", "smentita"];
export const TIPI_LEZIONI = ["mossa_avversaria", "interazione", "errore_coach", "mossa_vincente", "strategia"];
export const CAMPI_CARTA = ["nome", "testo", "costo", "attacco", "vita", "tipo", "rarita", "potere", "leggendaria",
  "potere_leggendario", "tag", "regola"];

const STOP = new Set(("che per con non una uno del della delle dei degli dal dalla dai dalle nel nella nei nelle sul " +
  "sulla sui sulle alla alle allo agli all gli the and for with from that this poi anche come quando sempre solo " +
  "sono essere viene vengono piu suo sua suoi sue tuo tua tue tuoi mio mia miei mie quella quello quelle quelli " +
  "questa questo queste questi ogni dopo prima cosa cui chi hai hanno essa esso loro").split(" "));

export function tokens(text) {
  const t = String(text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
  if (!t) return [];
  const out = new Set();
  for (const w of t.split(" ")) {
    if (/^\d+$/.test(w) || (w.length >= 3 && !STOP.has(w))) out.add(w);
  }
  return [...out].sort();
}

export function firma(text) {
  return tokens(text).join(" ");
}

export function slug(name) {
  return String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function numbers(toks) {
  return toks.filter((w) => /^\d+$/.test(w)).sort().join(",");
}

export function jaccard(a, b) {
  const A = new Set(a), B = new Set(b);
  if (!A.size && !B.size) return 1;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / (A.size + B.size - inter);
}

// Quanto due regole sono "la stessa": numeri diversi = regole diverse (20 ≠ 40).
export function ruleScore(firmaA, firmaB, sameCategory) {
  const a = firmaA ? firmaA.split(" ") : [], b = firmaB ? firmaB.split(" ") : [];
  const na = numbers(a), nb = numbers(b);
  if (na !== nb) return 0;
  return jaccard(a, b) + (sameCategory ? 0.05 : 0);
}
export const SOGLIA_REGOLE = 0.62;

export function lessonScore(firmaA, carteA, firmaB, carteB) {
  const ca = new Set(carteA.map(slug)), cb = new Set(carteB.map(slug));
  let inter = 0;
  for (const x of ca) if (cb.has(x)) inter++;
  if (ca.size && cb.size && !inter) return 0;
  const overlap = (ca.size || cb.size) ? inter / (ca.size + cb.size - inter) : 1;
  const a = firmaA ? firmaA.split(" ") : [], b = firmaB ? firmaB.split(" ") : [];
  if (numbers(a) !== numbers(b)) return 0;
  return 0.5 * overlap + 0.5 * jaccard(a, b);
}
export const SOGLIA_LEZIONI = 0.6;

// Pulizia dei testi in arrivo: niente link, email, caratteri di controllo; lunghezza massima.
export function clean(text, max = 400) {
  return String(text ?? "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, "")
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}

export function cleanList(list, maxItems = 30, maxLen = 60) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const x of list) {
    const c = clean(x, maxLen);
    if (c && !out.includes(c)) out.push(c);
    if (out.length >= maxItems) break;
  }
  return out;
}

// ------------------------------------------------------------------ consenso

export function ruleConsensus(votes, soglia) {
  const n = (s) => votes.filter((v) => v === s).length;
  const conf = n("confermata"), smen = n("smentita"), prob = n("probabile"), ipo = n("ipotesi"), dom = n("domanda");
  let stato = "ipotesi";
  if (smen >= soglia && smen > conf) stato = "smentita";
  else if (conf >= soglia && conf > smen) stato = "confermata";
  else if (conf + prob > 0 && conf + prob > smen) stato = "probabile";
  else if (dom === votes.length) stato = "domanda";
  else if (smen > 0 && smen >= conf + prob + ipo) stato = "contestata";
  return { stato, conferme: conf, probabili: prob, ipotesi: ipo, smentite: smen, domande: dom, giocatori: votes.length };
}

export function lessonConsensus(votes, soglia) {
  // votes: [{stato, volte}]
  const smen = votes.filter((v) => v.stato === "smentita").length;
  const sost = votes.length - smen;
  const conf = votes.filter((v) => v.stato === "confermata").length;
  let stato = "ipotesi";
  if (smen >= soglia && smen > sost) stato = "smentita";
  else if (sost >= soglia && sost > smen) stato = "confermata";
  else if (smen > 0 && smen >= sost) stato = "contestata";
  const volte = votes.reduce((s, v) => s + (v.stato === "smentita" ? 0 : Math.max(1, v.volte || 1)), 0);
  return { stato, giocatori: votes.length, sostengono: sost, confermata_da: conf, smentite: smen, volte };
}

function normValue(v) {
  return typeof v === "string" ? v.replace(/\s+/g, " ").trim().toLowerCase() : JSON.stringify(v);
}

// Per ogni campo della carta: il valore indicato dal maggior numero di giocatori. "concorde" se almeno `soglia`
// giocatori lo indicano e sono più di quelli che indicano qualunque altro valore.
export function cardConsensus(proposals, soglia) {
  const fields = {};
  for (const p of proposals) {
    for (const [k, v] of Object.entries(p)) {
      if (v === null || v === undefined || v === "" || k === "nome") continue;
      const key = normValue(v);
      fields[k] ??= {};
      fields[k][key] ??= { valore: v, giocatori: 0 };
      fields[k][key].giocatori++;
    }
  }
  const out = {};
  for (const [k, vals] of Object.entries(fields)) {
    const sorted = Object.values(vals).sort((a, b) => b.giocatori - a.giocatori);
    const best = sorted[0], second = sorted[1];
    out[k] = { valore: best.valore, giocatori: best.giocatori, alternative: sorted.length - 1,
      concorde: best.giocatori >= soglia && (!second || best.giocatori > second.giocatori) };
  }
  // il nome più usato
  const names = {};
  for (const p of proposals) if (p.nome) names[p.nome] = (names[p.nome] || 0) + 1;
  const nome = Object.entries(names).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
  return { nome, campi: out, giocatori: proposals.length };
}

// ------------------------------------------------------------------ partite

const win = (r) => /^v/i.test(r || "");

export function matchStats(rows, { minMazzo = 3, minMatchup = 3, minFreq = 0.15 } = {}) {
  // rows: [{contributore, mia_leggendaria, avv_leggendaria, risultato, mie_carte[], avv_carte[]}]
  const byOpp = new Map(), byMine = new Map(), mu = new Map();
  for (const r of rows) {
    if (r.avv_leggendaria) {
      const e = byOpp.get(r.avv_leggendaria) || { leggendaria: r.avv_leggendaria, partite: 0, vinte: 0,
        giocatori: new Set(), carte: new Map() };
      e.partite++;
      if (win(r.risultato)) e.vinte++;
      e.giocatori.add(r.contributore);
      for (const c of new Set(r.avv_carte || [])) {
        if (slug(c) === slug(r.avv_leggendaria)) continue;
        e.carte.set(c, (e.carte.get(c) || 0) + 1);
      }
      byOpp.set(r.avv_leggendaria, e);
    }
    if (r.mia_leggendaria) {
      const e = byMine.get(r.mia_leggendaria) || { leggendaria: r.mia_leggendaria, partite: 0, vinte: 0,
        giocatori: new Set() };
      e.partite++;
      if (win(r.risultato)) e.vinte++;
      e.giocatori.add(r.contributore);
      byMine.set(r.mia_leggendaria, e);
    }
    if (r.mia_leggendaria && r.avv_leggendaria) {
      const k = r.mia_leggendaria + "\u0000" + r.avv_leggendaria;
      const e = mu.get(k) || { mia: r.mia_leggendaria, avv: r.avv_leggendaria, partite: 0, vinte: 0 };
      e.partite++;
      if (win(r.risultato)) e.vinte++;
      mu.set(k, e);
    }
  }
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : null);
  const mazzi = [...byOpp.values()].filter((e) => e.partite >= minMazzo).map((e) => ({
    leggendaria: e.leggendaria, partite: e.partite, giocatori: e.giocatori.size,
    winrate_contro: pct(e.vinte, e.partite),
    carte: [...e.carte.entries()].map(([nome, n]) => ({ nome, freq: Math.round((n / e.partite) * 100) / 100 }))
      .filter((c) => c.freq >= minFreq).sort((a, b) => b.freq - a.freq || a.nome.localeCompare(b.nome)).slice(0, 20),
  })).sort((a, b) => b.partite - a.partite);
  const leggendarie = [...byMine.values()].map((e) => ({ leggendaria: e.leggendaria, partite: e.partite,
    giocatori: e.giocatori.size, winrate: pct(e.vinte, e.partite) })).sort((a, b) => b.partite - a.partite);
  const matchup = [...mu.values()].filter((e) => e.partite >= minMatchup)
    .map((e) => ({ mia: e.mia, avv: e.avv, partite: e.partite, winrate: pct(e.vinte, e.partite) }))
    .sort((a, b) => b.partite - a.partite);
  return { mazzi_avversari: mazzi, leggendarie, matchup, partite: rows.length };
}

// ------------------------------------------------------------------ validazione dei contributi

export const LIMITI = { regole: 300, lezioni: 300, carte: 400, location: 120, partite: 100 };

export function validateContribution(body) {
  if (!body || typeof body !== "object") return { errore: "corpo non valido" };
  const install = String(body.install || "");
  if (!/^[a-f0-9]{32,64}$/.test(install)) return { errore: "install non valido" };
  const out = { install, versione: clean(body.versione, 40), patch: clean(body.patch, 40),
    regole: [], lezioni: [], carte: [], location: [], partite: [] };
  for (const k of Object.keys(LIMITI)) {
    if (body[k] !== undefined && !Array.isArray(body[k])) return { errore: `${k} deve essere una lista` };
    if ((body[k] || []).length > LIMITI[k]) return { errore: `troppi elementi in ${k} (max ${LIMITI[k]})` };
  }
  for (const r of body.regole || []) {
    const testo = clean(r?.testo, 400), cid = clean(r?.cid, 40);
    if (!testo || !cid || !STATI_REGOLE.includes(r?.stato)) continue;
    out.regole.push({ cid, testo, categoria: clean(r.categoria, 30) || "altro", stato: r.stato,
      prove: cleanList(r.prove, 3, 300) });
  }
  for (const l of body.lezioni || []) {
    const testo = clean(l?.testo, 400), cid = clean(l?.cid, 40);
    if (!testo || !cid || !TIPI_LEZIONI.includes(l?.tipo) || !STATI_LEZIONI.includes(l?.stato)) continue;
    out.lezioni.push({ cid, testo, tipo: l.tipo, stato: l.stato, carte: cleanList(l.carte, 12, 60),
      volte: Math.max(1, Math.min(50, parseInt(l.volte, 10) || 1)) });
  }
  for (const [k, tipo] of [["carte", "carta"], ["location", "location"]]) {
    for (const c of body[k] || []) {
      const nome = clean(c?.nome, 60);
      if (!nome) continue;
      const dati = { nome };
      for (const f of CAMPI_CARTA) {
        if (f === "nome" || c[f] === undefined || c[f] === null || c[f] === "") continue;
        const v = c[f];
        if (typeof v === "number" && Number.isFinite(v) && v >= -1 && v <= 99) dati[f] = Math.round(v);
        else if (typeof v === "string") dati[f] = clean(v, 500);
        else if (typeof v === "boolean") dati[f] = v;
        else if (Array.isArray(v)) dati[f] = cleanList(v, 10, 40);
      }
      if (Object.keys(dati).length > 1) out[k].push({ tipo, chiave: slug(nome), dati });
    }
  }
  for (const p of body.partite || []) {
    const cid = clean(p?.cid, 40);
    if (!cid) continue;
    const ris = /^v/i.test(p.risultato || "") ? "vittoria" : /^s/i.test(p.risultato || "") ? "sconfitta"
      : /^p/i.test(p.risultato || "") ? "pareggio" : "";
    if (!ris) continue;
    out.partite.push({ cid, data: clean(p.data, 20), patch: clean(p.patch, 40) || out.patch,
      mia_leggendaria: clean(p.mia_leggendaria, 60), avv_leggendaria: clean(p.avv_leggendaria, 60), risultato: ris,
      round: Math.max(0, Math.min(40, parseInt(p.round, 10) || 0)),
      mie_carte: cleanList(p.mie_carte, 13, 60), avv_carte: cleanList(p.avv_carte, 25, 60) });
  }
  return out;
}
