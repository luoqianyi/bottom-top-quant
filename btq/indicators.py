"""Technical building blocks. All functions are causal (no look-ahead) unless noted."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD(12,26,9). DIF = EMA12-EMA26, DEA = EMA9(DIF), HIST = 2*(DIF-DEA) (A-share convention)."""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": 2 * (dif - dea)})


def typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"] + df["close"]) / 3.0


def anchored_vwap(df: pd.DataFrame, anchor_pos: int) -> pd.Series:
    """Anchored VWAP from integer bar position `anchor_pos` (inclusive). NaN before the anchor.
    AVWAP = sum(typical * vol) / sum(vol), cumulated from the anchor."""
    tp = typical_price(df).to_numpy()
    v = df["volume"].to_numpy(dtype=float)
    out = np.full(len(df), np.nan)
    if anchor_pos is None or anchor_pos < 0 or anchor_pos >= len(df):
        return pd.Series(out, index=df.index)
    pv = np.cumsum(tp[anchor_pos:] * v[anchor_pos:])
    vv = np.cumsum(v[anchor_pos:])
    with np.errstate(invalid="ignore", divide="ignore"):
        out[anchor_pos:] = np.where(vv > 0, pv / vv, tp[anchor_pos:])
    return pd.Series(out, index=df.index)


def speed_fan_level(p0: float, i0: int, p1: float, i1: int, ratio: float, i: int) -> float:
    """Speed resistance fan line value at bar i.
    The fan starts at the extreme (i0, p0) and passes through (i1, p1 + ratio*(p0-p1)) ... expressed as the
    retracement of the move (p0->p1) by `ratio` at x=i1, then extended linearly.
    For a down move (p0 = swing high, p1 = lowest low) the ratio-line at i1 sits at p0 - (1-ratio)*(p0-p1)?
    We follow the common convention: the 0.5 line passes through the midpoint of the range at the low bar.
    """
    if i1 == i0:
        return np.nan
    target = p0 + (p1 - p0) * ratio  # point on the vertical through i1
    slope = (target - p0) / (i1 - i0)
    return p0 + slope * (i - i0)


def confirmed_pivots(series: np.ndarray, k: int, kind: str):
    """Return list of (pos, value) pivot lows/highs, each confirmed only k bars after it happened.
    The tuple also carries `confirm_pos` = pos + k (first bar at which it is known)."""
    out = []
    n = len(series)
    for p in range(k, n - k):
        w = series[p - k:p + k + 1]
        v = series[p]
        if kind == "low" and v == w.min() and np.argmin(w) == k:
            out.append((p, v, p + k))
        if kind == "high" and v == w.max() and np.argmax(w) == k:
            out.append((p, v, p + k))
    return out
