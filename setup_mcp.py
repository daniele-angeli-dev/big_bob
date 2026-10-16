"""Scrive .mcp.json con i percorsi assoluti di questo PC (lo lancia installa.bat)."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
cfg = {"mcpServers": {"origins": {"command": sys.executable,
                                  "args": [str(root / "origins" / "server.py")]}}}
(root / ".mcp.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
conf = root / "config.json"
if not conf.exists():
    sys.path.insert(0, str(root))
    from origins import store
    store.save("config", store.DEFAULTS["config"])
print("Configurazione MCP scritta in", root / ".mcp.json")
