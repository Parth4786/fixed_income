"""Every excluded trade gets exactly one reason, and the reasons add up."""

import pandas as pd

from tapemark.clean.swaps import SWAP_RULES, usd_sofr_swaps
from tapemark.clean.swaptions import usd_swaptions
from tapemark.report import unusual_days, waterfall
from test_swaps import trade


def swaps(*rows):
    return usd_sofr_swaps(pd.DataFrame(list(rows)))


def test_clean_trade_has_no_exclusion():
    out = swaps(trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16"))
    assert out.loc[0, "exclusion"] == ""


def test_first_failing_rule_wins():
    # Forward-starting AND in a package: reported once, under the earlier rule.
    out = swaps(trade("2026-11-12T15:00:00Z", "2027-11-05", "2028-11-05", **{"Package indicator": "TRUE"}))
    assert out.loc[0, "exclusion"] == "starts in the future"


def test_each_rule_is_reachable():
    cases = {
        "starts before the trade date": trade("2026-11-12T15:00:00Z", "2026-06-01", "2031-06-01"),
        "starts in the future": trade("2026-11-12T15:00:00Z", "2027-11-05", "2028-11-05"),
        "part of a package": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Package indicator": "TRUE"}),
        "carries an upfront payment": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Other payment amount": "1"}),
        "has an embedded option": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Embedded Option type": "OPET"}),
        "flagged as non-standard terms": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Non-standardized term indicator": "TRUE"}),
        "spread on the floating leg": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Spread-Leg 2": "0.0005"}),
        "non-standard payment schedule": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Fixed rate payment frequency period-Leg 1": "MNTH"}),
        "rate outside 0.01% to 20%": trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Fixed rate-Leg 1": "0.000019"}),
    }
    assert set(cases) == {name for name, _ in SWAP_RULES}
    for expected, row in cases.items():
        assert swaps(row).loc[0, "exclusion"] == expected


def test_waterfall_adds_up():
    out = swaps(
        trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", trade_id="a"),
        trade("2026-11-12T15:00:00Z", "2027-11-05", "2028-11-05", trade_id="b"),
        trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", trade_id="c", **{"Package indicator": "TRUE"}),
    )
    w = waterfall(out, SWAP_RULES, "all", "clean")
    assert w["remaining"].iloc[0] == 3
    assert w["remaining"].iloc[-1] == int(out["standard"].sum()) == 1
    assert w["removed"].replace("", 0).sum() == 2


def test_unparseable_rows_are_dropped_not_crashed():
    out = swaps(trade("not a time", "2026-11-16", "2036-11-16"), trade("2026-11-12T15:00:00Z", "", "2036-11-16"))
    assert out.empty


def option(**over):
    row = {
        "trade_id": "1", "UPI FISN": "NA/O Call Epn OIS USD", "Execution Timestamp": "2026-11-12T22:03:16Z",
        "Expiration Date": "2027-11-12", "Maturity date of the underlier": "2032-11-16", "Strike Price": "0.037",
        "Option Premium Amount": "1,000,000", "Option Premium Currency": "USD", "Notional amount-Leg 1": "200,000,000",
        "Platform identifier": "ISWV", "Package indicator": "FALSE", "n_corrections": 0,
    }
    row.update(over)
    return row


def test_real_option_trade_is_usable_and_measured():
    out = usd_swaptions(pd.DataFrame([option()]))
    assert bool(out.loc[0, "usable"])
    assert round(out.loc[0, "option_years"]) == 1
    assert round(out.loc[0, "swap_years"]) == 5
    assert abs(out.loc[0, "premium_bp_of_notional"] - 50) < 1e-9


def test_option_exclusions():
    out = usd_swaptions(
        pd.DataFrame(
            [
                option(trade_id="zero", **{"Option Premium Amount": "0"}),
                option(trade_id="cap", **{"Notional amount-Leg 1": "250,000,000+"}),
                option(trade_id="eur", **{"Option Premium Currency": "EUR"}),
            ]
        )
    ).set_index("trade_id")
    assert out.loc["zero", "exclusion"] == "no premium reported"
    assert out.loc["cap", "exclusion"] == "size capped in the public record"
    assert out.loc["eur", "exclusion"] == "premium not in dollars"


def test_low_volume_day_is_flagged():
    days = pd.bdate_range("2026-10-01", periods=30)
    counts = [100] * 29 + [5]
    frame = pd.DataFrame({"trade_date": [d for d, n in zip(days, counts, strict=True) for _ in range(n)]})
    flagged = unusual_days(frame)
    assert list(flagged.index) == [days[-1]]


def test_short_swap_with_single_payment_is_standard():
    # Swaps of a year or less pay once, at maturity. That is their normal schedule.
    six_months = trade("2026-11-12T15:00:00Z", "2026-11-16", "2027-05-17", **{"Fixed rate payment frequency period-Leg 1": "EXPI"})
    ten_years = trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Fixed rate payment frequency period-Leg 1": "EXPI"})
    assert swaps(six_months).loc[0, "exclusion"] == ""
    assert swaps(ten_years).loc[0, "exclusion"] == "non-standard payment schedule"


def test_missing_optional_columns_do_not_break_cleaning():
    # Older files lack some columns; the cleaner must treat them as blank.
    row = trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16")
    assert "Embedded Option type" not in row
    assert bool(swaps(row).loc[0, "standard"])


def test_true_false_flags_ignore_letter_case():
    # The source wrote 'true' until 2 Nov 2025 and 'TRUE' afterwards.
    for spelling in ("TRUE", "true", "True", " true "):
        out = swaps(trade("2026-11-12T15:00:00Z", "2026-11-16", "2036-11-16", **{"Package indicator": spelling}))
        assert out.loc[0, "exclusion"] == "part of a package", spelling
    opt = usd_swaptions(pd.DataFrame([option(**{"Package indicator": "true"})]))
    assert bool(opt.loc[0, "package"])
