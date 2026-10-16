"""Aggiornatore di BIG-BOB: lo avvia il pulsante AGGIORNA ORA (o aggiorna.bat lo può sostituire).

Aspetta che BIG-BOB si chiuda, scarica la nuova versione, aggiorna le librerie solo se sono cambiate,
ricrea collegamenti e icone, scrive l'esito in logs/aggiornamento.json e riapre BIG-BOB.
I dati personali (data, config.json, logs, captures) non vengono toccati.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from origins import updates  # noqa: E402

LOG = ROOT / "logs" / "aggiornamento.log"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def wait_for_exit(pid: int, timeout: float = 30) -> None:
    if sys.platform != "win32" or not pid:
        time.sleep(1.5)
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, int(timeout * 1000))
        k32.CloseHandle(h)
    time.sleep(0.5)


def run(cmd: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=NOWIN)
    log(f"$ {' '.join(cmd)} -> {r.returncode}\n{(r.stdout or '')[-1500:]}{(r.stderr or '')[-1500:]}")
    return r


def update(status=lambda s: None) -> dict:
    py = sys.executable.replace("pythonw.exe", "python.exe")
    da = updates.installed_version()
    status("Scarico la nuova versione…")
    old = updates._git("rev-parse", "HEAD").stdout.strip()
    r = updates._git("fetch", "-q", "origin", updates.BRANCH, timeout=120)
    if r.returncode != 0:
        return {"ok": False, "errore": "download non riuscito: " + (r.stderr or "").strip()[-300:], "da": da}
    r = updates._git("reset", "-q", "--hard", f"origin/{updates.BRANCH}")
    if r.returncode != 0:
        return {"ok": False, "errore": "aggiornamento dei file non riuscito: " + (r.stderr or "").strip()[-300:],
                "da": da}
    changed = updates._git("diff", "--name-only", old, "HEAD").stdout.split() if old else ["requirements.txt"]
    if "requirements.txt" in changed:
        status("Aggiorno le librerie…")
        if run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", "requirements.txt"]).returncode:
            return {"ok": False, "errore": "librerie non aggiornate (vedi logs/aggiornamento.log)", "da": da}
    status("Ricollego Claude Code e le icone…")
    run([py, "setup_mcp.py"], 60)
    run([py, "collegamenti.py", "installa"], 60)
    novita = updates._git("log", "--format=%s", f"{old}..HEAD").stdout.splitlines() if old else []
    return {"ok": True, "da": da, "a": updates.installed_version(), "novita": novita[:12]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--no-riavvio", action="store_true")
    a = ap.parse_args()

    state = {"text": "Chiudo BIG-BOB…", "done": False, "result": None}

    def work():
        wait_for_exit(a.pid)
        try:
            state["result"] = update(lambda s: state.__setitem__("text", s))
        except Exception as e:  # noqa: BLE001
            state["result"] = {"ok": False, "errore": str(e)}
        updates.RESULT.parent.mkdir(exist_ok=True)
        updates.RESULT.write_text(json.dumps(state["result"], ensure_ascii=False), encoding="utf-8")
        log(f"esito: {state['result']}")
        state["text"] = "Riapro BIG-BOB…"
        if not a.no_riavvio:
            exe = Path(sys.executable)
            pyw = exe.with_name("pythonw.exe")
            subprocess.Popen([str(pyw if pyw.exists() else exe), str(ROOT / "app.py")], cwd=ROOT,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        state["done"] = True

    t = threading.Thread(target=work, daemon=True)
    t.start()
    try:  # piccola finestra di avanzamento (se tkinter c'è)
        import tkinter as tk
        root = tk.Tk()
        root.title("BIG-BOB · aggiornamento")
        root.configure(bg="#24104F")
        root.geometry("360x110")
        root.attributes("-topmost", True)
        tk.Label(root, text="AGGIORNAMENTO DI BIG-BOB", bg="#24104F", fg="#FFD23F",
                 font=("Segoe UI", 12, "bold")).pack(pady=(18, 6))
        lab = tk.Label(root, text=state["text"], bg="#24104F", fg="#FFFFFF", font=("Segoe UI", 10))
        lab.pack()

        def tick():
            lab.configure(text=state["text"])
            if state["done"]:
                root.after(800, root.destroy)
            else:
                root.after(200, tick)
        tick()
        root.mainloop()
    except Exception:  # noqa: BLE001
        pass
    t.join()


if __name__ == "__main__":
    main()
