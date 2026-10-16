---
description: Registra una nuova patch e aggiorna carte, mazzi e meta
argument-hint: [nome patch, note o testo delle patch notes]
---
Nuova patch: $ARGUMENTS

1. Chiedi a Daniele (se non l'ha già fatto) le patch notes: testo incollato, oppure screenshot
   catturati con F9 (in quel caso leggili da `list_scan_images`).
2. `record_patch` con nome, data e un riassunto delle note.
3. Per ogni carta/location cambiata: `upsert_cards` / `upsert_locations` con `patch` = nome patch
   e SOLO i campi cambiati (più il nome). Carte nuove: inseriscile complete.
4. Mostra `patch_changes`.
5. `patch_changes` elenca anche le **lezioni da riverificare** (quelle sulle carte cambiate): per ognuna
   decidi se vale ancora, va riformulata (`lesson_review` con il nuovo testo) o va smentita.
6. Rivaluta: i mazzi di Daniele (`list_decks`) — quali migliorano, quali peggiorano, che sostituzioni
   fare — e gli archetipi del meta (`meta_report`) — chi sale e chi scende, con il perché.
