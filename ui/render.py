"""Prepara la pagina della finestra: incorpora i font (ui/fonts) così funziona anche offline."""
import base64
from pathlib import Path

UI = Path(__file__).resolve().parent
FACES = [("Anton", 400, "anton-latin-400-normal.woff2")] + [
    ("Barlow Semi Condensed", w, f"barlow-semi-condensed-latin-{w}-normal.woff2") for w in (500, 600, 700)]


def page() -> str:
    html = (UI / "arena.html").read_text(encoding="utf-8")
    rules = []
    for family, weight, fname in FACES:
        f = UI / "fonts" / fname
        if f.exists():
            data = base64.b64encode(f.read_bytes()).decode()
            rules.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
                         f"font-display:block;src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return html.replace("/*FONTS*/", "\n".join(rules), 1)
