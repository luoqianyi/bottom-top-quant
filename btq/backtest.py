"""Event-driven daily backtest of the 四证抄底 / 四证逃顶 rules.

Timing: evidences are evaluated on the close of bar t; orders fill on the open of bar t+1.
Stops and targets are checked intrabar (fill at the level, or at the open if the bar gaps through it).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .config import Config
from .signals import SignalEngine


@dataclass
class Position:
    side: int = 0              # +1 long, -1 short, 0 flat
    shares: float = 0.0
    avg: float = 0.0
    stop: float = np.nan
    targets: list = field(default_factory=list)
    anchor: int | None = None
    entry_t: int = -1
    added: bool = False
    tp_done: bool = False
    reduced: bool = False
    episode: int = 0


class Backtester:
    def __init__(self, df: pd.DataFrame, cfg: Config):
        self.df = df
        self.cfg = cfg
        self.eng = SignalEngine(df, cfg)
        self.fills = []
        self.signals = []
        self.equity = []

    # -------------------------------------------------------------- order helpers
    def _fill(self, t, price, shares, reason):
        """shares > 0 buy, < 0 sell. Applies slippage + commission."""
        cc = self.cfg.cost
        px = price * (1 + cc.slippage * np.sign(shares))
        cost = px * shares
        fee = abs(cost) * cc.commission
        self.cash -= cost + fee
        p = self.pos
        new = p.shares + shares
        if p.shares == 0 or np.sign(new) != np.sign(p.shares):
            p.avg = px
        elif abs(new) > abs(p.shares):
            p.avg = (p.avg * p.shares + px * shares) / new
        p.shares = new
        if abs(p.shares) < 1e-9:
            p.shares = 0.0
        self.fills.append(dict(date=self.df.index[t], t=t, action="BUY" if shares > 0 else "SELL", price=round(px, 6),
                               shares=round(shares, 6), reason=reason, episode=p.episode))

    def _equity(self, t, price):
        return self.cash + self.pos.shares * price

    def _open_side(self, t, side, ev, reason):
        p = self.pos
        p.episode += 1
        p.side = side
        eq = self._equity(t, self.eng.o[t])
        sh = eq * self.cfg.risk.initial_frac / self.eng.o[t]
        self._fill(t, self.eng.o[t], side * sh, reason)
        p.stop = ev.stop
        p.targets = list(ev.targets)
        p.anchor = ev.anchor_pos
        p.entry_t = t
        p.added = p.tp_done = p.reduced = False
        p.peak = self.eng.o[t]

    def _close_all(self, t, price, reason):
        if self.pos.shares != 0:
            self._fill(t, price, -self.pos.shares, reason)
        self.pos.side = 0
        self.pos.stop = np.nan

    # -------------------------------------------------------------- main loop
    def run(self) -> "Backtester":
        cfg, e = self.cfg, self.eng
        n = len(self.df)
        self.cash = cfg.cost.initial_cash
        self.pos = Position()
        pending = []          # list of (kind, payload)
        used_waves = set()
        warm = cfg.signal.volume_window + cfg.signal.min_wave_bars
        for t in range(n):
            o, h, l, c = e.o[t], e.h[t], e.l[t], e.c[t]
            p = self.pos
            # 1) execute pending orders at the open
            for kind, ev in pending:
                if kind == "open_long" and p.side == 0:
                    self._open_side(t, +1, ev, "抄底 4/4 先上半仓")
                elif kind == "open_short" and p.side == 0:
                    self._open_side(t, -1, ev, "逃顶 4/4 开空")
                elif kind == "add" and p.side != 0 and not p.added:
                    eq = self._equity(t, o)
                    self._fill(t, o, p.side * eq * cfg.risk.add_frac / o, "回踩成本线不破 加仓")
                    p.added = True
                elif kind == "exit" and p.side != 0:
                    self._close_all(t, o, ev)
                elif kind == "reduce" and p.side != 0 and not p.reduced:
                    self._fill(t, o, -p.shares * cfg.top.reduce_frac, "逃顶 3/4 减仓")
                    p.reduced = True
                elif kind == "flip_short" and p.side == 0:
                    self._open_side(t, -1, ev, "逃顶 4/4 反手开空")
            pending = []

            # 2) intrabar stop / target
            if p.side == 1:
                if l <= p.stop:
                    self._close_all(t, min(o, p.stop), "保本/移动止盈" if p.tp_done else "止损(最低点下方3%)")
                elif not p.tp_done and p.targets and h >= p.targets[0]:
                    self._fill(t, max(o, p.targets[0]), -p.shares * cfg.risk.take_profit_frac, "第一目标 止盈一半")
                    p.tp_done = True
                    p.stop = max(p.stop, p.avg)
                elif cfg.risk.exit_at_target2 and p.tp_done and len(p.targets) > 1 and h >= p.targets[1]:
                    self._close_all(t, max(o, p.targets[1]), "第二目标 清仓")
                if p.side == 1 and p.tp_done and cfg.risk.trail_after_tp > 0:
                    p.peak = max(getattr(p, "peak", c), c)
                    p.stop = max(p.stop, p.peak * (1 - cfg.risk.trail_after_tp))
            elif p.side == -1:
                if h >= p.stop:
                    self._close_all(t, max(o, p.stop), "空单止损")
                elif not p.tp_done and p.targets and l <= p.targets[0]:
                    self._fill(t, min(o, p.targets[0]), -p.shares * cfg.risk.take_profit_frac, "空单第一目标")
                    p.tp_done = True
                    p.stop = min(p.stop, p.avg)

            # 3) close-of-bar evaluation
            if t >= warm and t < n - 1:
                if p.side == 0:
                    b = e.bottom(t)
                    key = (b.extreme_pos, b.pivot_pos)
                    if b.fired and key not in used_waves:
                        used_waves.add(key)
                        self.signals.append(dict(date=self.df.index[t], side="bottom", score=4, close=c,
                                                 stop=b.stop, avwap=b.avwap, targets=[round(float(x), 4) for x in b.targets]))
                        pending.append(("open_long", b))
                    elif cfg.risk.allow_short:
                        tp = e.top(t)
                        k2 = ("top", tp.extreme_pos, tp.pivot_pos)
                        if tp.fired and k2 not in used_waves:
                            used_waves.add(k2)
                            self.signals.append(dict(date=self.df.index[t], side="top", score=4, close=c,
                                                     stop=tp.stop, avwap=tp.avwap, targets=[round(float(x), 4) for x in tp.targets]))
                            pending.append(("open_short", tp))
                elif p.side == 1:
                    aw = e.avwap(p.anchor)[t] if p.anchor is not None else np.nan
                    tp = e.top(t)
                    if tp.wave_ok and tp.score >= cfg.top.exit_score:
                        self.signals.append(dict(date=self.df.index[t], side="top", score=tp.score, close=c,
                                                 stop=tp.stop, avwap=tp.avwap, targets=[round(float(x), 4) for x in tp.targets]))
                        pending.append(("exit", "逃顶 4/4 清仓"))
                        if cfg.risk.allow_short:
                            pending.append(("flip_short", tp))
                    elif cfg.risk.exit_on_avwap_break and not np.isnan(aw) and c < aw * (1 - cfg.risk.avwap_break_tolerance) and t > p.entry_t:
                        pending.append(("exit", "跌回成本线下 判断错了"))
                    else:
                        if tp.wave_ok and tp.score >= cfg.top.reduce_score and not p.reduced:
                            pending.append(("reduce", None))
                        if (not p.added and t - p.entry_t >= 2 and not np.isnan(aw)
                                and l <= aw * (1 + cfg.risk.add_tolerance) and c >= aw):
                            pending.append(("add", None))
                elif p.side == -1:
                    aw = e.avwap(p.anchor)[t] if p.anchor is not None else np.nan
                    b = e.bottom(t)
                    if b.wave_ok and b.score >= 3:
                        pending.append(("exit", "空单 遇抄底信号 平仓"))
                    elif cfg.risk.exit_on_avwap_break and not np.isnan(aw) and c > aw * (1 + cfg.risk.avwap_break_tolerance) and t > p.entry_t:
                        pending.append(("exit", "空单 站回成本线 平仓"))
            self.equity.append(self._equity(t, c))
        self.equity = pd.Series(self.equity, index=self.df.index, name="equity")
        return self

    # -------------------------------------------------------------- results
    def trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.fills)

    def episodes(self) -> pd.DataFrame:
        f = self.trades()
        if f.empty:
            return pd.DataFrame(columns=["episode", "side", "entry_date", "exit_date", "pnl", "ret", "bars"])
        rows = []
        for ep, g in f.groupby("episode"):
            flow = -(g["price"] * g["shares"]).sum()
            first = g.iloc[0]
            side = "long" if first["shares"] > 0 else "short"
            gross = (g["price"] * g["shares"].abs())[g["shares"] * np.sign(first["shares"]) > 0].sum()
            closed = abs(g["shares"].sum()) < 1e-6
            rows.append(dict(episode=ep, side=side, entry_date=first["date"], exit_date=g.iloc[-1]["date"] if closed else None,
                             pnl=flow if closed else np.nan, ret=flow / gross if closed and gross else np.nan,
                             bars=int(g.iloc[-1]["t"] - first["t"]), exit_reason=g.iloc[-1]["reason"] if closed else "持仓中"))
        return pd.DataFrame(rows)

    def metrics(self) -> dict:
        eq = self.equity
        rets = eq.pct_change().fillna(0)
        years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
        total = eq.iloc[-1] / eq.iloc[0] - 1
        dd = (eq / eq.cummax() - 1).min()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
        bh = self.df["close"].iloc[-1] / self.df["close"].iloc[0] - 1
        ep = self.episodes().dropna(subset=["pnl"])
        wins = ep[ep["pnl"] > 0]
        losses = ep[ep["pnl"] <= 0]
        pf = wins["pnl"].sum() / -losses["pnl"].sum() if len(losses) and losses["pnl"].sum() < 0 else np.inf if len(wins) else 0
        return {
            "start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
            "total_return": round(total, 4), "cagr": round((1 + total) ** (1 / years) - 1, 4),
            "max_drawdown": round(dd, 4), "sharpe": round(sharpe, 2),
            "buy_and_hold": round(bh, 4), "trades": int(len(ep)), "win_rate": round(len(wins) / len(ep), 3) if len(ep) else None,
            "profit_factor": round(pf, 2) if np.isfinite(pf) else "inf",
            "avg_trade_ret": round(ep["ret"].mean(), 4) if len(ep) else None,
        }
