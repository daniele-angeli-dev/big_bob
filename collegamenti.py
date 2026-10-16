"""Crea (o toglie) i collegamenti di BIG-BOB: icona sul desktop e cartella nel menu Start.

python collegamenti.py installa     -> desktop + menu Start (lo fanno installa.bat e aggiorna.bat)
python collegamenti.py disinstalla  -> toglie i collegamenti (i file e i tuoi dati restano)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON = ROOT / "ui" / "bigbob.ico"
START_FOLDER = "BIG-BOB"


def pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def shortcuts() -> list[dict]:
    """(cartella, nome, destinazione, argomenti, descrizione)"""
    py = str(pythonw())
    app = f'"{ROOT / "app.py"}"'
    return [
        {"where": "desktop", "name": "BIG-BOB", "target": py, "args": app,
         "desc": "BIG-BOB, il coach di Origins TCG"},
        {"where": "start", "name": "BIG-BOB", "target": py, "args": app,
         "desc": "BIG-BOB, il coach di Origins TCG"},
        {"where": "start", "name": "Claude Code (BIG-BOB)", "target": str(ROOT / "apri_claude_code.bat"), "args": "",
         "desc": "Comandi di BIG-BOB: /scansiona, /mazzo, /lezioni…"},
        {"where": "start", "name": "Aggiorna BIG-BOB", "target": str(ROOT / "aggiorna.bat"), "args": "",
         "desc": "Scarica l'ultima versione di BIG-BOB"},
        {"where": "start", "name": "Diagnostica BIG-BOB", "target": str(ROOT / "diagnostica.bat"), "args": "",
         "desc": "Controlla che tutto funzioni"},
        {"where": "start", "name": "Statistiche BIG-BOB", "target": str(ROOT / "statistiche.bat"), "args": "",
         "desc": "Le tue statistiche di Origins TCG"},
        {"where": "start", "name": "Cosa ha imparato BIG-BOB", "target": str(ROOT / "imparato.bat"), "args": "",
         "desc": "Lezioni e regole nuove, partita per partita"},
        {"where": "start", "name": "BIG-BOB (finestra classica)", "target": str(ROOT / "avvia_classico.bat"), "args": "",
         "desc": "Da usare se la finestra nuova non parte"},
        {"where": "start", "name": "Cartella di BIG-BOB", "target": str(ROOT), "args": "",
         "desc": "Apre la cartella con dati, diari e configurazione"},
        {"where": "start", "name": "Disinstalla collegamenti BIG-BOB", "target": str(ROOT / "disinstalla.bat"),
         "args": "", "desc": "Toglie le icone (i file e i tuoi dati restano)"},
    ]


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_script(remove: bool = False) -> str:
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$desk = [Environment]::GetFolderPath('Desktop')",
        f"$start = Join-Path ([Environment]::GetFolderPath('Programs')) {_ps_quote(START_FOLDER)}",
    ]
    if remove:
        lines += [
            "Remove-Item -LiteralPath (Join-Path $desk 'BIG-BOB.lnk') -ErrorAction SilentlyContinue",
            "if (Test-Path -LiteralPath $start) { Remove-Item -LiteralPath $start -Recurse -Force }",
            "Write-Output 'Collegamenti di BIG-BOB rimossi.'",
        ]
        return "\n".join(lines)
    lines += ["New-Item -ItemType Directory -Force -Path $start | Out-Null", "$sh = New-Object -ComObject WScript.Shell"]
    for i, s in enumerate(shortcuts()):
        folder = "$desk" if s["where"] == "desktop" else "$start"
        lines += [
            f"$l{i} = $sh.CreateShortcut((Join-Path {folder} {_ps_quote(s['name'] + '.lnk')}))",
            f"$l{i}.TargetPath = {_ps_quote(s['target'])}",
            f"$l{i}.Arguments = {_ps_quote(s['args'])}",
            f"$l{i}.WorkingDirectory = {_ps_quote(str(ROOT))}",
            f"$l{i}.IconLocation = {_ps_quote(str(ICON) + ',0')}",
            f"$l{i}.Description = {_ps_quote(s['desc'])}",
            f"$l{i}.Save()",
        ]
    lines.append("Write-Output ('Icona BIG-BOB creata sul desktop e nel menu Start (cartella ' + "
                 f"{_ps_quote(START_FOLDER)} + ').')")
    return "\n".join(lines)


def run(remove: bool = False) -> int:
    if sys.platform != "win32":
        print("I collegamenti si creano solo su Windows.")
        return 0
    script = build_script(remove)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True)
    print((r.stdout or "").strip() or (r.stderr or "").strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(run(remove=len(sys.argv) > 1 and sys.argv[1].startswith("disinst")))
