import { bars, cv, el, hideTip, line, ramp, redrawAll, scatter, showNote, spark } from "./charts.js";

// ================================================================ helpers
const view = document.getElementById("view");
const state = { day: null, days: [], kind: "swap", lastQuote: null, stream: null };
const NODE_LABELS = ["3m", "6m", "1y", "2y", "3y", "4y", "5y", "7y", "10y", "12y", "15y", "20y", "25y", "30y"];
const NODE_TICKS = [0, 2, 3, 6, 8, 10, 11, 13];

const GLOSSARY = {
  swap: ["Interest rate swap", "Two sides exchange interest payments for a set number of years. One pays a fixed rate; the other pays the overnight rate, whatever it turns out to be. The fixed rate is the swap's price."],
  fair: ["Fair rate", "The rate the model expects for a swap right now. It is built only from real trades that happened earlier."],
  bp: ["Basis point (bp)", "One hundredth of a percent. A move from 4.75% to 4.76% is one basis point."],
  range: ["Normal range", "How far from the fair rate 9 in 10 recent real trades of this length landed. A trade outside it is unusual, not necessarily wrong."],
  perbp: ["Gain per basis point", "Money made or lost if rates rise by one basis point. Traders call it DV01 and use it to size and hedge positions."],
  vol: ["Volatility", "How much the market expects a swap rate to move over a year, in basis points. It is read back from the premiums people pay for options."],
  curve: ["Swap curve", "The swap rate for each length of time, from 3 months to 30 years, drawn as one line."],
  steep: ["Steepness", "Long rates minus short rates. When it rises, long rates are climbing relative to short ones."],
  sofr: ["Overnight rate (SOFR)", "The overnight dollar interest rate published each day by the New York Fed. The floating side of every dollar swap is built on it."],
  option: ["Swap option", "The right, without the obligation, to enter a swap later at a rate agreed today. The buyer pays a premium for it."],
  clean: ["Clean trade", "A plain, standalone swap starting on the standard date. Its rate can be read directly as a market price."],
  package: ["Package", "Several trades agreed together at one price. A single leg's reported rate may not be a standalone price."],
  bermudan: ["Bermudan option", "An option that can be used on any of several set dates, not just one. Callable bonds and cancellable swaps contain one."],
  oos: ["Out of sample", "Tested on trades the model had not seen when it made the prediction."],
  baseline: ["Baseline", "A simple alternative the model must beat, such as using the last trade of the same length."],
  spread: ["Swap rate minus Treasury yield", "The gap between a swap rate and the government bond yield of the same length."],
  margin: ["Initial margin", "Cash posted to the clearing house when a trade is opened, sized to cover a bad move while a defaulted position is closed out. It is returned at the end, but it has to be funded for the whole life of the trade."],
  future: ["Swap future", "An exchange-traded contract with the same cash flows as a swap. It needs less margin than the swap itself because a future can be closed out faster."],
  hedge: ["Hedge", "An offsetting trade chosen so that gains on one roughly cancel losses on the other when rates move."],
};
function term(text, key) {
  const [title, body] = GLOSSARY[key];
  const s = el("span", { class: "term", tabindex: 0, text });
  for (const ev of ["pointerenter", "focus"]) s.addEventListener(ev, (e) => showNote(e, title, body));
  for (const ev of ["pointerleave", "blur"]) s.addEventListener(ev, hideTip);
  return s;
}

async function api(path, opts) {
  const r = await fetch(path, opts && { ...opts, headers: { "Content-Type": "application/json" }, body: opts.body && JSON.stringify(opts.body) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status} ${r.statusText}`);
  return r.status === 204 ? null : r.json();
}
const q = (path) => api(`${path}${path.includes("?") ? "&" : "?"}day=${state.day || ""}`);
const pct = (v, d = 3) => (v == null ? "n/a" : `${v.toFixed(d)}%`);
const bp = (v, d = 1) => (v == null ? "n/a" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)} bp`);
const num = (v) => (v == null ? "n/a" : Math.round(v).toLocaleString("en-US"));
const money = (v, signed = false) => {
  if (v == null) return "n/a";
  if (Math.abs(v) < 0.5) return "$0";
  const a = Math.abs(v), s = v < 0 ? "−" : signed && v > 0 ? "+" : "";
  return a >= 1e9 ? `${s}$${(a / 1e9).toFixed(2)}bn` : a >= 1e6 ? `${s}$${(a / 1e6).toFixed(2)}m` : a >= 1e3 ? `${s}$${(a / 1e3).toFixed(1)}k` : `${s}$${a.toFixed(0)}`;
};
const size = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(1)}bn` : `$${Math.round(v / 1e6)}m`);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const nice = (d) => `${+String(d).slice(8, 10)} ${MONTHS[+String(d).slice(5, 7) - 1]} ${String(d).slice(0, 4)}`;       // 13 Nov 2026
const niceMonth = (m) => `${MONTHS[+String(m).slice(5, 7) - 1]} ${String(m).slice(0, 4)}`;                              // Nov 2026
const lvl = (v, d = 1) => (v == null ? "n/a" : `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`);                         // a level, with a true minus sign
/* Ticks for a daily series: the first trading day of a month, about `want` of them, labelled "Jan 2026". */
function monthTicks(days, want = 5) {
  const firsts = days.map((d, i) => (i > 0 && d.slice(0, 7) !== days[i - 1].slice(0, 7) ? i : -1)).filter((i) => i >= 0);
  const step = [1, 2, 3, 4, 6, 12].find((k) => firsts.length / k <= want) || 12;
  const xticks = firsts.filter((i) => (+days[i].slice(5, 7) - 1) % step === 0);
  return { xticks, xtext: xticks.map((i) => niceMonth(days[i])) };
}
const yrs = (t) => (t < 1 ? `${Math.round(t * 12)}m` : Math.abs(t - Math.round(t)) < 0.05 ? `${Math.round(t)}y` : `${t.toFixed(1)}y`);
/* An arrow and a size for a change on the day. The arrow carries the direction; the colour only repeats it. */
const delta = (v, unit = "bp") => el("span", {}, el("span", { class: `arrow ${v > 0.05 ? "up" : v < -0.05 ? "down" : ""}`, "aria-hidden": "true", text: v > 0.05 ? "▲" : v < -0.05 ? "▼" : "■" }),
  el("b", { text: ` ${v > 0.05 ? "up" : v < -0.05 ? "down" : "flat"} ${Math.abs(v).toFixed(1)} ${unit}` }));
/* The one number a card is about, with its label and a verdict. */
const headline = (value, label, verdict) => el("div", { class: "headline" }, el("b", { text: value }), el("span", { text: label }), verdict || "");
/* Supporting tables and method notes, closed until asked for. */
const more = (summary, ...kids) => el("details", { class: "more" }, el("summary", { text: summary }), ...kids);
const SHAPE = { "parallel shift": "a move of all rates together", "steeper or flatter": "a change in steepness", "more or less curved": "a change in curvature" };
const moved = (v) => (Math.abs(v) < 0.05 ? "was unchanged" : `${v > 0 ? "rose" : "fell"} ${Math.abs(v).toFixed(1)} bp`);

let tipSeq = 0;
function card(title, sub, cls = "c6") {
  const body = el("div");
  const id = `about${++tipSeq}`;
  const head = el("header", {}, el("h2", {}, title), sub && el("button", { class: "info", type: "button", "aria-label": "About this card", "aria-describedby": id, text: "i" }),
    sub && el("div", { class: "tip", role: "tooltip", id }, sub));
  return [el("section", { class: `card ${cls}` }, head, body), body];
}
function kpi(label, value, detail, trend, minor = false) {
  return el("div", { class: `kpi ${minor ? "minor" : ""}` }, el("div", { class: "k" }, label), el("div", { class: "v", text: value }), trend ? spark(trend) : el("span"), el("div", { class: "d" }, detail));
}
const chip = (text, kind = "plain") => el("span", { class: `chip ${kind}`, text });
function table(cols, rows, { scroll = true } = {}) {
  const t = el("table", {}, el("thead", {}, el("tr", {}, cols.map((c) => el("th", { class: `${c.n ? "n" : ""} ${c.lo ? "lo" : ""} ${c.mid ? "mid" : ""}` }, c.h || el("span", { class: "sr", text: c.sr || "Detail" }))))));
  const body = el("tbody");
  for (const r of rows) body.append(el("tr", {}, cols.map((c) => el("td", { class: `${c.n ? "n" : ""} ${c.wrap ? "wrapcell" : ""} ${c.lo ? "lo" : ""} ${c.mid ? "mid" : ""}` }, c.f(r)))));
  t.append(body);
  return el("div", scroll ? { class: "scroll", tabindex: 0, role: "group", "aria-label": "Table; scroll for more rows" } : { class: "scroll flat" }, t);
}
/* A gap drawn against its normal range. The two ticks mark the edge of the range, a quarter of the way out on each
   side, so a bar that passes a tick is an unusual trade. `money` colours by gain and loss instead of above and below. */
function gapBar(gap, band, money = false, scale = null) {
  // With `scale` (the widest gap in the table) bar lengths compare across rows; without it a gap of twice the range fills the bar.
  const full = scale || 2 * (band || 1.5), w = Math.max(Math.min(Math.abs(gap) / full, 1) * 50, 1), b = el("b");   // percent of the bar, half each side
  b.style.width = `${w}%`; b.style.left = gap >= 0 ? "50%" : `${50 - w}%`;
  b.style.background = money ? (gap >= 0 ? cv("--good") : cv("--crit")) : gap >= 0 ? cv("--pos") : cv("--neg");
  return el("span", { class: `gapbar ${money ? "" : "ticks"}`, "aria-hidden": "true" }, b);
}
const page = (title, lede, ...kids) => view.replaceChildren(el("div", { class: "pagehead" }, el("h1", { text: title }), lede && el("p", {}, lede)), ...kids);
const grid = (...kids) => el("div", { class: "grid" }, kids);
const go = (hash) => () => { location.hash = hash; };

// ================================================================ Overview
async function overview() {
  const [s, o] = await Promise.all([api("/api/scorecard"), q("/api/overview")]);
  const sw = s.swaps, f = sw.overall.filter, last = sw.overall.last, rk = s.risk;
  const better = Math.round((1 - f.median_bp / last.median_bp) * 100);
  const stat = (big, label, sub) => el("div", { class: "stat" }, el("b", { text: big }), el("div", {}, el("h2", { text: label }), el("p", {}, sub)));
  const hero = el("section", { class: "hero" },
    el("div", { class: "pitch" },
      el("div", { class: "eyebrow", text: "Interest rate swaps · public data only" }),
      el("h1", { text: "What should this trade cost?" }),
      el("p", {}, "A fair price for any interest rate ", term("swap", "swap"), ", built from public trade records and checked against what traders paid next."),
      el("div", { class: "cta" }, el("a", { class: "btn", href: "#price", text: "Price a trade" }), el("a", { class: "btn ghost", href: "#today", text: `See the market on ${nice(o.day)}` }),
        el("a", { class: "btn ghost", href: "#accuracy", text: "See the proof" }))),
    el("div", { class: "stats" },
      stat(`${f.median_bp.toFixed(2)} bp`, "Typical miss against the next real trade", el("span", {}, `${num(f.n)} unseen trades. About $2,000 on a $10 million 10-year swap. `, term("What is a bp?", "bp"))),
      stat(`${better}%`, "Smaller miss than using the last trade", `The last trade of the same length misses by ${last.median_bp.toFixed(2)} bp.`),
      stat(`${rk.risk_removed_pct.bucket_hedge.toFixed(1)}%`, "Of next-day risk removed by its hedges", `${num(rk.trades)} real trades, hedged and revalued the next day.`)));

  const [cRank, bRank] = card("Four ways to price a swap, ranked by real trades", "Typical miss against the next real trade, all trades, in basis points. Lower is better. The closes are an outside provider's closing curves, on the day and the day before.", "c7");
  const o4 = sw.overall;
  bars(bRank, { cats: ["Model", "Last trade", "Same-day close", "Prior-day close"], catColors: [cv("--s1"), cv("--muted"), cv("--muted"), cv("--muted")],
    series: [{ name: "Typical miss", color: cv("--s1"), values: [o4.filter.median_bp, o4.last.median_bp, o4.same_close.median_bp, o4.prev_close.median_bp] }], yfmt: (x) => x.toFixed(2), valueLabels: true, h: 250 });
  const [cTry, bTry] = card("The test in numbers", "Every trade was predicted before the model was allowed to use it.", "c5 tight");
  bTry.append(el("div", { class: "kv" }, [["Trades tested", num(f.n)], ["Period", `${nice(sw.period[0])} to ${nice(sw.period[1])}`], ["Trading days compared", `${sw.filter_vs_last.days}`], ["Significance against the last trade", `t = ${Math.abs(sw.filter_vs_last.t_stat).toFixed(1)}`],
    ["Trades inside the normal range", `${(sw.coverage.calibrated * 100).toFixed(1)}% against a 90% target`]].flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: b })])));
  const tasks = grid(cRank, cTry);

  const [cHow, bHow] = card("How it works", null, "c12");
  bHow.append(el("div", { class: "steps" },
    el("div", {}, el("h3", { text: "Collect" }), el("p", { text: "4.1 million public trade reports." })),
    el("div", {}, el("h3", { text: "Clean" }), el("p", { text: "Corrections applied; every exclusion has a reason." })),
    el("div", {}, el("h3", { text: "Price" }), el("p", { text: "One curve, nudged by every trade." })),
    el("div", {}, el("h3", { text: "Prove" }), el("p", { text: "Each trade predicted before it is used." }))));

  const [cNow, bNow] = card(`The market on ${nice(o.day)}`, "A taste of the Today screen.", "c12");
  bNow.append(brief(o));
  page("", null, hero, tasks, grid(cNow), grid(cHow),
    el("p", { class: "note", text: "US dollar swaps and swap options in depth; other markets as daily summaries. Hover any dotted word for a definition." }));
  view.querySelector(".pagehead").remove();
}

function brief(o, compact = false) {
  const r = Object.fromEntries(o.key_rates.map((k) => [k.length, k]));
  const st = o.slopes[0], shape = o.move_shape.slice().sort((a, b) => b.share_pct - a.share_pct)[0];
  const top = o.surprises[0];
  const items = [
    el("span", {}, "The 10-year swap rate closed at ", el("b", { text: pct(r["10y"].rate) }), ` and ${moved(r["10y"].change_bp)}. The 2-year ${moved(r["2y"].change_bp)}, so the `, term("curve", "curve"),
      st.change_bp > 0.05 ? " steepened" : st.change_bp < -0.05 ? " flattened" : " kept its shape", ` by ${Math.abs(st.change_bp).toFixed(1)} bp. `, `Most of the day's move (${shape.share_pct}%) was ${SHAPE[shape.name]}.`),
    el("span", {}, el("b", { text: `${num(o.trades.all_swaps)} dollar swaps` }), ` traded, ${size(o.trades.notional_bn * 1e9)} of size. `,
      o.trades.busiest_length ? `The most risk changed hands in ${o.trades.busiest_length} swaps (${o.trades.busiest_share_pct}% of the total).` : ""),
    el("span", {}, el("b", { text: `${num(o.trades.outside)} of ${num(o.trades.clean)} clean trades` }), " landed outside the ", term("normal range", "range"), ". ",
      top ? `The furthest was a ${top.length}-year at ${pct(top.rate, 4)}, ${Math.abs(top.gap_bp).toFixed(2)} bp ${top.gap_bp < 0 ? "below" : "above"} fair on ${size(top.notional)}.` : ""),
  ];
  if (compact) {
    const short = [
      el("span", {}, "10y ", el("b", { text: pct(r["10y"].rate) }), " ", delta(r["10y"].change_bp), "; curve ", st.change_bp > 0.05 ? "steeper" : st.change_bp < -0.05 ? "flatter" : "unchanged", ` ${Math.abs(st.change_bp).toFixed(1)} bp (2s10s).`),
      el("span", {}, el("b", { text: num(o.trades.all_swaps) }), ` swaps, ${size(o.trades.notional_bn * 1e9)}.`, o.trades.busiest_length ? ` Most risk in ${o.trades.busiest_length} (${o.trades.busiest_share_pct}%).` : ""),
      el("span", {}, el("b", { text: num(o.trades.outside) }), ` of ${num(o.trades.clean)} trades outside the `, term("normal range", "range"), ". ", el("a", { href: "#trades", text: "See them" })),
    ];
    return el("ul", { class: "bullets" }, short.map((x) => el("li", {}, x)));
  }
  return el("div", { class: "brief" }, el("ul", {}, items.map((x, i) => el("li", {}, el("span", { class: "n", text: i + 1 }), x))));
}

