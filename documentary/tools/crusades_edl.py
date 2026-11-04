"""Edit decision list for The Crusades. Builds the narration timeline, the shot list, music cues and subtitles.

usage: crusades_edl.py [--check | --audio-only]
Requires: narration_crusades/manifest.json with word timings (tools/transcribe.py), assets from assets_crusades.json.
"""
import json, os, re, sys
import numpy as np
import soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import W, H, DOC, ASSETS, Still, Footage, Text, Fade, Black, Document, render
import maps
from maps import MapShot
from textnorm import norm
from credits_roll import roll_shot
import ia_find

maps.use_region("mediterranean")
XF = 0.6
NAR = os.path.join(DOC, "narration_crusades")
OUT = os.path.join(DOC, "out", "crusades"); os.makedirs(OUT, exist_ok=True)
RED, GREEN = (150, 38, 30), (60, 110, 70)
VID = lambda f: os.path.join(ASSETS, "video", f)

# ------------------------------------------------------------------ timeline
man = json.load(open(os.path.join(NAR, "manifest.json")))
SR = sf.info(man[0]["wav"]).samplerate
LEAD, GAP, QUOTE_PAD, TITLE, CHAPTER, TAIL = 2.0, 0.9, 0.6, 4.6, 3.2, 6.0
t, chapters = LEAD, {}
for i, p in enumerate(man):
    if p["section"] and p["n"] > 1:
        if p["n"] == 3:  # title card follows the cold open, then the first chapter card
            p["title_at"] = t
            t += TITLE
        chapters[p["n"]] = (t, p["section"])
        t += CHAPTER
    if p["quote"]:
        t += QUOTE_PAD
    p["start"] = t
    t += p["dur"] + (QUOTE_PAD if p["quote"] else 0) + GAP
END = t - GAP + TAIL  # end of the narrated film; the credits roll follows
ROLL, ROLL_SHOT = roll_shot(os.path.join(DOC, "assets_crusades.json"), "The Crusades", "crusades")
TOTAL = END + ROLL
P = {p["n"]: p for p in man}
T_TITLE = P[3]["title_at"]

if __name__ == "__main__":
    nar = np.zeros(int(TOTAL * SR), np.float32)
    for p in man:
        a, _ = sf.read(p["wav"], dtype="float32")
        i = int(p["start"] * SR); nar[i:i + len(a)] += a
    sf.write(os.path.join(OUT, "narration.wav"), nar, SR)
    json.dump([{k: p[k] for k in ("n", "text", "start", "dur", "words")} for p in man], open(os.path.join(OUT, "timeline.json"), "w"))


def at(n, word, k=1, end=False, prefix=False):
    """Global time of the k-th script word in paragraph n equal to `word` (or starting with it, if prefix)."""
    target = norm(word)
    hits = [w for w in P[n]["words"] if (norm(w[0]).startswith(target) if prefix else norm(w[0]) == target)]
    if len(hits) < k:
        raise KeyError(f"paragraph {n} has no occurrence {k} of {word!r}")
    w = hits[k - 1]
    return P[n]["start"] + (w[2] if end else w[1])


def ps(n): return P[n]["start"]
def pe(n): return P[n]["start"] + P[n]["dur"]


def words_of(n):
    return [(w[0], P[n]["start"] + w[1]) for w in P[n]["words"]]


# ------------------------------------------------------------------ helpers
def autocrop(name, thresh=22, paper_probe=False, m=0.008):
    from PIL import Image
    a = np.asarray(Image.open(os.path.join(ASSETS, name)).convert("L")).astype(np.float32)
    h, w = a.shape
    if paper_probe:  # book plates: sample the paper above the engraving, not the scanner edge
        edge = np.median(a[int(h * 0.02):int(h * 0.06), int(w * 0.3):int(w * 0.7)])
    else:
        edge = np.median(np.concatenate([a[:8].ravel(), a[-8:].ravel(), a[:, :8].ravel(), a[:, -8:].ravel()]))
    rows = np.where(np.abs(a - edge).mean(1) > thresh)[0]
    cols = np.where(np.abs(a - edge).mean(0) > thresh)[0]
    return (cols[0] / w + m, rows[0] / h + m, cols[-1] / w - m, rows[-1] / h - m)


def photo(name, d, **kw):
    """LOC photochroms carry a grey border and Doré plates a printed page: trim them unless a crop is given."""
    if "crop" not in kw and name.startswith("loc/"):
        kw["crop"] = autocrop(name)
    if "crop" not in kw and name.startswith("dore/"):
        kw["crop"] = autocrop(name, paper_probe=True, m=0.012)
        kw.setdefault("tone", "sepia")
    return Still(name, d, **kw)


def lower(text, sub, t_in=0.6, t_out=None):
    return Text("lower", text, sub, t_in=t_in, t_out=t_out)


def dore(name, d, plate, title, t_in=0.6, **kw):
    kw.setdefault("parallax", 0.08)
    kw.setdefault("end", (0.5, 0.48, 1.14))
    return photo(f"dore/{name}.jpg", d, overlays=[lower(title, f"Plate {plate}  ·  engraving after Gustave Doré, 1877", t_in)] + kw.pop("overlays", []), **kw)


def doc_lines(ident, leaf, image, start_pat, end_pat, pad=10):
    """Line boxes (image px) covering the words from start_pat through end_pat on one scanned page."""
    from PIL import Image
    pw, ph, raw = ia_find.pages(ident)[leaf]
    iw, ih = Image.open(os.path.join(ASSETS, image)).size
    words = []  # OCR entries sometimes hold several words; split them and share out the box by character count
    for text, x0, y0, x1, y1 in raw:
        parts = text.split()
        total = sum(len(t) for t in parts) or 1
        x = x0
        for t in parts:
            xe = x + (x1 - x0) * len(t) / total
            words.append((t, x, y0, xe, y1)); x = xe
    sx, sy = iw / pw, ih / ph
    toks, spans, k = [], [], 0
    while k < len(words):
        t, j = words[k][0], k
        while t.endswith("-") and j + 1 < len(words):
            j += 1; t = t[:-1] + words[j][0]
        toks.append(norm(t)); spans.append((k, j)); k = j + 1
    def find(pat, frm=0):
        seq = [norm(x) for x in pat.split()]
        for i in range(frm, len(toks) - len(seq) + 1):
            if toks[i:i + len(seq)] == seq:
                return i, i + len(seq) - 1
        raise KeyError(f"{pat!r} not found on leaf {leaf}")
    a, _ = find(start_pat)
    _, b = find(end_pat, a)
    i0, i1 = spans[a][0], spans[b][1]
    lines = []
    for w in words[i0:i1 + 1]:
        _, x0, y0, x1, y1 = w
        if lines and abs(lines[-1][1] - y0) < (y1 - y0) * 0.6:
            l = lines[-1]; lines[-1] = [min(l[0], x0), min(l[1], y0), max(l[2], x1), max(l[3], y1)]
        else:
            lines.append([x0, y0, x1, y1])
    left = min(l[0] for l in lines)
    lines = [lines[0]] + [[left] + l[1:] for l in lines[1:]]
    return [(x0 * sx - pad, y0 * sy - pad, x1 * sx + pad, y1 * sy + pad) for x0, y0, x1, y1 in lines]


