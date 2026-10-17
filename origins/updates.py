"""Aggiornamenti: controlla all'avvio se nel repository c'è una versione nuova e la installa con un clic.

Il controllo non chiede mai credenziali (GitHub viene interrogato in silenzio con quelle salvate da Git);
se l'accesso non è ancora stato fatto, lo dice e rimanda a «Aggiorna BIG-BOB» nel menu Start.
I dati personali (data, config.json, logs, captures) sono esclusi dal repository e non vengono toccati.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "https://github.com/daniele-angeli-dev/big_bob.git"
BRANCH = "main"
RESULT = ROOT / "logs" / "aggiornamento.json"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


_GIT: str | None = None


def git_exe() -> str | None:
    """Il comando git. Se Git è stato appena installato (dall'installer) Windows aggiorna il PATH solo dal login
    successivo: BIG-BOB aperto dall'icona non lo vedrebbe, quindi lo cerco anche nei percorsi soliti e nel PATH
    salvato nel registro."""
    global _GIT
    if _GIT and (Path(_GIT).exists() or shutil.which(_GIT)):
        return _GIT
    found = shutil.which("git")
    if not found and sys.platform == "win32":
        cands = [Path(os.environ.get(v, "")) / "Git" / "cmd" / "git.exe"
                 for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
        cands.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe")
        try:
            import winreg
            for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                try:
                    with winreg.OpenKey(root, key) as k:
                        path = os.path.expandvars(winreg.QueryValueEx(k, "Path")[0])
                    cands += [Path(d) / "git.exe" for d in path.split(";") if d]
                except OSError:
                    continue
        except ImportError:
            pass
        found = next((str(c) for c in cands if str(c) and c.exists()), None)
    _GIT = found
    return found


def _git(*args, timeout: float = 30) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    exe = git_exe() or "git"
    return subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env, creationflags=NOWIN)


def git_available() -> bool:
    return git_exe() is not None


def installed_version() -> str:
    """Versione installata: commit del repository, oppure quella scritta dall'installer."""
    if (ROOT / ".git").exists() and git_available():
        r = _git("log", "-1", "--format=%h · %cd", "--date=format:%d/%m/%Y %H:%M")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    v = ROOT / "VERSION"
    return v.read_text(encoding="utf-8").split()[0][:7] if v.exists() else "sconosciuta"


def _ensure_repo() -> None:
    """Collega la cartella al repository se l'installazione non l'ha già fatto (non scarica nulla)."""
    if (ROOT / ".git").exists():
        return
    _git("init", "-q")
    _git("remote", "add", "origin", REMOTE)


def check() -> dict:
    """{'disponibile': bool, 'novita': [...], 'versione': str, 'errore': str|None}"""
    out = {"disponibile": False, "novita": [], "versione": installed_version(), "errore": None,
           "modifiche_locali": []}
    if not git_available():
        out["errore"] = "Git non è installato: installalo per ricevere gli aggiornamenti."
        return out
    try:
        _ensure_repo()
        r = _git("fetch", "-q", "origin", BRANCH, timeout=40)
        if r.returncode != 0:
            msg = (r.stderr or "").lower()
            if "auth" in msg or "credential" in msg or "403" in msg or "could not read" in msg or "terminal prompts" in msg:
                out["errore"] = ("Accesso a GitHub non ancora fatto: apri una volta «Aggiorna BIG-BOB» dal menu Start "
                                 "e accedi nel browser.")
            else:
                out["errore"] = "Controllo aggiornamenti non riuscito: GitHub non risponde (connessione?)."
                out["rete"] = True
            return out
        head = _git("rev-parse", "-q", "--verify", "HEAD")
        if head.returncode != 0:
            # cartella appena collegata: allinea la storia alla versione installata senza toccare i file
            v = ROOT / "VERSION"
            sha = v.read_text(encoding="utf-8").split()[0] if v.exists() else ""
            if sha and _git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
                _git("reset", "-q", "--mixed", sha)
            else:
                _git("reset", "-q", "--mixed", f"origin/{BRANCH}")
        log = _git("log", "--format=%s", f"HEAD..origin/{BRANCH}")
        novita = [x for x in log.stdout.splitlines() if x.strip()]
        out["novita"] = novita[:12]
        out["disponibile"] = bool(novita)
        st = _git("status", "--porcelain", "--untracked-files=no")
        out["modifiche_locali"] = [x[3:] for x in st.stdout.splitlines() if x.strip()][:10]
        out["versione"] = installed_version()
    except subprocess.TimeoutExpired:
        out["errore"] = "Controllo aggiornamenti troppo lento (connessione?)."
        out["rete"] = True
    except Exception as e:  # noqa: BLE001
        out["errore"] = f"Controllo aggiornamenti non riuscito: {e}"
    return out


def launch_updater(app_pid: int) -> None:
    """Avvia l'aggiornamento in un processo separato: aspetta che BIG-BOB si chiuda, aggiorna e lo riapre."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else exe
    subprocess.Popen([str(runner), str(ROOT / "updater.py"), "--pid", str(app_pid)], cwd=ROOT,
                     creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)


def last_result() -> dict | None:
    """Esito dell'ultimo aggiornamento (letto una volta all'avvio, poi cancellato)."""
    if not RESULT.exists():
        return None
    try:
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = None
    RESULT.unlink(missing_ok=True)
    return data
