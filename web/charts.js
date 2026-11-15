// Small SVG chart helpers. No dependencies.
// Rules followed: one y-axis per chart; legend whenever there are two or more
// series; direct labels at line ends; a hover layer on every chart; text in
// ink colours, never in a series colour; labels set with textContent.

const NS = "http://www.w3.org/2000/svg";
export const cv = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}
function s(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}
function txt(parent, x, y, str, attrs = {}) {
  const t = s("text", { x, y, ...attrs }, parent);
  t.textContent = str;
  return t;
}

const tip = () => document.getElementById("tip");
export function showTip(evt, title, rows) {
  const t = tip();
  t.replaceChildren(el("div", { class: "t", text: title }));
  for (const r of rows) {
    const key = el("i");
    if (r.color) key.style.borderTopColor = r.color; else key.style.visibility = "hidden";
    t.append(el("div", { class: "r" }, el("span", {}, key, r.name), el("b", { text: r.value })));
  }
  t.hidden = false;
  const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  t.style.left = `${Math.max(8, x)}px`;
  t.style.top = `${Math.max(8, y)}px`;
}
export const hideTip = () => { tip().hidden = true; };

function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= step0);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/* Draw a chart at the real pixel width of its container, so text never scales.
   The draw function is kept on the host and called again when the window resizes. */
function mount(parent, drawInto) {
  // The chart gets a container of its own, placed where the chart was asked for: what the card already holds stays
  // above it and what is added later goes below. It is drawn a moment after the page is built and redrawn on resize,
  // and each draw clears only this container, so headlines, notes and tables in the same card survive.
  let host = [...parent.children].find((c) => c.classList.contains("chartbox"));
  if (!host) { host = el("div", { class: "chartbox" }); parent.append(host); }
  host.dataset.chart = "1";
  host._draw = () => {
    if (!(host.isConnected && host.clientWidth)) return;
    drawInto(host, Math.max(260, Math.floor(host.clientWidth)));
    // Name the chart for screen readers from the heading of the card or panel it sits in.
    const box = host.closest("section, .card"), title = box?.querySelector("h2, h3")?.textContent;
    host.querySelector("svg[role=img]")?.setAttribute("aria-label", title ? `Chart: ${title}` : "Chart");
  };
  // A timer, not an animation frame: frames stop while the tab is in the background and the chart would stay blank.
  let tries = 0, drawn = 0;
  const go = () => {
    if (host.isConnected && host.clientWidth) { drawn = host.clientWidth; host._draw(); watch?.observe(host); }
    else if (tries++ < 200) setTimeout(go, 25);
  };
  // Redraw when the card itself changes width (a sidebar collapsing, a phone rotating), not only the window.
  const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
    if (!host.isConnected) { watch.disconnect(); return; }
    if (Math.abs(host.clientWidth - drawn) > 4) { drawn = host.clientWidth; host._draw(); }
  });
  go();
}
export function redrawAll() { for (const h of document.querySelectorAll("[data-chart]")) h._draw?.(); }

export function legend(series) {
  return el("div", { class: "legend" }, series.map((x) => {
    const key = el("i", { class: x.box ? "box" : x.dash ? "dash" : "" });
    if (x.box) key.style.background = x.color; else key.style.borderTopColor = x.color;
    return el("span", {}, key, x.name);
  }));
}

/* Line chart over an ordered x (index). series: [{name, color, dash, values}], labels: x labels. */
export const line = (parent, o) => mount(parent, (host, W) => drawLine(host, o, W));
/* Options beyond the basics:
   xtext    text for each tick in `xticks` (for example month names on a daily series)
   ydomain  [low, high] to fix the y-range, so a small wobble is not drawn as a large one
   a series with `markers: true` is drawn as labelled points with no connecting line: use it when the points are few and
   a line between them would suggest values that were never measured. */
