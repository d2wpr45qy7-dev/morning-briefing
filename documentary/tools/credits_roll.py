"""End-credits roll: one tall image listing every source in an assets file, scrolled by a Still camera move.

roll_shot(assets_json, film_title, slug) -> (duration, factory) for a roll that scrolls from blank to blank.
"""
import json, os, textwrap
from PIL import Image, ImageDraw
import cv2
from render import W, H, FPS, ASSETS, GOLD, IVORY, F_SERIF, F_SERIF_I, F_SANS_B, font, Still

GEN = os.path.join(ASSETS, "generated")


def _entries(assets_json):
    out = []
    for e in json.load(open(assets_json)):
        side = os.path.join(ASSETS, e["file"] + ".json")
        e = {**(json.load(open(side)) if os.path.exists(side) else {}), **e}
        if e.get("credit") is False or not e.get("title"):
            continue
        out.append(e)
    groups = [("Film", lambda e: e["file"].startswith("video/")), ("Documents", lambda e: e["file"].startswith("docs/")),
              ("Photographs and prints", lambda e: e["file"].startswith("loc/")),
              ("Objects", lambda e: e["file"].startswith("cma/")),
              ("Engravings and paintings", lambda e: True)]
    done, res = set(), []
    for name, pred in groups:
        items = [e for e in sorted(out, key=lambda e: e["file"]) if e["file"] not in done and pred(e)]
        done |= {e["file"] for e in items}
        if items:
            res.append((name, items))
    return res


def txt(v):
    return (", ".join(map(str, v)) if isinstance(v, list) else str(v or "")).strip()


def make_roll(assets_json, film_title, path):
    f_title, f_head, f_item, f_sub = font(F_SANS_B, 44), font(F_SANS_B, 28), font(F_SERIF, 28), font(F_SERIF_I, 24)
    lines = [("title", film_title.upper()), ("gap", 30),
             ("item", "Narration: a synthetic voice (Chatterbox TTS) conditioned on a synthetic Kokoro voice. No real person's voice is used."),
             ("item", "Music: an original score composed and synthesized for this film."),
             ("item", "Maps drawn from Natural Earth (public domain)."), ("gap", 40)]
    for head, items in _entries(assets_json):
        lines += [("head", head.upper()), ("gap", 14)]
        for e in items:
            lines.append(("item", txt(e["title"])))
            lic = txt(e.get("license")).split(". For information")[0]
            sub = "  ·  ".join(x for x in (txt(e.get("artist")), lic, txt(e.get("source"))) if x)
            lines.append(("sub", sub))
            lines.append(("gap", 10))
        lines.append(("gap", 30))
    wrap = {"item": 92, "sub": 110, "title": 60, "head": 80}
    rows = []
    for kind, val in lines:
        if kind == "gap":
            rows.append((kind, val)); continue
        for part in textwrap.wrap(val, wrap[kind]) or [""]:
            rows.append((kind, part))
    lh = {"title": 62, "head": 42, "item": 36, "sub": 30}
    height = H + sum(v if k == "gap" else lh[k] for k, v in rows) + H
    im = Image.new("RGB", (W, height), (14, 12, 11))
    d = ImageDraw.Draw(im)
    y = H
    for kind, val in rows:
        if kind == "gap":
            y += val; continue
        fnt = dict(title=f_title, head=f_head, item=f_item, sub=f_sub)[kind]
        col = dict(title=IVORY, head=GOLD, item=IVORY, sub=(176, 164, 140))[kind]
        x = (W - d.textlength(val, font=fnt)) / 2
        d.text((x, y), val, font=fnt, fill=col)
        y += lh[kind]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path)
    return im.size


class Roll(Still):
    """A Still that scrolls at constant speed (credits must not ease in and out)."""

    def _frames(self):
        n = round(self.dur * FPS)
        for i in range(n):
            u = i / max(1, n - 1)
            cy = (self.start[1] + (self.end[1] - self.start[1]) * u) * self.h
            fr = cv2.remap(self.img, self.gx + self.w / 2, cy + self.gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            for ov in self.overlays:
                fr = ov.apply(fr, i / FPS)
            yield fr


def roll_shot(assets_json, film_title, slug, speed=150.0):
    """Returns (duration, factory): the roll scrolls at `speed` px/s from blank to blank."""
    path = os.path.join(GEN, f"credits_{slug}.png")
    w, h = make_roll(assets_json, film_title, path)
    dur = (h - H) / speed
    a, b = (H / 2) / h, 1 - (H / 2) / h
    return dur, lambda d: Roll(os.path.relpath(path, ASSETS), d, start=(0.5, a, 1.0), end=(0.5, b, 1.0))
