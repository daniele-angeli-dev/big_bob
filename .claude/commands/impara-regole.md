---
description: Studia una partita registrata (⏺ Registra) e ne deduce le regole
argument-hint: [nome registrazione, opzionale]
---
Studia una registrazione di partita e aggiorna il regolamento.

0. Solo la prima volta: chiama `legacy_rules_file` e importa ciò che è verificato.
1. `list_recordings`: scegli $ARGUMENTS oppure la più vecchia non elaborata.
2. `rules_get()` per sapere cosa sappiamo già e cosa manca (stati domanda/ipotesi/probabile).
3. Leggi i fotogrammi **in ordine**, 10 alla volta (`recording_frames` + Read). Tieni appunti
   turno per turno: numero del turno, risorse/energia visibili, carte in mano (quante), carte
   giocate e in quale corsia, ordine di rivelazione, valori delle corsie, effetti attivati,
   regole delle location, punteggi, timer, e come finisce la partita.
4. Dagli appunti deduci le regole. Per ognuna `rules_upsert`:
   - risponde a una domanda → usa il suo id, `fonte="osservazione <nome registrazione>"`,
     `prova` = cosa hai visto (turno e fotogramma, es. "T3 fot. 0042: energia passa da 2 a 3")
   - una sola osservazione → `stato="probabile"`; se la regola era già probabile da un'altra fonte
     indipendente → `confermata`
   - se vedi qualcosa che **contraddice** una regola, mettila `smentita` (o correggi il testo) e spiega
   - non promuovere mai a confermata una cosa solo dedotta e mai vista accadere
5. Se una carta si comporta in modo diverso dal suo testo nel database, aggiungi una nota alla
   carta con `upsert_cards` (campo `note`).
6. `mark_recording_done` con un riassunto di 3 righe.
7. Rispondi con: regole nuove, regole confermate, contraddizioni trovate, dubbi rimasti e
   1-2 esperimenti da fare contro il bot per chiarirli.
