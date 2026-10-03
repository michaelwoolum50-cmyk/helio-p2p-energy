"""HELIO — autonomous peer-to-peer renewable energy trading agents.

An IEEE ClimateChain Global Hackathon 2026 entry (track T2: Renewable Energy
& Energy Trading).

Each HELIO agent represents one household in a residential microgrid. Agents
forecast their rooftop solar generation and household demand, trade surplus
energy with neighbours in a double-auction market, and settle trades on a
hash-chained, tamper-evident prototype ledger.

Prototype scope (honest): the ledger is a local hash-chained prototype, not a
mainnet blockchain. Generation/demand data is simulated, not metered. There
are no network calls, no API keys, and no real money.
"""

__version__ = "0.1.0"
__all__ = ["forecast", "ledger", "market", "agent", "simulate"]
