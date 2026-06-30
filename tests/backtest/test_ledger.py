import pytest

from bbmr.backtest.ledger import Ledger
from bbmr.signals import EntryReference
from bbmr.state_machine import TradeState
from bbmr.trade_models import TradeContext


def test_long_pnl_and_fees():
    ledger = Ledger("BTC", cash=1000, fee_rate=0.001, slippage_rate=0)
    context = TradeContext(side="long", entry_reference=EntryReference("s", 90, 100, 110, 1, "long"), fixed_sl=95, one_r=5)
    ledger.open_trade("t1", "long", 100, 1, context, TradeState.PENDING_ENTRY, TradeState.OPEN_NORMAL)
    ledger.close_trade("t2", 110, "TAKE_PROFIT_5M", "take_profit", TradeState.OPEN_NORMAL, TradeState.EXITED)
    assert ledger.trades[0]["gross_pnl"] == 10
    assert ledger.trades[0]["fees"] == pytest.approx(0.21)
    assert ledger.trades[0]["net_pnl"] == pytest.approx(9.79)


def test_short_pnl_and_fees():
    ledger = Ledger("BTC", cash=1000, fee_rate=0.001, slippage_rate=0)
    context = TradeContext(side="short", entry_reference=EntryReference("s", 90, 100, 110, 1, "short"), fixed_sl=105, one_r=5)
    ledger.open_trade("t1", "short", 100, 1, context, TradeState.PENDING_ENTRY, TradeState.OPEN_NORMAL)
    ledger.close_trade("t2", 90, "TAKE_PROFIT_5M", "take_profit", TradeState.OPEN_NORMAL, TradeState.EXITED)
    assert ledger.trades[0]["gross_pnl"] == 10
    assert ledger.trades[0]["fees"] == pytest.approx(0.19)
    assert ledger.trades[0]["net_pnl"] == pytest.approx(9.81)


def test_add_updates_weighted_average():
    ledger = Ledger("BTC", cash=1000, fee_rate=0, slippage_rate=0)
    context = TradeContext(side="long", entry_reference=EntryReference("s", 90, 100, 110, 1, "long"), fixed_sl=95, one_r=5)
    ledger.open_trade("t1", "long", 100, 1, context, TradeState.PENDING_ENTRY, TradeState.OPEN_NORMAL)
    ledger.add_trade("t2", 90, 1, context, TradeState.OPEN_NORMAL, TradeState.OPEN_ADDED)
    assert ledger.position.weighted_avg_entry == 95
