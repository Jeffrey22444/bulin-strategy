import pytest

from bbmr.live.symbols import from_exchange_symbol, same_symbol, to_exchange_symbol


def test_symbol_conversion():
    assert to_exchange_symbol("btc") == "BTC/USDC:USDC"
    assert from_exchange_symbol("BTC/USDC:USDC") == "BTC"
    assert from_exchange_symbol("BTCUSDC") == "BTC"
    assert same_symbol("BTC", "BTC/USDC:USDC") is True


def test_empty_symbol_rejected():
    with pytest.raises(ValueError):
        from_exchange_symbol(" ")
