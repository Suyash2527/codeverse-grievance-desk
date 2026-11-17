# -*- coding: utf-8 -*-
"""
Record the CodeVerse demo video, narrated with Sarvam text-to-speech.

    set SARVAM_API_KEY=...            (never written to any file)
    python scripts/demo/make_video.py              # full run
    python scripts/demo/make_video.py --dry-run    # no key: silent, estimated timing,
                                                   # and the grievance is NOT filed

Needs the app running: frontend on :3000, backend on :8000.

How it stays in sync: every scene's narration is generated first, and its
length becomes that scene's time budget. Each scene is then recorded on its
own, waits out whatever is left of its budget, and is muxed with its own
audio. Scenes are joined at the end. Nothing has to be lined up by hand.

A full run files ONE real grievance (the exposed-wire case), because the
point of the demo is to show a dangerous complaint being held for a human.
A dry run stops at the draft and files nothing.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "docs" / "demo" / "build"
OUT = ROOT / "docs" / "demo" / "CodeVerse_demo.mp4"
BASE = "http://localhost:3000"
API = "http://127.0.0.1:8000"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
VOICE = os.environ.get("SARVAM_SPEAKER", "shubh_en_narration")
MODEL = os.environ.get("SARVAM_MODEL", "bulbul:v3")
SAMPLE_RATE = 24000

CREAM = "0xFFF8DC"
INK = "0x111010"
RED = "0xD22B2B"
FONT_BOLD = "C\\:/Windows/Fonts/arialbd.ttf"
FONT = "C\\:/Windows/Fonts/arial.ttf"

COMPLAINT = (
    "There is an exposed electric wire hanging near the primary school in Loha, "
    "it is dangerous for the children."
)

# ------------------------------------------------------------- the story --
NARRATION = {
    "home": (
        "This is the Grievance Desk, built by team CodeVerse for HackFusion 4.0. "
        "It is an agentic AI system for a district administration. Every rule it "
        "follows, the categories, the deadlines, the departments, is read from the "
        "district's own CSV sheets. Nothing is hard-coded."
    ),
    "citizen": (
        "A citizen opens it on their phone, in Marathi, Hindi or English. "
        "Here, they report an exposed electric wire near a school. The AI drafts "
        "the complaint, but nothing is filed until the citizen confirms it. "
        "They get a reference number straight away."
    ),
    "channels": (
        "Not every citizen will use a website. As our MVP, the same agent is "
        "reachable on WhatsApp and through a phone helpline. On WhatsApp, the "
        "complaint arrives as a chat and the draft comes back to confirm. On a "
        "call, the caller hears the draft read back and presses one to file. "
        "Both follow exactly the same rules."
    ),
    "queue": (
        "On the officer's side, the queue is ordered by severity, urgency and the "
        "number of people affected, never by how many times something was reported. "
        "The new case is marked sensitive."
    ),
    "case": (
        "Opening it shows why. The category sheet marks electrical hazards as "
        "sensitive, so the AI is not allowed to close this case, whatever its "
        "confidence. The citizen's identity is withheld from the department. And "
        "every decision records its confidence, the exact rule that applied, and "
        "the past cases it looked at."
    ),
    "hotspots": (
        "For the district, a heat map shows where grievances come from, at taluka "
        "level only, so no individual can be identified. The ranked list shows "
        "which talukas need attention first."
    ),
    "rules": (
        "These safety rules are not promises written into a prompt. This page runs "
        "each rule live against the real code. Nine out of nine hold."
    ),
    "track": (
        "Finally, the citizen tracks the case with their reference number and sees "
        "every step. If they are not satisfied, they can reopen it."
    ),
    "close": (
        "That is the CodeVerse Grievance Desk. Quick with routine cases, careful "
        "with dangerous ones, and accountable at every step. Thank you."
    ),
}

CAPTIONS = {
    "home": "Policy from CSV, not code",
    "citizen": "Citizen files on a phone",
    "channels": "MVP: WhatsApp and phone helpline",
    "queue": "Officer queue",
    "case": "Why the system decided this",
    "hotspots": "District hotspots",
    "rules": "Safety rules, checked live",
    "track": "Citizen tracks the case",
    "close": "CodeVerse · HackFusion 4.0",
}

PHONE_SCENES = {"citizen", "track"}

OVERLAY_JS = r"""
(() => {
  const css = `nextjs-portal,[data-nextjs-toast],[data-next-badge-root]{display:none!important}
  #__demo_cursor{position:fixed;z-index:2147483647;width:28px;height:28px;margin:-14px 0 0 -14px;
    border-radius:50%;background:rgba(210,43,43,.22);border:3px solid #d22b2b;pointer-events:none;
    left:-100px;top:-100px;transition:transform .12s ease,background .12s ease}
  #__demo_cursor.down{transform:scale(.7);background:rgba(210,43,43,.55)}`;
  const add = () => {
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    const c = document.createElement('div'); c.id = '__demo_cursor'; document.body.appendChild(c);
    const at = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
    addEventListener('mousemove', e => at(e.clientX, e.clientY), true);
    addEventListener('mousedown', () => c.classList.add('down'), true);
    addEventListener('mouseup', () => c.classList.remove('down'), true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', add); else add();
})();
"""


# ---------------------------------------------------------------- audio --
def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def silent_wav(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * int(seconds * SAMPLE_RATE))


def sarvam_tts(text: str, out: Path, key: str) -> None:
    body = json.dumps({
        "text": text,
        "language_code": "en-IN",
        "model": MODEL,
        "speaker": VOICE,
        "pace": 1.0,
        "speech_sample_rate": SAMPLE_RATE,
        "output_audio_codec": "wav",
    }).encode()
    req = urllib.request.Request(
        SARVAM_URL, data=body, method="POST",
        headers={"api-subscription-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:400]
        sys.exit(f"Sarvam rejected the request ({err.code}): {detail}")
    out.write_bytes(base64.b64decode(payload["audios"][0]))


def narration(dry_run: bool) -> dict[str, tuple[Path, float]]:
    audio_dir = BUILD / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not dry_run and not key:
        sys.exit("SARVAM_API_KEY is not set. Set it in this terminal, or use --dry-run.")
    result = {}
    for scene, text in NARRATION.items():
        tag = "dry" if dry_run else f"{MODEL}-{VOICE}"
        digest = hashlib.sha1(f"{tag}|{text}".encode()).hexdigest()[:12]
        path = audio_dir / f"{scene}-{digest}.wav"
        if not path.exists():
            if dry_run:
                silent_wav(path, len(text.split()) / 2.6)   # ~156 wpm
            else:
                print(f"  tts: {scene}")
                sarvam_tts(text, path, key)
        result[scene] = (path, wav_seconds(path))
    total = sum(d for _, d in result.values())
    print(f"narration: {total:.1f}s across {len(result)} scenes")
    return result


# ------------------------------------------------------------ recording --
@dataclass
class Take:
    scene: str
    video: Path
    trim: float
    length: float


@dataclass
class Director:
    page: object
    t0: float
    ready: float = 0.0
    x: float = 0
    y: float = 0

    def glide(self, x, y, steps=22):
        self.page.mouse.move(x, y, steps=steps)
        self.x, self.y = x, y

    def click(self, locator, pause=250, center=True):
        # Centre the target first. "Just into view" leaves it under the phone
        # layout's fixed bottom tab bar, and the tap would land on a tab.
        # Pass center=False when the scene has already framed the shot.
        locator.wait_for(state="visible", timeout=30000)
        if center:
            locator.evaluate("e => e.scrollIntoView({block: 'center', inline: 'center'})")
            self.page.wait_for_timeout(350)
        box = locator.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.glide(cx, cy)
        self.page.wait_for_timeout(pause)
        self.page.mouse.down()
        self.page.wait_for_timeout(90)
        self.page.mouse.up()

    def scroll(self, dy, steps=12, each=55):
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(each)

    def pause(self, ms):
        self.page.wait_for_timeout(ms)


def record(scene: str, budget: float, browser, pw, action, *, url: str) -> Take:
    phone = scene in PHONE_SCENES
    vdir = BUILD / "video" / scene
    vdir.mkdir(parents=True, exist_ok=True)
    for old in vdir.glob("*.webm"):
        old.unlink()

    # Record at exactly the viewport size. Playwright scales a recording DOWN
    # to fit record_video_size but never up: a larger size only pads the
    # picture into the top-left corner. Upscaling happens later, in ffmpeg.
    if phone:
        dev = dict(pw.devices["iPhone 13"])
        ctx = browser.new_context(**dev, record_video_dir=str(vdir),
                                  record_video_size=dict(dev["viewport"]))
    else:
        view = {"width": 1600, "height": 900}
        ctx = browser.new_context(viewport=view, record_video_dir=str(vdir),
                                  record_video_size=view)
    ctx.add_init_script(OVERLAY_JS)
    t0 = time.monotonic()
    page = ctx.new_page()
    page.goto(url, wait_until="networkidle")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(500)
    d = Director(page, t0)
    d.ready = time.monotonic()
    d.glide(page.viewport_size["width"] * 0.55, page.viewport_size["height"] * 0.45, steps=1)

    action(d)

    # hold until the narration (plus a breath) has been spoken
    elapsed = time.monotonic() - d.ready
    remaining = budget + 0.9 - elapsed
    if remaining > 0:
        page.wait_for_timeout(int(remaining * 1000))
    length = time.monotonic() - d.ready
    video = Path(page.video.path())
    ctx.close()
    print(f"  {scene:9s} {length:5.1f}s (narration {budget:4.1f}s)"
          + ("  <- actions ran longer than the narration" if elapsed > budget + 0.5 else ""))
    return Take(scene, video, d.ready - t0, length)


@dataclass
class State:
    dry_run: bool
    reference: str = ""
    seen: dict = field(default_factory=dict)


def scenes(state: State):
    """(scene, url, action) - urls are lambdas when they depend on earlier scenes."""

    def home(d: Director):
        d.pause(1200)
        d.scroll(700, steps=16, each=70)
        d.pause(1600)
        d.scroll(700, steps=16, each=70)
        d.pause(1800)
        d.scroll(-1400, steps=14, each=50)

    def citizen(d: Director):
        p = d.page
        d.pause(900)
        d.click(p.get_by_role("button", name="मराठी").first)
        d.pause(1800)
        d.click(p.get_by_role("button", name="English").first)
        d.pause(700)
        box = p.get_by_placeholder("Describe the problem")
        d.click(box)
        box.press_sequentially(COMPLAINT, delay=28)
        d.pause(400)
        d.click(p.get_by_role("button", name="Send"))
        p.get_by_text("Draft for your confirmation").wait_for(timeout=30000)
        d.pause(500)
        p.get_by_text("Draft for your confirmation").scroll_into_view_if_needed()
        d.pause(1500)
        name = p.locator("input").first
        d.click(name)
        name.press_sequentially("Demo Citizen", delay=40)
        confirm = p.get_by_role("button", name="Yes, file this grievance")
        confirm.evaluate("e => e.scrollIntoView({block: 'center'})")
        d.pause(600)
        if state.dry_run:
            d.glide(*_center(confirm))
            d.pause(800)
            state.reference = _first_reference()
        else:
            d.click(confirm)
            ref = p.locator(".ref").filter(has_text="GRV-").last
            ref.wait_for(timeout=30000)
            state.reference = ref.inner_text().strip()
            ref.scroll_into_view_if_needed()
            d.pause(1200)
        print(f"    reference used from here on: {state.reference}")

    def channels(d: Director):
        p = d.page
        d.pause(900)
        # bring both phones fully into view
        # frame both phones whole, just below the sticky header, and keep them
        # framed: the Play buttons sit inside the shot already
        p.evaluate(
            """() => {
              const f = document.querySelector('figure');
              if (f) window.scrollTo({top: f.getBoundingClientRect().top + scrollY - 92, behavior: 'smooth'});
            }"""
        )
        d.pause(1300)
        d.click(p.get_by_role("button", name="Play").first, center=False)
        d.pause(700)
        d.click(p.get_by_role("button", name="Call").first, center=False)

    def queue(d: Director):
        p = d.page
        d.pause(1500)
        d.click(p.get_by_role("button", name="Sensitive").first)
        d.pause(1800)
        card = p.get_by_text(state.reference).first
        if card.count():
            d.glide(*_center(card))
        d.pause(1200)

    def case(d: Director):
        d.pause(2500)
        d.scroll(500, steps=12, each=70)
        d.pause(2500)
        d.scroll(650, steps=14, each=70)
        d.pause(2500)
        d.scroll(650, steps=14, each=70)

    def hotspots(d: Director):
        p = d.page
        d.pause(800)
        d.scroll(420, steps=10, each=60)
        d.pause(4200)
        d.click(p.get_by_role("button", name="Ranked list"))
        d.pause(900)
        d.scroll(250, steps=8, each=60)

    def rules(d: Director):
        p = d.page
        d.pause(1200)
        d.click(p.get_by_role("button", name="Run the checks again"))
        d.pause(2400)
        d.scroll(600, steps=14, each=70)
        d.pause(1500)
        d.scroll(600, steps=14, each=70)

    def track(d: Director):
        d.pause(2200)
        d.scroll(500, steps=12, each=70)
        d.pause(1800)
        d.scroll(500, steps=12, each=70)

    def close(d: Director):
        d.pause(500)

    return [
        ("home", lambda: f"{BASE}/", home),
        ("citizen", lambda: f"{BASE}/citizen", citizen),
        ("channels", lambda: f"{BASE}/channels", channels),
        ("queue", lambda: f"{BASE}/officer", queue),
        ("case", lambda: f"{BASE}/officer/{state.reference}", case),
        ("hotspots", lambda: f"{BASE}/officer/hotspots", hotspots),
        ("rules", lambda: f"{BASE}/compliance", rules),
        ("track", lambda: f"{BASE}/track?ref={state.reference}", track),
        ("close", lambda: f"{BASE}/", close),
    ]


def _center(locator):
    b = locator.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _first_reference() -> str:
    with urllib.request.urlopen(f"{API}/api/officer/queue?limit=1", timeout=10) as r:
        return json.load(r)["rows"][0]["reference_no"]


# ------------------------------------------------------------- assembly --
def ff(*args):
    run = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
                         capture_output=True, text=True)
    if run.returncode:
        sys.exit(f"ffmpeg failed:\n{run.stderr[-1500:]}")


def caption_file(scene: str) -> str:
    path = BUILD / "captions" / f"{scene}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CAPTIONS[scene], encoding="utf-8")
    return str(path).replace("\\", "/").replace(":", "\\:")


def segment(take: Take, audio: Path, index: int) -> Path:
    out = BUILD / "segments" / f"{index:02d}_{take.scene}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = caption_file(take.scene)
    if take.scene in PHONE_SCENES:
        video = (
            # 780x1688 phone capture -> 444x960, framed with a 4px ink border
            f"[0:v]fps=30,scale=444:960,"
            f"pad=1920:1080:1080:60:color={CREAM},"
            f"drawbox=x=1076:y=56:w=452:h=968:color={INK}:t=4,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{cap}':fontsize=64:fontcolor={INK}:x=150:y=430,"
            f"drawtext=fontfile='{FONT}':text='Mobile-first citizen view':fontsize=34:"
            f"fontcolor={RED}:x=150:y=520[v]"
        )
    else:
        video = (
            f"[0:v]fps=30,scale=1920:1080,"
            f"drawtext=fontfile='{FONT_BOLD}':textfile='{cap}':fontsize=30:fontcolor=white:"
            f"box=1:boxcolor={INK}@0.88:boxborderw=18:x=48:y=h-th-60[v]"
        )
    graph = BUILD / "segments" / f"{index:02d}.filter"
    # The screencast only emits frames when the page changes, so a quiet
    # scene can be shorter than its narration: hold the last frame to cover it.
    video = video.replace("[0:v]fps=30,", "[0:v]tpad=stop_mode=clone:stop_duration=8,fps=30,", 1)
    graph.write_text(f"{video};[1:a]adelay=350|350,apad[a]", encoding="utf-8")
    ff("-ss", f"{take.trim:.3f}", "-i", str(take.video), "-i", str(audio),
       "-filter_complex_script", str(graph), "-map", "[v]", "-map", "[a]",
       "-t", f"{take.length:.3f}",
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(out))
    return out


def title_card() -> Path:
    out = BUILD / "segments" / "00_title.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    graph = BUILD / "segments" / "00.filter"
    graph.write_text(
        f"color=c={CREAM}:s=1920x1080:d=3.2:r=30,"
        f"drawtext=fontfile='{FONT_BOLD}':text='Agentic AI Grievance Desk':fontsize=92:"
        f"fontcolor={INK}:x=(w-tw)/2:y=(h/2)-110,"
        f"drawtext=fontfile='{FONT}':text='Team CodeVerse  ·  HackFusion 4.0':fontsize=44:"
        f"fontcolor={RED}:x=(w-tw)/2:y=(h/2)+20,"
        f"fade=t=out:st=2.7:d=0.5[v];"
        f"anullsrc=r=48000:cl=stereo,atrim=0:3.2[a]",
        encoding="utf-8",
    )
    ff("-filter_complex_script", str(graph), "-map", "[v]", "-map", "[a]",
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(out))
    return out


def join(parts: list[Path], out: Path) -> None:
    listing = BUILD / "segments" / "list.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    ff("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out))


# ----------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="silent audio, estimated timing, and no grievance is filed")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)
    audio = narration(args.dry_run)
    state = State(dry_run=args.dry_run)

    takes: list[Take] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scene, url, action in scenes(state):
            takes.append(record(scene, audio[scene][1], browser, pw, action, url=url()))
        browser.close()

    print("assembling")
    parts = [title_card()]
    for i, take in enumerate(takes, start=1):
        parts.append(segment(take, audio[take.scene][0], i))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    join(parts, out)
    total = 3.2 + sum(t.length for t in takes)
    print(f"saved {out}  ({total:.0f}s, {out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