def doc_cam(image, boxes, t_zoom, t_end, width=1500):
    """Open on the whole page, then settle on the passage, kept above the translation band."""
    from PIL import Image
    pw, ph = Image.open(os.path.join(ASSETS, image)).size
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    z0 = min(W / pw, H / ph) * 1.55
    z1 = min(1.3, width / (x1 - x0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + (H / 2 - 360) / z1
    return [(0, pw / 2, min(ph / 2, cy + 300), z0), (t_zoom, cx, cy, z1), (t_end, cx, cy - 20 / z1, z1 * 1.04)]


# ------------------------------------------------------------------ map geometry (lon, lat)
CITY = dict(Jerusalem=(35.23, 31.78), Bethlehem=(35.20, 31.70), Nazareth=(35.30, 32.70), Antioch=(36.16, 36.20), Alexandria=(29.92, 31.20),
            Carthage=(10.32, 36.85), Constantinople=(28.98, 41.01), Rome=(12.48, 41.90), Medina=(39.61, 24.47), Damascus=(36.29, 33.51),
            Yarmouk=(35.95, 32.75), Palermo=(13.36, 38.12), Manzikert=(42.53, 39.14), Nicaea=(29.72, 40.43), Ramla=(34.87, 31.93),
            Piacenza=(9.69, 45.05), Clermont=(3.08, 45.78), Speyer=(8.43, 49.32), Worms=(8.36, 49.63), Mainz=(8.27, 50.00),
            Dorylaeum=(30.52, 39.78), Edessa=(38.79, 37.16), Acre=(35.07, 32.93), Hattin=(35.45, 32.80), Arsuf=(34.81, 32.20),
            Jaffa=(34.75, 32.05), Zara=(15.23, 44.12), Venice=(12.33, 45.44), Lepanto=(21.10, 38.25), Vienna=(16.37, 48.21),
            Belgrade=(20.46, 44.82), Mohacs=(18.68, 45.99), Civetot=(29.35, 40.62), Heraclea=(34.05, 37.50), Toledo=(-4.02, 39.86),
            Cologne=(6.96, 50.94), Ostia=(12.29, 41.73))
C = lambda name: CITY[name]
ROMAN_600 = [(-10, 36), (-10, 44), (-1.8, 43.4), (-4.5, 48.7), (2, 51.2), (6, 51.2), (7.5, 49.5), (8.5, 47.6), (16, 48.3), (19, 45), (22.5, 44.2),
             (28.5, 44.4), (29.5, 45.3), (41.5, 41.5), (44, 40), (44, 37.4), (38.5, 37.3), (40, 35), (38, 31), (35, 29.4), (33.8, 27.5),
             (32.9, 24.0), (32.3, 23.0), (31.5, 23.0), (30.8, 24.5), (30.2, 27.5), (29.0, 29.5), (24.9, 29.8), (20, 29.6), (15, 30.3),
             (10, 31.5), (5, 32.3), (0, 32.2), (-5, 30.5), (-10, 29.5)]
ARABIA = [(34.9, 29.4), (37.0, 29.3), (46, 29), (46, 23), (38.5, 23), (36, 26.5)]
SYRIA = [(34.2, 31.0), (34.9, 33.3), (35.8, 35.5), (35.9, 36.9), (38.5, 37.3), (42.5, 37.3), (46, 35.5), (46, 29), (37, 29.3), (34.9, 29.4)]
EGYPT = [(24.9, 31.7), (29, 31.3), (32.3, 31.3), (34.3, 31.3), (34.9, 29.4), (33.8, 27.5), (32.9, 24.0), (32.3, 23.0), (31.5, 23.0),
         (30.8, 24.5), (30.2, 27.5), (29.0, 29.5), (24.9, 29.8)]
MAGHREB = [(-9.8, 33.0), (-6.5, 35.8), (-5.3, 35.95), (-1, 35.9), (3, 36.9), (9, 37.4), (11.2, 37.2), (11.2, 33.5), (15, 32.4), (20, 31),
           (24.9, 31.7), (24.9, 29.8), (20, 29.6), (15, 30.3), (10, 31.5), (5, 32.3), (0, 32.2), (-5, 30.5), (-9.8, 29.5)]
SICILY = [(12.3, 38.4), (15.7, 38.4), (15.7, 36.6), (12.3, 36.6)]
ANATOLIA = [(26, 40.3), (26.5, 38), (27.5, 36.6), (30, 36.2), (32.5, 36.1), (36, 36.6), (36.2, 37), (38.5, 37.2), (42, 37.2), (44.5, 38.5),
            (44.5, 41), (41.5, 41.6), (36, 42.1), (31, 41.3), (29.5, 41.2), (29.1, 40.9)]
BYZ_BALKANS = [(19.3, 42), (20, 39.5), (21, 36.3), (24, 36.8), (26.5, 40.2), (29.1, 41.1), (28.5, 42), (28.2, 44), (22.5, 44.4), (19.5, 44)]
EDESSA_C = [(37.0, 37.9), (38.0, 38.2), (39.6, 37.9), (40.2, 37.2), (39.3, 36.4), (38.0, 36.4), (37.2, 36.9)]
ANTIOCH_P = [(35.6, 35.4), (35.9, 36.7), (36.2, 37.1), (37.0, 37.3), (37.2, 36.4), (36.6, 35.6), (36.1, 35.1)]
TRIPOLI_C = [(35.5, 34.2), (35.8, 35.3), (36.4, 35.1), (36.4, 34.4), (35.9, 34.0)]
JERUSALEM_K = [(34.0, 31.2), (34.8, 33.0), (35.2, 33.6), (35.5, 34.2), (35.95, 34.0), (35.9, 33.2), (36.2, 32.4), (35.9, 31.2), (35.5, 30.3),
               (35.0, 29.4), (34.6, 29.6), (34.6, 30.6)]
COAST_1268 = [(34.6, 31.6), (34.8, 33.0), (35.2, 33.6), (35.5, 34.2), (35.85, 34.5), (36.05, 34.2), (35.4, 33.2), (35.3, 32.5), (35.0, 31.7)]
BALKANS_HUN = [(19.3, 42), (20, 39.5), (21, 36.3), (24, 36.8), (26.5, 40.2), (29.1, 41.1), (28.5, 42), (29.5, 45.3), (27, 48.2), (22.5, 48.6),
               (17.5, 47.9), (16.2, 46.4), (15.5, 45.1), (16.5, 43.5)]
CRUSADER_STATES = [EDESSA_C, ANTIOCH_P, TRIPOLI_C, JERUSALEM_K]


def lab(t, name, sub=None, t_out=None, text=None):
    lo, la = C(name)
    return (t, lo, la, text or name, sub) + ((t_out,) if t_out is not None else ())


def mark(t, name):
    return (t, *C(name))


# ------------------------------------------------------------------ shot list: (start time, factory(duration))
S = []
def shot(t0, f): S.append((t0, f))

STEREO = (0.11, 0.12, 0.485, 0.80)     # left frame of a stereograph card
JAFFA_1897 = "crop=1360:1020:281:30"   # the Lumière film sits in a pillarbox
J1918 = "crop=620:474:17:2"

# COLD OPEN
shot(0.0, lambda d: Footage(VID("jaffa_gate_1897.mkv"), d, src_start=1.0, speed=0.9, zoom=(1.02, 1.08), pre=JAFFA_1897, sharpen=True,
                            overlays=[Fade(0, 1.8), lower("Jerusalem, April 1897", "The Jaffa Gate  ·  film by Alexandre Promio for the Lumière company", 2.2)]))
shot(at(1, "Church") - 0.3, lambda d: photo("loc/holy_sepulchre_front.jpg", d, start=(0.5, 0.55, 1.0), end=(0.5, 0.45, 1.15), parallax=0.10,
                                            overlays=[lower("The Church of the Holy Sepulchre", "Jerusalem  ·  photochrom, about 1890–1900", 0.8)]))
shot(at(1, "crucified") - 0.2, lambda d: photo("loc/holy_sepulchre_interior.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.45, 1.0), parallax=0.10,
                                               overlays=[lower("The Edicule", "The shrine over the tomb, Church of the Holy Sepulchre", 0.6)]))
shot(at(1, "For"), lambda d: dore("caesarea_massacre", d, "XXXIII", "Crusaders massacring the inhabitants of Caesarea, 1101", 0.8))
shot(ps(2) - 0.2, lambda d: dore("war_cry", d, "V", "The war cry of the crusaders", 1.0))
shot(at(2, "appeal"), lambda d: Still("cma/byzantine_processional_cross.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.05,
                                      overlays=[lower("Byzantine processional cross", "About 1050  ·  Cleveland Museum of Art", 0.5)]))
shot(at(2, "loss"), lambda d: Footage(VID("jerusalem_1918.mp4"), d, src_start=13.0, zoom=(1.0, 1.06), pre=J1918, sharpen=True,
                                      overlays=[lower("Jerusalem, 1918", "Amateur film", 0.5)]))
shot(T_TITLE, lambda d: photo("loc/jerusalem_general_view.jpg", d, start=(0.5, 0.45, 1.0), end=(0.5, 0.42, 1.10), parallax=0.12,
                              overlays=[Text("title", "THE CRUSADES", "The long war for the Holy Land", t_in=0.5, t_out=TITLE - 0.6)]))
CUTS = set()
for n, (tc, sec) in chapters.items():
    part, _, name = sec.partition(":")
    label, title = (part.strip().title(), name.strip().title()) if name else ("", part.strip().title())
    title = re.sub(r"\b(Of|The|And|To|A)\b", lambda m: m.group(1).lower(), title)
    title = title[0].upper() + title[1:]
    shot(tc, (lambda lb, tt: lambda d: Black(d, overlays=[Text("chapter", lb, tt, t_in=0.3, t_out=CHAPTER - 0.7)]))(label, title))
    CUTS.add(tc)

# PART ONE: THE LONG CONQUEST
r3 = lambda x: x - ps(3)
shot(ps(3), lambda d: MapShot(d, cam=[(0, 17.0, 37.5, 48.0), (r3(at(3, "Jerusalem")) - 0.3, 34.9, 32.2, 4.0), (d, 35.0, 32.25, 3.4)],
                              base_fill=([ROMAN_600], GREEN),
                              labels=[lab(r3(at(3, "Jerusalem")), "Jerusalem"), lab(r3(at(3, "Bethlehem")), "Bethlehem", text="Bethlehem"),
                                      lab(r3(at(3, "Nazareth")), "Nazareth"), (1.0, 4.5, 40.6, "The Christian world", "about 600", r3(at(3, "Jerusalem")) - 1.0)]))
shot(at(3, "Antioch"), lambda d: Still("loc/antioch_1881.jpg", d, crop=STEREO, end=(0.5, 0.48, 1.14), parallax=0.10, tone="sepia",
                                       overlays=[lower("Antioch", "Stereograph, 1881  ·  Library of Congress", 0.6)]))
shot(at(3, "Alexandria"), lambda d: photo("loc/alexandria_pompeys_pillar.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08,
                                          overlays=[lower("Alexandria", "The Roman column called Pompey's Pillar  ·  photochrom, about 1890–1900", 0.5)]))
shot(at(3, "Carthage"), lambda d: Still("cma/augustine_initial.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.05,
                                        overlays=[lower("Saint Augustine", "Initial from a gradual, about 1420  ·  Cleveland Museum of Art", 0.5)]))
r4 = lambda x: x - ps(4)
shot(ps(4) - 0.2, lambda d: MapShot(d, cam=[(0, 38.0, 29.5, 22.0), (r4(at(4, "Yarmouk")), 36.5, 31.5, 15.0), (d, 35.5, 32.0, 12.0)],
                                    base_fill=([ROMAN_600], GREEN),
                                    sweeps=[(r4(at(4, "Arabia")) - 0.4, r4(at(4, "Arabia")) + 1.6, 23.0, 30.0, RED, [ARABIA]),
                                            (r4(at(4, "Yarmouk")), r4(at(4, "Jerusalem")) + 1.0, 29.0, 37.5, RED, [SYRIA])],
                                    markers=[mark(r4(at(4, "Yarmouk")), "Yarmouk")],
                                    labels=[lab(r4(at(4, "Muhammad")), "Medina", "632"), lab(r4(at(4, "Yarmouk")), "Yarmouk", "636"),
                                            lab(r4(at(4, "Jerusalem")), "Jerusalem", "637")]))
shot(at(4, "Jerusalem") + 1.2, lambda d: Footage(VID("levy_1933.mp4"), d, src_start=528.0, zoom=(1.0, 1.06), sharpen=True,
                                                 overlays=[lower("Jerusalem, 1933", "The Dome of the Rock, built on the Temple Mount in 691", 0.4)]))
shot(at(4, "Egypt") - 0.2, lambda d: MapShot(d, cam=[(0, 27.0, 31.0, 26.0), (r4(at(4, "Spain")) - (at(4, "Egypt") - 0.2 - ps(4)), 6.0, 36.5, 40.0),
                                                     (d, 11.0, 39.5, 22.0)],
                                             base_fill=([ROMAN_600], GREEN),
                                             sweeps=[(-1, 0, 0, 90, RED, [ARABIA, SYRIA]),
                                                     (0.3, 2.2, 35.0, 24.8, RED, [EGYPT], "lon"),
                                                     (1.2, at(4, "Carthage") - at(4, "Egypt") + 1.8, 25.0, -10.0, RED, [MAGHREB], "lon"),
                                                     (at(4, "Spain") - at(4, "Egypt"), at(4, "Spain") - at(4, "Egypt") + 2.2, 35.8, 43.9, RED, "iberia_minus_asturias"),
                                                     (at(4, "Sicily") - at(4, "Egypt"), at(4, "Sicily") - at(4, "Egypt") + 1.2, 36.5, 38.4, RED, [SICILY])],
                                             arrows=[(at(4, "raiding") - at(4, "Egypt"), at(4, "Tiber") - at(4, "Egypt") + 0.6,
                                                      [C("Palermo"), (12.2, 39.8), (11.9, 41.2), C("Ostia")], RED)],
                                             labels=[lab(at(4, "Egypt") - at(4, "Egypt") + 0.4, "Alexandria", "642"),
                                                     lab(at(4, "Carthage") - at(4, "Egypt"), "Carthage", "698"),
                                                     (at(4, "Spain") - at(4, "Egypt"), -4.0, 40.0, "Spain", "711"),
                                                     lab(at(4, "Tiber") - at(4, "Egypt"), "Rome", "846")]))
shot(at(4, "sacked"), lambda d: photo("loc/rome_st_paul_cloister.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08,
                                      overlays=[lower("Saint Paul Outside the Walls, Rome", "The basilica was plundered by Arab raiders in 846  ·  its cloister, about 1890", 0.4)]))
shot(ps(5) - 0.2, lambda d: Footage(VID("jerusalem_1918.mp4"), d, src_start=170.0, zoom=(1.0, 1.05), pre=J1918, sharpen=True,
                                    overlays=[lower("Jerusalem, 1918", "The Old City  ·  amateur film", 0.6)]))
shot(at(5, "dhimmi"), lambda d: photo("loc/damascus_street_called_straight.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                      overlays=[lower("Damascus", "The Street Called Straight  ·  photochrom, about 1890–1900", 0.5)]))
shot(ps(6) - 0.2, lambda d: Still("cma/tiraz_al_hakim_1009.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.5, 1.2), parallax=0.04,
                                  overlays=[lower("Silk woven in the reign of al-Hakim", "Egypt, 1008–09, the year of his order  ·  Cleveland Museum of Art", 0.6)]))
shot(at(6, "His"), lambda d: photo("loc/roberts_holy_sepulchre.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08, tone="sepia",
                                   overlays=[lower("The Church of the Holy Sepulchre", "Lithograph after David Roberts, 1842", 0.5)]))
shot(ps(7) - 0.2, lambda d: dore("holy_sepulchre", d, "I", "The Holy Sepulchre", 0.5, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.18)))

# PART TWO: THE CALL
shot(ps(8), lambda d: photo("loc/hagia_sophia_1890.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                            overlays=[lower("Hagia Sophia, Constantinople", "Built as the cathedral of the Byzantine capital in 537  ·  photochrom, about 1890", 0.8)]))
T8 = at(8, "1071") - 0.4
r8 = lambda x: x - T8
shot(T8, lambda d: MapShot(d, cam=[(0, 34.0, 39.5, 20.0), (r8(at(8, "Manzikert")), 38.0, 39.4, 15.0), (r8(ps(9)), 36.0, 39.6, 16.0),
                                            (r8(at(9, "Nicaea")), 30.4, 40.6, 7.5), (d, 30.0, 40.7, 6.5)],
                                    base_fill=([ANATOLIA, BYZ_BALKANS], GREEN),
                                    sweeps=[(r8(ps(9)), r8(at(9, "Anatolia", end=True)) + 1.0, 44.5, 29.3, RED, [ANATOLIA], "lon")],
                                    markers=[mark(r8(at(8, "Manzikert")), "Manzikert")],
                                    labels=[(0.5, 32.0, 41.6, "Byzantine Empire", None, r8(ps(9))), lab(r8(at(8, "Manzikert")), "Manzikert", "1071"),
                                            lab(r8(at(9, "Nicaea")), "Nicaea", "Seljuk capital"), lab(r8(at(9, "Constantinople")), "Constantinople")]))
shot(ps(10) - 0.2, lambda d: photo("loc/jaffa_from_sea.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Jaffa", "The pilgrims' port for Jerusalem  ·  photochrom, about 1890", 0.8)]))
shot(at(10, "German") - 0.2, lambda d: dore("pilgrims", d, "II", "Pilgrims on the road", 0.5))
shot(at(10, "Ramla") - 0.2, lambda d: photo("loc/ramleh_tower_1867.jpg", d, end=(0.5, 0.42, 1.14), parallax=0.10, tone="sepia",
                                            overlays=[lower("Ramla", "Photographed in 1867", 0.5)]))
r11 = lambda x: x - ps(11)
shot(ps(11) - 0.2, lambda d: MapShot(d, cam=[(0, 22.0, 42.5, 24.0), (d, 15.0, 44.0, 18.0)],
                                     arrows=[(r11(at(11, "envoys")) + 0.2, r11(at(11, "Second", end=True)) + 0.4, [C("Constantinople"), (23.0, 40.5), (19.0, 41.5), (13.0, 44.2), C("Piacenza")], GREEN)],
                                     labels=[lab(0.8, "Constantinople"), lab(r11(at(11, "Piacenza")), "Piacenza", "March 1095")]))
shot(at(11, "Council"), lambda d: photo("loc/piacenza_cathedral.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                        overlays=[lower("Piacenza", "The cathedral, begun in 1122  ·  photograph, about 1900", 0.5)]))
BERNOLD = [(1888, 1198, 2162, 1255), (228, 1254, 2163, 1314), (227, 1312, 2162, 1373), (228, 1376, 1111, 1432)]
r12 = lambda x: x - at(11, "Bernold") + 0.3
shot(at(11, "Bernold") - 0.3, lambda d: Document("docs/bernold_1095_p462.jpg", d,
    cam=doc_cam("docs/bernold_1095_p462.jpg", BERNOLD, r12(ps(12)), r12(pe(12)) + 0.9),
    highlights=[(r12(ps(12)), r12(pe(12)), BERNOLD)],
    panel=(r12(ps(12)), [w for w, _ in words_of(12)], [r12(tt) for _, tt in words_of(12)], "Bernold of Constance, Chronicle, 1095  ·  English translation"),
    overlays=[lower("Bernold of Constance, Chronicle", "Year 1095  ·  Latin text, Monumenta Germaniae Historica (1844)", 0.8, r12(ps(12)) - 0.6)]))
shot(ps(13) - 0.2, lambda d: photo("loc/puy_de_dome.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Clermont, Auvergne", "The Puy de Dôme above the city  ·  photochrom, about 1890", 0.8)]))
shot(at(13, "Urban"), lambda d: photo("loc/clermont_notre_dame_du_port.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                      overlays=[lower("Notre-Dame-du-Port, Clermont", "Romanesque church of the eleventh and twelfth centuries", 0.5)]))
shot(at(13, "He"), lambda d: dore("peter_the_hermit", d, "IV", "Preaching the crusade", 0.5))
shot(at(13, "called"), lambda d: dore("benediction", d, "LVII", "Benediction", 0.5))
ROBERT_IMG = "docs/robert_monk_clermont_p729.jpg"
ROBERT = doc_lines("RecueilDesHistoriensDesCroisadesOccidentaux3", 804, ROBERT_IMG, "Deus vult Deus vult", "Deus vult Deus vult")
ROBERT_CTX = doc_lines("RecueilDesHistoriensDesCroisadesOccidentaux3", 804, ROBERT_IMG, "Haec8 et id genus", "Deus vult Deus vult")
r13 = lambda x: x - at(13, "According") + 0.3
def _robert(d):
    t0 = r13(at(13, "Deus")); t1 = r13(at(13, "it", end=True))
    gw = ["God", "wills", "it!", "God", "wills", "it!"]
    return Document(ROBERT_IMG, d, cam=doc_cam(ROBERT_IMG, ROBERT_CTX, t0 - 1.2, d),
                    highlights=[(t0, t1, ROBERT)],
                    panel=(t0, gw, [t0 + (t1 - t0) * i / len(gw) for i in range(len(gw))], "Robert the Monk, History of Jerusalem, book I  ·  English translation"),
                    overlays=[lower("Robert the Monk, History of Jerusalem", "Book I, chapter 2  ·  Latin text, Recueil des historiens des croisades (1866)", 0.6, t0 - 0.8)])
shot(at(13, "According") - 0.3, _robert)

# PART THREE: A JUST WAR
shot(ps(14), lambda d: Still("cma/augustine_print.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.05,
                             overlays=[lower("Saint Augustine of Hippo", "Engraving, Germany, about 1465  ·  Cleveland Museum of Art", 0.8)]))
shot(at(14, "legitimate") - 0.3, lambda d: photo("loc/piacenza_cathedral_interior.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08,
                                                 overlays=[lower("Piacenza Cathedral", "Photograph, about 1900", 0.5)]))
shot(at(14, "right", 1) - 0.3, lambda d: Still("cma/jerusalem_reliquary_cross.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.05,
                                               overlays=[lower("Reliquary cross", "Made in the crusader Kingdom of Jerusalem, 12th century  ·  Cleveland Museum of Art", 0.5)]))
shot(ps(15) - 0.2, lambda d: dore("departure", d, "LXIV", "The departure", 0.8))
shot(at(15, "armed"), lambda d: dore("way_to_holy_city", d, "XXIII", "The way to the Holy City", 0.5))
CANON_IMG = "docs/clermont_canon_mansi.jpg"
CANON = [(1739, 4040, 2768, 4104), (1684, 4104, 2768, 4158), (1692, 4158, 2770, 4211), (1690, 4215, 2440, 4269)]  # measured from the scan
r16 = lambda x: x - at(15, "council") + 0.3
shot(at(15, "council") - 0.3, lambda d: Document(CANON_IMG, d,
    cam=doc_cam(CANON_IMG, CANON, r16(ps(16)), r16(pe(16)) + 0.9, width=1300),
    highlights=[(r16(ps(16)), r16(pe(16)), CANON)],
    panel=(r16(ps(16)), [w for w, _ in words_of(16)], [r16(tt) for _, tt in words_of(16)], "Council of Clermont, 1095  ·  English translation"),
    overlays=[lower("Canons of the Council of Clermont", "November 1095  ·  Latin text, Mansi, Sacrorum conciliorum collectio, vol. 20", 0.8, r16(ps(16)) - 0.6)]))
shot(ps(17) - 0.2, lambda d: dore("wealth_of_the_east", d, "X", "The crusaders astonished at the wealth of the East", 0.8))
shot(at(17, "Families"), lambda d: dore("gathering_means", d, "XCIV", "Gathering means for the holy war", 0.5))
shot(at(17, "most"), lambda d: dore("the_return", d, "LXIX", "The return", 0.5))

# PART FOUR: JERUSALEM
r18 = lambda x: x - ps(18)
shot(ps(18), lambda d: MapShot(d, cam=[(0, 14.0, 45.0, 30.0), (r18(at(18, "People's", prefix=True)), 24.0, 42.5, 22.0),
                                       (r18(at(18, "knights")), 29.0, 40.0, 18.0), (d, 33.5, 38.0, 17.0)],
                               arrows=[(0.6, r18(at(18, "People's", prefix=True)), [C("Clermont"), (9.5, 46.5), (16.0, 45.6), (21.0, 43.8), (26.5, 41.8), C("Constantinople")], GREEN),
                                       (0.9, r18(at(18, "People's", prefix=True)) + 0.4, [C("Cologne"), (12.0, 48.8), (19.0, 47.0), (21.0, 44.0), (26.0, 42.2), C("Constantinople")], GREEN),
                                       (r18(at(18, "knights")), r18(pe(18)) + 0.6, [C("Constantinople"), C("Nicaea"), C("Dorylaeum"), (32.0, 38.4), C("Heraclea"), (36.5, 37.6), C("Antioch")], GREEN)],
                               markers=[mark(r18(at(18, "destroyed")), "Civetot")],
                               labels=[lab(0.6, "Clermont"), lab(1.0, "Constantinople", None), lab(r18(at(18, "destroyed")), "Civetot", "1096"),
                                       lab(r18(at(18, "knights")) + 1.2, "Nicaea", "1097"), lab(r18(pe(18)) - 0.5, "Antioch")]))
shot(at(18, "heat") - 0.3, lambda d: dore("taurus", d, "XVII", "Crusaders crossing the Taurus Mountains", 0.5))
shot(ps(19) - 0.2, lambda d: Still("loc/antioch_orontes_1881.jpg", d, crop=STEREO, end=(0.5, 0.48, 1.14), parallax=0.10, tone="sepia",
                                   overlays=[lower("Antioch and the Orontes plain", "Stereograph, 1881  ·  Library of Congress", 0.8)]))
shot(at(19, "took"), lambda d: dore("antioch_ramparts", d, "XX", "Bohemond mounting the ramparts of Antioch, June 1098", 0.5))
shot(at(19, "Starving"), lambda d: dore("famished", d, "XXVI", "Famished for water", 0.5))
shot(ps(20) - 0.2, lambda d: photo("loc/jerusalem_from_scopus.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                          overlays=[lower("Jerusalem from Mount Scopus", "Photochrom, about 1890–1900", 0.8)]))
shot(at(20, "Before"), lambda d: photo("loc/jerusalem_damascus_gate.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                       overlays=[lower("The walls of Jerusalem", "Rebuilt by Suleiman the Magnificent, 1537–41  ·  the Damascus Gate", 0.5)]))
shot(at(20, "On"), lambda d: dore("godfrey_enters", d, "XXIX", "Godfrey enters Jerusalem, 15 July 1099", 0.5))
shot(ps(21) - 0.2, lambda d: photo("loc/golgotha_1906.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08,
                                   overlays=[lower("Golgotha", "Chapel of the Crucifixion, Church of the Holy Sepulchre  ·  1906", 0.8)]))
shot(at(21, "Godfrey"), lambda d: Still("cma/nine_heroes_godfrey.jpg", d, start=(0.5, 0.5, 1.0), end=(0.72, 0.5, 1.25), parallax=0.04,
                                        overlays=[lower("Godfrey of Bouillon among the Nine Worthies", "Lucas van Leyden, about 1515–17  ·  Cleveland Museum of Art", 0.5)]))
shot(at(21, "Tradition"), lambda d: Still("cma/pilgrim_flask_holy_sepulchre.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.48, 1.18), parallax=0.04,
                                          overlays=[lower("Pilgrim's flask", "Cast with the Church of the Holy Sepulchre, crusader Jerusalem, 12th century  ·  Cleveland Museum of Art", 0.5)]))

# PART FIVE: THE HARDER CASES
shot(ps(22), lambda d: photo("loc/jerusalem_st_stephens_gate.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                             overlays=[lower("Jerusalem", "Saint Stephen's Gate  ·  photochrom, about 1890–1900", 0.8)]))
shot(ps(23) - 0.2, lambda d: dore("repulse_jerusalem", d, "XXVII", "The crusaders at the walls of Jerusalem", 0.8))
shot(at(23, "Later"), lambda d: photo("loc/jerusalem_jaffa_gate.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                      overlays=[lower("Jerusalem", "The Jaffa Gate  ·  photochrom, about 1890–1900", 0.5)]))
shot(ps(24) - 0.2, lambda d: dore("massacre_antioch", d, "XXI", "Massacre at Antioch, 1098", 0.8))
shot(at(24, "Zengi"), lambda d: Still("loc/urfa_edessa_1881.jpg", d, crop=STEREO, end=(0.5, 0.48, 1.14), parallax=0.10, tone="sepia",
                                      overlays=[lower("Edessa (Urfa)", "Stereograph, 1881  ·  Library of Congress", 0.5)]))
shot(at(24, "Baybars"), lambda d: Still("loc/antioch_1881.jpg", d, crop=STEREO, start=(0.4, 0.5, 1.15), end=(0.6, 0.5, 1.0), parallax=0.10, tone="sepia",
                                        overlays=[lower("Antioch", "Taken by Baybars in 1268  ·  stereograph, 1881", 0.5)]))
shot(ps(25) - 0.2, lambda d: dore("emicho", d, "VII", "The bands of Volkmar and Count Emicho", 0.8))
r25 = lambda x: x - at(25, "Rhineland")
shot(at(25, "Rhineland"), lambda d: MapShot(d, cam=[(0, 8.6, 49.0, 7.0), (d, 8.4, 49.6, 4.2)],
                                            labels=[lab(r25(at(25, "Speyer")), "Speyer"), lab(r25(at(25, "Worms")), "Worms"),
                                                    lab(r25(at(25, "Mainz")), "Mainz"), lab(0.4, "Cologne")]))
shot(at(25, "bishop"), lambda d: photo("loc/speyer_dom.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                       overlays=[lower("Speyer", "The cathedral, consecrated in 1061  ·  photograph, about 1890", 0.5)]))
shot(at(25, "archbishop"), lambda d: photo("loc/mainz_dom.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                           overlays=[lower("Mainz", "The cathedral  ·  photograph, about 1890", 0.5)]))
shot(at(25, "Fifty"), lambda d: dore("bernard_louis", d, "XXXVII", "Saint Bernard gives the cross to Louis VII, 1146", 0.5))
shot(ps(26) - 0.2, lambda d: photo("loc/st_marks_venice_1901.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Saint Mark's, Venice", "The bronze horses above its doors were taken from Constantinople in 1204", 0.8)]))
r26 = lambda x: x - at(26, "turned")
shot(at(26, "turned"), lambda d: MapShot(d, cam=[(0, 18.0, 43.0, 20.0), (d, 22.0, 42.0, 17.0)],
                                         arrows=[(0.2, r26(at(26, "sacked", end=True)) + 0.3, [C("Venice"), (14.0, 44.8), C("Zara"), (18.5, 41.5), (20.0, 38.5), (23.5, 37.0), (26.0, 39.8), C("Constantinople")], RED)],
                                         markers=[mark(r26(at(26, "sacked")), "Constantinople")],
                                         labels=[lab(0.2, "Venice"), lab(0.9, "Zara", "1202"), lab(r26(at(26, "sacked")), "Constantinople", "1204")]))
shot(at(26, "Pope"), lambda d: photo("loc/constantinople_walls_yedikule.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                     overlays=[lower("The land walls of Constantinople", "Photochrom, about 1890", 0.5)]))
shot(at(26, "Zara"), lambda d: photo("loc/zara_from_sea.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                     overlays=[lower("Zara (Zadar), Dalmatia", "A Christian city, taken by the crusaders in 1202  ·  photochrom, about 1890", 0.5)]))
shot(at(26, "2001"), lambda d: Still("cma/stroganoff_ivory.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.04,
                                     overlays=[lower("The Mother of God enthroned", "Byzantine ivory, 950–1025  ·  Cleveland Museum of Art", 0.5)]))
shot(ps(27) - 0.2, lambda d: dore("prayers_for_the_dead", d, "LXXXVI", "Prayers for the dead", 0.8))

# PART SIX: SALADIN AND THE LONG DEFENSE
r28 = lambda x: x - ps(28)
shot(ps(28), lambda d: MapShot(d, cam=[(0, 37.0, 34.6, 14.5), (r28(at(28, "Edessa")), 37.3, 34.9, 13.5), (d, 36.6, 34.3, 12.5)],
                               base_fill=(CRUSADER_STATES, GREEN),
                               sweeps=[(r28(at(28, "Edessa")), r28(at(28, "1144", end=True)) + 0.3, 38.4, 36.3, RED, [EDESSA_C])],
                               labels=[lab(0.8, "Edessa"), lab(1.2, "Antioch"), (1.6, 35.84, 34.44, "Tripoli", None), lab(2.0, "Jerusalem"),
                                       (r28(at(28, "1144")), 38.79, 37.16, "", "1144")]))
shot(at(28, "July") - 0.3, lambda d: photo("loc/horns_of_hattin_1934.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.12,
                                   overlays=[lower("The Horns of Hattin", "Above the Sea of Galilee  ·  photograph, 1934", 0.5)]))
shot(at(28, "October"), lambda d: Footage(VID("jaffa_gate_1897.mkv"), d, src_start=20.0, speed=0.9, zoom=(1.05, 1.0), pre=JAFFA_1897, sharpen=True,
                                          overlays=[lower("Jerusalem, 1897", "The Jaffa Gate  ·  Lumière film", 0.4)]))
shot(ps(29) - 0.2, lambda d: photo("loc/damascus_general_view.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Damascus", "Saladin's capital  ·  photochrom, about 1890–1900", 0.8)]))
shot(at(29, "Many"), lambda d: dore("the_captives", d, "LXXXII", "The captives", 0.5))
shot(at(29, "Templars"), lambda d: dore("de_mailly", d, "XLII", "Death of De Mailly, marshal of the Temple, 1187", 0.5))
shot(ps(30) - 0.2, lambda d: photo("loc/roberts_acre_1839.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08, tone="sepia",
                                   overlays=[lower("Acre", "Lithograph after David Roberts, 1839", 0.8)]))
shot(at(30, "Arsuf"), lambda d: dore("arsuf", d, "XLVII", "The Battle of Arsuf, 1191", 0.5))
shot(at(30, "Acre", 2) - 0.3, lambda d: photo("loc/acre_crusader_castle_1920.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Acre", "The citadel, built over the crusader fortress  ·  photograph, about 1920", 0.5)]))
shot(at(30, "never"), lambda d: Footage(VID("jaffa_gate_1897.mkv"), d, src_start=31.0, speed=0.9, zoom=(1.0, 1.05), pre=JAFFA_1897, sharpen=True,
                                        overlays=[lower("Jerusalem, 1897", "Pilgrims and townspeople at the Jaffa Gate", 0.6)]))
shot(ps(31) - 0.2, lambda d: photo("loc/caesarea_ramparts_1938.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                   overlays=[lower("Caesarea", "The crusader ramparts  ·  photograph, 1938", 0.8)]))
r31 = lambda x: x - at(31, "Antioch")
shot(at(31, "Antioch"), lambda d: MapShot(d, cam=[(0, 36.0, 34.6, 9.0), (d, 35.4, 33.4, 7.5)],
                                          base_fill=([ANTIOCH_P, COAST_1268], GREEN),
                                          sweeps=[(0.2, 1.6, 37.3, 35.0, RED, [ANTIOCH_P]), (r31(at(31, "Acre")), r31(at(31, "fell", 2, end=True)) + 0.4, 34.6, 31.4, RED, [COAST_1268])],
                                          labels=[lab(0.2, "Antioch", "1268"), lab(r31(at(31, "Acre")), "Acre", "1291")]))
shot(at(31, "came"), lambda d: photo("loc/athlit_castle_towers.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                     overlays=[lower("Athlit, Castle Pilgrim", "The last crusader fortress, abandoned in August 1291", 0.4)]))

# PART SEVEN: THE MEMORY OF THE CRUSADES
shot(ps(32), lambda d: photo("loc/damascus_from_salhiyeh.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                             overlays=[lower("Damascus", "Photochrom, about 1890–1900", 0.8)]))
shot(ps(33) - 0.2, lambda d: Still("cma/arabic_manuscript_1315.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.18), parallax=0.04,
                                   overlays=[lower("A page of Arabic prose", "Manuscript dated 1315  ·  Cleveland Museum of Art", 0.8)]))
shot(at(33, "Arabic"), lambda d: Footage(VID("jerusalem_1918.mp4"), d, src_start=216.0, zoom=(1.0, 1.05), pre=J1918, sharpen=True,
                                         overlays=[lower("Jerusalem, 1918", "A market in the Old City  ·  amateur film", 0.5)]))
shot(ps(34) - 0.2, lambda d: photo("loc/saladin_tomb_1898.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08, tone="sepia",
                                   overlays=[lower("The tomb of Saladin, Damascus", "Photograph by the American Colony, Jerusalem, 1898", 0.8)]))
shot(at(34, "German"), lambda d: photo("loc/kaiser_jerusalem_1898_cortege.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08, tone="sepia",
                                       overlays=[lower("Wilhelm II in Jerusalem, 1898", "The same journey took him to Damascus  ·  American Colony photograph", 0.5)]))
shot(ps(35) - 0.2, lambda d: dore("richard_saladin", d, "XLIX", "Richard and Saladin at the Battle of Arsuf", 0.8))
shot(at(35, "twentieth", prefix=True), lambda d: Footage(VID("levy_1933.mp4"), d, src_start=154.0, zoom=(1.0, 1.05), sharpen=True,
                                            overlays=[lower("Bethlehem, 1933", "Under the British Mandate  ·  amateur film", 0.5)]))

# EPILOGUE: LEPANTO AND VIENNA
shot(ps(36), lambda d: dore("mehmed_ii", d, "XCII", "Mehmed II before Constantinople, 1453", 0.8))
shot(at(36, "Hagia"), lambda d: photo("loc/hagia_sophia_interior_1860.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08, tone="sepia",
                                      overlays=[lower("Hagia Sophia as a mosque", "Photograph, about 1860", 0.5)]))
r36 = lambda x: x - at(36, "Their")
shot(at(36, "Their"), lambda d: MapShot(d, cam=[(0, 24.0, 42.0, 20.0), (d, 21.0, 44.5, 19.0)],
                                        sweeps=[(0.2, r36(pe(36)) + 0.8, 40.0, 48.8, RED, [BALKANS_HUN])],
                                        labels=[lab(0.2, "Constantinople", "1453"), lab(1.2, "Belgrade", "1521"), lab(1.9, "Mohacs", "1526", text="Mohács"),
                                                lab(2.6, "Vienna")]))
r37 = lambda x: x - ps(37)
shot(ps(37) - 0.2, lambda d: MapShot(d, cam=[(0, 19.0, 40.0, 16.0), (d, 21.3, 38.4, 6.0)],
                                     markers=[mark(r37(at(37, "Lepanto")), "Lepanto")],
                                     labels=[lab(r37(at(37, "Lepanto")), "Lepanto", "7 October 1571")]))
shot(at(37, "fleet"), lambda d: Still("loc/lepanto_1571_print.jpg", d, start=(0.5, 0.5, 1.0), end=(0.45, 0.5, 1.25), parallax=0.04, tone="sepia",
                                      overlays=[lower("The battle of Lepanto", "Venetian engraving, 1571  ·  Library of Congress", 0.5)]))
shot(at(37, "Its"), lambda d: Still("cma/barbarigo_veronese.jpg", d, start=(0.5, 0.4, 1.0), end=(0.5, 0.35, 1.15), parallax=0.06,
                                    overlays=[lower("Agostino Barbarigo, killed at Lepanto", "Second in command of the Venetian fleet  ·  Paolo Veronese  ·  Cleveland Museum of Art", 0.5)]))
shot(at(37, "asked"), lambda d: Still("cma/madonna_of_the_rosary.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.42, 1.18), parallax=0.04, tone="sepia",
                                      overlays=[lower("Madonna of the Rosary", "Print, 17th century  ·  Cleveland Museum of Art", 0.5)]))
VIENNA_PRINT = (0.07, 0.02, 0.98, 0.98)  # trims the strip of book text beside the plate
shot(ps(38) - 0.2, lambda d: Still("loc/vienna_1683_print.jpg", d, crop=VIENNA_PRINT, start=(0.5, 0.5, 1.0), end=(0.5, 0.55, 1.25), parallax=0.04, tone="sepia",
                                   overlays=[lower("The siege and relief of Vienna, 1683", "Engraving, Hamburg, 1685  ·  Library of Congress", 0.8)]))
shot(at(38, "Jan"), lambda d: Still("loc/vienna_1683_print.jpg", d, crop=VIENNA_PRINT, start=(0.484, 0.80, 1.35), end=(0.484, 0.84, 1.75), parallax=0.0, tone="sepia",
                                    overlays=[lower("John III Sobieski, \u201cKing of Poland\u201d", "Detail of the same engraving, 1685", 0.5)]))
shot(at(38, "hills"), lambda d: photo("loc/vienna_kahlenberg.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.10,
                                      overlays=[lower("The Kahlenberg above Vienna", "Where the relief army formed  ·  photochrom, about 1890", 0.5)]))
shot(at(38, "To"), lambda d: Still("cma/tughra_mehmed_iv.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.48, 1.15), parallax=0.04,
                                   overlays=[lower("Tughra of Sultan Mehmed IV", "In whose reign the siege was laid  ·  Cleveland Museum of Art", 0.5)]))
r39 = lambda x: x - ps(39)
shot(ps(39) - 0.2, lambda d: MapShot(d, cam=[(0, 26.0, 40.0, 44.0), (d, 22.0, 40.5, 40.0)],
                                     markers=[mark(r39(at(39, "Yarmouk")), "Yarmouk"), mark(r39(at(39, "Vienna")), "Vienna"),
                                              mark(r39(at(39, "Vienna")) + 0.5, "Manzikert"), mark(r39(at(39, "Vienna")) + 0.9, "Hattin"),
                                              mark(r39(at(39, "Vienna")) + 1.3, "Constantinople"), mark(r39(at(39, "Vienna")) + 1.7, "Lepanto")],
                                     labels=[lab(r39(at(39, "Yarmouk")), "Yarmouk", "636"), lab(r39(at(39, "Vienna")), "Vienna", "1683"),
                                             lab(r39(at(39, "Vienna")) + 0.5, "Manzikert", "1071"), lab(r39(at(39, "Vienna")) + 1.3, "Constantinople", "1453"),
                                             lab(r39(at(39, "Vienna")) + 1.7, "Lepanto", "1571"), (r39(at(39, "Vienna")) + 0.9, 35.45, 32.80, "Hattin", "1187")]))

# CLOSING
shot(ps(40), lambda d: Footage(VID("jerusalem_1918.mp4"), d, src_start=349.0, zoom=(1.0, 1.05), pre=J1918, sharpen=True,
                               overlays=[lower("Jerusalem, 1918", "Amateur film", 0.8)]))
shot(at(40, "church"), lambda d: dore("holy_sepulchre", d, "I", "The Holy Sepulchre", 0.5, start=(0.5, 0.42, 1.2), end=(0.5, 0.5, 1.0)))
shot(at(40, "last"), lambda d: photo("loc/constantinople_sea_walls_1860.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08, tone="sepia",
                                     overlays=[lower("The walls of Constantinople", "Photograph, about 1860", 0.5)]))
shot(ps(41) - 0.2, lambda d: photo("loc/clermont_notre_dame_du_port.jpg", d, start=(0.5, 0.45, 1.14), end=(0.5, 0.5, 1.0), parallax=0.08))
shot(at(41, "men"), lambda d: dore("departure", d, "LXIV", "The departure", 0.5, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0)))
shot(at(41, "When"), lambda d: photo("loc/zara_general_view.jpg", d, end=(0.5, 0.45, 1.14), parallax=0.08,
                                     overlays=[lower("Zara (Zadar)", "Photochrom, about 1890", 0.5)]))
shot(ps(42) - 0.2, lambda d: Still("cma/true_cross_reliquary_1214.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.16), parallax=0.04,
                                   overlays=[lower("Reliquary of the True Cross", "Cross from the crusader Kingdom of Jerusalem, about 1214  ·  Cleveland Museum of Art", 0.8)]))
shot(at(42, "empty"), lambda d: photo("loc/holy_sepulchre_interior.jpg", d, start=(0.5, 0.45, 1.18), end=(0.5, 0.5, 1.0), parallax=0.10))
shot(at(42, "Church"), lambda d: photo("loc/holy_sepulchre_front.jpg", d, start=(0.5, 0.5, 1.18), end=(0.5, 0.45, 1.0), parallax=0.12,
                                       overlays=[Fade(d - 3.5, d - 0.3, out=True)]))

shot(END, ROLL_SHOT)
CUTS.add(END)


def build():
    S.sort(key=lambda s: s[0])
    objs = []
    for i, (t0, make) in enumerate(S):
        t1 = S[i + 1][0] if i + 1 < len(S) else TOTAL
        nxt_cut = i + 1 < len(S) and S[i + 1][0] in CUTS
        o = make((t1 - t0) + (XF if i + 1 < len(S) and not nxt_cut else 0))
        o.cut = t0 in CUTS
        objs.append(o)
    return objs


def cues():
    return {"intro": [0, T_TITLE], "title": [T_TITLE - 0.5, T_TITLE + TITLE + 1], "conquest": [ps(4) - 0.5, pe(4) + 0.8],
            "lament": [ps(6) - 0.3, pe(7) + 1.0], "conquest2": [T8 - 0.3, pe(9) + 0.6], "lament2": [ps(12) - 0.5, pe(12) + 1.0],
            "conquest3": [ps(18) - 0.3, pe(20) + 0.6], "lament3": [ps(23) - 0.3, pe(23) + 1.0], "conquest4": [ps(28) - 0.3, pe(28) + 0.6],
            "conquest5": [ps(37) - 0.3, pe(38) + 0.6], "closing": [ps(40), TOTAL]}


if __name__ == "__main__":
    json.dump(dict(total=TOTAL, cues=cues()), open(os.path.join(OUT, "cues.json"), "w"))
    starts = sorted(s[0] for s in S)
    short = [(round(a, 2), round(b - a, 2)) for a, b in zip(starts, starts[1:] + [TOTAL]) if b - a < 1.2]
    print(f"total {TOTAL / 60:.1f} min, {len(S)} shots, shortest gaps {short[:5]}", flush=True)
    if "--check" in sys.argv:
        for i, o in enumerate(build()):
            pass
        print("all shots constructed")
        sys.exit()
    if "--audio-only" in sys.argv:
        sys.exit()
    secs = render(build(), os.path.join(OUT, "video.mp4"), xfade=XF)
    print(f"video {secs:.2f}s (timeline {TOTAL:.2f}s)")
