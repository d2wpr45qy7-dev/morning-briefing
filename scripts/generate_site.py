#!/usr/bin/env python3
"""
Regenerates index.html for the Morning Briefing GitHub Pages site.
Scans ./pdfs/ for files named:
  Morning-Briefing-YYYY-MM-DD.pdf        (light edition)
  Morning-Briefing-YYYY-MM-DD-dark.pdf   (dark edition, optional)
and builds index.html: shows the most recent day's briefing inline (light or
dark PDF chosen automatically based on the visitor's OS color-scheme, with a
manual toggle that overrides it) + a download link for both editions + an
archive list.
Run this from the repo root (the directory containing pdfs/).
"""
import os
import re
import datetime
import sys

REPO_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PDF_DIR = os.path.join(REPO_ROOT, "pdfs")
LIGHT_PATTERN = re.compile(r"^Morning-Briefing-(\d{4}-\d{2}-\d{2})\.pdf$")
DARK_PATTERN = re.compile(r"^Morning-Briefing-(\d{4}-\d{2}-\d{2})-dark\.pdf$")


def load_dates():
    """Returns dates (desc) that have at least a light PDF, and the set of
    dates that also have a dark PDF."""
    light_dates = []
    dark_dates = set()
    if os.path.isdir(PDF_DIR):
        for fname in os.listdir(PDF_DIR):
            m = LIGHT_PATTERN.match(fname)
            if m:
                light_dates.append(m.group(1))
                continue
            m = DARK_PATTERN.match(fname)
            if m:
                dark_dates.add(m.group(1))
    light_dates.sort(reverse=True)
    return light_dates, dark_dates


def pretty(date_str):
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def build_html(dates, dark_dates):
    if not dates:
        latest_block = "<p>No briefings published yet. Check back tomorrow morning.</p>"
    else:
        latest = dates[0]
        light_file = f"pdfs/Morning-Briefing-{latest}.pdf"
        has_dark = latest in dark_dates
        dark_file = f"pdfs/Morning-Briefing-{latest}-dark.pdf" if has_dark else light_file

        dl_row = f"<a class='pdf-button' id='pdf-open-btn' href='{light_file}' data-light='{light_file}' data-dark='{dark_file}'>Open Today's Briefing (PDF)</a>"
        edition_note = (
            "<div class='edition-note'>Auto-matches your device's light/dark setting. "
            f"Direct links: <a href='{light_file}'>light edition</a>"
            + (f" &middot; <a href='{dark_file}'>dark edition</a>" if has_dark else " (dark edition not available for today)")
            + "</div>"
        )

        latest_block = f"""
    <div class='today-tag'>TODAY &mdash; {pretty(latest)}</div>
    {dl_row}
    {edition_note}
    <div class='viewer-wrap'>
      <embed src='{light_file}' type='application/pdf' class='viewer' id='pdf-viewer' data-light='{light_file}' data-dark='{dark_file}'>
    </div>
"""

    archive_items = ""
    for d in dates[1:22]:
        light_file = f"pdfs/Morning-Briefing-{d}.pdf"
        row = f"<a href='{light_file}'>{pretty(d)}</a>"
        if d in dark_dates:
            row += f" &middot; <a class='muted-link' href='pdfs/Morning-Briefing-{d}-dark.pdf'>dark</a>"
        archive_items += f"      <li>{row}</li>\n"
    if not archive_items:
        archive_items = "      <li class='muted'>Nothing archived yet.</li>\n"

    html = f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='color-scheme' content='light dark'>
