import pandas as pd

from tapemark.clean.lifecycle import apply_lifecycle


def report(id_, action, orig="", event="TRAD", stamp="2026-11-12T10:00:00Z", rate="0.04"):
    return {
        "Dissemination Identifier": id_,
        "Original Dissemination Identifier": orig,
        "Action type": action,
        "Event type": event if action == "NEWT" else "",
        "Event timestamp": stamp,
        "Fixed rate-Leg 1": rate,
    }


def run(rows):
    return apply_lifecycle(pd.DataFrame(rows))


def test_plain_trade_is_kept():
    out = run([report("1", "NEWT")])
    assert out["trade_id"].tolist() == ["1"]
    assert out["n_corrections"].tolist() == [0]


def test_cancelled_trade_is_dropped():
    out = run([report("1", "NEWT"), report("2", "EROR", orig="1")])
    assert out.empty


def test_correction_replaces_values_but_keeps_first_id():
    out = run([report("1", "NEWT", rate="0.04"), report("2", "CORR", orig="1", rate="0.045")])
    assert out["trade_id"].tolist() == ["1"]
    assert out["Fixed rate-Leg 1"].tolist() == ["0.045"]
    assert out["n_corrections"].tolist() == [1]


def test_chain_of_corrections_uses_the_last():
    out = run(
        [
            report("1", "NEWT", rate="0.04"),
            report("2", "CORR", orig="1", rate="0.041", stamp="2026-11-12T11:00:00Z"),
            report("3", "CORR", orig="2", rate="0.042", stamp="2026-11-12T12:00:00Z"),
        ]
    )
    assert out["Fixed rate-Leg 1"].tolist() == ["0.042"]
    assert out["n_corrections"].tolist() == [2]


def test_cancel_after_correction_drops_the_trade():
    out = run([report("1", "NEWT"), report("2", "CORR", orig="1"), report("3", "EROR", orig="2")])
    assert out.empty


def test_post_trade_events_are_not_trades():
    out = run([report("1", "NEWT", event="COMP"), report("2", "NEWT", event="NOVA"), report("3", "MODI", orig="9")])
    assert out.empty
