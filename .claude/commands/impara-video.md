---
description: Studia un video tutorial/partita di YouTube (sottotitoli + fotogrammi)
argument-hint: <link YouTube> [altri link]
---
Link da studiare: $ARGUMENTS

Per ogni link:
1. Prepara il video con Bash (può richiedere qualche minuto per i video lunghi):
   `python origins/video.py "<link>"`
   L'output è un JSON con titolo, canale, data di pubblicazione, cartella dei fotogrammi e della
   trascrizione. Se il video è già stato preparato (cartella esistente con info.json), riusala.
   Se fallisce, riprova con `--solo-testo` e lavora solo sulla trascrizione.
2. Leggi la trascrizione intera (Read), poi i fotogrammi in ordine, 10 alla volta. Il nome di ogni
   fotogramma contiene il minuto (es. `0012_t03m40s.png`): collegalo alla trascrizione di quel momento.
3. Estrai e salva:
   - **Regole** con `rules_upsert`: `fonte="video: <titolo> (<canale>) <mm:ss>"`, `prova` = cosa dice
     o mostra il video. Video spiegato a voce dagli sviluppatori o tutorial ufficiale → può confermare;
     video di un giocatore → `probabile`. Se il video è più vecchio di una patch registrata
     (`patch_changes`, `record_patch`), segnalalo nella prova.
   - **Carte**: solo se il testo è leggibile per intero, `upsert_cards` (aggiungi in `note`
     "da video del <data>"). Non sovrascrivere carte già scansionate dal gioco se i dati differiscono:
     segnala la differenza (potrebbe essere una patch).
   - **Strategia** (piani di gioco, mazzi mostrati, consigli): aggiungili a `data/strategia.md`
     sotto un titolo con nome del video, canale, data e link. Mazzi completi mostrati:
     `record_opponent_deck` con `archetype` = nome dato nel video.
4. Rispondi con un riassunto: regole nuove/confermate/contraddette, carte aggiunte, mazzi e idee
   strategiche trovate, e cosa del video non è stato chiaro.
