---
description: Legge le schermate catturate con F9 e aggiorna database carte, location e regole
---
Elabora le schermate in coda per costruire il database di Origins TCG.

1. Chiama `list_scan_images`. Se non ce ne sono, spiega a Daniele come catturarle (overlay aperto,
   apri la collezione o il dettaglio di una carta nel gioco, premi F9 per ogni schermata) e fermati.
2. Leggi le immagini con il tool Read, a gruppi di 5.
3. Per ogni carta leggibile estrai: `nome`, `leggendaria` (true/false), `costo`, `attacco` e `vita`
   (le due cifre ⚔/❤ delle creature), `testo` (esatto, come scritto), `tipo` ("creatura" o "spell"),
   `potere_leggendario` (solo per le leggendarie: cosa fa il potere/la carta che arriva a inizio
   partita), `rarita`, `tag` (parole chiave/fazioni/tribù in lista). Non usare il campo `potere`.
   Campi che non vedi: lasciali fuori, non inventarli. Se la stessa carta appare più volte, unisci.
4. Per le location: `nome`, `testo`, `rarita`. Per le schermate del tutorial o delle regole:
   aggiorna il regolamento con `rules_upsert` (`fonte="tutorial"`; il testo ufficiale del gioco
   conferma una regola: usa l'id della domanda o ipotesi corrispondente) e salva i numeri chiave
   con `set_rules_numbers`. Solo la prima volta: chiama `legacy_rules_file` e importa il vecchio file.
5. Salva con `upsert_cards` / `upsert_locations` (patch = quella corrente se nota, altrimenti vuota).
6. Archivia le immagini elaborate con `archive_scan_images`; quelle illeggibili lasciale in coda e
   dimmi quali rifare.
7. Chiama `cards_to_check` e includi nel riepilogo le carte ancora incomplete.
8. Chiudi con: carte nuove, carte modificate (con le differenze), location nuove, regole scoperte,
   totale nel database (`database_status`).

$ARGUMENTS
