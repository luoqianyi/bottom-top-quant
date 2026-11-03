import numpy as np
import pandas as pd
from btq.config import Config
from btq.indicators import anchored_vwap, macd, speed_fan_level
from btq.signals import SignalEngine
from btq.backtest import Backtester


def _df(close, vol):
    idx = pd.date_range("2020-01-01", periods=len(close), freq="D")
    c = np.asarray(close, float)
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": np.asarray(vol, float)}, index=idx)


def test_anchored_vwap_constant_price():
    df = _df([10] * 20, [100] * 20)
    aw = anchored_vwap(df, 5)
    assert np.isnan(aw.iloc[4]) and abs(aw.iloc[-1] - 10) < 1e-9


def test_anchored_vwap_weights_volume():
    df = _df([10, 20], [1, 3])
    aw = anchored_vwap(df, 0)
    assert abs(aw.iloc[-1] - (10 * 1 + 20 * 3) / 4) < 1e-9


def test_speed_fan_midpoint():
    # high 100 at bar 0, low 50 at bar 10 -> 0.5 line is 75 at bar 10 and keeps falling
    assert speed_fan_level(100, 0, 50, 10, 0.5, 10) == 75
    assert speed_fan_level(100, 0, 50, 10, 0.5, 20) == 50


def test_macd_shapes():
    m = macd(pd.Series(np.linspace(1, 2, 100)))
    assert list(m.columns) == ["dif", "dea", "hist"] and len(m) == 100


def synthetic_bottom():
    """Up, crash with a lower low on weaker momentum, drying volume, then a volume reclaim."""
    rng = np.random.default_rng(0)
    up = np.linspace(60, 100, 80)
    d1 = np.linspace(100, 62, 30)
    b1 = np.linspace(62, 70, 8)
    d2 = np.linspace(70, 58, 18)        # slow grind to a marginally lower low -> divergence
    flat = np.full(10, 58.5)
    rec = np.linspace(59, 80, 25)
    close = np.concatenate([up, d1, b1, d2, flat, rec]) * (1 + rng.normal(0, 0.002, 171))
    vol = np.concatenate([np.full(80, 1000), np.full(30, 1500), np.full(8, 900), np.linspace(700, 300, 18),
                          np.full(10, 250), [2500] * 3, np.full(22, 900)])
    return _df(close, vol)


def test_bottom_evidences_appear():
    df = synthetic_bottom()
    eng = SignalEngine(df, Config())
    scores = [eng.bottom(t) for t in range(100, len(df))]
    assert any(e.e1_volume for e in scores)
    assert any(e.e3_speed for e in scores)
    assert max(e.score for e in scores) >= 3


def test_no_lookahead():
    """Evidence at bar t must not change when future bars are appended."""
    df = synthetic_bottom()
    full = SignalEngine(df, Config())
    for t in (130, 145, 150, 160):
        part = SignalEngine(df.iloc[: t + 1], Config())
        a, b = full.bottom(t), part.bottom(t)
        assert (a.e1_volume, a.e2_divergence, a.e3_speed, a.e4_cost) == (b.e1_volume, b.e2_divergence, b.e3_speed, b.e4_cost)


def test_backtest_runs():
    bt = Backtester(synthetic_bottom(), Config()).run()
    m = bt.metrics()
    assert "total_return" in m and len(bt.equity) == 171


def test_analysis_replay_no_lookahead():
    """Analysis at bar t must be identical whether or not later bars exist (bar replay relies on this)."""
    from btq.analysis import Analyzer
    df = _synthetic() if "_synthetic" in globals() else None
    if df is None:
        import numpy as np, pandas as pd
        rng = np.random.default_rng(1)
        n = 600
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
        idx = pd.bdate_range("2020-01-01", periods=n)
        df = pd.DataFrame(dict(open=c * (1 + rng.normal(0, 0.003, n)), high=c * 1.01, low=c * 0.99, close=c,
                               volume=rng.integers(1_000, 10_000, n).astype(float)), index=idx)
    cfg = Config()
    t = 450
    a_full = Analyzer(df, cfg).analyze(t=t)
    a_cut = Analyzer(df.iloc[: t + 1], cfg).analyze()
    for k in ("evidence", "scores", "plan", "interpretation"):
        assert a_full[k] == a_cut[k], k
    assert a_full["plan"]["stop"] is not None
