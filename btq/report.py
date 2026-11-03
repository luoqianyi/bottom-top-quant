"""Charts and reports."""
from __future__ import annotations
import json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .indicators import macd


def _font():
    path = os.environ.get("BTQ_FONT")
    if path and os.path.exists(path):
        from matplotlib import font_manager
        font_manager.fontManager.addfont(path)
        plt.rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=path).get_name()]
        plt.rcParams["axes.unicode_minus"] = False
        return
    for name in ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "PingFang SC", "Microsoft YaHei", "Arial Unicode MS"]:
        try:
            from matplotlib import font_manager
            if any(name in f.name for f in font_manager.fontManager.ttflist):
                plt.rcParams["font.sans-serif"] = [name]
                break
        except Exception:
            pass
    plt.rcParams["axes.unicode_minus"] = False


def plot_backtest(bt, symbol: str, path: str):
    _font()
    df = bt.df
    m = macd(df["close"])
    fig, ax = plt.subplots(4, 1, figsize=(15, 11), sharex=True, gridspec_kw={"height_ratios": [4, 1.2, 1.2, 1.6]})
    ax[0].plot(df.index, df["close"], color="#333", lw=1, label="close")
    f = bt.trades()
    if not f.empty:
        b = f[f["shares"] > 0]
        s = f[f["shares"] < 0]
        ax[0].scatter(b["date"], b["price"], marker="^", color="#e03131", s=60, zorder=5, label="buy")
        ax[0].scatter(s["date"], s["price"], marker="v", color="#2f9e44", s=60, zorder=5, label="sell")
    for sig in bt.signals:
        ax[0].axvline(sig["date"], color="#f59f00" if sig["side"] == "bottom" else "#7048e8", alpha=0.25, lw=1)
    ax[0].set_title(f"{symbol}  四证抄底 / 四证逃顶")
    ax[0].legend(loc="upper left")
    ax[1].bar(df.index, df["volume"], color="#adb5bd", width=1)
    ax[1].set_ylabel("volume")
    ax[2].plot(df.index, m["dif"], lw=0.8, label="DIF")
    ax[2].plot(df.index, m["dea"], lw=0.8, label="DEA")
    ax[2].bar(df.index, m["hist"], color=np.where(m["hist"] >= 0, "#e03131", "#2f9e44"), width=1)
    ax[2].set_ylabel("MACD")
    eq = bt.equity / bt.equity.iloc[0]
    bh = df["close"] / df["close"].iloc[0]
    ax[3].plot(eq.index, eq, label="strategy", color="#1c7ed6")
    ax[3].plot(bh.index, bh, label="buy & hold", color="#868e96", alpha=0.7)
    ax[3].legend(loc="upper left")
    ax[3].set_ylabel("equity")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_report(bt, symbol: str, outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    met = bt.metrics()
    bt.trades().to_csv(os.path.join(outdir, "fills.csv"), index=False, encoding="utf-8-sig")
    bt.episodes().to_csv(os.path.join(outdir, "trades.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(bt.signals).to_csv(os.path.join(outdir, "signals.csv"), index=False, encoding="utf-8-sig")
    bt.equity.to_csv(os.path.join(outdir, "equity.csv"), encoding="utf-8-sig")
    with open(os.path.join(outdir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(met, f, ensure_ascii=False, indent=2)
    plot_backtest(bt, symbol, os.path.join(outdir, "chart.png"))
    return met


def plot_case(df, cfg, t: int, symbol: str, path: str, side: str = "bottom", before: int = 90, after: int = 60):
    """Zoomed chart of one signal: price, anchored VWAP, speed fan 0.5 line, 地量 anchor, divergence pivots, MACD, volume."""
    from .signals import SignalEngine
    _font()
    eng = SignalEngine(df, cfg)
    ev = eng.bottom(t) if side == "bottom" else eng.top(t)
    a0 = max(0, min(t - before, ev.extreme_pos or t) - 5)
    a1 = min(len(df), t + after)
    d = df.iloc[a0:a1]
    x = np.arange(a0, a1)
    m = macd(df["close"]).iloc[a0:a1]
    fig, ax = plt.subplots(3, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [4, 1.3, 1.3]})
    up = d["close"] >= d["open"]
    col = np.where(up, "#e03131", "#2f9e44")
    ax[0].vlines(x, d["low"], d["high"], color=col, lw=0.8)
    ax[0].bar(x, (d["close"] - d["open"]).abs().clip(lower=d["close"] * 0.0008), bottom=np.minimum(d["open"], d["close"]), color=col, width=0.7)
    if ev.anchor_pos is not None:
        aw = eng.avwap(ev.anchor_pos)[a0:a1]
        ax[0].plot(x, aw, color="#f59f00", lw=2, label="锚定VWAP（成本线）")
        ax[0].axvline(ev.anchor_pos, color="#f59f00", ls=":", lw=1)
        ax[0].annotate("地量第一天（锚点）" if side == "bottom" else "天量（锚点）", (ev.anchor_pos, df["low"].iloc[ev.anchor_pos]),
                       xytext=(0, -28), textcoords="offset points", ha="center", color="#e67700", fontsize=10)
    from .indicators import speed_fan_level
    i0, p0, i1, p1 = ev.extreme_pos, ev.extreme_price, ev.pivot_pos, ev.pivot_price
    if i0 is not None and i1 is not None and i1 > i0:
        for r, ls in ((0.382, ":"), (0.5, "-"), (0.618, ":")):
            xs = np.arange(i0, a1)
            ax[0].plot(xs, [speed_fan_level(p0, i0, p1, i1, r, i) for i in xs], color="#1c7ed6", ls=ls,
                       lw=1.6 if r == 0.5 else 0.9, label="速度阻力扇 0.5 线" if r == 0.5 else None)
    ax[0].axhline(ev.stop, color="#868e96", ls="--", lw=1, label=f"止损 {ev.stop:.2f}")
    for i, tg in enumerate(ev.targets):
        ax[0].axhline(tg, color="#be4bdb", ls="--", lw=0.8, label=f"目标{i + 1} {tg:.2f}")
    ax[0].scatter([t + 1], [df["open"].iloc[t + 1]] if t + 1 < len(df) else [df["close"].iloc[t]],
                  marker="^" if side == "bottom" else "v", s=160, color="#e03131" if side == "bottom" else "#2f9e44", zorder=6,
                  label="次日开盘进场" if side == "bottom" else "次日开盘离场")
    for n in ev.notes:
        if "pivots" in n:
            p1_, p2_ = [int(v) for v in n.split()[-1].split("->")]
            ax[0].plot([p1_, p2_], [df["low" if side == "bottom" else "high"].iloc[p] for p in (p1_, p2_)], color="#c92a2a", lw=1.5)
            ax[1].plot([p1_, p2_], [m["dif"].loc[df.index[p]] for p in (p1_, p2_)], color="#c92a2a", lw=1.5)
            ax[1].annotate("底背离" if side == "bottom" else "顶背离", (p2_, m["dif"].loc[df.index[p2_]]), xytext=(6, -14),
                           textcoords="offset points", color="#c92a2a")
    name = "抄底" if side == "bottom" else "逃顶"
    flags = "  ".join(("√" if f else "×") + s for f, s in zip([ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost],
                                                             ["量", "背离", "速度扇", "成本线"]))
    ax[0].set_title(f"{symbol}  {df.index[t].date()}  {name}证据 {ev.score}/4    {flags}")
    lo_y = min(d["low"].min(), ev.stop if np.isfinite(ev.stop) else d["low"].min())
    hi_y = max(d["high"].max(), ev.stop if np.isfinite(ev.stop) else d["high"].max())
    ax[0].set_ylim(lo_y * 0.95, hi_y * 1.04)
    ax[0].legend(loc="best", fontsize=9, framealpha=0.85)
    ax[1].plot(x, m["dif"], lw=1, label="DIF")
    ax[1].plot(x, m["dea"], lw=1, label="DEA")
    ax[1].bar(x, m["hist"], color=np.where(m["hist"] >= 0, "#e03131", "#2f9e44"), width=0.7)
    ax[1].set_ylabel("MACD")
    ax[2].bar(x, d["volume"], color=col, width=0.7)
    ax[2].set_ylabel("成交量")
    ticks = x[:: max(1, len(x) // 8)]
    ax[2].set_xticks(ticks)
    ax[2].set_xticklabels([str(df.index[i].date()) for i in ticks], fontsize=8)
    ax[2].axvline(t, color="#e03131", ls=":", lw=1)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return ev
