from bbmr.backtest.data import load_ohlcv_csv
from bbmr.backtest.features import build_1h_features
from bbmr.config import load_config


def test_feature_builder_emits_bw_percentile_not_bw_pct():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    features = build_1h_features(load_ohlcv_csv("tests/fixtures/ohlcv/BTC_1h.csv"), config)
    assert "bw_percentile" in features.columns
    assert "bw_pct" not in features.columns


def test_feature_builder_emits_side_specific_and_active_fail_columns():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    features = build_1h_features(load_ohlcv_csv("tests/fixtures/ohlcv/BTC_1h.csv"), config)
    for column in ["soft_fail_long", "soft_fail_short", "early_fail_long", "early_fail_short", "soft_fail", "early_fail"]:
        assert column in features.columns
    for column in ["squeeze", "expansion", "range_allowed", "long_signal_1h", "short_signal_1h", "invalid_signal"]:
        assert column in features.columns
