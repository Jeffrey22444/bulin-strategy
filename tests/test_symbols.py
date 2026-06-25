import pytest

from bbmr.symbols import from_exchange_symbol, to_exchange_symbol


@pytest.mark.parametrize("symbol", ["BTC", "btc", "BTCUSDT", "BTC/USDC:USDC"])
def test_from_exchange_symbol_normalizes_to_base(symbol):
    assert from_exchange_symbol(symbol) == "BTC"


def test_to_exchange_symbol_uses_hyperliquid_usdc_perpetual():
    assert to_exchange_symbol("BTC", "hyperliquid") == "BTC/USDC:USDC"


def test_empty_symbol_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        from_exchange_symbol("")


def test_non_hyperliquid_exchange_is_rejected():
    with pytest.raises(ValueError, match="Hyperliquid"):
        to_exchange_symbol("BTC", "binance")
