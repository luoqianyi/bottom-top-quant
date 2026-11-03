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
