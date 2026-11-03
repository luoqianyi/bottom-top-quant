"""Configuration (dataclasses, loadable from YAML)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import yaml


@dataclass
class SignalCfg:
    wave_lookback: int = 250       # bars to look back for the wave extreme
    min_wave_bars: int = 10        # wave must be at least this long
    min_wave_move: float = 0.20    # 抄底: drawdown from wave high must be >= 20%
    volume_window: int = 60        # 地量 / 天量: N-bar min / max
    vol_avg_window: int = 5        # 放量: compared with mean of previous 5 bars
    reclaim_vol_mult: float = 2.5  # 放量站回: volume >= 2.5x
    reclaim_tolerance: float = 0.0
    confirm_window: int = 5        # evidence 4 may have happened within the last 5 bars
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    pivot_k: int = 3               # pivot confirmation (bars on each side)
    low_tolerance: float = 0.005   # divergence pivot must be within 0.5% of the wave extreme
    fan_ratio: float = 0.5         # speed resistance fan line used (0.382 / 0.5 / 0.618)
    wave_pivot_k: int = 5          # zig-zag pivots used to find the wave start
    min_pivot_gap: int = 5         # divergence pivots must be at least 5 bars apart
    max_bars_from_extreme: int = 60  # only act within 60 bars of the wave low / high
    cluster_gap: int = 5           # 地量 bars within 5 bars belong to one cluster (anchor = cluster's first day)


@dataclass
class TopCfg:
    min_wave_move: float = 0.30    # 逃顶: rise from wave low must be >= 30%
    accept_volume_divergence: bool = True   # 量价背离 counts as evidence 1
    break_vol_mult: float = 0.0    # 0 = breaking the cost line needs no volume
    exit_score: int = 4            # sell everything when top score reaches this
    reduce_score: int = 3          # sell `reduce_frac` when top score reaches this
    reduce_frac: float = 0.5


@dataclass
class RiskCfg:
    initial_frac: float = 0.5      # 先上半仓
    add_frac: float = 0.5          # 回踩成本线没破，加仓
    add_tolerance: float = 0.015   # pullback within 1.5% of AVWAP counts as a retest
    stop_below_low: float = 0.03   # 止损: 最低点下方 3%
    exit_on_avwap_break: bool = True  # 跌回线下，判断错了，止损
    avwap_break_tolerance: float = 0.01
    take_profit_frac: float = 0.5  # sell half at target 1, raise stop to breakeven
    exit_at_target2: bool = False  # False: let the rest run until 逃顶 / trailing stop
    trail_after_tp: float = 0.15   # after target 1, trail the stop 15% under the highest close
    allow_short: bool = False      # open a short on a 4/4 top (crypto / futures / margin)


@dataclass
class CostCfg:
    commission: float = 0.0005     # per side
    slippage: float = 0.0005       # per side
    initial_cash: float = 100000.0


@dataclass
class Config:
    signal: SignalCfg = field(default_factory=SignalCfg)
    top: TopCfg = field(default_factory=TopCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    cost: CostCfg = field(default_factory=CostCfg)

    @classmethod
    def load(cls, path: str | None) -> "Config":
        cfg = cls()
        if not path:
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for section, obj in (("signal", cfg.signal), ("top", cfg.top), ("risk", cfg.risk), ("cost", cfg.cost)):
            for k, v in (raw.get(section) or {}).items():
                if not hasattr(obj, k):
                    raise KeyError(f"unknown config key {section}.{k}")
                setattr(obj, k, v)
        return cfg

    def to_dict(self):
        return asdict(self)
