# -*- coding: utf-8 -*-
"""
Build the CodeVerse HackFusion 4.0 idea deck from the official template.

    python scripts/demo/build_deck.py  [--out PATH]

Starts from the untouched template every time, so it is safe to re-run after
re-capturing screenshots.

What is kept exactly as the organisers wrote it:
  - every slide heading, logo, character, footer and colour;
  - every pointer line ("Detailed explanation of the proposed solution", ...),
    word for word; the template's slide 7 forbids changing them.

What changes:
  - the pointer lines are restyled as section labels in the template's own
    footer purple, and our content sits under each one as points;
  - screenshots of the running system fill the right-hand column;
  - slide 3 gets a native flowchart, since its pointer asks for one;
  - the instructions slide (7) is removed, which the template itself permits
    and its six-slide limit requires.
"""
from __future__ import annotations

import argparse
import copy
import sys
import io
from pathlib import Path

from PIL import Image, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(r"C:\Users\Predator\Downloads\Hackfusion4_ppt.pptx")
SHOTS = ROOT / "docs" / "screenshots"
DEFAULT_OUT = ROOT / "CodeVerse_HackFusion4_Idea_v2.pptx"

TEAM = "CodeVerse"
FONT = "Arial"
PURPLE = RGBColor(0x47, 0x15, 0x64)  # sampled from the template's footer band
INK = RGBColor(0x1E, 0x1E, 0x1E)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
TINT = RGBColor(0xF3, 0xEE, 0xF7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# Content-area geometry, in inches, on the template's 20 x 11.25 canvas.
LEFT_X, LEFT_W = 0.75, 9.6
RIGHT_X, RIGHT_R = 11.0, 17.3  # the corner characters start at about 17.6
TOP = 2.0

LABEL_PT, SUB_PT, BODY_PT = 27, 23, 22

CROPS = SHOTS / "crops"


def crop(name: str, x0: float, x1: float, y0: int, aspect: float) -> str:
    """
    Cut the useful region out of a screenshot: x0/x1 are fractions of the
    width (the app centres its content, so the sides are empty margin), y0 is
    a pixel row, and the height follows from the aspect the slide needs.
    """
    CROPS.mkdir(parents=True, exist_ok=True)
    with Image.open(SHOTS / name) as im:
        left, right = int(x0 * im.width), int(x1 * im.width)
        height = int((right - left) / aspect)
        bottom = min(im.height, y0 + height)
        out = CROPS / f"{Path(name).stem}__{int(x0*100)}_{int(x1*100)}_{y0}.png"
        im.crop((left, y0, right, bottom)).save(out)
    return str(out.relative_to(SHOTS))

ARIAL = r"C:\Windows\Fonts\arial.ttf"
ARIAL_BOLD = r"C:\Windows\Fonts\arialbd.ttf"


# ------------------------------------------------------------------ fitting --
def text_lines(text: str, size_pt: float, width_in: float, bold: bool) -> int:
    """Real word-wrap with Arial's actual glyph widths, not an estimate."""
    font = ImageFont.truetype(ARIAL_BOLD if bold else ARIAL, int(size_pt * 10))
    limit = width_in * 72 * 10
    lines, current = 1, ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if font.getlength(trial) <= limit:
            current = trial
        else:
            lines += 1
            current = word
    return lines


# ------------------------------------------------------------- primitives --
def walk(shapes):
    for sh in shapes:
        yield sh
        if sh.shape_type == 6:
            yield from walk(sh.shapes)


def find(slide, shape_id):
    for sh in walk(slide.shapes):
        if sh.shape_id == shape_id:
            return sh
    raise LookupError(shape_id)


def style_run(run, size, *, bold=False, color=INK, italic=False):
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.underline = False
    f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs", "a:sym"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", FONT)


def set_bullet(paragraph, char: str | None, indent_in=0.32, level_in=0.0):
    pPr = paragraph._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buFont", "a:buClr"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    if char is None:
        pPr.set("marL", str(int(Inches(level_in))))
        pPr.set("indent", "0")
        pPr.append(pPr.makeelement(qn("a:buNone"), {}))
        return
    pPr.set("marL", str(int(Inches(level_in + indent_in))))
    pPr.set("indent", str(-int(Inches(indent_in))))
    clr = pPr.makeelement(qn("a:buClr"), {})
    srgb = clr.makeelement(qn("a:srgbClr"), {"val": "471564"})
    clr.append(srgb)
    pPr.append(clr)
    pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": FONT}))
    pPr.append(pPr.makeelement(qn("a:buChar"), {"char": char}))