/* The curve monitor: one row per swap length, then the main spreads. */
function monitorTable(m) {
  const sgn = (v, d = 1) => (v == null ? "" : el("span", { class: `num ${v > 0.05 ? "up" : v < -0.05 ? "dn" : ""}`, text: `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}` }));
  const plain = (v) => (v == null ? "" : el("span", { class: "num", text: `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}` }));
  const range = (r, now) => {
    const w = r.hi - r.lo || 1, at = Math.min(Math.max((now - r.lo) / w, 0), 1);
    const b = el("span", { class: "rng", title: `Past year: ${r.lo} to ${r.hi}; higher than ${r.pctile}% of days` }, el("i"));
    b.firstChild.style.left = `${at * 100}%`;
    return el("span", { class: "rngwrap" }, b, el("span", { class: "sr", text: `higher than ${r.pctile}% of the past year` }));
  };
  const cols = (fmtLevel) => [
    { h: "", sr: "Length", f: (r) => el("b", { text: r.length || r.name }) }, { h: "Level", n: 1, f: fmtLevel },
    { h: "1d", n: 1, f: (r) => sgn(r.chg_1d) }, { h: "1w", n: 1, f: (r) => sgn(r.chg_1w) }, { h: "1m", n: 1, f: (r) => sgn(r.chg_1m) },
    { h: "1-year range", lo: 1, f: (r) => range(r, r.rate ?? r.level_bp) }, { h: "60 days", lo: 1, f: (r) => spark(r.trend) },
  ];
  const rates = table([...cols((r) => el("span", { class: "num", text: r.rate.toFixed(3) })),
    { h: "Roll 3m", n: 1, mid: 1, f: (r) => plain(r.roll_3m_bp) }, { h: "Fwd 3m", n: 1, mid: 1, f: (r) => plain(r.fwd_3m_bp) }], m.rows, { scroll: false });
  const spreads = table(cols((r) => el("span", { class: "num", text: r.level_bp.toFixed(1) })), m.spreads, { scroll: false });
  rates.classList.add("monitor"); spreads.classList.add("monitor");
  return el("div", {}, rates, el("h3", { class: "sub", text: "Spreads, bp" }), spreads,
    el("p", { class: "note", text: "Rates in %, changes in bp. Red rose, blue fell." }));
}

// ================================================================ Today
async function today() {
  const [o, c, f, h, mk, mon] = await Promise.all([q("/api/overview"), q("/api/curve"), q("/api/flow"), api("/api/history"), api("/api/markets"), q("/api/monitor")]);
  const at = h.days.indexOf(o.day), tail = (a) => a.slice(Math.max(0, at - 60), at + 1);
  const [cMon, bMon] = card("Curve monitor", "Model closing rate at every swap length. Changes in basis points over one day, one week (5 days) and one month (21 days). The bar is the past year's range with today's level marked. Roll 3m: how much the rate falls as the swap ages three months on an unchanged curve. Fwd 3m: the same swap starting in three months, against today; the move the curve already prices in.", "c8 tight");
  bMon.append(monitorTable(mon));
  const [cBrief, bBrief] = card("In brief", null, "c4");
  bBrief.append(brief(o, true));
  const side = el("div", { class: "kv compact" }, [
    [term("Overnight rate", "sofr"), o.sofr ? pct(o.sofr.rate, 2) : "n/a"], [term("Option volatility, 1y into 10y", "vol"), o.vol_1y10y_bp == null ? "n/a" : `${o.vol_1y10y_bp.toFixed(0)} bp/yr`],
    [term("10y swap − Treasury", "spread"), o.swap_spread_10y_bp != null ? `${lvl(o.swap_spread_10y_bp)} bp${o.treasury_day !== o.day ? "*" : ""}` : "n/a"]].flatMap(([k, v]) => [el("span", {}, k), el("span", { class: "num", text: v })]));
  bBrief.append(side);
  if (o.treasury_day && o.treasury_day !== o.day) bBrief.append(el("p", { class: "note", text: `* Treasury curve of ${nice(o.treasury_day)}, the latest published.` }));

  const [cCurve, bCurve] = card("Where rates closed", el("span", {}, "The ", term("fair rate", "fair"), " for each swap length. Dots are the middle rate of the day's real trades; the dashed line is the previous day."), "c7");
  const dots = c.traded.filter((t) => t.trades >= 3 && NODE_LABELS.includes(`${t.length}y`)).map((t) => ({ i: NODE_LABELS.indexOf(`${t.length}y`), y: t.median, color: cv("--ink2"), name: `Middle of ${t.trades} trades` }));
  const chart = el("div");
  line(chart, { labels: NODE_LABELS, xticks: NODE_TICKS, yfmt: (v) => `${v.toFixed(2)}%`, dots, h: 290, endLabels: false,
    series: [{ name: "Model", color: cv("--s1"), values: c.ours }, ...(c.previous ? [{ name: "Previous day", color: cv("--muted"), dash: true, values: c.previous }] : [])] });
  bCurve.append(chart);

  const [cMove, bMove] = card("What moved", el("span", {}, "Change in the fair rate at each length, in ", term("basis points", "bp"), ". The shares split the day's move into the three ways the curve usually moves."), "");
  const mv = el("div");
  bars(mv, { cats: NODE_LABELS, series: [{ name: "Change", values: o.move_bp }], bySign: true, yfmt: (v) => v.toFixed(1), h: 200 });
  bMove.append(mv, el("div", { class: "kv" }, o.move_shape.flatMap((s) => [el("span", { text: `Share that was ${SHAPE[s.name]}` }), el("span", { text: `${s.share_pct}%` })])),
  );

  const [cFlow, bFlow] = card("Where risk changed hands", el("span", {}, term("Gain per basis point", "perbp"), " traded at each length."), "c5");
  const lens = [...new Set(f.by_length.map((r) => r.length))];
  const kinds = [["clean", "Standalone", "--s1"], ["package", "Inside packages", "--s3"], ["other", "Forward-starting and other", "--muted"]];
  const fl = el("div");
  bars(fl, { cats: lens, stacked: true, yfmt: (v) => `$${v.toFixed(0)}m/bp`, h: 380, series: kinds.map(([k, name, col]) => ({ name, color: cv(col), values: lens.map((l) => ((f.by_length.find((r) => r.length === l && r.kind === k) || {}).dv01_k || 0) / 1000) })) });
  bFlow.append(fl);

  const [cSur, bSur] = card("Trades furthest from fair", el("span", {}, term("Clean trades", "clean"), " with the widest gap to the model at the moment they happened. The last column is that gap in dollars."), "c7");
  bSur.append(table([
    { h: "Time, UTC", lo: 1, f: (r) => (/^\d{4}-\d\d-\d\d /.test(r.time) ? `${nice(r.time.slice(0, 10)).replace(/ \d{4}$/, "")} ${r.time.slice(11)}` : r.time) }, { h: "Length", n: 1, f: (r) => yrs(r.length) }, { h: "Traded", n: 1, f: (r) => pct(r.rate, 4) }, { h: "Fair", lo: 1, n: 1, f: (r) => pct(r.fair, 4) },
    { h: "Gap", n: 1, f: (r) => bp(r.gap_bp, 2) }, { h: "Size", lo: 1, n: 1, f: (r) => size(r.notional) }, { h: "Gap in dollars", n: 1, f: (r) => money(r.dollars, true) }], o.surprises, { scroll: false }),
    el("p", { class: "note", text: "A wide gap is a question, not a verdict: the public record does not show special terms. " }, el("a", { href: "#trades", text: "See every trade" })));

  const path = (c.meetings || []).filter((x) => x.from > o.day);
  const [cFed, bFed] = card("What the market prices for each Fed meeting", "The overnight rate implied for the period after each scheduled meeting, from today's curve. Read as the market's average expectation, not a forecast.", "c5");
  if (path.length) {
    const now = o.sofr ? o.sofr.rate : null, end = path.at(-1);
    bFed.append(headline(now == null ? pct(end.rate_pct, 2) : bp((end.rate_pct - now) * 100, 0), now == null ? `after ${nice(end.from)}` : `priced by ${nice(end.from)} against today's overnight rate of ${pct(now, 2)}`));
    line(bFed, { labels: path.map((x) => nice(x.from).replace(/^\d+ /, "")), series: [{ name: "Overnight rate after the meeting", color: cv("--s1"), values: path.map((x) => x.rate_pct), markers: true }], yfmt: (v) => `${v.toFixed(2)}%`, endLabels: false, xticks: path.map((_, i) => i), h: 240 });
  }
  const [cHist, bHist] = card("Rates over the past two years", "Model closing rate at three lengths.", "c6");
  line(bHist, { labels: h.days.map(nice), ...monthTicks(h.days), yfmt: (v) => `${v.toFixed(2)}%`, h: 240, endLabels: false, series: [{ name: "2y", color: cv("--s1"), values: h.rates["2y"] }, { name: "10y", color: cv("--s3"), values: h.rates["10y"] }, { name: "30y", color: cv("--muted"), values: h.rates["30y"] }] });
  const [cShape, bShape] = card("How the curve usually moves", `Three patterns explain ${Math.round(mk.pca.share.reduce((a, b) => a + b, 0) * 100)}% of daily moves over the past year (${mk.pca.share.map((x) => `${Math.round(x * 100)}%`).join(", ")}). Each line shows how much each length moves in that pattern.`, "c6");
  line(bShape, { labels: NODE_LABELS, xticks: NODE_TICKS, yfmt: (v) => v.toFixed(2), h: 220, zero: true, endLabels: false,
    series: [{ name: "All lengths together", color: cv("--s1"), values: mk.pca.shapes[0] }, { name: "Short against long", color: cv("--s3"), values: mk.pca.shapes[1] }, { name: "Middle against the ends", color: cv("--muted"), values: mk.pca.shapes[2] }] });

  page(`Today: ${nice(o.day)}`, null, grid(cMon, el("div", { class: "c4 stack" }, cBrief, cMove)), grid(cCurve, cFed), grid(cFlow, cSur), grid(cHist, cShape));
}

// ================================================================ Trades
/* A trade more than 25 bp from fair was almost certainly agreed on terms the public record does not show (an old coupon,
   an unreported fee). It is marked as such, and kept apart from trades that are merely outside the normal range. */
/* Public reports give a market identifier code; XOFF means off any venue and XXXX that none was reported. */
const venue = (v) => ({ XOFF: "off-venue", XXXX: "not reported", BBSF: "Bloomberg SEF", TWSF: "Tradeweb SEF" }[v] || v || "not reported");   // others: market code as reported
const offMarket = (r) => r.gap_bp != null && Math.abs(r.gap_bp) > 25;
const tradeCols = [
  { h: "Time, UTC", f: (r) => (/^\d{4}-\d\d-\d\d /.test(r.time) ? `${nice(r.time.slice(0, 10)).replace(/ \d{4}$/, "")}, ${r.time.slice(11)}` : r.time) }, { h: "Length", n: 1, f: (r) => yrs(r.length) }, { h: "Traded", n: 1, f: (r) => pct(r.rate, 4) },
  { h: "Fair before", lo: 1, n: 1, f: (r) => pct(r.fair, 4) },
  { h: "Gap to fair", n: 1, f: (r) => el("span", {}, bp(r.gap_bp, 2), gapBar(r.gap_bp, r.band_bp, false, state.gapMax), offMarket(r) ? chip("off-market terms", "plain") : r.outside ? chip("unusual", "warn") : el("span", { class: "chip-space" })) },
  { h: "Normal range", lo: 1, n: 1, f: (r) => (r.band_bp == null ? "" : `±${r.band_bp.toFixed(2)} bp`) },
  { h: "Size", lo: 1, n: 1, f: (r) => size(r.notional) }, { h: "Gap, $", n: 1, lo: 1, f: (r) => (r.dollars == null ? "" : money(r.dollars, true)) }, { h: "Venue", lo: 1, mid: 1, f: (r) => venue(r.venue) },
];
async function trades() {
  const [t, live] = await Promise.all([q("/api/tape?limit=800"), api("/api/live")]);

  const outside = t.rows.filter((r) => r.outside).length, off = t.rows.filter(offMarket).length;
  const [cTape, bTape] = card(`Clean trades on ${nice(t.day)}`, el("span", {}, "Each trade next to the ", term("fair rate", "fair"), " the model held just before it. “Unusual” means the gap was wider than the ", term("normal range", "range"), "."), "c12");
  const only = el("input", { type: "checkbox", id: "only" }), min = el("input", { type: "number", id: "minsize", value: 0, min: 0, step: "any", style: "width:90px" }), tbl = el("div");
  const order = el("select", { id: "order", "aria-label": "Order" }, [["unusual", "Furthest outside the range first"], ["time", "Latest first"]].map(([v, x]) => el("option", { value: v, text: x })));
  const stretch = (r) => Math.abs(r.gap_bp) / (r.band_bp || 1);
  const redraw = () => {
    const rows = t.rows.filter((r) => (!only.checked || r.outside) && r.notional >= min.value * 1e6);
    const rank = (r) => (offMarket(r) ? 1 : r.outside ? 2 : 0);          // unusual, then off-market, then the rest; widest first within each
    state.gapMax = Math.max(...rows.filter((r) => !offMarket(r)).map((r) => Math.abs(r.gap_bp || 0)), 1);
    tbl.replaceChildren(table(tradeCols, order.value === "unusual" ? rows.slice().sort((a, b) => rank(b) - rank(a) || stretch(b) - stretch(a)) : rows));
  };
  only.addEventListener("change", redraw); min.addEventListener("input", redraw); order.addEventListener("change", redraw);
  bTape.append(headline(`${num(outside)} of ${num(t.rows.length)}`, `landed outside the normal range${off ? `: ${num(outside - off)} unusual, and ${off} over 25 bp from fair, which points to terms the public record does not show` : ""}`),
    el("p", { class: "note lo", text: "Bars: blue below fair, red above, drawn to the scale of the widest gap shown (off-market trades fill the bar)." }),
    el("div", { class: "filters" }, el("label", {}, "Order", order), el("label", { class: "check" }, only, "Only unusual and off-market"), el("label", {}, "Minimum size, $m", min)), tbl);
  redraw();

  const [cLive, bLive] = card("Live feed", "New trades from the public ticker. Each is compared with the model the moment it arrives, then used to update it.", "c12");
  const status = el("div", { class: "filters" }), body = el("div");
  let rows = live.rows, st = live.status;
  const draw = () => {
    status.replaceChildren(chip(st.enabled ? (st.last_error ? "feed unreachable" : "listening") : "paused", st.enabled ? (st.last_error ? "crit" : "good") : "warn"),
      el("span", { class: "note", text: st.last_poll ? `Checked ${st.last_poll.slice(11, 19)} UTC · ${st.received} dollar swaps so far · checks every 45 seconds` : "Waiting for the first check" }),
      el("button", { class: "btn ghost sm", type: "button", text: st.enabled ? "Pause" : "Resume", onclick: async () => { st = await api(`/api/live/${st.enabled ? "off" : "on"}`, { method: "POST" }); draw(); } }));
    // Only trades that can be compared with the model are listed; the rest are counted by reason.
    const scored = rows.filter((r) => r.gap_bp != null), why = {};
    for (const r of rows.filter((x) => x.gap_bp == null)) why[r.reason || "no reason given"] = (why[r.reason || "no reason given"] || 0) + 1;
    const skipped = Object.entries(why).sort((a, b) => b[1] - a[1]);
    body.replaceChildren(scored.length ? table(tradeCols, scored.slice(0, 40)) : el("p", { class: "note", text: rows.length ? "No plain, standard-start swaps in the feed right now." : "No dollar swaps in the feed yet. Markets are closed at weekends; this fills when trading resumes." }),
      skipped.length ? el("p", { class: "note", text: `${skipped.reduce((a, [, n]) => a + n, 0)} more are not comparable with a fair rate: ${skipped.map(([k, n]) => `${k} (${n})`).join(", ")}.` }) : "");
  };
  draw();
  bLive.append(status, body);
  state.stream?.close();
  state.stream = new EventSource("/api/live/stream");
  state.stream.onmessage = (m) => { rows = [JSON.parse(m.data), ...rows]; st = { ...st, last_poll: new Date().toISOString(), received: st.received + 1 }; draw(); };
  page("Trades", "What traded, and whether each price was in line with the market at that moment.", grid(cTape), grid(cLive));
}

