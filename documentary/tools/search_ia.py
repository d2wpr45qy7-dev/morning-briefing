import json, sys, urllib.parse, urllib.request
UA = {"User-Agent": "DocBuilder/1.0 (educational history documentary)"}
for q in sys.argv[1:]:
    u = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode([("q", q), ("rows", 10), ("output", "json")] + [("fl[]", f) for f in ("identifier", "title", "year", "creator")])
    try:
        docs = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())["response"]["docs"]
    except Exception as e:
        print("##", q, "ERROR", e); continue
    print("##", q)
    for d in docs:
        c = d.get("creator"); c = c if isinstance(c, str) else ", ".join(c or [])
        print(f"   {d['identifier'][:44]:44s} | {str(d.get('title',''))[:58]:58s} | {d.get('year','')} | {c[:30]}")
