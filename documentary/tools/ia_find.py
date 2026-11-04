"""Find a phrase in an Internet Archive book's DjVu XML and report the page leaf and word boxes.

usage: ia_find.py IDENT "regex" [...]
Prints, for each hit: leaf index (for page/n{leaf}.jpg), page size in the XML, and the matched words' boxes.
"""
import json, os, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "DocBuilder/1.0 (educational history documentary)"}
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
os.makedirs(CACHE, exist_ok=True)


def pages(ident):
    path = os.path.join(CACHE, f"{ident}_djvu.xml")
    if not os.path.exists(path):
        meta = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://archive.org/metadata/{ident}", headers=UA), timeout=120).read())
        name = next(f["name"] for f in meta["files"] if f["name"].endswith("_djvu.xml"))
        data = urllib.request.urlopen(urllib.request.Request(f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}", headers=UA), timeout=600).read()
        open(path, "wb").write(data)
    out = []
    for obj in ET.parse(path).getroot().iter("OBJECT"):
        w, h = int(obj.get("width")), int(obj.get("height"))
        words = []
        for wd in obj.iter("WORD"):
            x0, y1, x1, y0 = map(int, wd.get("coords").split(",")[:4])
            words.append((wd.text or "", x0, y0, x1, y1))
        out.append((w, h, words))
    return out


def find(ident, pattern):
    hits = []
    for leaf, (w, h, words) in enumerate(pages(ident)):
        text, starts = "", []
        for wd in words:
            starts.append(len(text)); text += wd[0] + " "
        for m in re.finditer(pattern, text, re.I):
            idx = [i for i, s in enumerate(starts) if m.start() <= s < m.end()]
            hits.append(dict(leaf=leaf, size=(w, h), words=[words[i] for i in idx], context=text[max(0, m.start() - 100):m.end() + 100]))
    return hits


if __name__ == "__main__":
    ident = sys.argv[1]
    for pat in sys.argv[2:]:
        for h in find(ident, pat)[:6]:
            b = h["words"]
            box = (min(x[1] for x in b), min(x[2] for x in b), max(x[3] for x in b), max(x[4] for x in b)) if b else None
            print(f"{pat!r}: leaf {h['leaf']} size {h['size']} box {box}\n    ...{h['context']}...")
