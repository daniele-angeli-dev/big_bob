"""Logica di BIG-BOB, indipendente dalla grafica.

La finestra (app.py, HTML) chiama i metodi pubblici; il controller risponde emettendo eventi
{"type": ..., ...} verso la finestra tramite ui.emit(). Tutte le azioni passano da una coda
servita da un solo thread, quindi tasti, pulsanti e modalità Auto non si pestano i piedi.

Interfaccia richiesta a `ui`: emit(dict), hide(), show(), is_visible() -> bool,
rect() -> (x, y, w, h) | None.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from PIL import Image

from origins import deckproj, evaluate, screen, store, usage
from origins.voice import Voice

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("bigbob")

ROUND_SECONDS = 90
BUDGET_SECONDS = 40  # tempo massimo per la risposta: il resto serve a leggere e giocare

PROMPT_STORIA = (
    "[CRONOLOGIA] Daniele sta rivedendo una partita finita nel libro (scheda PARTITE) e parla con te. È analisi "
    "post-partita: i consigli di mossa sono permessi anche se la partita era ranked. È anche il momento in cui impari di "
    "più: Daniele è il giocatore e sa cose che tu non vedevi (le sue intenzioni, come funzionano davvero carte e regole, "
    "cosa ha fatto l'avversario).\n\n{contesto}\n\nDaniele: {domanda}\n\n"
    "Come rispondere (testo semplice, niente markdown, al massimo 10 righe):\n"
    "1. Rispondi: spiega il ragionamento con i numeri di allora (barrier, mana, carte probabili) e, ora che sai com'è "
    "andata, di' onestamente se il consiglio era giusto e cosa avresti fatto di diverso. Se serve usa get_card, "
    "rules_get, lessons_get o simulate_combat; non inventare dati di carte.\n"
    "2. Verifica, poi impara. Daniele può sbagliare quanto te: prima di dargli ragione controlla con i dati (get_card "
    "per testi e statistiche, rules_get, simulate_combat per i conti, com'è finita davvero la partita).\n"
    "- Se i dati gli danno ragione, dillo e registralo: record_lesson con fonte \"Daniele\" (diventa confermata) solo "
    "per FATTI del gioco verificati o non contraddetti dai dati (come funziona una carta o una regola, cosa ha fatto "
    "l'avversario); per opinioni di strategia o giocate alternative non dimostrate usa fonte \"Daniele (opinione)\": "
    "resta un'ipotesi finché le partite non la confermano. Tipo errore_coach se il tuo consiglio era davvero sbagliato, "
    "mossa_vincente se la sua giocata era davvero migliore, altrimenti interazione / mossa_avversaria / strategia; una "
    "frase pratica e generale con le carte coinvolte. rules_upsert (fonte \"Daniele\") per una regola del gioco, "
    "upsert_cards se il testo di una carta era sbagliato, lesson_review se conferma o smentisce una lezione esistente.\n"
    "- Se i dati dicono altro, diglielo chiaramente e con i numeri (es. «no: anche con Marian al centro il Bat passava, "
    "3 danni contro 1 di vita») e NON registrare la lezione; se resta un dubbio vero, registrala come ipotesi (fonte "
    "\"Daniele (opinione)\") e proponi come verificarla nella prossima partita.\n"
    "- Non cambiare idea solo perché insiste: cambia idea per un fatto nuovo o un conto sbagliato, e di' quale. Le "
    "lezioni finiscono nel cervello comune di tutti i giocatori: una lezione sbagliata fa danni anche a loro.\n"
    "Tono: diretto e rispettoso, da coach onesto; niente complimenti di circostanza, niente «hai ragione» se non è "
    "così.\n"
    "3. Chiudi con UNA domanda breve a Daniele, su una riga che inizia con «❓», per capire qualcosa che non sai di "
    "questa situazione (perché ha scelto un'altra giocata, cosa temeva, se una carta ha fatto ciò che ti aspettavi…). "
    "Se non c'è niente da chiedere, non chiedere."
)

PROMPT_STORIA_SEGUITO = (
    "[CRONOLOGIA · seguito] Daniele continua a parlarti della stessa {cosa}: {domanda}\n"
    "Stesse regole: rispondi in breve; prima di dargli ragione verifica con i dati e, se sbaglia, diglielo con i "
    "numeri; registra solo ciò che regge (fatti verificati: fonte \"Daniele\"; opinioni non dimostrate: fonte "
    "\"Daniele (opinione)\") e chiudi con una ❓ solo se c'è ancora qualcosa da capire."
)

PROMPT_TURNO = (
    "[F8 · analisi round] La schermata del round è allegata: NON chiamare get_screen. Leggila e chiama UNA "
    "volta update_match con lo stato completo (mano, campo, scarti, mana, vita delle barrier e quali sono "
    "rinforzate, barrier distrutte, chi rivela prima, carte rimaste nei due mazzi e in mano a entrambi se il gioco le "
    "mostra; le carte giocate da quando hai risposto l'ultima volta vanno in my_played_new / opp_played_new, con le "
    "copie ripetute): "
    "ti restituisce anche le probabilità aggiornate. Poi rispondi nel formato 'Risposta live' di CLAUDE.md. "
    "Se non c'è una partita attiva e dallo schermo non capisci il mio mazzo, chiedimelo in una riga. "
    "Tempo massimo 40 secondi. Modalità attuale: {mode}."
)
PROMPT_TURNO_LETTO = (
    "[F8 · analisi round · schermata già letta] Due lettori hanno già trascritto la schermata e BIG-BOB ha già chiamato "
    "update_match: il risultato è qui sotto (stato, contatori, combattimento previsto, probabilità, mazzo e previsione "
    "avversaria, lezioni). NON chiamare update_match di nuovo, a meno che nella schermata allegata vedi un errore di "
    "lettura che cambia la mossa (allora correggi solo quel campo). Le MOSSE CALCOLATE sono già simulate (anche "
    "contro la risposta avversaria più dannosa): scegli tra quelle, correggendo con gli effetti delle carte che il "
    "simulatore non conosce e con le magie; simulate_combat solo se un effetto non simulato cambia tutto. Poi "
    "rispondi subito nel formato 'Risposta live' di CLAUDE.md. Modalità attuale: {mode}.\n"
    "{recenti}"
    "Avvisi della lettura: {avvisi}\n\n"
    "RISULTATO DI update_match:\n{stato}"
)
PROMPT_AUTO = (
    "[AUTO · lo schermo è cambiato] La schermata è allegata: NON chiamare get_screen. Se è iniziato un nuovo "
    "round o sono state rivelate carte, chiama UNA volta update_match e rispondi nel formato 'Risposta live' "
    "(modalità {mode}). Se non è cambiato niente di rilevante rispondi solo: '—'."
)
PROMPT_OSSERVATORE = (
    "[OSSERVATORE] Prima della schermata attuale trovi {n} presi da BIG-BOB da quando hai risposto "
    "l'ultima volta, in ordine di tempo, ognuno con orario e zona dello schermo: di solito sono RITAGLI ad alta "
    "risoluzione della sola zona cambiata (leggi i nomi delle carte); quando sono tanti sono affiancati in fogli con i "
    "ritagli numerati [1], [2]… nello stesso ordine, alcuni presi durante le animazioni (BIG-BOB di solito è invisibile alle catture; se vedi "
    "una zona nera, è la sua finestra). Guardali tutti per ricostruire cosa è successo nel frattempo: carte rivelate o giocate dall'avversario anche se poi distrutte o scartate, magie lanciate, "
    "creature morte in combattimento, carte pescate o create da effetti (Spellbook e simili), barrier colpite. Metti "
    "tutto in update_match (opp_played_new / my_played_new per le carte giocate da allora, opp_discarded / "
    "my_discarded, opp_created / my_created per quelle create da effetti): così i contatori e le "
    "probabilità restano veri. "
)
PROMPT_STUDIO = (
    "[STUDIO DELLE REGISTRAZIONI · in background] Studia le registrazioni non ancora elaborate (list_recordings), dalla "
    "più vecchia, una alla volta ({n} in tutto). Per ciascuna segui il metodo di /impara-regole: fotogrammi in ordine, "
    "10 alla volta (recording_frames, poi Read), appunti round per round. Ne ricavi due cose.\n"
    "1) REGOLE: rules_upsert con fonte \"osservazione <nome registrazione>\" e la prova (round e fotogramma); una sola "
    "osservazione = probabile; mai confermata una cosa solo dedotta.\n"
    "2) STRATEGIA: chi ha vinto e perché, le giocate che hanno spostato la partita (corsia scelta, tempi, colpi di "
    "chiusura, difese mancate), errori ricorrenti di Daniele, abitudini dell'avversario, come hanno reso le carte del "
    "mazzo. Per ognuna record_lesson (tipo strategia, mossa_avversaria o mossa_vincente; carte coinvolte; fonte "
    "\"registrazione <nome>\"): una frase pratica e generale per la prossima volta, non la cronaca.\n"
    "Poi mark_recording_done con un riassunto di 3 righe (regole + strategia). Alla fine rispondi in testo semplice, "
    "senza markdown: per ogni registrazione 2 righe con cosa hai imparato."
)
PROMPT_CHAT = "{text}\n\n(Modalità: {mode}. Se ti serve vedere la partita usa get_screen.)"
PROMPT_CREA = (
    "[CREAZIONE MAZZO] Daniele vuole che tu crei un mazzo nuovo da mettere alla prova con le partite di allenamento. "
    "Richiesta: {goal}. Segui la sezione 'Creazione mazzo' di CLAUDE.md: guarda il meta (community_stats, "
    "community_decks delle leggendarie più forti e community_deck delle 2-3 liste migliori), le carte "
    "(card_pool_compact), le lezioni (lessons_get) e il regolamento; confronta 2-3 candidati con deck_lab; poi crea il "
    "progetto con deck_project_start (nome breve e riconoscibile, motivo = piano di gioco, fonti = i mazzi meta da cui "
    "parti, partite = {games}). Rispondi in testo semplice, senza markdown, massimo 12 righe: nome, leggendaria e le 12 "
    "carte da costruire nel gioco, il piano in 2 righe, da quali mazzi meta parte e cosa cambia rispetto a loro, quante "
    "partite di test servono. Chiudi ricordando di costruirlo nel gioco e di sceglierlo con NUOVA."
)
PROMPT_FINE_TEST = (
    " Questa partita era un TEST del progetto «{nome}» versione {v} (modalità creazione mazzo). Chiama "
    "deck_project_status. Se mancano ancora partite di test, aggiungi una riga con cosa stai osservando sul mazzo e "
    "quante partite mancano. Se il test della versione è finito (partite_mancanti 0), trova il punto debole principale "
    "(punti_deboli, statistiche delle carte, matchup, lezioni; per i sostituti guarda community_stats delle carte e i "
    "mazzi meta della stessa leggendaria con community_decks) e chiama deck_project_propose con UNA miglioria precisa "
    "(1-2 carte) e il suo motivo; se la versione va peggio della precedente proponi di tornare indietro. In quel caso "
    "scrivi anche la miglioria e il motivo in 2 righe."
)
PROMPT_IMPARA = (
    "[APPRENDIMENTO · in background: Daniele non sta aspettando questa risposta] Confronta ciò che avevi "
    "previsto al round precedente (la tua risposta e le probabilità) con ciò che la schermata di questo round "
    "mostra che è successo davvero. Cerca solo sorprese vere: (a) l'avversario ha giocato qualcosa, o in un modo, "
    "che non avevi considerato; (b) una carta o una location ha avuto un effetto diverso da come lo intendevi; "
    "(c) la mossa che avevi consigliato non ha funzionato; (d) Daniele ha giocato diversamente dal consiglio e ha "
    "funzionato meglio. Per ogni sorpresa capisci il PERCHÉ e chiama record_lesson con una frase pratica e "
    "generale, utile la prossima volta (non il racconto del round), il tipo giusto, le carte coinvolte, "
    "situazione/accaduto/perche e fonte \"partita R<numero round>\". Se la sorpresa rivela una regola usa anche "
    "rules_upsert; se una carta fa qualcosa di diverso dal suo testo aggiungi una nota con upsert_cards. Se le lezioni "
    "già imparate che ti ho mostrato si sono dimostrate sbagliate, usa lesson_review. Infine chiama note_round per "
    "il round precedente: se Daniele ha seguito il tuo consiglio (true/false, null se non si capisce) e com'è andata "
    "('bene'/'male'/'neutro' + mezza riga). Se non c'è nessuna sorpresa non chiamare record_lesson. "
    "Quando una lezione vale solo in certe situazioni passa anche condizioni (mana, round, tipo di mazzo avversario, "
    "leggendarie, corsia): così torna fuori solo quando serve.\n{contesto}"
    "{valuta}Rispondi in una sola riga: 'ok' oppure cosa hai imparato."
)
PROMPT_VALUTA = (
    "Infine chiama set_match_eval con la probabilità (1-99) che Daniele vinca la partita: parti dalla STIMA RAPIDA "
    "di update_match e correggila con quello che i numeri non vedono (cosa fanno le carte in campo e in mano, location, "
    "carte probabili dell'avversario, chi rivela prima, fatica), motivo in mezza riga, e campo / mano / barrier "
    "(vantaggio, parità o svantaggio di Daniele su ciascun fronte). "
)
PROMPT_SOLO_VALUTA = (
    "[VALUTAZIONE · in background: Daniele non sta aspettando questa risposta] " + PROMPT_VALUTA
    + "Non chiamare altri strumenti. Rispondi solo: ok"
)


SYSTEM_PROMPT = (
    "Sei BIG-BOB, il coach di Daniele per Origins TCG (gioco di carte digitale di Koin Games). Segui alla lettera le "
    "istruzioni del progetto (CLAUDE.md): regole del gioco, formato delle risposte, modalità, regole sui dati. "
    "Rispondi sempre in italiano. Lavori solo con gli strumenti mcp__origins (database di carte, partita, probabilità, "
    "simulazioni, lezioni, meta) e con Read per guardare immagini: non inventare mai dati di carte né probabilità, "
    "prendili dagli strumenti. Sii conciso e onesto: se Daniele sbaglia, diglielo con i numeri; non dargli ragione "
    "per compiacerlo."
)


def find_claude() -> str | None:
    import configura
    return configura.find_claude()


class ClaudeSession:
    """Un processo Claude Code acceso per tutta la partita (stream-json in ingresso e in uscita).

    Evita a ogni F8 l'avvio di Claude Code, del server MCP e il ricaricamento della sessione.
    Se il processo muore, al turno dopo ne parte un altro che riprende la stessa sessione."""

    PARTIAL = True  # --include-partial-messages; si spegne da solo se la versione di Claude Code non lo conosce

    def __init__(self, exe: str, cwd: Path, live: bool = True) -> None:
        self.exe, self.cwd, self.live = exe, cwd, live
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def _mcp_config(self) -> Path:
        """In partita solo gli strumenti di partita (BIGBOB_TOOLSET=live): contesto più piccolo, risposte più economiche."""
        full = self.cwd / ".mcp.json"
        if not self.live or not full.exists():
            return full
        live = self.cwd / ".mcp-live.json"
        try:
            cfg = json.loads(full.read_text(encoding="utf-8"))
            for srv in cfg.get("mcpServers", {}).values():
                srv["env"] = {**(srv.get("env") or {}), "BIGBOB_TOOLSET": "live"}
            text = json.dumps(cfg, indent=2)
            if not live.exists() or live.read_text(encoding="utf-8") != text:
                live.write_text(text, encoding="utf-8")
            return live
        except Exception:  # noqa: BLE001
            log.exception(".mcp-live.json non scritto: uso tutti gli strumenti")
            return full

    def _cmd(self) -> list[str]:
        cfg = store.load("config")
        # solo Read tra gli strumenti di Claude Code (servono quelli di BIG-BOB) e istruzioni di sistema brevi: le regole
        # vere sono in CLAUDE.md, che Claude Code carica comunque. Contesto fisso da ~87.000 a ~18.000 token.
        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               *(["--include-partial-messages"] if ClaudeSession.PARTIAL else []),  # la riga ▶ arriva mentre è scritta
               "--model", cfg.get("modello_live", "sonnet"),
               "--mcp-config", str(self._mcp_config()), "--strict-mcp-config",
               "--tools", "Read", "--system-prompt", SYSTEM_PROMPT,
               "--allowedTools", "mcp__origins", "Read"]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        return cmd

    def _env(self) -> dict:
        import os
        cfg = store.load("config")
        import configura
        # abbonamento: una chiave API rimasta nel sistema farebbe pagare a consumo senza accorgersene
        env = configura.claude_env(cfg)
        env["ENABLE_TOOL_SEARCH"] = "false"  # strumenti di BIG-BOB caricati subito: niente passaggio ToolSearch
        # cintura di sicurezza: i round normali usano ~2.500-3.000 token, il tetto ferma solo i casi
        # patologici così la risposta resta sotto i 40 secondi (≈7,5 ms per token + ~6 s fissi)
        mt = getattr(self, "thinking", None) or cfg.get("max_thinking_live", 4000)
        if mt and self.live:  # il tetto vale solo per le risposte in partita, non per creare mazzi
            env["MAX_THINKING_TOKENS"] = str(mt)
        else:
            env.pop("MAX_THINKING_TOKENS", None)
        return env

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure(self) -> None:
        with self._lock:
            if self.alive():
                return
            self._q = queue.Queue()
            self.proc = subprocess.Popen(self._cmd(), cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=self._env(),
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log.info("processo Claude avviato (pid %s, sessione %s)", self.proc.pid, self.session_id)
            proc, q = self.proc, self._q

            def reader():
                for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("session_id"):
                        self.session_id = ev["session_id"]
                    q.put(ev)
                q.put({"type": "_eof"})

            threading.Thread(target=reader, daemon=True, name="bb-claude-reader").start()

    def reset(self) -> None:
        """Nuova partita: chiude il processo e dimentica la sessione."""
        self.close()
        self.session_id = None

    def close(self) -> None:
        with self._lock:
            if self.alive():
                try:
                    self.proc.stdin.close()
                    self.proc.wait(timeout=3)
                except Exception:  # noqa: BLE001
                    self.proc.kill()
            self.proc = None

    def ask(self, content: list[dict], timeout: float = 120.0):
        """Invia un messaggio e restituisce gli eventi fino al risultato (generatore)."""
        self.ensure()
        msg = {"type": "user", "message": {"role": "user", "content": content}}
        try:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.close()
            self.ensure()
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        deadline = time.time() + timeout
        while True:
            try:
                ev = self._q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                self.close()
                raise TimeoutError(f"nessuna risposta in {int(timeout)} s: riavvio Claude Code")
            if ev.get("type") == "_eof":
                err = b""
                try:
                    err = self.proc.stderr.read() if self.proc else b""
                except Exception:  # noqa: BLE001
                    pass
                self.proc = None
                text = err.decode("utf-8", "replace")
                if ClaudeSession.PARTIAL and "include-partial-messages" in text:
                    # Claude Code vecchio: niente anteprima della mossa, ma tutto il resto funziona
                    ClaudeSession.PARTIAL = False
                    log.warning("--include-partial-messages non supportato: anteprima della mossa spenta")
                    yield from self.ask(content, max(5.0, deadline - time.time()))
                    return
                raise RuntimeError("Claude Code si è chiuso: " + text[-400:])
            yield ev
            if ev.get("type") == "result":
                return


# ---------------------------------------------------------------- parser risposta live

class ReaderSession(ClaudeSession):
    """Un lettore della schermata (sottoagente): sessione minima, senza CLAUDE.md, senza server MCP, senza ragionamento
    esteso. Legge un'immagine e risponde con un JSON. Ogni lettura parte da una sessione nuova (niente storia)."""

    MODELLO = {"mio": "haiku", "avv": "sonnet"}  # il tuo lato è facile (conosce le 13 carte del tuo mazzo): Haiku

    def __init__(self, exe: str, root: Path, side: str = "avv") -> None:
        cwd = root / "logs" / "lettore"  # cartella vuota: niente CLAUDE.md del progetto da caricare
        cwd.mkdir(parents=True, exist_ok=True)
        super().__init__(exe, cwd, live=False)
        self.side = side

    def _cmd(self) -> list[str]:
        from origins import reader
        cfg = store.load("config")
        empty = self.cwd / "nessun-server.json"  # nessun server MCP: il lettore non usa strumenti
        if not empty.exists():
            empty.write_text('{"mcpServers": {}}', encoding="utf-8")
        return [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--model", cfg.get(f"modello_lettura_{self.side}") or self.MODELLO.get(self.side, "sonnet"),
                "--mcp-config", str(empty), "--strict-mcp-config", "--tools", "Read",
                "--system-prompt", reader.SYSTEM]

    def _env(self) -> dict:
        import configura
        env = configura.claude_env(store.load("config"))
        env.pop("MAX_THINKING_TOKENS", None)
        return env

    def read(self, content: list[dict], timeout: float = 25.0) -> str:
        """Testo della risposta ('' se fallisce). Poi la sessione si chiude: la prossima lettura riparte pulita."""
        text = ""
        try:
            for ev in self.ask(content, timeout=timeout):
                if ev.get("type") == "result":
                    text = (ev.get("result") or "").strip()
                    usage.add_from_result(ev, self)
        except Exception:  # noqa: BLE001
            log.exception("lettura della schermata fallita")
        finally:
            self.reset()
        return text