function drawLine(host, { series, labels, yfmt = (v) => v.toFixed(2), h = 230, xticks, xtext, ydomain, ref, dots, endLabels = true, zero = false }, W) {
  host.replaceChildren();
  if (series.length > 1) host.append(legend(series));
  endLabels = endLabels && W >= 460;  // no room for labels at the line ends in a narrow card; the legend carries the names
  const L = 50, T = 10, B = 24;
  const R = Math.max(endLabels ? Math.min(160, 14 + 6.6 * Math.max(...series.map((x) => x.name.length))) : 14, ref?.label ? 12 + 6.6 * ref.label.length : 0);
  const svg = s("svg", { viewBox: `0 0 ${W} ${h}`, width: W, height: h, role: "img" }, null);
  const vals = series.flatMap((x) => x.values).concat(dots ? dots.map((d) => d.y) : [], ref ? [ref.y] : [], zero ? [0] : []).filter((v) => v != null && isFinite(v));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const padY = (hi - lo || 1) * 0.08; lo -= padY; hi += padY;
  if (ydomain) [lo, hi] = ydomain;
  const n = labels.length, X = (i) => L + (n === 1 ? 0.5 : i / (n - 1)) * (W - L - R), Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
  for (const t of niceTicks(lo, hi)) {
    s("line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: cv("--grid") }, svg);
    txt(svg, L - 6, Y(t) + 4, yfmt(t), { "text-anchor": "end" });
  }
  // As many x labels as fit without touching, evenly spaced.
  const room = Math.max(2, Math.floor((W - L - R) / (Math.max(...labels.map((l) => String(l).length)) * 6.4 + 18)));
  const spread = (k) => [...new Set(Array.from({ length: k }, (_, i) => Math.round(i * (n - 1) / (k - 1))))];
  if (xtext) {                               // caller-chosen ticks with their own text; thin them out if they cannot all fit
    let edge = -Infinity;                    // right edge of the last label drawn; the next one must clear it
    xticks.forEach((i, k) => {
      const w = xtext[k].length * 6.4, anchor = X(i) - w / 2 < L ? "start" : X(i) + w / 2 > W - 2 ? "end" : "middle";
      const left = anchor === "start" ? X(i) : anchor === "end" ? X(i) - w : X(i) - w / 2;
      if (left < edge + 10) return;
      txt(svg, X(i), h - 6, xtext[k], { "text-anchor": anchor });
      edge = left + w;
    });
  } else {
    const tx = xticks && xticks.length <= room ? xticks : spread(Math.min(room, 5, n));
    for (const i of tx) txt(svg, X(i), h - 6, labels[i], { "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" });
  }
  if (ref) {
    s("line", { x1: L, x2: W - R, y1: Y(ref.y), y2: Y(ref.y), stroke: cv("--axis"), "stroke-dasharray": "4 4" }, svg);
    txt(svg, W - R + 4, Y(ref.y) + 4, ref.label, { class: "lab" });
  }
  const ends = [];
  for (const x of series) {
    let d = "", pen = false, last = null;
    x.values.forEach((v, i) => {
      if (v == null || !isFinite(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true; last = [i, v];
    });
    if (x.markers) {
      x.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) return;
        s("circle", { cx: X(i), cy: Y(v), r: 5, fill: x.color, stroke: cv("--surface"), "stroke-width": 2 }, svg);
        txt(svg, X(i), Y(v) - 10, yfmt(v), { "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", class: "lab" });
      });
    } else s("path", { d, fill: "none", stroke: x.color, "stroke-width": 2, "stroke-dasharray": x.dash ? "5 4" : null, "stroke-linejoin": "round" }, svg);
    if (last && endLabels) ends.push({ y: Y(last[1]), name: x.name, x: X(last[0]) });
  }
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 12) ends[i].y = ends[i - 1].y + 12;
  for (const e of ends) txt(svg, e.x + 6, e.y + 4, e.name, { class: "lab" });
  if (dots) for (const d of dots) s("circle", { cx: X(d.i), cy: Y(d.y), r: 4, fill: d.color, stroke: cv("--surface"), "stroke-width": 2 }, svg);
  const hair = s("line", { y1: T, y2: h - B, stroke: cv("--axis"), visibility: "hidden" }, svg);
  const marks = series.map((x) => s("circle", { r: 4, fill: x.color, stroke: cv("--surface"), "stroke-width": 2, visibility: "hidden" }, svg));
  const hit = s("rect", { x: L, y: T, width: W - L - R, height: h - T - B, fill: "transparent" }, svg);
  hit.addEventListener("pointermove", (evt) => {
    const box = svg.getBoundingClientRect();
    const px = (evt.clientX - box.left) / box.width * W;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - L) / (W - L - R) * (n - 1))));
    hair.setAttribute("x1", X(i)); hair.setAttribute("x2", X(i)); hair.setAttribute("visibility", "visible");
    series.forEach((x, k) => {
      const v = x.values[i], ok = v != null && isFinite(v);
      marks[k].setAttribute("visibility", ok ? "visible" : "hidden");
      if (ok) { marks[k].setAttribute("cx", X(i)); marks[k].setAttribute("cy", Y(v)); }
    });
    const rows = series.filter((x) => x.values[i] != null).map((x) => ({ name: x.name, color: x.color, value: yfmt(x.values[i]) }));
    if (dots) for (const d of dots.filter((d) => d.i === i)) rows.push({ name: d.name, color: d.color, value: yfmt(d.y) });
    showTip(evt, labels[i], rows);
  });
  hit.addEventListener("pointerleave", () => { hair.setAttribute("visibility", "hidden"); marks.forEach((m) => m.setAttribute("visibility", "hidden")); hideTip(); });
  host.append(svg);
}

