---
description: Analisi approfondita dell'ultima partita (consigli di mossa sempre permessi qui)
---
1. `match_history(last=1)` e `get_recent_screens(4)` per rivedere le ultime schermate.
2. Ricostruisci la partita turno per turno per quanto possibile dalle note e dalle schermate.
3. Indica i 2-3 momenti decisivi: cosa ho giocato, cosa sarebbe stato meglio, con le probabilità
   che avevo in quel momento (ricalcolale con le funzioni se servono).
4. Cosa ho imparato sull'archetipo avversario: aggiorna il meta se ho visto carte nuove
   (`record_opponent_deck`). Registra con `record_lesson` (fonte "postpartita") le lezioni dei momenti
   decisivi che non erano già state registrate durante la partita (le simili vengono rafforzate).
5. Un consiglio concreto per la prossima partita.

$ARGUMENTS
