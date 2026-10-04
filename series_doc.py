"""The 'REPO list' PDF: every repo posted so far in the series, and ONLY those.

On Day N it lists Days 1..N (built from series_state.json, which only contains
published posts), so an unposted repo can never leak. Rendered by headless Chrome
from HTML, so the links are clickable. Written to docs/100-ai-repos.pdf.
"""
import datetime
import html
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "docs" / "100-ai-repos.pdf"
HTML_OUT = BASE / "docs" / "100-ai-repos.html"


def _card(e, related):
    esc = html.escape
    stars = f"{e['stars']:,} stars" if e.get("stars") else ""
    meta = " · ".join(x for x in (stars, e.get("license") or "", e.get("language") or "") if x)
    qs = (f'<div class="lbl">Quick start (from the README)</div><pre>{esc(e["quickstart"])}</pre>'
          if e.get("quickstart") else "")
    n = (e.get("note") or "").strip()
    note = (f'<div class="note">{esc(n)}</div>'
            if n and n.lower() != (e.get("description") or "").strip().lower() else "")
    rel = (f'<div class="rel">Also in the series: {", ".join(esc(r) for r in related)}</div>'
           if related else "")
    return f"""<section class="card">
  <div class="day">DAY {e['day']}</div>
  <h2><a href="{esc(e['url'])}">{esc(e['name'])}</a></h2>
  <p class="desc">{esc(e.get('description', ''))}</p>
  <div class="meta">{esc(meta)}</div>
  {note}{qs}{rel}
</section>"""


def build_html(state):
    posted = sorted(state["posted"], key=lambda e: e["day"])
    cards = []
    for e in posted:
        related = [o["name"] for o in posted
                   if o["day"] != e["day"] and e.get("category") and o.get("category") == e["category"]][:3]
        cards.append(_card(e, related))
    n = len(posted)
    today = datetime.date.today().strftime("%d %b %Y")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>100 AI Repos Worth Knowing</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#15171c;margin:0;padding:0;line-height:1.45}}
 header{{background:#0d1117;color:#fff;padding:36px 40px}} header h1{{margin:0 0 6px;font-size:30px}}
 header p{{margin:0;color:#c9d1d9}} header .rule{{margin-top:10px;color:#ffc400;font-weight:600}} .wrap{{padding:20px 40px}}
 .card{{border:1px solid #e3e6ea;border-radius:14px;padding:16px 20px;margin:14px 0;page-break-inside:avoid}}
 .day{{display:inline-block;background:#ffc400;color:#141414;font-weight:800;font-size:12px;border-radius:20px;padding:3px 12px}}
 h2{{margin:8px 0 4px;font-size:21px}} h2 a{{color:#0b57d0;text-decoration:none}}
 .desc{{margin:4px 0;font-size:15px}} .meta{{color:#586069;font-size:13px}}
 .note{{margin:8px 0;padding:8px 12px;background:#fff8e1;border-radius:8px;font-size:14px}}
 .lbl{{margin-top:10px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#586069}}
 pre{{background:#0d1117;color:#e6edf3;padding:10px 12px;border-radius:8px;font-size:13px;white-space:pre-wrap;word-break:break-all;margin:4px 0}}
 .rel{{margin-top:8px;font-size:13px;color:#586069}} footer{{padding:10px 40px 30px;color:#6a737d;font-size:12px}}
</style></head><body>
<header><h1>100 AI Repos Worth Knowing</h1>
<p>Days 1&ndash;{n} so far &middot; updated {today} &middot; a new repo every day, in plain words</p>
<p class="rule">Repos are added to this list on the day they are revealed &mdash; check back daily.</p></header>
<div class="wrap">{''.join(cards) or '<p>The first repo goes live soon.</p>'}</div>
<footer>Facts (stars, licence) are from GitHub on the day each repo was posted. Always read a project's own README and licence before relying on it. Not financial advice for any trading-related project.</footer>
</body></html>"""


def build(state):
    """Write docs/100-ai-repos.html and .pdf from the current state."""
    OUT.parent.mkdir(exist_ok=True)
    doc = build_html(state)
    HTML_OUT.write_text(doc, encoding="utf-8")
    from webreel import _launch
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _launch(p)
        pg = b.new_page()
        pg.set_content(doc, wait_until="load")
        pg.pdf(path=str(OUT), format="A4", print_background=True,
               margin={"top": "0", "bottom": "12mm", "left": "0", "right": "0"})
        b.close()
    print(f"[series] wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(state['posted'])} repos)")
    return OUT