MARKERS = {"▶": "mossa", "⚠": "minacce", "🎴": "pescate", "👁": "avv_mano", "📍": "location", "🤖": "pilota"}

PROMPT_PILOTA = (
    "\n[PILOTA AUTOMATICO ATTIVO] In questa partita giochi TU al posto di Daniele: le tue azioni vengono eseguite con "
    "il mouse. Dopo le righe della risposta live aggiungi SEMPRE come ULTIMA riga (non conta nelle 5 righe, e serve "
    "anche se rispondi in breve) una riga che inizia con 🤖 con le azioni "
    "sulla schermata allegata (l'ultima immagine), separate da ' ; ': 'trascina X1,Y1 > X2,Y2' per portare una carta "
    "dalla mano allo spazio del campo, 'clicca X,Y' per pulsanti (fine turno / conferma, Keep, carte da cambiare nel "
    "mulligan). X e Y sono in PERCENTUALE della larghezza e dell'altezza della schermata allegata (0-100, una cifra "
    "decimale), al centro dell'elemento: guarda bene dove sono la carta e lo spazio. Prima le carte nell'ordine in cui "
    "vuoi che si attivino, poi il pulsante che conferma il turno. Solo carte che puoi pagare con il mana di adesso; se "
    "giocando una carta la mano si sposta, considera che le carte a destra scorrono. Se non è la tua fase di gioco "
    "(animazioni, attesa dell'avversario, combattimento, schermata di fine) o hai già confermato il turno, scrivi "
    "'🤖 niente'. Se nella schermata vedi che una tua azione di prima non è riuscita (carta ancora in mano), ripetila "
    "con coordinate corrette."
)


def thinking_budget(m: dict, cfg: dict) -> tuple[int, str]:
    """Quanto ragionare nel prossimo round: poco nei round facili, di più in quelli decisivi. Base = max_thinking_live.
    Decisivo: una barrier non rinforzata a 8 o meno, o una barrier già distrutta da una parte e un'altra sotto metà
    (la partita si chiude a 2), o tardi nella partita. Facile: primi round con poche carte giocabili."""
    base = int(cfg.get("max_thinking_live", 4000) or 4000)
    if not cfg.get("ragionamento_dosato", True) or not m:
        return base, "fisso"
    bm = [b for b in (m.get("barrier_mie") or []) if isinstance(b, (int, float))]
    bo = [b for b in (m.get("barrier_avv") or []) if isinstance(b, (int, float))]
    low_any = any(b <= 8 for b in bm + bo)
    by, to = m.get("distrutte_da_me") or 0, m.get("distrutte_a_me") or 0
    close = (by >= 1 and any(b <= 12 for b in bo)) or (to >= 1 and any(b <= 12 for b in bm))
    turn = m.get("turno") if isinstance(m.get("turno"), int) else 0
    if low_any or close or turn >= 8:
        return min(12000, int(base * 2)), "round decisivo"
    if turn and turn <= 2:
        return max(1024, int(base * 0.4)), "round iniziale"
    return base, "normale"


def preview_move(text: str) -> dict | None:
    """Dalla risposta mentre viene scritta: la riga ▶ appena è completa (e il perché, se è già arrivato)."""
    lines = text.split("\n")
    for n, line in enumerate(lines[:-1]):  # solo righe finite (l'ultima può essere a metà)
        s = line.strip()
        if s.startswith("▶"):
            mossa = s.lstrip("▶").strip()
            if not mossa:
                return None
            why = ""
            if n + 1 < len(lines) - 1 and lines[n + 1].strip().lower().startswith(("perché:", "perche:")):
                why = lines[n + 1].split(":", 1)[1].strip()
            return {"mossa": mossa, "perche": why}
    return None


def parse_live(text: str) -> dict | None:
    """Scompone una 'Risposta live' (vedi CLAUDE.md) in parti per la card. None se non è in quel formato."""
    out: dict = {"mossa": None, "perche": None, "minacce": [], "pescate": [], "avv_mano": [],
                 "location": [], "altro": []}
    found = False
    last = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        key = next((k for m, k in MARKERS.items() if line.startswith(m)), None)
        if key:
            found = True
            body = line[1:].strip().lstrip("️").strip()
            body = re.sub(r"^(Giocata|Mossa|Avversario|Prossima pescata|Pescata|Location)\s*:\s*", "", body, flags=re.I)
            if key == "pilota":
                continue
            if key == "mossa":
                if " — " in body and not out["mossa"]:
                    body, why = body.split(" — ", 1)
                    out["perche"] = why.strip()
                out["mossa"] = body.strip()
            else:
                out[key].append(body)
            last = key
            continue
        low = line.lower()
        if low.startswith(("perché:", "perche:", "motivo:")) and last == "mossa":
            out["perche"] = line.split(":", 1)[1].strip()
        elif re.match(r"^R\d+\s*·", line) or re.match(r"^T\d+\s*·", line):
            continue  # intestazione: la mostra già l'HUD
        else:
            out["altro"].append(line)
    return out if found else None


