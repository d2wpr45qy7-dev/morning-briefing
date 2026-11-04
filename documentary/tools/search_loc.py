import json, sys, time, urllib.parse, urllib.request
UA = {"User-Agent": "DocBuilder/1.0 (educational history documentary)"}
for q in sys.argv[1:]:
    u = "https://www.loc.gov/photos/?" + urllib.parse.urlencode({"q": q, "fo": "json", "c": 12, "fa": "online-format:image"})
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
    except Exception as e:
        print("##", q, "ERROR", e); continue
    print("##", q)
    for r in d.get("results", []):
        print(f"   {r.get('id','').rstrip('/').split('/')[-1]:>12}  {r.get('date','')[:4]}  {r.get('title','')[:85]}")
    time.sleep(1.2)