// ================================================================ Price a trade
const field = (label, hint, input) => el("label", {}, el("span", {}, label, hint && el("small", { text: ` ${hint}` })), input);
async function price() {
  const out = el("div", { style: "display:grid;gap:12px" });
  const quote = el("div", { class: "quote", "aria-live": "polite" });
  const f = {};
  const inp = (name, attrs) => (f[name] = el("input", { id: `f-${name}`, ...attrs }));
  const swap = state.kind === "swap";
  const seg = el("div", { class: "seg full", role: "group", "aria-label": "Product" }, [["swap", "Swap"], ["option", "Swap option"]].map(([k, t]) => el("button", { type: "button", "aria-pressed": String(state.kind === k), text: t, onclick: () => { state.kind = k; price(); } })));
  // Side as two buttons: the one choice every trade has
  f.side = { value: "pay" };
  const sideBtns = [["pay", swap ? "Pay fixed" : "Payer"], ["receive", swap ? "Receive fixed" : "Receiver"]].map(([k, t]) => el("button", { type: "button", "aria-pressed": String(k === "pay"), text: t, onclick: (e) => {
    f.side.value = k; for (const b of sideBtns) b.setAttribute("aria-pressed", String(b === e.currentTarget)); run(); } }));
  const side = el("div", { class: "seg full", role: "group", "aria-label": "Side" }, sideBtns);
  const chipsFor = (name, vals, fmt) => el("div", { class: "presets tight" }, vals.map((v) => el("button", { type: "button", text: fmt(v), "aria-label": `${name} ${fmt(v)}`, onclick: () => { f[name].value = v; run(); } })));
  const form = el("form", { class: "ticket" });
  if (swap) {
    form.append(seg, side,
      field("Length", "years", inp("years", { type: "number", value: 10, min: 0.25, max: 50, step: "any" })), chipsFor("years", [2, 5, 10, 30], (v) => `${v}y`),
      el("div", { class: "pair" }, field("Size", "$m", inp("size_m", { type: "number", value: 100, min: 0, step: "any" })), field("Your rate", "%", inp("rate", { type: "number", step: "any", placeholder: "blank = fair" }))),
      field("Start", "blank = spot", inp("start", { type: "date" })));
  } else {
    form.append(seg, side,
      el("div", { class: "pair" }, field("Option", "years", inp("expiry_years", { type: "number", value: 1, min: 0.05, max: 30, step: "any" })), field("Into swap", "years", inp("swap_years", { type: "number", value: 10, min: 1, max: 40, step: "any" }))),
      el("div", { class: "pair" }, field("Strike", "%", inp("strike", { type: "number", step: "any", placeholder: "blank = at the money" })), field("Size", "$m", inp("size_m", { type: "number", value: 100, min: 0, step: "any" }))),
      field("Premium paid", "$, optional", inp("premium", { type: "number", step: "any" })),
      el("div", { class: "presets tight" }, [["1y×10y", 1, 10], ["3m×10y", 0.25, 10], ["1y×5y", 1, 5], ["5y×5y", 5, 5]].map(([t, e, w]) => el("button", { type: "button", text: t, onclick: () => { f.expiry_years.value = e; f.swap_years.value = w; run(); } }))));
  }
  const terms = () => {
    const v = (k) => (f[k] && f[k].value !== "" ? f[k].value : null);
    const notional = (+v("size_m") || 0) * 1e6;
    return swap ? { years: +v("years"), start: v("start"), rate: v("rate"), notional, pay_fixed: f.side.value === "pay" }
      : { expiry_years: +v("expiry_years"), swap_years: +v("swap_years"), strike: v("strike"), notional, payer: f.side.value === "pay", premium: v("premium") };
  };
  // Reprice as the terms change; a slower answer to an older request is dropped.
  let seq = 0, timer = null;
  const run = async () => {
    const my = ++seq;
    quote.classList.add("busy"); out.classList.add("busy");
    try {
      const r = await api(`/api/price/${state.kind}`, { method: "POST", body: { ...terms(), day: state.day } });
      if (my !== seq) return;
      state.lastQuote = { kind: state.kind, terms: terms() };
      (swap ? swapResult : optionResult)(out, r, quote);
    } catch (e) { if (my === seq) quote.replaceChildren(el("p", { class: "err", text: `Cannot price these terms: ${e.message}` })); }
    finally { if (my === seq) { quote.classList.remove("busy"); out.classList.remove("busy"); } }
  };
  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 280); });
  form.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(timer); run(); });
  const [cT, bT] = card("Ticket", `Priced on the curve of ${nice(state.day)}; change the day at the top right. Reprices as you type.`, "c4");
  bT.append(form);
  const [cQ, bQ] = card("Quote", null, "c8");
  bQ.append(quote);
  page("Price a trade", null, grid(cT, cQ), out);
  run();
}
function saveRow() {
  const label = el("input", { id: "save-label", placeholder: "Name it, for example: client quote, 10-year", style: "flex:1;min-width:200px" }), msg = el("span", { class: "note" });
  return el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" }, label,
    el("button", { class: "btn ghost", type: "button", text: "Save to Saved trades", onclick: async () => {
      try { await api("/api/blotter", { method: "POST", body: { ...state.lastQuote, label: label.value } }); msg.replaceChildren("Saved. ", el("a", { href: "#saved", text: "Open Saved trades" })); } catch (e) { msg.textContent = `Not saved: ${e.message}`; }
    } }), msg);
}
function swapResult(out, r, quote) {
  const inside = r.verdict.startsWith("inside"), atFair = Math.abs(r.gap_bp) < 0.005;
  const worse = r.value < 0;
  const span = Math.max(3 * r.band_bp, Math.abs(r.gap_bp) * 1.25), pos = (x) => `${50 + (Math.max(-span, Math.min(span, x)) / span) * 50}%`;
  const range = el("div", { class: "range" }, el("div", { class: "bar" }), el("div", { class: "band" }), el("div", { class: "fair" }), el("div", { class: "mark" }),
    el("span", { text: `fair ${pct(r.fair_rate, 4)}` }), el("span", { text: pct(r.low, 4) }), el("span", { text: pct(r.high, 4) }));
  range.children[1].style.left = pos(-r.band_bp); range.children[1].style.width = `${(r.band_bp / span) * 100}%`;
  range.children[2].style.left = "50%"; range.children[3].style.left = pos(r.gap_bp);
  range.children[4].style.left = "50%"; range.children[5].style.left = pos(-r.band_bp); range.children[6].style.left = pos(r.band_bp);
  if (Math.abs(pos(r.band_bp).replace("%", "") - 50) < 9) { range.children[5].hidden = true; range.children[6].hidden = true; }
  const line1 = atFair ? null : `${pct(r.rate, 4)} is ${Math.abs(r.gap_bp).toFixed(1)} bp ${r.gap_bp > 0 ? "above" : "below"} fair: ${money(Math.abs(r.value))} ${worse ? "worse" : "better"} for you.`;
  const why = atFair ? `9 in 10 recent real trades of this length landed between ${pct(r.low, 4)} and ${pct(r.high, 4)}.`
    : inside ? `Inside the normal range: 9 in 10 recent real trades of this length landed within ${r.band_bp.toFixed(2)} bp of fair.`
      : `Outside the normal range: only about 1 in 10 recent real trades of this length landed more than ${r.band_bp.toFixed(2)} bp from fair.`;
  const stat = (k, v) => el("div", { class: "qs" }, el("span", {}, k), el("b", { text: v }));
  quote.replaceChildren(
    el("div", { class: "qtop" },
      el("div", {}, el("div", { class: "qlabel" }, term("Fair rate", "fair"), ` · ${r.length_years}-year, ${r.pay_fixed ? "you pay fixed" : "you receive fixed"}`), el("div", { class: "big", text: pct(r.fair_rate, 4) })),
      el("div", { class: "qband" }, el("div", { class: "qlabel", text: "9 in 10 recent trades" }), el("div", { class: "qmid", text: `${r.low.toFixed(4)} – ${r.high.toFixed(4)}` })),
      atFair ? chip("at fair", "plain") : chip(inside ? "in line" : "unusual price", inside ? "good" : "warn")),
    range,
    line1 ? el("div", { class: "qline", text: line1 }) : el("div", { class: "qline muted", text: "Type your rate to see how it compares." }),
    el("div", { class: "qstats" }, stat("Value", money(r.value, true)), stat(term("Per bp rise", "perbp"), money(r.dv01, true)), stat(term("Normal range", "range"), `±${r.band_bp.toFixed(2)} bp`), stat("Runs", `${nice(r.start)} – ${nice(r.end)}`)),
    saveRow(),
    more("Typical gap to fair by trade size", table([{ h: "Size", f: (x) => x.size.replace(/(\d+)m/g, "$$$1m") }, { h: "Typical gap", n: 1, f: (x) => `${x.bp.toFixed(2)} bp` }], r.typical_gap_by_size_bp, { scroll: false }),
      el("p", { class: "note", text: "Bigger trades show a wider gap, but once length, venue and clearing are accounted for, size alone has no reliable effect (see Patterns)." })));
  void why;

  const [c3, b3] = card("Risk by curve point and hedge", el("span", {}, "Gain or loss if the rate at one point on the curve rises by a basis point, and the swaps that cancel it."), "c6");
  const point = (x) => (x.length < 1 ? `${x.length * 12}-month` : `${x.length}-year`);
  if (r.by_point.length <= 2) b3.append(el("div", { class: "kv" }, r.by_point.flatMap((x) => [el("span", { text: `${point(x)} point` }), el("span", { text: `${money(x.dv01, true)} per bp` })])));
  else { const ch = el("div"); bars(ch, { cats: r.by_point.map((x) => (x.length < 1 ? `${x.length * 12}m` : `${x.length}y`)), series: [{ name: "Per basis point", values: r.by_point.map((x) => x.dv01) }], bySign: true, yfmt: (v) => money(v), h: 190 }); b3.append(ch); }
  b3.append(r.hedge.length ? table([{ h: "To cancel the risk", wrap: 1, f: (x) => `${x.action === "pay fixed" ? "Pay" : "Receive"} fixed on a ${x.length} swap` }, { h: "Size", n: 1, f: (x) => size(Math.abs(x.notional)) }, { h: "At about", n: 1, f: (x) => pct(x.rate, 4) }], r.hedge, { scroll: false })
    : el("p", { class: "note", text: "No hedge needed." }), el("p", { class: "note" }, "On real trades this kind of hedge removed 99.6% of next-day risk. ", el("a", { href: "#accuracy", text: "See the test" })));

  const [c4, b4] = card("Scenarios", "Each scenario fully repriced. The last three repeat the largest real daily moves in the data.", "c6");
  const worst = Math.max(...r.stress.map((x) => Math.abs(x.change)));
  b4.append(table([{ h: "Scenario", wrap: 1, f: (x) => x.scenario.replace(/\d{4}-\d\d-\d\d/, (d) => nice(d)) }, { h: "Change in value", n: 1, f: (x) => el("span", {}, money(x.change, true), gapBar(x.change, worst / 2, true)) }], r.stress, { scroll: false }));

  const [c5, b5] = card("Since yesterday", r.explain ? `Why the value changed from ${nice(r.explain.from)} to ${nice(r.explain.to)}.` : "Not available for this start date.", "c4 tight");
  if (r.explain) b5.append(el("div", { class: "kv" }, [["Total change", r.explain.total], ["From one day passing", r.explain.time], ["From rates moving", r.explain.rates], ["Left unexplained", r.explain.rest]].flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: money(b, true) })])),
    el("p", { class: "note", text: "A small unexplained part means the risk numbers describe the trade well." }));
  const [cM, bM] = card("Every model", `Each model's rate, and its typical miss against the next real ${r.length_group} trade.`, "c8");
  const worstMiss = Math.max(...r.models.map((m) => m.miss_bp));
  const missBar = (m) => { const b = el("b"); b.style.left = "0"; b.style.width = `${Math.max(2, m.miss_bp / worstMiss * 100)}%`; b.style.background = m.used ? cv("--s1") : cv("--muted"); return el("span", { class: "gapbar", "aria-hidden": "true", style: "background:none" }, b); };
  bM.append(table([{ h: "Model", wrap: 1, f: (m) => el("span", {}, m.name.replace("Curve model", "Model").replace("Today's closing curve (outside provider)", "Same-day close").replace("Yesterday's closing curve (outside provider)", "Prior-day close"), " ", m.used ? chip("used", "good") : "") }, { h: "Fair rate", n: 1, f: (m) => pct(m.rate, 4) }, { h: "Your rate against it", n: 1, lo: 1, f: (m) => bp(m.your_gap_bp, 1) },
    { h: "Typical miss", n: 1, f: (m) => el("span", {}, `${m.miss_bp.toFixed(2)} bp`, missBar(m)) }, { h: "", wrap: 1, lo: 1, f: (m) => el("span", { class: "note", text: m.how }) }], r.models, { scroll: false }));
  const rows = [grid(c3, c4), grid(cM, c5)];
  if (r.clearing) {
    const k = r.clearing, [cC, bC] = card("Swap or future? The cost of margin", el("span", {}, "The same position as a cleared swap and as ", term("swap futures", "future"), ". Both need ", term("margin", "margin"), ", and margin has to be funded."), "c12");
    const spread = el("input", { type: "number", value: 50, min: 0, max: 500, step: "any", id: "funding", style: "width:90px" });
    const body = el("div");
    const draw = () => {
      const f = Math.max(0, Number(spread.value) || 0) / 1e4, cost = (x) => x.margin_years * f, extra = cost(k.swap) - cost(k.future);
      body.replaceChildren(headline(`${(extra / k.dv01).toFixed(2)} bp`, `on the rate: what the extra margin of a swap costs to fund (${money(extra)} over the life)`),
        table([{ h: "", sr: "Form", wrap: 1, f: (x) => el("span", {}, x[0], el("span", { class: "note", style: "display:block", text: x[2] })) }, { h: "Margin", n: 1, f: (x) => money(x[1].margin) },
          { h: "Funding cost", n: 1, f: (x) => money(cost(x[1])) }], [[`${num(k.contracts)} swap futures`, k.future, `${k.future.days}-day close-out`], ["Cleared swap", k.swap, `${k.swap.days}-day close-out`]], { scroll: false }));
    };
    spread.addEventListener("input", draw);
    bC.append(el("div", { class: "filters" }, el("label", { for: "funding" }, "Your cost of funding, bp above the overnight rate", spread)), body,
      more("How margin is worked out", el("p", { class: "note", text: `Margin is the move not exceeded in ${Math.round(k.confidence * 100)} of 100 past windows of that length, times the position's gain per basis point. The futures rule reproduces the exchange's published margins; the swap rule follows the method the clearing house describes${k.backtest ? `, and on ${num(k.backtest.days)} later days it was enough ${k.backtest.swap_pct}% of the time against a ${k.backtest.target_pct}% standard` : ""}. The exchange itself says the gap is wider, without publishing how, so that claim is not used here. One trade on its own, no netting; the funding spread is yours to set.` })));
    draw();
    rows.push(grid(cC));
  }
  out.replaceChildren(...rows);
}
function optionResult(out, r, quote) {
  const paid = r.premium_paid != null, inside = paid && r.verdict.startsWith("inside"), v = r.vol;
  const line1 = paid ? `${money(r.premium_paid)} is ${money(Math.abs(r.premium_gap))} ${r.premium_gap > 0 ? "more" : "less"} than the model's ${money(r.model_premium)}.` : null;
  const why = paid ? (r.implied_vol_bp == null ? "No level of volatility reproduces that premium: the terms or the premium are likely misreported."
    : `It implies ${r.implied_vol_bp} bp of volatility against ${v.used_bp}; ${inside ? "inside" : "outside"} what 4 in 5 comparable trades showed (±${r.vol_band_bp} bp).`) : null;
  const stat = (k, val) => el("div", { class: "qs" }, el("span", {}, k), el("b", { text: val }));
  quote.replaceChildren(
    el("div", { class: "qtop" },
      el("div", {}, el("div", { class: "qlabel", text: `Model premium · ${r.payer ? "payer" : "receiver"}, ${r.expiry_years}y into ${r.swap_years}y` }), el("div", { class: "big", text: money(r.model_premium) })),
      el("div", { class: "qband" }, el("div", { class: "qlabel", text: "Range from recent trades" }), el("div", { class: "qmid", text: `${money(r.premium_low)} – ${money(r.premium_high)}` })),
      paid ? chip(inside ? "in line" : "unusual price", inside ? "good" : "warn") : chip(`${r.model_premium_bp} bp of size`, "plain")),
    line1 ? el("div", {}, el("div", { class: "qline", text: line1 }), el("div", { class: "note", text: why })) : el("div", { class: "qline muted", text: "Enter the premium paid to check it." }),
    el("div", { class: "qstats" }, stat(term("Volatility", "vol"), `${v.used_bp} bp/yr`), stat("Forward rate", pct(r.forward_rate, 4)), stat("Strike", pct(r.strike, 4)),
      stat(term("Per bp rise", "perbp"), money(r.rate_risk_per_bp, true)), stat("Per bp of vol", money(r.vol_risk_per_bp, true))),
    saveRow());

  const [c3, b3] = card("Which volatility, and why", null, "c4");
  b3.append(el("div", { class: "kv" }, [[term("Volatility", "vol"), `${v.used_bp} bp a year`], ["Taken from", v.source], ["Last similar real trade", v.last ? `${v.last.vol_bp} bp on ${nice(v.last.day)}` : "none"],
    ["Smooth surface at this point", v.surface_bp == null ? "n/a" : `${v.surface_bp} bp`], ["Normal range around it", `±${r.vol_band_bp} bp`]].flatMap(([a, b]) => [el("span", {}, a), el("span", { text: b })])),
    el("div", { class: "takeaway" }, el("b", { text: "Why the last trade: " }), "in testing, the last similar trade predicted the next one better than a smooth surface, so it is used when it is at most three days old. The surface fills in where nothing has traded. ", el("a", { href: "#accuracy", text: "See the result" })));
  const [cM, bM] = card("Every model", "Each model's volatility and premium, and how far it has typically been from the next real trade.", "c8");
  const worstMiss = Math.max(...r.models.map((m) => m.miss_bp));
  const missBar = (m) => { const b = el("b"); b.style.left = "0"; b.style.width = `${Math.max(2, m.miss_bp / worstMiss * 100)}%`; b.style.background = m.used ? cv("--s1") : cv("--muted"); return el("span", { class: "gapbar", "aria-hidden": "true", style: "background:none" }, b); };
  bM.append(table([{ h: "Model", wrap: 1, f: (m) => el("span", {}, m.name, " ", m.used ? chip("used", "good") : "") }, { h: "Volatility", n: 1, f: (m) => `${m.vol_bp} bp` }, { h: "Premium", n: 1, f: (m) => money(m.premium) },
    ...(paid ? [{ h: "Paid against it", n: 1, f: (m) => money(r.premium_paid - m.premium, true) }] : []), { h: "Typical miss", n: 1, f: (m) => el("span", {}, `${m.miss_bp.toFixed(1)} bp of volatility`, missBar(m)) }], r.models, { scroll: false }));
  const rows = [grid(cM, c3)];
  const bz = r.bermudan;
  if (bz && !bz.error) {
    const eu = bz.european, be = bz.bermudan, wait = be.pde - eu.exact, side = r.payer ? "above" : "below";
    const [cB, bB] = card("If the right could be used on every yearly reset", el("span", {}, "A ", term("Bermudan", "bermudan"), ` option: the same right, usable on each of ${be.dates} reset dates into the swap that remains, priced by the Hull-White model calibrated on ${nice(bz.calibrated_on)}.`), "c12");
    bB.append(headline(money(be.pde), `for the right on every reset, against ${money(eu.exact)} on the first date only`, chip(`waiting is worth ${money(wait)}`, "plain")));
    const fwdLine = bz.boundary.map(() => r.forward_rate);
    line(bB, { labels: bz.boundary.map((x) => nice(x.date)), series: [{ name: "Exercise level", color: cv("--s1"), values: bz.boundary.map((x) => x.rate_pct) },
      { name: "Today's rate", color: cv("--muted"), values: fwdLine }], yfmt: (y) => `${y.toFixed(2)}%`, h: 220 });
    bB.append(el("div", { class: "takeaway" }, el("b", { text: "Reading it: " }), `on each date, using the right is better than waiting only if the swap rate then is ${side} the line. The line moves toward today's rate as fewer dates remain, because there is less left to wait for.`),
      more("Two engines, one answer", table([{ h: "", sr: "Price", wrap: 1, f: (x) => x[0] }, { h: "First date only", n: 1, f: (x) => x[1] }, { h: "Every reset", n: 1, f: (x) => x[2] }],
        [["Direct integration (exact for one date)", money(eu.exact), "n/a"], [`PDE, Crank-Nicolson, ${bz.grid} points × ${num(bz.time_steps)} steps`, money(eu.pde), money(be.pde)],
         [`Monte Carlo, Longstaff-Schwartz, ${num(bz.paths)} paths`, `${money(eu.mc)} ± ${money(eu.mc_stderr)}`, `${money(be.mc)} ± ${money(be.mc_stderr)}`]], { scroll: false }),
        el("p", { class: "note", text: `Model: pull-back speed ${bz.speed}, short-rate volatility ${bz.sigma_bp} bp a year, fitted to that day's real option trades. Its first-date price is the model's own and can differ from the market premium above. Monte Carlo fits its exercise rule on one set of paths and prices on another, so it sits slightly below the PDE: a rule learned from samples can only lose value. ` },
          el("a", { href: "#accuracy", text: "See the engine checks" }))));
    rows.push(grid(cB));
  }
  out.replaceChildren(...rows);
}

