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
import shutil
import subprocess
import threading
import time
from pathlib import Path

from origins import deckproj, screen, store
from origins.voice import Voice

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("bigbob")

ROUND_SECONDS = 90
BUDGET_SECONDS = 40  # tempo massimo per la risposta: il resto serve a leggere e giocare

PROMPT_TURNO = (
    "[F8 · analisi round] La schermata del round è allegata: NON chiamare get_screen. Leggila e chiama UNA "
    "volta update_match con lo stato completo (mano, campo, scarti, mana, vita delle barrier e quali sono "
    "rinforzate, barrier distrutte, chi rivela prima, carte nel mio mazzo, carte in mano all'avversario): "
    "ti restituisce anche le probabilità aggiornate. Poi rispondi nel formato 'Risposta live' di CLAUDE.md. "
    "Se non c'è una partita attiva e dallo schermo non capisci il mio mazzo, chiedimelo in una riga. "
    "Tempo massimo 40 secondi. Modalità attuale: {mode}."
)
PROMPT_AUTO = (
    "[AUTO · lo schermo è cambiato] La schermata è allegata: NON chiamare get_screen. Se è iniziato un nuovo "
    "round o sono state rivelate carte, chiama UNA volta update_match e rispondi nel formato 'Risposta live' "
    "(modalità {mode}). Se non è cambiato niente di rilevante rispondi solo: '—'."
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
    "('bene'/'male'/'neutro' + mezza riga). Se non c'è nessuna sorpresa non chiamare record_lesson. Rispondi in una "
    "sola riga: 'ok' oppure cosa hai imparato."
)


def find_claude() -> str | None:
    return shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")


class ClaudeSession:
    """Un processo Claude Code acceso per tutta la partita (stream-json in ingresso e in uscita).

    Evita a ogni F8 l'avvio di Claude Code, del server MCP e il ricaricamento della sessione.
    Se il processo muore, al turno dopo ne parte un altro che riprende la stessa sessione."""

    def __init__(self, exe: str, cwd: Path) -> None:
        self.exe, self.cwd = exe, cwd
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def _cmd(self) -> list[str]:
        cfg = store.load("config")
        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--model", cfg.get("modello_live", "sonnet"),
               "--mcp-config", str(self.cwd / ".mcp.json"), "--strict-mcp-config",
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
        mt = cfg.get("max_thinking_live", 4000)
        if mt:
            env["MAX_THINKING_TOKENS"] = str(mt)
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
                raise RuntimeError("Claude Code si è chiuso: " + err.decode("utf-8", "replace")[-400:])
            yield ev
            if ev.get("type") == "result":
                return


