# BIG-BOB · assistente per Origins TCG

BIG-BOB è il tuo coach personale per Origins TCG, gira sul tuo PC con Claude Code (abbonamento Max, nessun costo extra).

- **Overlay** sempre sopra il gioco con chat: premi **F8** e Claude guarda la partita e risponde in pochi secondi.
- **Database carte, location e regole** costruito dalle tue schermate (F9 + `/scansiona`), con storico delle modifiche per patch.
- **Probabilità esatte** di pescata (ipergeometrica sul tuo mazzo da 25) e **probabilità sulla mano avversaria**, pesate sugli archetipi che incontri.
- **Meta personale**: ogni partita registra il mazzo avversario; `/meta` ti dice cosa gira e come batterlo.
- **Deckbuilding** con `/mazzo` e aggiornamento dopo ogni patch con `/patch`.

## Requisiti
- Windows con **Python 3.10+** (python.org, spunta "Add python.exe to PATH" durante l'installazione)
- **Claude Code** installato e collegato al tuo account Max (guida ufficiale: https://docs.claude.com/en/docs/claude-code/setup).
  Verifica: apri un terminale e scrivi `claude`; se si apre e sei loggato, sei a posto.

## Installazione: BIG-BOB-Setup.exe
Doppio clic su **BIG-BOB-Setup.exe** e segui le schermate:
1. **Benvenuto** e scelta della cartella (se BIG-BOB c'è già, propone la stessa: il codice si aggiorna, i dati restano).
2. Se è già installato puoi scegliere **Aggiorna/ripara** oppure **Disinstalla**.
3. Controlla **Python, Claude Code e Git** e installa con winget quello che manca (Git serve per gli aggiornamenti).
4. Copia BIG-BOB, installa le librerie, fa i collaudi e crea **l'icona sul desktop e nel menu Start**.
5. **Collega Claude**: abbonamento (consigliato) o chiave API, modello (Sonnet/Opus/Haiku), pulsanti
   *Accedi a Claude* e *Prova collegamento*.
6. Fine, con la casella **Avvia BIG-BOB**.

Windows può mostrare "PC protetto da Windows" perché l'installer non è firmato: *Ulteriori informazioni → Esegui
comunque*. BIG-BOB compare in **Impostazioni → App installate**, da dove si disinstalla (ti chiede se tenere i dati).

## Aggiornamenti: te lo dice lui
A ogni avvio BIG-BOB controlla se c'è una versione nuova. Se c'è, compare un banner con le novità e il pulsante
**AGGIORNA ORA**: scarica solo le differenze, aggiorna le librerie se sono cambiate, si chiude e si riapre da solo
(i tuoi dati non vengono toccati). Puoi controllare anche a mano da ⚙ Impostazioni → Controlla aggiornamenti, o dal menu
Start → BIG-BOB → Aggiorna BIG-BOB. La prima volta GitHub chiede di accedere: fallo una volta da "Aggiorna BIG-BOB".

## Carte, location e meta da OriginsMeta (automatico)
BIG-BOB legge da solo [originsmeta.com](https://originsmeta.com) ogni 12 ore (subito, se il database delle carte è vuoto):
- **carte e location**: aggiunge quelle che mancano; i cambiamenti di costo/attacco/vita diventano una patch
  "<versione> (OriginsMeta)" con lo storico. Un testo corretto da te (o letto dalle schermate) non viene più sovrascritto;
- **mazzi** pubblicati e da torneo, con winrate, partite, valutazione, versione e guida: pesano nelle probabilità
  sulla mano avversaria e Claude Code li usa in `/mazzo` e `/meta`;
- **statistiche** delle partite registrate: winrate e diffusione per leggendaria, archetipo e carta, griglia dei matchup.

Scarica solo pagine pubbliche, una al secondo, e riscarica un mazzo solo se è nuovo o cambiato. A mano:
⚙ → *Aggiorna meta ora*, oppure `python -m origins.originsmeta --forza`. Se qualcosa non viene letto bene,
`python -m origins.originsmeta --forza --salva-pagine` salva le pagine in `logs/originsmeta/` da mandarmi.
Le regole confermate nell'intervista vengono con BIG-BOB: anche un'installazione nuova parte con il regolamento.

## Impostazioni (icona a ingranaggio)
- **Collegamento a Claude**: abbonamento Claude (Claude Code con il tuo account, consigliato) oppure chiave API Anthropic
  (a consumo; la chiave resta solo nel tuo `config.json`). Con l'abbonamento BIG-BOB ignora eventuali chiavi API
  rimaste nel sistema, così non paghi a consumo per errore. *Accedi a Claude* apre Claude Code per il login,
  *Prova collegamento* verifica che risponda.
- **Modello per le risposte live**: Sonnet (veloce, consigliato), Opus (più preciso ma rischia i 40 s), Haiku (velocissimo).
- Voce, apprendimento tra i round, Claude Code all'avvio, controllo aggiornamenti, tetto di ragionamento.

## Avvio: un'icona
Clicca l'icona **BIG-BOB** (desktop, menu Start, o fissala sulla barra delle applicazioni: tasto destro → Aggiungi alla
barra delle applicazioni). Si apre la finestra di BIG-BOB e, accanto, il terminale di **Claude Code** già nella cartella
giusta per i comandi (`/scansiona`, `/mazzo`, `/lezioni`…). Il Claude Code che risponde a F8 è dentro la finestra e parte da
solo: il terminale serve solo per i comandi. Non lo vuoi all'avvio? `apri_claude_code_all_avvio: false` in `config.json`;
lo apri quando serve con il pulsante **>_** della finestra.
Se clicchi l'icona con BIG-BOB già aperto, riporta in primo piano la finestra (anche se era nascosta con F10).

Nel menu Start, cartella **BIG-BOB**: Aggiorna, Claude Code, Diagnostica, Statistiche, finestra classica, cartella dei
dati e Disinstalla collegamenti (toglie solo le icone: file e dati restano).

## Primo utilizzo: insegnare il gioco a Claude
1. Apri BIG-BOB dall'icona e apri il gioco.
2. **Regole**: apri tutorial/regole/glossario delle parole chiave nel gioco e premi **F9** su ogni schermata.
3. **Carte**: apri la collezione. Per ogni carta (o pagina, se il testo è leggibile) premi **F9**. Il dettaglio della singola carta è più affidabile della griglia.
4. **Location**: se il gioco ha un elenco delle location, fai lo stesso.
5. Avvia **`apri_claude_code.bat`** e scrivi **`/scansiona`**. Claude legge tutto, salva il database e ti dice quali schermate rifare. Puoi ripetere a blocchi (es. 30 carte alla volta).
6. Crea i mazzi: `/mazzo voglio un mazzo aggressivo con Robin Hood` (o salva i tuoi: "salva il mio mazzo X: leggendaria ..., carte ...").

## Insegnare le regole (non esiste un manuale)
BIG-BOB ricostruisce il regolamento da più fonti; ogni regola ha uno stato
(⬜ domanda · ❓ ipotesi · 🟡 probabile · ✅ confermata · ❌ smentita), le fonti e le prove. Lo leggi in `data/regole.md`.
1. **Intervista** (10-15 minuti, il modo più veloce): in Claude Code `/intervista-regole`. Ti fa 3-4 domande alla volta.
2. **Video**: `/impara-video <link YouTube>` scarica sottotitoli e fotogrammi ai cambi di scena e li studia (il video viene poi cancellato, restano testo e immagini).
3. **Osservazione**: nell'overlay spunta **⏺ Registra**, gioca una partita contro il bot (premi F10 per nascondere l'overlay), togli la spunta a fine partita, poi `/impara-regole`. Non consuma utilizzo durante la partita.
4. **Esperimenti**: `/esperimento` ti propone prove precise contro il bot per chiarire i dubbi rimasti.
5. **Schermate**: tutorial, glossario e tooltip delle parole chiave catturati con F9 e letti da `/scansiona`.

Durante le partite vere BIG-BOB annota da solo le contraddizioni con il regolamento.

## BIG-BOB impara dalle sorprese
Claude non modifica sé stesso: BIG-BOB fa come un giocatore con un quaderno. Quando succede qualcosa che non aveva
previsto lo capisce, scrive una **lezione** e la rilegge ogni volta che tornano in gioco le stesse carte.
- **Durante la partita**: dopo ogni risposta (dal secondo round), mentre tu leggi e giochi, confronta cosa aveva
  previsto con cosa è successo davvero: mossa avversaria inattesa, carta che fa più di quanto pensava, consiglio
  che non ha funzionato, tua mossa diversa che ha funzionato meglio. Le nuove lezioni compaiono nella chat
  (riquadro "LEZIONE IMPARATA"). Non rallenta la risposta: se premi F8 mentre sta ancora imparando aspetta qualche secondo.
- **A fine partita** (FINE): ripensa alla partita intera e trasforma in lezioni anche le tue segnalazioni ✕.
- **Insegnagliele tu**: in chat scrivi "impara: …" o "ricordati che …": diventa subito una lezione confermata.
- Una lezione vista una volta è un'ipotesi ❓; quando si ripete diventa ✅. Quelle smentite dai fatti vengono segnate ❌.
- Le lezioni sulle carte in gioco arrivano a BIG-BOB già dentro `update_match`, quindi non costano tempo.
- Le trovi in `data/lezioni.md`; in Claude Code `/lezioni` per rivederle, confermarle, correggerle o eliminarle.
  Dopo una patch, `/patch` ti segnala quelle sulle carte cambiate da riverificare.
- Costa un turno breve in più per round (~5-10 s, mentre giochi). Per spegnerlo: `apprendimento_live: false` in `config.json`.

## Cosa fa BIG-BOB in partita
- **Simulatore di combattimento**: BIG-BOB non fa i conti a mente. Passa il campo a `update_match` e riceve la
  previsione del combattimento (corsie da sinistra a destra, colpi simultanei, Defender, barrier che si rinforzano a 40
  senza danno in eccesso, vittoria a 2 barrier); quando la mossa non è ovvia confronta 2-3 giocate con
  `simulate_combat`, compresa la risposta più pericolosa dell'avversario.
- **Mulligan**: sulla schermata iniziale (Keep or Replace) premi F8: ti dice quali carte tenere e quali cambiare con le
  probabilità di avere una giocata nei round 1-3.
- **Location**: il nome della location compare sopra ogni corsia nell'HUD (passa il mouse per la regola). Se è nuova,
  BIG-BOB la legge, la salva e ti dice come cambia il piano.
- **Voce**: pulsante **VOCE**, legge la mossa ad alta voce con la voce di Windows (italiana se installata), così non
  stacchi gli occhi dal gioco. In ranked non dice nulla (niente mosse).
- **Statistiche**: pulsante **%** nella finestra (o `statistiche.bat`): winrate per mazzo, archetipo e location, tempo
  medio di risposta, risposte oltre 40 s, consigli seguiti e andati bene, lezioni confermate.
- **Rivedi la partita**: a fine partita il pulsante **RIVEDI LA PARTITA** apre la linea del tempo con schermate,
  risposte, lezioni e segnalazioni.

## Durante la partita (finestra Arena)
In alto vedi **round, mana, chi rivela prima e le 6 barrier** (avversario arancione, tu teal; giallo = a rischio,
RINF. = rinforzata, max 40) con il punteggio delle barrier distrutte. Sotto, la card gialla **LA MOSSA** e le card
di minaccia, pescata, mano avversaria e location; poi la chat.

| Tasto | Cosa fa |
|---|---|
| **NUOVA** | scegli il mazzo (o scrivi "leggilo dallo schermo e salvalo come X"): Claude inizia a tracciare |
| **F8** | analisi del round: cattura il gioco e risponde con mossa, minacce e probabilità |
| chat | domande libere ("se gioca X al centro cosa faccio?", "probabilità di pescare Y in 2 round?") |
| **REGISTRA** | salva un fotogramma a ogni cambio di schermata (per `/impara-regole`), senza chiamare Claude |
| **AUTO** | analizza da solo quando lo schermo cambia: la risposta parte prima ancora che tu prema F8 |
| **FINE** | registra risultato e mazzo avversario nel meta + 3 righe di feedback |
| **F9** | cattura per la scansione (la finestra lampeggia) |
| **VOCE** | legge la mossa ad alta voce |
| **%** | apre le statistiche |
| **>_** | apre Claude Code per i comandi |
| **F10** / **–** | nasconde/mostra la finestra · **×** chiude BIG-BOB |
| **✕** | segnala che l'ultima risposta era sbagliata (finisce nel diario della partita) |

La finestra si trascina dalla barra in alto e può stare sopra il gioco: a ogni cattura si nasconde per un istante.
Se la grafica nuova non partisse, si apre da sola la **finestra classica** (o lanciala con `avvia_classico.bat`).

Ogni partita ha un **diario** in `logs/partite/<data>/diario.md`: per ogni richiesta salva la schermata, gli strumenti
usati con i tempi, i token generati, la risposta e le tue segnalazioni ✕.

### Velocità (obiettivo: risposta entro 40 secondi)
Il round dura 90 secondi e ti servono ~50 secondi per leggere e giocare, quindi BIG-BOB punta a rispondere entro 40.
La barra in basso mostra il tempo con una tacca a 40 s (arancione dopo 30 s, rossa dopo 40 s). Misurato sul flusso:
prima ~24 s per un F8, ora ~14-20 s, senza togliere nulla al ragionamento:
- Claude Code resta **acceso per tutta la partita** (parte già all'apertura e a NUOVA): niente avvio a ogni F8.
- La schermata viene **allegata alla domanda**: niente passaggio per chiederla.
- Gli strumenti di BIG-BOB sono **caricati subito** (niente ricerca degli strumenti a ogni avvio).
- `update_match` restituisce **già le probabilità**, calcolate sullo stato appena aggiornato (prima venivano
  chiamate in parallelo e potevano usare lo stato vecchio).
- **Cintura di sicurezza**: il ragionamento ha un tetto di 4.000 token (`max_thinking_live` in `config.json`). Un round
  normale ne usa 2.500-3.000, quindi non cambia nulla; il tetto ferma solo i casi estremi sotto i 40 s.
- Con **AUTO** acceso l'analisi parte quando cambia il round, così spesso la risposta è pronta quando guardi.

### Modalità: ALLENAMENTO e RANKED
Il pulsante in alto a sinistra cambia modalità.
- **ALLENAMENTO**: coach completo, ti suggerisce le giocate. Per casual, bot, amichevoli e analisi.
- **RANKED · solo tracker**: probabilità di pescata, probabilità sulla mano avversaria, testi di carte/location. Niente consigli di mossa. Usala in ranked e nei tornei (Crimson Cup inclusa): un aiuto esterno che decide le mosse è con ogni probabilità vietato dal regolamento e rischi la squalifica o le carte. Controlla comunque le regole ufficiali del torneo sul Discord: se vietano anche i tracker, non usare l'overlay.

## Comandi in Claude Code (`apri_claude_code.bat`)
- `/scansiona` — elabora le schermate F9 → carte, location, regole
- `/intervista-regole` — ricostruisce le regole facendoti domande
- `/impara-regole` — studia una partita registrata con ⏺ Registra
- `/esperimento` — prove da fare contro il bot per i dubbi
- `/impara-video <link>` — studia un video di YouTube
- `/mazzo [richiesta]` — 2-3 liste con curva, sinergie, matchup e motivazioni legate alla patch
- `/patch [nome e note]` — registra una patch, aggiorna le carte cambiate, rivaluta mazzi e meta
- `/meta` — archetipi più incontrati, winrate, contromisure
- `/postpartita` — revisione dettagliata dell'ultima partita (e lezioni dai momenti decisivi)
- `/lezioni [carta|tipo|nuove]` — rivedi, conferma, correggi o elimina le lezioni imparate
- `/importa-meta [testo]` — importa liste e risultati della community (Discord, tornei, video) nel meta
- Laboratorio mazzi: `/mazzo` confronta le liste con migliaia di partite simulate in solitario (`deck_lab`);
  puoi anche chiedere "confronta con deck_lab i miei mazzi X e Y"
- Domande libere: "confronta i miei due mazzi", "quali carte puniscono le location che bloccano il centro?"

## Dove stanno i dati
Cartella `data/` (JSON leggibili, puoi farne backup o modificarli a mano):
`cards.json`, `locations.json`, `decks.json` (tuoi mazzi), `meta.json` (archetipi avversari),
`patches.json`, `matches_log.json`, `rules.json` (regolamento, con versione leggibile `regole.md`),
`lessons.json` (lezioni imparate, versione leggibile `lezioni.md`),
`strategia.md` (idee da video e analisi). Schermate, registrazioni e video sono in `captures/`.

## Configurazione (`config.json`)
- `modello_live`: modello per la finestra (`sonnet` = più veloce; `opus` = più preciso ma più lento: rischia di superare i 40 s)
- `max_thinking_live`: tetto ai token di ragionamento per le risposte live (default 4000; `0` = nessun tetto)
- `apprendimento_live`: impara dalle sorprese tra un round e l'altro (default `true`)
- `voce`: lettura ad alta voce della mossa (default `true`, si cambia anche dal pulsante VOCE)

## Controllo patch automatico
Ogni mattina alle 8:47 un'attività programmata nel cloud cerca note di patch e novità di Origins TCG (Steam, X,
articoli). Se trova qualcosa ti arriva una notifica e una mail con il riepilogo e un blocco già pronto da incollare
in `/patch`. La gestisci dalle attività programmate del tuo account Claude.
- `titolo_finestra`: parte del titolo della finestra del gioco (default `Origins`). Se l'overlay cattura lo schermo sbagliato, controlla il titolo esatto nella barra delle applicazioni.
- `hotkey_analisi`, `hotkey_scan`: tasti rapidi

## Problemi comuni
Per prima cosa lancia **`diagnostica.bat`** con il gioco aperto: controlla librerie, finestra del gioco, cattura, tasto F9 e Claude Code, e ti dice cosa sistemare. Gli errori dell'overlay sono scritti in `logs/bigbob.log`.

- **I tasti F8/F9 non funzionano dentro il gioco**: alcuni giochi bloccano i tasti globali se girano come amministratore. Sull'icona BIG-BOB: tasto destro → Proprietà → Avanzate → "Esegui come amministratore", oppure usa i pulsanti F8 e F9 della finestra.
- **La finestra si apre in stile vecchio**: la grafica Arena non è partita. Rilancia `installa.bat` e guarda `logs/bigbob.log`; serve Microsoft Edge WebView2, già incluso in Windows 11.
- **"Non trovo il comando claude"**: Claude Code non è nel PATH. Riapri il terminale dopo l'installazione o reinstallalo.
- **Cattura nera**: gioco in schermo intero esclusivo. Imposta "finestra senza bordi" (borderless) nelle opzioni video.
- **Probabilità strane**: lo stato partita è sbagliato. Scrivi in chat cosa hai in mano e cosa c'è sul campo: Claude lo corregge.
- **Limiti di utilizzo**: ogni analisi invia un'immagine. Con Auto acceso in tutte le partite puoi avvicinarti ai limiti del piano Max; usa F8 quando serve.

## Come funziona
```
Finestra Arena (HTML/WebView2) ──F8 + schermata──► Claude Code sempre acceso (una sessione per partita)
                                   │  legge CLAUDE.md (regole da coach)
                                   ▼
                       server MCP "origins" (origins/server.py)
                       ├─ get_screen: cattura la finestra del gioco
                       ├─ database carte/location/mazzi/meta/patch (data/*.json)
                       └─ probabilità esatte (origins/odds.py)
```
