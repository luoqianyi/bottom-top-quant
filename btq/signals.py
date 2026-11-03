"""四证抄底 / 四证逃顶 signal logic.

抄底 (bottom) — all four evidences must hold ("四证不齐，一手别抄"):
  1. 地量   : volume shrinks to the lowest of the last N (60) bars inside the down wave.
              The first such bar becomes the anchor of the cost line (anchored VWAP).
  2. 底背离 : price prints a new low while MACD DIF does not (bullish divergence on confirmed pivots).
  3. 跌速   : close gets back above the 0.5 line of the speed-resistance fan drawn from the wave high
              to the wave low.
  4. 成本线 : close stands back above the anchored VWAP on expanded volume
              (volume >= 2.5 x mean of the previous 5 bars).

逃顶 (top) is the mirror image:
  1. 天量 / 量价背离 : volume hits the highest of the last N bars inside the up wave (anchor), or price makes
              a new high on less volume than the previous high.
  2. 顶背离 : price makes a new high while MACD DIF does not.
  3. 涨速   : close falls below the 0.5 line of the speed-resistance fan from the wave low to the wave high.
  4. 成本线 : close falls below the anchored VWAP (anchored at the 天量 bar), optionally on volume.

Every evaluation at bar t only uses bars 0..t (pivots are used only after they are confirmed).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import numpy as np
import pandas as pd

from .config import Config
from .indicators import macd, anchored_vwap, speed_fan_level, confirmed_pivots


@dataclass
class Evidence:
    side: str                      # "bottom" | "top"
    t: int                         # bar position evaluated
    date: object = None
    wave_ok: bool = False
    e1_volume: bool = False
    e2_divergence: bool = False
    e3_speed: bool = False
    e4_cost: bool = False
    extreme_pos: Optional[int] = None   # wave high (bottom) / wave low (top)
    extreme_price: float = np.nan
    pivot_pos: Optional[int] = None     # wave low (bottom) / wave high (top)
    pivot_price: float = np.nan
    anchor_pos: Optional[int] = None
    avwap: float = np.nan
    fan_05: float = np.nan
    stop: float = np.nan
    targets: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def score(self) -> int:
        return int(self.e1_volume) + int(self.e2_divergence) + int(self.e3_speed) + int(self.e4_cost)

    @property
    def fired(self) -> bool:
        return self.wave_ok and self.score == 4

    def to_dict(self):
        d = asdict(self)
        d["score"] = self.score
        d["fired"] = self.fired
        return d


class SignalEngine:
    def __init__(self, df: pd.DataFrame, cfg: Config):
        self.df = df.reset_index(drop=False)
        self.cfg = cfg
        c = cfg.signal
        self.o = self.df["open"].to_numpy(float)
        self.h = self.df["high"].to_numpy(float)
        self.l = self.df["low"].to_numpy(float)
        self.c = self.df["close"].to_numpy(float)
        self.v = self.df["volume"].to_numpy(float)
        m = macd(self.df["close"], c.macd_fast, c.macd_slow, c.macd_signal)
        self.dif = m["dif"].to_numpy()
        self.hist = m["hist"].to_numpy()
        n = c.volume_window
        vs = pd.Series(self.v)
        self.vmin = vs.rolling(n, min_periods=n).min().to_numpy()
        self.vmax = vs.rolling(n, min_periods=n).max().to_numpy()
        self.vavg_prev = vs.shift(1).rolling(c.vol_avg_window, min_periods=c.vol_avg_window).mean().to_numpy()
        self.piv_lo = confirmed_pivots(self.l, c.pivot_k, "low")
        self.piv_hi = confirmed_pivots(self.h, c.pivot_k, "high")
        self.wave_lo = confirmed_pivots(self.l, c.wave_pivot_k, "low")
        self.wave_hi = confirmed_pivots(self.h, c.wave_pivot_k, "high")
        self._avwap_cache = {}
        self.has_volume = np.nansum(self.v) > 0

    # ------------------------------------------------------------------ helpers
    def avwap(self, anchor: int) -> np.ndarray:
        if anchor not in self._avwap_cache:
            self._avwap_cache[anchor] = anchored_vwap(self.df, anchor).to_numpy()
        return self._avwap_cache[anchor]

    def _cluster_start(self, hits):
        """First bar of the most recent cluster of 地量/天量 bars (bars within `cluster_gap` of each other)."""
        if not hits:
            return None
        gap = self.cfg.signal.cluster_gap
        start = hits[-1]
        for a, b in zip(reversed(hits[:-1]), reversed(hits[1:])):
            if b - a <= gap:
                start = a
            else:
                break
        return start

    def _wave_start(self, t, lo, kind):
        """Most recent swing extreme from which the move to now is large enough (zig-zag style).
        Candidates are confirmed wave pivots plus the lookback extreme; we take the nearest candidate that is
        still the extreme of everything after it and whose move clears `min_wave_move`."""
        c = self.cfg.signal
        arr_hi, arr_lo = self.h, self.l
        piv = self.wave_hi if kind == "high" else self.wave_lo
        glob = lo + int(np.argmax(arr_hi[lo:t + 1]) if kind == "high" else np.argmin(arr_lo[lo:t + 1]))
        cands = sorted({p for (p, v, cp) in piv if lo <= p <= t and cp <= t} | {glob}, reverse=True)
        need = c.min_wave_move if kind == "high" else self.cfg.top.min_wave_move
        for p in cands:
            if kind == "high":
                if arr_hi[p] < arr_hi[p:t + 1].max():
                    continue
                if 1 - arr_lo[p:t + 1].min() / arr_hi[p] >= need:
                    return p
            else:
                if arr_lo[p] > arr_lo[p:t + 1].min():
                    continue
                if arr_hi[p:t + 1].max() / arr_lo[p] - 1 >= need:
                    return p
        return glob

    def _date(self, t):
        col = self.df.columns[0]
        return self.df[col].iloc[t]

    # ------------------------------------------------------------------ bottom
    def bottom(self, t: int) -> Evidence:
        c = self.cfg.signal
        ev = Evidence("bottom", t, self._date(t))
        lo = max(0, t - c.wave_lookback)
        if t - lo < c.volume_window:
            ev.notes.append("history too short")
            return ev
        iH = self._wave_start(t, lo, "high")
        PH = self.h[iH]
        if t - iH < c.min_wave_bars:
            ev.notes.append("wave high too recent")
            return ev
        iL = iH + int(np.argmin(self.l[iH:t + 1]))
        PL = self.l[iL]
        drop = 1 - PL / PH
        ev.extreme_pos, ev.extreme_price, ev.pivot_pos, ev.pivot_price = iH, PH, iL, PL
        ev.wave_ok = drop >= c.min_wave_move
        if not ev.wave_ok:
            ev.notes.append(f"drop {drop:.1%} < {c.min_wave_move:.0%}")

        # 1. 地量 — first bar in the wave whose volume is the N-bar minimum
        anchor = None
        if self.has_volume:
            hits = [j for j in range(iH + 1, t + 1)
                    if not np.isnan(self.vmin[j]) and 0 < self.v[j] <= self.vmin[j] * (1 + 1e-9)]
            anchor = self._cluster_start(hits)
        ev.e1_volume = anchor is not None
        ev.anchor_pos = anchor

        # 2. 底背离 — the pivot at the wave low vs the previous (higher) pivot low: price lower, DIF higher
        pl = [p for p in self.piv_lo if iH <= p[0] <= t and p[2] <= t]
        p2 = next((p for p in reversed(pl) if p[1] <= PL * (1 + c.low_tolerance)), None)
        if p2 is not None:
            prev = [p for p in pl if p[0] <= p2[0] - c.min_pivot_gap and p[1] > p2[1]]
            if prev:
                p1 = prev[-1]
                if self.dif[p2[0]] > self.dif[p1[0]]:
                    ev.e2_divergence = True
                    ev.notes.append(f"divergence pivots {p1[0]}->{p2[0]}")
        if t - iL > c.max_bars_from_extreme:
            ev.wave_ok = False
            ev.notes.append("too far from the wave low")

        # 3. 跌速 — close back above the 0.5 speed fan line
        if t > iL:
            f05 = speed_fan_level(PH, iH, PL, iL, c.fan_ratio, t)
            ev.fan_05 = f05
            ev.e3_speed = self.c[t] > f05

        # 4. 成本线 — volume reclaim of the anchored VWAP within the confirmation window
        if anchor is not None:
            aw = self.avwap(anchor)
            ev.avwap = aw[t]
            if self.c[t] > aw[t]:
                # bars since the close last crossed above the cost line (capped by confirm_window after the cross)
                j0 = t
                while j0 - 1 > anchor and self.c[j0 - 1] > aw[j0 - 1] * (1 + c.reclaim_tolerance):
                    j0 -= 1
                for j in range(j0, min(t, j0 + c.confirm_window - 1) + 1):
                    vol_ok = self.vavg_prev[j] > 0 and self.v[j] >= c.reclaim_vol_mult * self.vavg_prev[j]
                    if self.c[j] > aw[j] and vol_ok:
                        ev.e4_cost = True
                        break

        # risk levels
        ev.stop = PL * (1 - self.cfg.risk.stop_below_low)
        res = sorted({round(v, 6) for (p, v, cp) in self.piv_hi if iH < p < t and cp <= t and v > self.c[t]})
        if len(res) < 2:
            res += [PL + 0.382 * (PH - PL), PL + 0.618 * (PH - PL)]
        ev.targets = sorted(x for x in res if x > self.c[t])[:2]
        return ev

    # ------------------------------------------------------------------ top
    def top(self, t: int) -> Evidence:
        c = self.cfg.signal
        tc = self.cfg.top
        ev = Evidence("top", t, self._date(t))
        lo = max(0, t - c.wave_lookback)
        if t - lo < c.volume_window:
            ev.notes.append("history too short")
            return ev
        iL = self._wave_start(t, lo, "low")
        PL = self.l[iL]
        if t - iL < c.min_wave_bars:
            return ev
        iH = iL + int(np.argmax(self.h[iL:t + 1]))
        PH = self.h[iH]
        rise = PH / PL - 1
        ev.extreme_pos, ev.extreme_price, ev.pivot_pos, ev.pivot_price = iL, PL, iH, PH
        ev.wave_ok = rise >= tc.min_wave_move

        # 1. 天量 (or 量价背离)
        anchor = None
        if self.has_volume:
            hits = [j for j in range(iL + 1, t + 1)
                    if not np.isnan(self.vmax[j]) and self.v[j] >= self.vmax[j] * (1 - 1e-9)]
            anchor = self._cluster_start(hits)
        ph = [p for p in self.piv_hi if iL <= p[0] <= t and p[2] <= t]
        shrink = False
        if len(ph) >= 2 and self.has_volume:
            (p2, v2, _), (p1, v1, _) = ph[-1], ph[-2]
            shrink = v2 > v1 and self.v[p2] < self.v[p1]
        ev.e1_volume = anchor is not None or (tc.accept_volume_divergence and shrink)
        if anchor is None and shrink:
            anchor = ph[-1][0]
        ev.anchor_pos = anchor

        # 2. 顶背离 — the pivot at the wave high vs the previous (lower) pivot high: price higher, DIF lower
        p2 = next((p for p in reversed(ph) if p[1] >= PH * (1 - c.low_tolerance)), None)
        if p2 is not None:
            prev = [p for p in ph if p[0] <= p2[0] - c.min_pivot_gap and p[1] < p2[1]]
            if prev:
                p1 = prev[-1]
                if self.dif[p2[0]] < self.dif[p1[0]]:
                    ev.e2_divergence = True
                    ev.notes.append(f"top divergence pivots {p1[0]}->{p2[0]}")
        if t - iH > c.max_bars_from_extreme:
            ev.wave_ok = False

        # 3. 涨速 — close below 0.5 fan line from the low to the high
        if t > iH:
            f05 = speed_fan_level(PL, iL, PH, iH, c.fan_ratio, t)
            ev.fan_05 = f05
            ev.e3_speed = self.c[t] < f05

        # 4. 成本线 — close falls below the anchored VWAP
        if anchor is not None:
            aw = self.avwap(anchor)
            ev.avwap = aw[t]
            if self.c[t] < aw[t]:
                j0 = t
                while j0 - 1 > anchor and self.c[j0 - 1] < aw[j0 - 1] * (1 - c.reclaim_tolerance):
                    j0 -= 1
                for j in range(j0, min(t, j0 + c.confirm_window - 1) + 1):
                    vol_ok = tc.break_vol_mult <= 0 or (self.vavg_prev[j] > 0 and self.v[j] >= tc.break_vol_mult * self.vavg_prev[j])
                    if self.c[j] < aw[j] and vol_ok:
                        ev.e4_cost = True
                        break
        ev.stop = PH * (1 + self.cfg.risk.stop_below_low)
        ev.targets = sorted([PH - 0.382 * (PH - PL), PH - 0.618 * (PH - PL)], reverse=True)
        return ev


def scan(df: pd.DataFrame, cfg: Config) -> dict:
    """Evaluate the latest bar. Returns both sides."""
    eng = SignalEngine(df, cfg)
    t = len(df) - 1
    return {"bottom": eng.bottom(t), "top": eng.top(t)}