# ---------------------------------------------------------------- parser risposta live
MARKERS = {"▶": "mossa", "⚠": "minacce", "🎴": "pescate", "👁": "avv_mano", "📍": "location"}


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
        self.session = ClaudeSession(self.claude, ROOT) if self.claude else None
        self.voice = Voice()
        cfg = store.load("config")
        store.save("config", cfg)  # crea config.json se manca
        self.busy = False
        self.capturing = False
        self.last_call = 0.0
        self.last_capture = 0.0
        self.auto_on = False
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
        threading.Thread(target=self._startup_meta, daemon=True, name="bb-originsmeta").start()
        if not self.claude:
            self.say("Non trovo il comando 'claude'. Installa Claude Code e fai il login (vedi README).", "warn")
        else:
            self.say("Pronto. F8 analizza il round, F9 cattura per la scansione, F10 nasconde. "
                     "Premi NUOVA prima di iniziare una partita.", "dim")

    def stop(self) -> None:
        self._stop.set()
        self.voice.stop()
        if self.session:
            self.session.close()

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
                   "rec": self.rec_on, "busy": self.busy, "round_seconds": ROUND_SECONDS,
                   "voice": bool(cfg.get("voce", True)) and self.voice.available(),
                   "voice_available": self.voice.available(),
                   "budget_seconds": BUDGET_SECONDS,
                   "decks": self._deck_names(), "lab": deckproj.summary()})
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
        from origins import report
        p = deckproj.active()
        if not p:
            self.say("Nessun mazzo in creazione: premi CREA MAZZO.", "dim")
            return
        try:
            self._open(report.lab_html(p["nome"]))
        except Exception as e:  # noqa: BLE001
            log.exception("pagina laboratorio")
            self.say(f"Pagina non generata: {e}", "warn")

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
        if res:
            if res.get("ok"):
                nov = "; ".join(res.get("novita") or []) or "nessun dettaglio"
                self.say(f"BIG-BOB aggiornato ({res.get('da')} → {res.get('a')}). Novità: {nov}", "lesson")
            else:
                self.say(f"Aggiornamento non riuscito: {res.get('errore')}. BIG-BOB è rimasto alla versione di prima.",
                         "warn")
        if store.load("config").get("controlla_aggiornamenti", True):
            time.sleep(3)  # lascia partire prima la finestra e Claude Code
            self._check_updates(manual=False)

    def check_updates(self) -> None:
        threading.Thread(target=self._check_updates, kwargs={"manual": True}, daemon=True).start()

    def _check_updates(self, manual: bool) -> None:
        from origins import updates
        if manual:
            self.status("Controllo aggiornamenti…")
        res = updates.check()
        log.info("controllo aggiornamenti: %s", res)
        if res["disponibile"] or manual or (res.get("errore") and "GitHub" in res["errore"]):
            self.emit({"type": "update", **res})
        if manual and not res["disponibile"] and not res.get("errore"):
            self.status(f"BIG-BOB è aggiornato (versione {res['versione']})")

    def apply_update(self) -> None:
        from origins import updates
        if self.busy:
            self.status("Aspetta la fine della risposta, poi aggiorna")
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

    # ------------------------------------------------ impostazioni e collegamento a Claude
    SETTINGS_KEYS = ("modello_live", "connessione", "voce", "apprendimento_live", "apri_claude_code_all_avvio",
                     "controlla_aggiornamenti", "max_thinking_live", "modalita", "meta_originsmeta")

    def get_settings(self) -> None:
        from origins import updates
        cfg = store.load("config")
        vals = {k: cfg.get(k) for k in self.SETTINGS_KEYS}
        vals.setdefault("connessione", "abbonamento")
        vals["connessione"] = vals["connessione"] or "abbonamento"
        vals["api_key_impostata"] = bool(cfg.get("api_key"))
        self.emit({"type": "settings", "valori": vals, "versione": updates.installed_version(),
                   "claude_trovato": bool(self.claude)})

    def save_settings(self, vals: dict) -> None:
        import configura
        cfg_before = store.load("config")
        extra = {k: vals[k] for k in ("voce", "apprendimento_live", "apri_claude_code_all_avvio",
                                      "controlla_aggiornamenti", "meta_originsmeta") if k in vals}
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
    @staticmethod
    def _open(path: Path) -> None:
        import os
        import webbrowser
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows: browser predefinito
        except Exception:  # noqa: BLE001
            webbrowser.open(path.as_uri())

    def open_stats(self) -> None:
        from origins import report
        try:
            self._open(report.stats_html())
        except Exception as e:  # noqa: BLE001
            log.exception("statistiche")
            self.say(f"Statistiche non generate: {e}", "warn")

    def open_learned(self) -> None:
        from origins import report
        try:
            self._open(report.learned_html())
        except Exception as e:  # noqa: BLE001
            log.exception("pagina cosa ho imparato")
            self.say(f"Pagina non generata: {e}", "warn")

    def open_replay(self) -> None:
        from origins import report
        d = self.journal_dir or max((ROOT / "logs" / "partite").glob("*/"), default=None)
        if d is None or not (Path(d) / "diario.md").exists():
            self.say("Nessuna partita da rivedere.", "dim")
            return
        try:
            self._open(report.replay_html(Path(d)))
        except Exception as e:  # noqa: BLE001
            log.exception("replay")
            self.say(f"Replay non generato: {e}", "warn")

    def set_voice(self, on: bool) -> None:
        cfg = store.load("config")
        cfg["voce"] = bool(on)
        store.save("config", cfg)
        if on:
            self.voice.warm()
        self.emit_state()

    def set_auto(self, on: bool) -> None:
        self.auto_on = bool(on)
        self.emit_state()

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
        prompt = (PROMPT_AUTO if auto else PROMPT_TURNO).format(mode=self._mode())
        self._ask(prompt, label=None if auto else "Analisi round", attach=True, kind="live")

    def _do_chat(self, text: str) -> None:
        self._ask(PROMPT_CHAT.format(text=text, mode=self._mode()), label=text)

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
        if self.session:
            self.session.reset()
            threading.Thread(target=self._prewarm, daemon=True).start()
        self.journal_dir = None
        self.req_n = 0
        self.live_n = 0
        self.flags = []
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
        if self.auto_on:
            self.auto_on = False
            self.emit_state()
        flags = ""
        if self.flags:
            flags = ("\nDurante la partita Daniele ha segnalato questi errori tuoi:\n" + "\n".join(f"- {f}" for f in self.flags)
                     + "\nPer ciascuno capisci cosa avevi sbagliato e registra una lezione con record_lesson "
                     "(tipo errore_coach, fonte \"Daniele\"); se era un errore di lettura dello schermo, la lezione "
                     "dice come leggerlo giusto.")
        cur = store.load("match") if store.FILES["match"].exists() else {}
        test = PROMPT_FINE_TEST.format(nome=cur["progetto"], v=cur.get("versione")) if cur.get("progetto") else ""
        self._ask(f"Partita finita: {result}. Chiama end_match con il risultato e tutte le carte avversarie "
                  "viste. Ripensa alla partita intera: registra con record_lesson le lezioni sul piano "
                  "dell'avversario e sui momenti decisivi che non avevi ancora registrato (niente doppioni: quelle "
                  f"simili vengono rafforzate).{flags} Poi dammi in 3 righe di testo semplice (niente markdown, niente "
                  "asterischi): il mio errore principale, cosa ha fatto "
                  f"bene l'avversario, un consiglio per il prossimo match.{test}", label=f"Fine partita · {result}",
                  kind="fine")
        if self.rec_on:
            self._do_record(False)
        if self.journal_dir is not None:
            self.emit({"type": "action", "label": "RIVEDI LA PARTITA", "call": "open_replay"})
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
        p = self.hidden_capture(self.rec_dir)
        p.rename(p.with_name(f"{self.rec_count:04d}_{p.name}"))
        self.status(f"Registrazione: {self.rec_count} fotogrammi")

    # ------------------------------------------------ cattura con finestra nascosta
    def hidden_capture(self, folder: Path | None = None) -> Path:
        title = store.load("config").get("titolo_finestra", "Origins")
        visible = self.ui.is_visible()
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
    def _ask(self, prompt: str, label: str | None, attach: bool = False, kind: str = "other") -> None:
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
        shot = None
        try:
            shot = self.hidden_capture()  # get_screen userà questa cattura (finestra esclusa)
        except Exception:  # noqa: BLE001
            log.exception("pre-cattura fallita: Claude catturerà da solo")
        self.req_n += 1
        img_note = ""
        if shot is not None:
            try:
                self._journal("")
                dest = self.journal_dir / f"{self.req_n:02d}.png"
                shutil.copy(shot, dest)
                img_note = f" · schermata {dest.name}"
            except Exception:  # noqa: BLE001
                log.exception("copia schermata nel diario fallita")
        self._journal(f"## #{self.req_n} · {time.strftime('%H:%M:%S')} · {label or 'AUTO'}{img_note}")
        self.busy = True
        self.last_call = time.time()
        what = {"live": "Penso alla mossa", "fine": "Analizzo la partita",
                "crea": "Creo il mazzo"}.get(kind, "Penso alla risposta")
        self.emit({"type": "busy", "value": True, "what": what})
        content: list[dict] = []
        if attach and shot is not None:
            import base64
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                         "data": base64.b64encode(shot.read_bytes()).decode()}})
        content.append({"type": "text", "text": prompt})
        self._session_free.clear()
        threading.Thread(target=self._run_claude, args=(content, kind), daemon=True, name="bb-claude").start()

    def _run_claude(self, content: list[dict], kind: str = "other") -> None:
        learn = False
        t0 = time.time()
        steps: list[str] = []
        texts: list[str] = []
        try:
            for ev in self.session.ask(content):
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            texts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "").replace("mcp__origins__", "")
                            steps.append(f"{time.time() - t0:.1f}s {name}")
                            self.status(f"⚙ {name}")
                elif ev.get("type") == "result":
                    final = (ev.get("result") or (texts[-1] if texts else "")).strip()
                    dt = time.time() - t0
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
                            self.live_n += 1
                            learn = self.live_n >= 2 and store.load("config").get("apprendimento_live", True)
                    self.emit({"type": "timing", "secs": round(dt, 1)})
        except Exception as e:  # noqa: BLE001
            log.exception("chiamata a Claude fallita")
            self.say(f"Errore: {e}", "warn")
        finally:
            self.busy = False
            self.emit({"type": "busy", "value": False})
            self._emit_hud(force=True)
            try:
                self._lab_after(kind)
            except Exception:  # noqa: BLE001
                log.exception("aggiornamento laboratorio")
            if learn:
                self._learn()
            self._session_free.set()

    def _learn(self) -> None:
        """Dopo la risposta live, mentre Daniele legge e gioca: impara da ciò che non era stato previsto."""
        self.learning = True
        self.emit({"type": "learning", "value": True})
        t0 = time.time()
        learned: list[str] = []
        try:
            for ev in self.session.ask([{"type": "text", "text": PROMPT_IMPARA}], timeout=60):
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
                elif ev.get("type") == "result":
                    summary = (ev.get("result") or "").strip()
                    self._journal(f"### 📚 Apprendimento ({time.time() - t0:.1f}s)\n"
                                  + ("\n".join(f"- {x}" for x in learned) or summary or "nessuna sorpresa"))
        except Exception:  # noqa: BLE001
            log.exception("turno di apprendimento fallito")
        finally:
            self.learning = False
            self.emit({"type": "learning", "value": False})

    # ------------------------------------------------ HUD dalla partita in corso
    def _emit_hud(self, force: bool = False) -> None:
        p = store.FILES["match"]
        mtime = p.stat().st_mtime if p.exists() else 0.0
        if not force and mtime == self._match_mtime:
            return
        self._match_mtime = mtime
        m = store.load("match") if p.exists() else {}
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
            "mie": lanes(m.get("barrier_mie"), m.get("rinforzate_mie")),
            "avv": lanes(m.get("barrier_avv"), m.get("rinforzate_avv")),
            "distrutte_da_me": m.get("distrutte_da_me"), "distrutte_a_me": m.get("distrutte_a_me"),
            "mazzo": m.get("mio_mazzo"), "avv_leggendaria": m.get("avv_leggendaria"),
            "location": [self._loc(n) for n in (m.get("location") or [])[:3]],
        }})

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
        from PIL import ImageChops, ImageStat

        def d(a, b):
            return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]

        prev = ref_rec = ref_auto = None
        last_rec = 0.0
        while not self._stop.is_set():
            time.sleep(0.7)
            if not (self.auto_on or self.rec_on):
                prev = ref_rec = ref_auto = None
                continue
            if self.capturing or time.time() - self.last_capture < 1.0:
                continue
            try:
                mask = self.ui.rect() if self.ui.is_visible() else None
                sig = screen.thumbnail_signature(store.load("config").get("titolo_finestra", "Origins"), mask=mask)
            except Exception:  # noqa: BLE001
                continue
            if prev is None:
                prev = ref_rec = ref_auto = sig
                continue
            moving = d(sig, prev) > 1.0
            prev = sig
            if moving:
                continue
            now_t = time.time()
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
            else:
                ref_auto = None
