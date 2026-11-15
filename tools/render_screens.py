"""Render every screen in a real browser and check its layout.

Each of the twelve screens is opened at desktop width, at phone width and in
the dark theme (39 renders). For each one the page is checked for: sideways
page scrolling, chart text outside its card, chart labels that overlap, cards
wider than the screen, charts that did not draw, and errors in the browser
console. Desktop and dark renders are also run through axe-core, the standard
accessibility checker (colour contrast, names for charts and controls, heading
order, keyboard reach), and the time from reload to content is recorded for
each screen; axe-core is fetched from a public CDN, and that part is
skipped with a note if it cannot be loaded. A full-page image of every render
is saved so the result can also be checked by eye.

Needs the app running (`python -m tapemark serve`) and Playwright with a
Chromium-family browser:

    pip install -e ".[ui]"
    python tools/render_screens.py [output folder]

Exit code 1 if any screen has a problem.
"""

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/"
ROUTES = ["overview", "guide", "today", "trades", "vol", "markets", "patterns", "price", "lab", "saved", "accuracy", "data"]
AUDIT = """() => {
  const iss = []; const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) iss.push('page scrolls sideways');
  for (const svg of document.querySelectorAll('svg')) {
    const card = svg.closest('.card,.kpi') || svg.parentElement; const cb = card.getBoundingClientRect();
    const texts = [...svg.querySelectorAll('text')].map(t => ({t: t.textContent, b: t.getBoundingClientRect()})).filter(x => x.b.width);
    for (const x of texts) if (x.b.right > cb.right - 1 || x.b.left < cb.left + 1) iss.push('text outside card: ' + x.t);
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) { const a = texts[i].b, b = texts[j].b;
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 2 && oy > 4) iss.push('labels overlap: ' + texts[i].t + ' | ' + texts[j].t); } }
  for (const c of document.querySelectorAll('.card,.kpi')) { if (c.scrollWidth > c.clientWidth + 1) iss.push('card overflow: ' + (c.querySelector('h2,h3,.k')||{}).textContent);
    if (c.getBoundingClientRect().right > vw + 1) iss.push('card wider than screen'); }
  const blank = [...document.querySelectorAll('[data-chart]')].filter(h => !h.querySelector('svg')).length; if (blank) iss.push(blank + ' charts blank');
  const wide = [...document.querySelectorAll('.scroll')].filter(s => s.scrollWidth > s.clientWidth + 1).length;
  return {issues: [...new Set(iss)].slice(0, 6), cards: document.querySelectorAll('.card').length, charts: document.querySelectorAll('[data-chart] svg').length, tables_that_scroll: wide};
}"""
# Ready when the screen has content and nothing on it is still loading, pricing or running.
AXE = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
AXE_RUN = """async () => { const r = await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'best-practice']});
  return r.violations.map(v => v.id + ' (' + v.impact + ', ' + v.nodes.length + ' places)'); }"""
READY = "() => { const v = document.querySelector('#view'); return v && v.querySelector('.card, .kpis') && !/^Loading|Running the model|Pricing…/.test(v.innerText.trim()); }"
SETS = [("desktop", {"viewport": {"width": 1440, "height": 1000}}, ROUTES),
        ("phone", {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}, ROUTES),
        ("dark", {"viewport": {"width": 1440, "height": 1000}, "color_scheme": "dark"}, ROUTES),
        ("dark-phone", {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True, "color_scheme": "dark"}, ["today", "price", "accuracy"])]


def _launch(p):
    for channel in ("msedge", "chrome", None):          # whichever Chromium-family browser is installed
        try:
            return p.chromium.launch(channel=channel, headless=True) if channel else p.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001 - try the next browser
            continue
    raise SystemExit("no Chromium-family browser found; run `playwright install chromium`")


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/reports/screens")
    out.mkdir(parents=True, exist_ok=True)
    report, axe_ok = {}, None
    with sync_playwright() as p:
        browser = _launch(p)
        for name, opts, routes in SETS:
            ctx = browser.new_context(**opts)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m, e=errors: e.append(m.text[:160]) if m.type == "error" else None)
            page.on("pageerror", lambda ex, e=errors: e.append(str(ex)[:160]))
            for r in routes:
                page.goto(BASE + "#" + r)
                began = time.perf_counter()
                page.reload()
                page.wait_for_function(READY, timeout=60000)
                ready_ms = round(1000 * (time.perf_counter() - began))
                page.wait_for_timeout(1800)
                report[f"{name}/{r}"] = page.evaluate(AUDIT) | {"ready_ms": ready_ms}
                page.screenshot(path=str(out / f"{name}-{r}.png"), full_page=True)
                if name in ("desktop", "dark") and axe_ok is not False:
                    try:
                        page.add_script_tag(url=AXE)
                        found = page.evaluate(AXE_RUN)
                        axe_ok = True
                        if found:
                            report[f"{name}/{r}"]["issues"] += [f"accessibility: {f}" for f in found]
                    except Exception:  # noqa: BLE001 - no network, or the CDN is blocked
                        axe_ok = False
            report[f"{name}/console_errors"] = errors
            ctx.close()
        browser.close()
    bad = {k: v for k, v in report.items() if (isinstance(v, dict) and v["issues"]) or (isinstance(v, list) and v)}
    scroll = {k: v["tables_that_scroll"] for k, v in report.items() if isinstance(v, dict) and v["tables_that_scroll"]}
    ready = sorted((v["ready_ms"], k) for k, v in report.items() if isinstance(v, dict) and k.startswith("desktop/"))
    print(json.dumps({"time_to_content_ms": {"median": ready[len(ready) // 2][0], "slowest": f"{ready[-1][1]} {ready[-1][0]}", "second_slowest": f"{ready[-2][1]} {ready[-2][0]}"},
                      "screens_rendered": sum(isinstance(v, dict) for v in report.values()), "with_problems": bad, "tables_that_scroll_sideways": scroll,
                      "accessibility": "checked with axe-core" if axe_ok else "skipped: axe-core could not be loaded", "images": str(out)}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
