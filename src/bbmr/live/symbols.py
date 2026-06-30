def from_exchange_symbol(symbol: str) -> str:
    base = symbol.strip().upper().split("/", 1)[0]
    if not base:
        raise ValueError("symbol cannot be empty")
    for quote in ("USDT", "USDC", "USD"):
        if base.endswith(quote) and len(base) > len(quote):
            return base[: -len(quote)]
    return base


def to_exchange_symbol(symbol: str) -> str:
    return f"{from_exchange_symbol(symbol)}/USDC:USDC"


def same_symbol(left: str, right: str) -> bool:
    return from_exchange_symbol(left) == from_exchange_symbol(right)