// ================================================================ Volatility
async function vol() {
  const v = await q("/api/vol");
  const exp = (t) => (t < 1 ? `${Math.round(t * 12)} month${Math.round(t * 12) === 1 ? "" : "s"}` : t === 1 ? "1 year" : `${t} years`), short = (t) => (t < 1 ? `${Math.round(t * 12)}m` : `${t}y`);
  const [c1, b1] = card(`Volatility on ${nice(v.day)}`, el("span", {}, "Expected yearly move of the swap rate, in ", term("basis points", "bp"), ". Rows: how long the option lasts. Columns: length of the swap. Stronger blue is higher. Dotted numbers have little recent trading behind them."), "c6");
  if (v.grid) {
    const flat = v.grid.flat().filter((x) => x != null), lo = Math.min(...flat), hi = Math.max(...flat);
    const t = el("table", { class: "heat" }, el("thead", {}, el("tr", {}, el("th", {}, el("span", { class: "sr", text: "Option life" })), v.tenor.map((x) => el("th", { text: `${x}y` })))));
    const tb = el("tbody");
    v.grid.forEach((row, i) => tb.append(el("tr", {}, el("th", { text: exp(v.expiry[i]) }), row.map((x, j) => {
      const td = el("td", { text: x == null ? "·" : x.toFixed(0) });
      if (x != null) { const [bg, dark] = ramp((x - lo) / (hi - lo || 1)); td.style.background = bg; td.style.color = dark ? "#0b0b0b" : "#fff"; if (v.support[i][j] < 3) td.className = "thin"; }
      return td;
    }))));
    t.append(tb);
    const hiCell = v.grid.flatMap((row, i) => row.map((x, j) => [x, i, j])).filter((c) => c[0] != null).sort((a, b) => b[0] - a[0])[0];
    b1.append(el("div", { class: "scroll flat" }, t), el("div", { class: "takeaway" }, "Highest: ", el("b", { text: `${hiCell[0].toFixed(0)} bp a year` }), ` for a ${exp(v.expiry[hiCell[1]]).replace(/ (month|year)s?$/, "-$1")} option on a ${v.tenor[hiCell[2]]}-year swap. In a year, a rate with 100 bp of volatility typically ends within about 1 percentage point of where it started.`));
  } else b1.append(el("p", { class: "note", text: "No grid for this day." }));
  const [c2, b2] = card("Recent option trades", "Standalone trades over the last five days. Each dot is the volatility, in bp a year, implied by one real premium.", "c6");
  scatter(b2, { points: v.trades.map((t) => ({ x: Math.max(t.expiry_years, 0.04), y: t.vol_bp, title: `${nice(t.day)}: ${short(t.expiry_years)} option on a ${t.swap_years}y swap`,
    rows: [{ name: "Implied volatility", value: `${t.vol_bp} bp a year` }, { name: "Strike against today's rate", value: bp(t.strike_gap_bp, 0) }, { name: "Premium", value: `${t.premium_bp} bp of size` }, { name: "Size", value: size(t.notional) }] })),
    xlog: true, xfmt: short, yfmt: (y) => y.toFixed(0), xlabel: "how long the option lasts", h: 400 });
  const [c3, b3] = card("Volatility over time", "A 1-year option on a 10-year swap.", "c12");
  line(b3, { labels: v.history_1y10y.map((x) => nice(x.day)), ...monthTicks(v.history_1y10y.map((x) => x.day), 6), series: [{ name: "1y into 10y", color: cv("--s1"), values: v.history_1y10y.map((x) => x.vol_bp) }], yfmt: (y) => y.toFixed(0), endLabels: false, h: 220 });
  page("Volatility", el("span", {}, "How much movement option buyers are paying for, read back from real premiums on ", term("swap options", "option"), "."), grid(c1, c2), grid(c3));
}

// ================================================================ Other markets
async function markets() {
  const [m, h] = await Promise.all([api("/api/markets"), api("/api/history")]);
  const names = { EUR: "Euro", GBP: "Sterling", JPY: "Yen", INR: "Indian rupee", CAD: "Canadian dollar", AUD: "Australian dollar", CHF: "Swiss franc" };
  const small = el("div", { class: "small" });
  // A curve is drawn only where at least five lengths from 1 to 30 years traded; otherwise the tile states the one rate it has.
  const tiles = Object.entries(m.curves || {}).map(([ccy, all]) => ({ ccy, all, pts: all.filter((x) => x.length >= 1 && x.length <= 30) })).sort((a, b) => b.pts.length - a.pts.length);
  const thin = [];
  for (const { ccy, all, pts } of tiles) {
    const body = el("div"), ten = pts.find((x) => x.length === 10) || pts.at(-1) || all.at(-1), n = all.reduce((a, x) => a + x.trades, 0);
    if (pts.length < 5) { thin.push(`${names[ccy] || ccy} ${ten.length}-year ${pct(ten.rate, 2)}`); continue; }
    small.append(el("section", {}, el("h3", { text: `${names[ccy] || ccy}` }), el("p", { class: "note", text: `${ten.length}-year: ${pct(ten.rate, 2)} · ${num(n)} trades` }), body));
    if (pts.length >= 5) line(body, { labels: pts.map((x) => `${x.length}y`), series: [{ name: ccy, color: cv("--s1"), values: pts.map((x) => x.rate) }], yfmt: (v) => `${v.toFixed(2)}%`, endLabels: false, h: 150, xticks: [0, pts.length - 1] });
  }
  const [c1, b1] = card("Swap curves in other currencies", "Middle traded rate at each length from 1 to 30 years, from the same public files as the dollar data.", "c12"); b1.append(small);
  if (thin.length) b1.append(el("p", { class: "note", text: `Too few lengths traded to draw a curve: ${thin.join("; ")}.` }));
  const [c2, b2] = card("Expected inflation", `What the market expects US inflation to average over each horizon, from inflation swaps. ${m.inflation_day ? nice(m.inflation_day) : ""}`, "c6");
  if (m.inflation_curve) line(b2, { labels: m.inflation_curve.map((x) => `${x.length}y`), series: [{ name: "Expected inflation", color: cv("--s1"), values: m.inflation_curve.map((x) => x.rate) }], yfmt: (v) => `${v.toFixed(2)}%`, endLabels: false, h: 220 });
  const [c3, b3] = card(el("span", {}, term("Swap rate minus Treasury yield", "spread")), "In basis points. Below zero means swaps yield less than government bonds of the same length.", "c6");
  if (h.swap_spread_bp) line(b3, { labels: h.days.map(nice), ...monthTicks(h.days), yfmt: (v) => lvl(v, 0), h: 220, series: [{ name: "2y", color: cv("--s1"), values: h.swap_spread_bp["2y"] }, { name: "10y", color: cv("--s3"), values: h.swap_spread_bp["10y"] }, { name: "30y", color: cv("--muted"), values: h.swap_spread_bp["30y"] }] });
  const [c4, b4] = card(el("span", {}, term("Overnight rate", "sofr")), "The rate the floating side of every dollar swap is built on.", "c6");
  const [c5, b5] = card("Funding pressure", "Gap between the highest and lowest 1% of overnight rates paid each day, in basis points. Spikes mark days when cash was hard to borrow.", "c6");
  if (m.funding) {
    line(b4, { labels: m.funding.days.map(nice), ...monthTicks(m.funding.days), series: [{ name: "SOFR", color: cv("--s1"), values: m.funding.rate }], yfmt: (v) => `${v.toFixed(2)}%`, endLabels: false, h: 220 });
    line(b5, { labels: m.funding.days.map(nice), ...monthTicks(m.funding.days), series: [{ name: "Spread", color: cv("--s1"), values: m.funding.spread_bp }], yfmt: (v) => v.toFixed(0), endLabels: false, h: 220, zero: true });
  }
  const rows = [grid(c1), grid(c2, c3), grid(c4, c5)];
  const ib = m.inflation_basis && (m.inflation_basis["10y"] || m.inflation_basis["5y"]);
  if (ib) {
    const tenor = m.inflation_basis["10y"] ? "10-year" : "5-year";
    const [c6, b6] = card("Inflation two ways: swaps against Treasury bonds", `Expected yearly inflation over ${tenor}s, read from inflation swaps (public trades) and from inflation-protected Treasuries (TIPS, the Federal Reserve's fitted curve). Days with at least three swap trades.`, "c12");
    b6.append(headline(`${bp(ib.last_bp, 1)}`, `swap minus bond; typical gap ${bp(ib.median_bp, 1)} over ${ib.days_used} days`, chip(`latest TIPS curve ${nice(ib.last_day).replace(/ \d{4}$/, "")}`, "plain")));
    line(b6, { labels: ib.days.map(nice), ...monthTicks(ib.days), yfmt: (v) => `${v.toFixed(2)}%`, h: 240, endLabels: false,
      series: [{ name: "Inflation swaps", color: cv("--s1"), values: ib.swap }, { name: "TIPS breakeven", color: cv("--s2"), values: ib.bond }] });
    b6.append(el("div", { class: "takeaway" }, el("b", { text: "Why they differ: " }), "Both measure the same thing, so the gap is a price: swaps usually sit above TIPS because TIPS are harder to trade and to fund, and part of a breakeven is a liquidity discount rather than lower expected inflation.",
      " A gap far from its usual level is a relative-value signal desks watch; it is not a forecast of inflation."));
    rows.push(grid(c6));
  }
  page("Other markets", "Rates products found in the same free public files, plus Treasury and funding data from the Federal Reserve.", ...rows);
}

