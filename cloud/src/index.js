// Cervello comune di BIG-BOB: Cloudflare Worker + D1.
//
//   GET  /v1/stato                 → controllo veloce (numeri principali)
//   GET  /v1/conoscenza            → la conoscenza fusa di tutti (regole, lezioni, carte, mazzi avversari, statistiche)
//   POST /v1/contributi            → un BIG-BOB invia ciò che ha imparato (anonimo)
//   /v1/admin/...                  → moderazione, solo con "Authorization: Bearer <ADMIN_KEY>"
//
// Variabili: CONFERMA_GIOCATORI (giocatori diversi per confermare, default 2). Segreti: ADMIN_KEY, SALE.

import {
  cardConsensus, firma, lessonConsensus, lessonScore, matchStats, ruleConsensus, ruleScore, SOGLIA_LEZIONI,
  SOGLIA_REGOLE, slug, validateContribution, clean,
} from "./merge.js";

const VERSIONE_API = 1;
const MAX_BODY = 256 * 1024;
const LIMITE_INVII_IP = 40;          // invii al giorno per indirizzo
const LIMITE_NUOVI_IP = 3;           // nuovi giocatori al giorno per indirizzo (contro i voti gonfiati)
const LIMITE_INVII_GIOCATORE = 20;   // invii al giorno per giocatore
const GIORNI_PARTITE = 45;
const GIORNI_CARTE = 120;
const RICALCOLA_DOPO_MIN = 15;

const now = () => new Date().toISOString();
const today = () => now().slice(0, 10);
const daysAgo = (d) => new Date(Date.now() - d * 86400000).toISOString();

function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*", ...headers },
  });
}

