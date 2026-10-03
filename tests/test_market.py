"""Market tests: uniform-price double-auction correctness."""

import pytest

from helio.market import Ask, Bid, clear_market


def test_basic_clearing_matches_merit_order():
    asks = [Ask("H0", 5.0, 0.10), Ask("H1", 3.0, 0.12)]
    bids = [Bid("H2", 4.0, 0.15), Bid("H3", 4.0, 0.11)]
    r = clear_market(asks, bids)
    # Best bid (0.15, 4 kWh) takes 4 of the cheapest ask (0.10);
    # next bid (0.11) takes the remaining 1 kWh of that ask; the 0.12 ask
    # cannot meet the 0.11 bid, so 3 kWh of asks and 3 kWh of bids stay open.
    assert r.matched_kwh == pytest.approx(5.0)
    assert r.clearing_price == pytest.approx(0.10)  # marginal ask price
    assert r.unmatched_ask_kwh == pytest.approx(3.0)
    assert r.unmatched_bid_kwh == pytest.approx(3.0)
    assert len(r.trades) == 2
    for t in r.trades:
        assert t["price"] == pytest.approx(0.10)  # uniform price


def test_no_match_when_bid_below_ask():
    r = clear_market([Ask("H0", 2.0, 0.12)], [Bid("H1", 2.0, 0.10)])
    assert r.matched_kwh == 0.0
    assert r.clearing_price is None
    assert r.trades == []


def test_partial_fill_splits_across_counterparties():
    asks = [Ask("H0", 1.0, 0.05), Ask("H1", 1.0, 0.06)]
    bids = [Bid("H2", 2.0, 0.20)]
    r = clear_market(asks, bids)
    assert r.matched_kwh == pytest.approx(2.0)
    assert len(r.trades) == 2  # one bid split across two sellers
    assert r.unmatched_bid_kwh == pytest.approx(0.0)


def test_uniform_price_never_violates_reservations():
    asks = [Ask(f"S{i}", 1.0, 0.05 + 0.01 * i) for i in range(5)]
    bids = [Bid(f"B{i}", 1.0, 0.20 - 0.01 * i) for i in range(5)]
    r = clear_market(asks, bids)
    ask_by_seller = {a.seller: a.min_price for a in asks}
    bid_by_buyer = {b.buyer: b.max_price for b in bids}
    for t in r.trades:
        assert t["price"] >= ask_by_seller[t["seller"]] - 1e-9
        assert t["price"] <= bid_by_buyer[t["buyer"]] + 1e-9


def test_empty_books():
    r = clear_market([], [])
    assert r.matched_kwh == 0.0
    assert r.clearing_price is None


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        Ask("H0", -1.0, 0.10)
    with pytest.raises(ValueError):
        Bid("H0", -1.0, 0.10)


def test_inputs_not_mutated():
    asks = [Ask("H0", 2.0, 0.10)]
    bids = [Bid("H1", 1.0, 0.15)]
    clear_market(asks, bids)
    assert asks[0].remaining == pytest.approx(2.0)
    assert bids[0].remaining == pytest.approx(1.0)
