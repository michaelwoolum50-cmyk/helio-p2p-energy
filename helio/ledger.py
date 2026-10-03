"""Hash-chained, append-only trade ledger (prototype).

Each block commits to the hash of the previous block, so any tampering with
a settled trade changes that block's hash and breaks every later link.
`verify_chain()` detects this and reports exactly where the chain broke.

Prototype scope (honest): this is a local, single-process, in-memory ledger
for the hackathon prototype. It is NOT a distributed blockchain, has no
consensus, no networking, and no cryptographic signatures — a real deployment
would add those. What it DOES honestly demonstrate is tamper evidence: you
cannot silently rewrite history.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(obj: Any) -> str:
    """Deterministic JSON serialisation used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Block:
    """One ledger block: a batch of settled trades plus the chain link."""

    index: int
    timestamp: float
    trades: List[Dict[str, Any]]
    prev_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        body = {
            "index": self.index,
            "timestamp": self.timestamp,
            "trades": self.trades,
            "prev_hash": self.prev_hash,
        }
        return _sha256_hex(_canonical(body))

    def seal(self) -> "Block":
        """Compute and store this block's hash. Call once, at append time."""
        self.hash = self.compute_hash()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Ledger:
    """Append-only hash-chained ledger of settled energy trades."""

    def __init__(self, genesis_note: str = "HELIO genesis block") -> None:
        genesis = Block(
            index=0,
            timestamp=time.time(),
            trades=[{"type": "genesis", "note": genesis_note}],
            prev_hash="0" * 64,
        ).seal()
        self.blocks: List[Block] = [genesis]

    def append_trades(self, trades: List[Dict[str, Any]],
                      timestamp: Optional[float] = None) -> Block:
        """Append one block containing a batch of settled trades.

        Each trade should be a JSON-serialisable dict, e.g.
        {"buyer": "H1", "seller": "H0", "kwh": 1.25, "price": 0.11,
         "interval": 7, "timestamp": 1710000000.0}.
        Empty batches are allowed (they still advance the chain).
        """
        block = Block(
            index=len(self.blocks),
            timestamp=time.time() if timestamp is None else timestamp,
            trades=[dict(t) for t in trades],
            prev_hash=self.blocks[-1].hash,
        ).seal()
        self.blocks.append(block)
        return block

    def verify_chain(self) -> Dict[str, Any]:
        """Verify the full chain. Returns {"ok": bool, "broken_at": int|None}.

        Checks, for every block: the stored hash matches a recomputation over
        the block's contents, and prev_hash equals the previous block's hash.
        """
        for i, block in enumerate(self.blocks):
            if block.compute_hash() != block.hash:
                return {"ok": False, "broken_at": i,
                        "reason": f"block {i}: stored hash != recomputed hash"}
            if i == 0:
                if block.prev_hash != "0" * 64:
                    return {"ok": False, "broken_at": 0,
                            "reason": "genesis prev_hash corrupted"}
            elif block.prev_hash != self.blocks[i - 1].hash:
                return {"ok": False, "broken_at": i,
                        "reason": f"block {i}: prev_hash does not match block {i-1}"}
        return {"ok": True, "broken_at": None, "reason": "",
                "blocks": len(self.blocks)}

    def trade_count(self) -> int:
        return sum(len(b.trades) for b in self.blocks
                   if not (len(b.trades) == 1 and b.trades[0].get("type") == "genesis"))

    def to_dict(self) -> Dict[str, Any]:
        return {"blocks": [b.to_dict() for b in self.blocks]}
