"""Edit decision list for The Reconquista. Builds the narration timeline, the shot list, music cues and subtitles.

usage: reconquista_edl.py [--audio-only]
Requires: narration_reconquista/manifest.json with word timings (tools/transcribe.py), assets from assets_reconquista.json.
"""
import json, os, re, sys
import numpy as np
import soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import W, H, DOC, ASSETS, Still, Footage, Text, Fade, Black, Document, render
from maps import MapShot
from textnorm import norm
import ia_find

XF = 0.6
NAR = os.path.join(DOC, "narration_reconquista")
OUT = os.path.join(DOC, "out", "reconquista"); os.makedirs(OUT, exist_ok=True)
RED, GREEN = (150, 38, 30), (60, 110, 70)

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
TOTAL = t - GAP + TAIL
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
def autocrop(name, thresh=22):
    from PIL import Image
    a = np.asarray(Image.open(os.path.join(ASSETS, name)).convert("L")).astype(np.float32)
    h, w = a.shape
    edge = np.median(np.concatenate([a[:8].ravel(), a[-8:].ravel(), a[:, :8].ravel(), a[:, -8:].ravel()]))
    rows = np.where(np.abs(a - edge).mean(1) > thresh)[0]
    cols = np.where(np.abs(a - edge).mean(0) > thresh)[0]
    m = 0.008
    return (cols[0] / w + m, rows[0] / h + m, cols[-1] / w - m, rows[-1] / h - m)


def photo(name, d, **kw):
    """LOC photochroms carry a grey border: trim it automatically unless a crop is given."""
    if "crop" not in kw and name.startswith("loc/"):
        kw["crop"] = autocrop(name)
    return Still(name, d, **kw)


def lower(text, sub, t_in=0.6, t_out=None):
    return Text("lower", text, sub, t_in=t_in, t_out=t_out)


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
    # join words hyphenated across a line break ("cris-" + "tianos") so phrases match; keep word index spans
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
    left = min(l[0] for l in lines)  # continuation lines begin at the text margin
    lines = [lines[0]] + [[left] + l[1:] for l in lines[1:]]
    return [(x0 * sx - pad, y0 * sy - pad, x1 * sx + pad, y1 * sy + pad) for x0, y0, x1, y1 in lines]


