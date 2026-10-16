---
description: Intervista Daniele per ricostruire le regole del gioco
---
Ricostruisci il regolamento intervistando Daniele, che il gioco lo conosce già giocandolo.

0. Solo la prima volta: chiama `legacy_rules_file`. Se restituisce del contenuto, importa con
   `rules_upsert` le informazioni verificate che non sono già nel regolamento (fonte: "tutorial").
1. `rules_get(stato="domanda")` e `rules_get(stato="ipotesi")`.
2. Fai **3-4 domande alla volta**, brevi e concrete, in quest'ordine di priorità: vittoria → risorse →
   turno → rivelazione → corsie → leggendaria → parole chiave → location. Per le ipotesi chiedi
   conferma ("È vero che…?").
3. Per ogni risposta usa `rules_upsert` con l'**id** della domanda: riscrivi il testo come regola
   chiara, `stato="confermata"`, `fonte="Daniele"`, `prova` = la sua risposta in breve.
   Se emergono regole nuove, creale. Se Daniele dice "non so" o "credo", usa `stato="probabile"`
   e segnala che va verificata con un esperimento.
4. Fai domande di approfondimento quando una risposta apre dubbi (es. "e se la corsia è in parità?").
5. Continua finché Daniele non dice basta o le domande sono finite. Alla fine mostra in breve
   quante regole sono confermate e quali dubbi restano, e proponi `/esperimento` per quelli.

Tono: rapido, niente spiegazioni lunghe. $ARGUMENTS
