"""Ledger tests: tamper-evidence must hold."""

from helio.ledger import Ledger


def _sample_trades():
    return [
        {"buyer": "H1", "seller": "H0", "kwh": 1.25,
         "price": 0.11, "interval": 7},
        {"buyer": "H2", "seller": "H0", "kwh": 0.75,
         "price": 0.11, "interval": 7},
    ]


def test_chain_verifies_when_untouched():
    ledger = Ledger()
    ledger.append_trades(_sample_trades())
    ledger.append_trades(_sample_trades())
    result = ledger.verify_chain()
    assert result["ok"] is True
    assert result["broken_at"] is None


def test_tampering_with_trade_is_detected():
    ledger = Ledger()
    ledger.append_trades(_sample_trades())
    # Attacker rewrites a settled trade (e.g. inflates the kWh sold).
    ledger.blocks[1].trades[0]["kwh"] = 999.0
    result = ledger.verify_chain()
    assert result["ok"] is False
    assert result["broken_at"] == 1


def test_tampering_with_prev_hash_is_detected():
    ledger = Ledger()
    ledger.append_trades(_sample_trades())
    ledger.append_trades(_sample_trades())
    ledger.blocks[2].prev_hash = "0" * 64
    result = ledger.verify_chain()
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_empty_batches_still_advance_chain():
    ledger = Ledger()
    ledger.append_trades([])
    assert ledger.verify_chain()["ok"] is True
    assert len(ledger.blocks) == 2


def test_trade_count_excludes_genesis():
    ledger = Ledger()
    assert ledger.trade_count() == 0
    ledger.append_trades(_sample_trades())
    assert ledger.trade_count() == 2