def add_par(tf, text, size, *, bold=False, color=INK, bullet=None,
            before=0, after=4, first=False, level_in=0.0, align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.line_spacing = 1.08
    p.space_before = Pt(before)
    p.space_after = Pt(after)
    set_bullet(p, bullet, level_in=level_in)
    r = p.add_run()
    r.text = text
    style_run(r, size, bold=bold, color=color)
    return p


def frame(tf):
    tf.clear()
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = MSO_ANCHOR.TOP


def picture(slide, name, x, y, *, w=None, h=None, border=True):
    path = SHOTS / name
    if not path.exists():
        raise FileNotFoundError(f"missing screenshot {path} - run capture_screens.py")
    with Image.open(path) as im:
        ratio = im.width / im.height
    if w is None:
        w = h * ratio
    if h is None:
        h = w / ratio
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    if border:
        pic.line.color.rgb = INK
        pic.line.width = Pt(1.75)
    return pic, w, h


def caption(slide, text, x, y, w, size=15):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.45))
    tf = tb.text_frame
    frame(tf)
    # upright: PowerPoint's export mis-kerns italic Arial ("aw aiting")
    add_par(tf, text, size, color=MUTED, first=True, after=0)
    return tb


def box(slide, x, y, w, h, *, fill=WHITE, line=PURPLE, line_pt=2.0,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_pt)
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.12
    tf = s.text_frame
    frame(tf)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.1)
    return s


# --------------------------------------------------- the pointer layouts --
def pointer_column(shape, sections, *, width, heading=None, check=True, slide_no=0,
                   height=None):
    """
    Rebuild a template pointer box as labelled sections.
    `sections` is [(pointer_text_verbatim, [points...]), ...].
    """
    shape.left, shape.top = Inches(LEFT_X), Inches(TOP)
    shape.width = Inches(width)
    tf = shape.text_frame
    frame(tf)

    first = True
    used = 0.0
    if heading:
        add_par(tf, heading, LABEL_PT, bold=True, color=PURPLE, first=True, after=10)
        used += text_lines(heading, LABEL_PT, width - 0.1, True) * LABEL_PT * 1.17 + 10
        first = False

    label_size = SUB_PT if heading else LABEL_PT
    for pointer, points in sections:
        add_par(tf, pointer, label_size, bold=True, color=PURPLE,
                first=first, before=0 if first else 12, after=4)
        used += text_lines(pointer, label_size, width - 0.1, True) * label_size * 1.17
        used += (0 if first else 12) + 4
        first = False
        for pt in points:
            add_par(tf, pt, BODY_PT, color=INK, bullet="\u25aa", after=3)
            used += text_lines(pt, BODY_PT, width - 0.1 - 0.32, False) * BODY_PT * 1.17 + 3

    used_in = used / 72
    shape.height = Inches(height if height else min(used_in + 0.2, 8.1))
    if check:
        limit = (height or 8.1)
        flag = "OK" if used_in <= limit else "OVERFLOW"
        print(f"  slide {slide_no}: text {used_in:.2f}in of {limit:.2f}in  [{flag}]")
    return used_in


# ------------------------------------------------------------------ slides --
def slide_title(s):
    tb = find(s, 93)
    # one leading blank paragraph in the template only pushes the list down
    paras = tb.text_frame.paragraphs
    if paras and not paras[0].text.strip():
        paras[0]._p.getparent().remove(paras[0]._p)
    # start just under "TITLE PAGE" and tighten the gaps a little, so the
    # wrapped problem-statement title cannot push the team name off the slide
    tb.top = Inches(3.05)
    tb.width = Inches(11.2)
    tb.height = Inches(7.6)
    for p in tb.text_frame.paragraphs:
        p.line_spacing = 1.0
        p.space_before = Pt(16)
        p.space_after = Pt(0)

    values = {
        "Problem Statement \u2013": " [enter PS ID]",
        "Problem Statement Title-": " Agentic AI Grievance Redressal System",
        "Theme-": " [enter theme]",
        "Team ID-": " [enter Team ID]",
        "Team Name (Registered on portal)": " \u2013 " + TEAM,
    }
    filled = 0
    for p in tb.text_frame.paragraphs:
        label = p.text.strip()
        if label in values:
            p.alignment = PP_ALIGN.LEFT
            r = p.add_run()
            r.text = values[label]
            style_run(r, 30, bold=label.startswith("Team Name"), color=PURPLE)
            filled += 1
    print(f"  slide 1: filled {filled}/5 title lines")


def set_team_badges(prs):
    n = 0
    for slide in prs.slides:
        for sh in walk(slide.shapes):
            if sh.has_text_frame and sh.text_frame.text.strip() == "Your Team Name":
                runs = sh.text_frame.paragraphs[0].runs
                for i, r in enumerate(runs):     # NOT `r is runs[0]`: python-pptx
                    r.text = TEAM if i == 0 else ""  # makes new proxies per access
                style_run(runs[0], 24, bold=True, color=PURPLE)
                n += 1
    print(f"  team badge set on {n} slides")


