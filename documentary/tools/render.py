"""Shot types and the streaming compositor for the documentary.

Shots: Still (camera move on an image, optional depth parallax), Footage (real video), Document (camera over a scan,
synced highlights and a translation band), Black (title cards). Overlays: Text (lower third, title, chapter, label), Fade.
render() streams frames to ffmpeg with crossfades and a consistent film finish (grade, vignette, grain).
"""
import math, os, subprocess
from collections import deque
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1920, 1080, 30
DOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(DOC, "assets")
CACHE = os.path.join(DOC, "cache")
os.makedirs(CACHE, exist_ok=True)

F_SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
F_SERIF_I = "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"
F_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
F_SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
GOLD = (214, 178, 96)
IVORY = (238, 230, 212)


def font(path, size):
    return ImageFont.truetype(path, size)


def smooth(t):
    t = min(1.0, max(0.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def lerp(a, b, t):
    return a + (b - a) * t


def asset(name):
    return os.path.join(ASSETS, name)


def load_image(name, crop=None, max_w=4200):
    im = Image.open(asset(name)).convert("RGB")
    if crop:  # fractional (l, t, r, b)
        l, t, r, b = crop
        im = im.crop((int(l * im.width), int(t * im.height), int(r * im.width), int(b * im.height)))
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    return np.asarray(im)


_DEPTH = None


def depth_map(name, crop=None):
    key = os.path.join(CACHE, "depth_" + name.replace("/", "_") + (f"_{crop}" if crop else "") + ".npy")
    if os.path.exists(key):
        return np.load(key)
    global _DEPTH
    if _DEPTH is None:
        from transformers import pipeline
        _DEPTH = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device="cpu")
    img = load_image(name, crop)
    d = np.asarray(_DEPTH(Image.fromarray(img))["depth"].resize((img.shape[1], img.shape[0]), Image.BICUBIC)).astype(np.float32)
    d = cv2.GaussianBlur(d, (0, 0), max(3, img.shape[1] / 300))
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    np.save(key, d)
    return d


def tone(fr, kind):
    if kind == "sepia":
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY).astype(np.float32)
        return np.clip(np.stack([g * 1.07 + 8, g * 0.98 + 4, g * 0.82], -1), 0, 255).astype(np.uint8)
    return fr


class Shot:
    """Base class: subclasses load their media lazily in prepare() so a long edit does not hold everything in memory."""
    cut = False

    def frames(self):
        self.prepare()
        try:
            yield from self._frames()
        finally:
            self.release()

    def prepare(self):
        pass

    def release(self):
        pass