// ================================================================ Patterns
async function patterns() {
  const p = await api("/api/insights"), rc = p.rich_cheap, ir = p.implied_realised, cm = p.cross_market, gd = p.gap_drivers, ec = p.execution_cost, dl = p.diebold_li;
  const kv = (rows) => el("div", { class: "kv" }, rows.flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: b })]));
  const [c0, b0] = card("What the data says", null, "c12");
  const top = rc[0], us = cm.labels.indexOf("US 10y");
  const short = (l) => l.replace(/ \d+y$/, "");
  const partners = cm.labels.map((l, i) => [l, cm.matrix[us][i]]).filter(([l, v]) => !l.startsWith("US") && l !== "Option volatility" && v != null).sort((a, b) => b[1] - a[1]);
  const roll = ec.roll_spread.map((r) => r.spread_bp).filter((x) => x != null);
  b0.append(el("div", { class: "brief" }, el("ul", {},
    el("li", {}, el("span", { class: "n", text: "1" }), el("span", {}, "Options have charged for more movement than actually happened on ", el("b", { text: `${ir.share_of_days_implied_above.toFixed(0)}% of days` }), `. Right now they charge ${ir.now.implied.toFixed(0)} bp a year against ${ir.now.realised.toFixed(0)} realised.`)),
    el("li", {}, el("span", { class: "n", text: "2" }), el("span", {}, "The dollar 10-year rate moves most closely with ", el("b", { text: `${short(partners[0][0])} (${partners[0][1].toFixed(2)})` }), ` and least with ${short(partners.at(-1)[0])} (${lvl(partners.at(-1)[1], 2)}).`)),
    el("li", {}, el("span", { class: "n", text: "3" }), el("span", {}, Math.abs(top.z) >= 1.5 ? `The most stretched part of the curve is the ${top.name}, ${Math.abs(top.z).toFixed(1)} standard deviations ${top.z > 0 ? "above" : "below"} its 60-day average.`
      : `No part of the curve is stretched against its own recent history: the largest reading is ${Math.abs(top.z).toFixed(1)} standard deviations (${top.name}).`)),
    el("li", {}, el("span", { class: "n", text: "4" }), el("span", {}, "The spread implied by trade prices alone is ", el("b", { text: `${Math.min(...roll).toFixed(2)} to ${Math.max(...roll).toFixed(2)} bp` }),
      ", about the size of the model's typical miss: the model is near the floor set by the market's own bounce between buyers and sellers.")))));

  const [c1, b1] = card("Stretched or normal? The curve against its own history", "Each row is a difference between rates. The score is how many standard deviations today sits from its 60-day average; beyond 2 is unusual.", "c7");
  b1.append(headline(`${Math.abs(top.z).toFixed(1)} sd`, `largest reading today (${top.name})`, Math.abs(top.z) >= 2 ? chip("stretched", "warn") : chip("all normal", "plain")));
  b1.append(table([{ h: "Measure", wrap: 1, f: (r) => r.name }, { h: "Now", n: 1, f: (r) => `${lvl(r.now_bp)} bp` }, { h: "60d avg", lo: 1, n: 1, f: (r) => `${lvl(r.mean_60d_bp)} bp` },
    { h: "Score", n: 1, f: (r) => el("span", {}, lvl(r.z, 2), gapBar(r.z, 2)) }, { h: "", sr: "Reading", f: (r) => (Math.abs(r.z) >= 2 ? chip("stretched", "warn") : chip("normal", "plain")) },
    { h: "1y rank", lo: 1, n: 1, f: (r) => `${r.percentile_1y.toFixed(0)}%` }], rc, { scroll: false }),
    el("p", { class: "note", text: "Rank is the share of the past year that was lower. A stretched reading is a prompt to look, not a signal to trade." }));
  const [c2, b2] = card("Implied against realised volatility", "What options charge for movement of the 10-year rate, against how much it moved over the previous 20 days. Basis points a year.", "c5");
  b2.append(headline(`${ir.share_of_days_implied_above.toFixed(0)}%`, "of days, options charged for more movement than happened"));
  line(b2, { labels: ir.days.map(nice), ...monthTicks(ir.days, 4), yfmt: (v) => v.toFixed(0), h: 250, endLabels: false, series: [{ name: "Charged by options", color: cv("--s1"), values: ir.implied }, { name: "Actually moved", color: cv("--s2"), values: ir.realised }] });

  const [c3, b3] = card("Which markets move together", "Correlation of daily changes over the past year. 1 means they always move together, 0 means no relation, below 0 means opposite. Columns follow the same order as the rows.", "c8");
  const code = (l) => (l.startsWith("US ") && !l.includes("inflation") ? l : ({ Euro: "EUR", Sterling: "GBP", Yen: "JPY", Canada: "CAD", Swiss: "CHF", India: "INR", "US inflation": "Infl.", "Option volatility": "Vol" }[short(l)] || short(l)));
  const both = (wide, narrow) => [el("span", { class: "full", text: wide }), el("span", { class: "mini", text: narrow })];
  const t = el("table", { class: "heat corr" }, el("thead", {}, el("tr", {}, el("th", {}, el("span", { class: "sr", text: "Market" })), cm.labels.map((l, k) => el("th", { title: l }, both(code(l), String(k + 1)))))));
  const tb = el("tbody");
  cm.matrix.forEach((row, i) => tb.append(el("tr", {}, el("th", {}, both(cm.labels[i], `${i + 1} ${code(cm.labels[i])}`)), row.map((v, j) => {
    const td = el("td", {}, v == null ? "·" : i === j ? "" : both(lvl(v, 2), lvl(Math.round(v * 100), 0)));
    if (v != null && i !== j) { const [bg, dark] = v >= 0 ? ramp(v, "--mid", "--pos") : ramp(-v, "--mid", "--neg"); td.style.background = bg; td.style.color = dark ? "#0b0b0b" : "#fff"; }
    return td;
  }))));
  t.append(tb);
  b3.append(headline(lvl(partners[0][1], 2), `correlation of the dollar 10-year with ${short(partners[0][0])}, the closest outside the US`), el("div", { class: "scroll flat" }, t), el("p", { class: "note" }, el("span", { class: "mini", text: "Numbers across the top are the numbered rows; values are in hundredths, so 85 means 0.85. " }), "Other currencies are daily middles of thin trading in a different time zone, so their true link to dollar rates is stronger than shown."));
  const [c4, b4] = card("Is the link stable?", "Correlation with the dollar 10-year rate over a moving 60-day window.", "c4");
  const names = Object.keys(cm.rolling).filter((k) => k !== "days");
  const lastOf = (n) => cm.rolling[n].filter((x) => x != null).at(-1);
  b4.append(headline(lvl(lastOf(names[0]), 2), `${short(names[0])}, last 60 days`));
  line(b4, { labels: cm.rolling.days.map(nice), ...monthTicks(cm.rolling.days, 3), yfmt: (v) => lvl(v, 1), h: 360, zero: true, endLabels: false, series: names.map((n, i) => ({ name: short(n), color: cv(["--s1", "--s3", "--muted"][i]), values: cm.rolling[n] })) });

  const hours = p.time_of_day.map((x) => String(x.hour_utc).padStart(2, "0"));
  const [c5, b5] = card("When the market is busy", "Clean trades per day by hour (UTC). New York opens around 13:00.", "c6");
  const busiest = p.time_of_day.slice().sort((a, b) => b.trades_per_day - a.trades_per_day)[0], noisiest = p.time_of_day.slice().sort((a, b) => b.median_gap_bp - a.median_gap_bp)[0];
  b5.append(headline(`${String(busiest.hour_utc).padStart(2, "0")}:00`, `busiest hour UTC, ${busiest.trades_per_day.toFixed(0)} clean trades a day`));
  bars(b5, { cats: hours, series: [{ name: "Clean trades per day", color: cv("--s1"), values: p.time_of_day.map((x) => x.trades_per_day) }], yfmt: (v) => v.toFixed(0), h: 220 });
  const [c6, b6] = card("When prices are noisiest", "Typical gap to fair by hour (UTC), in basis points. Trades land further from fair in the busy New York morning, when rates move fastest.", "c6");
  b6.append(headline(`${noisiest.median_gap_bp.toFixed(2)} bp`, `typical gap at ${String(noisiest.hour_utc).padStart(2, "0")}:00 UTC, the noisiest hour`));
  bars(b6, { cats: hours, series: [{ name: "Typical gap, bp", color: cv("--s1"), values: p.time_of_day.map((x) => x.median_gap_bp) }], yfmt: (v) => v.toFixed(2), h: 220 });

  const [c8, b8] = card("What moves a trade away from fair", `A regression on ${num(ec.trades)} trades, with errors grouped by day.`, "c7 tight");
  const sure = ec.terms.slice(1).filter((r) => Math.abs(r.t) >= 2).sort((a, b) => Math.abs(b.bp) - Math.abs(a.bp));
  b8.append(headline(`${(ec.r_squared * 100).toFixed(1)}%`, "of the gap is explained by what is visible about a trade", chip("mostly noise", "plain")),
    el("p", { class: "note", text: `Largest reliable effects: ${sure.slice(0, 3).map((r) => `${r.term.toLowerCase()} ${bp(r.bp, 2)}`).join("; ")}. Trade size has no reliable effect.` }),
    more("All effects", table([{ h: "Effect", wrap: 1, f: (r) => r.term }, { h: "Gap changes by", n: 1, f: (r) => bp(r.bp, 3) }, { h: "t-statistic", lo: 1, n: 1, f: (r) => lvl(r.t, 1) },
      { h: "", sr: "Reliable", f: (r) => (Math.abs(r.t) >= 2 ? chip("reliable", "good") : chip("not reliable", "plain")) }], ec.terms.slice(1), { scroll: false }),
      el("p", { class: "note", text: `Baseline gap ${ec.terms[0].bp.toFixed(2)} bp. Method follows studies of swap execution costs on regulatory trade data.` })));
  const [c9, b9] = card("Effective spread without quotes", "Roll's estimator: the bounce between successive trade prices implies a spread.", "c5 tight");
  b9.append(headline(`${Math.min(...roll).toFixed(2)} to ${Math.max(...roll).toFixed(2)} bp`, "spread implied by trade prices alone"),
    table([{ h: "Swap length", f: (r) => r.length }, { h: "Trades", lo: 1, n: 1, f: (r) => num(r.trades) }, { h: "Implied spread", n: 1, f: (r) => (r.spread_bp == null ? "not measurable" : `${r.spread_bp.toFixed(2)} bp`) }], ec.roll_spread, { scroll: false }));

  const flowRows = [], nulls = [], detail = [];
  if (p.flow) {
    const cl = p.flow.clustering, sf = p.flow.signed_flow, ld = p.flow.late_day;
    const [f1, g1] = card("Do trades trigger more trades?", "Seconds with a trade, per minute, around the 8:30 New York releases of consumer prices and jobs.", "c7");
    g1.append(headline(`${cl.calendar.median_jump.toFixed(1)}×`, "as many seconds with a trade in the first five minutes after a release as on other mornings"));
    line(g1, { labels: cl.profile.minutes, h: 250, endLabels: false, zero: true, yfmt: (v) => v.toFixed(1), xticks: [0, 10, 25, 40, 55, 69], series: [{ name: `Release days (${cl.calendar.release_days})`, color: cv("--s1"), values: cl.profile.release }, { name: `Other days (${cl.calendar.other_days})`, color: cv("--s2"), values: cl.profile.other }] });
    const [f2, g2] = card("Share of trading that is a reaction to earlier trades", "A self-exciting (Hawkes) model fitted to every second. 0 means trades arrive on their own; 1 means trading feeds on itself.", "c5 tight");
    const sets = [["8:30 hour, release days", cl.release], ["8:30 hour, other days", cl.other], ["10:30 hour, other days", cl.midmorning]];
    g2.append(headline(cl.release.branching.toFixed(2), `on release mornings, against ${cl.other.branching.toFixed(2)} on other mornings`, chip("no rise", "plain")),
      el("div", { class: "takeaway" }, el("b", { text: "The trap: " }), `fitted naively, release mornings score ${cl.release_flat_baseline.branching.toFixed(2)}. That is the burst of news, not trades triggering trades.`),
      more("By hour", table([{ h: "Hours", wrap: 1, f: (x) => x[0] }, { h: "Share", n: 1, f: (x) => `${x[1].branching.toFixed(2)} ± ${x[1].branching_se.toFixed(2)}` }, { h: "Fades in", n: 1, f: (x) => `${Math.round(x[1].half_life_s)} s` }], sets, { scroll: false })));
    flowRows.push(grid(f1, f2));
    nulls.push(["Net paying flow", "the rate over the next ten minutes", sf.next_interval.out_of_sample_r_squared <= 0 ? "none: on later days it does worse than assuming no change" : `${(sf.next_interval.out_of_sample_r_squared * 100).toFixed(2)}% of the variation explained on later days`, chip("no", "plain")],
      ["A move of 8 bp or more by 2 pm", "more of the same until 4 pm", `${ld.same_direction_pct.toFixed(0)}% continued, on ${ld.big_days} days`, chip("no", "plain")]);
    detail.push(more("Net paying flow", kv([["Trades given a side from where they printed against fair", `${sf.signed_share_pct.toFixed(1)}% of ${num(sf.trades)}`], ["Move in the same ten minutes, per $1bn of net paying", `${bp(sf.same_interval.bp_per_bn, 2)} (t ${lvl(sf.same_interval.t, 1)})`],
      ["Move in the next ten minutes, per $1bn", `${bp(sf.next_interval.bp_per_bn, 2)} (t ${lvl(sf.next_interval.t, 1)})`]]),
      el("p", { class: "note", text: "Paying flow lifts the rate while it trades, and part of that is built in, because the model learns from those same trades. Flow is in billions of ten-year equivalents." })),
      more("A move of 8 bp or more by 2 pm", kv([["Days with a move of 8 bp or more by 2 pm New York", `${ld.big_days} of ${ld.days}`], ["Kept going in the same direction until 4 pm", `${ld.same_direction_pct.toFixed(1)}%`], ["Average continuation", `${bp(ld.mean_continuation_bp, 2)} (t ${lvl(ld.t, 2)})`]])));
  }
  if (dl.horizons.length) {
    const one = dl.horizons[0], ten = dl.lengths.indexOf("10y");
    nulls.push(["A three-factor model of the curve (Diebold-Li)", "tomorrow's curve", `${one.model_rmse_bp[ten].toFixed(1)} bp error against ${one.random_walk_rmse_bp[ten].toFixed(1)} bp for assuming no change (10-year)`, chip("no change wins", "warn")]);
    const rows = dl.horizons.flatMap((x) => [{ h: x, who: "Diebold-Li", v: x.model_rmse_bp }, { h: x, who: "No change", v: x.random_walk_rmse_bp }]);
    detail.push(more("A three-factor model of the curve (Diebold-Li), by horizon", table([{ h: "Days", f: (r) => (r.who === "Diebold-Li" ? r.h.days_ahead : "") }, { h: "Forecast", f: (r) => r.who }, ...dl.lengths.map((l, i) => ({ h: l, n: 1, lo: l !== "10y", f: (r) => r.v[i].toFixed(2) })),
      { h: "Verdict", f: (r) => (r.who === "Diebold-Li" ? (r.h.t_stat < -2 ? chip("model wins", "good") : r.h.t_stat > 2 ? chip("no change wins", "warn") : chip("no reliable difference", "plain")) : "") }], rows, { scroll: false }),
      el("p", { class: "note", text: `Error in basis points on ${dl.days} days. The three factors describe each day's curve to within ${dl.fit_rmse_bp.toFixed(1)} bp; forecasting it is another matter.` })));
  } else nulls.push(["A three-factor model of the curve (Diebold-Li)", "tomorrow's curve", `needs about ${dl.needs_days || 240} trading days of history; ${dl.days} are loaded`, chip("not run", "plain")]);
  nulls.push(["Size, length, hour and venue of a trade", "how far it lands from fair", `${gd.improvement_pct.toFixed(1)}% better than guessing the typical gap, on ${num(gd.test_trades)} later trades`, chip("barely", "plain")]);
  const worst = gd.importance[0].worsening_bp;
  const impBar = (r) => { const b = el("b"); b.style.left = "0"; b.style.width = `${Math.max(1, r.worsening_bp / worst * 100)}%`; b.style.background = cv("--s1"); return el("span", { class: "gapbar", "aria-hidden": "true", style: "background:none" }, b); };
  detail.push(more("Size, length, hour and venue: what the model leans on", table([{ h: "Input", wrap: 1, f: (r) => r.feature }, { h: "Error added when scrambled", n: 1, f: (r) => el("span", {}, `${r.worsening_bp.toFixed(4)} bp`, impBar(r)) }], gd.importance, { scroll: false }),
    el("p", { class: "note", text: `Gradient-boosted trees trained on trades before ${nice(gd.train_until)}. Average error ${gd.mae_model_bp.toFixed(3)} bp against ${gd.mae_baseline_bp.toFixed(3)} bp for always guessing the typical gap.` })));
  const [cN, bN] = card(`${nulls.length} things that do not predict`, "Each was tested on days or trades it had not seen. Knowing what does not work is part of the result.", "c12");
  bN.append(table([{ h: "This", wrap: 1, f: (r) => r[0] }, { h: "Does it predict", wrap: 1, lo: 1, f: (r) => r[1] }, { h: "Result", wrap: 1, f: (r) => r[2] }, { h: "", sr: "Verdict", f: (r) => r[3] }], nulls, { scroll: false }), ...detail);
  page("Patterns", "Standard desk analytics and published models, on two years of data. None is a forecast.", grid(c0), grid(c1, c2), grid(c3, c4), grid(c5, c6), ...flowRows, grid(c8, c9), grid(cN));
}

