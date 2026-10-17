---
description: Studia una partita registrata (⏺ Registra): regole del gioco e lezioni di strategia
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
6. **Studio strategico**: chi ha vinto e perché, le giocate che hanno spostato la partita (corsia scelta, tempi, colpi
   di chiusura, difese mancate), errori ricorrenti di Daniele, abitudini dell'avversario, come hanno reso le carte del
   mazzo. Per ognuna `record_lesson` (tipo strategia, mossa_avversaria o mossa_vincente; carte coinvolte;
   fonte "registrazione <nome>"): una frase pratica e generale, non la cronaca.
7. `mark_recording_done` con un riassunto di 3 righe (regole + strategia).
8. Rispondi con: regole nuove, regole confermate, contraddizioni trovate, dubbi rimasti e
   1-2 esperimenti da fare contro il bot per chiarirli.

Alla fine ricorda a Daniele che trova tutto ciò che hai imparato da questa registrazione nella pagina
"Cosa ho imparato" (pulsante a forma di libro nella finestra di BIG-BOB): per questo chiama sempre
`mark_recording_done` con un riassunto, e nelle fonti di lezioni e regole scrivi il nome della registrazione.
