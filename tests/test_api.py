"""The web service, exercised end to end. Skipped when model results have not been built."""

import pytest

from tapemark.paths import DATA

pytestmark = pytest.mark.skipif(not (DATA / "results" / "swap_summary.json").exists(), reason="run `python -m tapemark score` first")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient

    from tapemark.server import app as service

    service.DB = tmp_path_factory.mktemp("db") / "app.db"  # never touch the real saved items
    service.POLL_SECONDS = 3600
    with TestClient(service.app) as c:
        service.app.state.live.status["enabled"] = False
        yield c


@pytest.mark.parametrize("path", ["/api/health", "/api/days", "/api/overview", "/api/curve", "/api/history", "/api/tape?limit=5", "/api/flow",
                                  "/api/vol", "/api/scorecard", "/api/quality", "/api/markets", "/api/live", "/"])
def test_read_routes_answer(client, path):
    assert client.get(path).status_code == 200


def test_swap_priced_at_fair_is_worth_nothing(client):
    r = client.post("/api/price/swap", json={"years": 10, "notional": 1e8}).json()
    assert r["gap_bp"] == 0 and abs(r["value"]) < 1.0
    assert r["low"] < r["fair_rate"] < r["high"]


def test_paying_above_fair_loses_money_and_receiving_gains(client):
    fair = client.post("/api/price/swap", json={"years": 5}).json()["fair_rate"]
    pay = client.post("/api/price/swap", json={"years": 5, "rate": fair + 0.10, "pay_fixed": True}).json()
    rec = client.post("/api/price/swap", json={"years": 5, "rate": fair + 0.10, "pay_fixed": False}).json()
    assert pay["value"] < 0 < rec["value"]
    assert pay["value"] == pytest.approx(-rec["value"])
    assert pay["dv01"] > 0 > rec["dv01"]


def test_option_premium_round_trips_through_implied_volatility(client):
    base = {"expiry_years": 1, "swap_years": 10, "notional": 1e8, "payer": True}
    model = client.post("/api/price/option", json=base).json()
    again = client.post("/api/price/option", json=base | {"premium": model["model_premium"]}).json()
    assert again["vol_gap_bp"] == pytest.approx(0, abs=0.2)
    assert again["verdict"] == "inside the normal range"


def test_bad_terms_are_rejected(client):
    assert client.post("/api/price/swap", json={"years": "abc"}).status_code == 422


def test_blotter_create_read_update_delete(client):
    terms = {"years": 5, "rate": 4.7, "notional": 5e7, "pay_fixed": True}
    made = client.post("/api/blotter", json={"kind": "swap", "label": "t", "terms": terms})
    assert made.status_code == 201 and "fair_rate" in made.json()["now"]
    i = made.json()["id"]
    assert any(x["id"] == i for x in client.get("/api/blotter").json())
    changed = client.put(f"/api/blotter/{i}", json={"kind": "swap", "label": "t", "terms": terms, "note": "n", "status": "quoted"}).json()
    assert changed["status"] == "quoted" and changed["note"] == "n"
    assert client.delete(f"/api/blotter/{i}").status_code == 204
    assert client.delete(f"/api/blotter/{i}").status_code == 404
    assert client.post("/api/blotter", json={"kind": "bond", "terms": {}}).status_code == 422


def test_notes_create_read_update_delete(client):
    n = client.post("/api/notes", json={"day": "2026-11-11", "text": "holiday"}).json()
    assert client.put(f"/api/notes/{n['id']}", json={"day": "2026-11-11", "text": "Veterans Day"}).json()["text"] == "Veterans Day"
    assert any(x["id"] == n["id"] for x in client.get("/api/notes").json())
    assert client.delete(f"/api/notes/{n['id']}").status_code == 204
    assert client.put(f"/api/notes/{n['id']}", json={"day": "x", "text": "y"}).status_code == 404


def test_margin_comparison_is_consistent(client):
    r = client.post("/api/price/swap", json={"years": 10, "notional": 100_000_000, "pay_fixed": True}).json()
    k = r["clearing"]
    if k is None:
        pytest.skip("run `python -m tapemark score` with network access to build the futures results")
    assert k["contracts"] == 1000
    assert k["future"]["days"] < k["swap"]["days"]
    assert 0 < k["future"]["margin"] < k["swap"]["margin"]                    # a longer close-out needs more margin
    assert "swap_high" not in k                                               # nothing is computed from the exchange's marketing figure
    assert 0 < k["future"]["margin_years"] < k["swap"]["margin_years"]
    assert k["future"]["margin_years"] < 10 * k["future"]["margin"]            # margin shrinks as the trade shortens
    assert abs(k["dv01"] / abs(r["dv01"]) - 1) < 0.02                           # same risk as the pricing engine reports
    forward = client.post("/api/price/swap", json={"years": 10, "start": "2028-06-15", "notional": 100_000_000}).json()
    assert forward["clearing"] is None                                          # only offered for swaps starting now


def test_insights_carry_the_flow_and_futures_studies(client):
    r = client.get("/api/insights").json()
    if r.get("flow"):
        c = r["flow"]["clustering"]
        assert 0 <= c["release"]["branching"] < 1 and len(c["profile"]["minutes"]) == len(c["profile"]["release"])
    if r.get("futures"):
        assert r["futures"]["engine"]["a"]["max"] < 0.01                        # under $10 a contract, far below one price step
