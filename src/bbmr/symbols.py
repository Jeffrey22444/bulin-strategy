"""Translate stable logical symbols to Hyperliquid exchange symbols."""


def from_exchange_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("invalid symbol: empty string")

    base = normalized.split("/", 1)[0]
    for quote in ("USDT", "USDC", "USD"):
        if base.endswith(quote) and len(base) > len(quote):
            return base[: -len(quote)]
    return base


def to_exchange_symbol(symbol: str, exchange_name: str) -> str:
    if exchange_name.lower() != "hyperliquid":
        raise ValueError(f"only Hyperliquid is supported: {exchange_name}")
    return f"{from_exchange_symbol(symbol)}/USDC:USDC"
