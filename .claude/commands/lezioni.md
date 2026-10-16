---
description: Rivedi le lezioni imparate da BIG-BOB (conferma, correggi, elimina, insegnane di nuove)
argument-hint: [carta, tipo o "nuove"]
---
Filtro richiesto da Daniele: $ARGUMENTS

1. `lessons_get` (con `carte` o `tipo` se Daniele ha indicato un filtro; "nuove" = stato ipotesi).
2. Mostrale raggruppate per tipo, le ipotesi ❓ per prime, in una riga ciascuna: id, lezione, carte, quante volte vista.
3. Segnala le **lezioni in conflitto** tra loro o con il regolamento (`rules_get`) e i **doppioni** da fondere.
4. Chiedi a Daniele cosa fare con le ipotesi, 5 alla volta: confermare, riformulare, smentire o eliminare.
   Applica con `lesson_review`. Per fondere due doppioni: riformula la migliore e elimina l'altra.
5. Se Daniele vuole insegnare qualcosa di nuovo, registralo con `record_lesson` (fonte "Daniele").