async function sha(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function soglia(env) {
  const n = parseInt(env.CONFERMA_GIOCATORI || "2", 10);
  return Number.isFinite(n) && n >= 1 ? n : 2;
}

function sameSecret(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

async function bump(env, chiave, limite) {
  const row = await env.DB.prepare(
    "INSERT INTO limiti (chiave, giorno, n) VALUES (?1, ?2, 1) ON CONFLICT (chiave, giorno) DO UPDATE SET n = n + 1 RETURNING n",
  ).bind(chiave, today()).first();
  return (row?.n ?? 1) <= limite;
}

async function runBatch(env, stmts) {
  for (let i = 0; i < stmts.length; i += 80) await env.DB.batch(stmts.slice(i, i + 80));
}

// ====================================================================== contributi

async function contribute(request, env, ctx) {
  const len = parseInt(request.headers.get("content-length") || "0", 10);
  if (len > MAX_BODY) return json({ errore: "contributo troppo grande" }, 413);
  const raw = await request.text();
  if (raw.length > MAX_BODY) return json({ errore: "contributo troppo grande" }, 413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ errore: "JSON non valido" }, 400);
  }
  const c = validateContribution(body);
  if (c.errore) return json(c, 400);

  const sale = env.SALE || "";
  const ip = request.headers.get("cf-connecting-ip") || "locale";
  const ipKey = "ip:" + (await sha(sale + ip + today())).slice(0, 24);
  if (!(await bump(env, ipKey, LIMITE_INVII_IP))) return json({ errore: "troppi invii oggi da questo indirizzo" }, 429);

  const chi = (await sha(sale + c.install)).slice(0, 24);
  const t = now();
  const known = await env.DB.prepare("SELECT bannato FROM contributori WHERE hash = ?1").bind(chi).first();
  if (known?.bannato) return json({ ok: true, ignorato: true });  // niente spiegazioni a chi è bloccato
  if (!known) {
    if (!(await bump(env, "nuovi:" + ipKey, LIMITE_NUOVI_IP))) {
      return json({ errore: "troppi giocatori nuovi oggi da questo indirizzo" }, 429);
    }
    await env.DB.prepare("INSERT INTO contributori (hash, primo, ultimo, invii, versione) VALUES (?1, ?2, ?2, 0, ?3)")
      .bind(chi, t, c.versione).run();
  }
  if (!(await bump(env, "chi:" + chi, LIMITE_INVII_GIOCATORE))) return json({ errore: "troppi invii oggi" }, 429);

  const stmts = [];

  const patchStmts = [];
  const res = { regole: 0, lezioni: 0, carte: 0, location: 0, partite: 0, nuove_regole: 0, nuove_lezioni: 0 };

  // mappe già note di questo giocatore (cid locale → gruppo)
  const mapRows = (await env.DB.prepare("SELECT tipo, cid, gruppo_id FROM mappe WHERE contributore = ?1")
    .bind(chi).all()).results || [];
  const mapped = new Map(mapRows.map((r) => [r.tipo + ":" + r.cid, r.gruppo_id]));

  // ---- regole
  if (c.regole.length) {
    const groups = (await env.DB.prepare("SELECT id, categoria, firma FROM regole WHERE nascosta = 0").all()).results || [];
    for (const r of c.regole) {
      const f = firma(r.testo);
      let gid = mapped.get("regola:" + r.cid);
      if (gid === undefined) {
        let best = null, bestScore = 0;
        for (const g of groups) {
          const s = ruleScore(f, g.firma, g.categoria === r.categoria);
          if (s > bestScore) [best, bestScore] = [g, s];
        }
        if (best && bestScore >= SOGLIA_REGOLE) gid = best.id;
        else {
          const row = await env.DB.prepare(
            "INSERT INTO regole (categoria, testo, firma, creata) VALUES (?1, ?2, ?3, ?4) RETURNING id",
          ).bind(r.categoria, r.testo, f, t).first();
          gid = row.id;
          groups.push({ id: gid, categoria: r.categoria, firma: f });
          res.nuove_regole++;
        }
        mapped.set("regola:" + r.cid, gid);
        stmts.push(env.DB.prepare("INSERT OR REPLACE INTO mappe (contributore, tipo, cid, gruppo_id) VALUES (?1, 'regola', ?2, ?3)")
          .bind(chi, r.cid, gid));
      }
      stmts.push(env.DB.prepare(
        "INSERT OR REPLACE INTO regole_voti (regola_id, contributore, stato, testo, prove, aggiornato) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
      ).bind(gid, chi, r.stato, r.testo, JSON.stringify(r.prove), t));
      if (c.patch) patchStmts.push(env.DB.prepare(
        "INSERT OR REPLACE INTO voti_patch (tipo, gruppo_id, contributore, patch) VALUES ('regola', ?1, ?2, ?3)",
      ).bind(gid, chi, c.patch));
      res.regole++;
    }
  }

  // ---- lezioni
  if (c.lezioni.length) {
    const groups = ((await env.DB.prepare("SELECT id, tipo, firma, carte FROM lezioni WHERE nascosta = 0").all()).results || [])
      .map((g) => ({ ...g, carte: JSON.parse(g.carte || "[]") }));
    for (const l of c.lezioni) {
      const f = firma(l.testo);
      let gid = mapped.get("lezione:" + l.cid);
      if (gid === undefined) {
        let best = null, bestScore = 0;
        for (const g of groups) {
          if (g.tipo !== l.tipo) continue;
          const s = lessonScore(f, l.carte, g.firma, g.carte);
          if (s > bestScore) [best, bestScore] = [g, s];
        }
        if (best && bestScore >= SOGLIA_LEZIONI) {
          gid = best.id;
          const merged = [...new Set([...best.carte, ...l.carte])].slice(0, 12);
          if (merged.length !== best.carte.length) {
            best.carte = merged;
            stmts.push(env.DB.prepare("UPDATE lezioni SET carte = ?1 WHERE id = ?2").bind(JSON.stringify(merged), gid));
          }
        } else {
          const row = await env.DB.prepare(
            "INSERT INTO lezioni (tipo, testo, firma, carte, creata) VALUES (?1, ?2, ?3, ?4, ?5) RETURNING id",
          ).bind(l.tipo, l.testo, f, JSON.stringify(l.carte), t).first();
          gid = row.id;
          groups.push({ id: gid, tipo: l.tipo, firma: f, carte: l.carte });
          res.nuove_lezioni++;
        }
        mapped.set("lezione:" + l.cid, gid);
        stmts.push(env.DB.prepare("INSERT OR REPLACE INTO mappe (contributore, tipo, cid, gruppo_id) VALUES (?1, 'lezione', ?2, ?3)")
          .bind(chi, l.cid, gid));
      }
      stmts.push(env.DB.prepare(
        "INSERT OR REPLACE INTO lezioni_voti (lezione_id, contributore, stato, volte, testo, aggiornato) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
      ).bind(gid, chi, l.stato, l.volte, l.testo, t));
      if (c.patch) patchStmts.push(env.DB.prepare(
        "INSERT OR REPLACE INTO voti_patch (tipo, gruppo_id, contributore, patch) VALUES ('lezione', ?1, ?2, ?3)",
      ).bind(gid, chi, c.patch));
      res.lezioni++;
    }
  }

  // ---- carte e location
  for (const k of ["carte", "location"]) {
    for (const x of c[k]) {
      stmts.push(env.DB.prepare(
        "INSERT OR REPLACE INTO carte (tipo, chiave, contributore, dati, aggiornato) VALUES (?1, ?2, ?3, ?4, ?5)",
      ).bind(x.tipo, x.chiave, chi, JSON.stringify(x.dati), t));
      res[k]++;
    }
  }

  // ---- partite
  for (const p of c.partite) {
    stmts.push(env.DB.prepare(
      `INSERT OR IGNORE INTO partite (contributore, cid, data, patch, mia_leggendaria, avv_leggendaria, risultato, round,
        mie_carte, avv_carte, ricevuta) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)`,
    ).bind(chi, p.cid, p.data || t.slice(0, 10), p.patch, p.mia_leggendaria, p.avv_leggendaria, p.risultato, p.round,
      JSON.stringify(p.mie_carte), JSON.stringify(p.avv_carte), t));
    res.partite++;
  }

  stmts.push(env.DB.prepare("UPDATE contributori SET ultimo = ?1, invii = invii + 1, versione = ?2 WHERE hash = ?3")
    .bind(t, c.versione, chi));
  await runBatch(env, stmts);
  // la patch dei voti a parte: se la tabella non c'è ancora (server pubblicato prima dello schema) l'invio vale lo stesso
  if (patchStmts.length) await env.DB.batch(patchStmts).catch(() => {});

  const last = await env.DB.prepare("SELECT creato FROM riassunto WHERE id = 1").first();
  if (!last || Date.parse(last.creato) < Date.now() - RICALCOLA_DOPO_MIN * 60000) ctx.waitUntil(rebuild(env));
  return json({ ok: true, ricevuti: res });
}

