---
description: Importa mazzi e risultati dalla community (Discord, tornei, video) nel meta
argument-hint: [incolla qui liste, risultati o un link a una schermata]
---
Materiale della community da importare:

$ARGUMENTS

0. I mazzi e le statistiche di originsmeta.com arrivano da soli (`community_decks`, `community_stats`; per
   riscaricarli subito `originsmeta_sync`): questo comando serve per le altre fonti.
1. Se non c'è materiale, chiedi a Daniele di incollare il testo (liste dal Discord, top 8 di un torneo come la
   Crimson Cup, risultati) oppure di catturare con F9 le schermate dei mazzi e poi leggile con `list_scan_images`.
2. Per ogni mazzo riconosci: nome dell'archetipo (quello usato dalla community), leggendaria, carte (riconduci
   ogni nome a una carta del database con `search_cards`; segnala quelle che non trovi).
3. Registralo con `record_opponent_deck(legendary, cards_seen, archetype=<nome>, fonte="community")`.
   I mazzi community pesano nelle probabilità della mano avversaria, ma non contano come partite di Daniele.
4. Se ci sono risultati (piazzamenti, winrate), salvali in `data/strategia.md` sotto un titolo con fonte e data.
5. Chiudi con `meta_report`: quali archetipi sono entrati, quanti hanno la lista completa (12/12),
   e quali ti sembrano i più pericolosi per i mazzi di Daniele (`list_decks`), con una contromossa per ciascuno.