def center_of(boxes):
    return (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2, (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2


GRANADA = [(-5.6, 36.0), (-5.6, 37.0), (-4.6, 37.35), (-3.4, 37.62), (-2.4, 37.55), (-1.6, 37.35), (-1.6, 36.6), (-2.2, 36.7), (-4.4, 36.6)]
IB = [(-10.5, 36.5), (-10.5, 44.3), (-1.75, 43.45), (-0.5, 42.85), (1.0, 42.65), (3.4, 42.45), (3.4, 41.9), (2.4, 41.2), (1.1, 40.6),
      (0.4, 39.5), (0.6, 38.6), (-0.2, 37.6), (-1.5, 36.9), (-4.0, 36.4), (-5.3, 35.97), (-6.5, 36.2)]

# ------------------------------------------------------------------ shot list: (start time, factory(duration))
S = []
def shot(t0, f): S.append((t0, f))

TOLEDO_CARD = (0.102, 0.15, 0.495, 0.86)
GIB_CARD = (0.095, 0.06, 0.495, 0.82)

# COLD OPEN (as approved in the pilot)
shot(0.0, lambda d: photo("loc/alhambra_court_of_lions.jpg", d, start=(0.5, 0.60, 1.0), end=(0.5, 0.40, 1.12), parallax=0.10,
                          overlays=[Fade(0, 1.8), lower("Granada", "The Court of the Lions, Alhambra", 2.2, at(1, "To") - 1.2)]))
shot(at(1, "To"), lambda d: Footage(os.path.join(ASSETS, "video/alcazaba_adarves.avi"), d, speed=0.85, zoom=(1.0, 1.05)))
shot(at(1, "golden"), lambda d: photo("loc/alhambra_dos_hermanas.jpg", d, start=(0.42, 0.5, 1.15), end=(0.55, 0.5, 1.0), parallax=0.08))
shot(at(1, "until"), lambda d: photo("loc/granada_from_silla_del_moro.jpg", d, start=(0.45, 0.45, 1.08), end=(0.55, 0.5, 1.0), parallax=0.06))
shot(ps(2), lambda d: Footage(os.path.join(ASSETS, "video/alcazaba_views.avi"), d, speed=0.85, zoom=(1.03, 1.0)))
shot(at(2, "reclaiming") - 0.3, lambda d: Still("lanepoole/sierra_nevada.jpg", d, end=(0.5, 0.46, 1.12), tone="sepia", parallax=0.06))
shot(T_TITLE, lambda d: photo("loc/alhambra_sierra_nevada.jpg", d, start=(0.5, 0.42, 1.0), end=(0.5, 0.4, 1.10), parallax=0.12,
                              overlays=[Text("title", "THE RECONQUISTA", "Eight centuries of war for Spain", t_in=0.5, t_out=TITLE - 0.6)]))
CUTS = set()
for n, (tc, sec) in chapters.items():
    part, _, name = sec.partition(":")
    label, title = (part.strip().title(), name.strip().title()) if name else ("", part.strip().title())
    title = re.sub(r"\b(Of|The|And|To|A)\b", lambda m: m.group(1).lower(), title)
    title = title[0].upper() + title[1:]
    shot(tc, (lambda lb, tt: lambda d: Black(d, overlays=[Text("chapter", lb, tt, t_in=0.3, t_out=CHAPTER - 0.7)]))(label, title))
    CUTS.add(tc)

# PART ONE (as approved in the pilot)
shot(ps(3), lambda d: Still("loc/toledo_stereo_1902.jpg", d, crop=TOLEDO_CARD, start=(0.45, 0.5, 1.0), end=(0.55, 0.46, 1.15), parallax=0.10, tone="sepia",
                            overlays=[lower("Toledo", "Capital of the Visigothic kingdom", 0.8)]))
shot(at(3, "brought"), lambda d: Still("cma/visigothic_tomb_plaque.jpg", d, start=(0.5, 0.42, 1.0), end=(0.5, 0.5, 1.18), parallax=0.05,
                                       overlays=[lower("Christian tomb plaque", "Hispania, 400–800  ·  Cleveland Museum of Art")]))
shot(at(3, "own"), lambda d: Still("cma/visigothic_belt_buckle.jpg", d, end=(0.5, 0.5, 1.15),
                                   overlays=[lower("Visigothic belt buckle", "Hispania, c. 525–560  ·  Cleveland Museum of Art", 0.4)]))
shot(ps(4) - 0.4, lambda d: MapShot(d, cam=[(0, -5.6, 36.0, 4.2), (d, -5.35, 36.2, 2.6)],
                                    arrows=[(at(4, "crossed") - ps(4) + 0.4, at(4, "crossed") - ps(4) + 3.2, [(-5.31, 35.86), (-5.47, 35.99), (-5.36, 36.12)], RED)],
                                    labels=[(0.8, -5.31, 35.88, "Ceuta", None), (1.2, -5.80, 35.77, "Tangier", None),
                                            (at(4, "crossed") - ps(4) + 3.0, -5.35, 36.14, "Gibraltar", "711")]))
shot(at(4, "rock") - 0.25, lambda d: Still("loc/gibraltar_stereo_1895.jpg", d, crop=GIB_CARD, start=(0.5, 0.45, 1.0), end=(0.42, 0.38, 1.18), parallax=0.12, tone="sepia",
                                           overlays=[lower("Gibraltar", "Jabal Tariq, the mountain of Tariq", at(4, "Jabal") - at(4, "rock") + 0.25)]))
r5 = lambda x: x - ps(5)
shot(ps(5), lambda d: MapShot(d, cam=[(0, -4.6, 38.6, 13.0), (r5(at(5, "Within")), -3.8, 39.6, 17.5), (r5(at(5, "advance")), -3.8, 39.8, 18.5), (d, -1.6, 43.2, 22.0)],
                              sweeps=[(r5(at(5, "Within")), r5(at(5, "Caliphate", end=True)), 35.6, 44.6, RED, "iberia_minus_asturias")],
                              asturias_t=r5(at(5, "Only")),
                              arrows=[(r5(at(5, "advance")), r5(at(5, "Tours")) + 0.3, [(-1.4, 43.05), (-0.58, 44.84), (0.34, 46.58), (0.55, 46.95)], RED)],
                              markers=[(r5(at(5, "Guadalete")), -5.93, 36.47), (r5(at(5, "Tours")), 0.55, 46.95)],
                              labels=[(r5(at(5, "Guadalete")), -5.93, 36.47, "Guadalete", "711"), (r5(at(5, "Within")) + 0.5, -4.02, 39.86, "Toledo", None),
                                      (r5(at(5, "Within")) + 1.0, -4.78, 37.88, "Córdoba", None), (r5(at(5, "Only")), -7.4, 43.3, "Asturias", "beyond Umayyad rule"),
                                      (r5(at(5, "Tours")), 0.55, 46.95, "Tours", "732")]))
shot(at(5, "Frankish") - 0.5, lambda d: Still("engraving/battle_of_tours.jpg", d, start=(0.55, 0.45, 1.0), end=(0.45, 0.5, 1.15), parallax=0.12, tone="sepia",
                                              overlays=[lower("Near Tours, 732", "Engraving, Guizot's History of France (1869)", 0.5)]))
CH754_ATROC = [(1490, 1035, 1850, 1082), (190, 1088, 1850, 1134), (190, 1140, 570, 1186)]
CH754_LAMENT = [(860, 1451, 1850, 1498), (188, 1508, 1850, 1556), (188, 1562, 1650, 1604)]
r6 = lambda x: x - ps(6) + 0.3
shot(ps(6) - 0.3, lambda d: Document("docs/chronicle754_p353.jpg", d,
    cam=[(0, 1150, 900, 0.50), (r6(at(6, "described")), 1060, 1110, 0.92), (r6(at(6, "And")), 1060, 1110, 0.92),
         (r6(ps(7)) + 0.3, 1030, 1640, 1.05), (r6(pe(7)) + 0.9, 1060, 1660, 1.10)],
    highlights=[(r6(at(6, "cities")), r6(at(6, "daggers", end=True)), CH754_ATROC), (r6(ps(7)), r6(pe(7)), CH754_LAMENT)],
    panel=(r6(ps(7)), [w for w, _ in words_of(7)], [r6(tt) for _, tt in words_of(7)], "Chronicle of 754  ·  English translation"),
    overlays=[lower("Chronicle of 754", "Written by a Christian under Muslim rule  ·  Latin text, ed. Mommsen (1894)", 0.8, r6(at(6, "described")) - 0.7)]))
shot(ps(8) - 0.2, lambda d: photo("loc/cordoba_mezquita.jpg", d, start=(0.5, 0.56, 1.0), end=(0.5, 0.5, 1.28), parallax=0.14,
                                  overlays=[lower("Córdoba", "The Great Mosque, begun 785", 0.8)]))
shot(at(8, "They"), lambda d: Still("cma/madinat_al_zahra_capital.jpg", d, start=(0.5, 0.45, 1.0), end=(0.5, 0.5, 1.2), parallax=0.06,
                                    overlays=[lower("Column capital, Madinat al-Zahra", "Caliphal palace near Córdoba, c. 960–76  ·  Cleveland Museum of Art", 0.5)]))
shot(at(8, "New"), lambda d: Still("lanepoole/cordoba_mosque_exterior.jpg", d, end=(0.55, 0.5, 1.15), tone="sepia", parallax=0.08))
shot(at(8, "In"), lambda d: Footage(os.path.join(ASSETS, "video/cordoba_mass.mov"), d, src_start=6.0, zoom=(1.05, 1.12), sharpen=True,
                                    overlays=[lower("Córdoba today", "Mass in the former Great Mosque, a cathedral since 1236", at(8, "Church") - at(8, "In") - 0.3)]))
shot(ps(9) - 0.2, lambda d: Still("lanepoole/almohad_banner.jpg", d, end=(0.5, 0.45, 1.15), tone="sepia", parallax=0.05,
                                  overlays=[lower("Banner of the Almohads", "After a 19th-century engraving", 0.7)]))
shot(at(9, "Christians"), lambda d: photo("loc/seville_giralda.jpg", d, start=(0.5, 0.75, 1.0), end=(0.5, 0.3, 1.0), parallax=0.10,
                                          overlays=[lower("The Giralda, Seville", "Built as the minaret of the Almohad mosque, 1184–98", 0.6)]))
shot(at(9, "Among"), lambda d: Still("lanepoole/cordoba_mosque_gate.jpg", d, start=(0.5, 0.5, 1.18), end=(0.5, 0.5, 1.0), tone="sepia", parallax=0.08))
shot(ps(10) - 0.2, lambda d: photo("loc/cordoba_patio_naranjos.jpg", d, start=(0.5, 0.62, 1.0), end=(0.5, 0.48, 1.12), parallax=0.10))

# PART TWO: THE LONG ROAD BACK
shot(ps(11), lambda d: Still("loc/covadonga_1882.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.12, tone="sepia",
                             overlays=[lower("Covadonga, Asturias", "The cave shrine, photographed in 1882", 0.8)]))
r11 = lambda x: x - at(11, "battle")
shot(at(11, "battle"), lambda d: MapShot(d, cam=[(0, -5.0, 42.6, 8.0), (d, -3.4, 41.8, 13.5)],
                                         sweeps=[(-2, -1, 35.6, 44.6, RED, "iberia_minus_asturias")], asturias_t=0.0,
                                         markers=[(0.3, -5.06, 43.31)],
                                         labels=[(0.3, -5.06, 43.31, "Covadonga", "c. 722"), (r11(at(11, "León")), -5.57, 42.6, "León", None),
                                                 (r11(at(11, "Castile")), -3.7, 42.34, "Castile", None),
                                                 (r11(at(11, "Navarre")), -1.65, 42.82, "Navarre", None), (r11(at(11, "Aragon")), -0.88, 42.6, "Aragon", None),
                                                 (r11(at(11, "Catalonia")), 1.9, 42.1, "Catalonia", None)]))
r12 = lambda x: x - ps(12)
shot(ps(12), lambda d: MapShot(d, cam=[(0, -4.0, 40.5, 14.5), (d, -4.0, 40.0, 13.0)],
                               sweeps=[(-2, -1, 35.6, 44.6, RED, [GRANADA, IB]), (0.4, d - 0.6, 43.6, 40.0, GREEN, [IB])],
                               labels=[(d * 0.55, -4.02, 39.86, "Toledo", "1085")]))
shot(at(12, "Castile"), lambda d: photo("loc/segovia_alcazar.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.10,
                                        overlays=[lower("Segovia", "Castle of the kings of Castile", 0.6)]))
shot(ps(13), lambda d: Still("collins/santiago_cathedral.jpg", d, start=(0.5, 0.55, 1.0), end=(0.5, 0.45, 1.15), parallax=0.08,
                             overlays=[lower("Santiago de Compostela", "Shrine of Saint James  ·  watercolour, W. W. Collins (1909)", at(13, "Santiago") - ps(13))]))
shot(at(13, "sacked"), lambda d: Still("collins/santiago_interior.jpg", d, start=(0.5, 0.5, 1.12), end=(0.5, 0.5, 1.0), parallax=0.06))
shot(at(13, "According"), lambda d: photo("loc/cordoba_mihrab.jpg", d, start=(0.5, 0.6, 1.0), end=(0.5, 0.45, 1.15), parallax=0.10,
                                          overlays=[lower("The Great Mosque of Córdoba", "Where the bells of Santiago hung as lamps", 0.6)]))
r14 = lambda x: x - ps(14)
shot(ps(14), lambda d: MapShot(d, cam=[(0, -4.2, 39.0, 13.0), (d, -4.0, 38.2, 11.0)],
                               sweeps=[(-2, -1, 35.6, 44.6, RED, [GRANADA, IB]), (-2, -1, 43.6, 40.0, GREEN, [IB]),
                                       (r14(at(14, "broke")), r14(at(14, "fallen", end=True)), 40.0, 37.45, GREEN, [IB])],
                               markers=[(r14(at(14, "Navas")), -3.57, 38.28)],
                               labels=[(r14(at(14, "Navas")), -3.57, 38.28, "Las Navas de Tolosa", "1212"),
                                       (r14(at(14, "Córdoba")), -4.78, 37.88, "Córdoba", "1236"),
                                       (r14(at(14, "fallen")), -5.98, 37.39, "Seville", "1248")]))
shot(at(14, "chronicles"), lambda d: Still("collins/cordoba_campanario.jpg", d, start=(0.5, 0.6, 1.0), end=(0.5, 0.4, 1.12), parallax=0.08,
                                           overlays=[lower("Córdoba", "The bell tower of the cathedral, once the minaret  ·  W. W. Collins (1909)", 0.6)]))
shot(ps(15) - 0.2, lambda d: photo("loc/seville_cathedral.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.45, 1.15), parallax=0.10,
                                   overlays=[lower("Seville Cathedral", "Built on the site of the Almohad mosque", 0.8)]))
shot(ps(16) - 0.2, lambda d: Still("loc/toledo_santa_maria_la_blanca.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.5, 1.15), parallax=0.10, tone="sepia",
                                   overlays=[lower("Toledo", "Santa María la Blanca, built in the Mudéjar style", 0.8)]))
shot(at(16, "door"), lambda d: Still("lanepoole/toledo_puerta_del_sol.jpg", d, end=(0.5, 0.45, 1.12), tone="sepia", parallax=0.06))
shot(at(16, "Where", 1), lambda d: Still("lanepoole/toledo.jpg", d, start=(0.5, 0.5, 1.12), end=(0.5, 0.5, 1.0), tone="sepia", parallax=0.06,
                                         overlays=[lower("Toledo", "Christian since 1085", 0.6)]))

# PART THREE: 1492
r17 = lambda x: x - ps(17)
shot(ps(17), lambda d: MapShot(d, cam=[(0, -3.6, 37.6, 7.5), (d, -3.6, 37.2, 6.0)],
                               sweeps=[(-2, -1, 35.6, 44.6, RED, [GRANADA]), (-2, -1, 44.0, 35.6, GREEN, [IB]),
                                       (r17(at(17, "surrendered")), r17(at(17, "city", end=True)), 37.8, 35.9, GREEN, [GRANADA])],
                               labels=[(0.6, -3.6, 37.18, "Granada", "the last Muslim kingdom")]))
shot(at(17, "surrendered") - 0.3, lambda d: photo("loc/alhambra_puerta_del_vino.jpg", d, start=(0.5, 0.6, 1.0), end=(0.5, 0.5, 1.15), parallax=0.10,
                                                  overlays=[lower("The Alhambra", "Surrendered 2 January 1492", 0.6)]))
shot(at(17, "After"), lambda d: Still("lanepoole/sword_of_boabdil.jpg", d, end=(0.5, 0.5, 1.15), tone="sepia",
                                      overlays=[lower("Sword of Boabdil", "Last Nasrid ruler of Granada", 0.5)]))
shot(ps(18) - 0.2, lambda d: Still("lanepoole/plan_of_granada.jpg", d, start=(0.5, 0.5, 1.0), end=(0.45, 0.45, 1.25), tone="sepia",
                                   overlays=[lower("The Capitulations of Granada", "November 1491", 0.8)]))
shot(at(18, "No"), lambda d: photo("loc/alhambra_mesquita.jpg", d, start=(0.5, 0.55, 1.0), end=(0.5, 0.45, 1.12), parallax=0.10))
shot(ps(19) - 0.2, lambda d: photo("loc/granada_cathedral_from_gate_of_justice.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.5, 1.15), parallax=0.08, tone="sepia",
                                   overlays=[lower("Granada", "Seat of Archbishop Hernando de Talavera", 0.8)]))
shot(at(19, "Muslims"), lambda d: Footage(os.path.join(ASSETS, "video/alcazaba_views.avi"), d, src_start=4.0, speed=0.8, zoom=(1.0, 1.06),
                                          overlays=[lower("The Albaicín", "The old Muslim quarter of Granada", 0.6)]))
shot(ps(20) - 0.2, lambda d: Still("lanepoole/alpuxarras.jpg", d, end=(0.5, 0.45, 1.15), tone="sepia", parallax=0.08,
                                   overlays=[lower("The Alpujarras", "Mountains south of Granada", at(20, "Alpujarras") - ps(20))]))
shot(ps(21) - 0.2, lambda d: Still("collins/granada_cathedral.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("Castile, 1502", "Baptism, or departure", 0.8)]))
shot(at(21, "From"), lambda d: photo("loc/granada_tombs_catholic_monarchs.jpg", d, start=(0.5, 0.55, 1.0), end=(0.5, 0.5, 1.18), parallax=0.10,
                                     overlays=[lower("Ferdinand and Isabella", "Their tombs in the Royal Chapel, Granada", 0.6)]))
shot(ps(22) - 0.2, lambda d: Still("collins/cordoba_mesquita_interior.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.5, 1.0), parallax=0.10))
shot(at(22, "In"), lambda d: Still("collins/toledo_cathedral.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))

# PART THREE AND A HALF: THE HARDER CASE
DEC_DL = "docs/alhambra_decree_deadline.jpg"
def deadline_boxes(): return doc_lines("historiasocialpo03amad", 625, DEC_DL, "mandamos á todos los judíos", "salgan")
def decree_shot(d):
    bx = deadline_boxes(); cx, cy = center_of(bx)
    r = lambda x: x - ps(23) + 0.2
    return Document(DEC_DL, d, cam=[(0, cx, 900, 0.48), (r(at(23, "Every")), cx, cy, 0.85), (d, cx, cy + 40, 0.92)],
                    highlights=[(r(at(23, "Every")), r(at(23, "July", end=True)), bx)],
                    overlays=[lower("The Alhambra Decree, 31 March 1492", "Printed in Amador de los Ríos (1876) from the manuscript in the Biblioteca Nacional", 0.6, r(at(23, "Every")) - 0.5)])
shot(ps(23) - 0.2, decree_shot)
shot(ps(24) - 0.2, lambda d: Still("loc/toledo_santa_maria_la_blanca.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.5, 1.0), parallax=0.10, tone="sepia",
                                   overlays=[lower("Toledo", "Santa María la Blanca, built as a synagogue", 0.8)]))
DEC_RS = "docs/alhambra_decree_reason.jpg"
def reason_shot(d):
    bx = doc_lines("historiasocialpo03amad", 623, DEC_RS, "porque Nos fuimos informados", "con los cristianos")
    cx, cy = center_of(bx)
    r = lambda x: x - ps(25) + 0.2
    return Document(DEC_RS, d, cam=[(0, cx, cy + 200, 0.55), (r(ps(26)), cx, cy + 260, 0.95), (d, cx, cy + 270, 1.0)],
                    highlights=[(r(ps(26)), r(pe(26)), bx)],
                    panel=(r(ps(26)), [w for w, _ in words_of(26)], [r(tt) for _, tt in words_of(26)], "Alhambra Decree  ·  English translation"))
shot(ps(25) - 0.2, reason_shot)
shot(ps(27) - 0.2, lambda d: Still("collins/toledo_cathedral.jpg", d, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08))
shot(at(27, "How"), lambda d: Still("lanepoole/toledo.jpg", d, end=(0.55, 0.5, 1.12), tone="sepia", parallax=0.06))
r28 = lambda x: x - ps(28)
shot(ps(28) - 0.2, lambda d: MapShot(d, cam=[(0, -1.0, 45.5, 22.0)],
                                     labels=[(r28(at(28, "England")), -1.5, 49.6, "England", "expelled its Jews, 1290"),
                                             (r28(at(28, "France")), 2.35, 46.8, "France", "1306 and 1394"),
                                             (r28(at(28, "Spain's")), -3.7, 40.4, "Castile and Aragon", "1492: baptism, or exile")]))
shot(ps(29) - 0.2, lambda d: Still("collins/segovia_aqueduct.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("Segovia", "Home of Abraham Seneor, chief rabbi of Castile", 0.8)]))
shot(at(29, "Others"), lambda d: Still("collins/malaga_harbour.jpg", d, start=(0.5, 0.5, 1.0), end=(0.55, 0.5, 1.15), parallax=0.08))
shot(ps(30) - 0.2, lambda d: photo("loc/alhambra_palace_charles_v.jpg", d, end=(0.5, 0.5, 1.12), parallax=0.08))

# PART FOUR: BEHIND CLOSED DOORS
shot(ps(31), lambda d: Still("collins/granada_cathedral.jpg", d, start=(0.5, 0.5, 1.2), end=(0.5, 0.45, 1.0), parallax=0.08))
shot(at(31, "Spanish"), lambda d: Still("collins/toledo_cathedral.jpg", d, end=(0.48, 0.45, 1.18), parallax=0.08,
                                        overlays=[lower("The Spanish Inquisition", "Founded 1478", 0.5)]))
shot(ps(32) - 0.2, lambda d: Still("lanepoole/alhambra_window.jpg", d, end=(0.5, 0.48, 1.18), tone="sepia", parallax=0.08))
shot(at(32, "They", 2), lambda d: Still("lanepoole/koran_case_escorial.jpg", d, end=(0.5, 0.5, 1.15), tone="sepia",
                                        overlays=[lower("Ancient Qur'an case", "Escorial Library", 0.6)]))
shot(ps(33) - 0.2, lambda d: MapShot(d, cam=[(0, -2.5, 37.0, 9.0), (d, -1.8, 36.6, 7.0)],
                                     labels=[(0.6, -0.64, 35.70, "Oran", "1504"), (1.2, -3.6, 37.18, "Granada", None)]))
shot(ps(34) - 0.2, lambda d: Still("collins/cordoba_mesquita_interior.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.5, 1.2), parallax=0.12))

# PART FIVE: THE ENEMY AT THE COAST
r35 = lambda x: x - ps(35)
shot(ps(35), lambda d: MapShot(d, cam=[(0, 0.5, 38.5, 16.0), (d, 0.0, 38.2, 14.0)],
                               arrows=[(r35(at(35, "corsairs")), r35(at(35, "corsairs")) + 2.2, [(3.06, 36.78), (1.8, 37.8), (0.2, 38.9)], RED),
                                       (r35(at(35, "corsairs")) + 0.8, r35(at(35, "corsairs")) + 3.0, [(-0.64, 35.72), (-0.9, 36.7), (-1.0, 37.55)], RED)],
                               labels=[(r35(at(35, "corsairs")), 3.06, 36.76, "Algiers", None), (r35(at(35, "corsairs")) + 0.6, -0.64, 35.70, "Oran", None),
                                       (r35(at(35, "Spanish")), -0.37, 39.47, "Valencia", None)]))
shot(at(35, "burning"), lambda d: photo("loc/algiers_harbor_lighthouse.jpg", d, end=(0.5, 0.5, 1.15), parallax=0.08,
                                        overlays=[lower("Algiers", "Base of the Barbary corsairs", 0.5)]))
shot(ps(36) - 0.2, lambda d: photo("loc/algiers_harbor_admiralty.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08))
shot(at(36, "1568"), lambda d: Still("lanepoole/alpuxarras.jpg", d, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0), tone="sepia", parallax=0.10,
                                     overlays=[lower("The Alpujarras", "Rebellion of 1568–71", 0.5)]))
shot(at(36, "Both"), lambda d: Still("lanepoole/sierra_nevada.jpg", d, start=(0.45, 0.5, 1.12), end=(0.55, 0.5, 1.0), tone="sepia", parallax=0.08))
shot(ps(37) - 0.2, lambda d: Still("collins/avila.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("Castile", "Where the Moriscos of Granada were resettled", 0.8)]))
shot(at(37, "In"), lambda d: photo("loc/valencia_plaza_de_la_seo.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("Valencia", "1605", 0.5)]))
BAN_L = "docs/valencia_bando_1609_letter.jpg"
def bando_letter(d):
    bx = doc_lines("losmoriscosespa02borouoft", 204, BAN_L, "continuando su apostasia", "perturbación de nuestros Reynos")
    cx, cy = center_of(bx)
    r = lambda x: x - ps(38) + 0.2
    return Document(BAN_L, d, cam=[(0, cx, cy - 300, 0.5), (r(at(38, "royal")), cx, cy, 0.85), (d, cx, cy + 30, 0.92)],
                    highlights=[(r(at(38, "Moriscos", 2)), r(at(38, "kingdoms", end=True)), bx)],
                    overlays=[lower("Proclamation of expulsion, Valencia, 22 September 1609", "Printed in Boronat, Los moriscos españoles y su expulsión (1901)", 0.6, r(at(38, "royal")) - 0.4)])
shot(ps(38) - 0.2, bando_letter)
r38 = lambda x: x - at(38, "Over")
shot(at(38, "Over"), lambda d: MapShot(d, cam=[(0, 0.0, 38.4, 13.0), (d, 0.3, 38.0, 12.0)],
                                       arrows=[(0.2, 2.6, [(0.10, 38.84), (0.0, 37.6), (-0.6, 35.75)], RED), (0.6, 3.0, [(-0.32, 39.46), (-0.5, 37.8), (-0.64, 35.73)], RED),
                                               (1.0, 3.4, [(-0.48, 38.34), (-0.6, 37.0), (-0.66, 35.74)], RED), (1.4, 3.8, [(0.47, 40.47), (1.8, 38.5), (2.9, 36.8)], RED)],
                                       labels=[(0.2, 0.10, 38.84, "Dénia", None), (0.6, -0.37, 39.47, "Valencia", None), (1.0, -0.48, 38.34, "Alicante", None),
                                               (2.6, -0.64, 35.70, "Oran", None), (3.8, 3.06, 36.76, "Algiers", None)]))

# PART SIX: THREE WAYS TO SEE 1609
shot(ps(39) - 0.2, lambda d: Still("collins/valencia_cathedral_door.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(40) - 0.2, lambda d: Still("lanepoole/alpuxarras.jpg", d, start=(0.5, 0.5, 1.0), end=(0.55, 0.45, 1.15), tone="sepia", parallax=0.08))
shot(at(40, "Ottoman"), lambda d: Still("loc/lepanto_1571_print.jpg", d, start=(0.5, 0.5, 1.0), end=(0.55, 0.5, 1.25), tone="sepia",
                                        overlays=[lower("Lepanto, 1571", "Engraving published the year of the battle  ·  Library of Congress", 0.5)]))
shot(ps(41) - 0.2, lambda d: Still("collins/cordoba_mesquita_interior.jpg", d, start=(0.45, 0.5, 1.15), end=(0.55, 0.5, 1.0), parallax=0.10))
shot(at(41, "Historians"), lambda d: photo("loc/valencia_miguelete.jpg", d, end=(0.5, 0.4, 1.12), parallax=0.08))
shot(ps(42) - 0.2, lambda d: photo("loc/valencia_plaza_de_la_seo.jpg", d, start=(0.5, 0.5, 1.12), end=(0.5, 0.45, 1.0), parallax=0.08,
                                   overlays=[lower("Valencia Cathedral", "Seat of Archbishop Juan de Ribera", at(42, "Ribera") - ps(42))]))
shot(at(42, "teaching") - 1.0, lambda d: Still("collins/valencia_cathedral_door.jpg", d, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08))
BAN_C, BAN_E = "docs/valencia_bando_1609_clauses.jpg", "docs/valencia_bando_1609_exemptions.jpg"
def bando_clauses(d):
    six = doc_lines("losmoriscosespa02borouoft", 205, BAN_C, "que en cada lugar de cien casas", "muestras huuieren dado de Christianos")
    kids = doc_lines("losmoriscosespa02borouoft", 205, BAN_C, "QUE los mochachos y mochachas menores de quatro", "no serán expelidos")
    cx, cy = center_of(six)
    kx, ky = center_of(kids)
    r = lambda x: x - ps(43) + 0.2
    return Document(BAN_C, d, cam=[(0, cx, cy - 250, 0.52), (r(at(43, "Children")), kx, ky, 0.85), (r(at(43, "village")) - 0.5, cx, cy, 0.72), (d, cx, cy + 40, 0.75)],
                    highlights=[(r(at(43, "Children")), r(at(43, "agreed", end=True)), kids), (r(at(43, "village")) - 0.5, r(at(43, "Christians", end=True)), six)],
                    overlays=[lower("The proclamation of 1609", "Clauses 5 and 9: who could stay", 0.6, r(at(43, "Children")) - 0.4)])
shot(ps(43) - 0.2, bando_clauses)
def bando_exempt(d):
    bx = doc_lines("losmoriscosespa02borouoft", 206, BAN_E, "los que de tiempo atrás considerable", "habitación")
    cx, cy = center_of(bx)
    r = lambda x: x - ps(44) + 0.4
    return Document(BAN_E, d, cam=[(0, cx, cy + 100, 0.6), (r(ps(44)) + 0.5, cx, cy + 260, 0.95), (d, cx, cy + 270, 1.0)],
                    highlights=[(r(ps(44)), r(pe(44)), bx)],
                    panel=(r(ps(44)), [w for w, _ in words_of(44)], [r(tt) for _, tt in words_of(44)], "Clauses 11 and 12  ·  English translation"))
shot(ps(44) - 0.4, bando_exempt)
shot(ps(45) - 0.2, lambda d: Still("collins/avila.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08))
shot(at(45, "town") - 0.4, lambda d: Still("collins/segovia_aqueduct.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.45, 1.0), parallax=0.08,
                                   overlays=[lower("Villarrubia de los Ojos", "La Mancha, where neighbors defended the Moriscos", 0.6)]))
shot(ps(46) - 0.2, lambda d: photo("loc/alhambra_sierra_nevada.jpg", d, start=(0.5, 0.45, 1.12), end=(0.5, 0.42, 1.0), parallax=0.10))
shot(at(46, "If"), lambda d: photo("loc/granada_tombs_catholic_monarchs.jpg", d, start=(0.5, 0.5, 1.18), end=(0.5, 0.55, 1.0), parallax=0.10))

# PART SEVEN: THE ONES WHO STAYED
shot(ps(47), lambda d: Still("collins/burgos_cathedral.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(48) - 0.2, lambda d: photo("loc/burgos_escalera_dorada.jpg", d, start=(0.5, 0.6, 1.0), end=(0.5, 0.45, 1.15), parallax=0.10,
                                   overlays=[lower("Burgos Cathedral", "See of Pablo de Santa María and Alonso de Cartagena", 0.8)]))
shot(at(48, "His"), lambda d: Still("collins/burgos_capilla_mayor.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(49) - 0.2, lambda d: Still("loc/columbus_departure_print.jpg", d, end=(0.5, 0.5, 1.15), tone="sepia", parallax=0.06,
                                   overlays=[lower("Columbus departs, 1492", "Print, c. 1850  ·  Library of Congress", 0.8)]))
shot(ps(50) - 0.2, lambda d: Still("collins/granada_cathedral.jpg", d, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08,
                                   overlays=[lower("Hernando de Talavera", "Archbishop of Granada, 1493–1507", 0.8)]))
shot(ps(51) - 0.2, lambda d: Still("lanepoole/generalife_garden.jpg", d, end=(0.5, 0.45, 1.15), tone="sepia", parallax=0.08))
shot(at(51, "He"), lambda d: Still("collins/granada_generalife.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("The Generalife, Granada", "Held for generations by the Granada Venegas", 0.6)]))
shot(ps(52) - 0.2, lambda d: Still("lanepoole/shield_king_of_granada.jpg", d, end=(0.5, 0.5, 1.15), tone="sepia",
                                   overlays=[lower("Shield of a king of Granada", "The Nasrid dynasty", 0.8)]))
shot(at(52, "In"), lambda d: photo("loc/escorial_monastery.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08,
                                   overlays=[lower("El Escorial", "Where Muley al-Shaykh was baptized in 1593", 0.6)]))
shot(ps(53) - 0.2, lambda d: Still("lanepoole/koran_case_escorial.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.5, 1.0), tone="sepia",
                                   overlays=[lower("The Escorial library", "Its Arabic manuscripts were catalogued by Alonso del Castillo", 0.8)]))
shot(at(53, "Miguel"), lambda d: photo("loc/escorial_plaza.jpg", d, end=(0.5, 0.45, 1.12), parallax=0.08))
shot(ps(54) - 0.2, lambda d: photo("loc/avila_walls_1904.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.10, tone="sepia",
                                   overlays=[lower("Ávila", "Home of Saint Teresa", at(54, "Ávila") - ps(54))]))
shot(at(54, "John"), lambda d: Still("collins/avila.jpg", d, start=(0.5, 0.45, 1.15), end=(0.5, 0.5, 1.0), parallax=0.08))
shot(ps(55) - 0.2, lambda d: Still("collins/saragossa_la_seo.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))

# PART EIGHT: PURITY OF BLOOD
shot(ps(56), lambda d: Still("loc/toledo_cathedral_close.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08, tone="sepia",
                             overlays=[lower("Toledo, 1449", "Where the first purity of blood statute was drawn up", 0.8)]))
shot(ps(57) - 0.2, lambda d: Still("collins/toledo_cathedral.jpg", d, start=(0.5, 0.5, 1.15), end=(0.5, 0.45, 1.0), parallax=0.08))
shot(ps(58) - 0.2, lambda d: Still("loc/toledo_cathedral_gate_of_lions.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08, tone="sepia",
                                   overlays=[lower("Toledo Cathedral", "Its chapter adopted a statute in 1547", at(58, "1547") - ps(58) - 0.5)]))
shot(ps(59) - 0.2, lambda d: Still("collins/leon_cathedral.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(60) - 0.2, lambda d: Still("collins/santiago_south_door.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(61) - 0.2, lambda d: photo("loc/avila_view_1860.jpg", d, end=(0.5, 0.5, 1.15), parallax=0.10, tone="sepia"))

# CLOSING
shot(ps(62), lambda d: Still("collins/oviedo_cathedral.jpg", d, end=(0.5, 0.45, 1.15), parallax=0.08))
shot(ps(63) - 0.2, lambda d: photo("loc/cordoba_bridge.jpg", d, end=(0.5, 0.45, 1.12), parallax=0.08))
shot(at(63, "Many"), lambda d: Still("collins/seville_giralda_collins.jpg", d, end=(0.5, 0.4, 1.12), parallax=0.08))
r64 = lambda x: x - ps(64)
shot(ps(64) - 0.2, lambda d: MapShot(d, cam=[(0, -6.5, 40.5, 12.5), (d, -6.6, 40.4, 11.5)],
                                     arrows=[(r64(at(64, "carried")), r64(at(64, "997", end=True)) + 0.4, [(-8.54, 42.88), (-6.9, 40.7), (-4.78, 37.88)], RED),
                                             (r64(at(64, "carried", 2)), r64(at(64, "1236", end=True)) + 0.4, [(-4.78, 37.88), (-6.3, 40.2), (-8.54, 42.88)], GREEN)],
                                     labels=[(0.3, -8.54, 42.88, "Santiago", None), (0.6, -4.78, 37.88, "Córdoba", None)]))
shot(at(64, "To"), lambda d: Still("collins/santiago_cathedral.jpg", d, start=(0.5, 0.5, 1.0), end=(0.5, 0.42, 1.18), parallax=0.10,
                                   overlays=[Fade(d - 3.5, d - 0.3, out=True)]))


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
    c = {"intro": [0, T_TITLE], "title": [T_TITLE - 0.5, T_TITLE + TITLE + 1], "conquest": [ps(4) - 0.5, pe(5) + 0.8],
         "lament": [ps(6), pe(7) + 1.2], "conquest2": [ps(14) - 0.3, pe(14) + 0.6], "conquest3": [ps(36) - 0.3, pe(36) + 0.6],
         "lament2": [ps(44) - 0.5, pe(44) + 1.0], "closing": [ps(62), TOTAL]}
    return c


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