// ====================================================================== riassunto

async function rebuild(env) {
  const S = soglia(env);
  const all = async (sql, ...args) => (await env.DB.prepare(sql).bind(...args).all()).results || [];
  const banned = new Set((await all("SELECT hash FROM contributori WHERE bannato = 1")).map((r) => r.hash));
  const ok = (r) => !banned.has(r.contributore);
  const hidden = new Set((await all("SELECT tipo, chiave FROM nascosti")).map((r) => r.tipo + ":" + r.chiave));
  // patch più votata per ogni regola/lezione (per pesare le voci di patch vecchie)
  const patchVotes = new Map();
  for (const v of (await all("SELECT tipo, gruppo_id, contributore, patch FROM voti_patch").catch(() => [])).filter(ok)) {
    const k = v.tipo + ":" + v.gruppo_id;
    const m = patchVotes.get(k) || patchVotes.set(k, new Map()).get(k);
    m.set(v.patch, (m.get(v.patch) || 0) + 1);
  }
  const patchOf = (tipo, id) => {
    const m = patchVotes.get(tipo + ":" + id);
    if (!m) return null;
    return [...m.entries()].sort((a, b) => b[1] - a[1] || b[0].localeCompare(a[0]))[0][0];
  };
  const latest = (vs) => vs.reduce((a, v) => (v.aggiornato > a ? v.aggiornato : a), "");

  // regole
  const rv = (await all("SELECT regola_id, contributore, stato, prove, aggiornato FROM regole_voti")).filter(ok);
  const votesByRule = new Map();
  for (const v of rv) (votesByRule.get(v.regola_id) || votesByRule.set(v.regola_id, []).get(v.regola_id)).push(v);
  const regole = [];
  for (const g of await all("SELECT id, categoria, testo FROM regole WHERE nascosta = 0")) {
    const vs = votesByRule.get(g.id);
    if (!vs?.length) continue;
    const cons = ruleConsensus(vs.map((v) => v.stato), S);
    const prove = [];
    for (const v of vs.sort((a, b) => b.aggiornato.localeCompare(a.aggiornato))) {
      for (const p of JSON.parse(v.prove || "[]")) if (prove.length < 3 && !prove.includes(p)) prove.push(p);
    }
    regole.push({ id: "C" + g.id, categoria: g.categoria, testo: g.testo, ...cons, prove, voto: latest(vs),
      patch: patchOf("regola", g.id) });
  }
  regole.sort((a, b) => b.giocatori - a.giocatori || a.id.localeCompare(b.id));

  // lezioni
  const lv = (await all("SELECT lezione_id, contributore, stato, volte, aggiornato FROM lezioni_voti")).filter(ok);
  const votesByLesson = new Map();
  for (const v of lv) (votesByLesson.get(v.lezione_id) || votesByLesson.set(v.lezione_id, []).get(v.lezione_id)).push(v);
  const lezioni = [];
  for (const g of await all("SELECT id, tipo, testo, carte FROM lezioni WHERE nascosta = 0")) {
    const vs = votesByLesson.get(g.id);
    if (!vs?.length) continue;
    lezioni.push({ id: "CL" + g.id, tipo: g.tipo, testo: g.testo, carte: JSON.parse(g.carte || "[]"),
      ...lessonConsensus(vs, S), voto: latest(vs), patch: patchOf("lezione", g.id) });
  }
  lezioni.sort((a, b) => b.sostengono - a.sostengono || b.volte - a.volte);

  // carte e location
  const cr = (await all("SELECT tipo, chiave, contributore, dati, aggiornato FROM carte WHERE aggiornato >= ?1", daysAgo(GIORNI_CARTE)))
    .filter(ok).filter((r) => !hidden.has(r.tipo + ":" + r.chiave));
  const byCard = new Map();
  for (const r of cr) {
    const k = r.tipo + ":" + r.chiave;
    const e = byCard.get(k) || byCard.set(k, { tipo: r.tipo, chiave: r.chiave, prop: [], agg: "" }).get(k);
    e.prop.push(JSON.parse(r.dati));
    if (r.aggiornato > e.agg) e.agg = r.aggiornato;
  }
  const carte = [], location = [];
  for (const e of byCard.values()) {
    const cons = cardConsensus(e.prop, S);
    (e.tipo === "location" ? location : carte).push({ chiave: e.chiave, ...cons, voto: e.agg });
  }

  // partite
  const pr = (await all(
    "SELECT contributore, mia_leggendaria, avv_leggendaria, risultato, mie_carte, avv_carte FROM partite WHERE ricevuta >= ?1",
    daysAgo(GIORNI_PARTITE),
  )).filter(ok).map((r) => ({ ...r, mie_carte: JSON.parse(r.mie_carte || "[]"), avv_carte: JSON.parse(r.avv_carte || "[]") }));
  const stats = matchStats(pr);

  const giocatori = (await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM contributori WHERE bannato = 0 AND ultimo >= ?1",
  ).bind(daysAgo(90)).first())?.n || 0;

  // per lo scarico incrementale: "agg" cambia quando cambia il CONTENUTO di una voce (nuovi voti, testo modificato
  // dall'amministratore, unione, giocatore bloccato, soglia diversa), non solo quando arriva un voto
  const creato = now();
  const prevRow = await env.DB.prepare("SELECT json FROM riassunto WHERE id = 1").first();
  const prev = prevRow ? JSON.parse(prevRow.json) : {};
  for (const [k, idk] of [["regole", "id"], ["lezioni", "id"], ["carte", "chiave"], ["location", "chiave"]]) {
    const old = new Map((prev[k] || []).map((x) => [x[idk], x]));
    const items = { regole, lezioni, carte, location }[k];
    for (const x of items) {
      const { agg: _a, h: _h, ...body } = x;
      x.h = (await sha(JSON.stringify(body))).slice(0, 16);
      const o = old.get(x[idk]);
      x.agg = o && o.h === x.h ? o.agg : creato;
    }
  }
  const out = {
    api: VERSIONE_API, creato, soglia_conferma: S, giocatori, giorni_partite: GIORNI_PARTITE,
    regole, lezioni, carte, location, ...stats,
  };
  await env.DB.batch([
    env.DB.prepare("INSERT OR REPLACE INTO riassunto (id, json, creato) VALUES (1, ?1, ?2)").bind(JSON.stringify(out), out.creato),
    env.DB.prepare("DELETE FROM limiti WHERE giorno < ?1").bind(daysAgo(2).slice(0, 10)),
  ]);
  return out;
}

