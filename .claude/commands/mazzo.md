---
description: Crea o migliora un mazzo in base a carte, meta e ultima patch
argument-hint: [leggendaria, stile di gioco o mazzo da migliorare]
---
Richiesta di Daniele: $ARGUMENTS

Segui la sezione "Deckbuilding" di CLAUDE.md:
1. Raccogli: `card_pool_compact`, `meta_report`, `patch_changes`, `list_decks`, `rules_get`, `data/strategia.md` (se esiste).
   Se il database ha poche carte, dillo subito e suggerisci `/scansiona`.
2. Proponi 2-3 liste diverse (leggendaria + 12 carte). Per ognuna:
   - piano di gioco in 2 righe e su quali corsie/location rende meglio
   - curva, attacco e vita totali con `deck_curve`
   - 3 sinergie chiave spiegate
   - matchup stimati contro gli archetipi più visti (se il meta ha dati) e perché
   - le 2 carte più "flessibili" da cambiare in base al meta
   - cosa è cambiato con l'ultima patch che rende questa lista buona o rischiosa
3. Valida ogni lista con `validate_deck` e confrontale con `deck_lab` (anche contro i mazzi già salvati di
   Daniele): giocate per round, mana sfruttato, attacco in campo, leggendaria pescata. Riporta i numeri in una
   piccola tabella e usali per motivare la scelta (sono partite in solitario: misurano la fluidità, non i matchup).
4. Chiedi quale salvare e salvala con `save_deck` solo dopo conferma.
