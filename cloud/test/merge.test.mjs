import test from "node:test";
import assert from "node:assert/strict";
import {
  cardConsensus, clean, firma, lessonConsensus, lessonScore, matchStats, ruleConsensus, ruleScore, SOGLIA_LEZIONI,
  SOGLIA_REGOLE, tokens, validateContribution,
} from "../src/merge.js";

test("tokens: accenti, stopword, numeri", () => {
  assert.deepEqual(tokens("Una barrier a 0 si rigenera a 40 e il danno in eccesso non passa"),
    ["0", "40", "barrier", "danno", "eccesso", "passa", "rigenera"]);
  assert.deepEqual(tokens("Più città"), ["citta"]);
});

test("regole: stessa regola scritta in modo diverso si unisce, numeri diversi no", () => {
  const a = firma("Una barrier a 0 si rigenera a 40 e il danno in eccesso non passa");
  const b = firma("Quando una barrier arriva a 0 si rigenera a 40; il danno in eccesso non passa");
  const c = firma("Una barrier a 0 si rigenera a 20 e il danno in eccesso non passa");
  assert.ok(ruleScore(a, b, true) >= SOGLIA_REGOLE);
  assert.equal(ruleScore(a, c, true), 0);
  assert.ok(ruleScore(a, firma("Le spell non occupano spazi nelle corsie"), true) < SOGLIA_REGOLE);
});

test("lezioni: carte diverse = lezioni diverse", () => {
  const f = firma("Se Dracula ha 3+ mana aspettati Brides al centro");
  assert.ok(lessonScore(f, ["Brides of Dracula"], f, ["Brides of Dracula", "Garlic"]) >= SOGLIA_LEZIONI);
  assert.equal(lessonScore(f, ["Brides of Dracula"], f, ["Marian"]), 0);
});

test("consenso regole", () => {
  assert.equal(ruleConsensus(["confermata"], 2).stato, "probabile");
  assert.equal(ruleConsensus(["confermata", "confermata"], 2).stato, "confermata");
  assert.equal(ruleConsensus(["confermata", "smentita", "smentita"], 2).stato, "smentita");
  assert.equal(ruleConsensus(["domanda", "domanda"], 2).stato, "domanda");
  assert.equal(ruleConsensus(["ipotesi", "smentita"], 2).stato, "contestata");
  assert.equal(ruleConsensus(["ipotesi"], 2).stato, "ipotesi");
});

test("consenso lezioni", () => {
  assert.equal(lessonConsensus([{ stato: "ipotesi", volte: 1 }], 2).stato, "ipotesi");
  const two = lessonConsensus([{ stato: "ipotesi", volte: 1 }, { stato: "confermata", volte: 3 }], 2);
  assert.equal(two.stato, "confermata");
  assert.equal(two.volte, 4);
  assert.equal(lessonConsensus([{ stato: "smentita" }, { stato: "smentita" }, { stato: "ipotesi" }], 2).stato, "smentita");
});

test("consenso carte: vale il testo indicato da più giocatori", () => {
  const r = cardConsensus([
    { nome: "Marian", testo: "On Reveal: +2 vita", costo: 3 },
    { nome: "Marian", testo: "on reveal:  +2 vita", costo: 3 },
    { nome: "Marian", testo: "On Reveal: +3 vita", costo: 4 },
  ], 2);
  assert.equal(r.campi.testo.giocatori, 2);
  assert.equal(r.campi.testo.concorde, true);
  assert.equal(r.campi.costo.valore, 3);
  const one = cardConsensus([{ nome: "X", testo: "a" }], 2);
  assert.equal(one.campi.testo.concorde, false);
});

test("statistiche delle partite", () => {
  const rows = [];
  for (let i = 0; i < 4; i++) {
    rows.push({ contributore: "a" + (i % 2), mia_leggendaria: "Robin Hood", avv_leggendaria: "Dracula",
      risultato: i < 3 ? "vittoria" : "sconfitta", avv_carte: ["Dracula", "Garlic", i % 2 ? "Bat" : "Garlic"] });
  }
  const s = matchStats(rows);
  assert.equal(s.mazzi_avversari[0].leggendaria, "Dracula");
  assert.equal(s.mazzi_avversari[0].winrate_contro, 75);
  assert.equal(s.mazzi_avversari[0].giocatori, 2);
  assert.deepEqual(s.mazzi_avversari[0].carte.map((c) => c.nome), ["Garlic", "Bat"]);
  assert.equal(s.matchup[0].winrate, 75);
});

test("validazione: scarta il superfluo e pulisce", () => {
  const install = "a".repeat(32);
  assert.ok(validateContribution({ install: "x" }).errore);
  assert.ok(validateContribution({ install, regole: new Array(301).fill({}) }).errore);
  const v = validateContribution({
    install,
    regole: [{ cid: "R030", testo: "Vedi https://x.y e scrivi a a@b.it", stato: "confermata", prove: ["t3"] },
      { cid: "R031", testo: "x", stato: "boh" }],
    lezioni: [{ cid: "L001", testo: "Tieni un blocco", tipo: "strategia", stato: "ipotesi", carte: ["A", "A"], volte: 999 }],
    carte: [{ nome: "Marian", testo: "On Reveal", costo: 3, attacco: "x", segreto: "no" }],
    partite: [{ cid: "p1", risultato: "Vittoria", mia_leggendaria: "Robin Hood", round: 7 }, { cid: "p2", risultato: "?" }],
  });
  assert.equal(v.regole.length, 1);
  assert.equal(v.regole[0].testo, "Vedi e scrivi a");
  assert.equal(v.lezioni[0].volte, 50);
  assert.deepEqual(v.lezioni[0].carte, ["A"]);
  assert.deepEqual(v.carte[0].dati, { nome: "Marian", testo: "On Reveal", costo: 3, attacco: "x" });
  assert.equal(v.partite.length, 1);
  assert.equal(v.partite[0].risultato, "vittoria");
  assert.equal(clean("a\u0000b"), "a b");
});
