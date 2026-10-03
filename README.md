# HELIO — Autonomous Peer-to-Peer Renewable Energy Trading Agents

**IEEE ClimateChain Global Hackathon 2026 · Track T2: Renewable Energy & Energy Trading**

HELIO is a working prototype of autonomous household agents that trade rooftop
solar energy with neighbours in a residential microgrid, instead of dumping
surplus to the grid for pennies and buying it back at full retail.

Each household runs one HELIO agent (designed to fit cheap local hardware like
a Raspberry Pi). Every market interval the agent forecasts its solar generation
and demand, submits a bid or ask to a double-auction market, and the cleared
trades are sealed into a tamper-evident hash-chained ledger.

## Quick start

```bash
# No dependencies beyond the standard library (+ pytest for tests).
python -m helio.simulate --households 6 --days 2 --seed 42
python -m pytest tests/ -q
```

The simulation prints clearing prices for intervals with trades, totals (P2P kWh
traded vs grid import/export), the self-consumption share, savings vs buying
everything from the grid, and the ledger verification result. Full detail goes
to `results.json`.

## Architecture

```
┌─────────────┐   forecast surplus/deficit    ┌──────────────────────┐
│ HELIO agent │ ───────────────────────────▶ │  Double-auction      │
│  (per house)│   ask: kWh @ min price        │  market (market.py)  │
│             │   bid: kWh @ max price        │                      │
│ forecast.py │ ◀─────────────────────────── │  merit-order match,  │
│ agent.py    │   clearing price + matches    │  uniform clearing    │
└──────┬──────┘                               │  price               │
       │ LLM hook (optional)                  └──────────┬───────────┘
       │ negotiate_with_llm()                            │ settled trades
       │ default: offline stub                           ▼
       │ opt-in: any OpenAI-compatible              ┌────────────────┐
       │ endpoint (e.g. local llama.cpp)            │ Hash-chained   │
       │                                            │ ledger         │
       │ unmatched surplus → grid export            │ (ledger.py)    │
       │ unmatched deficit → grid import            │ append-only,   │
       │                                            │ tamper-evident │
       └────────────────────────────────────────────▶└────────────────┘
```

**Module map**

| Module | Role |
|---|---|
| `helio/forecast.py` | Clear-sky solar model (solar geometry + seeded cloud noise) and household demand profiles (base + morning/midday/evening peaks). Deterministic per seed. Includes roof-orientation and pure-consumer archetypes. |
| `helio/agent.py` | Household agent: grid-anchored bid/ask strategy + the `negotiate_with_llm()` hook. Default is an offline stub (zero network); pass an `llm_config` to use any OpenAI-compatible endpoint, e.g. a local `llama-server` such as Qwen 2.5 Coder on `127.0.0.1:8081`. The LLM is advisory only — failures fall back to the stub. |
| `helio/market.py` | Uniform-price double auction: asks sorted ascending, bids descending, matched in merit order while bid ≥ ask. All matched kWh clear at the marginal ask price. Partial fills supported. |
| `helio/ledger.py` | Append-only hash-chained ledger: each block stores `{index, timestamp, trades, prev_hash, hash}`. `append_trades()` seals a block; `verify_chain()` detects any tampering and reports the exact block. |
| `helio/simulate.py` | CLI that runs the microgrid, settles residuals with the grid, verifies the ledger, prints the summary, and writes `results.json`. |

**Agent strategy (rational, grid-anchored):** a surplus agent asks at the grid
export price — it will never accept less from a neighbour than the grid pays.
A deficit agent bids at the grid import price — it will never pay a neighbour
more than the grid charges. The LLM hook may nudge the reservation price.

## Honest scope notes (please read before judging)

- **The ledger is a prototype, not a blockchain.** It is a local, single-process,
  in-memory hash chain with no consensus, no networking, and no signatures.
  What it honestly demonstrates is *tamper evidence*: settled history cannot be
  silently rewritten (`verify_chain()` proves it; `tests/test_ledger.py` proves
  the detection). A production deployment would need a real distributed ledger.
- **All data is simulated.** There are no smart meters, no weather APIs, no
  real households. Generation uses a clear-sky solar-geometry model with seeded
  cloud noise; demand uses synthetic load profiles.
- **No network calls, no API keys.** The default run is fully offline. The LLM
  hook only touches the network if you explicitly configure an endpoint.
- **Simplifications:** no batteries, no grid constraints or line losses, no
  transaction fees, hourly intervals, and every household is assumed honest.
- **Why P2P volumes look modest:** rooftop solar is highly correlated — most
  households have surplus at the same midday hours. Trades happen in the
  shoulder hours and between mismatched archetypes (east/west roofs, pure
  consumers, home-office loads). That correlation is real physics, not a bug,
  and it is exactly the problem storage and demand-shifting would address next.

## Reproducibility

Every run is seeded: the same `--seed` always produces the same households,
weather, trades, and ledger. `results.json` records the full config.

## License

MIT — built for the IEEE ClimateChain Global Hackathon 2026.