def slide_idea(s):
    # the template's "IDEA TITLE" is a placeholder for the idea's name
    for sh in walk(s.shapes):
        if sh.has_text_frame and sh.text_frame.text.strip() == "IDEA TITLE":
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.text.strip() == "IDEA TITLE":
                        r.text = "AGENTIC AI GRIEVANCE DESK"
    shape = find(s, 115)
    pointer_column(
        shape,
        [
            ("Detailed explanation of the proposed solution", [
                "Citizens file by voice or text in Marathi, Hindi or English",
                "AI drafts the complaint; nothing is filed until the citizen confirms",
            ]),
            ("How it addresses the problem", [
                "Routes to the right department and deadline from CSV",
                "Ranks by severity, urgency and people affected",
            ]),
            ("Innovation and uniqueness of the solution", [
                "8 safety rules are tested code guards, not prompt instructions",
                "Duplicates grouped, never merged; every AI step audited",
            ]),
        ],
        width=LEFT_W - 0.4,
        heading="Proposed Solution (Describe your Idea/Solution/Prototype)",
        slide_no=2,
    )
    # two phones, the Marathi one behind, the draft-confirmation one in front
    picture(s, "06c_citizen_marathi_mobile.png", 10.55, 3.15, h=5.9)
    _, w, h = picture(s, "06b_citizen_draft_mobile.png", 13.05, 2.0, h=7.45)
    caption(s, "Same screen in Marathi, and the AI draft awaiting the citizen\u2019s confirmation",
            10.55, 2.0 + h + 0.1, 6.9, size=14)


def slide_technical(s):
    shape = find(s, 130)
    pointer_column(
        shape,
        [
            ("Technologies to be used (e.g. programming languages, frameworks)", [
                "Backend: Python, FastAPI, SQLAlchemy, Postgres + pgvector",
                "AI: LangGraph agents, Langfuse tracing, speech-to-text",
                "Frontend: Next.js 15, React 19, Tailwind, Leaflet maps",
                "Automation: n8n webhooks \u2014 every notification is mock",
            ]),
            ("Methodology and process for implementation (Flow Charts/Images/ working prototype)", [
                "All policy read from CSV at runtime \u2014 nothing hard-coded",
                "One guard layer enforces 8 rules; 191 tests prove it",
            ]),
        ],
        width=LEFT_W,
        slide_no=3,
        height=4.9,
    )
    img_w = 5.9
    shot = crop("03b_case_reasoning.png", 0.03, 0.69, 140, img_w / 4.75)
    _, w, h = picture(s, shot, RIGHT_R - img_w, TOP, w=img_w)
    caption(s, "Officer view: the exact rule applied and why",
            RIGHT_R - img_w, TOP + h + 0.06, img_w, size=14)

    # the flowchart the pointer asks for
    steps = [
        ("Intake", "language, draft, confirm"),
        ("Retrieval", "similar past cases"),
        ("Policy", "CSV rules & deadline"),
        ("Decision", "resolve or human queue"),
        ("Action", "webhook + audit row"),
    ]
    y, bw, bh, gap = 7.45, 2.72, 1.18, 0.5
    x = LEFT_X
    for i, (title, sub) in enumerate(steps):
        b = box(s, x, y, bw, bh)
        tf = b.text_frame
        add_par(tf, title, 21, bold=True, color=PURPLE, first=True, after=1,
                align=PP_ALIGN.CENTER)
        add_par(tf, sub, 14, color=INK, after=0, align=PP_ALIGN.CENTER)
        if i < len(steps) - 1:
            a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + bw + 0.08),
                                   Inches(y + bh / 2 - 0.17), Inches(gap - 0.16), Inches(0.34))
            a.fill.solid(); a.fill.fore_color.rgb = PURPLE
            a.line.fill.background(); a.shadow.inherit = False
        x += bw + gap
    flow_right = x - gap
    g = box(s, LEFT_X, y + bh + 0.22, flow_right - LEFT_X, 0.62, fill=PURPLE, line=None)
    add_par(g.text_frame,
            "Guard layer on every step: 8 hard rules checked in code  \u00b7  an audit row for every AI action",
            16, bold=True, color=WHITE, first=True, after=0, align=PP_ALIGN.CENTER)


