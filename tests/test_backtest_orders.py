from bbmr.backtest_orders import ORDER_COLUMNS, generate_orders_from_events


def test_generate_orders_from_events_returns_empty_schema():
    orders = generate_orders_from_events([], None)
    assert list(orders.columns) == ORDER_COLUMNS
    assert orders.empty
