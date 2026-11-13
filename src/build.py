#!/usr/bin/env python3
"""Build the GitHub profile card, link buttons and README for moebis.

The output is deterministic. The same inputs always give the same bytes.

Inputs:
  src/profile.json   public profile facts, card lines, buttons, portrait settings
  src/portrait.txt   ASCII portrait (82 x 50 characters)

Outputs:
  assets/card-dark.svg, assets/card-light.svg
  assets/button-<id>-dark.svg, assets/button-<id>-light.svg
  README.md

Usage:
  python3 src/build.py                  rebuild SVGs and README
  python3 src/build.py --check          exit 1 if a generated file is out of date
  python3 src/build.py --photo PATH     regenerate src/portrait.txt from a photo,
                                        then rebuild (needs ImageMagick 7)

Only the --photo step needs ImageMagick. Everything else uses the Python 3
standard library.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ASSETS = ROOT / "assets"

FONT = ('ui-monospace, SFMono-Regular, \'SF Mono\', Menlo, Monaco, Consolas, '
        '\'Liberation Mono\', \'DejaVu Sans Mono\', monospace')
ADVANCE = 0.6  # monospace advance width in em; textLength locks every run to it

THEMES = {
    "dark": {
        "bg": "#151619", "bar": "#1b1c20", "border": "#2b2c31", "dot": "#3a3b41",
        "ink": "#dcd5c6", "text": "#ece6da", "dim": "#77736b", "lead": "#4f4c47",
        "accent": "#e8ae5b", "rule": "#33343a",
    },
    "light": {
        "bg": "#fbf9f4", "bar": "#f3efe7", "border": "#e4ded2", "dot": "#dbd4c7",
        "ink": "#23211e", "text": "#1e1d1b", "dim": "#8f897e", "lead": "#c9c2b5",
        "accent": "#a65f0a", "rule": "#e4ded2",
    },
}

# Card geometry (SVG user units; GitHub scales the image to the README width).
W = 1000
BAR_H = 40
PAD_TOP = 30
PAD_X = 36
P_FS, P_LH = 9.0, 10.0           # portrait font size and line height
I_FS, I_LH, I_COLS = 14.0, 22.0, 52  # info font size, line height, columns
I_RIGHT = 40

# Button geometry: four images of 250 units tile the 1000-unit card width.
B_W, B_H, B_GAP, B_SLOT = 241, 44, 12, 250

# ---------------------------------------------------------------------------
# Photo to ASCII (deterministic; tone plus 2x4 shape matching)
# ---------------------------------------------------------------------------

CHARS = " .:-=+*#%@/\\|_()'`,"
# Ink coverage of each glyph in a 2x4 grid (Menlo, measured once, densest = 1).
TEMPLATES = {
    " ": (0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000),
    ".": (0.000, 0.000, 0.000, 0.000, 0.763, 0.428, 0.108, 0.060),
    ":": (0.000, 0.000, 0.640, 0.436, 0.557, 0.380, 0.089, 0.060),
    "-": (0.000, 0.000, 0.340, 0.364, 0.488, 0.522, 0.000, 0.000),
    "=": (0.000, 0.000, 0.851, 0.857, 0.851, 0.857, 0.000, 0.000),
    "+": (0.000, 0.000, 0.597, 0.806, 0.751, 0.978, 0.000, 0.000),
    "*": (0.000, 0.000, 0.983, 1.037, 1.029, 1.090, 0.000, 0.000),
    "#": (0.252, 0.435, 1.385, 1.586, 1.604, 1.378, 0.098, 0.054),
    "%": (0.650, 0.007, 1.463, 0.840, 0.608, 1.797, 0.000, 0.113),
    "@": (0.249, 0.461, 1.299, 1.557, 1.558, 1.363, 0.766, 0.748),
    "/": (0.000, 0.454, 0.158, 0.931, 1.045, 0.044, 0.409, 0.000),
    "\\": (0.454, 0.000, 1.028, 0.061, 0.130, 0.959, 0.000, 0.408),
    "|": (0.126, 0.366, 0.253, 0.733, 0.253, 0.733, 0.232, 0.672),
    "_": (0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.998, 0.990),
    "(": (0.194, 0.503, 1.049, 0.049, 0.812, 0.249, 0.010, 0.306),
    ")": (0.570, 0.128, 0.135, 0.961, 0.383, 0.680, 0.317, 0.000),
    "'": (0.275, 0.366, 0.297, 0.396, 0.000, 0.000, 0.000, 0.000),
    "`": (0.498, 0.131, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000),
    ",": (0.000, 0.000, 0.000, 0.000, 0.491, 0.396, 0.820, 0.140),
}


def _magick(args):
    exe = shutil.which("magick")
    if not exe:
        sys.exit("ImageMagick 7 ('magick') is required for --photo.")
    return subprocess.run([exe, *args], check=True, capture_output=True).stdout


def _read_pgm(data):
    """Parse a binary 8-bit PGM (P5) into rows of floats in 0..1."""
    fields, pos = [], 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos)
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    if fields[0] != b"P5" or int(fields[3]) != 255:
        raise ValueError("expected an 8-bit binary PGM")
    w, h = int(fields[1]), int(fields[2])
    pix = data[pos + 1:pos + 1 + w * h]
    return [[pix[y * w + x] / 255.0 for x in range(w)] for y in range(h)]


def photo_to_ascii(photo, cfg):
    cols, rows = cfg["cols"], cfg["rows"]
    iw, ih = (int(v) for v in _magick([str(photo), "-format", "%w %h", "info:"]).split())
    fx, fy, fw, fh = cfg["crop"]
    cx, cy, cw, ch = round(fx * iw), round(fy * ih), round(fw * iw), round(fh * ih)
    sigma = cfg["blur"] * cw
    img = _read_pgm(_magick([
        str(photo), "-colorspace", "Gray", "-crop", f"{cw}x{ch}+{cx}+{cy}", "+repage",
        "-blur", f"0x{sigma:.3f}", "-filter", "Box", "-resize", f"{cols * 2}x{rows * 4}!",
        "-depth", "8", "pgm:-",
    ]))
    lo, hi = cfg["contrast"]
    wt, ws = cfg["tone_weight"], cfg["shape_weight"]

    def ink(v):  # darkness with a smooth S-curve between lo and hi
        t = min(max(((1.0 - v) - lo) / (hi - lo), 0.0), 1.0)
        return t * t * (3.0 - 2.0 * t)

    tmpl = []
    for c in CHARS:
        t = TEMPLATES[c]
        m = sum(t) / 8.0
        tmpl.append((c, m, [x - m for x in t]))

    lines = []
    for r in range(rows):
        out = []
        for c in range(cols):
            v = [ink(img[r * 4 + j][c * 2 + i]) for j in range(4) for i in range(2)]
            vm = sum(v) / 8.0
            vd = [x - vm for x in v]
            best, best_e = " ", None
            for ch_, m, td in tmpl:
                e = wt * 8.0 * (m - vm) ** 2 + ws * sum((a - b) ** 2 for a, b in zip(td, vd))
                if best_e is None or e < best_e:
                    best, best_e = ch_, e
            out.append(best)
        lines.append("".join(out).rstrip())
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

def num(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def run(text, x, y, fs, cls, anchor=None, tracking=0.0):
    """One text run locked to the monospace grid with textLength."""
    length = len(text) * fs * ADVANCE + max(len(text) - 1, 0) * tracking
    a = f' text-anchor="{anchor}"' if anchor else ""
    return (f'<text x="{num(x)}" y="{num(y)}" class="{cls}" textLength="{num(length)}"'
            f'{a} xml:space="preserve">{escape(text)}</text>')


def style_block(t, extra=""):
    return (
        "<style>"
        f"text{{font-family:{FONT};white-space:pre}}"
        f".a{{fill:{t['accent']}}}.x{{fill:{t['text']}}}.d{{fill:{t['dim']}}}.l{{fill:{t['lead']}}}"
        ".b{font-weight:700}"
        f"{extra}"
        "</style>"
    )


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def info_segments(item, header):
    """Return ([(text, class)], rule) for one info line. rule is True for a ruled line."""
    if item is None:
        return [(".", "d")], False
    if item == "header":
        return [(header, "a b")], True
    if isinstance(item, dict) and "section" in item:
        return [("- ", "d"), (item["section"], "x b")], True
    if item == "prompt":
        return [("> ", "a b")], False
    key, value = item
    head = f". {key}: "
    tail = f" {value}"
    dots = I_COLS - len(head) - len(tail)
    if dots < 3:
        raise ValueError(f"card line too long for {I_COLS} columns: {key}: {value}")
    return [(". ", "d"), (key, "a"), (": ", "d"), ("." * dots, "l"), (tail, "x")], False


def build_card(profile, portrait, theme):
    t = THEMES[theme]
    card = profile["card"]
    pcfg = profile["portrait"]
    rows, cols = pcfg["rows"], pcfg["cols"]
    p_cw = P_FS * ADVANCE
    i_cw = I_FS * ADVANCE

    p_h = rows * P_LH
    content_top = BAR_H + PAD_TOP
    H = int(content_top + p_h + PAD_TOP)
    ix = W - I_RIGHT - I_COLS * i_cw
    widest = max(len(line.rstrip()) for line in portrait[:rows])
    if widest > cols or len(portrait[:rows]) < rows - 1:
        raise ValueError(f"portrait.txt must be at most {cols} columns and {rows} rows")
    px = max(PAD_X, (ix - widest * p_cw) / 2)  # centre the art in the space left of the info column

    items = ["header", *card["lines"], None, "prompt"]
    i_h = len(items) * I_LH
    i_top = content_top + (p_h - i_h) / 2

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">'
    )
    out.append(f'<title id="title">{escape(profile["name"])} ({escape(profile["login"])})</title>')
    out.append(f'<desc id="desc">{escape(card_alt(profile))}</desc>')
    blink = (
        f".c{{fill:{t['accent']};animation:k 1.2s steps(1,end) infinite}}"
        "@keyframes k{50%{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.c{animation:none}}"
    )
    out.append(style_block(t, blink + f".p{{font-size:{num(P_FS)}px;font-weight:700}}"
                                      f".i{{font-size:{num(I_FS)}px}}"))
    out.append("<defs>")
    out.append(f'<clipPath id="clip"><rect width="{W}" height="{H}" rx="12"/></clipPath>')
    out.append(
        f'<linearGradient id="fade" gradientUnits="userSpaceOnUse" x1="0" y1="{num(content_top)}" '
        f'x2="0" y2="{num(content_top + p_h)}">'
        f'<stop offset="0" stop-color="{t["ink"]}"/>'
        f'<stop offset="0.7" stop-color="{t["ink"]}"/>'
        f'<stop offset="1" stop-color="{t["ink"]}" stop-opacity="0.12"/>'
        "</linearGradient>"
    )
    out.append("</defs>")

    # Frame and title bar.
    out.append('<g clip-path="url(#clip)">')
    out.append(f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>')
    out.append(f'<rect width="{W}" height="{BAR_H}" fill="{t["bar"]}"/>')
    out.append(f'<path d="M0 {BAR_H - 0.5}H{W}" stroke="{t["border"]}"/>')
    out.append("</g>")
    out.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="11.5" '
               f'fill="none" stroke="{t["border"]}"/>')
    for i in range(3):
        out.append(f'<circle cx="{22 + i * 18}" cy="{BAR_H / 2:g}" r="5.5" fill="{t["dot"]}"/>')
    out.append(f'<g font-size="12">{run(card["title"], W / 2, BAR_H / 2 + 4.2, 12, "d", "middle")}</g>')

    # Portrait.
    out.append(f'<g class="p" fill="url(#fade)">')
    for r, line in enumerate(portrait[:rows]):
        body = line.rstrip()
        lead = len(body) - len(body.lstrip(" "))
        body = body.strip(" ")
        if not body:
            continue
        y = content_top + r * P_LH + P_LH * 0.8
        length = len(body) * p_cw
        out.append(f'<text x="{num(px + lead * p_cw)}" y="{num(y)}" '
                   f'textLength="{num(length)}" xml:space="preserve">{escape(body)}</text>')
    out.append("</g>")

    # Info column.
    out.append('<g class="i">')
    for n, item in enumerate(items):
        segs, rule = info_segments(item, card["header"])
        y_mid = i_top + n * I_LH + I_LH / 2
        base = y_mid + I_FS * 0.36
        x = ix
        for text, cls in segs:
            out.append(run(text, x, base, I_FS, cls))
            x += len(text) * i_cw
        if rule:
            x0 = x + i_cw
            out.append(f'<path d="M{num(x0)} {num(y_mid + 0.5)}H{num(ix + I_COLS * i_cw)}" '
                       f'stroke="{t["rule"]}"/>')
        if item == "prompt":
            out.append(f'<rect class="c" x="{num(x)}" y="{num(y_mid - 8)}" width="{num(i_cw)}" '
                       f'height="16" rx="1"/>')
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def card_alt(profile):
    """Plain-language summary of the card for alt text and the SVG description."""
    parts = [f"Terminal-style profile card for {profile['name']} ({profile['login']}). "
             f"{profile['portrait_alt']}."]
    section, entries = None, []

    def flush():
        if section and entries:
            parts.append(f"{section}: {', '.join(entries)}.")

    for item in profile["card"]["lines"]:
        if item is None:
            continue
        if isinstance(item, dict):
            flush()
            section, entries = item["section"], []
            continue
        key, value = item
        if section:
            entries.append(f"{key} ({value})")
        else:
            parts.append(f"{key.replace('.', ' ')}: {value}.")
    flush()
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

ICONS = {
    # 18x18 stroke icons centred on (0, 0).
    "globe": ('<circle r="7.5"/><ellipse rx="3.2" ry="7.5"/>'
              '<path d="M-7.5 0H7.5M-6.4 -3.8H6.4M-6.4 3.8H6.4"/>'),
    "shield": ('<path d="M0 -8.2 6.6 -5.6V-0.6C6.6 3.6 3.9 6.6 0 8.2 -3.9 6.6 -6.6 3.6 -6.6 -0.6V-5.6Z"/>'
               '<path d="M-2.6 0.2 -0.6 2.2 3 -1.6"/>'),
    "points": ('<path d="M-6.5 -3.6 0 -7.3 6.5 -3.6V3.6L0 7.3 -6.5 3.6Z" opacity="0.45"/>'
               '<g stroke="none" fill="currentColor">'
               '<circle cx="0" cy="-7.3" r="1.5"/><circle cx="6.5" cy="-3.6" r="1.5"/>'
               '<circle cx="6.5" cy="3.6" r="1.5"/><circle cx="0" cy="7.3" r="1.5"/>'
               '<circle cx="-6.5" cy="3.6" r="1.5"/><circle cx="-6.5" cy="-3.6" r="1.5"/>'
               '<circle cx="0" cy="0" r="1.8"/><circle cx="-2.9" cy="-1.9" r="1"/>'
               '<circle cx="3.1" cy="2.2" r="1"/><circle cx="2.6" cy="-2.6" r="0.9"/>'
               '<circle cx="-2.4" cy="3" r="0.9"/></g>'),
    "mic": ('<rect x="-3" y="-8" width="6" height="10.5" rx="3"/>'
            '<path d="M-6.2 -0.5C-6.2 3.2 -3.4 5.6 0 5.6S6.2 3.2 6.2 -0.5M0 5.6V8.4M-3.2 8.4H3.2"/>'),
}


def build_button(button, index, theme):
    t = THEMES[theme]
    H = B_H + 8
    bx = index * (B_W + B_GAP) - index * B_SLOT  # local offset so four images tile the card width
    by = 4
    fs, tracking = 12.5, 1.1
    label = button["label"].upper()
    label_w = len(label) * fs * ADVANCE + (len(label) - 1) * tracking
    icon_w, gap = 18, 11
    group = icon_w + gap + label_w
    gx = bx + (B_W - group) / 2
    cy = by + B_H / 2
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{B_SLOT}" height="{H}" '
        f'viewBox="0 0 {B_SLOT} {H}" role="img" aria-label="{escape(button["alt"])}">',
        f'<title>{escape(button["alt"])}</title>',
        style_block(t),
        f'<rect x="{bx + 0.5}" y="{by + 0.5}" width="{B_W - 1}" height="{B_H - 1}" rx="8" '
        f'fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<path d="M{bx + 14} {by + B_H - 1}H{bx + B_W - 14}" stroke="{t["accent"]}" '
        f'stroke-width="2" stroke-linecap="round" opacity="0.85"/>',
        f'<g transform="translate({num(gx + icon_w / 2)} {num(cy)})" fill="none" '
        f'stroke="{t["accent"]}" color="{t["accent"]}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[button["icon"]]}</g>',
        f'<text x="{num(gx + icon_w + gap)}" y="{num(cy + fs * 0.36)}" class="x" '
        f'font-size="{fs}" letter-spacing="{tracking}" textLength="{num(label_w)}" xml:space="preserve">'
        f'{escape(label)}</text>',
        "</svg>",
    ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def picture(stem, alt, width):
    return (
        "<picture>"
        f'<source media="(prefers-color-scheme: dark)" srcset="assets/{stem}-dark.svg">'
        f'<source media="(prefers-color-scheme: light)" srcset="assets/{stem}-light.svg">'
        f'<img src="assets/{stem}-light.svg" width="{width}" alt="{escape(alt, {chr(34): "&quot;"})}">'
        "</picture>"
    )


def build_readme(profile):
    site = profile["website"]
    host = site.split("//", 1)[-1].rstrip("/")
    buttons = "".join(
        f'<a href="{b["href"]}">{picture("button-" + b["id"], b["alt"], "25%")}</a>'
        for b in profile["buttons"]
    )
    projects = "\n".join(
        f"- [{p['name']}]({p['url']}): {p['description']}" for p in profile["projects"]
    )
    return f"""<!-- Generated by src/build.py from src/profile.json and src/portrait.txt. Do not edit by hand. -->

