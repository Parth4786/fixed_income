"""One-page data quality report.

Written for a reader with two minutes: what arrived, what survived cleaning
and why the rest did not, whether it agrees with an outside source, and which
days look wrong. Detail lives in the tables; this is the summary.
"""

from __future__ import annotations

import json

import pandas as pd

from tapemark.clean.swaps import SWAP_RULES
from tapemark.clean.swaptions import OPTION_RULES
from tapemark.paths import CLEAN, DATA
from tapemark.sources import eris

REPORTS = DATA / "reports"


def waterfall(df: pd.DataFrame, rules, start_label: str, end_label: str) -> pd.DataFrame:
    """Rows remaining after each exclusion rule, in rule order."""
    counts = df["exclusion"].value_counts()
    remaining = len(df)
    rows = [(start_label, "", remaining)]
    for name, _ in rules:
        removed = int(counts.get(name, 0))
        remaining -= removed
        rows.append((f"less: {name}", removed, remaining))
    rows.append((end_label, "", remaining))
    out = pd.DataFrame(rows, columns=["step", "removed", "remaining"])
    out["share_of_start"] = (out["remaining"] / max(len(df), 1) * 100).round(1)
    return out


def curve_gaps(swaps: pd.DataFrame) -> pd.DataFrame:
    """Daily median traded rate minus the Eris closing par rate, in basis points."""
    std = swaps[swaps["standard"]].copy()
    std["tenor"] = std["tenor_years"].round()
    std = std[(std["tenor_years"] - std["tenor"]).abs() < 0.05]
    med = std.groupby(["trade_date", "tenor"])["fixed_rate_pct"].agg(["median", "count"])
    med = med[med["count"] >= 5]["median"]
    rows = []
    for day in sorted({d for d, _ in med.index}):
        if not eris.raw_path(day.date(), "par").exists():
            continue
        par = eris.par_rates(day.date())
        for tenor in (2, 5, 10, 30):
            sym = f"SOFR{tenor}Y"
            if (day, tenor) in med.index and sym in par.index:
                rows.append((day, tenor, (med[(day, tenor)] - par[sym]) * 100))
    return pd.DataFrame(rows, columns=["day", "tenor", "gap_bp"])


def unusual_days(swaps: pd.DataFrame, window: int = 20, floor: float = 0.3) -> pd.DataFrame:
    """Weekdays whose trade count is far below the recent norm."""
    wk = swaps[swaps["trade_date"].dt.weekday < 5]
    daily = wk.groupby("trade_date").size().rename("swaps").to_frame()
    all_days = pd.bdate_range(daily.index.min(), daily.index.max())
    daily = daily.reindex(all_days, fill_value=0)
    daily["usual"] = daily["swaps"].rolling(window, min_periods=5).median().shift(1)
    flagged = daily[daily["swaps"] < floor * daily["usual"]].copy()
    flagged["pct_of_usual"] = (flagged["swaps"] / flagged["usual"] * 100).round(0)
    return flagged


def _cell(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int) or (hasattr(v, "dtype") and getattr(v.dtype, "kind", "") in "iu"):
        return f"{int(v):,}"
    if isinstance(v, float) or (hasattr(v, "dtype") and getattr(v.dtype, "kind", "") == "f"):
        return "" if pd.isna(v) else (f"{int(v):,}" if float(v).is_integer() and abs(v) >= 100 else f"{v:,.2f}")
    return str(v)


def _md(df: pd.DataFrame) -> str:
    """Markdown table without extra dependencies. Numbers right-aligned."""
    head = "| " + " | ".join(str(c).replace("_", " ") for c in df.columns) + " |"
    align = "|" + "|".join("---:" if df[c].dtype.kind in "iuf" else "---" for c in df.columns) + "|"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in df.itertuples(index=False, name=None)]
    return "\n".join([head, align, *body])


