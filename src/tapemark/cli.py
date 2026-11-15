"""Command line: fetch public files, build clean tables, audit coverage.

    python -m tapemark fetch --start 2024-11-09 --end 2026-11-13 --workers 8
    python -m tapemark build
    python -m tapemark summary
    python -m tapemark audit
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from tapemark.clean.lifecycle import apply_lifecycle
from tapemark.clean.swaps import usd_sofr_swaps
from tapemark.clean.swaptions import usd_swaptions
from tapemark.paths import CLEAN, DATA
from tapemark.sources import dtcc, eris

STAGE = DATA / "stage" / "dtcc_usd"  # one small table per day: dollar swaps and options only


def _days(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def _fetch_one(day: dt.date) -> tuple[dt.date, bool, bool, str]:
    try:
        trades = dtcc.fetch(day) is not None  # DTCC publishes on weekends too
        curve = False
        if day.weekday() < 5:
            curve = eris.fetch(day, "discount") is not None
            eris.fetch(day, "par")
        return day, trades, curve, ""
    except Exception as exc:  # keep going; a rerun retries only what is missing
        return day, False, False, repr(exc)[:120]


def cmd_fetch(args) -> None:
    days = list(_days(args.start, args.end))
    got_trades = got_curve = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (day, trades, curve, err) in enumerate(pool.map(_fetch_one, days), 1):
            got_trades += trades
            got_curve += curve
            failed += bool(err)
            if err:
                print(f"{day}  FAILED {err}", flush=True)
            if i % 25 == 0 or i == len(days):
                print(f"{i}/{len(days)} days checked | trade files {got_trades} | curve files {got_curve} | failed {failed}", flush=True)


def _stage(day: dt.date) -> pd.DataFrame:
    """Dollar swaps and options for one day, cached. Unreadable files are skipped and recorded."""
    path = STAGE / f"{day.isoformat()}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df = dtcc.read_usd(day)
    except Exception as exc:  # one bad file must not stop a two-year build
        path.with_suffix(".error.txt").write_text(repr(exc), encoding="utf-8")
        return pd.DataFrame(columns=[*dtcc.COLUMNS, "file_date"])
    if df.attrs.get("missing_columns"):
        path.with_suffix(".missing.json").write_text(json.dumps(df.attrs["missing_columns"]), encoding="utf-8")
    df.to_parquet(path, index=False)
    return df


def cmd_build(args) -> None:
    days = dtcc.available_days()
    if not days:
        raise SystemExit("no raw files yet; run: python -m tapemark fetch --start ... --end ...")
    raw = pd.concat([_stage(d) for d in days], ignore_index=True)
    trades = apply_lifecycle(raw)
    CLEAN.mkdir(parents=True, exist_ok=True)
    swaps, swaptions = usd_sofr_swaps(trades), usd_swaptions(trades)
    swaps.to_parquet(CLEAN / "usd_sofr_swaps.parquet", index=False)
    swaptions.to_parquet(CLEAN / "usd_swaptions.parquet", index=False)
    missing: dict[str, int] = {}
    for f in STAGE.glob("*.missing.json"):
        for col in json.loads(f.read_text()):
            missing[col] = missing.get(col, 0) + 1
    stats = {
        "first_day": days[0].isoformat(), "last_day": days[-1].isoformat(), "files": len(days),
        "unreadable_files": len(list(STAGE.glob("*.error.txt"))),
        "lifecycle": trades.attrs["lifecycle"], "missing_columns": missing,
    }
    (CLEAN / "build_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"days {len(days)} ({days[0]} to {days[-1]}) | dollar reports {len(raw):,} | trades after lifecycle {len(trades):,}")
    print(f"USD SOFR swaps {len(swaps):,} (standard {int(swaps['standard'].sum()):,})")
    print(f"USD swaptions {len(swaptions):,} (usable {int(swaptions['usable'].sum()):,})")


def cmd_summary(args) -> None:
    swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    opts = pd.read_parquet(CLEAN / "usd_swaptions.parquet")
    by_day = swaps.groupby(swaps["trade_date"].dt.date).agg(
        swaps=("trade_id", "size"), standard=("standard", "sum"), packages=("package", "sum")
    )
    by_day["swaptions"] = opts.groupby(opts["trade_date"].dt.date)["usable"].sum()
    print(by_day.tail(15).to_string())
    std = swaps[swaps["standard"]]
    std = std[(std["tenor_years"].round() - std["tenor_years"]).abs() < 0.05]
    last = std[std["trade_date"] == std["trade_date"].max()]
    print("\nmedian traded rate by tenor, latest day:")
    print(last.groupby(last["tenor_years"].round().astype(int))["fixed_rate_pct"].agg(["median", "count"]).query("count >= 5").to_string())


def cmd_audit(args) -> None:
    """Month by month: is there enough usable data, and does it agree with an outside curve?"""
    swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet")
    opts = pd.read_parquet(CLEAN / "usd_swaptions.parquet")
    first = pd.Timestamp(dtcc.available_days()[0])
    swaps, opts = swaps[swaps["trade_date"] >= first], opts[opts["trade_date"] >= first]
    m = swaps["trade_date"].dt.to_period("M")
    table = swaps.groupby(m).agg(
        days=("trade_date", "nunique"), swaps=("trade_id", "size"), standard=("standard", "sum"),
        package_pct=("package", lambda s: round(100 * s.mean())), corrected_pct=("n_corrections", lambda s: round(100 * (s > 0).mean(), 1)),
    )
    use = opts[opts["usable"]]
    om = use["trade_date"].dt.to_period("M")
    table["options_usable"] = use.groupby(om).size()
    table["options_standalone"] = use[~use["package"]].groupby(om).size()

    # Agreement with the Eris closing curve: daily median traded rate against par rate.
    std = swaps[swaps["standard"]].copy()
    std["tenor"] = std["tenor_years"].round()
    std = std[(std["tenor_years"] - std["tenor"]).abs() < 0.05]
    med = std.groupby([std["trade_date"], "tenor"])["fixed_rate_pct"].agg(["median", "count"]).query("count >= 5")["median"]
    rows = []
    for day in sorted({d for d, _ in med.index}):
        if not eris.raw_path(day.date(), "par").exists():
            continue
        par = eris.par_rates(day.date())
        for tenor in (2, 5, 10, 30):
            sym = f"SOFR{tenor}Y"
            if (day, tenor) in med.index and sym in par.index:
                rows.append((day, tenor, (med[(day, tenor)] - par[sym]) * 100))
    gaps = pd.DataFrame(rows, columns=["day", "tenor", "gap_bp"])
    if len(gaps):
        table["curve_gap_bp_median"] = gaps.groupby(gaps["day"].dt.to_period("M"))["gap_bp"].agg(lambda s: round(s.abs().median(), 2))
        table["curve_gap_bp_p95"] = gaps.groupby(gaps["day"].dt.to_period("M"))["gap_bp"].agg(lambda s: round(s.abs().quantile(0.95), 2))
    print(table.to_string())
    if len(gaps):
        print(f"\ncurve agreement overall: {len(gaps):,} comparisons | median gap {gaps['gap_bp'].abs().median():.2f} bp | 95th pct {gaps['gap_bp'].abs().quantile(0.95):.2f} bp")
        print(gaps.groupby("tenor")["gap_bp"].agg(lambda s: round(s.abs().median(), 2)).rename("median gap bp by tenor").to_string())
    CLEAN.mkdir(parents=True, exist_ok=True)
    table.to_csv(CLEAN / "audit_by_month.csv")


def cmd_report(args) -> None:
    from tapemark.report import REPORTS, write_report

    print(write_report())
    print(f"saved to {REPORTS / 'data_quality.md'}")


def cmd_score(args) -> None:
    """Run every model against the clean tables and write results for the app."""
    from tapemark import flow, futures, insights, markets, validation
    from tapemark.scoring import options, risk, swaps
    from tapemark.sources import fed

    steps = [("swap curve filter, walk-forward", swaps.score_spot), ("forward-starting swaps, held out", swaps.score_forwards), ("swap summary", swaps.summarise),
             ("option volatilities", options.implied_vols), ("option predictions, walk-forward", options.score), ("option summary", options.summarise),
             ("hedge test on real trades", risk.hedge_test), ("risk summary", risk.summarise), ("other currencies and inflation", markets.build),
             ("Treasury curve", fed.fetch_treasury_curve), ("TIPS breakevens", fed.fetch_breakevens), ("Fed Treasury holdings", fed.fetch_soma), ("SOFR history", fed.fetch_sofr), ("validation pack", validation.run), ("patterns in the data", insights.run),
             ("order flow: clustering, signed flow, late-day drift", flow.run), ("swap futures against the exchange", futures.run)]
    for name, fn in steps:
        print(f"... {name}", flush=True)
        try:
            fn()
        except Exception as exc:
            if name in ("Treasury curve", "TIPS breakevens", "Fed Treasury holdings", "SOFR history", "swap futures against the exchange"):  # optional outside sources
                print(f"    skipped: {exc!r}"[:160])
            else:
                raise
    print("done. Start the app with: python -m tapemark serve")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("tapemark.server.app:app", host=args.host, port=args.port, reload=False)


def main() -> None:
    p = argparse.ArgumentParser(prog="tapemark")
    sub = p.add_subparsers(required=True)
    f = sub.add_parser("fetch", help="download public trade and curve files")
    f.add_argument("--start", type=dt.date.fromisoformat, required=True)
    f.add_argument("--end", type=dt.date.fromisoformat, required=True)
    f.add_argument("--workers", type=int, default=4)
    f.set_defaults(func=cmd_fetch)
    sub.add_parser("build", help="rebuild clean tables from raw files").set_defaults(func=cmd_build)
    sub.add_parser("summary", help="print what is in the clean tables").set_defaults(func=cmd_summary)
    sub.add_parser("audit", help="month-by-month coverage and agreement with an outside curve").set_defaults(func=cmd_audit)
    sub.add_parser("report", help="write the one-page data quality report").set_defaults(func=cmd_report)
    sub.add_parser("score", help="run all models walk-forward and write results").set_defaults(func=cmd_score)
    sv = sub.add_parser("serve", help="start the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
