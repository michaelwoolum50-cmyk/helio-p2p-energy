"""Uniform-price double-auction market for peer-to-peer energy trading.

Each interval, surplus households submit ASKS (kWh offered, minimum acceptable
price) and deficit households submit BIDS (kWh wanted, maximum acceptable
price). The auctioneer:

  1. sorts asks ascending by price (cheapest first — merit order),
  2. sorts bids descending by price (highest willingness first),
  3. walks both books, matching while the best bid >= the best ask,
  4. clears every matched kWh at ONE uniform price: the marginal ask price
     (the ask price of the last unit matched), the standard uniform-price
     auction rule.

Partial fills are allowed (an order can be split across counterparties).
Unmatched quantities simply do not trade — in the simulation the grid
absorbs the residual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class Ask:
    seller: str
    kwh: float
    min_price: float          # $/kWh — will not sell below this
    remaining: float = field(init=False)

    def __post_init__(self) -> None:
        if self.kwh < 0:
            raise ValueError("ask kwh must be >= 0")
        self.remaining = self.kwh


@dataclass
class Bid:
    buyer: str
    kwh: float
    max_price: float           # $/kWh — will not pay above this
    remaining: float = field(init=False)

    def __post_init__(self) -> None:
        if self.kwh < 0:
            raise ValueError("bid kwh must be >= 0")
        self.remaining = self.kwh


@dataclass
class ClearingResult:
    clearing_price: float | None   # $/kWh; None when nothing matched
    matched_kwh: float
    trades: List[Dict[str, Any]]   # each: buyer, seller, kwh, price
    unmatched_ask_kwh: float
    unmatched_bid_kwh: float


def clear_market(asks: List[Ask], bids: List[Bid]) -> ClearingResult:
    """Run one uniform-price double auction.

    Returns the clearing price and the list of matched trades. All trades
    clear at the same price (the marginal ask price).
    """
    # Work on copies so callers' objects keep their original quantities.
    asks = sorted((Ask(a.seller, a.kwh, a.min_price) for a in asks),
                  key=lambda a: a.min_price)
    bids = sorted((Bid(b.buyer, b.kwh, b.max_price) for b in bids),
                  key=lambda b: b.max_price, reverse=True)

    matches: List[tuple] = []  # (bid, ask, kwh)
    i = j = 0
    while i < len(asks) and j < len(bids):
        ask, bid = asks[i], bids[j]
        if bid.max_price < ask.min_price:
            break  # best remaining bid cannot meet best remaining ask
        qty = min(ask.remaining, bid.remaining)
        if qty <= 1e-12:
            if ask.remaining <= 1e-12:
                i += 1
            if bid.remaining <= 1e-12:
                j += 1
            continue
        matches.append((bid, ask, qty))
        ask.remaining -= qty
        bid.remaining -= qty
        if ask.remaining <= 1e-12:
            i += 1
        if bid.remaining <= 1e-12:
            j += 1

    if not matches:
        return ClearingResult(
            clearing_price=None,
            matched_kwh=0.0,
            trades=[],
            unmatched_ask_kwh=sum(a.kwh for a in asks),
            unmatched_bid_kwh=sum(b.kwh for b in bids),
        )

    # Uniform price = marginal ask price (ask of the last matched unit).
    clearing_price = matches[-1][1].min_price
    trades = [
        {"buyer": bid.buyer, "seller": ask.seller,
         "kwh": round(qty, 6), "price": round(clearing_price, 6)}
        for bid, ask, qty in matches
    ]
    return ClearingResult(
        clearing_price=round(clearing_price, 6),
        matched_kwh=round(sum(q for _, _, q in matches), 6),
        trades=trades,
        unmatched_ask_kwh=round(sum(a.remaining for a in asks), 6),
        unmatched_bid_kwh=round(sum(b.remaining for b in bids), 6),
    )