def slide_feasibility(s):
    shape = find(s, 155)
    pointer_column(
        shape,
        [
            ("Analysis of the feasibility of the idea", [
                "Working end to end today: file \u2192 triage \u2192 route \u2192 track",
                "Built on open tools; one DATABASE_URL moves it to AWS",
            ]),
            ("Potential challenges and risks", [
                "AI misreads a dangerous case as routine",
                "Too little history to predict deadlines honestly",
                "Analytics could reveal who complained",
            ]),
            ("Strategies for overcoming these challenges", [
                "Two independent signals hold risky cases for a human",
                "The predictor refuses to guess below 8 similar cases",
                "Taluka-level maps only, with small counts hidden",
            ]),
        ],
        width=LEFT_W,
        slide_no=4,
    )
    w = RIGHT_R - RIGHT_X
    shot = crop("05_compliance_full.png", 0.19, 0.81, 180, w / 5.6)
    _, w, h = picture(s, shot, RIGHT_X, TOP, w=w)
    caption(s, "Safety rules page: each rule is probed live against the running code",
            RIGHT_X, TOP + h + 0.06, RIGHT_R - RIGHT_X, size=14)

    stats = [("191", "tests passing"), ("9 / 9", "rules proved live"), ("16", "talukas mapped")]
    sy, sh_ = TOP + h + 0.6, 1.4
    sw = ((RIGHT_R - RIGHT_X) - 2 * 0.22) / 3
    for i, (num, label) in enumerate(stats):
        b = box(s, RIGHT_X + i * (sw + 0.22), sy, sw, sh_)
        add_par(b.text_frame, num, 36, bold=True, color=PURPLE, first=True, after=0,
                align=PP_ALIGN.CENTER)
        add_par(b.text_frame, label, 15, color=INK, after=0, align=PP_ALIGN.CENTER)


def slide_impact(s):
    shape = find(s, 180)
    pointer_column(
        shape,
        [
            ("Potential impact on the target audience", [
                "Citizens: file in their own language, track one reference",
                "Officers: a severity-ranked queue with the reasoning shown",
                "District: taluka hotspots and deadline-miss rates",
                "Reach: WhatsApp and phone helpline channels (MVP preview)",
            ]),
            ("Benefits of the solution (social, economic, environmental, etc.)", [
                "Social: help follows danger, not who complains loudest",
                "Economic: officer time moves from sorting to deciding",
                "Governance: every AI step is logged and labelled AI-generated",
                "Reusable: any district adopts it by swapping CSV sheets",
            ]),
        ],
        width=LEFT_W,
        slide_no=5,
    )
    w = RIGHT_R - RIGHT_X
    map_shot = crop("04_hotspots_map_full.png", 0.16, 0.84, 330, w / 4.85)
    _, _, h1 = picture(s, map_shot, RIGHT_X, TOP, w=w)
    queue_shot = crop("02_queue_full.png", 0.10, 0.90, 600, (w - 0.35) / 2.45)
    picture(s, queue_shot, RIGHT_X, TOP + h1 + 0.25, w=w - 0.35)


def slide_references(s):
    shape = find(s, 208)
    pointer_column(
        shape,
        [
            ("Details / Links of the reference and research work", [
                "HackFusion 4.0 dataset pack: category master, 800-case history, department directory",
                "CPGRAMS, Government of India (pgportal.gov.in): grievance lifecycle and deadlines",
                "NIST AI Risk Management Framework 1.0: accountable, auditable automation",
                "Documentation: LangGraph, pgvector, Langfuse, FastAPI, Next.js",
                "OpenStreetMap and Nominatim (ODbL): taluka coordinates",
                "Code: [add GitHub URL]",
                "Demo video: [add link]",
            ]),
        ],
        width=LEFT_W,
        slide_no=6,
    )
    w = RIGHT_R - RIGHT_X
    shot = crop("01_home_full.png", 0.10, 0.90, 160, w / 7.35)
    _, w, h = picture(s, shot, RIGHT_X, TOP, w=w)
    caption(s, "Live prototype home: what it refuses to do, and the five agents",
            RIGHT_X, TOP + h + 0.06, RIGHT_R - RIGHT_X, size=14)


def delete_slide(prs, index):
    sldIdLst = prs.slides._sldIdLst
    sld = sldIdLst[index]
    prs.part.drop_rel(sld.rId)
    sldIdLst.remove(sld)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    prs = Presentation(str(SRC))
    assert len(prs.slides) == 7, "unexpected template"

    slides = list(prs.slides)
    slide_title(slides[0])
    set_team_badges(prs)
    slide_idea(slides[1])
    slide_technical(slides[2])
    slide_feasibility(slides[3])
    slide_impact(slides[4])
    slide_references(slides[5])
    delete_slide(prs, 6)

    prs.save(args.out)
    print(f"saved {args.out}  ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
