#!/usr/bin/env python3
"""
Regenerates index.html for the Morning Briefing GitHub Pages site.
Scans ./pdfs/ for files named Morning-Briefing-YYYY-MM-DD.pdf and builds:
  - index.html: shows the most recent PDF inline + a download link + archive list.
Run this from the repo root (the directory containing pdfs/).
"""
import os
import re
import datetime
import sys

REPO_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PDF_DIR = os.path.join(REPO_ROOT, "pdfs")
PATTERN = re.compile(r"^Morning-Briefing-(\d{4}-\d{2}-\d{2})\.pdf$")

def load_dates():
    dates = []
    if os.path.isdir(PDF_DIR):
        for fname in os.listdir(PDF_DIR):
            m = PATTERN.match(fname)
            if m:
                dates.append(m.group(1))
    dates.sort(reverse=True)
    return dates

def pretty(date_str):
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")

def build_html(dates):
    if not dates:
        latest_block = "<p>No briefings published yet. Check back tomorrow morning.</p>"
    else:
        latest = dates[0]
        latest_file = f"pdfs/Morning-Briefing-{latest}.pdf"
        latest_block = f"""
    <div class='today-tag'>TODAY &mdash; {pretty(latest)}</div>
    <a class='pdf-button' href='{latest_file}'>Open Today's Briefing (PDF)</a>
    <div class='viewer-wrap'>
      <embed src='{latest_file}' type='application/pdf' class='viewer'>
    </div>
"""

    archive_items = ""
    for d in dates[1:22]:
        archive_items += f"      <li><a href='pdfs/Morning-Briefing-{d}.pdf'>{pretty(d)}</a></li>\n"
    if not archive_items:
        archive_items = "      <li class='muted'>Nothing archived yet.</li>\n"

    html = f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>The Morning Briefing</title>
<style>
  body {{
    background: #fbf7ef;
    color: #1a1a1a;
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 0 16px 40px 16px;
  }}
  .masthead {{
    max-width: 760px;
    margin: 0 auto;
    border-top: 4px double #1a1a1a;
    border-bottom: 4px double #1a1a1a;
    padding: 10px 0;
    text-align: center;
    margin-top: 24px;
  }}
  .masthead h1 {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 30px;
    margin: 4px 0;
    letter-spacing: 0.5px;
  }}
  .masthead .sub {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #555;
  }}
  .content {{
    max-width: 760px;
    margin: 20px auto;
  }}
  .today-tag {{
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #a11f1f;
    margin-bottom: 8px;
    text-align: center;
  }}
  .pdf-button {{
    display: block;
    text-align: center;
    background: #143a63;
    color: #fbf7ef;
    text-decoration: none;
    font-size: 17px;
    font-weight: 600;
    padding: 14px 20px;
    border-radius: 6px;
    margin: 0 auto 20px auto;
    max-width: 420px;
  }}
  .viewer-wrap {{
    border: 1px solid #ccc;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    margin-bottom: 30px;
  }}
  .viewer {{
    width: 100%;
    height: 80vh;
    display: block;
  }}
  .archive {{
    margin-top: 10px;
  }}
  .archive h2 {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 18px;
    border-bottom: 2px solid #1a1a1a;
    padding-bottom: 6px;
  }}
  .archive ul {{
    list-style: none;
    padding: 0;
    margin: 0;
  }}
  .archive li {{
    padding: 7px 0;
    border-bottom: 1px solid #ddd;
    font-size: 14px;
  }}
  .archive a {{
    color: #143a63;
    text-decoration: none;
  }}
  .archive a:hover {{
    text-decoration: underline;
  }}
  .muted {{
    color: #888;
  }}
  footer {{
    max-width: 760px;
    margin: 30px auto 0 auto;
    text-align: center;
    font-size: 11px;
    color: #888;
  }}
</style>
</head>
<body>
  <div class='masthead'>
    <div class='sub'>Prepared for Marcus Johnson &middot; San Antonio, Texas</div>
    <h1>The Morning Briefing</h1>
    <div class='sub'>Politics &middot; Law &middot; Middle East &middot; Rome &middot; The World</div>
  </div>
  <div class='content'>
{latest_block}
    <div class='archive'>
      <h2>Archive</h2>
      <ul>
{archive_items}      </ul>
    </div>
  </div>
  <footer>Updates automatically every morning.</footer>
</body>
</html>
"""
    return html

if __name__ == "__main__":
    dates = load_dates()
    html = build_html(dates)
    with open(os.path.join(REPO_ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated index.html with {len(dates)} briefing(s). Latest: {dates[0] if dates else 'none'}")