/* Vertical bars. series: [{name, color, values}]; stacked or grouped; bySign colours one series by sign. */
export const bars = (parent, o) => mount(parent, (host, W) => drawBars(host, o, W));
/* catColors gives each category its own colour (one series only), to single one bar out from the rest. */
function drawBars(host, { cats, series, yfmt = (v) => v.toFixed(1), h = 220, stacked = false, bySign = false, valueLabels = false, catColors }, W) {
  host.replaceChildren();
  if (series.length > 1) host.append(legend(series.map((x) => ({ ...x, box: true }))));
  const L = 50, R = 10, T = 14;
  // Category names wrap onto as many lines as they need, so every bar keeps its name.
  const perLine = Math.max(1, Math.floor(((W - L - R) / cats.length - 6) / 6.4));
  const wrapped = cats.map((c) => {
    const out = [];
    for (const word of String(c).split(" ")) {
      if (out.length && (out[out.length - 1] + " " + word).length <= perLine) out[out.length - 1] += " " + word;
      else out.push(word);
    }
    return out;
  });
  const fits = wrapped.every((ls) => ls.length <= 3 && ls.every((l) => l.length <= perLine));  // otherwise every n-th name is shown
  const B = 14 + 13 * (fits ? Math.max(...wrapped.map((ls) => ls.length)) : 1);
  const svg = s("svg", { viewBox: `0 0 ${W} ${h}`, width: W, height: h, role: "img" }, null);
  const totals = cats.map((_, i) => series.reduce((a, x) => a + Math.max(x.values[i] || 0, 0), 0));
  const all = stacked ? totals.concat([0]) : series.flatMap((x) => x.values).concat([0]).filter((v) => v != null);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo || 1) * 0.1; hi += hi > 0 ? pad : 0; lo -= lo < 0 ? pad : 0;
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (h - T - B), band = (W - L - R) / cats.length;
  for (const t of niceTicks(lo, hi)) {
    s("line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: t === 0 ? cv("--axis") : cv("--grid") }, svg);
    txt(svg, L - 6, Y(t) + 4, yfmt(t), { "text-anchor": "end" });
  }
  const bar = (x, y0, y1, w, color, title, rows) => {
    const top = Math.min(y0, y1), ht = Math.max(Math.abs(y1 - y0), 1), r = Math.min(3, w / 2, ht);
    const up = y1 <= y0;
    const d = up ? `M${x} ${top + ht}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + w - r}Q${x + w} ${top} ${x + w} ${top + r}V${top + ht}Z`
                 : `M${x} ${top}V${top + ht - r}Q${x} ${top + ht} ${x + r} ${top + ht}H${x + w - r}Q${x + w} ${top + ht} ${x + w} ${top + ht - r}V${top}Z`;
    const p = s("path", { d, fill: color, tabindex: 0 }, svg);
    const hitbox = s("rect", { x: x - 1, y: top - 6, width: w + 2, height: ht + 12, fill: "transparent" }, svg);
    for (const target of [hitbox, p]) {
      target.addEventListener("pointermove", (evt) => { p.setAttribute("opacity", 0.8); showTip(evt, title, rows); });
      target.addEventListener("pointerleave", () => { p.setAttribute("opacity", 1); hideTip(); });
    }
  };
  cats.forEach((c, i) => {
    const x0 = L + i * band, gap = Math.min(10, band * 0.18);
    const every = Math.ceil((Math.max(...cats.map((k) => String(k).length)) * 6.6 + 6) / band);  // skip labels that would collide
    if (fits) wrapped[i].forEach((l, k) => txt(svg, x0 + band / 2, h - B + 16 + 13 * k, l, { "text-anchor": "middle" }));
    else if (i % every === 0) txt(svg, x0 + band / 2, h - 8, c, { "text-anchor": "middle" });
    const rows = series.map((x) => ({ name: x.name, color: bySign ? null : x.color, value: x.values[i] == null ? "none" : yfmt(x.values[i]) }));
    if (stacked) {
      let acc = 0;
      for (const x of series) {
        const v = x.values[i] || 0; if (v <= 0) continue;
        const sw = Math.min(band - 2 * gap, 72);
        bar(x0 + (band - sw) / 2, Y(acc) - (acc ? 2 : 0), Y(acc + v), sw, x.color, c, rows); acc += v;
      }
    } else {
      const w = Math.min((band - 2 * gap - (series.length - 1) * 2) / series.length, 64);  // a lone bar must not fill the plot
      const left = x0 + (band - (series.length * w + (series.length - 1) * 2)) / 2;
      series.forEach((x, k) => {
        const v = x.values[i]; if (v == null) return;
        const color = catColors ? catColors[i] : bySign ? (v >= 0 ? cv("--pos") : cv("--neg")) : x.color;
        bar(left + k * (w + 2), Y(0), Y(v), w, color, c, rows);
        if (valueLabels) txt(svg, left + k * (w + 2) + w / 2, v >= 0 ? Y(v) - 4 : Y(v) + 12, yfmt(v), { "text-anchor": "middle", class: "lab" });
      });
    }
  });
  host.append(svg);
}

