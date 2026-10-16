"""Prepara un video di YouTube per lo studio: sottotitoli + fotogrammi ai cambi di scena.

Uso (lo lancia Claude Code con /impara-video):
    python origins/video.py "https://www.youtube.com/watch?v=..." [--max-fotogrammi 100]

Risultato in captures/video/<id>/: info.json, trascrizione.txt, fotogrammi/NNNN_tMMmSSs.png
Il video scaricato viene cancellato alla fine: restano solo testo e fotogrammi.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = ROOT / "captures" / "video"


def fmt_t(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def vtt_to_text(vtt: str, group_seconds: int = 15) -> str:
    """Converte un .vtt (anche sottotitoli automatici, che ripetono le righe) in testo con orari."""
    cues: list[tuple[int, list[str]]] = []
    for line in vtt.splitlines():
        m = re.match(r"(?:(\d+):)?(\d\d):(\d\d)[.,]\d+\s+-->", line)
        if m:
            h, mi, se = (int(x) if x else 0 for x in m.groups())
            cues.append((h * 3600 + mi * 60 + se, []))
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or not cues or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        cues[-1][1].append(line)
    # i sottotitoli automatici ripetono la riga precedente in ogni blocco: emetti ogni riga una volta
    emitted: list[tuple[int, str]] = []
    recent: list[str] = []
    for t, lines in cues:
        for ln in lines:
            if ln in recent:
                continue
            emitted.append((t, ln))
            recent = (recent + [ln])[-4:]
    out, block_t, block = [], None, []
    for t, text in emitted:
        if block_t is None:
            block_t = t
        if t - block_t >= group_seconds and block:
            out.append(f"[{fmt_t(block_t)}] {' '.join(block)}")
            block_t, block = t, []
        block.append(text)
    if block:
        out.append(f"[{fmt_t(block_t)}] {' '.join(block)}")
    return "\n".join(out)


def extract_frames(video: Path, out: Path, max_frames: int) -> list[str]:
    from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)
    cmd = [ffmpeg, "-hide_banner", "-i", str(video),
           "-vf", "select='gt(scene,0.22)+eq(n,0)',showinfo,scale='min(1280,iw)':-2",
           "-vsync", "vfr", str(tmp / "%05d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    files = sorted(tmp.glob("*.png"))
    if len(files) < 8:  # pochi cambi di scena (es. una partita lunga e statica): uno ogni 10 secondi
        for f in files:
            f.unlink()
        cmd = [ffmpeg, "-hide_banner", "-i", str(video), "-vf", "fps=1/10,showinfo,scale='min(1280,iw)':-2",
               str(tmp / "%05d.png")]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
        files = sorted(tmp.glob("*.png"))
    if len(times) != len(files):
        times = [i * 10.0 for i in range(len(files))]
    keep = list(range(len(files)))
    if len(files) > max_frames:  # campiona in modo uniforme
        step = len(files) / max_frames
        keep = sorted({int(i * step) for i in range(max_frames)})
    names = []
    for n, i in enumerate(keep, 1):
        t = int(times[i])
        name = f"{n:04d}_t{t // 60:02d}m{t % 60:02d}s.png"
        files[i].rename(out / name)
        names.append(name)
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()
    return names


def prepare(url: str, max_frames: int = 80, solo_testo: bool = False) -> dict:
    import yt_dlp

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    vid = info["id"]
    d = VIDEO_DIR / vid
    d.mkdir(parents=True, exist_ok=True)

    # Scegli UNA traccia di sottotitoli: manuali it/en, poi automatici nella lingua originale.
    # Le traduzioni automatiche (es. it tradotto da en) fanno scattare l'errore 429 di YouTube.
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    lang0 = (info.get("language") or "en").split("-")[0]
    choice = None
    for lang in ("it", "en", lang0):
        if lang in manual:
            choice = (lang, False)
            break
    if choice is None:
        for lang in (f"{lang0}-orig", lang0, "en-orig", "en"):
            if lang in auto:
                choice = (lang, True)
                break

    base = {"quiet": True, "no_warnings": True, "outtmpl": str(d / "video.%(ext)s")}
    if choice:
        try:
            with yt_dlp.YoutubeDL({**base, "skip_download": True, "writesubtitles": not choice[1],
                                   "writeautomaticsub": choice[1], "subtitleslangs": [choice[0]],
                                   "subtitlesformat": "vtt"}) as ydl:
                ydl.download([url])
        except Exception as e:  # noqa: BLE001  senza sottotitoli si va avanti con le sole immagini
            print(f"Sottotitoli non scaricati ({e}): continuo senza", file=sys.stderr)
    if not solo_testo:
        with yt_dlp.YoutubeDL({**base, "format": "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]/b"}) as ydl:
            ydl.download([url])

    subs = sorted(d.glob("*.vtt"), key=lambda p: (".it" not in p.name, ".en" not in p.name))
    transcript = vtt_to_text(subs[0].read_text(encoding="utf-8", errors="replace")) if subs else ""
    (d / "trascrizione.txt").write_text(transcript or "(nessun sottotitolo disponibile)", encoding="utf-8")
    for s in subs:
        s.unlink()

    frames: list[str] = []
    videos = [p for p in d.glob("video.*") if p.suffix not in (".vtt", ".json", ".part")]
    if videos and not solo_testo:
        frames = extract_frames(videos[0], d / "fotogrammi", max_frames)
        for v in videos:
            v.unlink()

    meta = {"id": vid, "titolo": info.get("title"), "canale": info.get("channel") or info.get("uploader"),
            "data_pubblicazione": info.get("upload_date"), "durata": fmt_t(info.get("duration") or 0),
            "url": url, "cartella": str(d), "trascrizione": str(d / "trascrizione.txt"),
            "righe_trascrizione": len(transcript.splitlines()), "fotogrammi": len(frames),
            "cartella_fotogrammi": str(d / "fotogrammi")}
    (d / "info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-fotogrammi", type=int, default=80)
    ap.add_argument("--solo-testo", action="store_true")
    a = ap.parse_args()
    try:
        print(json.dumps(prepare(a.url, a.max_fotogrammi, a.solo_testo), ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(1)
