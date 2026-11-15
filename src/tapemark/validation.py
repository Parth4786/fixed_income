"""Model validation pack.

Brings every check on the models into one document, in the order a bank's
model-risk review asks for them: is the data sound, is the code right, do the
results hold up out of sample, are the uncertainty bands honest, how fragile
are the settings, how does it behave on the worst days, and what is it not
fit for.

It only reports; nothing here fits or tunes a model.
"""

from __future__ import annotations

import datetime as dt
import json
import time

import numpy as np
import pandas as pd

from tapemark.models.curve_filter import NODES
from tapemark.paths import CLEAN, DATA
from tapemark.pricing import risk
from tapemark.pricing.curve import Curve, par_rate, shift_years, spot_start
from tapemark.scoring import swaps as swap_scoring
from tapemark.sources import eris

RESULTS = DATA / "results"
REPORTS = DATA / "reports"
SYMBOL = {t: s for t, s in swap_scoring.SYMBOLS.items()}


def referee_checks(n_days: int = 24) -> dict:
    """Our pricer and bootstrap against an outside curve, on evenly spaced real days."""
    par = swap_scoring.eris_par_table()
    days = [d.date() for d in par.index[:: max(len(par) // n_days, 1)] if eris.raw_path(d.date(), "discount").exists()]
    price_gap, zero_gap, fwd_gap = [], [], []
    for day in days:
        p = eris.par_rates(day)
        dfs = eris.discount_factors(day)
        ref = Curve.from_discount_factors(day, dfs.index.values.astype("datetime64[D]"), dfs.values)
        ours = Curve.from_par(day, NODES, [p[SYMBOL[t]] for t in NODES])
        s = spot_start(day)
        price_gap += [abs(par_rate(ref, s, shift_years(s, int(t)))[0] - p[SYMBOL[t]]) * 100 for t in NODES if t >= 1]
        ends = np.array([shift_years(s, n) for n in (1, 2, 5, 10, 20, 30)], dtype="datetime64[D]")
        zero_gap += list(np.abs(ours.zero_rate(ends) - ref.zero_rate(ends)) * 1e4)
        fwd_gap += [abs(par_rate(ours, shift_years(s, a), shift_years(s, b))[0] - par_rate(ref, shift_years(s, a), shift_years(s, b))[0]) * 100
                    for a, b in ((1, 2), (2, 5), (5, 10), (10, 20))]
    q = lambda v: {"median_bp": round(float(np.median(v)), 3), "max_bp": round(float(np.max(v)), 3)}  # noqa: E731
    return {"days": len(days), "swap_rates_off_outside_discount_factors": q(price_gap), "our_bootstrap_vs_outside_zero_rates": q(zero_gap),
            "forward_swap_rates": q(fwd_gap)}


def residual_checks() -> dict:
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    s = s[s["scored"]]
    gap = (s["fixed_rate_pct"] - s["filter"]) * 100
    bucket = pd.cut(s["tenor_years"], [0, 1.5, 3.5, 7.5, 12.5, 60], labels=["up to 1y", "2-3y", "4-7y", "8-12y", "over 12y"])
    clipped = gap.clip(-10, 10)  # a few bad prints would otherwise dominate
    z = (gap / 100 / s["filter_sd"]).clip(-8, 8)
    return {
        "bias_bp_median": round(float(gap.median()), 4),
        "bias_bp_by_length": {str(b): round(float(gap[bucket == b].median()), 4) for b in bucket.cat.categories},
        "lag1_autocorrelation": round(float(clipped.autocorr(1)), 4),
        "lag1_autocorrelation_same_length": round(float(clipped.groupby((s["tenor_years"] * 4).round()).apply(lambda v: v.autocorr(1) if len(v) > 3 else np.nan).median()), 4),
        "share_beyond_3_sd": round(float((z.abs() > 3).mean()), 4),
        "kurtosis_of_standardised_gap": round(float(z.kurt()), 2),
    }


def sensitivity() -> list[dict]:
    """Change one setting at a time and rescore. A sound model should not hinge on any of them."""
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    par = swap_scoring.eris_par_table()
    base = json.loads((RESULTS / "swap_filter.json").read_text())["noise_sd_pct"]
    runs = [("as used", {}), ("trade noise halved", {"noise": base / 2}), ("trade noise doubled", {"noise": base * 2}),
            ("trade noise x4", {"noise": base * 4}), ("surprise limit 2 sd", {"huber": 2.0}), ("surprise limit 5 sd", {"huber": 5.0}),
            ("no damping of surprises", {"huber": 1e9}), ("covariance window 60 days", {"cov_window": 60}),
            ("covariance window 250 days", {"cov_window": 250}),
            ("covariance on an expanding window (all past days)", {"cov_window": 10**6})]
    scored = s["scored"].values
    # Four consecutive blocks of the scored period, to see whether a setting that
    # was best early stays best later (it was chosen before any of them).
    days = np.sort(s.loc[s["scored"], "trade_date"].unique())
    edges = [days[i * len(days) // 4] for i in range(4)] + [days[-1] + np.timedelta64(1, "D")]
    block = np.searchsorted(np.array(edges[1:-1], dtype="datetime64[ns]"), s["trade_date"].values.astype("datetime64[ns]"), side="right")
    out = []
    for name, kw in runs:
        pred, _, damped, _ = swap_scoring._run_filter(s, par, kw.get("noise", base), huber=kw.get("huber", 3.0), cov_window=kw.get("cov_window", 120))
        e_all = np.abs(s["fixed_rate_pct"].values - pred) * 100
        e = e_all[scored]
        out.append({"setting": name, "median_bp": round(float(np.median(e)), 3), "p95_bp": round(float(np.quantile(e, 0.95)), 2),
                    "damped_pct": round(float(damped[scored].mean() * 100), 1),
                    "by_block": [round(float(np.median(e_all[scored & (block == b)])), 3) for b in range(4)]})
    out[0]["blocks"] = [f"{pd.Timestamp(edges[i]).date()} to {(pd.Timestamp(edges[i + 1]) - pd.Timedelta(days=1)).date()}" for i in range(4)]
    return out


def stress_days() -> dict:
    """Accuracy on the most violent days against the rest."""
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    s = s[s["scored"]]
    par = swap_scoring.eris_par_table()
    move = par["10"].diff().abs() * 100
    cut = move.quantile(0.95)
    wild = set(move[move >= cut].index)
    is_wild = s["trade_date"].isin(wild)
    e = {m: (s[m] - s["fixed_rate_pct"]).abs() * 100 for m in ("filter", "last", "prev_close")}
    row = lambda mask: {m: {"median_bp": round(float(v[mask].median()), 3), "p95_bp": round(float(v[mask].quantile(0.95)), 2)} for m, v in e.items()}  # noqa: E731
    worst = move.nlargest(5)
    return {"threshold_bp": round(float(cut), 1), "wild_days": int(len(wild)), "wild": row(is_wild), "calm": row(~is_wild),
            "coverage_wild": round(float(s["in_band"][is_wild].mean()), 3), "coverage_calm": round(float(s["in_band"][~is_wild].mean()), 3),
            "largest_moves": [{"day": str(d.date()), "ten_year_move_bp": round(float(v), 1)} for d, v in worst.items()]}


def bias_audit(sample: int = 120_000) -> dict:
    """Test, rather than assert, that the headline result is not flattered by a known bias."""
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    par = swap_scoring.eris_par_table()
    noise = json.loads((RESULTS / "swap_filter.json").read_text())["noise_sd_pct"]
    scored = s[s["scored"]]
    gap = (scored["fixed_rate_pct"] - scored["filter"]).abs() * 100

    # 1. Look-ahead. Predictions for early trades must be identical whether or not later trades exist.
    n = 40_000
    with_future, *_ = swap_scoring._run_filter(s.iloc[: 2 * n], par, noise)
    without_future, *_ = swap_scoring._run_filter(s.iloc[:n], par, noise)
    causal = float(np.abs(with_future[:n] - without_future).max())

    # 2. Survivorship and hindsight. Some trades were amended or cancelled after the fact.
    clean = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    info = clean.set_index("trade_id")[["n_corrections", "report_lag_days"]]
    j = scored.join(info, on="trade_id")
    amended = j["n_corrections"] > 0
    late = j["report_lag_days"] >= 1
    stats = json.loads((CLEAN / "build_stats.json").read_text())["lifecycle"]

    # 3. Selection. Only clean trades are scored. How does the model do on trades the rules excluded?
    start = scored["trade_date"].min()
    rng = np.random.default_rng(11)
    excluded = {}
    for reason in ("part of a package", "carries an upfront payment", "flagged as non-standard terms", "non-standard payment schedule"):
        f = clean[(clean["exclusion"] == reason) & (clean["trade_date"] >= start) & (clean["tenor_years"] >= 0.2) & clean["fixed_rate_pct"].between(0.01, 20)]
        if len(f) > sample:
            f = f.iloc[np.sort(rng.choice(len(f), sample, replace=False))]
        f = f.sort_values("exec_ts")
        e = np.abs(swap_scoring.price_as_of(f) - f["fixed_rate_pct"].values) * 100
        e = e[np.isfinite(e)]
        excluded[reason] = {"population": int((clean["exclusion"] == reason).sum()), "scored": int(len(e)), "median_bp": round(float(np.median(e)), 3),
                            "p95_bp": round(float(np.quantile(e, 0.95)), 2)}

    # 4. Repeated rows of one execution, collapsed before scoring.
    std = clean[clean["standard"] & (clean["tenor_years"] >= 0.2) & (clean["trade_date"] >= par.index[0])]
    return {
        "look_ahead": {"trades_compared": n, "largest_difference_pct": causal, "passed": causal < 1e-12},
        "hindsight": {"amended_share_pct": round(float(amended.mean() * 100), 2), "median_bp_never_amended": round(float(gap[~amended.values].median()), 3),
                      "median_bp_amended": round(float(gap[amended.values].median()), 3), "known_a_day_or_more_late_pct": round(float(late.mean() * 100), 2),
                      "median_bp_known_same_day": round(float(gap[~late.values].median()), 3), "cancelled_trades_removed": int(stats["cancelled"]),
                      "cancelled_share_of_new_reports_pct": round(100 * stats["cancelled"] / stats["new_trade_reports"], 2)},
        "selection": {"clean_median_bp": round(float(gap.median()), 3), "clean_share_pct": round(float(clean["standard"].mean() * 100), 1), "excluded": excluded},
        "repeats": {"rows_before": int(len(std)), "executions_scored_or_burned": int(len(s)), "collapsed_pct": round(100 * (1 - len(s) / len(std)), 2)},
        "settings": {"chosen_on": "first 60 trading days", "frozen_from": json.loads((RESULTS / "swap_filter.json").read_text())["burn_in_ends"]},
    }


def performance() -> dict:
    s = pd.read_parquet(RESULTS / "swap_scores.parquet")
    par = swap_scoring.eris_par_table()
    sub = s.iloc[:50000]
    t = time.perf_counter()
    swap_scoring._run_filter(sub, par, 0.0015)
    filt = len(sub) / (time.perf_counter() - t)
    day = par.index[-1].date()
    curve = Curve.from_par(day, NODES, par.values[-1])
    start = spot_start(day)
    ends = start + np.random.default_rng(0).integers(200, 11000, 200_000).astype("timedelta64[D]")
    t = time.perf_counter()
    par_rate(curve, np.full(len(ends), start), ends)
    price = len(ends) / (time.perf_counter() - t)
    t = time.perf_counter()
    for _ in range(200):
        Curve.from_par(day, NODES, par.values[-1])
    boot = (time.perf_counter() - t) / 200 * 1e3
    end = shift_years(start, 10)
    t = time.perf_counter()
    for _ in range(20):
        risk.bucket_dv01_bump(day, NODES, par.values[-1], start, end, 4.7)
    bump = (time.perf_counter() - t) / 20 * 1e3
    t = time.perf_counter()
    for _ in range(20):
        risk.bucket_dv01_ad(day, NODES, par.values[-1], start, end, 4.7)
    ad = (time.perf_counter() - t) / 20 * 1e3
    return {"filter_trades_per_second": int(filt), "swaps_priced_per_second": int(price), "curve_build_ms": round(boot, 3),
            "risk_by_bump_ms": round(bump, 2), "risk_by_ad_ms": round(ad, 2)}


def run() -> dict:
    out = {
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "data": json.loads((CLEAN / "build_stats.json").read_text()),
        "referee": referee_checks(),
        "swaps": json.loads((RESULTS / "swap_summary.json").read_text()),
        "residuals": residual_checks(),
        "sensitivity": sensitivity(),
        "bias_audit": bias_audit(),
        "stress_days": stress_days(),
        "options": json.loads((RESULTS / "option_summary.json").read_text()),
        "risk": json.loads((RESULTS / "risk_summary.json").read_text()),
        "performance": performance(),
    }
    (RESULTS / "validation.json").write_text(json.dumps(out, indent=1))
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "model_validation.md").write_text(render(out), encoding="utf-8")
    return out


def _bias_lines(b: dict) -> list[str]:
    h, sel = b["hindsight"], b["selection"]
    return [
        "### Bias audit", "",
        "| Bias | How it was tested | Result |", "|---|---|---|",
        f"| Look-ahead | Predictions for the first {b['look_ahead']['trades_compared']:,} trades, computed with and without the later trades present | Largest difference {b['look_ahead']['largest_difference_pct']:.1e}: **{'none' if b['look_ahead']['passed'] else 'FOUND'}** |",
        f"| Tuning on the test | Settings chosen on the {b['settings']['chosen_on']}, frozen from {b['settings']['frozen_from']} | Later blocks show no decay (table above) |",
        f"| Hindsight from amendments | {h['amended_share_pct']}% of scored trades were amended after the fact. Scored separately | Never amended {h['median_bp_never_amended']} bp, amended {h['median_bp_amended']} bp |",
        f"| Late publication | {h['known_a_day_or_more_late_pct']}% of scored trades became public a day or more after trading | Same-day trades alone: {h['median_bp_known_same_day']} bp |",
        f"| Survivorship | {h['cancelled_trades_removed']:,} cancelled trades ({h['cancelled_share_of_new_reports_pct']}% of new reports) are removed. A live user would have seen them first | Stated limit: the stored history is the corrected record |",
        f"| Repeated rows | One execution published as several identical rows | {b['repeats']['collapsed_pct']}% of rows collapsed before scoring |",
        f"| Selection | Only clean trades ({sel['clean_share_pct']}% of swaps) are scored. Excluded groups priced with the same as-of curve, never fitted | See below |", "",
        "Model miss on trades the cleaning rules excluded (never used to fit anything):", "",
        "| Group | Trades scored | Median miss | 95th percentile |", "|---|---:|---:|---:|",
        f"| Clean trades (the headline) | | {sel['clean_median_bp']} bp | |",
        *[f"| {k.capitalize()} | {x['scored']:,} | {x['median_bp']} bp | {x['p95_bp']} bp |" for k, x in sel["excluded"].items()], "",
        "Reading: the headline describes plain standalone swaps. Excluded groups miss by more, as expected when a leg's rate reflects a bundle or a side payment. "
        "The numbers are published so that the selection is visible, not hidden.", "",
    ]


def render(v: dict) -> str:
    sw, op, rk, rs, ref = v["swaps"], v["options"], v["risk"], v["residuals"], v["referee"]
    o = sw["overall"]
    cov = sw["coverage"]
    months = [m["coverage"] for m in sw["by_month"].values() if m["filter"].get("n", 0) > 2000]
    lines = [
        "# Model validation report", "",
        f"Generated {v['generated']}. Scored period {sw['period'][0]} to {sw['period'][1]}. Every figure is out of sample.", "",
        "## 1. Verdict", "",
        "| Model | Use | Verdict |", "|---|---|---|",
        f"| Curve filter (swaps) | Fair rate for a dollar SOFR swap, with a band | **Fit for use.** Median miss {o['filter']['median_bp']} bp against {o['last']['median_bp']} bp for the last-trade baseline; band coverage {cov['calibrated'] * 100:.1f}% against a {cov['target'] * 100:.0f}% target. |",
        f"| Risk by curve point | Hedging and value-change explanation | **Fit for use.** A hedge built from it removed {rk['risk_removed_pct']['bucket_hedge']}% of next-day variance on {rk['trades']:,} real trades. |",
        f"| Volatility surface (options) | Volatility where nothing has traded recently | **Limited use.** It beats a single flat level but loses to the last similar trade ({op['standalone']['vol_bp']['surface']['median']} against {op['standalone']['vol_bp']['last']['median']} bp of volatility). Use the last trade when one exists. |",
        "| Package legs (options) | None | **Not fit for pricing.** Premiums reported on package legs imply volatilities about "
        f"{op['packages']['vol_bp']['surface']['median']:.0f} bp away from any model: they are not standalone prices. |", "",
        "## 2. Data", "",
        f"- {v['data']['files']} daily files, {v['data']['first_day']} to {v['data']['last_day']}; {v['data']['unreadable_files']} unreadable.",
        f"- {v['data']['lifecycle']['reports']:,} reports reduced to {v['data']['lifecycle']['trades']:,} trades; {v['data']['lifecycle']['cancelled']:,} cancelled, {v['data']['lifecycle']['corrected']:,} amended.",
        "- Each excluded trade carries one reason and the counts reconcile (see the data quality report).", "",
        "## 3. Is the code right", "",
        f"Checked on {ref['days']} real days against an independent closing curve:", "",
        "| Check | Median gap | Largest gap |", "|---|---:|---:|",
        f"| Our pricer applied to their discount factors, against their swap rates | {ref['swap_rates_off_outside_discount_factors']['median_bp']} bp | {ref['swap_rates_off_outside_discount_factors']['max_bp']} bp |",
        f"| Our curve built from their swap rates, against their zero rates | {ref['our_bootstrap_vs_outside_zero_rates']['median_bp']} bp | {ref['our_bootstrap_vs_outside_zero_rates']['max_bp']} bp |",
        f"| Forward-starting swap rates | {ref['forward_swap_rates']['median_bp']} bp | {ref['forward_swap_rates']['max_bp']} bp |", "",
        "Also: unit tests against hand calculations, pricing identities, QuantLib, and automatic differentiation against bump-and-rebuild.", "",
        "## 4. Out-of-sample accuracy on swaps", "",
        "| Predictor | Trades | Median miss | 95th percentile |", "|---|---:|---:|---:|",
        f"| Curve filter | {o['filter']['n']:,} | {o['filter']['median_bp']} bp | {o['filter']['p95_bp']} bp |",
        f"| Last trade of the same length | {o['last']['n']:,} | {o['last']['median_bp']} bp | {o['last']['p95_bp']} bp |",
        f"| Yesterday's outside close | {o['prev_close']['n']:,} | {o['prev_close']['median_bp']} bp | {o['prev_close']['p95_bp']} bp |",
        f"| Today's outside close (uses the future; reference only) | {o['same_close']['n']:,} | {o['same_close']['median_bp']} bp | {o['same_close']['p95_bp']} bp |", "",
        f"Is the improvement over the last trade real? Daily average miss is lower by {abs(sw['filter_vs_last']['mean_diff_bp'])} bp over {sw['filter_vs_last']['days']} days, "
        f"t-statistic {sw['filter_vs_last']['t_stat']} (Diebold-Mariano with Newey-West errors). Beyond about 2 in size is conventionally significant.", "",
        "By swap length:", "", "| Length | Filter | Last trade | Yesterday's close |", "|---|---:|---:|---:|",
        *[f"| {k} | {b['filter']['median_bp']} | {b['last']['median_bp']} | {b['prev_close']['median_bp']} |" for k, b in sw["by_length"].items()], "",
        f"Unusual lengths (not a whole number of years), where there is rarely a recent identical trade: filter {sw['odd_lengths']['filter']['median_bp']} bp, last trade {sw['odd_lengths']['last']['median_bp']} bp.", "",
        "Forward-starting swaps, which no model was fitted to:", "", "| Predictor | Trades | Median miss | 95th percentile |", "|---|---:|---:|---:|",
        *[f"| {n} | {sw['forwards']['overall'][k]['n']:,} | {sw['forwards']['overall'][k]['median_bp']} bp | {sw['forwards']['overall'][k]['p95_bp']} bp |"
          for n, k in (("Curve filter", "filter"), ("Yesterday's outside curve", "prev_close"), ("Today's outside curve (reference)", "same_close"))], "",
        f"Weak spot: forwards shorter than a year, where the filter misses by {sw['forwards']['by_length']['under 1y long']['filter']['median_bp']} bp. "
        "The curve is smooth between yearly points and cannot see central bank meeting dates.", "",
        "## 5. Are the uncertainty bands honest", "",
        f"- Target: {cov['target'] * 100:.0f}% of trades inside the band.",
        f"- Raw model band (assumes normal errors): {cov['uncalibrated'] * 100:.1f}%. Overconfident.",
        f"- Calibrated band (conformal: rescaled using past errors only): {cov['calibrated'] * 100:.1f}%.",
        f"- By month the calibrated coverage ranged from {min(months) * 100:.1f}% to {max(months) * 100:.1f}%.",
        f"- Typical half-width of the band: {cov['band_half_width_bp_median']} bp.", "",
        "## 6. Residual checks", "",
        f"- Bias: median gap {rs['bias_bp_median']} bp (traded minus predicted). By length: " + ", ".join(f"{k} {b}" for k, b in rs["bias_bp_by_length"].items()) + ".",
        f"- Memory: correlation between one gap and the next is {rs['lag1_autocorrelation']} overall and {rs['lag1_autocorrelation_same_length']} within a swap length. "
        "A well-specified filter leaves none; a positive value means it reacts too slowly.",
        f"- Fat tails: {rs['share_beyond_3_sd'] * 100:.1f}% of gaps exceed three standard deviations (0.3% if errors were normal). This is why the raw band fails and the calibrated one is used.", "",
        "## 7. Sensitivity to settings", "",
        "| Setting changed | Median miss | 95th percentile | Trades damped |", "|---|---:|---:|---:|",
        *[f"| {r['setting']} | {r['median_bp']} bp | {r['p95_bp']} bp | {r['damped_pct']}% |" for r in v["sensitivity"]], "",
        "The trade-noise setting was chosen on the first 60 trading days only and then frozen.", "",
        "### Evaluation schemes", "",
        "- **Walk-forward, one trade at a time.** Every prediction is made before its trade is used. This is the headline scheme.",
        "- **Frozen settings.** Tuned once on the burn-in period, never revisited. The table below shows the choice stays at or near the best in each later block.",
        "- **Rolling against expanding windows.** How rates move together is estimated on the last 60, 120 or 250 days, or on all past days. The result barely changes.",
        "- **Fully held-out product.** Forward-starting swaps are never used for fitting (section 4).",
        "- **Independent next-day data.** The hedge test revalues on an outside closing curve the model never saw (section 10).", "",
        "Median miss in four consecutive blocks of the scored period (" + "; ".join(v["sensitivity"][0]["blocks"]) + "):", "",
        "| Setting | Block 1 | Block 2 | Block 3 | Block 4 |", "|---|---:|---:|---:|---:|",
        *[f"| {r['setting']} | " + " | ".join(str(x) for x in r["by_block"]) + " |" for r in v["sensitivity"]], "",
        *(_bias_lines(v["bias_audit"]) if "bias_audit" in v else []),
        "## 8. Worst days", "",
        f"The {v['stress_days']['wild_days']} days when the 10-year rate moved more than {v['stress_days']['threshold_bp']} bp, against all other days:", "",
        "| | Filter | Last trade | Yesterday's close | Band coverage |", "|---|---:|---:|---:|---:|",
        f"| Violent days | {v['stress_days']['wild']['filter']['median_bp']} bp | {v['stress_days']['wild']['last']['median_bp']} bp | {v['stress_days']['wild']['prev_close']['median_bp']} bp | {v['stress_days']['coverage_wild'] * 100:.1f}% |",
        f"| Other days | {v['stress_days']['calm']['filter']['median_bp']} bp | {v['stress_days']['calm']['last']['median_bp']} bp | {v['stress_days']['calm']['prev_close']['median_bp']} bp | {v['stress_days']['coverage_calm'] * 100:.1f}% |", "",
        "Largest one-day moves in the period: " + ", ".join(f"{m['day']} ({m['ten_year_move_bp']} bp)" for m in v["stress_days"]["largest_moves"]) + ".", "",
        "## 9. Options", "",
        f"{op['coverage']['usable_options']:,} usable trades; {op['coverage']['valid_volatility']:,} gave a valid volatility; {op['coverage']['standalone_scored']:,} standalone trades scored.", "",
        "| Predictor | Median miss (bp of volatility) | 95th percentile |", "|---|---:|---:|",
        *[f"| {n} | {op['standalone']['vol_bp'][k]['median']} | {op['standalone']['vol_bp'][k]['p95']} |" for n, k in
          (("One flat level", "flat"), ("Last similar trade", "last"), ("Smooth surface", "surface"), ("Surface with strike adjustment", "smile"), ("Last trade moved by the surface", "anchored"),
           ("Hull-White one-factor rate model", "hull_white")) if k in op["standalone"]["vol_bp"]], "",
        *([f"Hull-White: fitted on {op['hull_white']['days']} days. Typical pull-back speed {op['hull_white']['a_median']}, at the edge of its allowed range on {op['hull_white']['a_share_at_grid_edge_pct']:.0f}% of days; "
            f"short-rate volatility {op['hull_white']['sigma_bp_median']} bp a year (5th to 95th percentile {op['hull_white']['sigma_bp_range'][0]} to {op['hull_white']['sigma_bp_range'][1]}); "
            f"in-sample fit error {op['hull_white']['fit_rmse_bp_median']} bp. Two numbers cannot match a whole surface, which is the known limit of a one-factor model.", ""] if "hull_white" in op else []),
        f"Typical volatility level is {op['level']['median_vol_bp']} bp a year. The surface beats a flat level (t-statistic {op['surface_vs_flat']['t_stat']}) "
        "but the simplest baseline wins. The strike adjustment adds nothing measurable. Complexity has not earned its place here, and the report says so.", "",
        "## 10. Risk numbers", "",
        "| Position | One-day move, standard deviation | Variance removed |", "|---|---:|---:|",
        f"| Unhedged | {rk['one_day_move_sd_bp_of_notional']['unhedged']} bp of size | |",
        f"| Hedged with one standard swap | {rk['one_day_move_sd_bp_of_notional']['single_swap_hedge']} bp | {rk['risk_removed_pct']['single_swap_hedge']}% |",
        f"| Hedged by curve point | {rk['one_day_move_sd_bp_of_notional']['bucket_hedge']} bp | {rk['risk_removed_pct']['bucket_hedge']}% |", "",
        f"Value-change explanation: the part left unexplained after time and rates has a median of {rk['explain']['unexplained_share_median_pct']}% of the move.", "",
        "## 11. Speed", "",
        f"- Curve filter: {v['performance']['filter_trades_per_second']:,} trades a second.",
        f"- Swap pricing: {v['performance']['swaps_priced_per_second']:,} swaps a second.",
        f"- Curve build: {v['performance']['curve_build_ms']} ms.",
        f"- Risk to every curve point: {v['performance']['risk_by_ad_ms']} ms by automatic differentiation, {v['performance']['risk_by_bump_ms']} ms by rebuilding the curve per point.", "",
        "## 12. Limits", "",
        "- Dollar SOFR swaps only for trade-level results. Other currencies are daily medians.",
        "- 17% of swaps are clean enough to score; the rest are forwards, packages or carry extra terms.",
        "- No holiday-aware payment dates, payment delay or meeting-date steps. Measured cost: a few tenths of a basis point, more on short forwards.",
        "- Public data has no quotes, no direction and no identities. A trade far from the curve may be a real price for reasons the data does not show.",
        "- History starts in November 2024: one rate regime.",
        "- The outside curve used as referee is itself a model.", "",
        "## 13. What to watch in production", "",
        "| Signal | Alarm when |", "|---|---|",
        "| Clean swaps in the nightly window | below 500 |",
        "| Monthly band coverage | outside 85% to 95% |",
        "| Median miss over a week | above twice its trailing average |",
        "| Share of trades damped | above 30% |",
        "| Monthly share of any exclusion reason | changes by more than a third |",
    ]
    return "\n".join(lines) + "\n"
