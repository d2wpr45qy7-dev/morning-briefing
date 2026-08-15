#!/usr/bin/env python3
"""
Regenerates essays.html (an index of every weekly essay set) and one
rendered HTML page per week (essays/essays-YYYY-MM-DD.html), for the
Morning Briefing GitHub Pages site. This is separate from the daily PDF
briefing -- these are the weekly-essay-set task's four essays, published as
their own section of the website, not folded into the newspaper PDF.

Scans ./essays/ for source markdown files named:
  essays-YYYY-MM-DD.md
(written by the weekly-essay-set scheduled task) and converts each to a
styled HTML page matching the site's light/dark theme, plus an index page
(essays.html) listing every week with that week's four essay titles as
quick links.

Requires: pip install markdown
Run this from the repo root (the directory containing essays/).
"""
import os
import re
import sys
import glob
import datetime

try:
    import markdown as md
except ImportError:
    print("ERROR: the 'markdown' package isn't installed. Run: pip install markdown --break-system-packages", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
ESSAYS_DIR = os.path.join(REPO_ROOT, "essays")
FILE_PATTERN = re.compile(r"^essays-(\d{4}-\d{2}-\d{2})\.md$")

BASE_CSS = """
  :root {
    --bg: #fbf7ef; --text: #1a1a1a; --sub: #555; --rule: #1a1a1a;
    --accent: #a11f1f; --button-bg: #143a63; --button-text: #fbf7ef;
    --link: #143a63; --divider: #ddd; --muted: #888;
    --toggle-bg: #eee2cf; --toggle-text: #1a1a1a; --toggle-border: #1a1a1a;
    --card-bg: #fff; --card-border: #e4ddcc;
  }
  html[data-theme='dark'] {
    --bg: #15130f; --text: #ece5d8; --sub: #b3a998; --rule: #ece5d8;
    --accent: #e2795f; --button-bg: #3f6ea5; --button-text: #101010;
    --link: #7ea6d8; --divider: #332f27; --muted: #8f8a7c;
    --toggle-bg: #2a261e; --toggle-text: #ece5d8; --toggle-border: #ece5d8;
    --card-bg: #1c1913; --card-border: #332f27;
  }
  * { transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; margin: 0; padding: 0 16px 40px 16px; }
  .theme-toggle { max-width: 760px; margin: 14px auto 0 auto; display: flex; justify-content: flex-end; }
  .theme-toggle button { font-family: inherit; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; background: var(--toggle-bg); color: var(--toggle-text); border: 1px solid var(--toggle-border); border-radius: 999px; padding: 6px 14px; cursor: pointer; }
  .masthead { max-width: 760px; margin: 10px auto 0 auto; border-top: 4px double var(--rule); border-bottom: 4px double var(--rule); padding: 10px 0; text-align: center; }
  .masthead h1 { font-family: Georgia, 'Times New Roman', serif; font-size: 30px; margin: 4px 0; letter-spacing: 0.5px; }
  .masthead .sub { font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: var(--sub); }
  .nav-row { max-width: 760px; margin: 8px auto 0 auto; text-align: center; font-size: 12px; }
  .nav-row a { color: var(--link); text-decoration: none; margin: 0 8px; }
  .nav-row a:hover { text-decoration: underline; }
  .content { max-width: 760px; margin: 20px auto; }
  footer { max-width: 760px; margin: 30px auto 0 auto; text-align: center; font-size: 11px; color: var(--muted); }
"""

SCRIPT_BLOCK = """
<script>
  (function() {
    var stored = localStorage.getItem('mb-theme');
    var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  })();
</script>
"""

TOGGLE_SCRIPT = """
<script>
  function toggleTheme() {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('mb-theme', next);
  }
</script>
"""


def pretty(date_str):
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "essay"


def load_essay_files():
    files = []
    if os.path.isdir(ESSAYS_DIR):
        for fname in os.listdir(ESSAYS_DIR):
            m = FILE_PATTERN.match(fname)
            if m:
                files.append((m.group(1), os.path.join(ESSAYS_DIR, fname)))
    files.sort(key=lambda x: x[0], reverse=True)
    return files


def page_shell(title_html, sub, body_html, nav_html):
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='color-scheme' content='light dark'>
<title>{title_html} &mdash; The Morning Briefing</title>
<style>
{BASE_CSS}
  .essay-body h1 {{ font-family: Georgia, 'Times New Roman', serif; font-size: 24px; margin-top: 0; }}
  .essay-body h2 {{ font-family: Georgia, 'Times New Roman', serif; font-size: 20px; border-bottom: 2px solid var(--rule); padding-bottom: 6px; margin-top: 40px; scroll-margin-top: 20px; }}
  .essay-body p {{ line-height: 1.6; font-size: 15px; }}
  .essay-body strong {{ color: var(--accent); }}
  .essay-body a {{ color: var(--link); }}
  .essay-index-list {{ list-style: none; padding: 0; margin: 0; }}
  .essay-week {{ border: 1px solid var(--card-border); background: var(--card-bg); border-radius: 8px; padding: 14px 18px; margin-bottom: 14px; }}
  .essay-week .week-date {{ font-weight: bold; font-size: 13px; margin-bottom: 8px; }}
  .essay-week .week-date a {{ color: var(--text); text-decoration: none; }}
  .essay-week ul {{ margin: 0; padding-left: 18px; font-size: 13px; }}
  .essay-week li {{ margin-bottom: 4px; }}
  .essay-week a {{ color: var(--link); text-decoration: none; }}
  .essay-week a:hover {{ text-decoration: underline; }}
</style>
{SCRIPT_BLOCK}
</head>
<body>
  <div class='theme-toggle'><button onclick='toggleTheme()' aria-label='Toggle dark mode'>&#9788; / &#9790;</button></div>
  <div class='masthead'>
    <div class='sub'>Prepared for Marcus Johnson &middot; San Antonio, Texas</div>
    <h1>The Morning Briefing</h1>
    <div class='sub'>{sub}</div>
  </div>
  <div class='nav-row'>{nav_html}</div>
  <div class='content'>
{body_html}
  </div>
  <footer>Weekly essays, published Saturdays.</footer>
{TOGGLE_SCRIPT}
</body>
</html>
"""


def build_week_page(date_str, raw_md):
    html_body = md.markdown(raw_md, extensions=['extra'])
    # tag each H2 with an id matching its slug so the index can deep-link
    def add_id(m):
        text = m.group(1)
        return f"<h2 id='{slugify(re.sub('<.*?>', '', text))}'>{text}</h2>"
    html_body = re.sub(r"<h2>(.*?)</h2>", add_id, html_body)
    nav = "<a href='../index.html'>&larr; Briefing</a> &middot; <a href='../essays.html'>All Essays</a>"
    return page_shell(pretty(date_str), f"Weekly Essays &middot; {pretty(date_str)}", f"<div class='essay-body'>{html_body}</div>", nav)


def extract_titles(raw_md):
    return [line[3:].strip() for line in raw_md.splitlines() if line.startswith("## ")]


def build_index_page(files):
    if not files:
        list_html = "<p>No essays published yet. Check back Saturday.</p>"
    else:
        rows = []
        for date_str, path in files:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            titles = extract_titles(raw)
            items = "".join(
                f"<li><a href='essays/essays-{date_str}.html#{slugify(t)}'>{t}</a></li>" for t in titles
            )
            rows.append(f"""
    <div class='essay-week'>
      <div class='week-date'><a href='essays/essays-{date_str}.html'>{pretty(date_str)}</a></div>
      <ul>{items}</ul>
    </div>""")
        list_html = f"<div class='essay-index-list'>{''.join(rows)}</div>"
    nav = "<a href='index.html'>&larr; Briefing</a>"
    return page_shell("Weekly Essays", "Weekly Essays &middot; Politics, History/Philosophy, Conversation, Science", list_html, nav)


def main():
    files = load_essay_files()
    os.makedirs(ESSAYS_DIR, exist_ok=True)

    for date_str, path in files:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        out_path = os.path.join(ESSAYS_DIR, f"essays-{date_str}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(build_week_page(date_str, raw))

    with open(os.path.join(REPO_ROOT, "essays.html"), "w", encoding="utf-8") as f:
        f.write(build_index_page(files))

    print(f"Generated essays.html + {len(files)} weekly essay page(s). Latest: {files[0][0] if files else 'none'}")


if __name__ == "__main__":
    main()
