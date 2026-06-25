import pandas as pd


ORDER_COLUMNS = ["timestamp", "run_id", "trade_id", "symbol", "side", "order_type", "price", "size", "reason"]


def generate_orders_from_events(events, config) -> pd.DataFrame:
    return pd.DataFrame(columns=ORDER_COLUMNS)