# ---------------------------------------------------------------- controller
class Controller:
    def __init__(self, ui) -> None:
        self.ui = ui
        self.claude = find_claude()
        if self.claude:
            try:
                import configura
                configura.ensure_claude_on_path(self.claude)  # claude trovato ma non nel PATH: lo aggiungo
            except Exception:  # noqa: BLE001
                log.exception("PATH di Claude Code")
        self.session = ClaudeSession(self.claude, ROOT) if self.claude else None
        self.voice = Voice()
        cfg = store.load("config")
        store.save("config", cfg)  # crea config.json se manca
        self.busy = False
        self.capturing = False
        self.last_call = 0.0
        self.last_capture = 0.0
        self.auto_on = False
        self.pilot_on = False          # pilota automatico: BIG-BOB gioca al posto di Daniele (mai in ranked)
        self._pilot_stop = False
        self._pilot_rounds: dict = {}
        self._shot_region = None       # regione dello schermo della schermata mandata a Claude (per le coordinate)
        self.readers = ({"mio": ReaderSession(self.claude, ROOT, "mio"), "avv": ReaderSession(self.claude, ROOT, "avv")}
                        if self.claude else {})
        self._read_lock = threading.Lock()  # lettura anticipata e lettura dell'F8 non si sovrappongono
        self._pre: dict | None = None      # l'ultima lettura anticipata (a inizio round, prima dell'F8)
        self._last_sig = None
        self._recent_moves: list[str] = []  # gli ultimi consigli: con il contesto pulito a ogni round restano qui
        self._last_live = ""
        self.rec_on = False
        self.rec_dir: Path | None = None
        self.rec_count = 0
        self.journal_dir: Path | None = None
        self.req_n = 0
        self.live_n = 0           # analisi live in questa partita (dalla seconda si impara dal round prima)
        self.flags: list[str] = []  # segnalazioni ✕ della partita, rilette a fine partita
        self.learning = False
        self._session_free = threading.Event()
        self._session_free.set()
        self._q: queue.Queue = queue.Queue()
        self._match_mtime = 0.0
        self._stop = threading.Event()
        self.obs_frames: list[dict] = []   # fotogrammi dell'osservatore dall'ultimo F8: {"path", "score", "t"}
        self._obs_lock = threading.Lock()
        self._obs_n = 0
        self._match_active = False
        self._history_lock = threading.Lock()

    # ------------------------------------------------ avvio
    def start(self) -> None:
        threading.Thread(target=self._worker, daemon=True, name="bb-worker").start()
        threading.Thread(target=self._watch_loop, daemon=True, name="bb-watch").start()
        threading.Thread(target=self._hud_loop, daemon=True, name="bb-hud").start()
        self.emit_state()
        if self.session:  # accende Claude Code subito: il primo F8 non paga l'avvio
            threading.Thread(target=self._prewarm, daemon=True).start()
        if store.load("config").get("voce", True):
            self.voice.warm()
        threading.Thread(target=self._startup_updates, daemon=True).start()
        threading.Thread(target=self._startup_data, daemon=True, name="bb-dati").start()
        try:
            screen.cleanup_empty_recordings()
        except Exception:  # noqa: BLE001
            log.exception("pulizia registrazioni vuote")
        if not self.claude:
            if os.name == "nt" and not os.environ.get("BIGBOB_NO_SYNC"):
                threading.Thread(target=self._install_claude, daemon=True, name="bb-claude").start()
            else:
                self.say("Non trovo il comando 'claude'. Installa Claude Code e fai il login (vedi README).", "warn")
        else:
            self.say("Pronto. F8 analizza il round, F9 cattura per la scansione, F10 nasconde. "
                     "Premi NUOVA prima di iniziare una partita.", "dim")

    def _install_claude(self) -> None:
        """Claude Code manca: lo installa da solo, poi apre il terminale per l'accesso con l'account Claude."""
        import configura
        self.say("Claude Code non è installato: lo installo adesso (uno o due minuti). Intanto non premere F8.", "warn")
        self.status("Installo Claude Code…")
        exe = configura.install_claude(log=lambda m: log.info("installa claude: %s", m))
        if not exe:
            self.say("Non sono riuscito a installare Claude Code. Installalo a mano: apri PowerShell e incolla "
                     "irm https://claude.ai/install.ps1 | iex — poi riapri BIG-BOB.", "warn")
            self.status("Claude Code non installato")
            return
        self.claude = exe
        try:
            configura.ensure_claude_on_path(exe)
        except Exception:  # noqa: BLE001
            log.exception("PATH di Claude Code")
        self.session = ClaudeSession(self.claude, ROOT)
        self.status("Claude Code installato")
        self.say("Claude Code installato. Ora accedi con il TUO account Claude (Pro o Max) nel terminale che si apre: "
                 "segui le istruzioni nel browser, poi chiudi il terminale e premi PROVA COLLEGAMENTO nelle "
                 "impostazioni (⚙). Con una chiave API invece scegli «Chiave API» in ⚙.", "lesson")
        self.emit({"type": "action", "label": "ACCEDI A CLAUDE", "call": "claude_login"})
        self.claude_login()

    def stop(self) -> None:
        self._stop.set()
        self.voice.stop()
        if self.session:
            self.session.close()
        if getattr(self, "lab_session", None):
            self.lab_session.close()

    def _prewarm(self) -> None:
        try:
            self.session.ensure()
        except Exception:  # noqa: BLE001
            log.exception("avvio anticipato di Claude Code fallito")

    # ------------------------------------------------ eventi verso la finestra
    def emit(self, ev: dict) -> None:
        try:
            self.ui.emit(ev)
        except Exception:  # noqa: BLE001
            log.exception("emit fallito: %s", ev.get("type"))

    def say(self, text: str, role: str = "bob") -> None:
        self.emit({"type": "say", "role": role, "text": text})

    def status(self, text: str) -> None:
        self.emit({"type": "status", "text": text})

    def emit_state(self) -> None:
        cfg = store.load("config")
        self.emit({"type": "state", "mode": cfg.get("modalita", "allenamento"), "auto": self.auto_on,
                   "pilot": bool(getattr(self, "pilot_on", False)),
                   "rec": self.rec_on, "busy": self.busy, "round_seconds": ROUND_SECONDS,
                   "voice": bool(cfg.get("voce", True)) and self.voice.available(),
                   "voice_available": self.voice.available(),
                   "budget_seconds": BUDGET_SECONDS,
                   "decks": self._deck_names(), "lab": deckproj.summary(),
                   "consumi": usage.summary() if usage.visible() else None,
                   "tutorial": not cfg.get("tutorial_visto", False),
                   "cervello_avviso": self._brain_notice(cfg)})
        self._emit_hud(force=True)

    @staticmethod
    def _deck_names() -> list[str]:
        names = [d["nome"] for d in store.load("decks")]
        p = deckproj.active()
        if p and deckproj.deck_name(p) in names:  # il mazzo in creazione per primo
            names.remove(deckproj.deck_name(p))
            names.insert(0, deckproj.deck_name(p))
        return names

    # ------------------------------------------------ API pubblica (chiamata da finestra e tasti)
    def analyze(self, auto: bool = False) -> None:
        self._q.put(("analyze", auto))

    def chat(self, text: str) -> None:
        if text and text.strip():
            self._q.put(("chat", text.strip()))

    def scan(self) -> None:
        self._q.put(("scan", None))

    def new_match(self, deck: str) -> None:
        if deck and deck.strip():
            self._q.put(("new_match", deck.strip()))

    def end_match(self, result: str) -> None:
        if result and result.strip():
            self._q.put(("end_match", result.strip()))

    def flag(self, note: str) -> None:
        if note and note.strip():
            self._q.put(("flag", note.strip()))

    MODES = ("allenamento", "ranked", "creazione")

    def toggle_mode(self) -> None:
        cfg = store.load("config")
        cur = cfg.get("modalita") if cfg.get("modalita") in self.MODES else "allenamento"
        cfg["modalita"] = self.MODES[(self.MODES.index(cur) + 1) % len(self.MODES)]
        store.save("config", cfg)
        if cfg["modalita"] == "ranked" and getattr(self, "pilot_on", False):
            self.pilot_on, self._pilot_stop = False, True
            self.say("Ranked: pilota automatico spento.", "dim")
        self.emit_state()
        if cfg["modalita"] == "creazione" and not deckproj.active():
            self.say("Modalità CREAZIONE MAZZO: premi CREA MAZZO e BIG-BOB costruisce un mazzo partendo dal meta, poi "
                     "lo migliora partita dopo partita.", "dim")

    # ------------------------------------------------ creazione mazzo (laboratorio)
    def create_deck(self, goal: str = "", games: int = 10) -> None:
        try:
            games = max(3, min(40, int(games or 10)))
        except (TypeError, ValueError):
            games = 10
        self._q.put(("create_deck", ((goal or "").strip(), games)))

    def _do_create_deck(self, arg) -> None:
        goal, games = arg
        self._ask(PROMPT_CREA.format(goal=goal or "nessuna preferenza: scegli tu la leggendaria più promettente",
                                     games=games),
                  label="Crea mazzo" + (f": {goal}" if goal else ""), kind="crea")

    def lab_apply(self) -> None:
        res = deckproj.apply()
        if res.get("errore"):
            self.say(res["errore"], "warn")
        else:
            self.say(f"Versione {res['versione']} pronta. {res['nel_gioco']} Servono {res['partite_di_test']} partite "
                     "di test: scegli il mazzo con NUOVA.", "lesson")
        self.emit_state()

    def open_lab(self) -> None:
        p = deckproj.active()
        if not p:
            self.say("Nessun mazzo in creazione: premi CREA MAZZO.", "dim")
            return
        self.open_library("mazzi", deckproj.deck_name(p))

    def _lab_after(self, kind: str) -> None:
        """Dopo la creazione o la fine di una partita di test: aggiorna il pannello e offre i pulsanti giusti."""
        if kind not in ("crea", "fine"):
            return
        p = deckproj.active()
        if not p:
            return
        self.emit_state()
        if p.get("proposta"):
            self.emit({"type": "action", "label": "APPLICA MIGLIORIA", "call": "lab_apply"})
        self.emit({"type": "action", "label": "STATISTICHE DEL MAZZO", "call": "open_lab"})

    # ------------------------------------------------ aggiornamenti
    def _startup_updates(self) -> None:
        from origins import updates
        res = updates.last_result()
        if res:  # appena riaperto dopo un aggiornamento: finestra "aggiornamento completato" (o l'errore)
            if not res.get("ok"):
                res["errore"] = f"{res.get('errore')}. BIG-BOB è rimasto alla versione di prima."
            self.emit({"type": "update_done", **res})
            if res.get("ok"):
                self.say(f"BIG-BOB aggiornato ({res.get('da')} → {res.get('a')}).", "dim")
        # a ogni avvio, sempre: prima la finestra e Claude Code, poi il controllo; se la rete non è ancora pronta
        # (PC appena acceso) riprova un paio di volte; poi ricontrolla ogni 3 ore finché BIG-BOB resta aperto
        time.sleep(3)
        for attempt in range(3):
            res = self._check_updates(manual=False, startup=True)
            if not (res or {}).get("rete"):
                break
            time.sleep(20)
        while not self._stop.wait(3 * 3600):
            if not self.busy:
                self._check_updates(manual=False)

    def check_updates(self) -> None:
        threading.Thread(target=self._check_updates, kwargs={"manual": True}, daemon=True).start()

    def _check_updates(self, manual: bool, startup: bool = False) -> dict:
        from origins import updates
        if manual or startup:
            self.status("Controllo aggiornamenti…")
        res = updates.check()
        log.info("controllo aggiornamenti: %s", res)
        if res["disponibile"]:
            # all'avvio la finestra delle novità si apre da sola (fuori partita); più tardi basta la barra
            in_match = store.FILES["match"].exists() and bool(store.load("match"))
            self.emit({"type": "update", **res, "manual": manual or (startup and not in_match and not self.busy)})
        else:
            # errore → barra rossa con il motivo; tutto a posto → la barra (se c'era) sparisce
            self.emit({"type": "update", **res, "manual": manual})
        if manual or startup:
            self.status(f"BIG-BOB è aggiornato · versione {res['versione']}" if not res["disponibile"]
                        and not res.get("errore") else "")
        return res

    def apply_update(self) -> None:
        from origins import updates
        if self.busy:
            self.emit({"type": "update", "manual": True, "disponibile": False,
                       "errore": "BIG-BOB sta rispondendo: aspetta la fine della risposta, poi riprova ad aggiornare."})
            return
        self.say("Aggiorno BIG-BOB: si chiude e si riapre da solo tra poco.", "dim")
        updates.launch_updater(os.getpid())
        time.sleep(0.8)
        if self.session:
            self.session.close()
        quit_ = getattr(self.ui, "quit", None)
        if quit_:
            quit_()

    # ------------------------------------------------ meta, carte e location da OriginsMeta
    def _cleanup_space(self) -> None:
        """Toglie le immagini che non servono più (vedi origins/spazio.py): la cartella di BIG-BOB non cresce senza limiti."""
        from origins import lessons, spazio
        try:
            rep = spazio.cleanup(active=self.journal_dir)
            log.info("spazio: %s · ora %s", rep, spazio.usage())
        except Exception:  # noqa: BLE001
            log.exception("pulizia dello spazio")
        try:  # riordino delle lezioni: le quasi uguali diventano una sola (con tutte le prove)
            t = lessons.tidy()
            if t["unite"]:
                log.info("lezioni unite: %s", t["unite"])
        except Exception:  # noqa: BLE001
            log.exception("riordino delle lezioni")

    def _startup_data(self) -> None:
        """All'avvio, in ordine (scrivono negli stessi file): prima OriginsMeta, poi il cervello comune."""
        self._cleanup_space()
        try:
            self._startup_meta()
        finally:
            self._startup_brain()

    def _startup_meta(self) -> None:
        from origins import originsmeta
        if os.environ.get("BIGBOB_NO_SYNC"):  # test automatici: niente rete
            return
        cfg = store.load("config")
        empty = len(store.load("cards")) < 50
        if not cfg.get("meta_originsmeta", True) and not empty:
            return
        if not empty and not originsmeta.due():
            return
        time.sleep(1 if empty else 8)  # con il database vuoto serve subito; altrimenti lascio partire il resto
        if empty:
            self.say("Database delle carte vuoto: scarico carte, location e meta da OriginsMeta (circa un minuto)…",
                     "dim")
        self._sync_meta(force=empty, manual=empty)

    def sync_meta(self) -> None:
        threading.Thread(target=self._sync_meta, kwargs={"force": True, "manual": True}, daemon=True).start()

    def _sync_meta(self, force: bool, manual: bool) -> None:
        from origins import originsmeta
        if getattr(self, "_meta_running", False):
            return
        self._meta_running = True
        try:
            if manual:
                self.status("Scarico il meta da OriginsMeta…")
            rep = originsmeta.sync(force=force, progress=(self.status if manual else (lambda s: None)))
            log.info("originsmeta: %s", {k: rep.get(k) for k in ("ok", "totale_mazzi", "completi", "errori",
                                                                  "carte_aggiunte", "carte_cambiate", "secondi")})
            if rep.get("saltato") and not manual:
                return
            line = originsmeta.summary_line(rep)
            important = rep.get("carte_cambiate") or rep.get("nuovi") or rep.get("carte_aggiunte") or not rep.get("ok")
            if manual or important:
                self.say(line, "warn" if not rep.get("ok") or rep.get("carte_cambiate") else "lesson")
            if manual:
                self.status("Meta aggiornato" if rep.get("ok") else "Meta non aggiornato")
            self.emit_state()
        except Exception as e:  # noqa: BLE001
            log.exception("sincronizzazione OriginsMeta fallita")
            if manual:
                self.say(f"OriginsMeta non raggiungibile: {e}", "warn")
        finally:
            self._meta_running = False

    # ------------------------------------------------ cervello comune (conoscenza condivisa tra i BIG-BOB)
    @staticmethod
    def _brain_notice(cfg: dict) -> bool:
        from origins import cervello
        return cervello.enabled() and not cfg.get("cervello_avviso_visto", False)

    def _startup_brain(self) -> None:
        from origins import cervello
        if os.environ.get("BIGBOB_NO_SYNC") or not cervello.enabled():
            return
        time.sleep(5)
        self._sync_brain(force=False, manual=False)

    def sync_brain(self) -> None:
        threading.Thread(target=self._sync_brain, kwargs={"force": True, "manual": True}, daemon=True).start()

    def _brain_soon(self) -> None:
        """Dopo fine partita / studio / creazione: invia subito ciò che è stato imparato."""
        from origins import cervello
        if os.environ.get("BIGBOB_NO_SYNC") or not cervello.enabled():
            return
        threading.Timer(3, self._sync_brain, kwargs={"force": True, "manual": False}).start()

    def sync_brain_now(self) -> dict:
        """Per il pulsante della pagina Studio: sincronizza e restituisce l'esito da mostrare lì."""
        from origins import cervello
        rep = self._sync_brain(force=True, manual=True) or {}
        errs = [v.get("errore") for v in (rep.get("invio"), rep.get("ricezione")) if isinstance(v, dict) and v.get("errore")]
        return {"ok": not errs and not rep.get("saltato"), "riga": rep.get("saltato") or cervello.summary_line(rep),
                "errore": "; ".join(errs) or None, "secondi": rep.get("secondi")}

    def _sync_brain(self, force: bool, manual: bool) -> dict | None:
        from origins import cervello
        lock = self.__dict__.setdefault("_brain_lock", threading.Lock())
        # se c'è già una sincronizzazione in corso (es. quella dell'avvio) aspetto che finisca invece di ignorare il clic
        if not lock.acquire(timeout=90 if manual else 0):
            if manual:
                self.say("Cervello comune: un'altra sincronizzazione è bloccata da più di un minuto e mezzo. "
                         "Controlla la connessione e riprova.", "warn")
            return {"saltato": "sincronizzazione già in corso"}
        try:
            if manual:
                self.status("Sincronizzo il cervello comune…")
            rep = cervello.sync(force=force)
            log.info("cervello comune: %s", rep)
            if rep.get("saltato"):
                if manual:
                    self.say(f"Cervello comune: {rep['saltato']}.", "dim")
                return rep
            ric = rep.get("ricezione") or {}
            news = ric.get("carte_aggiunte") or ric.get("carte_aggiornate")
            if manual or news:
                self.say(cervello.summary_line(rep) + (f" · carte aggiornate dal cervello comune: "
                                                      f"{(ric.get('carte_aggiunte') or 0) + (ric.get('carte_aggiornate') or 0)}"
                                                      if news else ""), "lesson")
            if manual:
                self.status("Cervello comune sincronizzato" if "problema" not in cervello.summary_line(rep)
                            else "Cervello comune: sincronizzazione con problemi")
            return rep
        except Exception as e:  # noqa: BLE001
            log.exception("cervello comune")
            if manual:
                self.say(f"Cervello comune non raggiungibile: {e}", "warn")
            return {"invio": {"errore": str(e)}, "ricezione": {}}
        finally:
            lock.release()

    def brain_consent(self, ok: bool) -> None:
        cfg = store.load("config")
        cfg["cervello_avviso_visto"] = True
        cfg["cervello_contribuisci"] = bool(ok)
        store.save("config", cfg)
        self.emit_state()
        if ok:
            self.status("Grazie: contribuisci al cervello comune")
            self.sync_brain()
        else:
            self.say("Va bene: non invio niente. Ricevi comunque ciò che imparano gli altri (puoi spegnerlo nelle "
                     "impostazioni).", "dim")

    # ------------------------------------------------ impostazioni e collegamento a Claude
    SETTINGS_KEYS = ("modello_live", "connessione", "voce", "apprendimento_live", "apri_claude_code_all_avvio",
                     "max_thinking_live", "modalita", "meta_originsmeta", "osservatore", "barra_vantaggio",
                     "cervello_contribuisci", "cervello_usa", "invisibile_catture", "lettura_veloce",
                     "contesto_pulito", "lettura_anticipata", "ragionamento_dosato")

    def get_settings(self) -> None:
        from origins import cervello, spazio, updates
        cfg = store.load("config")
        vals = {k: cfg.get(k) for k in self.SETTINGS_KEYS}
        try:
            space = {**spazio.usage(), "limite": int(cfg.get("spazio_max_mb") or spazio.DEFAULT_MAX_MB)}
        except Exception:  # noqa: BLE001
            space = {}
        vals.setdefault("connessione", "abbonamento")
        vals["connessione"] = vals["connessione"] or "abbonamento"
        vals["api_key_impostata"] = bool(cfg.get("api_key"))
        self.emit({"type": "settings", "valori": vals, "versione": updates.installed_version(),
                   "claude_trovato": bool(self.claude),
                   "cervello": {"attivo": cervello.enabled(), "riga": cervello.summary_line()}, "spazio": space})

    def save_settings(self, vals: dict) -> None:
        import configura
        cfg_before = store.load("config")
        extra = {k: vals[k] for k in ("voce", "apprendimento_live", "apri_claude_code_all_avvio",
                                      "meta_originsmeta", "osservatore", "barra_vantaggio", "cervello_contribuisci",
                                      "cervello_usa", "invisibile_catture", "lettura_veloce", "contesto_pulito",
                                      "lettura_anticipata", "ragionamento_dosato") if k in vals}
        if "max_thinking_live" in vals:
            try:
                extra["max_thinking_live"] = max(0, int(vals["max_thinking_live"]))
            except (TypeError, ValueError):
                pass
        key = (vals.get("api_key") or "").strip()
        try:
            cfg = configura.apply(vals.get("modello_live"), vals.get("connessione"), key or None, **extra)
        except ValueError as e:
            self.say(f"Impostazioni non salvate: {e}", "warn")
            return
        if cfg.get("connessione") == "api" and not cfg.get("api_key"):
            self.say("Hai scelto la chiave API ma non l'hai inserita: finché manca uso l'abbonamento.", "warn")
        changed = any(cfg_before.get(k) != cfg.get(k) for k in ("modello_live", "connessione", "api_key",
                                                                  "max_thinking_live"))
        if changed and self.session and not self.busy:
            self.session.reset()  # la prossima risposta usa subito il nuovo modello/collegamento
            threading.Thread(target=self._prewarm, daemon=True).start()
        if cfg_before.get("invisibile_catture", True) != cfg.get("invisibile_catture", True):
            self.apply_capture_exclusion()
        self.emit_state()
        self.status("Impostazioni salvate")

    def claude_login(self) -> None:
        from origins import winutil
        msg = winutil.open_claude_terminal(ROOT)
        self.say(msg + " Se non ti chiede di accedere, scrivi /login nel terminale e scegli il tuo account Claude "
                       "(abbonamento) o la chiave API.", "dim")

    def claude_test(self) -> None:
        threading.Thread(target=self._claude_test, daemon=True).start()

    def _claude_test(self) -> None:
        import configura
        ok, msg = configura.test_claude()
        if ok and not self.claude:
            self.claude = configura.find_claude()
        self.emit({"type": "claude_test", "ok": ok, "msg": msg})

    # ------------------------------------------------ pagine locali
    def _open(self, path: Path, title: str = "BIG-BOB", frag: str = "") -> None:
        """Dentro l'app (finestra di BIG-BOB) se la finestra lo permette; altrimenti nel browser (finestra classica)."""
        shower = getattr(self.ui, "show_html", None)
        if shower is not None:
            def fallback():  # la finestra interna è rimasta vuota: apro la stessa pagina nel browser
                self.say("La pagina non si è caricata nella finestra di BIG-BOB: l'ho aperta nel browser. Se succede "
                         "sempre, manda il file logs\\bigbob.log a chi ti ha dato BIG-BOB.", "warn")
                self._open_external(path)
            try:
                try:
                    shown = shower(self._inline_page(Path(path)), title, fallback=fallback)
                except TypeError:  # finestre senza controllo del caricamento (test, finestra classica)
                    shown = shower(self._inline_page(Path(path)), title)
                if shown:
                    return
            except Exception:  # noqa: BLE001
                log.exception("pagina interna non aperta: uso il browser")
        self._open_external(path)

    @staticmethod
    def _inline_page(path: Path) -> str:
        """Il contenuto della pagina, con le immagini (schermate del replay) incorporate: la finestra non legge file."""
        import base64
        text = path.read_text(encoding="utf-8")

        def embed(m):
            f = path.parent / m.group(2)
            if not f.exists():
                return m.group(0)
            data, mime = f.read_bytes(), "image/png"
            try:  # anteprima JPEG leggera: la finestra accetta pagine fino a circa 2 MB
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im.thumbnail((560, 560))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=60, optimize=True)
                data, mime = buf.getvalue(), "image/jpeg"
            except Exception:  # noqa: BLE001
                pass
            return f"{m.group(1)}data:{mime};base64,{base64.b64encode(data).decode()}{m.group(3)}"
        return re.sub(r"(src=['\"])([^'\":]+\.(?:png|jpg))(['\"])", embed, text)

    @staticmethod
    def _open_external(path: Path) -> None:
        import os
        import webbrowser
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows: browser predefinito
        except Exception:  # noqa: BLE001
            webbrowser.open(path.as_uri())

    def open_library(self, tab: str = "mazzi", deck: str = "", match: str = "") -> None:
        """La finestra del libro: MAZZI · PARTITE · STATISTICHE · STUDIO (dentro l'app)."""
        from origins import report
        try:
            path = report.library_html(tab, deck, match)
            frag = f"mazzo={store.slug(deck)}" if deck else (f"partita={match}" if match else tab)
            self._open(path, "BIG-BOB · Mazzi e statistiche", frag)
        except Exception as e:  # noqa: BLE001
            log.exception("libreria")
            self.say(f"Pagina non generata: {e}", "warn")

    def tutorial_done(self) -> None:
        cfg = store.load("config")
        cfg["tutorial_visto"] = True
        store.save("config", cfg)
        self.emit_state()

    def open_stats(self) -> None:
        self.open_library("statistiche")

    def open_learned(self) -> None:
        self.open_library("studio")

    def open_origin(self) -> None:
        """Il tasto Origin: i mazzi del meta presi da OriginsMeta (dentro l'app)."""
        from origins import report
        try:
            self._open(report.meta_html(), "BIG-BOB · Mazzi meta")
        except Exception as e:  # noqa: BLE001
            log.exception("pagina mazzi meta")
            self.say(f"Pagina non generata: {e}", "warn")

    @staticmethod
    def open_site(url: str = "https://originsmeta.com/it") -> None:
        """Apre OriginsMeta nel browser (richiesto esplicitamente dal pulsante «vai sul sito»): solo quel sito."""
        import webbrowser
        if not str(url).startswith("https://originsmeta.com"):
            return
        webbrowser.open(url)

    # ------------------------------------------------ studio delle registrazioni (regole + strategia)
    def study_recordings(self) -> None:
        from origins import report
        pend = report.pending_recordings()
        if not pend:
            self.say("Nessuna registrazione da studiare: premi REGISTRA durante una partita.", "dim")
            return
        if getattr(self, "studying", False):
            self.say("Sto già studiando le registrazioni: ti avviso quando ho finito.", "dim")
            return
        if self._match_active:
            self._study_after_match = True
            self.say(f"Studierò {len(pend)} registrazion{'e' if len(pend) == 1 else 'i'} a fine partita.", "dim")
            return
        threading.Thread(target=self._run_study, args=(len(pend),), daemon=True, name="bb-studio").start()

    def _run_study(self, n: int) -> None:
        self.studying = True
        self._study_after_match = False
        self.say(f"Studio {n} registrazion{'e' if n == 1 else 'i'} in background (regole e strategia): puoi continuare "
                 "a usare BIG-BOB, ti avviso quando ho finito.", "dim")
        sess = self.study_session = getattr(self, "study_session", None) or ClaudeSession(self.claude, ROOT, live=False)
        final = ""
        lessons_n = rules_n = 0
        try:
            for ev in sess.ask([{"type": "text", "text": PROMPT_STUDIO.format(n=n)}], timeout=3600):
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "").replace("mcp__origins__", "")
                            lessons_n += name == "record_lesson"
                            rules_n += name == "rules_upsert"
                elif ev.get("type") == "result":
                    final = (ev.get("result") or "").strip()
                    usage.add_from_result(ev, sess)
            self.say(f"Studio finito: {lessons_n} lezioni e {rules_n} regole aggiornate.\n{final}", "lesson")
            self.emit({"type": "action", "label": "APRI LO STUDIO", "call": "open_learned"})
        except Exception as e:  # noqa: BLE001
            log.exception("studio delle registrazioni")
            self.say(f"Studio delle registrazioni interrotto: {e}", "warn")
        finally:
            self.studying = False
            self._brain_soon()

    def open_replay(self) -> None:
        """RIVEDI LA PARTITA: la partita nella scheda PARTITE del libro (schermate, mosse suggerite e giocate)."""
        from origins import history
        d = self.journal_dir
        name = d.name if d is not None and (Path(d) / "diario.md").exists() else history.latest_id()
        if not name:
            self.say("Nessuna partita da rivedere.", "dim")
            return
        self.open_library("partite", match=name)

    def history_ask(self, pid: str, n: int, question: str) -> dict:
        """Conversazione dalla cronologia (libro → PARTITE) su una mossa o sull'intera partita: risponde una sessione
        a parte (non disturba la partita in corso) che registra le lezioni che il giocatore le insegna.
        Restituisce {'risposta', 'imparato': [..]} e salva lo scambio nel diario della partita."""
        from origins import history
        question = (question or "").strip()[:1500]
        n = int(n or 0)
        if not question:
            return {"risposta": "Scrivi una domanda.", "imparato": []}
        if not self.claude:
            return {"risposta": "Claude Code non è collegato: controlla le impostazioni.", "imparato": []}
        with self._history_lock:
            follow = getattr(self, "_history_last", None) == (pid, n) and getattr(self, "history_session", None)
            content: list[dict] = []
            if follow:
                content.append({"type": "text", "text": PROMPT_STORIA_SEGUITO.format(
                    cosa="partita" if n == 0 else f"richiesta #{n}", domanda=question)})
            else:
                try:
                    ctx, shot = history.question_context(pid, n)
                except Exception as e:  # noqa: BLE001
                    return {"risposta": f"Non trovo questa partita: {e}", "imparato": []}
                if shot is not None:
                    try:
                        data = history.image_data(shot.relative_to(history.LOGS).as_posix(), 1400)
                        if data:
                            mime, b64 = data[5:].split(";base64,", 1)
                            content.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                                         "data": b64}})
                    except Exception:  # noqa: BLE001
                        log.exception("schermata per la domanda")
                prev = [x for x in history.load_qa(pid) if x.get("n") == n][-3:]
                if prev:  # conversazione ripresa: ricorda gli ultimi scambi su questo punto
                    ctx += "\n\nGià detto su questo punto:\n" + "\n".join(
                        f"- Daniele: {x['domanda']}\n  Tu: {x['risposta'][:400]}" for x in prev)
                content.append({"type": "text", "text": PROMPT_STORIA.format(contesto=ctx, domanda=question)})
            sess = getattr(self, "history_session", None)
            if sess is None:
                sess = self.history_session = ClaudeSession(self.claude, ROOT, live=False)
            elif getattr(self, "_history_last", (None,))[0] != pid:
                sess.reset()  # partita diversa: contesto nuovo (e meno costoso)
            self._history_last = (pid, n)
            final, texts, learned = "", [], []
            try:
                for ev in sess.ask(content, timeout=300):
                    if ev.get("type") == "assistant":
                        for block in ev.get("message", {}).get("content", []):
                            if block.get("type") == "text" and block.get("text", "").strip():
                                texts.append(block["text"])
                            elif block.get("type") == "tool_use":
                                item = self._learned_item(block)
                                if item:
                                    learned.append(item)
                    elif ev.get("type") == "result":
                        usage.add_from_result(ev, sess)
                        final = (ev.get("result") or (texts[-1] if texts else "")).strip()
            except Exception as e:  # noqa: BLE001
                log.exception("domanda dalla cronologia")
                self._history_last = None
                return {"risposta": f"Non sono riuscito a rispondere: {e}", "imparato": learned}
        final = final or "Nessuna risposta."
        try:
            history.save_qa(pid, n, question, final, learned)
        except Exception:  # noqa: BLE001
            log.exception("salvataggio della conversazione")
        if learned:
            self._brain_soon()  # ciò che il giocatore ha insegnato va anche al cervello comune
        if usage.visible():
            self.emit({"type": "usage", **usage.summary()})
        return {"risposta": final, "imparato": learned}

    @staticmethod
    def _learned_item(block: dict) -> str | None:
        """Una riga leggibile per ciò che Claude ha registrato (lezione, regola, carta)."""
        name = block.get("name", "").replace("mcp__origins__", "")
        inp = block.get("input") or {}
        if name == "record_lesson":
            return "Lezione: " + str(inp.get("lezione", ""))[:200]
        if name == "rules_upsert":
            return ("Regola " + str(inp.get("id") or "nuova") + ": " + str(inp.get("testo") or inp.get("stato") or ""))[:200]
        if name == "lesson_review":
            return f"Lezione {inp.get('id', '')} → {inp.get('stato') or 'rivista'}"
        if name in ("upsert_cards", "upsert_locations"):
            names = ", ".join(str(c.get("nome", "")) for c in (inp.get("cards") or inp.get("locations") or [])[:4])
            return "Corretto: " + names
        return None

    @staticmethod
    def history_image(rel: str, size: int = 520) -> str | None:
        from origins import history
        try:
            return history.image_data(rel, size)
        except Exception:  # noqa: BLE001
            log.exception("immagine della cronologia")
            return None

    def _link_journal(self) -> None:
        """Dopo FINE: scrive nella partita appena salvata in quale diario sono schermate e risposte."""
        if self.journal_dir is None:
            return
        ms = store.load("matches")
        if ms and not ms[-1].get("diario"):
            ms[-1]["diario"] = self.journal_dir.name
            store.save("matches", ms)

    def set_voice(self, on: bool) -> None:
        cfg = store.load("config")
        cfg["voce"] = bool(on)
        store.save("config", cfg)
        if on:
            self.voice.warm()
        self.emit_state()

    def apply_capture_exclusion(self) -> None:
        """All'avvio (e quando cambia l'impostazione): BIG-BOB invisibile alle catture, se Windows lo permette."""
        from origins import winutil
        on = store.load("config").get("invisibile_catture", True)
        ok = winutil.exclude_from_capture("BIG-BOB", on)
        self.capture_excluded = bool(on and ok)
        log.info("invisibile alle catture: richiesto %s, attivo %s", on, self.capture_excluded)

    def set_auto(self, on: bool) -> None:
        self.auto_on = bool(on)
        if not self.auto_on:  # toglie dalla coda le analisi automatiche non ancora partite
            self._drop_queued("analyze", True)
            self.pilot_on = False  # senza AUTO il pilota non vede i round
        self.emit_state()

    # ------------------------------------------------ pilota automatico (solo allenamento / creazione)
    def set_pilot(self, on: bool) -> None:
        if on and self._mode() == "ranked":
            self.say("Il pilota automatico non funziona in ranked: lì BIG-BOB dà solo i numeri.", "warn")
            on = False
        self.pilot_on = bool(on)
        if self.pilot_on:
            self.auto_on = True  # il pilota gioca a ogni round: serve che BIG-BOB guardi da solo
            self._pilot_rounds = {}
            cfg = store.load("config")
            self.say("PILOTA AUTOMATICO acceso: a ogni round BIG-BOB sceglie la giocata e la esegue con il mouse. "
                     "Per riprendere il controllo muovi il mouse (si ferma subito) o premi F12. È sperimentale: le "
                     "coordinate le legge Claude dalla schermata, quindi ogni tanto può mancare uno spazio.", "dim")
            if not cfg.get("pilota_avviso_visto"):
                self.say("Attenzione: molti giochi online vietano nei termini di servizio i programmi che giocano al "
                         "posto tuo, e chi gioca contro di te in casual non sa di avere davanti un bot. Usalo a tuo "
                         "rischio; contro il bot del gioco il rischio è minore.", "warn")
                cfg["pilota_avviso_visto"] = True
                store.save("config", cfg)
            threading.Thread(target=self._pilot_selftest, daemon=True, name="bb-pilota-prova").start()
            if not self.busy:
                self.analyze(auto=True)
        else:
            self._pilot_stop = True
        self.emit_state()

    def _pilot_selftest(self) -> None:
        """All'accensione: controlla che il gioco si trovi, che il mouse vada dove BIG-BOB lo mette e che i comandi
        possano arrivare al gioco. I problemi li scrive in chat, invece di lasciare il pilota fermo senza spiegazioni."""
        from origins import pilot, winutil
        if not pilot.WIN:
            return
        title = store.load("config").get("titolo_finestra", "Origins")
        gw = screen.game_window(title)
        if not gw:
            self.say(f"Pilota: non trovo la finestra del gioco (cerco '{title}' nel titolo). Apri Origins in finestra o "
                     "a schermo intero e riaccendi il pilota.", "warn")
            return
        hwnd, region = gw
        if winutil.is_elevated(hwnd) and not winutil.is_elevated(None):
            self.say("Pilota: Origins gira come amministratore e BIG-BOB no, quindi Windows blocca i clic di BIG-BOB "
                     "sul gioco. Avvia BIG-BOB come amministratore (tasto destro › Esegui come amministratore).", "warn")
        res = pilot.selftest(region)
        log.info("pilota, prova del mouse: %s", res)
        if not res.get("ok"):
            self.say(f"Pilota: il mouse non va dove lo mando ({res.get('dettaglio')}). Dimmelo: è un problema di scala "
                     "dello schermo che correggo.", "warn")

    def stop_pilot(self) -> None:
        if getattr(self, "pilot_on", False):
            self._pilot_stop = True
            self.pilot_on = False
            self.status("Pilota automatico spento (F12)")
            self.emit_state()

    def _pilot_after(self, final: str) -> None:
        """Dopo una risposta live con il pilota acceso: esegue le azioni della riga 🤖 (in un thread a parte)."""
        from origins import pilot
        if not getattr(self, "pilot_on", False) or self._mode() == "ranked":
            return
        actions = pilot.parse(final)
        if not actions:
            if actions is None:
                log.info("pilota: nessuna riga 🤖 nella risposta")
                self._journal("🤖 Pilota: la risposta non conteneva la riga 🤖")
                self.say("Pilota: la risposta non conteneva azioni, riprovo tra poco.", "dim")
            else:
                self.status("🤖 niente da fare in questo momento")
            return
        turn = (store.load("match") or {}).get("turno") if store.FILES["match"].exists() else None
        n = self._pilot_rounds.get(turn, 0)
        if n >= pilot.MAX_PER_ROUND:
            self._journal(f"🤖 Pilota: già {n} giocate nel round {turn}, non ne faccio altre")
            self.status(f"🤖 già {n} giocate in questo round: aspetto il prossimo")
            return
        self._pilot_rounds[turn] = n + 1
        region = getattr(self, "_shot_region", None)
        threading.Thread(target=self._pilot_exec, args=(actions, region), daemon=True, name="bb-pilota").start()

    def _pilot_exec(self, actions: list, region) -> None:
        from origins import pilot, winutil
        title = store.load("config").get("titolo_finestra", "Origins")
        gw = screen.game_window(title)
        if not region or not gw or not pilot.WIN:
            self._journal(f"🤖 Pilota: finestra del gioco non trovata (titolo '{title}'), nessuna azione")
            self.say(f"Pilota: non trovo la finestra del gioco (cerco '{title}' nel titolo), quindi non clicco.", "warn")
            return
        hwnd, now = gw
        if any(abs(a - b) > 8 for a, b in zip(now, region)):
            self._journal(f"🤖 Pilota: il gioco si è spostato ({region} → {now}), nessuna azione")
            self.say("Pilota: la finestra del gioco si è spostata dopo la schermata, riprovo al prossimo controllo.", "dim")
            return
        self._pilot_stop = False
        pts = pilot.points(actions, region)
        hide = self.ui.is_visible() and pilot.overlaps(pts, self.ui.rect())
        self.status(f"🤖 eseguo {len(actions)} azioni")
        try:
            if hide:
                self.ui.hide()
                time.sleep(0.15)
            time.sleep(0.05)
            if not winutil.activate(hwnd):
                log.info("pilota: il gioco non è venuto in primo piano, provo lo stesso")
            done = pilot.run(actions, region, pilot.Mouse(stop=lambda: self._pilot_stop))
            self._journal("🤖 Pilota: " + pilot.describe(actions) + "\n" + "\n".join(f"- {d}" for d in done))
            self.status(f"🤖 fatto: {len(done)} azioni")
        except pilot.Interrotto as e:
            self.pilot_on = False
            self._journal(f"🤖 Pilota interrotto: {e}")
            self.say(f"Pilota automatico spento: {e}. Riprendi tu.", "warn")
            self.emit_state()
        except Exception as e:  # noqa: BLE001
            log.exception("pilota automatico")
            self.say(f"Pilota: errore nell'eseguire le azioni ({e}). Dettagli in logs/bigbob.log.", "warn")
        finally:
            if hide:
                self.ui.show()
            self.last_call = time.time()  # AUTO aspetta che la mossa sia sullo schermo prima di guardare di nuovo

    def _drop_queued(self, kind: str, arg=None) -> int:
        kept, dropped = [], 0
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item[0] == kind and (arg is None or item[1] == arg):
                dropped += 1
            else:
                kept.append(item)
        for item in kept:
            self._q.put(item)
        return dropped

    def set_record(self, on: bool) -> None:
        self._q.put(("record", bool(on)))

    def toggle_visibility(self) -> None:
        if self.ui.is_visible():
            self.ui.hide()
        else:
            self.ui.show()

    # ------------------------------------------------ worker
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                kind, arg = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                getattr(self, f"_do_{kind}")(arg)
            except Exception as e:  # noqa: BLE001
                log.exception("azione %s fallita", kind)
                self.say(f"Errore: {e} (dettagli in logs/bigbob.log)", "warn")

    def _mode(self) -> str:
        return store.load("config").get("modalita", "allenamento")

    def _do_analyze(self, auto: bool) -> None:
        if auto and not self.auto_on:
            return  # AUTO spento mentre questa analisi era in coda: niente cattura, niente finestra che lampeggia
        if self._fast_read_ok():
            try:
                if self._fast_analyze(auto):
                    return
            except Exception:  # noqa: BLE001
                log.exception("lettura veloce fallita: torno al giro normale")
                self.busy = False
        piloting = getattr(self, "pilot_on", False) and self._mode() != "ranked"
        # con il pilota serve sempre l'analisi completa: il prompt AUTO permette di rispondere "—" (niente da fare),
        # e a schermata ferma il pilota non giocherebbe mai
        prompt = (PROMPT_AUTO if auto and not piloting else PROMPT_TURNO).format(mode=self._mode())
        if piloting:
            prompt += PROMPT_PILOTA
        frames = self._take_obs_frames()
        if frames:
            n_mom = sum(len(f.get("foglio") or [f]) for f in frames)
            prompt = PROMPT_OSSERVATORE.format(n=f"{n_mom} momenti in {len(frames)} immagini") + prompt
        self._ask(prompt, label=None if auto else "Analisi round", attach=True, kind="live", frames=frames)

    # ------------------------------------------------ lettura veloce (due lettori in parallelo) + coach
    def _fast_read_ok(self) -> bool:
        cfg = store.load("config")
        return (cfg.get("lettura_veloce", True) and bool(self.readers) and not self.busy
                and getattr(self, "_fast_fail", 0) < 2
                and store.FILES["match"].exists() and bool(store.load("match")))

    def _recent_text(self) -> str:
        if not self._recent_moves:
            return ""
        return "Consigli dei round prima (il contesto riparte pulito a ogni round): " + " · ".join(self._recent_moves[-3:]) + "\n"

    def _read_screen(self, shot: Path, frames: list, m: dict) -> tuple[dict | None, dict | None, dict]:
        """I due lettori in parallelo sulla schermata (e sui fotogrammi, per il lato avversario)."""
        from origins import archetype, reader
        try:
            predicted = [x["carta"] for x in (archetype.predict(m).get("carte") or [])[:12]]
        except Exception:  # noqa: BLE001
            predicted = []
        import base64
        shot_img = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": base64.b64encode(shot.read_bytes()).decode()}}
        frame_imgs = []
        for i, f in enumerate(frames, 1):
            try:
                data = base64.b64encode(Path(f["path"]).read_bytes()).decode()
            except OSError:
                continue
            label = (f"Fotogramma {i}: foglio con ritagli numerati in ordine di tempo"
                     if f.get("foglio") else f"Fotogramma {i} · {f.get('ora', '')} · {f.get('zona', '')}")
            frame_imgs += [{"type": "text", "text": label},
                           {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]
        jobs = {"mio": [shot_img, {"type": "text", "text": reader.prompt("mio", m, predicted)}],
                "avv": frame_imgs + [shot_img, {"type": "text", "text": reader.prompt("avv", m, predicted)}]}
        out: dict = {}
        times: dict = {}

        def run(side):
            t = time.time()
            out[side] = reader.parse_json(self.readers[side].read(jobs[side]))
            times[side] = round(time.time() - t, 1)

        threads = [threading.Thread(target=run, args=(k,), daemon=True, name=f"bb-lettore-{k}") for k in jobs]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        for r in self.readers.values():  # le prossime letture trovano il processo già acceso
            threading.Thread(target=self._warm_reader, args=(r,), daemon=True).start()
        return out.get("mio"), out.get("avv"), times

    def _apply_reading(self, mine: dict, opp: dict) -> tuple[str, dict, list[str]]:
        """Unisce le letture, controlla che siano coerenti con lo stato di prima e chiama update_match."""
        from origins import reader
        from origins import server as srv
        before = store.load("match")
        args, warn = reader.merge(mine, opp)
        warn += reader.check(before, args)
        state = srv.update_match(**args)
        return state, args, warn

    def _fresh_pre(self) -> dict | None:
        """La lettura anticipata, se lo schermo da allora non è cambiato e non ci sono fotogrammi nuovi."""
        from origins import observer
        pre = self._pre
        if not pre or time.time() - pre["t"] > 60:
            return None
        self._obs_flush()
        with self._obs_lock:
            new_frames = len(self.obs_frames)
        if new_frames:
            return None
        if self._last_sig is not None and pre.get("sig") is not None:
            if observer.cell_diff(self._last_sig, pre["sig"])[0] > self.OBS_LOCAL_T:
                return None
        return pre

    def _preread(self, sig) -> None:
        """Lettura anticipata: a inizio round, quando lo schermo si ferma, i lettori leggono già la schermata. All'F8
        resta solo la mossa da pensare."""
        from origins import reader
        if not self._read_lock.acquire(blocking=False):
            return
        try:
            if self.busy or not self._fast_read_ok() or not getattr(self, "capture_excluded", False):
                return
            t0 = time.time()
            shot = self.hidden_capture()  # invisibile alle catture: niente lampeggio
            region = screen.last_region
            frames = self._take_obs_frames()
            mine, opp, times = self._read_screen(shot, frames, store.load("match"))
            if not reader.usable(mine, opp):
                with self._obs_lock:  # i fotogrammi restano per l'F8
                    self.obs_frames = frames + self.obs_frames
                return
            state, args, warn = self._apply_reading(mine, opp)
            self._pre = {"t": time.time(), "sig": sig, "shot": shot, "region": region, "state": state, "args": args,
                         "warn": warn, "frames": len(frames), "secs": round(time.time() - t0, 1), "times": times}
            self._emit_hud(force=True)
            log.info("lettura anticipata in %.1fs %s", time.time() - t0, times)
        except Exception:  # noqa: BLE001
            log.exception("lettura anticipata")
        finally:
            self._read_lock.release()

    def _fast_analyze(self, auto: bool) -> bool:
        """Legge la schermata con i due lettori in parallelo (o usa la lettura anticipata, se è ancora valida), registra
        lo stato e chiede al coach solo la mossa. Se la lettura non è utilizzabile (mulligan, schermata di fine, JSON
        non valido) usa il giro normale con la stessa schermata."""
        from origins import reader
        t0 = time.time()
        self._f8_t0 = t0  # il timer della finestra parte da qui e non si azzera quando il coach comincia a pensare
        self.busy = True
        self.emit({"type": "busy", "value": True, "what": "Leggo la schermata", "budget": BUDGET_SECONDS})
        with self._read_lock:  # se una lettura anticipata è in corso, la aspetto e la uso
            pre = self._fresh_pre()
            self._pre = None
            if pre:
                shot, region, state, args, warn = pre["shot"], pre["region"], pre["state"], pre["args"], pre["warn"]
                self._journal("")
                self._journal(f"Lettura anticipata usata (fatta {time.time() - pre['t']:.0f}s prima dell'F8 in "
                              f"{pre['secs']}s, {pre['frames']} immagini dell'osservatore)\n"
                              f"update_match: {json.dumps(args, ensure_ascii=False)}")
            else:
                shot = self.hidden_capture()
                region = screen.last_region
                frames = self._take_obs_frames()
                mine, opp, times = self._read_screen(shot, frames, store.load("match"))
                self._journal("")
                if not reader.usable(mine, opp):
                    fase = (mine or {}).get("fase")
                    if mine is None or opp is None:  # i lettori non rispondono: dopo due volte giro normale
                        self._fast_fail = getattr(self, "_fast_fail", 0) + 1
                        if self._fast_fail >= 2:
                            self.say("Lettura veloce sospesa per questa partita: i lettori non rispondono. Uso il giro "
                                     "normale.", "dim")
                    else:
                        self._fast_fail = 0
                    self._journal(f"Lettura veloce non usata ({fase or 'lettura non valida'}, {time.time() - t0:.1f}s):"
                                  " giro normale")
                    self.busy = False
                    prompt = (PROMPT_AUTO if auto and not self.pilot_on else PROMPT_TURNO).format(mode=self._mode())
                    if getattr(self, "pilot_on", False) and self._mode() != "ranked":
                        prompt += PROMPT_PILOTA
                    if frames:
                        n_mom = sum(len(f.get("foglio") or [f]) for f in frames)
                        prompt = PROMPT_OSSERVATORE.format(n=f"{n_mom} momenti in {len(frames)} immagini") + prompt
                    self._ask(self._recent_text() + prompt, label=None if auto else "Analisi round", attach=True,
                              kind="live", frames=frames, shot=shot, region=region)
                    return True
                self._fast_fail = 0
                state, args, warn = self._apply_reading(mine, opp)
                self._journal(f"Lettura veloce: {time.time() - t0:.1f}s (lato tuo {times.get('mio')}s, avversario "
                              f"{times.get('avv')}s, {len(frames)} immagini dell'osservatore)\n"
                              f"update_match: {json.dumps(args, ensure_ascii=False)}")
                log.info("lettura veloce in %.1fs %s", time.time() - t0, times)
        self._emit_hud(force=True)
        prompt = PROMPT_TURNO_LETTO.format(mode=self._mode(), recenti=self._recent_text(),
                                           avvisi="; ".join(warn) or "nessuno", stato=state)
        if getattr(self, "pilot_on", False) and self._mode() != "ranked":
            prompt += PROMPT_PILOTA
        self.busy = False
        self._ask(prompt, label=None if auto else "Analisi round", attach=True, kind="live", shot=shot, region=region)
        return True

    def _round_surprises(self) -> list[str]:
        """Le sorprese del round: carte avversarie non previste, combattimento diverso dal simulato (da update_match) e
        consiglio del round prima non seguito. Senza sorprese il turno di apprendimento non parte: si impara a fine
        partita."""
        from origins import history
        if not store.FILES["match"].exists():
            return []
        m = store.load("match") or {}
        out = list((m.get("sorprese_round") or {}).get("voci") or []) \
            if (m.get("sorprese_round") or {}).get("turno") == m.get("turno") else []
        snaps = [s for s in (m.get("storico") or []) if isinstance(s.get("turno"), int)]
        prev = self._recent_moves[-2] if len(self._recent_moves) >= 2 else ""
        if prev and len(snaps) >= 2:
            t_now = snaps[-1]["turno"]
            before = next((s for s in reversed(snaps) if s["turno"] < t_now), None)
            if before:
                played = history._diff(snaps[-1].get("miei_giocati"), before.get("miei_giocati"))
                mine = {store.slug(c): c for c in (m.get("carte_mie") or []) + [m.get("leggendaria_mia") or ""] if c}
                wanted = history._wanted(prev.split("▶", 1)[-1], mine)
                if wanted and played and not (wanted & {store.slug(c) for c in played}):
                    out.append(f"Daniele non ha seguito il consiglio ({prev}): ha giocato {', '.join(played)}")
        return out

    def _warm_reader(self, r) -> None:
        try:
            r.ensure()
        except Exception:  # noqa: BLE001
            log.exception("avvio anticipato del lettore fallito")

    def _rotate_live(self) -> None:
        """Contesto pulito a ogni round: la sessione del round finito (con le sue immagini) si chiude e ne parte una
        nuova già accesa per il prossimo F8. Le immagini dei round prima rallentavano ogni risposta."""
        if not store.load("config").get("contesto_pulito", True) or not self.claude:
            return
        old = self.session
        self.session = type(old)(old.exe, old.cwd) if old else ClaudeSession(self.claude, ROOT)
        try:
            m = store.load("match") if store.FILES["match"].exists() else {}
            self.session.thinking, why = thinking_budget(m, store.load("config"))
            log.info("ragionamento per il prossimo round: %s token (%s)", self.session.thinking, why)
        except Exception:  # noqa: BLE001
            log.exception("budget di ragionamento")
        threading.Thread(target=self._prewarm, daemon=True, name="bb-prewarm").start()
        if old:
            threading.Thread(target=old.close, daemon=True).start()

    def _do_chat(self, text: str) -> None:
        ctx = ""
        if self._last_live and store.load("config").get("contesto_pulito", True):
            ctx = f"(La tua ultima risposta in partita era:\n{self._last_live}\n)\n"
        self._ask(ctx + PROMPT_CHAT.format(text=text, mode=self._mode()), label=text)

    def _do_scan(self, _=None) -> None:
        try:
            p = self.hidden_capture(screen.SCAN)
        except Exception as e:  # noqa: BLE001
            log.exception("cattura scansione fallita")
            self.say(f"Cattura fallita: {e}", "warn")
            return
        n = len(list(screen.SCAN.glob("*.png")))
        log.info("scan salvata %s da %s", p.name, screen.last_source)
        warn = screen.last_source.startswith("schermo intero")
        self.emit({"type": "flash"})
        self.status(f"Scansione salvata · {n} in coda" + (" · ⚠ schermo intero" if warn else ""))

    def _do_new_match(self, deck: str) -> None:
        threading.Thread(target=self._cleanup_space, daemon=True, name="bb-spazio").start()
        with self._obs_lock:
            self.obs_frames = []
        self._obs_n = 0
        if self.session:
            self.session.reset()
            threading.Thread(target=self._prewarm, daemon=True).start()
        self.journal_dir = None
        self.req_n = 0
        self.live_n = 0
        self.flags = []
        self._recent_moves, self._last_live, self._fast_fail, self._pre = [], "", 0, None
        for r in self.readers.values():
            threading.Thread(target=self._warm_reader, args=(r,), daemon=True).start()
        cfg = store.load("config")
        self._journal(f"# Partita del {time.strftime('%d/%m/%Y %H:%M')}\nMazzo: {deck}\n"
                      f"Modalità: {cfg.get('modalita')} · modello: {cfg.get('modello_live', 'sonnet')}")
        self.emit({"type": "clear"})
        self._ask(f"Nuova partita. Il mio mazzo: {deck}. Se è un mazzo salvato chiama start_match. Se ti dico "
                  "di leggerlo dallo schermo, usa get_screen. Altrimenti salvalo con save_deck e poi "
                  "start_match. Rispondi con 'Pronto', l'elenco delle 13 carte in una riga ed eventuali "
                  "problemi del mazzo.", label=f"Nuova partita · {deck}", attach=True)

    def _do_end_match(self, result: str) -> None:
        # partita finita: si fermano l'analisi automatica e (dopo, così il messaggio resta visibile) la registrazione
        if self.auto_on or self.pilot_on:
            self.auto_on = False
            self.pilot_on, self._pilot_stop = False, True
            self.emit_state()
        flags = ""
        if self.flags:
            flags = ("\nDurante la partita Daniele ha segnalato questi errori tuoi:\n" + "\n".join(f"- {f}" for f in self.flags)
                     + "\nPer ciascuno controlla con i dati se l'errore c'era davvero. Se sì, registra una lezione con "
                     "record_lesson (tipo errore_coach, fonte \"Daniele\"); se era un errore di lettura dello schermo, "
                     "la lezione dice come leggerlo giusto. Se invece il tuo consiglio era corretto, non registrare "
                     "niente e diglielo nel riepilogo, con il motivo.")
        cur = store.load("match") if store.FILES["match"].exists() else {}
        test = PROMPT_FINE_TEST.format(nome=cur["progetto"], v=cur.get("versione")) if cur.get("progetto") else ""
        diary = ""
        if self.journal_dir is not None and store.load("config").get("contesto_pulito", True):
            # con il contesto pulito a ogni round la sessione non ricorda la partita: il diario sì
            diary = (f" Il contesto riparte pulito a ogni round, quindi i round passati non li hai in memoria: leggi il "
                     f"diario della partita con Read ({self.journal_dir / 'diario.md'}) e get_match.")
        self._ask(f"Partita finita: {result}. Chiama end_match con il risultato e tutte le carte avversarie "
                  f"viste.{diary} Ripensa alla partita intera: registra con record_lesson le lezioni sul piano "
                  "dell'avversario e sui momenti decisivi che non avevi ancora registrato (niente doppioni: quelle "
                  f"simili vengono rafforzate).{flags} Poi dammi in 3 righe di testo semplice (niente markdown, niente "
                  "asterischi): il mio errore principale, cosa ha fatto "
                  f"bene l'avversario, un consiglio per il prossimo match.{test}", label=f"Fine partita · {result}",
                  kind="fine")
        if self.rec_on:
            self._do_record(False)
        if getattr(self, "_study_after_match", False):
            self._study_after_match = False
            threading.Timer(5, self.study_recordings).start()
        if self.journal_dir is not None:
            self.emit({"type": "action", "label": "RIVEDI E PARLANE CON BIG-BOB", "call": "open_replay"})
            self.emit({"type": "action", "label": "STATISTICHE", "call": "open_stats"})
        self.emit({"type": "action", "label": "COSA HO IMPARATO", "call": "open_learned"})

    def _do_flag(self, note: str) -> None:
        self._journal(f"### ❌ SEGNALAZIONE dopo richiesta #{self.req_n} ({time.strftime('%H:%M:%S')})\n{note}")
        self.flags.append(f"dopo la richiesta #{self.req_n}: {note}")
        self.status("Segnalazione salvata nel diario")

    def _do_record(self, on: bool) -> None:
        if on and not self.rec_on:
            self.rec_dir = screen.new_recording()
            self.rec_count = 0
            self.rec_on = True
            self.say("Registrazione avviata: gioca normalmente. Salvo un fotogramma a ogni cambio di schermata "
                     "senza chiamare Claude. F10 nasconde la finestra.", "dim")
        elif not on and self.rec_on:
            self.rec_on = False
            if self.rec_dir is not None:
                self.say(f"Registrazione salvata: {self.rec_count} fotogrammi in {self.rec_dir.name}. "
                         "In Claude Code scrivi /impara-regole.", "dim")
            self.rec_dir = None
        self.emit_state()

    def _do_record_frame(self, _=None) -> None:
        if not self.rec_on or self.rec_dir is None:
            return
        self.rec_count += 1
        name = f"{self.rec_count:04d}_{time.strftime('%H%M%S')}.jpg"
        if self.ui.is_visible():
            # senza nascondere BIG-BOB (niente lampeggio): invisibile alle catture, o con la sua zona annerita
            img = screen.grab_masked(store.load("config").get("titolo_finestra", "Origins"), self._capture_mask(),
                                     max_width=1920)
            img.convert("RGB").save(self.rec_dir / name, "JPEG", quality=88)
            self.last_capture = time.time()
        else:
            p = self.hidden_capture(self.rec_dir)
            with Image.open(p) as im:
                im.convert("RGB").save(p.with_name(name), "JPEG", quality=88)
            p.unlink(missing_ok=True)
        self.status(f"Registrazione: {self.rec_count} fotogrammi")

    # ------------------------------------------------ osservatore: la partita tra un F8 e l'altro
    OBS_MAX_ATTACH = 10    # ritagli allegati al massimo a un F8 (uno per ogni tratto, poi i più cambiati)
    OBS_MAX_KEEP = 400     # file tenuti nel diario per partita
    OBS_LOCAL_T = 8        # quanto deve cambiare una zona (0-255) per salvare un fotogramma

    def _observe(self, mask, score: float) -> None:
        """Cattura e salva un fotogramma (senza ritaglio: usato quando non si sa cosa è cambiato)."""
        try:
            img = screen.grab_masked(store.load("config").get("titolo_finestra", "Origins"), mask, max_width=1600)
            self._observe_img(img, None, score, False)
        except Exception:  # noqa: BLE001
            log.exception("fotogramma dell'osservatore non salvato")

    def _observe_img(self, img, grid, score: float, moving: bool) -> None:
        """Mette il fotogramma in coda per il salvataggio: il ciclo di osservazione non aspetta il disco."""
        from origins import observer
        bbox = observer.changed_bbox(grid) if grid else None
        item = {"img": img, "bbox": bbox, "score": score, "t": time.time(), "ora": time.strftime("%H:%M:%S"),
                "moving": moving}
        if getattr(self, "_obs_async", False):
            try:
                self._obs_save_q.put_nowait(item)
                return
            except Exception:  # noqa: BLE001  (coda piena: lo salvo subito)
                pass
        self._save_obs(item)

    def _obs_saver(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._obs_save_q.get(timeout=0.5)
            except Exception:  # noqa: BLE001
                continue
            try:
                self._save_obs(item)
            finally:
                self._obs_save_q.task_done()

    def _obs_flush(self, timeout: float = 1.5) -> None:
        """Aspetta che i fotogrammi in coda siano salvati (all'F8 servono anche quelli degli ultimi istanti)."""
        q = getattr(self, "_obs_save_q", None)
        end = time.time() + timeout
        while q is not None and q.unfinished_tasks and time.time() < end:
            time.sleep(0.02)

    def _save_obs(self, item: dict) -> None:
        from origins import observer
        try:
            self._journal("")
            folder = self.journal_dir / "osservatore"
            folder.mkdir(exist_ok=True)
            self._obs_n += 1
            stamp = time.strftime("%H%M%S", time.localtime(item["t"]))
            full = folder / f"{self._obs_n:04d}_{stamp}.jpg"
            rgb = item["img"].convert("RGB")
            small = rgb if rgb.width <= 1600 else rgb.resize((1600, int(rgb.height * 1600 / rgb.width)), Image.BILINEAR)
            small.save(full, "JPEG", quality=72)
            bbox = item["bbox"]
            part = full
            if bbox and (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < 0.7:
                part = folder / f"{self._obs_n:04d}_{stamp}_zona.jpg"
                observer.crop(rgb, bbox).save(part, "JPEG", quality=85)  # dalla risoluzione piena: testo leggibile
            with self._obs_lock:
                self.obs_frames.append({"path": part, "intera": full, "score": item["score"], "t": item["t"],
                                        "ora": item["ora"], "zona": observer.position_label(bbox), "bbox": bbox,
                                        "movimento": item["moving"]})
                self.obs_frames = self.obs_frames[-400:]
                self.obs_saved = getattr(self, "obs_saved", 0) + 1
            if self._obs_n % 20 == 0:
                old = sorted(folder.glob("*.jpg"))
                for f in old[:-self.OBS_MAX_KEEP]:
                    f.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            log.exception("fotogramma dell'osservatore non salvato")

    def _take_obs_frames(self) -> list[dict]:
        """I fotogrammi da allegare all'F8, in ordine di tempo: senza i doppioni della stessa animazione e, se sono
        tanti, affiancati in fogli da 2-4 ritagli (al massimo OBS_MAX_ATTACH immagini). Poi si azzera."""
        from origins import observer
        self._obs_flush()
        with self._obs_lock:
            frames, self.obs_frames = self.obs_frames, []
            saved, self.obs_saved = getattr(self, "obs_saved", 0), 0
        frames = [f for f in frames if Path(f["path"]).exists()]
        groups = observer.plan(frames, self.OBS_MAX_ATTACH)
        out, n = [], 0
        for g in groups:
            if len(g) == 1:
                n += 1
                out.append({**g[0], "num": str(n)})
                continue
            try:
                ims, labs = [], []
                for f in g:
                    n += 1
                    with Image.open(f["path"]) as im:
                        ims.append(im.convert("RGB"))
                    labs.append(str(n))
                p = Path(g[0]["path"]).with_name(Path(g[0]["path"]).stem + "_foglio.jpg")
                observer.sheet(ims, labs).save(p, "JPEG", quality=85)
                out.append({"path": p, "foglio": [{**f, "num": lab} for f, lab in zip(g, labs)], "t": g[0]["t"],
                            "ora": g[0]["ora"], "zona": "", "score": max(f["score"] for f in g)})
            except Exception:  # noqa: BLE001
                log.exception("foglio dell'osservatore")
                out += g
        kept = sum(len(x.get("foglio") or [x]) for x in out)
        self.obs_stats = {"salvati": len(frames), "momenti": kept, "immagini": len(out), "da_quando": saved,
                          "ciclo": round(getattr(self, "_obs_cycle", 0.0), 2)}
        log.info("osservatore: %s", self.obs_stats)
        return out

    # ------------------------------------------------ cattura con finestra nascosta
    def _capture_mask(self):
        """La zona da annerire nelle catture: nessuna se BIG-BOB è invisibile alle catture (vede il gioco sotto)."""
        if getattr(self, "capture_excluded", False) or not self.ui.is_visible():
            return None
        return self.ui.rect()

    def hidden_capture(self, folder: Path | None = None) -> Path:
        title = store.load("config").get("titolo_finestra", "Origins")
        # se BIG-BOB è invisibile alle catture non serve nasconderlo: niente lampeggio
        visible = self.ui.is_visible() and not getattr(self, "capture_excluded", False)
        self.capturing = True
        try:
            if visible:
                self.ui.hide()
                time.sleep(0.22)  # tempo a Windows per ridisegnare il gioco sotto
            return screen.capture(title, folder)
        finally:
            if visible:
                self.ui.show()
            self.capturing = False
            self.last_capture = time.time()

    # ------------------------------------------------ diario
    def _journal(self, text: str) -> None:
        if self.journal_dir is None:
            self.journal_dir = ROOT / "logs" / "partite" / time.strftime("%Y%m%d-%H%M%S")
            self.journal_dir.mkdir(parents=True, exist_ok=True)
        if text:
            with (self.journal_dir / "diario.md").open("a", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n\n")

    # ------------------------------------------------ chiamata a Claude Code
    def _ask(self, prompt: str, label: str | None, attach: bool = False, kind: str = "other",
             frames: list | None = None, shot: Path | None = None, region=None) -> None:
        if not self.claude:
            self.say("Claude Code non trovato.", "warn")
            return
        if self.busy:
            self.status("Sto ancora rispondendo… attendi")
            return
        if not self._session_free.is_set():  # sta ancora imparando dal round prima: di solito pochi secondi
            self.status("Finisco di imparare dal round precedente…")
            self._session_free.wait(45)
        # nella finestra resta solo la richiesta attuale e la sua risposta (lo storico è nel diario / RIVEDI)
        self.emit({"type": "clear"})
        if label and kind != "live":  # per F8 basta la mossa: la scritta "Analisi round" sarebbe solo rumore
            self.say(label, "me")
        if shot is not None:  # cattura già fatta (lettura veloce)
            self._shot_region = region
        else:
            try:
                if kind != "crea":  # creare un mazzo non riguarda lo schermo
                    shot = self.hidden_capture()  # get_screen userà questa cattura (finestra esclusa)
                    self._shot_region = screen.last_region
            except Exception:  # noqa: BLE001
                log.exception("pre-cattura fallita: Claude catturerà da solo")
        self.req_n += 1
        img_note = ""
        if shot is not None:
            try:
                self._journal("")
                dest = self.journal_dir / f"{self.req_n:02d}.jpg"  # JPEG: ~10 volte più leggero del PNG, leggibile
                with Image.open(shot) as im:
                    im.convert("RGB").save(dest, "JPEG", quality=85)
                img_note = f" · schermata {dest.name}"
            except Exception:  # noqa: BLE001
                log.exception("copia schermata nel diario fallita")
        self._journal(f"## #{self.req_n} · {time.strftime('%H:%M:%S')} · {label or 'AUTO'}{img_note}")
        self.busy = True
        self.last_call = time.time()
        what = {"live": "Penso alla mossa", "fine": "Analizzo la partita",
                "crea": "Creo il mazzo"}.get(kind, "Penso alla risposta")
        # il limite dei 40 secondi vale solo in partita (F8/AUTO): creare un mazzo o analizzare la partita finita
        # può richiedere il tempo che serve
        f8_t0, self._f8_t0 = getattr(self, "_f8_t0", None), None
        self._run_t0 = f8_t0 if (kind == "live" and f8_t0 and time.time() - f8_t0 < 120) else time.time()
        self.emit({"type": "busy", "value": True, "what": what, "budget": BUDGET_SECONDS if kind == "live" else 0,
                   "continua": bool(f8_t0) and self._run_t0 == f8_t0, "da": round(time.time() - self._run_t0, 1)})
        content: list[dict] = []
        import base64
        n_frames = len(frames or [])
        for i, f in enumerate(frames or [], 1):  # prima i fotogrammi dell'osservatore, in ordine di tempo
            path = Path(f["path"]) if isinstance(f, dict) else Path(f)
            try:
                data = base64.b64encode(path.read_bytes()).decode()
            except OSError:
                continue
            if isinstance(f, dict) and f.get("foglio"):
                parts = [f"[{x['num']}] {x.get('ora', '')} {x.get('zona', '')}"
                         f"{' (animazione)' if x.get('movimento') else ''}" for x in f["foglio"]]
                content.append({"type": "text", "text": f"Immagine {i}/{n_frames}: foglio con {len(parts)} ritagli "
                                                        f"numerati, in ordine di tempo: " + " · ".join(parts)})
            elif isinstance(f, dict):
                content.append({"type": "text", "text": f"Immagine {i}/{n_frames} · [{f.get('num', i)}] {f.get('ora', '')}"
                                                        f" · zona cambiata: {f.get('zona', '')}"
                                                        f"{' (durante un’animazione)' if f.get('movimento') else ''}"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        if frames:
            names = [(Path(f["path"]) if isinstance(f, dict) else Path(f)).name for f in frames]
            st = getattr(self, "obs_stats", None) or {}
            extra = (f" · {st.get('momenti')} momenti da {st.get('salvati')} fotogrammi salvati, ciclo "
                     f"{st.get('ciclo')} s") if st else ""
            self._journal(f"Osservatore: {len(frames)} immagini allegate{extra} ({', '.join(names)})")
        if attach and shot is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                         "data": base64.b64encode(shot.read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt})
        self._session_free.clear()
        threading.Thread(target=self._run_claude, args=(content, kind), daemon=True, name="bb-claude").start()

    def _run_claude(self, content: list[dict], kind: str = "other") -> None:
        learn = False
        t0 = time.time()
        t_all = getattr(self, "_run_t0", None) or t0  # dall'F8 (lettura compresa): è il tempo che vede Daniele
        steps: list[str] = []
        texts: list[str] = []
        sess = self.session
        if kind == "crea":  # sessione a parte: niente tetto al ragionamento e la partita in corso non si sporca
            sess = self.lab_session = getattr(self, "lab_session", None) or ClaudeSession(self.claude, ROOT, live=False)
        try:
            partial, previewed = "", False
            for ev in sess.ask(content, timeout=120 if kind == "live" else 900):
                if ev.get("type") == "stream_event" and kind == "live" and not previewed:
                    e2 = ev.get("event") or {}
                    if e2.get("type") == "content_block_start":
                        partial = ""
                    delta = e2.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        partial += delta.get("text") or ""
                        pv = preview_move(partial)
                        if pv:
                            previewed = True
                            self.emit({"type": "preview", **pv, "secs": round(time.time() - t_all, 1)})
                    continue
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            texts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "").replace("mcp__origins__", "")
                            steps.append(f"{time.time() - t0:.1f}s {name}")
                            self.status(f"⚙ {name}")
                elif ev.get("type") == "result":
                    usage.add_from_result(ev, sess)
                    final = (ev.get("result") or (texts[-1] if texts else "")).strip()
                    dt = time.time() - t_all
                    out_tok = (ev.get("usage") or {}).get("output_tokens")
                    self._journal(f"Strumenti: {' → '.join(steps) or 'nessuno'}\nTempo totale: {dt:.1f}s"
                                  f" · token generati: {out_tok}\n\n{final}")
                    log.info("risposta in %.1fs (%s) token %s", dt, " → ".join(steps), out_tok)
                    if ev.get("is_error"):
                        self.say(final or "Errore da Claude Code", "warn")
                    elif final not in ("—", "-", ""):
                        parsed = parse_live(final) if kind not in ("fine", "crea") else None  # testo semplice
                        self.emit({"type": "answer", "text": final, "parsed": parsed, "secs": round(dt, 1)})
                        if parsed and parsed.get("mossa") and store.load("config").get("voce", True):
                            self.voice.say(parsed["mossa"])
                        if kind == "live":
                            self._last_live = final
                            if parsed and parsed.get("mossa"):
                                turn = (store.load("match") or {}).get("turno") if store.FILES["match"].exists() else None
                                self._recent_moves = (self._recent_moves + [f"R{turn} ▶ {parsed['mossa']}"])[-6:]
                            self._pilot_after(final)
                            self.live_n += 1
                            learn = (self.live_n >= 2 and store.load("config").get("apprendimento_live", True)
                                     and bool(self._round_surprises()))  # si impara solo dalle sorprese
                    self.emit({"type": "timing", "secs": round(dt, 1), "budget": BUDGET_SECONDS if kind == "live" else 0})
        except Exception as e:  # noqa: BLE001
            log.exception("chiamata a Claude fallita")
            self.say(f"Errore: {e}", "warn")
        finally:
            self.busy = False
            self.emit({"type": "busy", "value": False})
            self._emit_hud(force=True)
            if usage.visible():
                self.emit({"type": "usage", **usage.summary()})
            try:
                self._lab_after(kind)
            except Exception:  # noqa: BLE001
                log.exception("aggiornamento laboratorio")
            if kind == "live" and (learn or store.load("config").get("barra_vantaggio", True)):
                self._learn(learn)
            if kind == "live":
                self._rotate_live()
            if kind == "fine":
                try:
                    self._link_journal()
                except Exception:  # noqa: BLE001
                    log.exception("collegamento del diario alla partita")
            if kind in ("fine", "crea"):
                self._brain_soon()
            self._session_free.set()

    def _learn(self, learn: bool = True) -> None:
        """Dopo la risposta live, mentre Daniele legge e gioca: impara da ciò che non era stato previsto e aggiorna la
        barra di vantaggio (stima di chi sta vincendo). Senza apprendimento fa solo la stima, in un turno brevissimo."""
        cfg = store.load("config")
        valuta = PROMPT_VALUTA if cfg.get("barra_vantaggio", True) else ""
        if not learn and not valuta:
            return
        if learn:
            sur = self._round_surprises()
            prev = self._recent_moves[-2] if len(self._recent_moves) >= 2 else "nessuno"
            ctx = (f"Il tuo consiglio del round prima: {prev}.\nSORPRESE trovate da BIG-BOB in questo round (parti da "
                   "queste, non cercarne altre se non le vedi chiaramente): " + " · ".join(sur) + "\n")
            prompt = PROMPT_IMPARA.format(valuta=valuta, contesto=ctx)
        else:
            prompt = PROMPT_SOLO_VALUTA
        self.learning = True
        self.emit({"type": "learning", "value": True})
        t0 = time.time()
        learned: list[str] = []
        learned_eval = ""
        try:
            for ev in self.session.ask([{"type": "text", "text": prompt}], timeout=60):
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "").replace("mcp__origins__", "")
                            inp = block.get("input") or {}
                            if name == "record_lesson" and inp.get("lezione"):
                                learned.append(inp["lezione"])
                                self.emit({"type": "say", "role": "lesson", "text": inp["lezione"]})
                            elif name == "rules_upsert":
                                self.emit({"type": "say", "role": "lesson",
                                           "text": "Regola aggiornata: " + (inp.get("testo") or inp.get("id") or "")})
                            elif name == "lesson_review" and inp.get("stato") == "smentita":
                                self.emit({"type": "say", "role": "lesson",
                                           "text": f"Lezione {inp.get('id')} smentita da questo round"})
                            elif name == "set_match_eval":
                                learned_eval = f"vantaggio: vinci al {inp.get('mia_percentuale')}% ({inp.get('motivo', '')})"
                elif ev.get("type") == "result":
                    usage.add_from_result(ev, self.session)
                    summary = (ev.get("result") or "").strip()
                    lines = [f"- {x}" for x in learned] + ([f"- {learned_eval}"] if learned_eval else [])
                    title = "📚 Apprendimento" if learn else "📊 Valutazione"
                    self._journal(f"### {title} ({time.time() - t0:.1f}s)\n" + ("\n".join(lines) or summary or "nessuna sorpresa"))
        except Exception:  # noqa: BLE001
            log.exception("turno di apprendimento fallito")
        finally:
            self.learning = False
            self.emit({"type": "learning", "value": False})
            self._emit_hud(force=True)  # la barra di vantaggio con la stima di BIG-BOB

    # ------------------------------------------------ HUD dalla partita in corso
    def _emit_hud(self, force: bool = False) -> None:
        p = store.FILES["match"]
        mtime = p.stat().st_mtime if p.exists() else 0.0
        if not force and mtime == self._match_mtime:
            return
        self._match_mtime = mtime
        m = store.load("match") if p.exists() else {}
        self._match_active = bool(m)
        if not m:
            self.emit({"type": "hud", "match": None})
            return

        def lanes(vals, reinf):
            vals = vals or [None, None, None]
            reinf = reinf or [False, False, False]
            out = []
            for i in range(3):
                v = vals[i] if i < len(vals) else None
                r = bool(reinf[i]) if i < len(reinf) else False
                mx = 40 if (r or (isinstance(v, (int, float)) and v > 20)) else 20
                out.append({"v": v, "max": mx, "rinf": mx == 40})
            return out

        self.emit({"type": "hud", "match": {
            "round": m.get("turno"), "mana": m.get("mana"), "rivela_prima": m.get("rivela_prima"),
            "rivela_prima_dedotta": m.get("rivela_prima_dedotta"),
            "mie": lanes(m.get("barrier_mie"), m.get("rinforzate_mie")),
            "avv": lanes(m.get("barrier_avv"), m.get("rinforzate_avv")),
            "distrutte_da_me": m.get("distrutte_da_me"), "distrutte_a_me": m.get("distrutte_a_me"),
            "mazzo": m.get("mio_mazzo"), "avv_leggendaria": m.get("avv_leggendaria"),
            "location": [self._loc(n) for n in (m.get("location") or [])[:3]],
            "contatori": evaluate.counters(m), "valutazione": evaluate.current_eval(m),
            "avv_mazzo": self._opp_deck(m),
        }})

    @staticmethod
    def _opp_deck(m: dict):
        from origins import archetype
        try:
            sh = archetype.short(archetype.identify(m))
            pr = archetype.predict(m)
            probs = [{"carta": x["carta"], "p": round(x["p_mano"] * 100)}
                     for x in (pr.get("giocabili") or pr.get("carte") or [])[:3]]
            if sh is None and probs:
                sh = {"tipo": "?", "p": None, "mazzo": None, "p_mazzo": None, "viste": 0}
            if sh is not None:
                sh["probabili"] = probs
            return sh
        except Exception:  # noqa: BLE001
            log.exception("mazzo avversario")
            return None

    @staticmethod
    def _loc(name):
        if not name:
            return None
        e = store.find("locations", name)
        return {"nome": e["nome"] if e else name, "testo": (e or {}).get("testo", "nuova: non ancora nel database")}

    def _hud_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(1.0)
            try:
                self._emit_hud()
            except Exception:  # noqa: BLE001
                log.exception("hud")

    # ------------------------------------------------ Auto / Registra
    def _watch_loop(self) -> None:
        from origins import observer
        from PIL import ImageChops, ImageStat

        def d(a, b):
            return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]

        import queue
        self._obs_save_q = queue.Queue(maxsize=60)
        self._obs_async = True
        threading.Thread(target=self._obs_saver, daemon=True, name="bb-osservatore").start()
        prev = ref_rec = ref_auto = ref_obs = ref_pre = None
        last_rec = last_obs = last_pre = 0.0
        still_since = None
        cfg, cfg_t = {}, 0.0
        period = 0.3
        while not self._stop.is_set():
            t0 = time.time()
            if t0 - cfg_t > 1.0:  # la configurazione si rilegge al massimo una volta al secondo
                cfg, cfg_t = store.load("config"), t0
            observing = self._match_active and cfg.get("osservatore", True)
            if not (self.auto_on or self.rec_on or observing):
                prev = ref_rec = ref_auto = ref_obs = None
                time.sleep(0.7)
                continue
            excluded = getattr(self, "capture_excluded", False)
            # con BIG-BOB invisibile alle catture l'F8 non nasconde la finestra: si può continuare a guardare
            if not excluded and (self.capturing or time.time() - self.last_capture < 1.0):
                time.sleep(0.2)
                continue
            title = cfg.get("titolo_finestra", "Origins")
            try:
                mask = self._capture_mask()
                if observing:  # una sola cattura veloce a piena risoluzione: per capire cosa cambia e per i ritagli
                    img = screen.grab_fast(title, mask)
                    sig = observer.signature(img)
                else:
                    img = None
                    sig = screen.thumbnail_signature(title, mask=mask)
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
                continue
            if prev is None:
                prev = ref_rec = ref_auto = ref_obs = sig
                continue
            local_move = observer.cell_diff(sig, prev)[0]
            moving = d(sig, prev) > 1.0 or local_move > 12
            prev = sig
            now_t = time.time()
            self._last_sig = sig
            still_since = None if moving else (still_since or now_t)
            if observing and img is not None:
                # osservatore: salva ogni volta che una zona cambia rispetto all'ultimo fotogramma salvato, anche
                # durante le animazioni; i doppioni della stessa animazione si tolgono dopo, all'F8
                if ref_obs is None:
                    ref_obs = sig
                else:
                    loc, _glob, grid = observer.cell_diff(sig, ref_obs)
                    if loc > self.OBS_LOCAL_T and now_t - last_obs >= 0.3:
                        self._observe_img(img, grid, loc, moving)
                        ref_obs, last_obs = sig, now_t
            else:
                ref_obs = None
            elapsed = time.time() - t0
            self._obs_cycle = elapsed if not getattr(self, "_obs_cycle", 0) else self._obs_cycle * 0.9 + elapsed * 0.1
            time.sleep(max(0.05, (period if observing else 0.7) - elapsed))  # ritmo costante, non sleep + lavoro
            if moving:
                continue
            # lettura anticipata: lo schermo è cambiato parecchio (nuovo round) ed è fermo da un secondo
            if (observing and cfg.get("lettura_anticipata", True) and excluded and self.readers and not self.busy
                    and now_t - self.last_call > 6 and now_t - last_pre > 12 and still_since
                    and now_t - still_since >= 1.0 and (ref_pre is None or d(sig, ref_pre) > 5)):
                ref_pre, last_pre = sig, now_t
                threading.Thread(target=self._preread, args=(sig,), daemon=True, name="bb-prelettura").start()
            if self.rec_on:
                if ref_rec is None or (d(sig, ref_rec) > 2.0 and now_t - last_rec > 1.5):
                    self._q.put(("record_frame", None))
                    ref_rec, last_rec = sig, now_t
            else:
                ref_rec = None
            if self.auto_on:
                if ref_auto is None:
                    ref_auto = sig
                elif d(sig, ref_auto) > 6 and not self.busy and now_t - self.last_call > 8:
                    self.analyze(auto=True)
                    ref_auto = sig
                elif getattr(self, "pilot_on", False) and not self.busy and now_t - self.last_call > 25:
                    # pilota: a schermata ferma lo schermo non "cambia", ma il round va giocato lo stesso
                    self.analyze(auto=True)
                    ref_auto = sig
            else:
                ref_auto = None