<title>The Morning Briefing</title>
<style>
  :root {{
    --bg: #fbf7ef;
    --text: #1a1a1a;
    --sub: #555;
    --rule: #1a1a1a;
    --accent: #a11f1f;
    --button-bg: #143a63;
    --button-text: #fbf7ef;
    --viewer-border: #ccc;
    --viewer-shadow: rgba(0,0,0,0.08);
    --link: #143a63;
    --divider: #ddd;
    --muted: #888;
    --toggle-bg: #eee2cf;
    --toggle-text: #1a1a1a;
    --toggle-border: #1a1a1a;
  }}
  html[data-theme='dark'] {{
    --bg: #15130f;
    --text: #ece5d8;
    --sub: #b3a998;
    --rule: #ece5d8;
    --accent: #e2795f;
    --button-bg: #3f6ea5;
    --button-text: #101010;
    --viewer-border: #3a352c;
    --viewer-shadow: rgba(0,0,0,0.4);
    --link: #7ea6d8;
    --divider: #332f27;
    --muted: #8f8a7c;
    --toggle-bg: #2a261e;
    --toggle-text: #ece5d8;
    --toggle-border: #ece5d8;
  }}
  * {{ transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 0 16px 40px 16px;
  }}
  .theme-toggle {{
    max-width: 760px;
    margin: 14px auto 0 auto;
    display: flex;
    justify-content: flex-end;
  }}
  .theme-toggle button {{
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
    background: var(--toggle-bg);
    color: var(--toggle-text);
    border: 1px solid var(--toggle-border);
    border-radius: 999px;
    padding: 6px 14px;
    cursor: pointer;
  }}
  .masthead {{
    max-width: 760px;
    margin: 0 auto;
    border-top: 4px double var(--rule);
    border-bottom: 4px double var(--rule);
    padding: 10px 0;
    text-align: center;
    margin-top: 10px;
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
    color: var(--sub);
  }}
  .nav-row {{
    max-width: 760px;
    margin: 8px auto 0 auto;
    text-align: center;
    font-size: 12px;
  }}
  .nav-row a {{
    color: var(--link);
    text-decoration: none;
    margin: 0 8px;
  }}
  .nav-row a:hover {{
    text-decoration: underline;
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
    color: var(--accent);
    margin-bottom: 8px;
    text-align: center;
  }}
  .pdf-button {{
    display: block;
    text-align: center;
    background: var(--button-bg);
    color: var(--button-text);
    text-decoration: none;
    font-size: 17px;
    font-weight: 600;
    padding: 14px 20px;
    border-radius: 6px;
    margin: 0 auto;
    max-width: 420px;
  }}
  .edition-note {{
    text-align: center;
    font-size: 11px;
    color: var(--muted);
    margin: 8px 0 20px 0;
  }}
  .edition-note a {{
    color: var(--link);
  }}
  .viewer-wrap {{
    border: 1px solid var(--viewer-border);
    box-shadow: 0 2px 10px var(--viewer-shadow);
    margin-bottom: 30px;
    background: #fff;
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
    border-bottom: 2px solid var(--rule);
    padding-bottom: 6px;
  }}
  .archive ul {{
    list-style: none;
    padding: 0;
    margin: 0;
  }}
  .archive li {{
    padding: 7px 0;
    border-bottom: 1px solid var(--divider);
    font-size: 14px;
  }}
  .archive a {{
    color: var(--link);
    text-decoration: none;
  }}
  .archive a:hover {{
    text-decoration: underline;
  }}
  .muted-link {{
    color: var(--muted) !important;
    font-size: 12px;
  }}
  .muted {{
    color: var(--muted);
  }}
  footer {{
    max-width: 760px;
    margin: 30px auto 0 auto;
    text-align: center;
    font-size: 11px;
    color: var(--muted);
  }}
</style>
<script>
  (function() {{
    var stored = localStorage.getItem('mb-theme');
    var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  }})();
</script>
</head>
<body>
  <div class='theme-toggle'>
    <button id='theme-toggle-btn' onclick='toggleTheme()' aria-label='Toggle dark mode'>&#9788; / &#9790;</button>
  </div>
  <div class='masthead'>
    <div class='sub'>Prepared for Marcus Johnson &middot; San Antonio, Texas</div>
    <h1>The Morning Briefing</h1>
    <div class='sub'>Politics &middot; Law &middot; Geopolitics &middot; Markets</div>
  </div>
  <div class='nav-row'><a href='essays.html'>Weekly Essays &rarr;</a></div>
  <div class='content'>
{latest_block}
    <div class='archive'>
      <h2>Archive</h2>
      <ul>
{archive_items}      </ul>
    </div>
  </div>
  <footer>Updates automatically every morning.</footer>
  <script>
    function applyPdfEdition() {{
      var theme = document.documentElement.getAttribute('data-theme');
      var viewer = document.getElementById('pdf-viewer');
      var btn = document.getElementById('pdf-open-btn');
      [viewer, btn].forEach(function(el) {{
        if (!el) return;
        var src = theme === 'dark' ? el.getAttribute('data-dark') : el.getAttribute('data-light');
        if (!src) return;
        if (el.tagName === 'EMBED') {{ el.setAttribute('src', src); }}
        else {{ el.setAttribute('href', src); }}
      }});
    }}
    function toggleTheme() {{
      var current = document.documentElement.getAttribute('data-theme');
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('mb-theme', next);
      applyPdfEdition();
    }}
    applyPdfEdition();
  </script>
</body>
</html>
"""
    return html

if __name__ == "__main__":
    dates, dark_dates = load_dates()
    html = build_html(dates, dark_dates)
    with open(os.path.join(REPO_ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated index.html with {len(dates)} briefing(s) ({len(dark_dates)} with a dark edition). Latest: {dates[0] if dates else 'none'}")