// ================================================================ Model lab
async function lab() {
  const out = el("div", { style: "display:grid;gap:16px" });
  const f = {};
  const slider = (name, label, hint, min, max, step, value, fmt) => {
    const show = el("b", { text: fmt(value) });
    f[name] = el("input", { type: "range", id: `lab-${name}`, min, max, step, value });
    f[name].addEventListener("input", () => { show.textContent = fmt(+f[name].value); });
    return el("label", {}, el("span", {}, label, " ", show), f[name], el("small", { text: hint }));
  };
  const form = el("form", { class: "terms" },
    slider("noise_bp", "Noise in a single trade", "Lower trusts each trade more", 0.05, 2, 0.05, 0.15, (v) => `${v.toFixed(2)} bp`),
    slider("surprise_limit", "Surprise limit", "Beyond this a trade is damped", 1.5, 10, 0.5, 3, (v) => `${v} sd`),
    slider("history_days", "History for how rates move together", "Days of past data", 30, 250, 10, 120, (v) => `${v} days`),
    slider("days", "Test on the last", "Trading days of real trades", 5, 60, 5, 20, (v) => `${v} days`),
    el("button", { class: "btn", type: "submit", text: "Run on real trades" }));
  const run = async () => {
    out.replaceChildren(el("p", { class: "note", text: "Running the model…" }));
    try {
      const r = await api("/api/lab", { method: "POST", body: Object.fromEntries(Object.entries(f).map(([k, v]) => [k, +v.value])) });
      const diff = (1 - r.yours.median_bp / r.frozen.median_bp) * 100;
      const win = `last ${r.window.days} days`;
      const kp = el("div", { class: "kpis" }, kpi(`Typical miss, your settings, ${win}`, `${r.yours.median_bp.toFixed(2)} bp`, `95 in 100 within ${r.yours.p95_bp.toFixed(2)} bp`), kpi(`Published settings, ${win}`, `${r.frozen.median_bp.toFixed(2)} bp`, `95 in 100 within ${r.frozen.p95_bp.toFixed(2)} bp`),
        kpi(`Last trade, ${win}`, `${r.last_trade.median_bp.toFixed(2)} bp`, "the simple alternative to beat"), kpi("Trades damped", `${r.yours.damped_pct.toFixed(1)}%`, `published: ${r.frozen.damped_pct.toFixed(1)}%`));
      const [c1, b1] = card("Day by day", `Typical miss on ${num(r.window.trades)} real trades, ${nice(r.window.from)} to ${nice(r.window.to)}.`, "c12");
      const counts = r.daily.trades || [], usual = counts.slice().sort((a, b) => a - b)[Math.floor(counts.length / 2)] || 0;
      const full = r.daily.days.map((_, i) => i).filter((i) => !(counts[i] < usual / 5)), thin = r.daily.days.map((d, i) => [d, counts[i]]).filter(([, n]) => n < usual / 5);
      // Published settings are drawn dashed and first, so the solid line for your settings stays visible where the two agree.
      line(b1, { labels: full.map((i) => nice(r.daily.days[i])), yfmt: (v) => v.toFixed(2), h: 240, zero: true, endLabels: false,
        series: Math.abs(diff) < 1e-9 ? [{ name: "Your settings = published settings", color: cv("--s1"), values: full.map((i) => r.daily.yours[i]) }]
          : [{ name: "Published settings", color: cv("--s2"), dash: true, values: full.map((i) => r.daily.frozen[i]) }, { name: "Your settings", color: cv("--s1"), values: full.map((i) => r.daily.yours[i]) }] });
      if (thin.length) b1.append(el("p", { class: "note", text: `Left out: ${thin.map(([d, n]) => `${nice(d)} (${n} trades against a usual ${num(usual)})`).join("; ")}.` }));
      b1.prepend(el("div", { class: "verdict" }, el("div", {}, chip(Math.abs(diff) < 1 ? "about the same" : diff > 0 ? "better on this window" : "worse on this window", Math.abs(diff) < 1 ? "plain" : diff > 0 ? "good" : "warn")),
        el("div", { class: "why", text: Math.abs(diff) < 1 ? "Your settings and the published ones perform alike here." : `Your settings miss by ${Math.abs(diff).toFixed(1)}% ${diff > 0 ? "less" : "more"} than the published ones on this window.` })),
        el("div", { class: "takeaway" }, el("b", { text: "A caution: " }), "settings chosen on the same trades they are scored on always look good. The published ones were fixed after the first 60 days and never revisited."));
      out.replaceChildren(kp, grid(c1));
    } catch (e) { out.replaceChildren(el("p", { class: "err", text: `Could not run: ${e.message}` })); }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  const [cF, bF] = card("Settings", "Change how the curve model learns from trades, then rerun it on recent real trades.", "c12");
  bF.append(form);
  page("Model lab", "Calibrate the curve model yourself and see what each setting does.", grid(cF), out);
  run();
}

// ================================================================ Accuracy
async function accuracy() {
  const [s, extra, ec] = await Promise.all([api("/api/scorecard"), api("/api/insights").catch(() => ({})), api("/api/engine-checks").catch(() => null)]), fu = extra.futures, sw = s.swaps, op = s.options, rk = s.risk, v = s.validation, o = sw.overall;
  const kv = (rows) => el("div", { class: "kv" }, rows.flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: b })]));
  const kp = el("div", { class: "kpis" },
    kpi("Typical miss, model, all trades", `${o.filter.median_bp.toFixed(2)} bp`, `95 in 100 trades within ${o.filter.p95_bp.toFixed(2)} bp`),
    kpi("Typical miss, last trade, all trades", `${o.last.median_bp.toFixed(2)} bp`, "the simple alternative: the last trade of the same length"),
    kpi(el("span", {}, "Trades inside the ", term("normal range", "range")), `${(sw.coverage.calibrated * 100).toFixed(1)}%`, `the target is ${(sw.coverage.target * 100).toFixed(0)}%`),
    kpi("Next-day risk removed by hedging", `${rk.risk_removed_pct.bucket_hedge.toFixed(1)}%`, `${num(rk.trades)} real trades`));
  const [c0, b0] = card("What this page shows", null, "c12");
  b0.append(el("div", { class: "brief" }, el("ul", {},
    el("li", {}, el("span", { class: "n", text: "1" }), el("span", {}, "Every figure is ", term("out of sample", "oos"), `: ${num(o.filter.n)} trades between ${nice(sw.period[0])} and ${nice(sw.period[1])}, each predicted before it was used.`)),
    el("li", {}, el("span", { class: "n", text: "2" }), el("span", {}, `Over ${sw.filter_vs_last.days} trading days the model beats the last trade by a margin far beyond chance (Diebold-Mariano statistic ${Math.abs(sw.filter_vs_last.t_stat).toFixed(1)}; above 2 is conventionally significant).`)),
    el("li", {}, el("span", { class: "n", text: "3" }), el("span", {}, "Where it loses, this page says so: for swap options the last similar trade wins, and short forward-starting swaps are a weak spot.")))));

  const lens = Object.keys(sw.by_length);
  const prior = lens.map((l) => sw.by_length[l].prev_close.median_bp);
  const [c1, b1] = card("Typical miss by swap length", `Gap between the prediction and the real trade, in basis points. Lower is better. The prior-day close misses by ${Math.min(...prior).toFixed(1)} to ${Math.max(...prior).toFixed(1)} bp and is left off so these two can be compared.`, "c7");
  bars(b1, { cats: lens, yfmt: (x) => x.toFixed(2), h: 300, series: [{ name: "Model", color: cv("--s1"), values: lens.map((l) => sw.by_length[l].filter.median_bp) },
    { name: "Last trade", color: cv("--s2"), values: lens.map((l) => sw.by_length[l].last.median_bp) }] });
  const fw = sw.forwards;
  const [c2, b2] = card("Swaps that start in the future", "Never used to fit anything, so a fully held-out test.", "c5 tight");
  b2.append(headline(`${fw.overall.filter.median_bp.toFixed(2)} bp`, `typical miss on ${num(fw.overall.filter.n)} held-out swaps, against ${fw.overall.prev_close.median_bp.toFixed(2)} bp for the prior-day close`, chip("holds", "good")),
    el("div", { class: "takeaway" }, el("b", { text: "Weak spot: " }), `forwards shorter than a year (${fw.by_length[Object.keys(fw.by_length)[0]].filter.median_bp.toFixed(2)} bp). The curve is smooth between yearly points and cannot see central bank meeting dates.`),
    ...(fw.meeting_steps ? [el("p", { class: "note", text: `Steps on Fed meeting dates, same curve points: ${Object.entries(fw.meeting_steps).map(([k, x]) => `${k} ${x.smooth_bp.toFixed(2)} → ${x.steps_bp.toFixed(2)} bp (better on ${x.days_better_pct.toFixed(0)}% of ${x.days} days, t ${Math.abs(x.t).toFixed(1)})`).join("; ")}. ${Object.entries(fw.meeting_steps).map(([k, x]) => `${k}: ${Math.abs(x.t) >= 2 && x.daily_diff_bp < 0 ? "a small, reliable gain" : "no reliable difference"}`).join("; ")}. Most of the short-end miss comes from the curve points themselves, not their shape.` })] : []),
    more("By start and by length", table([{ h: "Group", f: (r) => r[0] }, { h: "Trades", lo: 1, n: 1, f: (r) => num(r[1].filter.n) }, { h: "Model", n: 1, f: (r) => `${r[1].filter.median_bp.toFixed(2)} bp` }, { h: "Yesterday", n: 1, f: (r) => `${r[1].prev_close.median_bp.toFixed(2)} bp` }],
      [["All", fw.overall], ...Object.entries(fw.by_start), ...Object.entries(fw.by_length)], { scroll: false })));

  const months = Object.keys(sw.by_month).filter((m) => sw.by_month[m].filter.n > 2000);
  const even = months.map((m, i) => [m, i]).filter(([m]) => (+m.slice(5, 7) - 1) % 4 === 0);
  const mt = { xticks: even.map(([, i]) => i), xtext: even.map(([m]) => niceMonth(m)) };
  const [c3, b3] = card("Is the normal range honest?", "Share of trades that landed inside the range each month. A range built to hold 90% should hold about 90%.", "c6");
  b3.append(headline(`${(sw.coverage.calibrated * 100).toFixed(1)}%`, "of trades landed inside, against a 90% target", chip("honest", "good")));
  line(b3, { labels: months.map(niceMonth), ...mt, series: [{ name: "Inside the range", color: cv("--s1"), values: months.map((m) => sw.by_month[m].coverage * 100) }], yfmt: (x) => `${x.toFixed(0)}%`, ydomain: [80, 100], ref: { y: 90, label: "target" }, endLabels: false, h: 200 });
  b3.append(el("p", { class: "note", text: `Without calibration the range would hold only ${(sw.coverage.uncalibrated * 100).toFixed(0)}%: errors have fatter tails than a textbook assumes. It is rescaled using past errors only.` }));
  const [c4, b4] = card("Is accuracy stable?", "Typical miss each month, in basis points. A good average can hide bad stretches; this shows there are none.", "c6");
  const beat = months.filter((m) => sw.by_month[m].filter.median_bp < sw.by_month[m].last.median_bp).length;
  b4.append(headline(`${beat} of ${months.length}`, "months the model beat the last trade", chip(beat === months.length ? "every month" : "most months", "good")));
  line(b4, { labels: months.map(niceMonth), ...mt, yfmt: (x) => x.toFixed(2), h: 220, zero: true, series: [{ name: "Model", color: cv("--s1"), values: months.map((m) => sw.by_month[m].filter.median_bp) }, { name: "Last trade", color: cv("--s2"), values: months.map((m) => sw.by_month[m].last.median_bp) }] });

  const [cB, bB] = card("Bias audit", "Each known way a result can flatter itself, tested against the data.", "c12");
  if (v.bias_audit) {
    const a = v.bias_audit, h = a.hindsight, sel = a.selection;
    const rows = [
      ["Look-ahead", `Predictions for ${num(a.look_ahead.trades_compared)} trades computed with and without later trades present`, a.look_ahead.passed ? "Identical: none" : "Differences found", a.look_ahead.passed],
      ["Tuning on the test", `Settings chosen on the ${a.settings.chosen_on}, then frozen`, "No decay in later periods", true],
      ["Hindsight from amendments", `${h.amended_share_pct.toFixed(1)}% of scored trades were amended later`, `Never amended ${h.median_bp_never_amended.toFixed(2)} bp; amended ${h.median_bp_amended.toFixed(2)} bp`, true],
      ["Late publication", `${h.known_a_day_or_more_late_pct.toFixed(1)}% became public a day or more late`, `Same-day trades alone: ${h.median_bp_known_same_day.toFixed(2)} bp`, true],
      ["Repeated rows", "One execution published as several identical rows", `${a.repeats.collapsed_pct.toFixed(1)}% collapsed before scoring`, true],
      ["Survivorship", `${num(h.cancelled_trades_removed)} cancelled trades removed (${h.cancelled_share_of_new_reports_pct.toFixed(1)}% of new reports)`, "Stated limit: history is the corrected record", null],
      ...Object.entries(sel.excluded).map(([k, x]) => [`Selection: ${k}`, `${num(x.scored)} excluded trades priced with the same curve, never fitted`, `${x.median_bp.toFixed(2)} bp against ${sel.clean_median_bp.toFixed(2)} bp on clean trades`, null]),
    ];
    const cols = [{ h: "Bias", wrap: 1, f: (r) => r[0] }, { h: "How it was tested", lo: 1, wrap: 1, f: (r) => r[1] }, { h: "Result", wrap: 1, f: (r) => r[2] },
      { h: "", sr: "Verdict", f: (r) => (r[3] === true ? chip("clear", "good") : r[3] === false ? chip("found", "crit") : chip("disclosed", "plain")) }];
    const clear = rows.filter((r) => r[3] === true), rest = rows.filter((r) => r[3] !== true);
    bB.append(headline(`${clear.length} of ${rows.length}`, `checks are clear; the other ${rest.length} are limits of the public record, measured and stated`, rows.some((r) => r[3] === false) ? chip("bias found", "crit") : chip("no bias found", "good")),
      table(cols, clear, { scroll: false }), more(`The ${rest.length} stated limits: survivorship and excluded trades`, table(cols, rest, { scroll: false })));
  } else bB.append(el("p", { class: "note", text: "Run `python -m tapemark score` to build the audit." }));

  const [c5, b5] = card("Does it depend on its settings?", "One setting changed at a time.", "c7");
  if (v.sensitivity) {
    const kept = v.sensitivity.filter((r) => !/no damping/.test(r.setting)).map((r) => r.median_bp), off = v.sensitivity.find((r) => /no damping/.test(r.setting));
    b5.append(headline(`${Math.min(...kept).toFixed(2)} to ${Math.max(...kept).toFixed(2)} bp`, `typical miss across ${kept.length} variations of the settings`, chip("stable", "good")),
      el("div", { class: "takeaway" }, el("b", { text: "The one that matters: " }), off ? `with damping of absurd trades switched off the miss rises to ${off.median_bp.toFixed(2)} bp. ` : "", "Settings were chosen on the first 60 days and frozen."),
      more("Every variation", table([{ h: "Setting", wrap: 1, f: (r) => r.setting }, { h: "Typical", n: 1, f: (r) => r.median_bp.toFixed(2) }, { h: "Worst 5%", n: 1, f: (r) => r.p95_bp.toFixed(2) },
        ...[0, 1, 2, 3].map((i) => ({ h: `P${i + 1}`, n: 1, lo: 1, f: (r) => (r.by_block?.[i] == null ? "" : r.by_block[i].toFixed(2)) }))], v.sensitivity, { scroll: false }),
        el("p", { class: "note", text: "Miss in basis points. P1 to P4 are four consecutive stretches of the test period." })));
  }
  const [c6, b6] = card("On the most violent days", v.stress_days ? `The ${v.stress_days.wild_days} days when the 10-year rate moved more than ${v.stress_days.threshold_bp.toFixed(1)} bp.` : "", "c5 tight");
  if (v.stress_days) {
    const w = v.stress_days;
    b6.append(headline(`${w.wild.filter.median_bp.toFixed(2)} bp`, `typical miss on those days, against ${w.calm.filter.median_bp.toFixed(2)} bp on the rest`, chip("holds", "good")),
      more("Against the alternatives", table([{ h: "", sr: "Days", f: (r) => r[0] }, { h: "Model", n: 1, f: (r) => r[1].filter.median_bp.toFixed(2) }, { h: "Last trade", n: 1, f: (r) => r[1].last.median_bp.toFixed(2) }, { h: "Yesterday", lo: 1, mid: 1, n: 1, f: (r) => r[1].prev_close.median_bp.toFixed(2) }, { h: "In range", n: 1, f: (r) => `${(r[2] * 100).toFixed(0)}%` }],
        [["Violent days", w.wild, w.coverage_wild], ["Other days", w.calm, w.coverage_calm]], { scroll: false }),
        el("p", { class: "note", text: `Typical miss in basis points. Largest moves: ${w.largest_moves.map((m) => `${nice(m.day)} (${m.ten_year_move_bp.toFixed(1)} bp)`).join(", ")}.` })));
  }

  const [c7, b7] = card("Swap options: the last similar trade wins", "Predicting the volatility of each standalone option trade from earlier trades. Typical miss in basis points of yearly volatility.", "c6");
  const ov = op.standalone.vol_bp;
  const optModels = [["One flat level", "flat"], ["Last similar trade", "last"], ["Smooth surface", "surface"], ["Surface + strike", "smile"], ["Last trade + surface", "anchored"], ["Hull-White model", "hull_white"]].filter(([, k]) => ov[k]);
  const best = Math.min(...optModels.map(([, k]) => ov[k].median)), worst = Math.max(...optModels.map(([, k]) => ov[k].median));
  b7.append(headline(`${best.toFixed(1)} bp`, "typical miss of the last similar trade, the best of six methods", chip("simple wins", "plain")));
  b7.append(el("div", { class: "ranked" }, optModels.slice().sort((x, y) => ov[x[1]].median - ov[y[1]].median).map(([n, k]) => {
    const bar = el("i"); bar.style.width = `${Math.max(1, 100 * ov[k].median / worst)}%`;
    return el("div", { class: `rk ${ov[k].median === best ? "best" : ""}` }, el("span", { text: n }), el("div", {}, bar), el("b", { text: `${ov[k].median.toFixed(1)} bp` }));
  })));
  b7.append(el("div", { class: "takeaway" }, el("b", { text: "Decision: " }), `the app prices options from the last similar trade. Trades inside packages miss by about ${Math.round(op.packages.vol_bp.surface.median)} bp: their reported premiums are not standalone prices.`));
  const [c8, b8] = card("Do the risk numbers work?", "One-day move of a real trade, unhedged and hedged, as a typical swing in basis points of its size.", "c6");
  const hm = rk.one_day_move_sd_bp_of_notional;
  b8.append(headline(`${rk.risk_removed_pct.bucket_hedge.toFixed(1)}%`, `of next-day risk removed by hedging point by point, on ${num(rk.trades)} real trades`, chip("holds", "good")));
  bars(b8, { cats: ["Unhedged", "Hedged with one swap", "Hedged point by point"], catColors: [cv("--muted"), cv("--muted"), cv("--s1")], series: [{ name: "Typical one-day swing", color: cv("--s1"), values: [hm.unhedged, hm.single_swap_hedge, hm.bucket_hedge] }], yfmt: (x) => x.toFixed(1), valueLabels: true, h: 200 });

  const futRows = [];
  if (fu) {
    const e = fu.engine, m = fu.margin, cents = (x) => (x * 1000 < 0.005 ? "under 1 cent" : `$${(x * 1000).toFixed(2)}`);
    const [cF, bF] = card("Swap futures engine, checked against the exchange", `Every listed contract on ${e.days} days. A price is 100 + value to come + amounts paid − interest on margin.`, "c7 tight");
    bF.append(headline(cents(e.price.max), `worst miss on a $100,000 contract, over ${num(e.contract_days)} contract-days`, chip("matches", "good")),
      more("Each part of the price", table([{ h: "Part of the price", wrap: 1, f: (x) => x[0] }, { h: "Typical", n: 1, f: (x) => x[1] }, { h: "Worst", n: 1, f: (x) => x[2] }],
        [["Value of cash flows to come", cents(e.a.median), cents(e.a.max)], ["Amounts already paid, rebuilt from fixings", cents(e.b.median), cents(e.b.max)], ["One day of interest on margin", cents(e.c_step.median), cents(e.c_step.max)],
         ["Whole price", cents(e.price.median), cents(e.price.max)], ["Risk per basis point", `${e.dv01_pct.median.toFixed(2)}%`, `${e.dv01_pct.p99.toFixed(2)}% (99th)`]], { scroll: false }),
        el("p", { class: "note", text: `Errors are in dollars per contract. ${e.converted_from_libor} contracts that began on LIBOR are left out of the paid-amounts check: their early payments cannot be rebuilt from SOFR fixings.` })));
    const [cG, bG] = card("Margin model", `Fitted to what the exchange charges on ${m.contracts} contracts, then tested on days it had not seen.`, "c5");
    const bt = m.backtest, weak = bt && bt.swap_by_year.slice().sort((x, y) => x.pct - y.pct)[0];
    bG.append(bt ? headline(`${bt.swap_pct.toFixed(1)}%`, `of ${num(bt.days)} later days the swap margin was enough; the standard is ${bt.target_pct.toFixed(0)}%`, chip(bt.swap_pct >= bt.target_pct ? "meets the standard" : "below the standard", bt.swap_pct >= bt.target_pct ? "good" : "warn")) : "",
      kv([["Rule that best fits published futures margins", `${m.best.days}-day move at ${(m.best.confidence * 100).toFixed(0)}%, within ${m.best.typical_miss_pct.toFixed(1)}%`], ...(bt ? [["Futures margin was enough", `${bt.future_pct.toFixed(1)}% of days`], ["Weakest year for swaps", `${weak.year}, ${weak.pct.toFixed(1)}%`]] : []),
        ["Swap margin against futures margin", `${m.swap_to_future.toFixed(1)} times`]]),
      more("Published against model, by contract", table([{ h: "Contract", f: (x) => x.length }, { h: "Published", n: 1, f: (x) => `$${num(x.published_margin)}` }, { h: "Model", n: 1, f: (x) => `$${num(x.model_margin)}` }], m.examples, { scroll: false }),
        el("p", { class: "note", text: `${m.table.length} rules were tried on ${num(m.history_days)} days of curves. Rescaling history to today's volatility, as the clearing house describes, changes the 10-year swap figure by ${m.published_structure.change_pct.toFixed(1)}% and fits published margins no better (${m.published_structure.futures_miss_with_scaling_pct.toFixed(1)}%).` })));
    futRows.push(grid(cF, cG));
    if (fu.options) {
      const op2 = fu.options, [cO, bO] = card("Options against the exchange", `The exchange settles options on its swap futures and publishes a price and a volatility for each: ${op2.days} days, option lives up to ${Math.round(op2.vol.longest_expiry_months)} months.`, "c12");
      bO.append(headline(`${op2.pricer.within_one_tick_pct.toFixed(0)}%`, `of ${num(op2.options)} settled option prices reproduced within one price step`, chip("pricer matches", "good")),
        el("div", { class: "takeaway" }, el("b", { text: "The volatility grid is a guide to the level only: " }), `typically ${op2.vol.typical_miss_bp.toFixed(1)} bp from the exchange, and its day-to-day changes do not follow the exchange's.`),
        more("Grid against exchange, by swap length", table([{ h: "Swap length", f: (x) => x.length }, { h: "Our grid", n: 1, f: (x) => `${x.ours_bp.toFixed(1)} bp` }, { h: "Exchange", n: 1, f: (x) => `${x.exchange_bp.toFixed(1)} bp` }, { h: "Typical gap", lo: 1, n: 1, f: (x) => `${x.typical_miss_bp.toFixed(1)} bp` },
          { h: "Daily changes move together", lo: 1, n: 1, f: (x) => (x.moves_together == null ? "n/a" : lvl(x.moves_together, 2)) }, { h: "", sr: "Reading", f: (x) => (Math.abs(x.moves_together) < 0.3 ? chip("level only", "warn") : chip("tracks", "good")) }], op2.vol.by_length, { scroll: false })));
      futRows.push(grid(cO));
    }
  }
  if (ec && !ec.error) {
    const cv_ = ec.convergence, bpS = (x) => `${(x * 1e4).toFixed(4)} bp`;
    const [cE, bE] = card("Option engines against the closed form", `PDE and Monte Carlo prices of a ${ec.case}, on every day the model was calibrated.`, "c7");
    bE.append(headline(`${ec.pde_vs_exact.max_rel_error_pct}%`, `largest gap between the PDE and the exact price over ${ec.pde_vs_exact.days} real days (typical ${ec.pde_vs_exact.median_rel_error_pct}%)`, chip("agrees", "good")));
    line(bE, { labels: ec.history.map((x) => nice(x.day)), ...monthTicks(ec.history.map((x) => x.day), 6), series: [{ name: "Every reset (PDE)", color: cv("--s1"), values: ec.history.map((x) => x.bermudan_bp) },
      { name: "First date only (exact)", color: cv("--s2"), values: ec.history.map((x) => x.european_bp) }], yfmt: (y) => y.toFixed(0), h: 220 });
    bE.append(el("p", { class: "note", text: "Premium in basis points of size, at the current rate as strike." }),
      more("Convergence", table([{ h: "PDE grid", f: (x) => `${x.grid} × ${x.steps_per_year} a year` }, { h: "Error, bp of size", n: 1, f: (x) => bpS(x.error) }], cv_.pde, { scroll: false }),
        table([{ h: "Monte Carlo paths", f: (x) => num(x.paths) }, { h: "Error, bp of size", n: 1, f: (x) => bpS(x.error) }, { h: "Standard error", n: 1, f: (x) => bpS(x.stderr) }], cv_.mc, { scroll: false }),
        el("p", { class: "note", text: "PDE error falls with the grid; Monte Carlo error stays within about two standard errors, which halve for every fourfold rise in paths." })));
    const [cS, bS] = card("What European prices cannot tell you", `Every row reproduces the same ${ec.swap_vol_bp} bp volatility, and so the same first-date price, with a different pull-back speed.`, "c5");
    const lo_ = Math.min(...ec.by_speed.map((x) => x.bermudan_bp)), hi_ = Math.max(...ec.by_speed.map((x) => x.bermudan_bp));
    bS.append(headline(`${(hi_ / lo_ * 100 - 100).toFixed(0)}%`, "spread in the every-reset price across speeds that fit the European equally well", chip("model risk", "warn")));
    bars(bS, { cats: ec.by_speed.map((x) => `${x.speed}`), catColors: ec.by_speed.map((x) => (x.calibrated ? cv("--s1") : cv("--muted"))), series: [{ name: "Every-reset premium, bp of size", values: ec.by_speed.map((x) => x.bermudan_bp) }], yfmt: (x) => x.toFixed(0), valueLabels: true, h: 200 });
    bS.append(el("div", { class: "takeaway" }, el("b", { text: "Why it matters: " }), "a faster pull-back makes rates on different dates less alike, so the right to choose the date is worth more. Desks set the speed from options on several dates, or from history; the blue bar is the speed fitted here."));
    futRows.push(grid(cE, cS));
  }
  const [c9, b9] = card("Is the code right, and is it fast?", "Checked against an independent closing curve on real days.", "c12");
  if (v.referee) {
    const a = v.referee.swap_rates_off_outside_discount_factors, b = v.referee.our_bootstrap_vs_outside_zero_rates, f = v.performance;
    b9.append(el("div", { class: "kpis" }, kpi("Our pricer on their inputs", `${a.median_bp.toFixed(3)} bp`, `typical gap to their swap rates; worst ${a.max_bp.toFixed(2)} bp`), kpi("Our curve from their rates", `${b.median_bp.toFixed(2)} bp`, `typical gap to theirs; worst ${b.max_bp.toFixed(2)} bp`),
      kpi("Trades through the model", `${num(f.filter_trades_per_second)} a second`, `${num(f.swaps_priced_per_second)} swaps priced a second`), kpi("Risk to every curve point", `${f.risk_by_ad_ms.toFixed(1)} ms`, `by automatic differentiation; ${f.risk_by_bump_ms.toFixed(0)} ms the slow way`)));
  }
  page("Accuracy", "Why the numbers on the other screens can be trusted, and where they cannot.", kp, grid(c0), grid(c1, c2), grid(c3, c4), grid(cB), grid(c5, c6), grid(c7, c8), ...futRows, grid(c9));
}

