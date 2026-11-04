"""Animated documentary maps drawn from Natural Earth: dark seas, parchment land, territory sweeps, arrows, labels."""
import json, math, os
import numpy as np
import cv2
from PIL import Image, ImageDraw
from render import W, H, FPS, ASSETS, CACHE, GOLD, IVORY, font, F_SANS_B, F_SERIF_I, smooth, lerp, spaced, Shot

LON0, LON1, LAT0, LAT1 = -15.0, 9.0, 32.0, 50.5
COSL = math.cos(math.radians(40))
PPU = 260.0
CW = int((LON1 - LON0) * COSL * PPU)
CH = int((LAT1 - LAT0) * PPU)
SEA = (19, 30, 36)
LAND = (196, 178, 140)
COAST = (92, 74, 48)
RED = (150, 38, 30)
GREEN = (60, 110, 70)

IBERIA = [(-10.5, 36.5), (-10.5, 44.3), (-1.75, 43.45), (-0.5, 42.85), (1.0, 42.65), (3.4, 42.45), (3.4, 41.9),
          (2.4, 41.2), (1.1, 40.6), (0.4, 39.5), (0.6, 38.6), (-0.2, 37.6), (-1.5, 36.9), (-4.0, 36.4), (-5.3, 35.97),
          (-6.5, 36.2)]
ASTURIAS = [(-9.6, 43.0), (-9.6, 44.2), (-1.5, 43.6), (-1.5, 42.7), (-4.0, 42.75), (-7.0, 42.8)]


def proj(lon, lat):
    return ((lon - LON0) * COSL * PPU, (LAT1 - lat) * PPU)


def _polys(path):
    for f in json.load(open(path))["features"]:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            lons = [p[0] for p in poly[0]]; lats = [p[1] for p in poly[0]]
            if max(lons) < LON0 - 2 or min(lons) > LON1 + 2 or max(lats) < LAT0 - 2 or min(lats) > LAT1 + 2:
                continue
            yield poly


