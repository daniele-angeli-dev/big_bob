"""Imposta il collegamento a Claude e il modello senza toccare il resto della configurazione.

python configura.py --modello sonnet --connessione abbonamento
python configura.py --connessione api --api-key sk-ant-...
python configura.py --mostra
Lo usano l'installer e la finestra Impostazioni.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from origins import store  # noqa: E402

MODELLI = {"sonnet": "Sonnet: veloce, consigliato per il live", "opus": "Opus: più preciso, più lento",
           "haiku": "Haiku: velocissimo, meno preciso"}
CONNESSIONI = {"abbonamento": "Abbonamento Claude (Claude Code con il tuo account)",
               "api": "Chiave API Anthropic (pagamento a consumo)"}


def apply(modello: str | None = None, connessione: str | None = None, api_key: str | None = None,
          **extra) -> dict:
    cfg = store.load("config")
    if modello:
        if modello not in MODELLI:
            raise ValueError(f"modello deve essere uno di {list(MODELLI)}")
        cfg["modello_live"] = modello
    if connessione:
        if connessione not in CONNESSIONI:
            raise ValueError(f"connessione deve essere una di {list(CONNESSIONI)}")
        cfg["connessione"] = connessione
    if api_key is not None:
        cfg["api_key"] = api_key.strip()
    for k, v in extra.items():
        if v is not None:
            cfg[k] = v
    store.save("config", cfg)
    return cfg


def claude_candidates() -> list[Path]:
    """Dove finisce Claude Code installato con l'installer ufficiale, winget o npm (anche se il PATH non è aggiornato)."""
    import os
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    return [home / ".local" / "bin" / "claude.exe", local / "Microsoft" / "WinGet" / "Links" / "claude.exe",
            roaming / "npm" / "claude.cmd", home / ".local" / "bin" / "claude"]


def find_claude() -> str | None:
    import shutil
    found = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if found:
        return found
    return next((str(p) for p in claude_candidates() if p.is_file()), None)


def install_claude(log=print) -> str | None:
    """Installa Claude Code (installer ufficiale; se non va, winget). Restituisce il percorso di claude o None."""
    import os
    import shutil
    import subprocess
    if find_claude():
        return find_claude()
    if os.name != "nt":
        log("Installazione automatica di Claude Code disponibile solo su Windows.")
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ps = shutil.which("powershell") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                                    "WindowsPowerShell", "v1.0", "powershell.exe")
    attempts = [("installer ufficiale", [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                         "irm https://claude.ai/install.ps1 | iex"])]
    if shutil.which("winget"):
        attempts.append(("winget", ["winget", "install", "-e", "--id", "Anthropic.ClaudeCode", "--silent",
                                    "--accept-package-agreements", "--accept-source-agreements"]))
    for name, cmd in attempts:
        log(f"Installo Claude Code ({name})…")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                               creationflags=flags)
            if r.returncode != 0:
                log(f"{name}: codice {r.returncode} {(r.stderr or r.stdout or '').strip()[-300:]}")
        except Exception as e:  # noqa: BLE001
            log(f"{name}: {e}")
        exe = find_claude()
        if exe:
            log(f"Claude Code installato: {exe}")
            return exe
    return None


def claude_env(cfg: dict | None = None) -> dict:
    """Ambiente per Claude Code secondo il collegamento scelto (abbonamento o chiave API)."""
    import os
    cfg = cfg or store.load("config")
    env = dict(os.environ)
    if cfg.get("connessione") == "api" and cfg.get("api_key"):
        env["ANTHROPIC_API_KEY"] = cfg["api_key"]
    else:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def test_claude(timeout: int = 90) -> tuple[bool, str]:
    """Chiede a Claude di rispondere 'OK' con il collegamento e il modello scelti."""
    import subprocess
    import time
    exe = find_claude()
    if not exe:
        return False, "Claude Code non è installato."
    cfg = store.load("config")
    root = Path(__file__).resolve().parent
    t0 = time.time()
    try:
        r = subprocess.run([exe, "-p", "Rispondi solo con la parola OK.", "--output-format", "json",
                            "--model", cfg.get("modello_live", "sonnet")], cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=claude_env(cfg),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, f"Nessuna risposta in {timeout} secondi: probabilmente serve l'accesso (Accedi a Claude)."
    except Exception as e:  # noqa: BLE001
        return False, f"Prova non riuscita: {e}"
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}
    ok = r.returncode == 0 and not data.get("is_error") and "OK" in (data.get("result") or "").upper()
    how = "chiave API" if cfg.get("connessione") == "api" and cfg.get("api_key") else "abbonamento"
    if ok:
        return True, f"Collegato a Claude ({how}, modello {cfg.get('modello_live', 'sonnet')}) in {time.time() - t0:.0f} s"
    detail = (data.get("result") or r.stderr or r.stdout or "").strip()[-300:] or f"codice {r.returncode}"
    return False, "Non collegato: " + detail


def public(cfg: dict) -> dict:
    """Configurazione senza la chiave API in chiaro."""
    out = dict(cfg)
    if out.get("api_key"):
        k = out["api_key"]
        out["api_key"] = k[:7] + "…" + k[-4:] if len(k) > 12 else "impostata"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modello", choices=list(MODELLI))
    ap.add_argument("--connessione", choices=list(CONNESSIONI))
    ap.add_argument("--api-key")
    ap.add_argument("--mostra", action="store_true")
    ap.add_argument("--riassunto", action="store_true", help="modello|connessione|si/no chiave (per l'installer)")
    ap.add_argument("--prova", action="store_true", help="prova il collegamento a Claude")
    ap.add_argument("--trova-claude", action="store_true", help="stampa il percorso di claude (codice 1 se manca)")
    ap.add_argument("--installa-claude", action="store_true", help="installa Claude Code se manca")
    a = ap.parse_args()
    if a.trova_claude or a.installa_claude:
        exe = install_claude() if a.installa_claude else find_claude()
        print(exe or "Claude Code non trovato")
        sys.exit(0 if exe else 1)
    if a.riassunto:
        c = store.load("config")
        print(f"{c.get('modello_live', 'sonnet')}|{c.get('connessione') or 'abbonamento'}|"
              f"{'si' if c.get('api_key') else 'no'}")
        sys.exit(0)
    if a.modello or a.connessione or a.api_key is not None:
        apply(a.modello, a.connessione, a.api_key)
    if a.prova:
        ok, msg = test_claude()
        print(msg)
        sys.exit(0 if ok else 1)
    print(json.dumps(public(store.load("config")), ensure_ascii=False, indent=2))