/* Scatter with one series. points: [{x, y, title, rows}]. xlog spaces x by log. */
export const scatter = (parent, o) => mount(parent, (host, W) => drawScatter(host, o, W));
function drawScatter(host, { points, xfmt, yfmt, xlog = false, h = 250, xlabel, color }, W) {
  host.replaceChildren();
  const L = 50, R = 14, T = 10, B = 38;
  const svg = s("svg", { viewBox: `0 0 ${W} ${h}`, width: W, height: h, role: "img" }, null);
  const fx = (v) => (xlog ? Math.log(v) : v);
  const xs = points.map((p) => fx(p.x)), ys = points.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const py = (y1 - y0 || 1) * 0.08; y0 -= py; y1 += py;
  const X = (v) => L + (fx(v) - x0) / (x1 - x0 || 1) * (W - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (h - T - B);
  for (const t of niceTicks(y0, y1)) { s("line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: cv("--grid") }, svg); txt(svg, L - 6, Y(t) + 4, yfmt(t), { "text-anchor": "end" }); }
  const ticks = xlog ? [1 / 12, 0.25, 0.5, 1, 2, 5, 10].filter((t) => fx(t) >= x0 - 1e-9 && fx(t) <= x1 + 1e-9) : niceTicks(x0, x1, 5);
  for (const t of ticks) txt(svg, X(t), h - 18, xfmt(t), { "text-anchor": "middle" });
  if (xlabel) txt(svg, W - R, h - 3, xlabel, { "text-anchor": "end" });
  const c = color || cv("--s1");
  for (const p of points) {
    const dot = s("circle", { cx: X(p.x), cy: Y(p.y), r: 4, fill: c, "fill-opacity": 0.75, stroke: cv("--surface"), "stroke-width": 1.5 }, svg);
    const hit = s("circle", { cx: X(p.x), cy: Y(p.y), r: 12, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (evt) => { dot.setAttribute("r", 6); showTip(evt, p.title, p.rows); });
    hit.addEventListener("pointerleave", () => { dot.setAttribute("r", 4); hideTip(); });
  }
  host.append(svg);
}

/* Colour between two CSS-variable colours, t in 0..1. Returns [css colour, use dark text?]. */
export function ramp(t, lo = "--seq-lo", hi = "--seq-hi") {
  const p = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const a = p(cv(lo)), b = p(cv(hi)), c = a.map((v, i) => Math.round(v + (b[i] - v) * Math.max(0, Math.min(1, t))));
  // Dark or white text, whichever contrasts more with this cell (WCAG relative luminance).
  const lin = (v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  const lum = 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  return [`rgb(${c.join(",")})`, (lum + 0.05) / 0.0533 > 1.05 / (lum + 0.05)];
}

/* Explanatory tooltip for a term: a title and one plain sentence. */
export function showNote(evt, title, text) {
  const t = tip();
  t.replaceChildren(el("div", { class: "t", text: title }), el("p", { text }));
  t.hidden = false;
  const box = evt.target.getBoundingClientRect();
  let x = box.left, y = box.bottom + 8;
  if (x + t.offsetWidth > innerWidth - 8) x = innerWidth - t.offsetWidth - 8;
  if (y + t.offsetHeight > innerHeight - 8) y = box.top - t.offsetHeight - 8;
  t.style.left = `${Math.max(8, x)}px`;
  t.style.top = `${Math.max(8, y)}px`;
}

/* Tiny trend line for a number tile. No axes: it shows direction, the tile shows the value. */
export function spark(values, color) {
  const v = values.filter((x) => x != null && isFinite(x));
  const W = 92, H = 30, lo = Math.min(...v), hi = Math.max(...v);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" }, null);
  const X = (i) => 2 + i / (v.length - 1) * (W - 6), Y = (y) => 3 + (1 - (y - lo) / (hi - lo || 1)) * (H - 8);
  s("path", { d: v.map((y, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(y).toFixed(1)}`).join(""), fill: "none", stroke: color || cv("--s1"), "stroke-width": 1.75, "stroke-linejoin": "round" }, svg);
  s("circle", { cx: X(v.length - 1), cy: Y(v.at(-1)), r: 2.6, fill: color || cv("--s1") }, svg);
  return svg;
}
