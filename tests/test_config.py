from spotscale.config import Config


def test_defaults():
    c = Config()
    assert c.max_workers == 4
    assert c.min_workers == 0
    assert c.max_hourly_spend == 5.00


def test_from_env_overrides():
    env = {
        "SPOTSCALE_GPU": "A100",
        "SPOTSCALE_MAX_PRICE": "1.25",
        "SPOTSCALE_MAX_SPEND": "20",
        "SPOTSCALE_MAX_WORKERS": "8",
        "SPOTSCALE_SCALE_THRESHOLD": "5",
    }
    c = Config.from_env(env)
    assert c.gpu == "A100"
    assert c.max_price_per_hour == 1.25
    assert c.max_hourly_spend == 20.0
    assert c.max_workers == 8
    assert c.scale_threshold == 5


def test_from_env_ignores_blank_and_bad():
    env = {"SPOTSCALE_MAX_WORKERS": "", "SPOTSCALE_MIN_WORKERS": "notint"}
    c = Config.from_env(env)
    assert c.max_workers == 4   # blank -> default
    assert c.min_workers == 0   # unparseable -> default
