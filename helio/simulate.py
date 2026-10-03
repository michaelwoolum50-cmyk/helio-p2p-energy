"""Microgrid simulation CLI.

Usage:
    python -m helio.simulate --households 6 --days 2 --seed 42

Each interval (default: 1 hour):
  1. every agent forecasts surplus/deficit and submits an ask or bid,
  2. the double auction clears at a uniform price,
  3. matched trades are sealed into the hash-chained ledger,
  4. unmatched surplus is exported to the grid, unmatched deficit is
     imported from the grid.

At the end it prints clearing prices per interval, totals (P2P kWh vs grid
kWh), the self-consumption share, money saved vs buying everything from the
grid, and the ledger verification result. Full detail is written to
results.json.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, List

from .agent import HouseholdAgent
from .forecast import make_profiles, forecast
from .ledger import Ledger
from .market import Ask, Bid, clear_market


def run_simulation(households: int = 6, days: int = 2, seed: int = 42,
                   interval_hours: float = 1.0,
                   grid_import_price: float = 0.16,
                   grid_export_price: float = 0.04,
                   day_of_year: int = 280) -> Dict[str, Any]:
    """Run the microgrid simulation; return the results dict."""
    profiles = make_profiles(households, seed)
    agents = [
        HouseholdAgent(
            profile=p,
            forecast=forecast(p, day_of_year, days, interval_hours,
                              seed=seed * 1000 + idx),
            grid_import_price=grid_import_price,
            grid_export_price=grid_export_price,
        )
        for idx, p in enumerate(profiles)
    ]

    ledger = Ledger(genesis_note=f"HELIO sim: {households} households, "
                                 f"{days} days, seed {seed}")
    n_intervals = int(days * 24 / interval_hours)

    intervals: List[Dict[str, Any]] = []
    total_p2p_kwh = 0.0
    total_grid_import_kwh = 0.0
    total_grid_export_kwh = 0.0
    total_demand_kwh = 0.0
    total_gen_kwh = 0.0
    p2p_cost = 0.0
    grid_baseline_cost = 0.0  # net cost with no P2P: all deficit imported,
                              # all surplus exported (export revenue credited)

    for t in range(n_intervals):
        asks: List[Ask] = []
        bids: List[Bid] = []
        for agent in agents:
            order = agent.decide(t)
            if isinstance(order, Ask):
                asks.append(order)
            elif isinstance(order, Bid):
                bids.append(order)

        clearing = clear_market(asks, bids)

        # Residuals go to the grid.
        for agent in agents:
            surplus_kwh = agent.forecast.surplus_kw[t] * interval_hours
            total_demand_kwh += agent.forecast.demand_kw[t] * interval_hours
            total_gen_kwh += agent.forecast.generation_kw[t] * interval_hours

        matched_by_household: Dict[str, float] = {}
        for tr in clearing.trades:
            matched_by_household[tr["buyer"]] = \
                matched_by_household.get(tr["buyer"], 0.0) + tr["kwh"]
            matched_by_household[tr["seller"]] = \
                matched_by_household.get(tr["seller"], 0.0) + tr["kwh"]
            total_p2p_kwh += tr["kwh"]
            p2p_cost += tr["kwh"] * tr["price"]

        for agent in agents:
            hid = agent.profile.household_id
            surplus_kwh = agent.forecast.surplus_kw[t] * interval_hours
            traded = matched_by_household.get(hid, 0.0)
            if surplus_kwh >= 0:
                # Surplus: traded P2P, the rest exported to grid.
                total_grid_export_kwh += max(0.0, surplus_kwh - traded)
            else:
                # Deficit: traded P2P, the rest imported from grid.
                total_grid_import_kwh += max(0.0, -surplus_kwh - traded)
            # Baseline: every deficit kWh bought from the grid, every
            # surplus kWh sold to the grid (export revenue credited).
            grid_baseline_cost += (max(0.0, -surplus_kwh) * grid_import_price
                                   - max(0.0, surplus_kwh) * grid_export_price)

        stamped = [dict(tr, interval=t, timestamp=time.time())
                   for tr in clearing.trades]
        ledger.append_trades(stamped)

        intervals.append({
            "interval": t,
            "hour_of_day": round((t * interval_hours) % 24, 2),
            "clearing_price": clearing.clearing_price,
            "matched_kwh": clearing.matched_kwh,
            "n_trades": len(clearing.trades),
            "unmatched_ask_kwh": clearing.unmatched_ask_kwh,
            "unmatched_bid_kwh": clearing.unmatched_bid_kwh,
        })

    verification = ledger.verify_chain()

    # Self-consumption: demand met by local solar (self-used + P2P), i.e.
    # everything that did NOT come from the grid.
    self_consumed_kwh = max(0.0, total_demand_kwh - total_grid_import_kwh)
    self_consumption_pct = (100.0 * self_consumed_kwh / total_demand_kwh
                            if total_demand_kwh > 0 else 0.0)

    actual_cost = (p2p_cost
                   + total_grid_import_kwh * grid_import_price
                   - total_grid_export_kwh * grid_export_price)

    return {
        "config": {"households": households, "days": days, "seed": seed,
                   "interval_hours": interval_hours,
                   "grid_import_price": grid_import_price,
                   "grid_export_price": grid_export_price},
        "intervals": intervals,
        "totals": {
            "p2p_traded_kwh": round(total_p2p_kwh, 3),
            "grid_import_kwh": round(total_grid_import_kwh, 3),
            "grid_export_kwh": round(total_grid_export_kwh, 3),
            "total_demand_kwh": round(total_demand_kwh, 3),
            "total_generation_kwh": round(total_gen_kwh, 3),
            "self_consumption_pct": round(self_consumption_pct, 1),
            "p2p_cost_usd": round(p2p_cost, 2),
            "actual_cost_usd": round(actual_cost, 2),
            "grid_baseline_cost_usd": round(grid_baseline_cost, 2),
            "saved_vs_grid_usd": round(grid_baseline_cost - actual_cost, 2),
        },
        "ledger": {"blocks": len(ledger.blocks),
                   "trades": ledger.trade_count(),
                   "verification": verification},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HELIO microgrid P2P energy trading simulation")
    parser.add_argument("--households", type=int, default=6)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interval-hours", type=float, default=1.0)
    parser.add_argument("--out", type=str, default="results.json")
    args = parser.parse_args()

    results = run_simulation(households=args.households, days=args.days,
                             seed=args.seed,
                             interval_hours=args.interval_hours)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    t = results["totals"]
    print("=" * 60)
    print("HELIO microgrid simulation")
    print("=" * 60)
    print(f"Households: {args.households}   Days: {args.days}   "
          f"Seed: {args.seed}   Interval: {args.interval_hours}h")
    print("\nClearing prices per interval (only intervals with trades):")
    for iv in results["intervals"]:
        if iv["n_trades"]:
            print(f"  hour {iv['hour_of_day']:>5.1f}  "
                  f"price ${iv['clearing_price']:.4f}/kWh  "
                  f"matched {iv['matched_kwh']:.2f} kWh "
                  f"({iv['n_trades']} trades)")
    print("\nTotals:")
    print(f"  P2P traded:        {t['p2p_traded_kwh']:>9.2f} kWh")
    print(f"  Grid import:       {t['grid_import_kwh']:>9.2f} kWh")
    print(f"  Grid export:       {t['grid_export_kwh']:>9.2f} kWh")
    print(f"  Total demand:      {t['total_demand_kwh']:>9.2f} kWh")
    print(f"  Total generation:  {t['total_generation_kwh']:>9.2f} kWh")
    print(f"  Self-consumption:  {t['self_consumption_pct']:>8.1f} %")
    print(f"  Saved vs all-grid: ${t['saved_vs_grid_usd']:>8.2f}")
    v = results["ledger"]["verification"]
    print(f"\nLedger: {results['ledger']['blocks']} blocks, "
          f"{results['ledger']['trades']} trades — "
          f"verification {'OK' if v['ok'] else 'FAILED @ block ' + str(v['broken_at'])}")
    print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