// ================================================================ Data quality
async function data() {
  const d = await api("/api/quality"), life = d.stats.lifecycle, clean = d.swap_waterfall.at(-1);
  const kp = el("div", { class: "kpis" }, kpi("Daily files", num(d.stats.files), `${nice(d.stats.first_day)} to ${nice(d.stats.last_day)}`), kpi("Reports read", num(life.reports), "every dollar swap and option report"),
    kpi("Real trades", num(life.trades), `${num(life.cancelled)} cancelled, ${num(life.corrected)} amended`), kpi(term("Clean swap prices", "clean"), num(clean.remaining), `${clean.share_of_start.toFixed(1)}% of dollar swaps`));
  const fall = (rows) => { const top = rows[0].remaining; return table([{ h: "Step", wrap: 1, f: (r) => r.step.replace("less: ", "Remove: ") }, { h: "Removed", n: 1, f: (r) => (r.removed == null ? "" : num(r.removed)) }, { h: "Left", n: 1, f: (r) => num(r.remaining) },
    { h: "", lo: 1, f: (r) => { const b = el("div", { class: "fill" }); b.style.width = `${Math.max(2, r.remaining / top * 130)}px`; return b; } }], rows, { scroll: false }); };
  const [c1, b1] = card("Why a swap is not used as a price", "Each trade is counted once, under the first rule it fails, so the column adds up.", "c6"); b1.append(fall(d.swap_waterfall));
  const [c2, b2] = card("Why an option is not used", null, "c6"); b2.append(fall(d.option_waterfall));
  const [c3, b3] = card("Month by month", "A sudden jump in any column means the source changed, not the market. This table once exposed a silent change in the file format.", "c7");
  const monthCols = [{ h: "Month", f: (r) => niceMonth(r.month) }, { h: "Days", lo: 1, n: 1, f: (r) => r.days }, { h: "Swaps", n: 1, f: (r) => num(r.swaps) }, { h: "Clean", n: 1, f: (r) => num(r.clean) }, { h: "In packages", lo: 1, n: 1, f: (r) => `${r.package_pct.toFixed(1)}%` },
    { h: "Amended", lo: 1, n: 1, f: (r) => `${r.corrected_pct.toFixed(1)}%` }, { h: "Options", n: 1, f: (r) => num(r.options) }];
  const recent = d.monthly.slice(-12).reverse(), earlier = d.monthly.slice(0, -12).reverse();
  b3.append(table(monthCols, recent, { scroll: false }), earlier.length ? more(`The ${earlier.length} earlier months`, table(monthCols, earlier, { scroll: false })) : "");
  const [c4, b4] = card("Quiet days, and why", "Weekdays with far fewer trades than usual. Record the reason so nobody has to wonder twice.", "c5 tight");
  const noteCell = (r) => {
    const box = el("span", { class: "row-actions" });
    const show = () => box.replaceChildren(el("span", { class: r.note ? "" : "note", text: r.note?.text || "no note" }),
      el("button", { class: "btn ghost sm", type: "button", "aria-label": `${r.note ? "Edit" : "Add"} note for ${r.day}`, text: r.note ? "Edit" : "Add", onclick: edit }));
    const edit = () => {
      const input = el("input", { value: r.note?.text || "", placeholder: "Reason", "aria-label": `Note for ${r.day}`, style: "flex:1 1 90px;width:90px;min-width:90px" });
      box.replaceChildren(input, el("button", { class: "btn ghost sm", type: "button", text: "Save", onclick: async () => {
        if (!input.value && r.note) { await api(`/api/notes/${r.note.id}`, { method: "DELETE" }); r.note = null; }
        else if (r.note) r.note = await api(`/api/notes/${r.note.id}`, { method: "PUT", body: { day: r.day, text: input.value } });
        else if (input.value) r.note = await api("/api/notes", { method: "POST", body: { day: r.day, text: input.value } });
        show();
      } }));
      input.focus();
    };
    show();
    return box;
  };
  const quiet = d.flagged.slice().reverse();
  b4.append(table([{ h: "Day", f: (r) => nice(r.day) }, { h: "Swaps", n: 1, f: (r) => num(r.swaps) }, { h: "Usual", lo: 1, n: 1, f: (r) => num(r.usual) }, { h: "Note", f: noteCell }], quiet.slice(0, 8), { scroll: false }),
    quiet.length > 8 ? more(`${quiet.length - 8} earlier quiet days`, table([{ h: "Day", f: (r) => nice(r.day) }, { h: "Swaps", n: 1, f: (r) => num(r.swaps) }, { h: "Usual", lo: 1, n: 1, f: (r) => num(r.usual) }, { h: "Note", f: noteCell }], quiet.slice(8), { scroll: false })) : "");
  page("Data quality", "What arrived, what survived cleaning, and why the rest did not.", kp, grid(c1, c2), grid(c3, c4));
}

// ================================================================ Saved trades
async function saved() {
  const items = await api("/api/blotter");
  const describe = (i) => (i.kind === "swap" ? `${i.terms.pay_fixed ? "Pay" : "Receive"} fixed ${i.terms.rate ? `${(+i.terms.rate).toFixed(4)}%` : "at fair"} for ${i.terms.years} years on ${size(i.terms.notional)}`
    : `Right to ${i.terms.payer ? "pay" : "receive"} ${i.terms.strike ? `${(+i.terms.strike).toFixed(4)}%` : "at the money"}, ${i.terms.expiry_years}y option on a ${i.terms.swap_years}y swap, ${size(i.terms.notional)}`);
  const nowCell = (i) => (i.now.error ? el("span", { class: "err", text: i.now.error }) : i.kind === "swap" ? `Fair ${pct(i.now.fair_rate, 4)} · gap ${bp(i.now.gap_bp, 1)} · value ${money(i.now.value, true)}` : `Model premium ${money(i.now.model_premium)}${i.now.vol_gap_bp != null ? ` · volatility gap ${bp(i.now.vol_gap_bp)}` : ""}`);
  const [c, b] = card("Your saved trades", "Kept between sessions. Each one is repriced on the latest day whenever this page opens.", "c12");
  if (!items.length) b.append(el("p", {}, "Nothing saved yet. ", el("a", { href: "#price", text: "Price a trade" }), " and press “Save to Saved trades”."));
  else b.append(table([{ h: "Name", wrap: 1, f: (i) => i.label || "(unnamed)" }, { h: "Trade", wrap: 1, f: describe }, { h: `Now, on ${nice(items[0].now.day || state.day)}`, wrap: 1, f: nowCell },
    { h: "Status", lo: 1, f: (i) => (i._status = el("select", { "aria-label": "Status" }, ["watching", "quoted", "done", "passed"].map((x) => el("option", { value: x, text: x, selected: x === i.status })))) },
    { h: "Note", lo: 1, f: (i) => (i._note = el("input", { value: i.note, "aria-label": "Note", style: "width:200px" })) },
    { h: "", f: (i) => el("span", { class: "row-actions" },
        el("button", { class: "btn ghost sm", type: "button", text: "Update", onclick: async () => { await api(`/api/blotter/${i.id}`, { method: "PUT", body: { kind: i.kind, label: i.label, terms: i.terms, note: i._note.value, status: i._status.value } }); saved(); } }),
        el("button", { class: "btn danger sm", type: "button", text: "Delete", onclick: async () => { await api(`/api/blotter/${i.id}`, { method: "DELETE" }); saved(); } })) }], items));
  page("Saved trades", "Trades you are watching or have quoted, revalued against the latest curve.", grid(c));
}