def build_report() -> str:
    swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    opts = pd.read_parquet(CLEAN / "usd_swaptions.parquet")
    stats = json.loads((CLEAN / "build_stats.json").read_text())
    first = pd.Timestamp(stats["first_day"])
    swaps, opts = swaps[swaps["trade_date"] >= first], opts[opts["trade_date"] >= first]
    gaps = curve_gaps(swaps)
    flagged = unusual_days(swaps)
    life = stats["lifecycle"]
    standalone = opts[opts["usable"] & ~opts["package"]]
    days = swaps["trade_date"].nunique()

    lines = [
        "# Data quality report",
        "",
        f"Period: {stats['first_day']} to {stats['last_day']} ({stats['files']} daily files). Generated from public data only.",
        "",
        "## Headline",
        "",
        f"- **{life['reports']:,}** dollar reports became **{life['trades']:,}** real trades after cancellations ({life['cancelled']:,}) and corrections ({life['corrected']:,} trades amended).",
        f"- **{len(swaps):,}** dollar SOFR swaps, of which **{int(swaps['standard'].sum()):,}** ({swaps['standard'].mean() * 100:.0f}%) are plain enough to read as a market price.",
        f"- **{int(opts['usable'].sum()):,}** usable swap options, **{len(standalone):,}** of them standalone (about {len(standalone) / max(days, 1):.0f} a day).",
    ]
    if len(gaps):
        lines.append(
            f"- Clean traded rates sit a median **{gaps['gap_bp'].abs().median():.2f} bp** from an outside closing curve "
            f"({len(gaps):,} comparisons; 95% within {gaps['gap_bp'].abs().quantile(0.95):.1f} bp)."
        )
    lines.append(f"- **{len(flagged)}** weekdays flagged for unusually low volume.")

    lines += ["", "## Why swaps were excluded", "", _md(waterfall(swaps, SWAP_RULES, "all dollar SOFR swaps", "clean swaps"))]
    lines += ["", "## Why options were excluded", "", _md(waterfall(opts, OPTION_RULES, "all dollar European swap options", "usable options"))]

    month = swaps["trade_date"].dt.to_period("M").astype(str)
    by_month = swaps.groupby(month).agg(
        trading_days=("trade_date", "nunique"), swaps=("trade_id", "size"), clean=("standard", "sum"),
        package_pct=("package", lambda s: s.mean() * 100), corrected_pct=("n_corrections", lambda s: (s > 0).mean() * 100),
    )
    use = opts[opts["usable"]]
    by_month["options"] = use.groupby(use["trade_date"].dt.to_period("M").astype(str)).size()
    by_month["options_standalone"] = standalone.groupby(standalone["trade_date"].dt.to_period("M").astype(str)).size()
    if len(gaps):
        g = gaps.groupby(gaps["day"].dt.to_period("M").astype(str))["gap_bp"]
        by_month["curve_gap_bp"] = g.agg(lambda s: s.abs().median())
    by_month = by_month.fillna(0).astype({"clean": int, "options": int, "options_standalone": int})
    lines += ["", "## Month by month", "", _md(by_month.reset_index(names="month"))]

    if len(gaps):
        by_tenor = gaps.groupby("tenor")["gap_bp"].agg(
            comparisons="size", median_gap_bp=lambda s: s.abs().median(), p95_gap_bp=lambda s: s.abs().quantile(0.95),
            bias_bp="median",
        )
        lines += ["", "## Agreement with the outside curve, by swap length", "", _md(by_tenor.reset_index().astype({"tenor": int})),
                  "", "Bias is the signed median: negative means traded rates sat below the closing curve."]

    if len(flagged):
        show = flagged.reset_index(names="day").assign(day=lambda d: d["day"].dt.date)[["day", "swaps", "usual", "pct_of_usual"]]
        lines += ["", "## Days flagged", "", _md(show.tail(25)), "", "Most are US public holidays. Each should be explained before the day is used."]

    if stats.get("missing_columns"):
        lines += ["", "## Schema changes", "", "Columns absent from some files (filled blank):", ""]
        lines += [f"- `{c}`: missing in {n} files" for c, n in sorted(stats["missing_columns"].items(), key=lambda kv: -kv[1])]
    return "\n".join(lines) + "\n"


def write_report() -> str:
    text = build_report()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "data_quality.md").write_text(text, encoding="utf-8")
    return text