async function knowledge(request, env, ctx) {
  let row = await env.DB.prepare("SELECT json, creato FROM riassunto WHERE id = 1").first();
  if (!row) {
    const out = await rebuild(env);
    row = { json: JSON.stringify(out), creato: out.creato };
  }
  const etag = `"${row.creato}"`;
  if (request.headers.get("if-none-match") === etag) return new Response(null, { status: 304, headers: { etag } });
  // scarico incrementale: ?da=<creato dell'ultimo scarico> → solo le voci cambiate da allora, più gli id di tutte
  // (così il client toglie quelle sparite) e le statistiche intere
  const da = new URL(request.url).searchParams.get("da");
  if (da && !Number.isNaN(Date.parse(da))) {
    const full = JSON.parse(row.json);
    const out = { ...full, delta: true, da, ids: {} };
    for (const [k, idk] of [["regole", "id"], ["lezioni", "id"], ["carte", "chiave"], ["location", "chiave"]]) {
      const items = full[k] || [];
      out.ids[k] = items.map((x) => x[idk]);
      out[k] = items.filter((x) => !x.agg || x.agg > da);  // agg = creato del riassunto in cui la voce è cambiata
    }
    return new Response(JSON.stringify(out), {
      headers: { "content-type": "application/json; charset=utf-8", etag, "cache-control": "private, max-age=60" },
    });
  }
  return new Response(row.json, {
    headers: { "content-type": "application/json; charset=utf-8", etag, "cache-control": "public, max-age=300",
      "access-control-allow-origin": "*" },
  });
}

