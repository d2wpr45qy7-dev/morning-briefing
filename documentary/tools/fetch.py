"""Download every asset listed in an assets JSON file, with credits, so a reset container can rebuild.

usage: fetch.py ASSETS.json
Entry kinds: loc (Library of Congress item id), cma (Cleveland Museum of Art id), ia_file (Internet Archive
identifier + path), ia_page (identifier + 0-based leaf), ia_video (identifier, largest video file), url (direct).
Wikimedia Commons is not used: it refuses file downloads from this environment under its robot policy.
"""
import json, os, re, sys, time, urllib.parse, urllib.request

DOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(DOC, "assets")
UA = {"User-Agent": "DocBuilder/1.0 (educational history documentary)"}


def get(url, timeout=300):
    for i in range(5):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            if i == 4:
                raise
            time.sleep(3 * 2 ** i)


def save_jpeg(data, path, width=3000):
    from PIL import Image
    import io
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(path, quality=92)


def fetch(e):
    path = os.path.join(ASSETS, e["file"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return "cached"
    k = e["kind"]
    if k == "loc":
        d = json.loads(get(f"https://www.loc.gov/item/{e['id']}/?fo=json"))
        files = [f for fs in d["resources"][0]["files"] for f in fs]
        tif = [f["url"] for f in files if f.get("mimetype") == "image/tiff"]
        jpg = sorted([f for f in files if f.get("mimetype") == "image/jpeg"], key=lambda f: f.get("width") or 0)
        save_jpeg(get(tif[0] if tif else jpg[-1]["url"]), path)
    elif k == "cma":
        o = json.loads(get(f"https://openaccess-api.clevelandart.org/api/artworks/{e['id']}"))["data"]
        imgs = o.get("images") or {}
        save_jpeg(get((imgs.get("print") or imgs.get("web"))["url"]), path)
    elif k == "ia_file":
        data = get(f"https://archive.org/download/{e['id']}/{urllib.parse.quote(e['path'])}")
        if path.endswith(".jpg") and not e["path"].lower().endswith(".jpg"):
            save_jpeg(data, path)
        else:
            open(path, "wb").write(data)
    elif k == "ia_page":
        open(path, "wb").write(get(f"https://archive.org/download/{e['id']}/page/n{e['leaf']}.jpg"))
    elif k == "ia_video":
        m = json.loads(get(f"https://archive.org/metadata/{e['id']}"))
        vids = sorted([f for f in m["files"] if f["name"].lower().endswith((".mp4", ".mov", ".avi", ".m4v", ".mkv", ".ogv"))],
                      key=lambda f: -int(f.get("size", 0)))
        open(path, "wb").write(get(f"https://archive.org/download/{e['id']}/{urllib.parse.quote(vids[0]['name'])}", timeout=900))
    elif k == "url":
        open(path, "wb").write(get(e["url"], timeout=900))
    else:
        raise ValueError(k)
    time.sleep(1)
    return "downloaded"


def credits_md(entries, out_path, title):
    lines = [f"# {title}: credits", "",
             "Narration: synthetic voice (Chatterbox TTS, MIT license) conditioned on a synthetic Kokoro voice; no real person's voice is used.",
             "Music: original score composed and synthesized for this film.", "Maps: drawn from Natural Earth (public domain).", "",
             "## Archival images, documents and footage", ""]
    for e in sorted(entries, key=lambda e: e["file"]):
        if e.get("credit") is False:
            continue
        lines.append(f"- {e['title']}. {('By ' + e['artist'] + '. ') if e.get('artist') else ''}License: {e['license']}. Source: {e['source']}")
    open(out_path, "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    entries = json.load(open(sys.argv[1]))
    bad = 0
    for e in entries:
        try:
            r = fetch(e)
        except Exception as ex:
            r = f"FAILED: {ex}"; bad += 1
        print(f"{r:10s} {e['file']}", flush=True)
    print("failures:", bad)
