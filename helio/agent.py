"""Household trading agent.

Each agent owns one household profile. Every market interval it:
  1. looks at its forecast surplus/deficit for the interval,
  2. builds a bid (deficit) or ask (surplus) using a simple rational
     strategy anchored to the grid's buy/sell prices,
  3. optionally refines the order through the LLM-negotiation hook.

LLM-negotiation hook
--------------------
`negotiate_with_llm(prompt, llm_config=None)` is the integration point for a
real language model at the head of the trading decision:

  * Default (`llm_config=None`): a deterministic heuristic stub — NO network,
    NO API key, fully offline. This is what the prototype and tests use.
  * Opt-in: pass `llm_config = {"base_url": ..., "model": ..., "api_key": ...}`
    pointing at any OpenAI-compatible chat-completions endpoint — for
    example a local llama.cpp server such as Michael Woolum's Qwen 2.5 Coder
    at http://127.0.0.1:8081. The agent then asks the model to propose a
    price adjustment, parses the JSON reply, and falls back to the stub if
    the model is unreachable or misbehaves.

The hook is deliberately OFF by default so the prototype runs anywhere with
zero network access.
"""

from __future__ import annotations

import json
import random
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .forecast import HouseholdProfile, ForecastResult
from .market import Ask, Bid


# ---------------------------------------------------------------------------
# LLM negotiation hook
# ---------------------------------------------------------------------------

def negotiate_with_llm(prompt: str,
                       llm_config: Optional[Dict[str, str]] = None,
                       timeout_s: float = 10.0) -> Dict[str, Any]:
    """Propose a trading strategy adjustment, optionally via an LLM.

    Args:
        prompt: Natural-language description of the situation, e.g.
            "I have 2.3 kWh surplus this hour. Grid export pays $0.04/kWh,
             grid import costs $0.16/kWh. Suggest an ask price."
        llm_config: Optional {"base_url", "model", "api_key"} for an
            OpenAI-compatible chat-completions endpoint. When None, the
            offline heuristic stub is used (no network ever).
        timeout_s: HTTP timeout for the opt-in LLM path.

    Returns:
        {"price_adjust": float, "reason": str, "source": "stub"|"llm"}
        where price_adjust is a fractional tweak to the reservation price
        (e.g. +0.05 means "raise price 5%").
    """
    if llm_config is None:
        return _stub_negotiate(prompt)

    try:
        return _llm_negotiate(prompt, llm_config, timeout_s)
    except Exception as exc:  # LLM is advisory — never let it break trading
        result = _stub_negotiate(prompt)
        result["reason"] += f" (LLM unavailable: {exc})"
        result["source"] = "stub-fallback"
        return result


def _stub_negotiate(prompt: str) -> Dict[str, Any]:
    """Offline heuristic: hold reservation prices, no adjustment."""
    return {"price_adjust": 0.0,
            "reason": "stub: trade at grid-anchored reservation price",
            "source": "stub"}


def _llm_negotiate(prompt: str, cfg: Dict[str, str],
                   timeout_s: float) -> Dict[str, Any]:
    """Query an OpenAI-compatible endpoint; parse a JSON strategy reply."""
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system",
             "content": ("You are a household energy trading strategist. Reply "
                         "with ONLY a JSON object: {\"price_adjust\": <float "
                         "fraction, e.g. 0.05>, \"reason\": \"<short>\"}.")},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 120,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg.get('api_key', '')}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = payload["choices"][0]["message"]["content"].strip()
    # Tolerate code fences around the JSON.
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    parsed = json.loads(text)
    return {"price_adjust": float(parsed.get("price_adjust", 0.0)),
            "reason": str(parsed.get("reason", ""))[:200],
            "source": "llm"}


# ---------------------------------------------------------------------------
# Household agent
# ---------------------------------------------------------------------------

@dataclass
class HouseholdAgent:
    """One HELIO agent = one household in the microgrid.

    Strategy (rational, grid-anchored):
      * Surplus -> ASK the full surplus at the grid export price (the agent
        will never accept less from a neighbour than the grid would pay).
      * Deficit -> BID the full deficit at the grid import price (the agent
        will never pay a neighbour more than the grid would charge).
    The LLM hook may then nudge the reservation price by a small fraction.
    """

    profile: HouseholdProfile
    forecast: ForecastResult
    grid_import_price: float = 0.16   # $/kWh — what the grid charges you
    grid_export_price: float = 0.04   # $/kWh — what the grid pays you
    llm_config: Optional[Dict[str, str]] = None
    rng: random.Random = field(default_factory=random.Random)

    def decide(self, interval: int) -> Ask | Bid | None:
        """Build this interval's market order (or None if balanced)."""
        surplus_kw = self.forecast.surplus_kw[interval]
        kwh = abs(surplus_kw) * self.interval_hours
        if kwh < 1e-9:
            return None

        if surplus_kw > 0:
            prompt = (f"I have {kwh:.2f} kWh surplus this interval. Grid "
                      f"export pays ${self.grid_export_price:.3f}/kWh. Suggest "
                      f"an ask price adjustment.")
            adj = negotiate_with_llm(prompt, self.llm_config)["price_adjust"]
            price = self.grid_export_price * (1.0 + adj)
            return Ask(seller=self.profile.household_id, kwh=kwh,
                       min_price=round(price, 4))
        else:
            prompt = (f"I need {kwh:.2f} kWh this interval. Grid import costs "
                      f"${self.grid_import_price:.3f}/kWh. Suggest a bid "
                      f"price adjustment.")
            adj = negotiate_with_llm(prompt, self.llm_config)["price_adjust"]
            price = self.grid_import_price * (1.0 + adj)
            return Bid(buyer=self.profile.household_id, kwh=kwh,
                       max_price=round(price, 4))

    @property
    def interval_hours(self) -> float:
        if len(self.forecast.hours) > 1:
            return self.forecast.hours[1] - self.forecast.hours[0]
        return 1.0
