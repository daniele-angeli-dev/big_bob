"""Voce: legge la mossa ad alta voce con la sintesi vocale di Windows (nessuna installazione).

Un processo PowerShell resta acceso e legge una riga alla volta; una nuova frase interrompe la precedente.
Su sistemi diversi da Windows non fa nulla.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading

log = logging.getLogger("bigbob")

PS_SCRIPT = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$it = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'it*' } | Select-Object -First 1
if ($it) { $s.SelectVoice($it.VoiceInfo.Name) }
$s.Rate = 2
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  $s.SpeakAsyncCancelAll()
  if ($line.Trim().Length -gt 0) { $s.SpeakAsync($line) | Out-Null }
}
"""


def clean(text: str) -> str:
    """Toglie ciò che suona male letto ad alta voce (parentesi, simboli, numeri tipo 3/4)."""
    t = re.sub(r"\([^)]*\)", "", text)
    t = re.sub(r"\b(\d+)/(\d+)\b", r"\1 su \2", t)
    t = t.replace("→", " a ").replace("·", ",").replace("≤", "al massimo ").replace("%", " per cento")
    t = re.sub(r"[*_`#>]", "", t)
    return re.sub(r"\s+", " ", t).strip(" ,.")


class Voice:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return sys.platform == "win32"

    def _ensure(self) -> bool:
        if not self.available():
            return False
        if self.proc is not None and self.proc.poll() is None:
            return True
        try:
            self.proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except Exception:  # noqa: BLE001
            log.exception("voce non disponibile")
            self.proc = None
            return False

    def warm(self) -> None:
        threading.Thread(target=lambda: self._ensure(), daemon=True).start()

    def say(self, text: str) -> None:
        text = clean(text)
        if not text:
            return
        with self._lock:
            if not self._ensure():
                return
            try:
                self.proc.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except Exception:  # noqa: BLE001
                log.exception("voce: invio fallito")
                self.proc = None

    def stop(self) -> None:
        with self._lock:
            if self.proc is not None:
                try:
                    self.proc.stdin.close()
                    self.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                self.proc = None
