"""Command line: python -m btq <scan|backtest|watch> ..."""
from __future__ import annotations
import argparse, json, sys, time
import numpy as np

from .config import Config
from . import data
from .signals import scan
from .backtest import Backtester
from .report import write_report

LABELS = {
    "bottom": ["地量", "底背离", "跌速(站上扇形0.5线)", "成本线(放量站回锚定VWAP)"],
    "top": ["天量/量价背离", "顶背离", "涨速(跌破扇形0.5线)", "成本线(跌破锚定VWAP)"],
}


def _fmt(x):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.4f}".rstrip("0").rstrip(".")


def print_scan(symbol, res, df):
    last = df.index[-1].date()
    print(f"\n== {symbol}  {last}  close {_fmt(df['close'].iloc[-1])}")
    for side in ("bottom", "top"):
        ev = res[side]
        name = "抄底" if side == "bottom" else "逃顶"
        flags = [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]
        marks = "  ".join(("✔" if f else "✘") + lab for f, lab in zip(flags, LABELS[side]))
        if ev.fired:
            verdict = "信号成立"
        elif not ev.wave_ok:
            verdict = "未形成有效波段"
        elif side == "top" and ev.score >= 3:
            verdict = "三证已现，先减半仓"
        else:
            verdict = "四证不齐，一手别动" if side == "bottom" else "四证不齐，继续持有"
        print(f"  [{name}] 证据 {ev.score}/4  {verdict}")
        print(f"     {marks}")
        if ev.wave_ok:
            print(f"     成本线 {_fmt(ev.avwap)}  扇形0.5线 {_fmt(ev.fan_05)}  止损 {_fmt(ev.stop)}  目标 {', '.join(_fmt(x) for x in ev.targets)}")


def read_watchlist(path):
    """Lines like `AAPL`, `akshare:600519`, `ccxt:binance:BTC/USDT`, `csv:data/x.csv`; # starts a comment."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            src = "yahoo"
            for prefix in ("yahoo", "akshare", "ccxt", "csv"):
                if line.startswith(prefix + ":"):
                    src, line = prefix, line[len(prefix) + 1:]
                    break
            out.append((line, src))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="btq", description="四证抄底 / 四证逃顶 量化系统")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "backtest", "watch"):
        s = sub.add_parser(name)
        s.add_argument("symbols", nargs="+", help="e.g. 000001.SS AAPL 0700.HK BTC-USD")
        s.add_argument("--source", default="yahoo", choices=["yahoo", "akshare", "ccxt", "csv"])
        s.add_argument("--start", default=None)
        s.add_argument("--end", default=None)
        s.add_argument("--config", default=None)
        if name == "backtest":
            s.add_argument("--out", default="reports")
        if name == "watch":
            s.add_argument("--every", type=int, default=3600, help="seconds between checks")
            s.add_argument("--webhook", default=None, help="POST alerts as JSON to this URL (企业微信/飞书/钉钉/Discord)")
    s = sub.add_parser("serve", help="web terminal (FastAPI + TradingView Lightweight Charts)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s = sub.add_parser("case", help="zoomed chart of one signal date")
    s.add_argument("symbol")
    s.add_argument("--date", required=True)
    s.add_argument("--side", default="bottom", choices=["bottom", "top"])
    s.add_argument("--source", default="yahoo")
    s.add_argument("--config", default=None)
    s.add_argument("--out", default="case.png")
    s = sub.add_parser("alert", help="scan a watchlist once and push 3/4+ alerts (for cron / GitHub Actions)")
    s.add_argument("--watchlist", default="watchlist.txt")
    s.add_argument("--config", default=None)
    s.add_argument("--webhook", default=None)
    s.add_argument("--min-score", type=int, default=3)
    a = ap.parse_args(argv)
    cfg = Config.load(getattr(a, "config", None))

    if a.cmd == "scan":
        for sym in a.symbols:
            df = data.load(sym, a.source, a.start or "2015-01-01", a.end)
            print_scan(sym, scan(df, cfg), df)
    elif a.cmd == "backtest":
        for sym in a.symbols:
            df = data.load(sym, a.source, a.start, a.end)
            bt = Backtester(df, cfg).run()
            out = f"{a.out}/{sym.replace('/', '_').replace(':', '_')}"
            met = write_report(bt, sym, out)
            print(f"\n== {sym}  -> {out}")
            print(json.dumps(met, ensure_ascii=False, indent=2))
            ep = bt.episodes()
            if not ep.empty:
                print(ep.to_string(index=False))
    elif a.cmd == "serve":
        from .server import serve
        print(f"btq 终端: http://{a.host}:{a.port}")
        serve(a.host, a.port)
    elif a.cmd == "case":
        import pandas as pd
        from .report import plot_case
        df = data.load(a.symbol, a.source, None, None)
        t = int(df.index.searchsorted(pd.Timestamp(a.date), side="right") - 1)
        ev = plot_case(df, cfg, t, a.symbol, a.out, a.side)
        print(f"{a.symbol} {df.index[t].date()} {a.side} score {ev.score}/4 -> {a.out}")
    elif a.cmd == "alert":
        from .notify import send
        hits = 0
        for sym, source in read_watchlist(a.watchlist):
            try:
                df = data.load(sym, source, "2015-01-01", None)
                res = scan(df, cfg)
                print_scan(sym, res, df)
                for side, ev in res.items():
                    if ev.wave_ok and ev.score >= a.min_score:
                        hits += 1
                        send(a.webhook or None, sym, side, ev, float(df["close"].iloc[-1]))
            except Exception as ex:
                print(f"[{sym}] error: {ex}", file=sys.stderr)
        print(f"\n{hits} alert(s)")
    elif a.cmd == "watch":
        from .notify import send
        seen = set()
        while True:
            for sym in a.symbols:
                try:
                    df = data.load(sym, a.source, a.start or "2015-01-01", a.end)
                    res = scan(df, cfg)
                    print_scan(sym, res, df)
                    for side, ev in res.items():
                        key = (sym, side, str(df.index[-1].date()))
                        if ev.score >= 3 and ev.wave_ok and key not in seen:
                            seen.add(key)
                            send(a.webhook, sym, side, ev, float(df["close"].iloc[-1]))
                except Exception as ex:  # keep watching other symbols
                    print(f"[{sym}] error: {ex}", file=sys.stderr)
            time.sleep(a.every)


if __name__ == "__main__":
    main()
