from bbmr.add_rules import long_add_allowed, short_add_allowed


def _long_kwargs(**overrides):
    data = dict(
        has_long_position=True,
        add_count=0,
        floating_pnl_R=-0.6,
        add_trigger_loss_r=0.5,
        fixed_sl_triggered=False,
        soft_fail_long=False,
        squeeze=False,
        expansion=False,
        lower_band_walking=False,
        volume_ratio=1.0,
        volume_reject=1.8,
        long_second_reentry_confirmed=True,
    )
    data.update(overrides)
    return data


def _short_kwargs(**overrides):
    data = dict(
        has_short_position=True,
        add_count=0,
        floating_pnl_R=-0.6,
        add_trigger_loss_r=0.5,
        fixed_sl_triggered=False,
        soft_fail_short=False,
        squeeze=False,
        expansion=False,
        upper_band_walking=False,
        volume_ratio=1.0,
        volume_reject=1.8,
        short_second_reentry_confirmed=True,
    )
    data.update(overrides)
    return data


def test_long_add_allowed_true_path():
    assert long_add_allowed(**_long_kwargs()) is True


def test_long_add_blockers():
    for key, value in [
        ("soft_fail_long", True),
        ("squeeze", True),
        ("expansion", True),
        ("lower_band_walking", True),
        ("volume_ratio", 1.8),
        ("long_second_reentry_confirmed", False),
    ]:
        assert long_add_allowed(**_long_kwargs(**{key: value})) is False


def test_short_add_allowed_and_blocked_by_second_reentry():
    assert short_add_allowed(**_short_kwargs()) is True
    assert short_add_allowed(**_short_kwargs(short_second_reentry_confirmed=False)) is False
