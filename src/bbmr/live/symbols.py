def from_exchange_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
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


def canonical_symbols(symbols: list[str]) -> list[str]:
    if not symbols:
        raise ValueError("symbols.default cannot be empty")
    canonical = [from_exchange_symbol(symbol) for symbol in symbols]
    if len(set(canonical)) != len(canonical):
        raise ValueError("symbols.default contains duplicate or equivalent symbols")
    return canonical