// ================================================================ Book risk
async function bookrisk() {
  const tier = state.tier1 || "";
  const [r, fb] = await Promise.all([api(`/api/book-risk${tier ? `?tier1=${tier * 1e6}` : ""}`), api("/api/fed-book").catch(() => null)]);
  const bn = (x) => `${x < 0 ? "−" : x > 0 ? "+" : ""}$${(Math.abs(x) / 1e9).toFixed(1)}bn`;
  const fedRows = [];
  if (fb && !fb.error) {
    const [f1, g1] = card("A real book: the Federal Reserve's Treasury portfolio", `Every Treasury bill, note and bond the Fed held on ${nice(fb.holdings_day)} (New York Fed, published weekly), priced on the Fed's fitted Treasury curve of ${nice(fb.curve_day)}. ${num(fb.securities)} securities, ${(fb.par / 1e12).toFixed(2)} trillion dollars of face value.`, "c12");
    g1.append(el("div", { class: "kpis" }, kpi("Value", `$${(fb.value / 1e12).toFixed(2)}tn`, `duration ${fb.duration_years.toFixed(1)} years`), kpi(term("Gain per basis point rise", "perbp"), bn(fb.dv01), "every rate up 1 bp"),
      kpi("1-day VaR, 99%", bn(fb.one_day.var99).replace("+", ""), `full repricing on ${num(fb.one_day.days)} real days since ${nice(fb.from).replace(/^\d+ /, "")}`), kpi("VaR backtest", `${fb.backtest.exceptions} of ${fb.backtest.days}`, `${fb.backtest.zone} zone; about ${fb.backtest.expected} expected`)));
    const worst = fb.irrbb.worst;
    g1.append(headline(bn(worst.delta_eve), `in the worst supervisory shock (${worst.scenario.toLowerCase()})`, chip(fb.backtest.zone === "green" ? "VaR backtest green" : `VaR backtest ${fb.backtest.zone}`, fb.backtest.zone === "green" ? "good" : "warn")));
    bars(g1, { cats: fb.irrbb.rows.map((x) => x.scenario.replace("rates ", "")), series: [{ name: "Change in value", values: fb.irrbb.rows.map((x) => x.delta_eve) }], catColors: fb.irrbb.rows.map((x) => (x.delta_eve < 0 ? cv("--crit") : cv("--good"))), yfmt: (x) => bn(x), valueLabels: true, h: 240 });
    const lo = Object.entries(fb.left_out).map(([k, x]) => `${k === "TIPS" ? "inflation-protected" : "floating-rate"} ${(x / 1e9).toFixed(0)}bn`).join(", ");
    g1.append(more("How this is computed", el("p", { class: "note", text: `Cash flows of each security discounted on the Fed's published zero-coupon curve; each shock and each past day's curve move is a full repricing, run by a C++ kernel (${fb.benchmark.cpp_ms ?? "n/a"} ms for ${num(fb.benchmark.cash_flows)} cash flows × ${num(fb.benchmark.scenarios)} days, against ${fb.benchmark.numpy_ms} ms in NumPy; results identical). Left out: ${lo} of face value. Ten-day VaR ${bn(fb.ten_day.var99).replace("+", "")}. The Fed does not mark its holdings to market or manage them against VaR; this shows what the standard measures say about a real, published portfolio.` })));
    fedRows.push(grid(f1));
  }
  if (!r.trades) {
    const [c, b] = card("Your own trades", "The same measures for the swaps you save on the Saved trades screen.", "c12");
    b.append(el("p", {}, "Nothing saved yet. ", el("a", { href: "#price", text: "Price a trade" }), " and save it to see its regulatory shocks, value at risk and backtest here."));
    page("Book risk", "Regulatory rate shocks, value at risk and its backtest, on real data.", ...fedRows, grid(c));
    return;
  }
  const ir = r.irrbb, v = r.var;
  const kp = el("div", { class: "kpis" },
    kpi(term("Gain per basis point rise", "perbp"), money(r.dv01, true), `${r.trades} swaps, curve of ${nice(r.day)}`),
    v ? kpi("1-day VaR, 99%", money(v.one_day.var99), `loss not exceeded on 99 of 100 days since ${nice(v.from).replace(/^\d+ /, "")}`) : null,
    v ? kpi("Expected shortfall, 97.5%", money(v.one_day.es975), "average loss on the worst 2.5% of days") : null,
    kpi("Worst regulatory shock", money(ir.worst.delta_eve, true), ir.worst.scenario.toLowerCase()));

  const [c1, b1] = card("The six regulatory rate shocks", el("span", {}, `Change in the book's value when the curve moves by Basel's prescribed shocks for US dollars (parallel ${ir.sizes_bp.parallel} bp, short ${ir.sizes_bp.short} bp, long ${ir.sizes_bp.long} bp). Every trade is fully repriced.`), "c7");
  bars(b1, { cats: ir.rows.map((x) => x.scenario.replace("rates ", "")), series: [{ name: "Change in value", values: ir.rows.map((x) => x.delta_eve) }], bySign: false, catColors: ir.rows.map((x) => (x.delta_eve < 0 ? cv("--crit") : cv("--good"))), yfmt: (x) => money(x), valueLabels: true, h: 260 });
  b1.append(more("Shock at each maturity, in basis points", table([{ h: "Scenario", wrap: 1, f: (x) => x.scenario }, ...["1y", "2y", "5y", "10y", "30y"].map((t) => ({ h: t, n: 1, lo: t === "1y" || t === "5y", f: (x) => lvl(x.shift_bp[t], 0) })), { h: "Change in value", n: 1, f: (x) => money(x.delta_eve, true) }], ir.rows, { scroll: false }),
    el("p", { class: "note", text: "Shocks apply to zero rates; after the shock no rate falls below −150 bp at zero maturity, rising 3 bp a year to 0% at 50 years. Sizes from the EBA's supervisory outlier test standard (from BCBS 368, 2016); Basel's 2024 recalibration is not yet applied." })));
  const [c2, b2] = card("Supervisory outlier test", "A bank whose worst shock loses more than 15% of its Tier 1 capital is an outlier and faces supervisory action.", "c5 tight");
  const capital = el("input", { type: "number", id: "tier1", min: 0, step: "any", value: tier, placeholder: "e.g. 500", style: "width:120px" });
  capital.addEventListener("change", () => { state.tier1 = Number(capital.value) || ""; bookrisk(); });
  b2.append(el("div", { class: "filters" }, el("label", { for: "tier1" }, "Tier 1 capital, $m", capital)),
    ir.tier1 ? headline(`${ir.worst_share_of_tier1_pct.toFixed(1)}%`, `of Tier 1 lost in the worst shock (${ir.worst.scenario.toLowerCase()})`, chip(ir.outlier ? "outlier" : "within the 15% limit", ir.outlier ? "crit" : "good"))
      : el("p", { class: "note", text: "Enter capital to run the test." }));

  const rows = [kp, grid(c1, c2)];
  if (v) {
    const [c3, b3] = card("Value at risk from six years of real curve moves", `The book's gain per basis point at each curve point, applied to every daily move in the published swap curve from ${nice(v.from)} to ${nice(v.to)} (${num(v.days)} days).`, "c7");
    const mids = v.histogram.map((_, i) => (v.edges[i] + v.edges[i + 1]) / 2);
    bars(b3, { cats: mids.map((m) => money(m)), series: [{ name: "Days", values: v.histogram }], catColors: mids.map((m) => (m < -v.one_day.var99 ? cv("--crit") : cv("--muted"))), yfmt: (x) => x.toFixed(0), h: 240 });
    b3.append(el("p", { class: "note", text: `Red bars are days worse than the 1-day VaR. Ten-day VaR ${money(v.ten_day.var99)}, expected shortfall ${money(v.ten_day.es975)}. A first-order (delta) measure covering ${v.share_of_dv01_covered_pct}% of the book's risk by curve point; the shocks above are full repricings.` }));
    const bt = v.backtest;
    const [c4, b4] = card("Is the VaR right? The backtest", "Each day VaR is set from the previous 250 days only, then compared with that day's result. Basel's traffic light counts the misses over the last 250 days.", "c5 tight");
    b4.append(headline(`${bt.exceptions} of ${bt.days}`, `days lost more than VaR; about ${bt.expected} expected`, chip(bt.zone, bt.zone === "green" ? "good" : bt.zone === "yellow" ? "warn" : "crit")),
      el("p", { class: "note", text: "Green is 0 to 4 misses, yellow 5 to 9, red 10 or more: the zones banks use for their market risk models." }));
    rows.push(grid(c3, c4));
  }
  const [c5, b5] = card("Where the book's risk sits", "Gain or loss if the rate at one point on the curve rises by a basis point.", "c12");
  bars(b5, { cats: r.by_point.map((x) => yrs(x.length)), series: [{ name: "Per basis point", values: r.by_point.map((x) => x.dv01) }], bySign: true, yfmt: (x) => money(x), h: 200 });
  rows.push(grid(c5));
  if (r.options_skipped) rows.push(el("p", { class: "note", text: `${r.options_skipped} saved swap option${r.options_skipped > 1 ? "s are" : " is"} not included: this screen covers swaps.` }));
  rows.unshift(el("h2", { class: "section", text: "Your own trades" }));
  page("Book risk", "Regulatory rate shocks, value at risk and its backtest, on real data.", ...fedRows, ...rows);
}

// ================================================================ Daily brief (printable)
async function brief_() {
  const [o, s, r, fb] = await Promise.all([q("/api/overview"), api("/api/scorecard"), api("/api/book-risk").catch(() => null), api("/api/fed-book").catch(() => null)]);
  const sw = s.swaps.overall;
  const head = el("div", { class: "brief-head" }, el("div", {}, el("div", { class: "eyebrow", text: "Tapemark · daily rates brief" }), el("h2", { text: `US dollar swaps, ${nice(o.day)}` })),
    el("button", { class: "btn noprint", type: "button", text: "Download as PDF", onclick: () => window.print() }));
  const rates = el("div", { class: "kpis" }, o.key_rates.map((k) => kpi(`${k.length.replace("y", "-year")} swap`, pct(k.rate), delta(k.change_bp))));
  const [c1, b1] = card("The day", null, "c12"); b1.append(brief(o));
  const [c2, b2] = card("Model record", null, "c6");
  b2.append(el("div", { class: "kv" }, [["Typical miss against the next real trade", `${sw.filter.median_bp.toFixed(2)} bp`], ["Last trade of the same length", `${sw.last.median_bp.toFixed(2)} bp`],
    ["Trades inside the normal range", `${(s.swaps.coverage.calibrated * 100).toFixed(1)}% (target 90%)`], ["Trades tested out of sample", num(sw.filter.n)]].flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: b })])));
  const [c3, b3] = card("Your book", null, "c6");
  if (r && r.trades) b3.append(el("div", { class: "kv" }, [["Swaps", r.trades], ["Gain per bp rise", money(r.dv01, true)], ["1-day VaR, 99%", r.var ? money(r.var.one_day.var99) : "n/a"],
    ["Worst regulatory shock", `${money(r.irrbb.worst.delta_eve, true)} (${r.irrbb.worst.scenario.toLowerCase()})`], ["VaR backtest", r.var ? `${r.var.backtest.zone} (${r.var.backtest.exceptions} misses in ${r.var.backtest.days} days)` : "n/a"]].flatMap(([a, b]) => [el("span", { text: a }), el("span", { text: String(b) })])));
  else if (fb && !fb.error) {
    b3.append(el("p", { class: "note", text: `No saved trades. The Federal Reserve's Treasury portfolio (${nice(fb.holdings_day)}):` }),
      el("div", { class: "kv" }, [["Value", `$${(fb.value / 1e12).toFixed(2)}tn`], ["Duration", `${fb.duration_years.toFixed(1)} years`], ["1-day VaR, 99%", `$${(fb.one_day.var99 / 1e9).toFixed(1)}bn`],
        ["Worst regulatory shock", `−$${(Math.abs(fb.irrbb.worst.delta_eve) / 1e9).toFixed(0)}bn (${fb.irrbb.worst.scenario.toLowerCase()})`], ["VaR backtest", `${fb.backtest.zone} (${fb.backtest.exceptions} in ${fb.backtest.days} days)`]].flatMap(([k, v]) => [el("span", { text: k }), el("span", { text: v })])));
  } else b3.append(el("p", { class: "note", text: "No saved trades." }));
  const foot = el("p", { class: "note", text: `Built from public trade reports and published curves as of ${nice(o.day)}. Generated ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC. Not investment advice.` });
  page("Daily brief", "One page with the latest data, ready to print or save as PDF.", el("section", { class: "printable" }, head, rates, grid(c1), grid(c2, c3), foot));
}

// ================================================================ Guide
async function guide() {
  const [c1, b1] = card("How to read this product", null, "c12");
  b1.append(el("div", { class: "steps" },
    el("div", {}, el("h3", { text: "Start with Today" }), el("p", { text: "Three sentences sum up the day. The charts below them show the same story in detail." })),
    el("div", {}, el("h3", { text: "Compare to fair" }), el("p", { text: "Every real trade is shown next to the rate the model expected just before it. The gap is the story." })),
    el("div", {}, el("h3", { text: "Mind the range" }), el("p", { text: "A gap inside the normal range is noise. Outside it is worth a question, not a conclusion." })),
    el("div", {}, el("h3", { text: "Check the proof" }), el("p", { text: "The Accuracy screen shows how often the model was right, and where it was not." }))));
  const [c2, b2] = card("Glossary", "The same definitions appear when you hover any dotted word.", "c12");
  b2.append(el("dl", { class: "defs" }, Object.values(GLOSSARY).flatMap(([t, d]) => [el("div", {}, el("dt", { text: t }), el("dd", { text: d }))])));
  const [c3, b3] = card("What it is not", null, "c12");
  b3.append(el("div", { class: "kv", style: "grid-template-columns:minmax(0,1fr)" }, ["It is not a live quoting system. Public trade reports arrive with a delay, and the live feed is checked every 45 seconds.",
    "It does not know who traded or in which direction. The public record leaves that out.", "It covers US dollar swaps and swap options in depth. Other currencies appear as daily summaries only.",
    "A price far from fair may be right for reasons the record does not show, such as special terms."].map((t) => el("span", { style: "text-align:left;font-weight:400;color:var(--ink2)", text: `• ${t}` }))));
  page("Guide and glossary", "Everything you need to read the screens, in plain words.", grid(c1), grid(c2), grid(c3));
}

// ================================================================ shell
const routes = { overview, guide, today, trades, vol, markets, patterns, price, lab, saved, risk: bookrisk, brief: brief_, accuracy, data };
const TITLES = { overview: "Overview", guide: "Guide and glossary", today: "Market · Today", trades: "Market · Trades", vol: "Market · Volatility", markets: "Market · Other markets", patterns: "Market · Patterns", price: "Tools · Price a trade", lab: "Tools · Model lab", saved: "Tools · Saved trades", risk: "Tools · Book risk", brief: "Tools · Daily brief", accuracy: "Proof · Accuracy", data: "Proof · Data quality" };
async function route() {
  hideTip();
  const name = routes[(location.hash || "#today").slice(1)] ? (location.hash || "#today").slice(1) : "today";
  if (name !== "trades") { state.stream?.close(); state.stream = null; }
  for (const a of document.querySelectorAll("#nav a")) { if (a.getAttribute("href") === `#${name}`) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
  document.getElementById("crumb").textContent = TITLES[name];
  document.querySelector('#nav a[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "center" });
  view.replaceChildren(el("p", { class: "note", text: "Loading…" }));
  try { await routes[name](); } catch (e) { view.replaceChildren(el("p", { class: "err", text: `Could not load this page: ${e.message}` })); }
  scrollTo(0, 0);
}
async function start() {
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* storage unavailable */ }
  state.days = await api("/api/days");
  state.day = state.days.at(-1);
  const sel = document.getElementById("day");
  sel.append(...state.days.slice().reverse().map((d) => el("option", { value: d, text: nice(d) })));
  const pick = (d) => { state.day = d; sel.value = d; route(); };
  sel.addEventListener("change", () => pick(sel.value));
  document.getElementById("prev").addEventListener("click", () => { const i = state.days.indexOf(state.day); if (i > 0) pick(state.days[i - 1]); });
  document.getElementById("next").addEventListener("click", () => { const i = state.days.indexOf(state.day); if (i < state.days.length - 1) pick(state.days[i + 1]); });
  document.getElementById("theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch { /* storage unavailable */ }
    route();
  });
  const dot = document.getElementById("livedot"), text = document.getElementById("livetext");
  const ping = async () => {
    try { const l = await api("/api/live"); dot.className = `live ${l.status.last_error ? "err" : l.status.enabled ? "on" : ""}`; text.textContent = l.status.last_error ? "Closing data · live ticker offline" : l.status.enabled ? "Live" : "Closing data"; if (l.status.last_error) dot.className = "live"; }
    catch { dot.className = "live err"; text.textContent = "Server unreachable"; }
  };
  ping(); setInterval(ping, 30000);
  let timer;
  addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(redrawAll, 150); });
  addEventListener("hashchange", route);
  route();
}
start();
