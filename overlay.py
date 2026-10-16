"""BIG-BOB: finestra sempre in primo piano con chat + scorciatoie globali per Origins TCG.

F8  = analizza il turno (cattura lo schermo e chiede a Claude)
F9  = cattura per la scansione di carte/location/regole (nessuna chiamata a Claude)
F10 = mostra/nascondi la finestra

Usa Claude Code in modalità non interattiva (claude -p) con il tuo abbonamento.
Ogni partita è una sessione: Claude ricorda i turni precedenti finché non premi "Nuova partita".
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import scrolledtext, simpledialog

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Con pythonw non c'è console: tutti gli errori finiscono in logs/bigbob.log
(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(filename=ROOT / "logs" / "bigbob.log", level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bigbob")
if sys.stderr is None:
    sys.stderr = open(ROOT / "logs" / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115
if sys.stdout is None:
    sys.stdout = sys.stderr

from origins import screen, store  # noqa: E402

CLAUDE = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")

PROMPT_TURNO = (
    "[F8 · analisi turno] Chiama get_screen e leggi la situazione. Aggiorna lo stato con update_match, "
    "inclusi mana, vita e numero di barrier distrutte di entrambi, chi rivela prima e carte nel mazzo "
    "(se non c'è una partita attiva e dallo schermo non capisci il mio mazzo, chiedimelo in una riga). "
    "update_match ti restituisce già le probabilità aggiornate, poi rispondi nel formato 'Risposta live' "
    "di CLAUDE.md. Modalità attuale: {mode}."
)
PROMPT_AUTO = (
    "[AUTO · lo schermo è cambiato] Chiama get_screen. Se è iniziato un nuovo turno o sono state "
    "rivelate carte, aggiorna update_match e rispondi nel formato 'Risposta live' (modalità {mode}). "
    "Se non è cambiato niente di rilevante rispondi solo: '—'."
)
PROMPT_CHAT = "{text}\n\n(Modalità: {mode}. Se ti serve vedere la partita usa get_screen.)"

BG, FG, DIM, ACC, WARN = "#14161b", "#e8e6e1", "#8b8f98", "#e0a84a", "#e06c5a"


class Overlay:
    def __init__(self) -> None:
        self.cfg = store.load("config")
        store.save("config", self.cfg)
        self.session_id: str | None = None
        self.busy = False
        self.q: queue.Queue = queue.Queue()
        self.last_call = 0.0
        self.capturing = False
        self.overlay_rect = None
        self.last_capture = 0.0
        self.auto_on = False
        self.rec_on = False
        self.rec_dir = None
        self.rec_count = 0
        self.journal_dir: Path | None = None
        self.req_n = 0

        self.root = tk.Tk()
        self.root.title("BIG-BOB")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.93)
        except tk.TclError:
            pass
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"470x600+{sw - 490}+60")
        self.auto = tk.BooleanVar(value=False)
        self.root.report_callback_exception = self._on_tk_error
        self._build()
        self._hotkeys()
        threading.Thread(target=self._auto_loop, daemon=True).start()
        self.root.after(80, self._pump)
        if not CLAUDE:
            self._say("Non trovo il comando 'claude'. Installa Claude Code e fai il login (vedi README).", "warn")
        elif self.hotkeys_ok:
            self._say("Pronto. F8 analizza il turno, F9 cattura per la scansione, F10 nasconde.\n"
                      "Se i tasti non rispondono dentro il gioco usa i pulsanti 📸 F8 / 🎴 F9 "
                      "e lancia diagnostica.bat.\nPremi 'Nuova partita' prima di iniziare.", "dim")

    # ---------------- UI ----------------
    def _build(self) -> None:
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.mode_btn = tk.Button(top, command=self._toggle_mode, relief="flat", bd=0, padx=8,
                                  font=("Segoe UI", 9, "bold"))
        self.mode_btn.pack(side="left")
        tk.Checkbutton(top, text="Auto", variable=self.auto, bg=BG, fg=FG, selectcolor=BG,
                       activebackground=BG, activeforeground=FG).pack(side="left", padx=6)
        self.rec = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="⏺ Registra", variable=self.rec, command=self._toggle_record, bg=BG, fg=WARN,
                       selectcolor=BG, activebackground=BG, activeforeground=WARN).pack(side="left")
        tk.Button(top, text="Nuova partita", command=self._new_match, relief="flat", bg="#2a2e37",
                  fg=FG, padx=8).pack(side="right")
        tk.Button(top, text="Fine partita", command=self._end_match, relief="flat", bg="#2a2e37",
                  fg=FG, padx=8).pack(side="right", padx=4)
        self._refresh_mode()

        self.out = scrolledtext.ScrolledText(self.root, wrap="word", bg=BG, fg=FG, insertbackground=FG,
                                             relief="flat", font=("Segoe UI", 10), padx=8, pady=6)
        self.out.pack(fill="both", expand=True, padx=8)
        self.out.tag_config("me", foreground=ACC)
        self.out.tag_config("dim", foreground=DIM)
        self.out.tag_config("warn", foreground=WARN)
        self.out.configure(state="disabled")

        self.status = tk.Label(self.root, text="", bg=BG, fg=DIM, anchor="w", font=("Segoe UI", 8))
        self.status.pack(fill="x", padx=10)

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=8, pady=8)
        self.entry = tk.Entry(bottom, bg="#22252c", fg=FG, insertbackground=FG, relief="flat",
                              font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", lambda e: self._send_chat())
        tk.Button(bottom, text="Invia", command=self._send_chat, relief="flat", bg=ACC, fg="#111",
                  padx=10).pack(side="left", padx=(6, 0))
        tk.Button(bottom, text="📸 F8", command=self.analyze, relief="flat", bg="#2a2e37", fg=FG,
                  padx=8).pack(side="left", padx=(6, 0))
        tk.Button(bottom, text="🎴 F9", command=self._scan, relief="flat", bg="#2a2e37", fg=FG,
                  padx=8).pack(side="left", padx=(6, 0))
        tk.Button(bottom, text="✗", command=self._flag_wrong, relief="flat", bg=WARN, fg="#111",
                  padx=8).pack(side="left", padx=(6, 0))

    def _on_tk_error(self, exc, val, tb) -> None:
        log.error("Errore interfaccia:\n%s", "".join(traceback.format_exception(exc, val, tb)))
        self._say(f"Errore: {val}  (dettagli in logs/bigbob.log)", "warn")

    def _say(self, text: str, tag: str | None = None) -> None:
        self.out.configure(state="normal")
        self.out.insert("end", text.strip() + "\n\n", tag)
        self.out.see("end")
        self.out.configure(state="disabled")

    def _refresh_mode(self) -> None:
        mode = self.cfg.get("modalita", "allenamento")
        if mode == "ranked":
            self.mode_btn.configure(text="RANKED · tracker", bg=WARN, fg="#111")
        else:
            self.mode_btn.configure(text="ALLENAMENTO", bg="#3d8f6a", fg="#111")

    def _toggle_mode(self) -> None:
        self.cfg = store.load("config")
        self.cfg["modalita"] = "allenamento" if self.cfg.get("modalita") == "ranked" else "ranked"
        store.save("config", self.cfg)
        self._refresh_mode()

    # ---------------- azioni ----------------
    def _hotkeys(self) -> None:
        def fire(action: str):
            log.info("tasto ricevuto: %s", action)
            self.q.put(("hotkey", action))
        try:
            import keyboard
            k_an = self.cfg.get("hotkey_analisi", "f8")
            k_sc = self.cfg.get("hotkey_scan", "f9")
            keyboard.add_hotkey(k_an, lambda: fire("analyze"))
            keyboard.add_hotkey(k_sc, lambda: fire("scan"))
            keyboard.add_hotkey("f10", lambda: fire("toggle"))
            log.info("scorciatoie registrate: %s %s f10", k_an, k_sc)
            self.hotkeys_ok = True
        except Exception as e:  # noqa: BLE001
            log.exception("scorciatoie non registrate")
            self.hotkeys_ok = False
            self._say(f"Scorciatoie globali non attive ({e}). Usa i pulsanti 📸 F8 e 🎴 F9.", "warn")

    def analyze(self, auto: bool = False) -> None:
        mode = store.load("config").get("modalita", "allenamento")
        self._ask((PROMPT_AUTO if auto else PROMPT_TURNO).format(mode=mode), label=None if auto else "📸 analisi turno")

    def _send_chat(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        mode = store.load("config").get("modalita", "allenamento")
        self._ask(PROMPT_CHAT.format(text=text, mode=mode), label=text)

    def _hidden_capture(self, folder=None):
        """Nasconde l'overlay per un istante, cattura il gioco e lo rimostra."""
        title = store.load("config").get("titolo_finestra", "Origins")
        was_visible = self.root.state() != "withdrawn"
        self.capturing = True
        try:
            if was_visible:
                self.root.withdraw()
                self.root.update()
                time.sleep(0.18)  # tempo a Windows per ridisegnare il gioco sotto
            return screen.capture(title, folder)
        finally:
            if was_visible:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
            self.capturing = False
            self.last_capture = time.time()

    # ---------------- diario partita (per il collaudo) ----------------
    def _journal(self, text: str) -> None:
        if self.journal_dir is None:
            self.journal_dir = ROOT / "logs" / "partite" / time.strftime("%Y%m%d-%H%M%S")
            self.journal_dir.mkdir(parents=True, exist_ok=True)
        with (self.journal_dir / "diario.md").open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n\n")

    def _flag_wrong(self) -> None:
        note = simpledialog.askstring("Segnala errore", "Cosa ha sbagliato BIG-BOB nell'ultima risposta?\n"
                                      "(es. 'mana letto 4, era 5', 'consiglio insensato: …')", parent=self.root)
        if note:
            self._journal(f"### ❌ SEGNALAZIONE dopo richiesta #{self.req_n} ({time.strftime('%H:%M:%S')})\n{note}")
            self.status.configure(text="Segnalazione salvata nel diario")

    def _toggle_record(self) -> None:
        if self.rec.get():
            self.rec_dir = screen.new_recording()
            self.rec_count = 0
            self.rec_on = True
            self._say("⏺ Registrazione avviata: gioca normalmente (meglio contro il bot). Salvo un fotogramma "
                      "a ogni cambio di schermata, senza chiamare Claude. Premi F10 per nascondere l'overlay "
                      "ed evitare che lampeggi. Togli la spunta a fine partita.", "dim")
        else:
            self.rec_on = False
            if self.rec_dir is not None:
                self._say(f"⏹ Registrazione salvata: {self.rec_count} fotogrammi in {self.rec_dir.name}. "
                          "In Claude Code scrivi /impara-regole.", "dim")
            self.rec_dir = None

    def _record_frame(self) -> None:
        if not self.rec_on or self.rec_dir is None:
            return
        self.rec_count += 1
        p = self._hidden_capture(self.rec_dir)
        p.rename(p.with_name(f"{self.rec_count:04d}_{p.name}"))
        self.status.configure(text=f"⏺ Registrazione: {self.rec_count} fotogrammi")

    def _scan(self) -> None:
        try:
            p = self._hidden_capture(screen.SCAN)
        except Exception as e:  # noqa: BLE001
            log.exception("cattura scansione fallita")
            self._say(f"Cattura fallita: {e}  (dettagli in logs/bigbob.log)", "warn")
            return
        n = len(list(screen.SCAN.glob("*.png")))
        self.root.bell()
        log.info("scan salvata %s da %s", p.name, screen.last_source)
        if screen.last_source != getattr(self, "_last_scan_source", None):
            self._last_scan_source = screen.last_source
            tag = "warn" if screen.last_source.startswith("schermo intero") else "dim"
            self._say(f"🎴 Catturo da: {screen.last_source}", tag)
        self.status.configure(text=f"🎴 Salvata {p.name} · {n} immagini in coda")

    def _new_match(self) -> None:
        decks = [d["nome"] for d in store.load("decks")]
        hint = ("Mazzi salvati: " + ", ".join(decks)) if decks else "Nessun mazzo salvato: scrivi leggendaria + 12 carte"
        deck = simpledialog.askstring("Nuova partita", f"Con quale mazzo giochi?\n{hint}", parent=self.root)
        if deck is None:
            return
        self.session_id = None
        self.journal_dir = None
        self.req_n = 0
        self._journal(f"# Partita del {time.strftime('%d/%m/%Y %H:%M')}\nMazzo: {deck}\n"
                      f"Modalità: {store.load('config').get('modalita')} · modello: "
                      f"{store.load('config').get('modello_live', 'sonnet')}")
        self._say("— nuova partita —", "dim")
        self._ask(f"Nuova partita. Il mio mazzo: {deck}. Se è un mazzo salvato chiama start_match, "
                  "altrimenti salvalo con save_deck e poi start_match. Rispondi solo 'Pronto' più "
                  "eventuali problemi del mazzo.", label=f"nuova partita · {deck}")

    def _end_match(self) -> None:
        res = simpledialog.askstring("Fine partita", "Risultato? (vittoria / sconfitta / pareggio)", parent=self.root)
        if not res:
            return
        self._ask(f"Partita finita: {res}. Chiama end_match con il risultato e tutte le carte avversarie viste. "
                  "Poi dammi in 3 righe: il mio errore principale, cosa ha fatto bene l'avversario, "
                  "un consiglio per il prossimo match.", label=f"fine partita · {res}")
        if self.journal_dir is not None:
            self._say(f"📒 Diario della partita: logs/partite/{self.journal_dir.name}/diario.md", "dim")

    # ---------------- chiamata a Claude ----------------
    def _ask(self, prompt: str, label: str | None) -> None:
        if not CLAUDE:
            self._say("Claude Code non trovato.", "warn")
            return
        if self.busy:
            self.status.configure(text="Sto ancora rispondendo… attendi")
            return
        if label:
            self._say(f"› {label}", "me")
        shot = None
        try:
            shot = self._hidden_capture()   # get_screen userà questa cattura (overlay escluso)
        except Exception:  # noqa: BLE001
            log.exception("pre-cattura fallita: Claude catturerà da solo")
        self.req_n += 1
        tag = label or "AUTO"
        img_note = ""
        if shot is not None:
            try:
                self._journal("")  # crea la cartella se serve
                dest = self.journal_dir / f"{self.req_n:02d}.png"
                shutil.copy(shot, dest)
                img_note = f" · schermata {dest.name}"
            except Exception:  # noqa: BLE001
                log.exception("copia schermata nel diario fallita")
        self._journal(f"## #{self.req_n} · {time.strftime('%H:%M:%S')} · {tag}{img_note}")
        self.busy = True
        self.last_call = time.time()
        self.status.configure(text="Sto guardando…")
        threading.Thread(target=self._run_claude, args=(prompt,), daemon=True).start()

    def _run_claude(self, prompt: str) -> None:
        cfg = store.load("config")
        cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
               "--model", cfg.get("modello_live", "sonnet"),
               "--mcp-config", str(ROOT / ".mcp.json"), "--strict-mcp-config",
               "--allowedTools", "mcp__origins", "Read"]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        t0 = time.time()
        steps: list[str] = []
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            proc.stdin.write(prompt)
            proc.stdin.close()
            texts: list[str] = []
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("session_id"):
                    self.q.put(("session", ev["session_id"]))
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            texts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "").replace("mcp__origins__", "")
                            steps.append(f"{time.time() - t0:.1f}s {name}")
                            self.q.put(("status", f"🔧 {name}"))
                elif ev.get("type") == "result":
                    final = ev.get("result") or (texts[-1] if texts else "")
                    dt = time.time() - t0
                    self.q.put(("journal", f"Strumenti: {' → '.join(steps) or 'nessuno'}\n"
                                           f"Tempo totale: {dt:.1f}s\n\n{final}"))
                    if ev.get("is_error"):
                        self.q.put(("error", final or "Errore da Claude Code"))
                    else:
                        self.q.put(("answer", final, dt))
            proc.wait()
            if proc.returncode not in (0, None):
                err = proc.stderr.read().strip()
                if err:
                    self.q.put(("error", err[-600:]))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("idle",))

    # ---------------- modalità auto ----------------
    def _auto_loop(self) -> None:
        """Rileva i cambi di schermata. Registra: salva un fotogramma a ogni cambio stabile.
        Auto: chiede un'analisi quando il cambio è grande (nuovo turno/rivelazione)."""
        from PIL import ImageChops, ImageStat

        def d(a, b):
            return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]

        prev = ref_rec = ref_auto = None
        last_rec = 0.0
        while True:
            time.sleep(0.7)
            if not (self.auto_on or self.rec_on):
                prev = ref_rec = ref_auto = None
                continue
            if self.capturing or time.time() - self.last_capture < 1.0:
                continue   # l'overlay si è appena nascosto/riapparso: campione non affidabile
            try:
                sig = screen.thumbnail_signature(store.load("config").get("titolo_finestra", "Origins"),
                                                 mask=self.overlay_rect)
            except Exception:  # noqa: BLE001
                continue
            if prev is None:
                prev = ref_rec = ref_auto = sig
                continue
            moving = d(sig, prev) > 1.0
            prev = sig
            if moving:          # aspetta che lo schermo si fermi (animazioni)
                continue
            now_t = time.time()
            if self.rec_on:
                if ref_rec is None or (d(sig, ref_rec) > 2.0 and now_t - last_rec > 1.5):
                    self.q.put(("record",))
                    ref_rec, last_rec = sig, now_t
            else:
                ref_rec = None
            if self.auto_on:
                if ref_auto is None:
                    ref_auto = sig
                elif d(sig, ref_auto) > 6 and not self.busy and now_t - self.last_call > 8:
                    self.q.put(("hotkey", "auto"))
                    ref_auto = sig
            else:
                ref_auto = None

    # ---------------- loop eventi ----------------
    def _pump(self) -> None:
        try:
            while True:
                try:
                    ev = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle(ev)
                except Exception as e:  # noqa: BLE001  un errore non deve bloccare i tasti successivi
                    log.exception("errore gestendo %s", ev)
                    self._say(f"Errore: {e}  (dettagli in logs/bigbob.log)", "warn")
        finally:
            self.auto_on = bool(self.auto.get())
            try:  # posizione dell'overlay letta qui (thread principale) per la modalità Auto
                self.overlay_rect = None if self.root.state() == "withdrawn" else (
                    self.root.winfo_rootx(), self.root.winfo_rooty(),
                    self.root.winfo_width(), self.root.winfo_height())
            except tk.TclError:
                pass
            self.root.after(80, self._pump)

    def _handle(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "hotkey":
            if ev[1] == "analyze":
                self.analyze()
            elif ev[1] == "auto":
                self.analyze(auto=True)
            elif ev[1] == "scan":
                self._scan()
            elif ev[1] == "toggle":
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                else:
                    self.root.withdraw()
        elif kind == "journal":
            self._journal(ev[1])
        elif kind == "record":
            self._record_frame()
        elif kind == "session":
            self.session_id = ev[1]
        elif kind == "status":
            self.status.configure(text=ev[1])
        elif kind == "answer":
            if ev[1].strip() not in ("—", "-", ""):
                self._say(ev[1])
            self.status.configure(text=f"Risposta in {ev[2]:.0f}s")
        elif kind == "error":
            self._say(f"Errore: {ev[1]}", "warn")
        elif kind == "idle":
            self.busy = False

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Overlay().run()