async function status(env) {
  const row = await env.DB.prepare("SELECT creato, json FROM riassunto WHERE id = 1").first();
  const s = row ? JSON.parse(row.json) : null;
  return json({ ok: true, api: VERSIONE_API, aggiornato: row?.creato || null, giocatori: s?.giocatori ?? 0,
    regole: s?.regole?.length ?? 0, lezioni: s?.lezioni?.length ?? 0, carte: s?.carte?.length ?? 0,
    partite: s?.partite ?? 0 });
}

// ====================================================================== amministrazione

async function admin(path, request, env) {
  const auth = request.headers.get("authorization") || "";
  if (!env.ADMIN_KEY || !sameSecret(auth.replace(/^Bearer\s+/i, ""), env.ADMIN_KEY)) {
    return json({ errore: "non autorizzato" }, 401);
  }
  const body = request.method === "POST" ? await request.json().catch(() => ({})) : {};
  const all = async (sql, ...args) => (await env.DB.prepare(sql).bind(...args).all()).results || [];
  const idNum = (s) => parseInt(String(s || "").replace(/^[A-Z]+/i, ""), 10);

  if (path === "panoramica") {
    return json({
      contributori: await all("SELECT hash, primo, ultimo, invii, versione, bannato FROM contributori ORDER BY ultimo DESC LIMIT 50"),
      regole_recenti: await all(`SELECT r.id, r.categoria, r.testo, r.nascosta, COUNT(v.contributore) AS giocatori
        FROM regole r LEFT JOIN regole_voti v ON v.regola_id = r.id GROUP BY r.id ORDER BY r.id DESC LIMIT 40`),
      lezioni_recenti: await all(`SELECT l.id, l.tipo, l.testo, l.carte, l.nascosta, COUNT(v.contributore) AS giocatori
        FROM lezioni l LEFT JOIN lezioni_voti v ON v.lezione_id = l.id GROUP BY l.id ORDER BY l.id DESC LIMIT 40`),
      nascosti: await all("SELECT * FROM nascosti ORDER BY data DESC LIMIT 50"),
      partite: (await env.DB.prepare("SELECT COUNT(*) AS n FROM partite").first())?.n || 0,
    });
  }
  if (path === "regola" || path === "lezione") {
    const tab = path === "regola" ? "regole" : "lezioni", vt = path === "regola" ? "regole_voti" : "lezioni_voti";
    const fk = path === "regola" ? "regola_id" : "lezione_id";
    const id = idNum(body.id ?? new URL(request.url).searchParams.get("id"));
    if (!id) return json({ errore: "serve id" }, 400);
    if (request.method === "POST") {
      if (body.testo) {
        const testo = clean(body.testo, 400);
        await env.DB.prepare(`UPDATE ${tab} SET testo = ?1, firma = ?2 WHERE id = ?3`).bind(testo, firma(testo), id).run();
      }
      if (body.nascosta !== undefined) {
        await env.DB.prepare(`UPDATE ${tab} SET nascosta = ?1 WHERE id = ?2`).bind(body.nascosta ? 1 : 0, id).run();
      }
      if (body.unisci_in) {  // sposta i voti in un altro gruppo (stessa regola scritta in modo diverso)
        const to = idNum(body.unisci_in);
        await env.DB.batch([
          env.DB.prepare(`INSERT OR IGNORE INTO ${vt} SELECT ?1, contributore, stato, ${path === "regola" ? "testo, prove" : "volte, testo"}, aggiornato FROM ${vt} WHERE ${fk} = ?2`).bind(to, id),
          env.DB.prepare(`DELETE FROM ${vt} WHERE ${fk} = ?1`).bind(id),
          env.DB.prepare("UPDATE mappe SET gruppo_id = ?1 WHERE tipo = ?2 AND gruppo_id = ?3").bind(to, path, id),
          env.DB.prepare(`UPDATE ${tab} SET nascosta = 1 WHERE id = ?1`).bind(id),
        ]);
      }
    }
    return json({
      gruppo: await env.DB.prepare(`SELECT * FROM ${tab} WHERE id = ?1`).bind(id).first(),
      voti: await all(`SELECT * FROM ${vt} WHERE ${fk} = ?1`, id),
    });
  }
  if (path === "nascondi" || path === "mostra") {
    const tipo = String(body.tipo || ""), chiave = slug(body.chiave || body.nome || "");
    if (!["carta", "location"].includes(tipo) || !chiave) return json({ errore: "servono tipo (carta|location) e chiave" }, 400);
    if (path === "nascondi") {
      await env.DB.prepare("INSERT OR REPLACE INTO nascosti (tipo, chiave, motivo, data) VALUES (?1, ?2, ?3, ?4)")
        .bind(tipo, chiave, clean(body.motivo, 200), now()).run();
    } else {
      await env.DB.prepare("DELETE FROM nascosti WHERE tipo = ?1 AND chiave = ?2").bind(tipo, chiave).run();
    }
    return json({ ok: true, tipo, chiave, nascosta: path === "nascondi" });
  }
  if (path === "banna") {
    const hash = String(body.contributore || "");
    if (!/^[a-f0-9]{8,64}$/.test(hash)) return json({ errore: "serve contributore (hash)" }, 400);
    const r = await env.DB.prepare("UPDATE contributori SET bannato = ?1 WHERE hash LIKE ?2 || '%'")
      .bind(body.bannato === false ? 0 : 1, hash).run();
    return json({ ok: true, modificati: r.meta?.changes ?? 0 });
  }
  if (path === "ricalcola") {
    const out = await rebuild(env);
    return json({ ok: true, creato: out.creato, regole: out.regole.length, lezioni: out.lezioni.length });
  }
  return json({ errore: "comando sconosciuto" }, 404);
}

// ====================================================================== router

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");
    try {
      if (request.method === "OPTIONS") {
        return new Response(null, { headers: { "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, POST", "access-control-allow-headers": "content-type, authorization" } });
      }
      if (path === "" || path === "/v1/stato") return status(env);
      if (path === "/v1/conoscenza" && request.method === "GET") return knowledge(request, env, ctx);
      if (path === "/v1/contributi" && request.method === "POST") return contribute(request, env, ctx);
      if (path.startsWith("/v1/admin/")) return admin(path.slice(10), request, env);
      return json({ errore: "non trovato" }, 404);
    } catch (e) {
      console.error(e);
      return json({ errore: "errore del server" }, 500);
    }
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(rebuild(env));
  },
};
