import pandas as pd

from tapemark.clean.swaps import to_number, usd_sofr_swaps


def trade(exec_ts, effective, maturity, **over):
    row = {
        "trade_id": "1",
        "UPI FISN": "NA/Swap OIS USD",
        "UPI Underlier Name": "USD-SOFR-OIS Compound",
        "Execution Timestamp": exec_ts,
        "Effective Date": effective,
        "Expiration Date": maturity,
        "Fixed rate-Leg 1": "0.0467",
        "Fixed rate-Leg 2": "",
        "Notional amount-Leg 1": "100,000,000",
        "Platform identifier": "TWSF",
        "Cleared": "I",
        "Block trade election indicator": "FALSE",
        "Package indicator": "FALSE",
        "Other payment amount": "",
        "Fixed rate day count convention-leg 1": "A004",
        "Fixed rate payment frequency period-Leg 1": "YEAR",
        "n_corrections": 0,
    }
    row.update(over)
    return row


def clean(*rows):
    return usd_sofr_swaps(pd.DataFrame(list(rows)))


def test_notional_parsing_handles_commas_and_caps():
    s = to_number(pd.Series(["220,000,000", "250,000,000+", "", "n/a"]))
    assert s.tolist()[:2] == [220e6, 250e6]
    assert s.isna().tolist() == [False, False, True, True]


def test_thursday_trade_starting_monday_is_spot():
    # 12 Nov 2026 is a Thursday; two business days later is Monday 16 Nov.
    out = clean(trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16"))
    assert out.loc[0, "start"] == "spot"
    assert bool(out.loc[0, "standard"])
    assert round(out.loc[0, "tenor_years"]) == 10
    assert abs(out.loc[0, "fixed_rate_pct"] - 4.67) < 1e-9


def test_forward_and_backdated_starts_are_labelled():
    out = clean(
        trade("2026-11-12T15:00:00Z", "2027-11-05", "2028-11-05", trade_id="f"),
        trade("2026-11-12T15:00:00Z", "2026-06-01", "2031-06-01", trade_id="b"),
    ).set_index("trade_id")
    assert out.loc["f", "start"] == "forward"
    assert out.loc["b", "start"] == "backdated"
    assert not out["standard"].any()


def test_packages_and_side_payments_are_not_standard():
    out = clean(
        trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", trade_id="p", **{"Package indicator": "TRUE"}),
        trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", trade_id="u", **{"Other payment amount": "5000"}),
    )
    assert not out["standard"].any()


def test_capped_notional_is_flagged():
    out = clean(trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Notional amount-Leg 1": "250,000,000+"}))
    assert bool(out.loc[0, "notional_capped"])
    assert out.loc[0, "notional"] == 250e6