def base_canvas():
    key = os.path.join(CACHE, "map_base.npz")
    if os.path.exists(key):
        z = np.load(key)
        return z["rgb"], z["land"]
    land = Image.new("L", (CW, CH), 0)
    dl = ImageDraw.Draw(land)
    for poly in _polys(os.path.join(ASSETS, "geo/ne_10m_land.geojson")):
        dl.polygon([proj(*p) for p in poly[0]], fill=255)
        for hole in poly[1:]:
            dl.polygon([proj(*p) for p in hole], fill=0)
    landa = np.asarray(land).astype(np.float32) / 255
    rng = np.random.default_rng(5)
    noise = cv2.resize(cv2.GaussianBlur(rng.normal(0, 1, (CH // 8, CW // 8)).astype(np.float32), (0, 0), 2), (CW, CH))[..., None]
    fine = rng.normal(0, 1, (CH, CW, 1)).astype(np.float32)
    ys = np.linspace(0, 1, CH, dtype=np.float32)[:, None, None]
    sea = np.array(SEA, np.float32) * (1.08 - 0.16 * ys) + noise * 3
    sea = sea + cv2.GaussianBlur(landa, (0, 0), 25)[..., None] * np.array([14, 22, 24], np.float32)
    lnd = (np.array(LAND, np.float32) + noise * 10 + fine * 4) * (0.82 + 0.18 * cv2.GaussianBlur(landa, (0, 0), 18)[..., None])
    a = cv2.GaussianBlur(landa, (0, 0), 1.0)[..., None]
    rgb = sea * (1 - a) + lnd * a
    edge = cv2.GaussianBlur(cv2.morphologyEx((landa > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((5, 5), np.uint8)).astype(np.float32), (0, 0), 1.2)[..., None]
    rgb = rgb * (1 - 0.85 * edge) + np.array(COAST, np.float32) * 0.85 * edge
    riv = Image.new("L", (CW, CH), 0); dr = ImageDraw.Draw(riv)
    for f in json.load(open(os.path.join(ASSETS, "geo/ne_10m_rivers.geojson")))["features"]:
        g = f["geometry"]
        if not g:
            continue
        for ln in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            if LON0 <= ln[0][0] <= LON1 and LAT0 <= ln[0][1] <= LAT1:
                dr.line([proj(*p[:2]) for p in ln], fill=255, width=3)
    rv = cv2.GaussianBlur(np.asarray(riv).astype(np.float32) / 255, (0, 0), 0.8)[..., None] * a
    rgb = np.clip(rgb * (1 - 0.5 * rv) + np.array([80, 104, 112], np.float32) * 0.5 * rv, 0, 255).astype(np.uint8)
    np.savez(key, rgb=rgb, land=(landa * 255).astype(np.uint8))
    return rgb, (landa * 255).astype(np.uint8)


def poly_mask(pts, scale):
    m = Image.new("L", (int(CW * scale), int(CH * scale)), 0)
    ImageDraw.Draw(m).polygon([(x * scale, y * scale) for x, y in (proj(*p) for p in pts)], fill=255)
    return np.asarray(m).astype(np.float32) / 255


def catmull(pts, n=60):
    pts = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = map(np.array, pts[i - 1:i + 3])
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(np.array(pts[-2]))
    return out


class MapShot(Shot):
    """cam: [(t, lon, lat, span_deg_lon)].
    sweep: (t0, t1, lat_from, lat_to, color, fill_mask) territory filled as a frontier moves north or south;
           fill_mask is 'iberia', 'iberia_minus_asturias' or a list of polygons; lat_to < lat_from sweeps south.
    asturias_t: time to highlight the Asturian refuge. arrows: [(t0, t1, [(lon, lat), ...], rgb)].
    labels: [(t_in, lon, lat, text, sub[, t_out])]. markers: [(t, lon, lat)] (battle marks)."""

    def __init__(self, dur, cam, sweeps=(), asturias_t=None, arrows=(), labels=(), markers=(), overlays=(), base_fill=None):
        self.dur, self.cam, self.sweeps, self.asturias_t = dur, cam, sweeps, asturias_t
        self.arrows, self.labels, self.markers, self.overlays, self.base_fill = arrows, labels, markers, overlays, base_fill

    def prepare(self):
        self.rgb, self.land = base_canvas()
        self.ms = 0.25
        lm = cv2.resize(self.land, (int(CW * self.ms), int(CH * self.ms)), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        self.iberia = lm * poly_mask(IBERIA, self.ms)
        self.astur = self.iberia * poly_mask(ASTURIAS, self.ms)
        self.lm = lm
        self.lat_rows = LAT1 - np.arange(self.iberia.shape[0], dtype=np.float32) / (PPU * self.ms)

    def release(self):
        self.rgb = self.land = self.iberia = self.astur = self.lm = None

    def region(self, which):
        if which == "iberia":
            return self.iberia
        if which == "iberia_minus_asturias":
            return self.iberia * (1 - self.astur)
        m = np.zeros_like(self.iberia)
        for poly in which:
            m = np.maximum(m, poly_mask(poly, self.ms))
        return m * self.lm

    def camera(self, t):
        ks = self.cam
        if t <= ks[0][0]:
            lon, lat, span = ks[0][1:]
        elif t >= ks[-1][0]:
            lon, lat, span = ks[-1][1:]
        else:
            for a, b in zip(ks, ks[1:]):
                if a[0] <= t <= b[0]:
                    u = smooth((t - a[0]) / (b[0] - a[0]))
                    lon, lat, span = lerp(a[1], b[1], u), lerp(a[2], b[2], u), math.exp(lerp(math.log(a[3]), math.log(b[3]), u))
                    break
        cx, cy = proj(lon, lat)
        return cx, cy, W / (span * COSL * PPU)

    def to_screen(self, lon, lat, cam):
        cx, cy, z = cam
        x, y = proj(lon, lat)
        return (x - cx) * z + W / 2, (y - cy) * z + H / 2

    def _overlay_region(self, fr, M, mask, color, alpha=0.5, edge_col=(120, 20, 15)):
        Ms = M.copy(); Ms[:, :2] /= self.ms
        tm = cv2.warpAffine(mask, Ms, (W, H), flags=cv2.INTER_LINEAR)[..., None]
        fr = fr * (1 - alpha * tm) + np.array(color, np.float32) * alpha * tm
        edge = cv2.morphologyEx((tm[..., 0] > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        fr[edge > 0] = fr[edge > 0] * 0.4 + np.array(edge_col) * 0.6
        return fr

    def _frames(self):
        n = round(self.dur * FPS)
        regions = {}
        for i in range(n):
            t = i / FPS
            cam = self.camera(t)
            cx, cy, z = cam
            M = np.float32([[z, 0, W / 2 - cx * z], [0, z, H / 2 - cy * z]])
            fr = cv2.warpAffine(self.rgb, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=SEA).astype(np.float32)
            if self.base_fill:
                which, color = self.base_fill
                key = ("base", str(which))
                regions.setdefault(key, self.region(which))
                fr = self._overlay_region(fr, M, regions[key], color)
            for si, (t0, t1, lat_from, lat_to, color, which) in enumerate(self.sweeps):
                if t < t0:
                    continue
                key = (si, str(which))
                regions.setdefault(key, self.region(which))
                u = smooth((t - t0) / (t1 - t0))
                front = lerp(lat_from, lat_to, u)
                if lat_to >= lat_from:
                    soft = np.clip((front - self.lat_rows) / 0.35, 0, 1)[:, None]
                else:
                    soft = np.clip((self.lat_rows - front) / 0.35, 0, 1)[:, None]
                mask = regions[key] * soft
                if mask.any():
                    fr = self._overlay_region(fr, M, mask, color, edge_col=tuple(int(c * 0.8) for c in color))
            if self.asturias_t is not None and t >= self.asturias_t:
                a = (0.5 + 0.25 * math.sin((t - self.asturias_t) * 3.0)) * smooth((t - self.asturias_t) / 0.8)
                Ms = M.copy(); Ms[:, :2] /= self.ms
                am = cv2.warpAffine(self.astur, Ms, (W, H), flags=cv2.INTER_LINEAR)[..., None]
                fr = fr * (1 - 0.45 * am * a) + np.array([235, 205, 120], np.float32) * 0.45 * am * a
            img = Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8)).convert("RGBA")
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            for (t0, t1, pts, color) in self.arrows:
                if t < t0:
                    continue
                u = smooth((t - t0) / (t1 - t0))
                path = [self.to_screen(lo, la, cam) for lo, la in catmull(pts)]
                seg = path[:max(2, int(len(path) * u))]
                for wdt, col in ((16, (0, 0, 0, 120)), (9, color + (255,))):
                    d.line(seg, fill=col, width=wdt, joint="curve")
                (x1, y1), (x0, y0) = seg[-1], seg[-2]
                ang = math.atan2(y1 - y0, x1 - x0)
                d.polygon([(x1 + 28 * math.cos(ang), y1 + 28 * math.sin(ang)), (x1 + 20 * math.cos(ang + 2.4), y1 + 20 * math.sin(ang + 2.4)),
                           (x1 + 20 * math.cos(ang - 2.4), y1 + 20 * math.sin(ang - 2.4))], fill=color + (255,), outline=(0, 0, 0, 160))
            for (tm_, lo, la) in self.markers:
                if t < tm_:
                    continue
                a = smooth((t - tm_) / 0.5)
                x, y = self.to_screen(lo, la, cam)
                r = 18 + 10 * (1 - a)
                d.ellipse([x - r, y - r, x + r, y + r], outline=(240, 220, 170, int(255 * a)), width=4)
                for s in (-1, 1):
                    d.line([(x - 10, y - 10 * s), (x + 10, y + 10 * s)], fill=(240, 220, 170, int(255 * a)), width=4)
            for lab in self.labels:
                t_in, lo, la, text, sub = lab[:5]
                t_out = lab[5] if len(lab) > 5 else None
                a = smooth((t - t_in) / 0.6)
                if t_out is not None:
                    a *= 1 - smooth((t - t_out) / 0.6)
                if a <= 0:
                    continue
                x, y = self.to_screen(lo, la, cam)
                d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(240, 228, 200, int(255 * a)), outline=(0, 0, 0, int(200 * a)))
                f = font(F_SANS_B, 38)
                for dx, dy, col in ((2, 2, (0, 0, 0, int(210 * a))), (0, 0, IVORY + (int(255 * a),))):
                    spaced(d, (x + 18 + dx, y - 22 + dy), text.upper(), f, col, 3)
                if sub:
                    for dx, dy, col in ((2, 2, (0, 0, 0, int(210 * a))), (0, 0, GOLD + (int(255 * a),))):
                        d.text((x + 18 + dx, y + 20 + dy), sub, font=font(F_SERIF_I, 34), fill=col)
            fr = np.asarray(Image.alpha_composite(img, layer).convert("RGB"))
            for ov in self.overlays:
                fr = ov.apply(fr, t)
            yield fr
