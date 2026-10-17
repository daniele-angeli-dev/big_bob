# BIG-BOB · assistente per Origins TCG

BIG-BOB è il tuo coach personale per Origins TCG, gira sul tuo PC con Claude Code (con il tuo abbonamento Claude Pro o
Max, oppure con una chiave API a consumo).

- **Overlay** sempre sopra il gioco con chat: premi **F8** e Claude guarda la partita e risponde in pochi secondi.
- **Database carte, location e regole** costruito dalle tue schermate (F9 + `/scansiona`), con storico delle modifiche per patch.
- **Probabilità esatte** di pescata (ipergeometrica sul tuo mazzo da 25) e **probabilità sulla mano avversaria**, pesate sugli archetipi che incontri.
- **Meta personale**: ogni partita registra il mazzo avversario; `/meta` ti dice cosa gira e come batterlo.
- **Deckbuilding** con `/mazzo` e aggiornamento dopo ogni patch con `/patch`.

## Novità
Le ultime modifiche, dalla più recente (BIG-BOB le mostra anche nella finestra dell'aggiornamento).

**17/10/2026**
- **Contatori dei mazzi corretti**: le carte giocate si sommano round dopo round invece di sparire quando non sono più
  sul campo; il numero letto sullo schermo non resta fermo nei round dopo (scala di una pescata a round); il conto non
  scende mai sotto le regole (4 iniziali + 1 a round) e la carta del potere leggendario non conta come pescata. BIG-BOB
  impara da solo, dai numeri letti, se si pesca anche al round 1. Passando il mouse sul numero vedi da dove viene.
- AUTO spento si spegne davvero: le analisi automatiche ancora in coda vengono scartate, quindi niente più catture e
  finestra che sparisce e ricompare dopo averlo disattivato. REGISTRA non fa più lampeggiare la finestra: i fotogrammi
  si prendono senza nasconderla (la zona di BIG-BOB resta nera, come per l'osservatore).
- **Previsione delle carte avversarie**: dal mazzo stimato BIG-BOB calcola cosa ha probabilmente in mano l'avversario,
  cosa può giocare in questo round con il suo mana (tenendo conto del round in cui di solito si giocano le carte e del
  tipo di mazzo), la minaccia principale, il suo piano tipico e la tua corsia più esposta. Nella finestra c'è la riga
  PUÒ GIOCARE; a ogni round controlla se aveva previsto giusto e impara dalle sorprese (nelle statistiche: «carte
  avversarie previste»).
- Finestra di gioco più leggibile: in partita pannelli più compatti e mossa in caratteri grandi; sotto la barra di
  vantaggio, al posto della frase, tre indicatori immediati **CAMPO · MANO · BARRIER** (▲ vantaggio, = parità,
  ▼ svantaggio). BIG-BOB si riapre dove e grande come l'hai lasciato (⚙ → *Ripristina posizione* per tornare al centro).
- Cervello comune: SINCRONIZZA ORA nello Studio ora aspetta e mostra l'esito lì (inviati, ricevuti, tempo o il
  problema preciso); un errore nell'invio non blocca più la ricezione; l'ultimo esito si vede anche in ⚙ e in
  `diagnostica.bat`, che ora controlla anche il server.
- **Cronologia delle partite** nel libro (scheda PARTITE): ogni partita con risultato, mazzi e tipo di avversario; con
  un clic, richiesta per richiesta, la schermata inviata (si ingrandisce), la mossa suggerita, cosa hai giocato davvero
  (con «consiglio seguito» / «giocata diversa»), cosa ha giocato l'avversario e le barrier dopo.
- **Parla con BIG-BOB delle tue partite** (è da qui che impara di più): sotto ogni mossa e per tutta la partita chiedi
  perché ti ha suggerito una mossa e se era giusta, oppure spiegagli le tue scelte («ho giocato Marian invece perché…»)
  e correggilo. BIG-BOB risponde, ti fa a sua volta una domanda (❓) per capire ciò che non vedeva, e registra subito
  quello che gli insegni come lezione confermata (o regola, o testo di carta corretto), mostrandotelo con 📚. Le
  conversazioni restano salvate con la partita; a fine partita il pulsante RIVEDI E PARLANE CON BIG-BOB porta qui.
- **Mazzo avversario riconosciuto**: dalle carte che gioca, confrontate con i mazzi del meta (OriginsMeta, le tue
  partite, il cervello comune), BIG-BOB dice quale lista sta usando e che tipo di mazzo è — Aggro, Midrange (aggro o
  control), Control, Combo, con i sottotipi Swarm, Tempo, Big, Ramp, Discard — e come giocarci contro. Si vede nella
  finestra (riga MAZZO AVV) e ne tiene conto nei consigli; una carta fuori lista non lo manda più fuori strada.
- Libro, Origin e statistiche: se la pagina non si carica entro 12 secondi nella finestra di BIG-BOB, BIG-BOB la chiude
  e la apre nel browser (prima poteva restare a caricare a vuoto); il tempo di caricamento finisce in `logs/bigbob.log`.
- Finestra più alta (fino a 1000 punti, adattata allo schermo senza coprire la barra delle applicazioni): la chat ha
  spazio anche con il pannello della partita e del laboratorio aperti.
- Claude Code si installa da solo (installer e primo avvio di BIG-BOB) e, se è installato ma fuori dal PATH, BIG-BOB lo
  trova e aggiunge la cartella al PATH: a un nuovo giocatore resta solo l'accesso con il proprio account Claude.
- **Cervello comune**: tutti i BIG-BOB mettono in comune, in forma anonima, regole, lezioni, testi delle carte e partite;
  una regola diventa ✅ quando la confermano 2 giocatori. Consenso al primo avvio, interruttori in ⚙.
- Osservatore (vede magie scartate e creature morte tra un F8 e l'altro), contatori di mazzo e mano per entrambi,
  barra di vantaggio stile scacchi, pagina Origin con i mazzi del meta, Studio con «Studia registrazioni»,
  tutorial al primo avvio, contatore dei consumi con la chiave API, risposte più veloci ed economiche.
- Libro con le schede MAZZI · STATISTICHE · STUDIO, tutto dentro la finestra; controllo aggiornamenti a ogni avvio.

**16/10/2026**
- Modalità CREAZIONE MAZZO: BIG-BOB crea un mazzo dal meta e lo migliora versione per versione con le partite di test.
- Carte, location e meta scaricati da OriginsMeta una volta al giorno; regole dell'intervista incluse.
- Pagina «Cosa ho imparato», caricamento mentre pensa, slot numerati da 1, finestra al centro dello schermo,
  aggiornamenti con finestra dedicata, installer .exe con icone e collegamento a Claude.

## Requisiti
- Windows con **Python 3.10+** (python.org, spunta "Add python.exe to PATH" durante l'installazione)
- **Claude Code** collegato al tuo account Claude (Pro o Max; oppure una chiave API). Se manca lo installano da soli
  l'installer e BIG-BOB stesso al primo avvio: a te resta solo l'accesso (guida: https://code.claude.com/docs/en/setup).
  Verifica: apri un terminale e scrivi `claude`; se si apre e sei loggato, sei a posto.

## Installazione: BIG-BOB-Setup.exe
Doppio clic su **BIG-BOB-Setup.exe** e segui le schermate:
1. **Benvenuto** e scelta della cartella (se BIG-BOB c'è già, propone la stessa: il codice si aggiorna, i dati restano).
2. Se è già installato puoi scegliere **Aggiorna/ripara** oppure **Disinstalla**.
3. Controlla **Python, Claude Code e Git** e installa quello che manca (Claude Code con l'installer ufficiale, gli altri
   con winget; Git serve per gli aggiornamenti).
4. Copia BIG-BOB, installa le librerie, fa i collaudi e crea **l'icona sul desktop e nel menu Start**.
5. **Collega Claude**: abbonamento (consigliato) o chiave API, modello (Sonnet/Opus/Haiku), pulsanti
   *Accedi a Claude* e *Prova collegamento*.
6. Fine, con la casella **Avvia BIG-BOB**.

Windows può mostrare "PC protetto da Windows" perché l'installer non è firmato: *Ulteriori informazioni → Esegui
comunque*. BIG-BOB compare in **Impostazioni → App installate**, da dove si disinstalla (ti chiede se tenere i dati).

## Aggiornamenti: te lo dice lui
A **ogni avvio** (e ogni 3 ore se BIG-BOB resta aperto) controlla se c'è una versione nuova: se c'è si apre la finestra
con le novità e **AGGIORNA ORA** (in partita basta la barra); se è tutto a posto lo dice nella riga di stato; se il
controllo non riesce compare una barra rossa con il motivo. AGGIORNA ORA scarica solo le differenze, si chiude e si
riapre da solo con «Aggiornamento completato» (i tuoi dati non vengono toccati). Anche da ⚙ → Controlla aggiornamenti.

## Modalità CREAZIONE MAZZO
Il pulsante della modalità gira tra **ALLENAMENTO → RANKED → CREAZIONE**. In creazione compare il pannello **LABORATORIO**:
1. **CREA MAZZO**: scrivi cosa vuoi (una leggendaria, uno stile… o niente) e quante partite di test per versione.
   BIG-BOB studia il meta di OriginsMeta (statistiche, liste migliori e le loro guide), confronta 2-3 candidati e crea
   il mazzo **v1**, dicendoti le carte da costruire nel gioco e da quali mazzi meta parte.
2. **Partite di test**: con NUOVA scegli il mazzo del laboratorio (è il primo della lista). In partita ti consiglia le
   mosse come in allenamento; ogni partita conta per la versione attuale. Il pannello mostra partite fatte/necessarie,
   vittorie e quante ne mancano.
3. **A fine partita** valuta il mazzo: quando il test della versione è finito trova il punto debole principale (carte che
   restano in mano, che entrano tardi, con cui perdi; matchup; lezioni) e propone **una** miglioria guardando anche le
   carte che rendono nel meta. Tu la costruisci nel gioco e premi **APPLICA MIGLIORIA**: nasce la versione successiva.
4. **Quante partite**: 10 per la v1 e per i cambi grandi, 8 per il cambio di una carta (le scegli tu o BIG-BOB). Se dopo
   almeno 6 partite il confronto con la versione precedente è già netto (90%), il test finisce prima. Se una versione va
   peggio, ti propone di tornare indietro.
5. **STATISTICHE DEL MAZZO**: per ogni versione vittorie, winrate con l'intervallo di confidenza, cosa è cambiato e
   perché; per le carte pescata/giocata, winrate quando giocata e non, round medio; risultati contro ogni leggendaria.
Con poche partite il winrate oscilla molto (±30 punti con 10 partite): per questo BIG-BOB guarda anche carte, matchup
e lezioni prima di cambiare il mazzo. Il comando `/mazzo` in Claude Code può creare un progetto allo stesso modo.

## Carte, location e meta da OriginsMeta (automatico)
BIG-BOB legge da solo [originsmeta.com](https://originsmeta.com) al **primo avvio di ogni giorno** (gli avvii successivi
non scaricano niente; se il sito non risponde riprova all'avvio dopo; subito, se il database delle carte è vuoto):
- **carte e location**: aggiunge quelle che mancano; i cambiamenti di costo/attacco/vita diventano una patch
  "<versione> (OriginsMeta)" con lo storico. Un testo corretto da te (o letto dalle schermate) non viene più sovrascritto;
- **mazzi** pubblicati e da torneo, con winrate, partite, valutazione, versione e guida: pesano nelle probabilità
  sulla mano avversaria e Claude Code li usa in `/mazzo` e `/meta`;
- **statistiche** delle partite registrate: winrate e diffusione per leggendaria, archetipo e carta, griglia dei matchup.

Scarica solo pagine pubbliche, una al secondo, e riscarica un mazzo solo se è nuovo o cambiato. A mano:
⚙ → *Aggiorna meta ora*, oppure `python -m origins.originsmeta --forza`. Se qualcosa non viene letto bene,
`python -m origins.originsmeta --forza --salva-pagine` salva le pagine in `logs/originsmeta/` da mandarmi.
Le regole confermate nell'intervista vengono con BIG-BOB: anche un'installazione nuova parte con il regolamento.

## Cervello comune (tutti i BIG-BOB imparano insieme)
Ogni BIG-BOB invia, in forma anonima, ciò che impara e riceve ciò che hanno imparato gli altri:
- **si invia**: regole del regolamento (con stato e prove), lezioni, testi di carte e location verificati sullo schermo,
  partite finite (leggendarie, risultato, round, le tue carte, le carte avversarie viste). Niente nomi, account, email,
  schermate, percorsi o chiavi: chi invia è un codice casuale (`data/cervello_stato.json`) di cui il server salva
  solo un hash. Si invia solo ciò che è cambiato, a ogni avvio (al massimo ogni 3 ore) e a fine partita/studio;
- **si riceve**: regole e lezioni con quanti giocatori le hanno confermate (una regola diventa ✅ quando la confermano
  2 giocatori diversi), testi di carte concordi, mazzi avversari più visti, winrate per leggendaria e matchup.
  Restano separati in `data/cervello.json`: il tuo regolamento e le tue lezioni non vengono toccati. Claude li vede
  con id `C…`/`CL…` e nello Studio c'è la sezione *Cervello comune*. Si uniscono ai tuoi dati solo i testi delle
  carte prese dal sito (mai quelle che hai verificato tu) e i mazzi avversari (pesano nelle probabilità).
- Al primo collegamento BIG-BOB chiede il consenso; poi ⚙ → *Cervello comune* per spegnere invio o ricezione.

**Il server (solo per chi lo gestisce)**: `pubblica_cervello.bat` lo pubblica sul tuo account Cloudflare (piano
gratuito): installa lo strumento di Cloudflare, ti fa accedere dal browser, crea il database, genera la chiave di
amministrazione (resta in `config.json`) e scrive l'indirizzo nelle impostazioni. Si rilancia per aggiornarlo.
Moderazione: `python -m origins.cervello admin panoramica` (ultimi giocatori, regole e lezioni),
`admin regola C12 --nascondi`, `admin regola C12 --testo "…"`, `admin regola C12 --unisci-in C3`,
`admin nascondi carta "Marian"`, `admin banna <hash>`, `admin ricalcola`. Dettagli in `cloud/README.md`.

## Impostazioni (icona a ingranaggio)
- **Collegamento a Claude**: abbonamento Claude (Claude Code con il tuo account, consigliato) oppure chiave API Anthropic
  (a consumo; la chiave resta solo nel tuo `config.json`). Con l'abbonamento BIG-BOB ignora eventuali chiavi API
  rimaste nel sistema, così non paghi a consumo per errore. *Accedi a Claude* apre Claude Code per il login,
  *Prova collegamento* verifica che risponda.
- **Modello per le risposte live**: Sonnet (veloce, consigliato), Opus (più preciso ma rischia i 40 s), Haiku (velocissimo).
- Voce, apprendimento tra i round, Claude Code all'avvio, controllo aggiornamenti, tetto di ragionamento.
- **Cervello comune**: contribuisci (invio anonimo) e usa la conoscenza degli altri, con *Sincronizza ora*.

## Avvio: un'icona
Clicca l'icona **BIG-BOB** (desktop, menu Start, o fissala sulla barra delle applicazioni: tasto destro → Aggiungi alla
barra delle applicazioni). Si apre la finestra di BIG-BOB. Il Claude Code che risponde a F8 è dentro la finestra e parte da
solo, invisibile. Il terminale di **Claude Code** serve solo per i comandi (`/scansiona`, `/mazzo`, `/lezioni`…): lo apri
quando serve con il pulsante **>_** della finestra (o dal menu Start → Claude Code (BIG-BOB)), e puoi chiuderlo quando vuoi.
Se lo vuoi sempre all'avvio: ⚙ → *Apri anche il terminale di Claude Code all'avvio*.
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
In alto: **round, mana, chi rivela prima**; la **barra di vantaggio** (stile scacchi: tu teal, avversario arancione) con la
probabilità di vincere; le **6 barrier** (giallo = a rischio, RINF. = rinforzata, max 40) con le barrier distrutte; i
**contatori** di carte nel mazzo e in mano per te e per l'avversario. Sotto, la card **LA MOSSA** e le card di minaccia,
pescata, mano avversaria e location.

**Tasti in alto** (da sinistra): ⚙ impostazioni · **>_** terminale di Claude Code · audio (legge la mossa) · **libro**
(mazzi, statistiche, studio) · **Origin** (mazzi del meta) · **–** riduci (F10 per riaprire) · **×** chiudi.
Al primo avvio un **tutorial** spiega ogni tasto; si rivede da ⚙ → RIVEDI IL TUTORIAL.

| Tasto | Cosa fa |
|---|---|
| **Modalità** | ALLENAMENTO (consigli) → RANKED (solo numeri) → CREAZIONE (BIG-BOB crea e migliora un mazzo) |
| **NUOVA** | scegli il mazzo (o scrivi "leggilo dallo schermo e salvalo come X"): Claude inizia a tracciare |
| **F8** | analisi del round: cattura il gioco e risponde con mossa, minacce e probabilità |
| chat | domande libere ("se gioca X al centro cosa faccio?", "probabilità di pescare Y in 2 round?") |
| **REGISTRA** | salva la partita per studiarla dopo (libro → STUDIO), senza chiamare Claude |
| **AUTO** | analizza da solo quando lo schermo cambia |
| **FINE** | registra risultato e mazzo avversario, impara dalla partita, ferma REGISTRA e AUTO |
| **F9** | cattura per la scansione delle carte |
| **✕** | segnala che l'ultima risposta era sbagliata (diventa una lezione a fine partita) |

**Osservatore**: durante la partita BIG-BOB salva da solo un fotogramma leggero a ogni schermata nuova (rivelazioni,
combattimento, scarti), senza chiamare Claude e senza far lampeggiare la finestra. All'F8 successivo Claude riceve i più
significativi (al massimo 6): così sa delle magie lanciate e scartate e delle creature morte tra un turno e l'altro, e
contatori e probabilità restano veri. Le carte create da effetti (Spellbook, carta del potere leggendario…) sono tenute a
parte e non falsano le carte rimaste. Si spegne da ⚙.

**Barra di vantaggio**: subito dopo ogni analisi c'è una stima rapida fatta coi numeri (barrier, campo, previsione del
combattimento, carte in mano); poi, mentre leggi la mossa, BIG-BOB la rifinisce in background ragionando su carte,
location e mano probabile dell'avversario. Non rallenta la risposta. Si spegne da ⚙.

Mentre pensa compare un riquadro di **caricamento** con il passaggio in corso e i secondi (l'obiettivo dei 40 s vale solo
in partita). La finestra mostra solo la **richiesta attuale**: le risposte passate restano nel diario e in RIVEDI.

**Il libro** (si apre in una finestra di BIG-BOB, non nel browser) ha tre schede:
- **MAZZI**: tutti i mazzi salvati con winrate, partite e ultima partita; cerca e ordina. Cliccandone uno: carte, winrate
  con il suo margine, punti deboli, statistiche carta per carta, risultati contro ogni leggendaria, ultime partite; per i
  mazzi del laboratorio la storia delle versioni.
- **STATISTICHE**: winrate per mazzo, avversario e location, tempi di risposta, consigli seguiti.
- **STUDIO**: **STUDIA REGISTRAZIONI** fa studiare a BIG-BOB tutte le registrazioni in sospeso, in background: ne ricava
  regole del gioco e **lezioni di strategia** (chi ha vinto e perché, giocate decisive, errori ricorrenti, abitudini degli
  avversari); con una partita in corso parte a fine partita. Sotto, **cosa ho imparato** partita per partita.

**Origin**: i mazzi del meta presi da OriginsMeta (lista con winrate, partite, valutazione, autore; filtri per leggendaria
e archetipo; dettaglio con carte, descrizione e guida), la tabella delle leggendarie, AGGIORNA ORA e il collegamento al sito.

**Consumi**: se sei collegato con una **chiave API** (pagamento a consumo) in basso vedi quanto hai speso oggi e nel mese.
Con l'abbonamento non compare. Per spendere meno, BIG-BOB in partita carica solo gli strumenti che servono: il contesto
fisso è passato da ~87.000 a ~18.000 token (avvio sessione −77%, ogni F8 circa −35%).

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
`strategia.md` (idee da video e analisi), `cervello.json` (conoscenza comune scaricata) e `cervello_stato.json`
(codice anonimo e cosa è già stato inviato). Schermate, registrazioni e video sono in `captures/`.

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
