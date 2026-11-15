"""Read side of the app: loads result tables once and answers questions about them.

Nothing here writes to the data folders. Pricing calls go to the pure
functions in ``tapemark.pricing``; this module only supplies the market state
(the curve as of a day, recent accuracy, recent option trades).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tapemark.clean.swaps import SWAP_RULES
from tapemark.clean.swaptions import OPTION_RULES
from tapemark.models.curve_filter import NODES
from tapemark.paths import CLEAN, DATA
from tapemark.pricing import eris_futures, hullwhite, risk
from tapemark.pricing import options as opt
from tapemark.pricing.calendar import add_business_days
from tapemark.pricing.curve import Curve, annuity_and_float, par_rate, payer_value, shift_months, shift_years, spot_start
from tapemark.report import unusual_days, waterfall
from tapemark.sources import fed

RESULTS = DATA / "results"
NODE_COLS = [str(t) for t in NODES]
LENGTH_EDGES = [0, 1.5, 3.5, 7.5, 12.5, 60]
LENGTH_LABELS = ["up to 1y", "2-3y", "4-7y", "8-12y", "over 12y"]
SIZE_EDGES = [0, 25e6, 100e6, 1e13]
SIZE_LABELS = ["under 25m", "25m to 100m", "over 100m"]


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


class Store:
    def __init__(self):
        self.scores = pd.read_parquet(RESULTS / "swap_scores.parquet")
        self.scores["gap_bp"] = (self.scores["fixed_rate_pct"] - self.scores["filter"]) * 100
        self.snaps = pd.read_parquet(RESULTS / "curve_snapshots.parquet")
        self.snap_ts = self.snaps["ts"].values.astype("datetime64[s]")
        self.snap_x = self.snaps[NODE_COLS].values
        self.days = np.sort(self.scores["trade_date"].unique()).astype("datetime64[D]")
        self.summary = {k: json.loads((RESULTS / f"{k}.json").read_text()) for k in ("swap_summary", "option_summary", "risk_summary")}
        self.futures = json.loads((RESULTS / "futures.json").read_text()) if (RESULTS / "futures.json").exists() else None
        vpath = RESULTS / "validation.json"
        self.validation = json.loads(vpath.read_text()) if vpath.exists() else {}
        self.opts = pd.read_parquet(RESULTS / "option_scores.parquet")
        self.vol_grids = json.loads((RESULTS / "vol_grids.json").read_text())
        self.par = pd.read_parquet(CLEAN / "eris_par.parquet")
        self.swaps = pd.read_parquet(CLEAN / "usd_sofr_swaps.parquet", columns=["trade_date", "exec_ts", "tenor_years", "notional", "start", "package", "exclusion", "standard", "n_corrections"])
        self.options_all = pd.read_parquet(CLEAN / "usd_swaptions.parquet", columns=["trade_date", "exclusion", "usable", "package"])
        self.stats = json.loads((CLEAN / "build_stats.json").read_text())
        self.global_ois = pd.read_parquet(CLEAN / "global_ois_daily.parquet") if (CLEAN / "global_ois_daily.parquet").exists() else pd.DataFrame()
        self.inflation = pd.read_parquet(CLEAN / "usd_inflation_daily.parquet") if (CLEAN / "usd_inflation_daily.parquet").exists() else pd.DataFrame()
        try:
            self.treasury, self.sofr = fed.treasury_curve(), fed.sofr()
        except Exception:  # optional sources; the app runs without them
            self.treasury, self.sofr = pd.DataFrame(), pd.DataFrame()
        # Closing curve per trading day: the state just before the next day's first trade.
        nxt = np.searchsorted(self.snap_ts, (self.days + 1).astype("datetime64[s]"), side="left")
        self.eod = pd.DataFrame(self.snap_x[np.minimum(nxt, len(self.snap_x) - 1)], index=pd.DatetimeIndex(self.days), columns=NODE_COLS)
        self._pca()

    # ---- market state -------------------------------------------------
    def day(self, day: str | None) -> np.datetime64:
        if not day:
            return self.days[-1]
        d = np.datetime64(day, "D")
        return self.days[min(np.searchsorted(self.days, d, side="right") - 1, len(self.days) - 1)] if d >= self.days[0] else self.days[0]

    def state(self, day) -> np.ndarray:
        return self.eod.loc[pd.Timestamp(day)].values

    def prev_day(self, day):
        i = int(np.searchsorted(self.days, day))
        return self.days[i - 1] if i > 0 else None

    def _per_bp(self, notional, tenor, x) -> np.ndarray:
        """Approximate dollars per basis point for a swap of this size and length."""
        y = np.interp(np.clip(tenor, 0.25, 30), NODES, x) / 100
        return np.asarray(notional) * (1 - (1 + y) ** -np.maximum(tenor, 0.08)) / y * 1e-4

    def band_bp(self, day, tenor: float) -> float:
        """Half-width that contained 90% of recent trades of this length (last 20 trading days)."""
        i = int(np.searchsorted(self.days, day))
        s = self.scores[(self.scores["trade_date"] >= pd.Timestamp(self.days[max(i - 20, 0)])) & (self.scores["trade_date"] <= pd.Timestamp(day))]
        lo, hi = (tenor * 0.7, tenor * 1.4) if tenor >= 1 else (0, 1.5)
        near = s[(s["tenor_years"] >= lo) & (s["tenor_years"] <= hi)]
        return float((near if len(near) >= 200 else s)["gap_bp"].abs().quantile(0.9))

    def _pca(self):
        ch = self.eod.diff().dropna().values * 100
        ch = ch[np.abs(ch).max(axis=1) < 60]
        cov = np.cov(ch[-250:], rowvar=False)
        val, vec = np.linalg.eigh(cov)
        order = np.argsort(val)[::-1][:3]
        self.pca_vec = vec[:, order] * np.sign(vec[:, order].sum(axis=0))
        self.pca_share = (val[order] / val.sum()).tolist()

    # ---- pages ---------------------------------------------------------
    def overview(self, day=None) -> dict:
        d = self.day(day)
        p = self.prev_day(d)
        x, x0 = self.state(d), self.state(p) if p is not None else self.state(d)
        at = lambda t, v=x: float(np.interp(t, NODES, v))  # noqa: E731
        key = [{"length": f"{t}y", "rate": _r(at(t)), "change_bp": _r((at(t) - at(t, x0)) * 100, 1)} for t in (2, 5, 10, 30)]
        slopes = [{"name": n, "bp": _r((at(b) - at(a)) * 100, 1), "change_bp": _r(((at(b) - at(a)) - (at(b, x0) - at(a, x0))) * 100, 1)}
                  for n, a, b in (("2y to 10y", 2, 10), ("5y to 30y", 5, 30))]
        ts = pd.Timestamp(d)
        s = self.scores[self.scores["trade_date"] == ts]
        allsw = self.swaps[self.swaps["trade_date"] == ts]
        i = int(np.searchsorted(self.days, d))
        recent = self.scores[(self.scores["trade_date"] > pd.Timestamp(self.days[max(i - 20, 0)])) & (self.scores["trade_date"] <= ts) & self.scores["scored"]]
        move = (x - x0) * 100
        load = self.pca_vec.T @ move
        parts = (self.pca_vec * load).T
        total = float(move @ move) or 1.0
        shape = [{"name": n, "share_pct": _r(100 * float(parts[k] @ parts[k]) / total, 1), "ten_year_bp": _r(parts[k][list(NODES).index(10)], 2)}
                 for k, n in enumerate(("parallel shift", "steeper or flatter", "more or less curved"))]
        grid = self.vol_grids["days"].get(str(d))
        vol = grid["vol"][self.vol_grids["expiry"].index(1)][self.vol_grids["tenor"].index(10)] if grid else None
        sofr = self.sofr[self.sofr["day"] <= ts].tail(1).to_dict("records") if len(self.sofr) else []
        tre = self.treasury[self.treasury.index <= ts].tail(1) if len(self.treasury) else None
        spread = None
        if tre is not None and len(tre) and tre.index[0] in self.eod.index:      # both rates from the same day, or no figure
            spread = _r((float(np.interp(10, NODES, self.eod.loc[tre.index[0]].values)) - float(tre[10].iloc[0])) * 100, 1)
        big = s[~s["damped"] | (s["gap_bp"].abs() < 25)].assign(a=lambda f: f["gap_bp"].abs()).nlargest(8, "a")
        band_each = (s["band_mult"] * s["filter_sd"] * 100).fillna(self.band_bp(d, 10))
        outside = int((s["gap_bp"].abs() > band_each).sum())
        flow_len = pd.cut(allsw["tenor_years"], LENGTH_EDGES, labels=LENGTH_LABELS)
        risk_by_len = pd.Series(self._per_bp(allsw["notional"].values, allsw["tenor_years"].values, x)).groupby(flow_len.values, observed=False).sum()
        return {
            "day": str(d), "previous_day": str(p) if p is not None else None, "key_rates": key, "slopes": slopes,
            "trades": {"clean": int(len(s)), "all_swaps": int(len(allsw)), "notional_bn": _r(allsw["notional"].sum() / 1e9, 1), "outside": outside,
                       "busiest_length": str(risk_by_len.idxmax()) if len(risk_by_len) else None,
                       "busiest_share_pct": _r(100 * risk_by_len.max() / risk_by_len.sum(), 0) if len(risk_by_len) and risk_by_len.sum() else None},
            "model": {"median_miss_bp": _r(recent["gap_bp"].abs().median()), "coverage_pct": _r(recent["in_band"].mean() * 100, 1),
                      "band_bp_10y": _r(self.band_bp(d, 10), 2)},
            "move_shape": shape, "move_bp": [_r(m, 2) for m in move],
            "vol_1y10y_bp": vol, "sofr": sofr[0] | {"day": str(sofr[0]["day"].date())} if sofr else None,
            "swap_spread_10y_bp": spread, "treasury_day": str(tre.index[0].date()) if tre is not None and len(tre) else None,
            "surprises": [{"time": t.exec_ts.strftime("%H:%M:%S"), "length": _r(t.tenor_years, 2), "rate": _r(t.fixed_rate_pct, 4), "fair": _r(t.filter, 4),
                           "gap_bp": _r(t.gap_bp, 2), "notional": float(t.notional), "venue": t.venue,
                           "dollars": _r(float(self._per_bp(t.notional, t.tenor_years, x)) * t.gap_bp, 0)} for t in big.itertuples()],
        }

    def curve(self, day=None) -> dict:
        d = self.day(day)
        p = self.prev_day(d)
        x = self.state(d)
        c = Curve.from_par(d, NODES, x)
        s0 = spot_start(d)
        fwd = [{"starts_in_years": k, "one_year_rate": _r(par_rate(c, shift_years(s0, k), shift_years(s0, k + 1))[0])} for k in (0, 1, 2, 3, 4, 5, 7, 10, 15, 20)]
        ts = pd.Timestamp(d)
        s = self.scores[self.scores["trade_date"] == ts]
        whole = s[(s["tenor_years"] - s["tenor_years"].round()).abs() < 0.05]
        traded = whole.groupby(whole["tenor_years"].round().astype(int))["fixed_rate_pct"].agg(["median", "size", "min", "max"]).reset_index()
        outside = self.par.loc[ts].tolist() if ts in self.par.index else None
        return {"day": str(d), "nodes": NODES.tolist(), "ours": [_r(v, 4) for v in x], "previous": [_r(v, 4) for v in self.state(p)] if p is not None else None,
                "outside": outside, "forwards": fwd,
                "traded": [{"length": int(r.tenor_years), "median": _r(r["median"], 4), "trades": int(r["size"]), "low": _r(r["min"], 4), "high": _r(r["max"], 4)} for _, r in traded.iterrows()]}

    def history(self) -> dict:
        e = self.eod
        at = lambda t: np.array([np.interp(t, NODES, row) for row in e.values])  # noqa: E731
        out = {"days": [str(d.date()) for d in e.index], "rates": {f"{t}y": np.round(at(t), 4).tolist() for t in (2, 5, 10, 30)},
               "slope_2y_10y_bp": np.round((at(10) - at(2)) * 100, 1).tolist()}
        if len(self.treasury):
            tre = self.treasury.reindex(e.index)                                 # no carrying forward: a stale yield against a fresh swap rate is not a spread
            out["swap_spread_bp"] = {f"{t}y": [None if not np.isfinite(v) else round(float(v), 1) for v in (at(t) - tre[t].values) * 100] for t in (2, 5, 10, 30)}
        return out

    def tape(self, day=None, limit: int = 400) -> dict:
        d = self.day(day)
        s = self.scores[self.scores["trade_date"] == pd.Timestamp(d)].sort_values("exec_ts", ascending=False).head(limit)
        band = (s["band_mult"] * s["filter_sd"] * 100).fillna(self.band_bp(d, 10))
        x = self.state(d)
        rows = [{"time": t.exec_ts.strftime("%H:%M:%S"), "length": _r(t.tenor_years, 2), "rate": _r(t.fixed_rate_pct, 4), "fair": _r(t.filter, 4),
                 "gap_bp": _r(t.gap_bp, 2), "band_bp": _r(b, 2), "outside": bool(abs(t.gap_bp) > b), "notional": float(t.notional), "venue": t.venue,
                 "cleared": bool(t.cleared), "dollars": _r(float(self._per_bp(t.notional, t.tenor_years, x)) * t.gap_bp, 0)} for t, b in zip(s.itertuples(), band, strict=True)]
        return {"day": str(d), "rows": rows}

    def flow(self, day=None) -> dict:
        d = self.day(day)
        a = self.swaps[self.swaps["trade_date"] == pd.Timestamp(d)]
        x = self.state(d)
        y = np.interp(a["tenor_years"].clip(0.25, 30), NODES, x) / 100
        dv01 = a["notional"].values * (1 - (1 + y) ** -a["tenor_years"].clip(lower=0.08).values) / y * 1e-4  # annuity approximation
        bucket = pd.cut(a["tenor_years"], LENGTH_EDGES, labels=LENGTH_LABELS)
        by = pd.DataFrame({"bucket": bucket, "dv01": dv01, "kind": np.where(a["standard"], "clean", np.where(a["package"], "package", "other"))})
        tab = by.groupby(["bucket", "kind"], observed=False)["dv01"].agg(["sum", "size"]).reset_index()
        hours = pd.Series(dv01).groupby(a["exec_ts"].dt.hour.values).sum()
        return {"day": str(d), "by_length": [{"length": r.bucket, "kind": r.kind, "dv01_k": _r(r["sum"] / 1e3, 0), "trades": int(r["size"])} for _, r in tab.iterrows()],
                "by_hour_utc": [{"hour": int(h), "dv01_k": _r(v / 1e3, 0)} for h, v in hours.items()]}

    # ---- pricing -------------------------------------------------------
    def price_swap(self, q: dict) -> dict:
        d = self.day(q.get("day"))
        x = self.state(d)
        start = np.datetime64(q["start"], "D") if q.get("start") else spot_start(d)
        if q.get("end"):
            end = np.datetime64(q["end"], "D")
        else:
            years = float(q.get("years") or 10)
            end = shift_years(start, int(years)) if float(years).is_integer() else shift_months(start, int(round(years * 12)))
        tenor = float((end - start).astype(int)) / 365.25
        notional = float(q.get("notional") or 1e8)
        sign = 1.0 if q.get("pay_fixed", True) else -1.0
        c = Curve.from_par(d, NODES, x)
        fair = float(par_rate(c, start, end)[0])
        fixed = float(q["rate"]) if q.get("rate") not in (None, "") else fair
        band = self.band_bp(d, tenor)
        dv = risk.bucket_dv01_ad(d, NODES, x, start, end, fixed, notional) * sign
        value = float(payer_value(c, start, end, fixed, notional)[0]) * sign
        hedges = np.array([2.0, 5.0, 10.0, 30.0])
        s0 = spot_start(d)
        h_rate = np.interp(hedges, NODES, x)
        h_dv = np.array([risk.bucket_dv01_ad(d, NODES, x, s0, shift_years(s0, int(t)), r).sum() for t, r in zip(hedges, h_rate, strict=True)])
        w = risk.hedge_weights(dv, NODES, hedges)
        big = self.eod.diff().dropna()
        worst = big.abs().max(axis=1).nlargest(3).index
        extra = {f"Repeat of {t.date()} (largest real moves)": big.loc[t].values * 100 for t in worst}
        stress = [{"scenario": s["scenario"], "change": s["change"] * sign} for s in risk.stress(d, NODES, x, start, end, fixed, notional, extra)]
        p = self.prev_day(d)
        explain = None
        if p is not None and start > d:
            e = risk.explain(p, self.state(p), d, x, NODES, start, end, fixed, notional)
            explain = {k: e[k] * sign for k in ("total", "time", "rates", "rest")} | {"from": str(p), "to": str(d),
                       "by_point": [{"length": float(t), "value": v * sign} for t, v in zip(NODES, e["by_bucket"], strict=True) if abs(v) > 1e-9]}
        # The same swap under each pricing method, with that method's proven accuracy.
        label = LENGTH_LABELS[min(int(np.digitize(tenor, LENGTH_EDGES[1:-1])), len(LENGTH_LABELS) - 1)]
        miss = self.summary["swap_summary"]["by_length"][label]
        ts = pd.Timestamp(d)
        models = [{"name": "Curve model", "used": True, "rate": _r(fair, 4), "miss_bp": miss["filter"]["median_bp"], "how": "One curve, updated by every trade"}]
        if abs(int((start - spot_start(d)).astype(int))) <= 3:
            near = self.scores[(self.scores["trade_date"] <= ts) & ((self.scores["tenor_years"] - tenor).abs() < 0.13)].tail(1)
            if len(near):
                models.append({"name": "Last trade of this length", "used": False, "rate": _r(float(near["fixed_rate_pct"].iloc[0]), 4), "miss_bp": miss["last"]["median_bp"],
                               "how": f"Traded {near['exec_ts'].iloc[0].strftime('%d %b, %H:%M')} UTC"})
        for name, key, when in (("Today's closing curve (outside provider)", "same_close", d), ("Yesterday's closing curve (outside provider)", "prev_close", p)):
            if when is not None and pd.Timestamp(when) in self.par.index:
                rate = float(par_rate(Curve.from_par(when, NODES, self.par.loc[pd.Timestamp(when)].values), start, end)[0])
                models.append({"name": name, "used": False, "rate": _r(rate, 4), "miss_bp": miss[key]["median_bp"], "how": "Known only after the close" if key == "same_close" else "Stale by a day"})
        for m in models:
            m["your_gap_bp"] = _r((fixed - m["rate"]) * 100, 2)
        size = self.scores[self.scores["scored"]].tail(60000)
        cost = size.groupby(pd.cut(size["notional"], SIZE_EDGES, labels=SIZE_LABELS), observed=False)["gap_bp"].agg(lambda v: v.abs().median())
        return {
            "day": str(d), "start": str(start), "end": str(end), "length_years": _r(tenor, 2), "notional": notional, "pay_fixed": sign > 0,
            "fair_rate": _r(fair, 4), "band_bp": _r(band, 2), "low": _r(fair - band / 100, 4), "high": _r(fair + band / 100, 4),
            "rate": _r(fixed, 4), "gap_bp": _r((fixed - fair) * 100, 2), "verdict": "inside the normal range" if abs(fixed - fair) * 100 <= band else "outside the normal range",
            "value": value, "dv01": float(dv.sum()), "by_point": [{"length": float(t), "dv01": float(v)} for t, v in zip(NODES, dv, strict=True) if abs(v) > 0.5],
            "hedge": [{"length": f"{int(t)}y", "rate": _r(r, 4), "notional": float(-wi / hd), "action": "pay fixed" if -wi / hd > 0 else "receive fixed"}
                      for t, r, wi, hd in zip(hedges, h_rate, w, h_dv, strict=True) if abs(wi / hd) > 0.01 * notional],
            "stress": stress, "explain": explain, "models": models, "length_group": label,
            "typical_gap_by_size_bp": [{"size": str(k), "bp": _r(v, 2)} for k, v in cost.items()],
            "clearing": self._clearing(c, d, tenor, notional) if abs(int((start - spot_start(d)).astype(int))) <= 3 else None,
        }

    def _clearing(self, c: Curve, d, tenor: float, notional: float) -> dict | None:
        """Margin today and discounted margin-years over the life, as a swap future and as a cleared swap."""
        if not self.futures:
            return None
        m = self.futures["margin"]
        nodes, day = np.array(m["nodes"]), np.datetime64(d, "D")

        def at(years):
            return day + np.timedelta64(int(round(years * 365.25)), "D")

        def annuity(years):                                 # value of 1 a year for `years`, paid yearly with a short last piece
            whole = np.arange(1, int(np.floor(years + 1e-9)) + 1)
            out = float(np.sum(c.df(np.array([at(k) for k in whole], dtype="datetime64[D]"))) * 365 / 360) if len(whole) else 0.0
            part = years - len(whole)
            return out + (part * float(c.df(np.array([at(years)]))[0]) if part > 1e-9 else 0.0)

        def discount(years):
            return float(c.df(np.array([at(years)]))[0])

        out = {"confidence": m["best"]["confidence"], "history_from": m["history_from"], "history_days": m["history_days"], "dv01": annuity(tenor) * 1e-4 * notional}
        for name, days, moves in (("future", m["best"]["days"], m["future_move_bp"]), ("swap", m["swap_days"], m["swap_move_bp"])):
            today, years = eris_futures.margin_years(tenor, annuity, lambda t, mv=moves: float(np.interp(t, nodes, mv)), discount)
            out[name] = {"days": days, "margin": today * notional, "margin_years": years * notional}
        out["backtest"] = m.get("backtest")
        out["contracts"] = int(round(notional / eris_futures.CONTRACT))
        return out

    def _vol_for(self, d, t_years: float, swap_years: float) -> dict:
        o = self.opts[(self.opts["trade_date"] <= pd.Timestamp(d)) & ~self.opts["package"]]
        eb = int(np.digitize(t_years, [0.2, 0.75, 1.5, 3.5, 7.5]))
        tb = int(np.digitize(swap_years, [1.5, 3.5, 7.5, 12.5, 25]))
        same = o[o["bucket"] == eb * 10 + tb].tail(1)
        g = self.vol_grids["days"].get(str(d)) or next((self.vol_grids["days"][k] for k in sorted(self.vol_grids["days"], reverse=True) if k <= str(d)), None)
        surface = None
        if g:
            grid = np.array(g["vol"], dtype=float)
            ie = int(np.argmin(np.abs(np.log(self.vol_grids["expiry"]) - np.log(t_years))))
            it = int(np.argmin(np.abs(np.log(self.vol_grids["tenor"]) - np.log(max(swap_years, 0.5)))))
            surface = float(grid[ie, it]) if np.isfinite(grid[ie, it]) else None
        last = None
        if len(same):
            r = same.iloc[0]
            age = int(np.busday_count(r["trade_date"].date(), pd.Timestamp(d).date()))
            last = {"vol_bp": _r(r["vol_bp"], 1), "day": str(r["trade_date"].date()), "age_days": age, "expiry_years": _r(r["option_years"], 2), "swap_years": _r(r["swap_years"], 1)}
        use_last = last is not None and last["age_days"] <= 3
        return {"used_bp": last["vol_bp"] if use_last else (surface if surface is not None else (last or {}).get("vol_bp")),
                "source": "last similar trade" if use_last else "surface", "last": last, "surface_bp": _r(surface, 1)}

    def price_option(self, q: dict) -> dict:
        d = self.day(q.get("day"))
        x = self.state(d)
        c = Curve.from_par(d, NODES, x)
        t_years = float(q.get("expiry_years") or 1)
        expiry = np.datetime64(q["expiry"], "D") if q.get("expiry") else shift_months(d, int(round(t_years * 12)))
        t_years = float((expiry - d).astype(int)) / 365.25
        swap_years = float(q.get("swap_years") or 10)
        start = add_business_days(expiry, 2)
        end = np.datetime64(q["swap_end"], "D") if q.get("swap_end") else shift_years(start, int(round(swap_years)))
        swap_years = float((end - start).astype(int)) / 365.25
        a, fl = annuity_and_float(c, start, end)
        ann, fwd = float(a[0]), float(fl[0] / a[0])
        strike = float(q["strike"]) / 100 if q.get("strike") not in (None, "") else fwd
        payer = bool(q.get("payer", True))
        notional = float(q.get("notional") or 1e8)
        v = self._vol_for(d, t_years, swap_years)
        vol = (v["used_bp"] or 100.0) / 1e4
        price = float(opt.bachelier(fwd, strike, t_years, vol, ann, payer))
        vega_bp = float(opt.vega(fwd, strike, t_years, vol, ann)) * 1e-4
        sd = vol * np.sqrt(t_years)
        d1 = (fwd - strike) / sd
        delta = ann * float(ndtr(d1)) if payer else -ann * float(ndtr(-d1))  # change in value per unit move in the forward rate
        o = self.opts[~self.opts["package"] & self.opts["last"].notna()].tail(5000)
        vol_band = float((o["last"] - o["vol_bp"]).abs().quantile(0.8))
        ov = self.summary["option_summary"]["standalone"]["vol_bp"]
        recent = self.opts[(self.opts["trade_date"] <= pd.Timestamp(d)) & ~self.opts["package"]]
        i = int(np.searchsorted(self.days, d))
        flat = float(recent[recent["trade_date"] > pd.Timestamp(self.days[max(i - 5, 0)])]["vol_bp"].median())
        a_, b_ = self.vol_grids.get("smile", (0.0, 0.0))
        cands = [("Last similar trade", (v["last"] or {}).get("vol_bp"), ov["last"]["median"], v["source"] == "last similar trade"),
                 ("Smooth surface", v["surface_bp"], ov["surface"]["median"], v["source"] == "surface"),
                 ("One flat level for the whole market", flat if np.isfinite(flat) else None, ov["flat"]["median"], False)]
        if v["surface_bp"]:
            z = (strike - fwd) / (v["surface_bp"] / 1e4 * np.sqrt(t_years))
            cands.insert(2, ("Surface with strike adjustment", v["surface_bp"] * (1 + a_ * z + b_ * z * z), ov["smile"]["median"], False))
        hw = self.vol_grids.get("hull_white", {})
        hw_day = next((k for k in sorted(hw, reverse=True) if k <= str(d)), None)
        if hw_day and "hull_white" in ov:
            speed, sig, _ = hw[hw_day]
            cands.append((f"Hull-White rate model (pull-back {speed}, short-rate volatility {sig * 1e4:.0f} bp)",
                          float(hullwhite.normal_vol_factor(c, expiry, start, end, speed)[0]) * sig * 1e4, ov["hull_white"]["median"], False))
        models = [{"name": n, "used": bool(u), "vol_bp": _r(x, 1), "miss_bp": m, "premium": float(opt.bachelier(fwd, strike, t_years, x / 1e4, ann, payer)) * notional}
                  for n, x, m, u in cands if x is not None and np.isfinite(x) and x > 0]
        out = {"models": models, "day": str(d), "expiry": str(expiry), "swap_start": str(start), "swap_end": str(end), "expiry_years": _r(t_years, 2), "swap_years": _r(swap_years, 1),
               "forward_rate": _r(fwd * 100, 4), "strike": _r(strike * 100, 4), "payer": payer, "notional": notional, "annuity": _r(ann, 4),
               "vol": v, "model_premium": price * notional, "model_premium_bp": _r(price * 1e4, 1), "vol_band_bp": _r(vol_band, 1),
               "premium_low": float(opt.bachelier(fwd, strike, t_years, max(vol - vol_band / 1e4, 1e-5), ann, payer)) * notional,
               "premium_high": float(opt.bachelier(fwd, strike, t_years, vol + vol_band / 1e4, ann, payer)) * notional,
               "rate_risk_per_bp": delta * notional * 1e-4, "vol_risk_per_bp": vega_bp * notional}
        if q.get("premium") not in (None, ""):
            paid = float(q["premium"])
            iv = float(opt.implied_vol(paid / notional, fwd, strike, t_years, ann, payer))
            out |= {"premium_paid": paid, "implied_vol_bp": _r(iv * 1e4, 1), "vol_gap_bp": _r((iv - vol) * 1e4, 1), "premium_gap": paid - price * notional,
                    "verdict": "no volatility reproduces this premium" if not np.isfinite(iv) else
                    ("inside the normal range" if abs(iv - vol) * 1e4 <= vol_band else "outside the normal range")}
        return out

    def vol(self, day=None) -> dict:
        d = self.day(day)
        g = self.vol_grids["days"].get(str(d))
        i = int(np.searchsorted(self.days, d))
        o = self.opts[(self.opts["trade_date"] > pd.Timestamp(self.days[max(i - 5, 0)])) & (self.opts["trade_date"] <= pd.Timestamp(d)) & ~self.opts["package"]]
        pts = [{"day": str(r.trade_date.date()), "expiry_years": _r(r.option_years, 2), "swap_years": _r(r.swap_years, 1), "vol_bp": _r(r.vol_bp, 1),
                "strike_gap_bp": _r(r.moneyness_bp, 0), "premium_bp": _r(r.premium_bp_of_notional, 1), "notional": float(r.notional), "payer": bool(r.payer)} for r in o.itertuples()]
        days = sorted(self.vol_grids["days"])
        ie, it = self.vol_grids["expiry"].index(1), self.vol_grids["tenor"].index(10)
        series = [{"day": k, "vol_bp": self.vol_grids["days"][k]["vol"][ie][it]} for k in days]
        return {"day": str(d), "expiry": self.vol_grids["expiry"], "tenor": self.vol_grids["tenor"], "grid": g["vol"] if g else None, "support": g["support"] if g else None,
                "trades": pts, "history_1y10y": series}

    # ---- lab -------------------------------------------------------------
    def lab(self, q: dict) -> dict:
        """Rerun the curve model on recent real trades with the caller's settings."""
        from tapemark.scoring.swaps import _run_filter

        days = int(min(max(q.get("days") or 20, 5), 120))
        warm = 5  # extra days to settle the model; never scored
        first = self.days[max(len(self.days) - days - warm, 0)]
        score_from = pd.Timestamp(self.days[max(len(self.days) - days, 0)])
        s = self.scores[self.scores["trade_date"] >= pd.Timestamp(first)].sort_values("exec_ts")
        default = self.summary["swap_summary"]["filter_settings"]["noise_sd_pct"]
        mine = {"noise": float(q.get("noise_bp") or default * 100) / 100, "huber": float(q.get("surprise_limit") or 3.0), "cov_window": int(q.get("history_days") or 120)}
        keep = (s["trade_date"] >= score_from).values
        day = s["trade_date"].values[keep]

        cache = self.__dict__.setdefault("_lab_runs", {})     # a run depends only on its settings and the window

        def run(noise, huber, cov_window):
            key = (days, round(noise, 6), round(huber, 3), cov_window)
            if key not in cache:
                cache[key] = one(noise, huber, cov_window)
                while len(cache) > 24:                           # keep the most recent; the published run is re-added on demand
                    cache.pop(next(iter(cache)))
            return cache[key]

        def one(noise, huber, cov_window):
            pred, sd, damped, _ = _run_filter(s, self.par, noise, huber=huber, cov_window=cov_window)
            e = (np.abs(s["fixed_rate_pct"].values - pred) * 100)[keep]
            z = e / 100 / sd[keep]
            daily = pd.Series(e).groupby(day).median()
            return {"median_bp": _r(np.median(e)), "p95_bp": _r(np.quantile(e, 0.95), 2), "damped_pct": _r(damped[keep].mean() * 100, 1),
                    "inside_raw_band_pct": _r((z <= 1.645).mean() * 100, 1)}, daily

        yours, d1 = run(**mine)
        frozen, d0 = run(default, 3.0, 120)
        last = (s["last"] - s["fixed_rate_pct"]).abs().values[keep] * 100
        return {"window": {"from": str(score_from.date()), "to": str(self.days[-1]), "trades": int(keep.sum()), "days": days},
                "settings": {"noise_bp": mine["noise"] * 100, "surprise_limit": mine["huber"], "history_days": mine["cov_window"]},
                "frozen_settings": {"noise_bp": default * 100, "surprise_limit": 3.0, "history_days": 120},
                "yours": yours, "frozen": frozen, "last_trade": {"median_bp": _r(np.nanmedian(last))},
                "daily": {"days": [str(pd.Timestamp(x).date()) for x in d0.index], "yours": [round(float(v), 3) for v in d1.values], "frozen": [round(float(v), 3) for v in d0.values],
                          "trades": [int(n) for n in pd.Series(day).groupby(day).size().reindex(d0.index).values]}}

    # ---- evidence ------------------------------------------------------
    def scorecard(self) -> dict:
        return {"swaps": self.summary["swap_summary"], "options": self.summary["option_summary"], "risk": self.summary["risk_summary"],
                "validation": {k: self.validation.get(k) for k in ("referee", "residuals", "sensitivity", "stress_days", "performance", "generated", "bias_audit")}}

    def quality(self) -> dict:
        """The cleaning audit. Built once and kept: the tables behind it only change when the store is reloaded."""
        if getattr(self, "_quality", None) is None:
            self._quality = self._build_quality()
        return self._quality

    def _build_quality(self) -> dict:
        first = pd.Timestamp(self.stats["first_day"])
        sw = self.swaps[self.swaps["trade_date"] >= first]
        op = self.options_all[self.options_all["trade_date"] >= first]
        month = sw["trade_date"].dt.to_period("M").astype(str)
        by = sw.groupby(month).agg(days=("trade_date", "nunique"), swaps=("standard", "size"), clean=("standard", "sum"),
                                   package_pct=("package", lambda s: round(100 * s.mean(), 1)), corrected_pct=("n_corrections", lambda s: round(100 * (s > 0).mean(), 1)))
        use = op[op["usable"]]
        by["options"] = use.groupby(use["trade_date"].dt.to_period("M").astype(str)).size()
        flagged = unusual_days(sw).reset_index(names="day")
        return {"stats": self.stats, "swap_waterfall": waterfall(sw, SWAP_RULES, "all dollar swaps", "clean swaps").replace("", None).to_dict("records"),
                "option_waterfall": waterfall(op, OPTION_RULES, "all dollar swap options", "usable options").replace("", None).to_dict("records"),
                "monthly": by.fillna(0).astype({"clean": int, "options": int}).reset_index(names="month").to_dict("records"),
                "flagged": [{"day": str(r.day.date()), "swaps": int(r.swaps), "usual": _r(r.usual, 0)} for r in flagged.itertuples()]}

    def _inflation_basis(self) -> dict | None:
        """Inflation swap rate minus TIPS breakeven, same day and maturity, in basis points.

        Both are zero-coupon and annually compounded. Only days with at least
        three swap trades at that maturity are used, and the TIPS curve is
        never carried forward, so the two rates always share a date.
        """
        try:
            be = fed.breakevens()
        except Exception:  # noqa: BLE001 - the file is optional
            return None
        f = self.inflation[self.inflation["trades"] >= 3]
        out = {}
        for t in (5, 10):
            sw = f[f["tenor"] == t].set_index("day")["rate"]
            both = pd.DataFrame({"swap": sw, "bond": be[t].reindex(sw.index)}).dropna()
            if len(both) < 20:
                continue
            gap = (both["swap"] - both["bond"]) * 100
            out[f"{t}y"] = {"days": [str(d.date()) for d in both.index], "swap": both["swap"].round(3).tolist(), "bond": both["bond"].round(3).tolist(),
                            "basis_bp": gap.round(1).tolist(), "median_bp": _r(float(gap.median()), 1), "last_bp": _r(float(gap.iloc[-1]), 1), "last_day": str(both.index[-1].date()), "days_used": int(len(both))}
        return out or None

    def markets(self) -> dict:
        out = {"pca": {"nodes": NODES.tolist(), "shapes": self.pca_vec.T.round(3).tolist(), "share": [round(s, 3) for s in self.pca_share]}}
        if len(self.global_ois):
            g = self.global_ois
            last = g["day"].max()
            recent = g[g["day"] >= last - pd.Timedelta(days=4)]
            cur = recent.sort_values("day").groupby(["ccy", "tenor"]).tail(1)
            out["curves"] = {c: [{"length": int(r.tenor), "rate": _r(r.rate, 3), "trades": int(r.trades)} for r in grp.sort_values("tenor").itertuples()] for c, grp in cur.groupby("ccy")}
            ten = g[g["tenor"] == 10].pivot_table(index="day", columns="ccy", values="rate").sort_index()
            out["ten_year"] = {"days": [str(d.date()) for d in ten.index], **{c: [None if not np.isfinite(v) else round(float(v), 3) for v in ten[c].values] for c in ten.columns}}
            usd10 = np.array([np.interp(10, NODES, r) for r in self.eod.values])
            out["ten_year"]["USD"] = pd.Series(usd10, index=self.eod.index).reindex(ten.index).round(3).where(lambda s: s.notna(), None).tolist()
        if len(self.inflation):
            f = self.inflation
            last = f["day"].max()
            out["inflation_curve"] = [{"length": int(r.tenor), "rate": _r(r.rate, 3), "trades": int(r.trades)} for r in f[f["day"] == last].sort_values("tenor").itertuples()]
            t10 = f[f["tenor"] == 10].set_index("day")["rate"].sort_index()
            out["inflation_10y"] = {"days": [str(d.date()) for d in t10.index], "rate": t10.round(3).tolist()}
            out["inflation_day"] = str(last.date())
            out["inflation_basis"] = self._inflation_basis()
        if len(self.sofr):
            s = self.sofr.tail(520)
            out["funding"] = {"days": [str(d.date()) for d in s["day"]], "rate": s["rate"].tolist(), "spread_bp": ((s["p99"] - s["p1"]) * 100).round(1).tolist(),
                              "volume_bn": s["volume_bn"].tolist()}
        return out