class Still(Shot):
    """Camera move across an image. start/end: (cx, cy, zoom) as fractions of the image; zoom=1 fills the frame."""

    def __init__(self, name, dur, start=(0.5, 0.5, 1.0), end=(0.5, 0.5, 1.12), crop=None, parallax=0.0, tone=None, overlays=()):
        self.name, self.crop, self.dur, self.start, self.end = name, crop, dur, start, end
        self.parallax, self.tone_kind, self.overlays = parallax, tone, overlays

    def prepare(self):
        self.img = load_image(self.name, self.crop)
        self.h, self.w = self.img.shape[:2]
        self.depth = depth_map(self.name, self.crop) if self.parallax else None
        self.cover = 1 / max(W / self.w, H / self.h)
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        self.gx, self.gy = xs - W / 2, ys - H / 2

    def release(self):
        self.img = self.depth = self.gx = self.gy = None

    def _frames(self):
        n = round(self.dur * FPS)
        for i in range(n):
            t = smooth(i / max(1, n - 1))
            cx = lerp(self.start[0], self.end[0], t) * self.w
            cy = lerp(self.start[1], self.end[1], t) * self.h
            s = self.cover / lerp(self.start[2], self.end[2], t)
            cx = min(max(cx, W * s / 2), self.w - W * s / 2)
            cy = min(max(cy, H * s / 2), self.h - H * s / 2)
            mx, my = cx + self.gx * s, cy + self.gy * s
            if self.depth is not None:
                d = cv2.remap(self.depth, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                k = self.parallax * (t - 0.5)
                mx = mx - (d - 0.5) * k * self.gx * s
                my = my - (d - 0.5) * k * self.gy * s
            fr = cv2.remap(self.img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            if self.tone_kind:
                fr = tone(fr, self.tone_kind)
            for ov in self.overlays:
                fr = ov.apply(fr, i / FPS)
            yield fr


class Footage(Shot):
    def __init__(self, path, dur, src_start=0.0, speed=1.0, zoom=(1.0, 1.06), overlays=(), sharpen=False, pre=None):
        """pre: an ffmpeg filter applied to the source first, e.g. 'crop=1440:1080:240:0' to drop a pillarbox."""
        self.path, self.dur, self.src_start, self.speed = path, dur, src_start, speed
        self.zoom, self.overlays, self.sharpen, self.pre = zoom, overlays, sharpen, pre

    def _frames(self):
        n = round(self.dur * FPS)
        need = self.dur * self.speed + 0.5
        vf = (f"{self.pre}," if self.pre else "") + f"setpts=PTS/{self.speed},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(self.src_start), "-t", str(need), "-i", self.path,
                              "-vf", vf, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        last = None
        for i in range(n):
            buf = p.stdout.read(W * H * 3)
            if len(buf) == W * H * 3:
                last = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            fr = last
            z = lerp(self.zoom[0], self.zoom[1], smooth(i / max(1, n - 1)))
            if z != 1.0:
                M = np.float32([[z, 0, W / 2 * (1 - z)], [0, z, H / 2 * (1 - z)]])
                fr = cv2.warpAffine(fr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            if self.sharpen:
                fr = cv2.addWeighted(fr, 1.5, cv2.GaussianBlur(fr, (0, 0), 2.0), -0.5, 0)
            for ov in self.overlays:
                fr = ov.apply(fr, i / FPS)
            yield fr
        p.stdout.close(); p.wait()


def spaced(d, xy, text, f, fill, spacing, center=False):
    widths = [d.textlength(c, font=f) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if center:
        x -= total / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=f, fill=fill)
        x += w + spacing


class Text:
    """kind: lower (lower third), title, chapter, label."""

    def __init__(self, kind, text, sub=None, t_in=0.4, t_out=None, pos=None):
        self.kind, self.text, self.sub, self.t_in, self.t_out, self.pos = kind, text, sub, t_in, t_out, pos
        self.layer = None

    def render(self):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if self.kind == "lower":
            f1, f2 = font(F_SANS_B, 36), font(F_SERIF_I, 34)
            x, y = 110, H - 215
            shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(shade).rectangle([0, y - 45, 1250, y + 120], fill=(0, 0, 0, 150))
            img = Image.alpha_composite(img, shade.filter(ImageFilter.GaussianBlur(40)))
            d = ImageDraw.Draw(img)
            d.line([(x, y - 14), (x + 70, y - 14)], fill=GOLD + (255,), width=3)
            spaced(d, (x, y), self.text.upper(), f1, IVORY + (255,), 4)
            if self.sub:
                d.text((x, y + 50), self.sub, font=f2, fill=(232, 222, 202, 255))
        elif self.kind == "title":
            spaced(d, (W / 2, H / 2 - 110), self.text, font(F_SERIF, 150), IVORY + (255,), 22, center=True)
            d.line([(W / 2 - 260, H / 2 + 75), (W / 2 + 260, H / 2 + 75)], fill=GOLD + (255,), width=2)
            if self.sub:
                spaced(d, (W / 2, H / 2 + 105), self.sub.upper(), font(F_SANS, 30), (220, 210, 190, 255), 9, center=True)
        elif self.kind == "chapter":
            spaced(d, (W / 2, H / 2 - 70), self.text.upper(), font(F_SANS, 34), GOLD + (255,), 12, center=True)
            spaced(d, (W / 2, H / 2 - 10), self.sub, font(F_SERIF, 96), IVORY + (255,), 4, center=True)
        elif self.kind == "label":
            x, y = self.pos
            f = font(F_SANS_B, 34)
            d.text((x + 2, y + 2), self.text, font=f, fill=(0, 0, 0, 200))
            d.text((x, y), self.text, font=f, fill=IVORY + (255,))
            if self.sub:
                d.text((x + 2, y + 48), self.sub, font=font(F_SERIF_I, 30), fill=(0, 0, 0, 200))
                d.text((x, y + 46), self.sub, font=font(F_SERIF_I, 30), fill=GOLD + (255,))
        return np.asarray(img).astype(np.float32) / 255.0

    def alpha(self, t):
        a = smooth((t - self.t_in) / 0.6)
        if self.t_out is not None:
            a *= 1 - smooth((t - self.t_out) / 0.6)
        return a

    def apply(self, fr, t):
        a = self.alpha(t)
        if a <= 0:
            return fr
        if self.layer is None:
            self.layer = self.render()
        rgb, al = self.layer[..., :3] * 255, self.layer[..., 3:] * a
        return (fr * (1 - al) + rgb * al).astype(np.uint8)


class Fade:
    def __init__(self, t0, t1, out=False):
        self.t0, self.t1, self.out = t0, t1, out

    def apply(self, fr, t):
        u = smooth((t - self.t0) / (self.t1 - self.t0))
        k = (1 - u) if self.out else u
        return (fr.astype(np.float32) * k).astype(np.uint8) if k < 1 else fr


class Black(Shot):
    def __init__(self, dur, overlays=()):
        self.dur, self.overlays = dur, overlays

    def _frames(self):
        base = np.zeros((H, W, 3), np.uint8) + np.array([12, 10, 9], np.uint8)
        for i in range(round(self.dur * FPS)):
            fr = base
            for ov in self.overlays:
                fr = ov.apply(fr, i / FPS)
            yield fr


class Document(Shot):
    """Camera over a scanned page. cam: [(t, cx, cy, zoom)] in page px (zoom = output px per page px).
    highlights: [(t0, t1, [(x0, y0, x1, y1), ...])] wiped in over t0..t1.
    panel: (t0, words, word_times, title) translation revealed word by word in a band along the bottom."""

    def __init__(self, name, dur, cam, highlights=(), panel=None, overlays=()):
        self.name, self.dur, self.cam, self.highlights, self.panel, self.overlays = name, dur, cam, highlights, panel, overlays

    def prepare(self):
        self.page = load_image(self.name, max_w=4000).astype(np.float32)
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        self.gx, self.gy = xs - W / 2, ys - H / 2
        self.panel_font = font(F_SERIF_I, 44)

    def release(self):
        self.page = self.gx = self.gy = None

    def camera(self, t):
        ks = self.cam
        if t <= ks[0][0]:
            return ks[0][1:]
        for a, b in zip(ks, ks[1:]):
            if a[0] <= t <= b[0]:
                u = smooth((t - a[0]) / (b[0] - a[0]))
                return tuple(lerp(x, y, u) for x, y in zip(a[1:], b[1:]))
        return ks[-1][1:]

    def _frames(self):
        n = round(self.dur * FPS)
        ph, pw = self.page.shape[:2]
        tint = np.array([255, 214, 120], np.float32)
        for i in range(n):
            t = i / FPS
            cx, cy, z = self.camera(t)
            mask = np.zeros((ph, pw), np.float32)
            any_hl = 0.0
            for (t0, t1, boxes) in self.highlights:
                if t < t0:
                    continue
                done = min(1.0, (t - t0) / max(0.01, t1 - t0)) * sum(b[2] - b[0] for b in boxes)
                for (x0, y0, x1, y1) in boxes:
                    if done <= 0:
                        break
                    mask[int(y0):int(y1), int(x0):int(x0 + min(x1 - x0, done))] = 1.0
                    done -= x1 - x0
                any_hl = max(any_hl, min(1.0, (t - t0) / 0.8))
            page = self.page
            if any_hl > 0:
                m = cv2.GaussianBlur(mask, (0, 0), 6)[..., None]
                page = (page * (1 - m) + (page * 0.75 + tint * 0.25) * m) * (1 - 0.45 * any_hl * (1 - m))
            s = 1 / z
            fr = cv2.remap(page.astype(np.float32), cx + self.gx * s, cy + self.gy * s, cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(20, 17, 15)).clip(0, 255).astype(np.uint8)
            if self.panel and t >= self.panel[0]:
                fr = self.draw_panel(fr, t)
            for ov in self.overlays:
                fr = ov.apply(fr, t)
            yield fr

    def draw_panel(self, fr, t):
        t0, words, times, title = self.panel
        a = smooth((t - t0) / 0.6)
        img = Image.fromarray(fr).convert("RGBA")
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shade).rectangle([0, 700, W, H], fill=(10, 9, 8, int(225 * a)))
        img = Image.alpha_composite(img, shade.filter(ImageFilter.GaussianBlur(30)))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        f = self.panel_font
        lines, cur, curw = [], [], 0
        for w, wt in zip(words, times):
            ww = d.textlength(w + " ", font=f)
            if cur and curw + ww > 1500:
                lines.append(cur); cur, curw = [], 0
            cur.append((w, wt, ww)); curw += ww
        if cur:
            lines.append(cur)
        y = 790 if len(lines) < 3 else 760
        spaced(d, (W / 2, y - 50), title.upper(), font(F_SANS, 24), (200, 190, 170, int(255 * a)), 6, center=True)
        for ln in lines:
            x = W / 2 - sum(x[2] for x in ln) / 2
            for w, wt, ww in ln:
                wa = smooth((t - wt + 0.15) / 0.35) * a
                if wa > 0:
                    d.text((x, y), w, font=f, fill=IVORY + (int(255 * wa),))
                x += ww
            y += 62
        return np.asarray(Image.alpha_composite(img, layer).convert("RGB"))


class Finisher:
    def __init__(self, seed=3):
        rng = np.random.default_rng(seed)
        self.grain = [cv2.resize(rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32), (W, H))[..., None] for _ in range(12)]
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xs - W / 2) / (W / 2)) ** 2 + ((ys - H / 2) / (H / 2)) ** 2)
        self.vig = (1 - 0.32 * np.clip(r - 0.35, 0, 1) ** 1.6)[..., None].astype(np.float32)
        self.i = 0

    def __call__(self, fr):
        f = fr.astype(np.float32) * np.array([1.025, 1.0, 0.95], np.float32) + np.array([3, 1, -2], np.float32)
        f = 255 * (np.clip(f, 0, 255) / 255) ** 1.04
        f = f * self.vig + self.grain[self.i % len(self.grain)] * 5.0
        self.i += 1
        return np.clip(f, 0, 255).astype(np.uint8)


def render(shots, out_path, xfade=0.6, crf=18):
    """Stream shots to the encoder. Consecutive shots overlap by `xfade` seconds (crossfade) unless the later shot
    has .cut = True. Each shot's .dur must include that overlap (see edl.build)."""
    fin = Finisher()
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                            "-pix_fmt", "yuv420p", out_path], stdin=subprocess.PIPE)
    nx = round(xfade * FPS)
    total = 0

    def write(fr):
        nonlocal total
        enc.stdin.write(fin(fr).tobytes()); total += 1

    tail = deque()
    for shot in shots:
        blend = bool(tail) and not getattr(shot, "cut", False)
        if not blend:
            while tail:
                write(tail.popleft())
        k = len(tail) if blend else 0
        j = 0
        for fr in shot.frames():
            if j < k:
                u = smooth((j + 1) / (k + 1))
                fr = (tail.popleft().astype(np.float32) * (1 - u) + fr.astype(np.float32) * u).astype(np.uint8)
            j += 1
            tail.append(fr)
            if len(tail) > nx:
                write(tail.popleft())
        while len(tail) > nx:
            write(tail.popleft())
    while tail:
        write(tail.popleft())
    enc.stdin.close(); enc.wait()
    return total / FPS