<p align="center">
  {picture("card", card_alt(profile), "100%")}
</p>

<p align="center">{buttons}</p>

**{profile['name']}** · {profile['location']} · [{host}]({site})

{profile['bio']}

{projects}
"""


# ---------------------------------------------------------------------------

def outputs(profile, portrait):
    files = {}
    for theme in THEMES:
        files[ASSETS / f"card-{theme}.svg"] = build_card(profile, portrait, theme)
        for i, b in enumerate(profile["buttons"]):
            files[ASSETS / f"button-{b['id']}-{theme}.svg"] = build_button(b, i, theme)
    files[ROOT / "README.md"] = build_readme(profile)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--photo", type=Path, help="regenerate src/portrait.txt from this image")
    ap.add_argument("--check", action="store_true", help="fail if outputs are out of date")
    args = ap.parse_args()

    profile = json.loads((SRC / "profile.json").read_text(encoding="utf-8"))
    if len(profile["buttons"]) * B_SLOT != W:
        sys.exit(f"buttons must tile the card: {len(profile['buttons'])} x {B_SLOT} != {W}")
    if args.photo:
        (SRC / "portrait.txt").write_text(photo_to_ascii(args.photo, profile["portrait"]),
                                          encoding="utf-8")
    portrait = (SRC / "portrait.txt").read_text(encoding="utf-8").split("\n")

    stale = []
    for path, text in outputs(profile, portrait).items():
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            continue
        if args.check:
            stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        sys.exit("out of date: " + ", ".join(map(str, stale)))
    if args.check:
        print("all generated files are current")


if __name__ == "__main__":
    main()
