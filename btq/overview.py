"""首屏总览：每个市场收盘后，对 markets.yaml 里的每个标的跑一遍四证，给出 入场 / 离场 / 减仓 / 关注 / 观望。"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import yaml

from .analysis import Analyzer, _r

MARKET_NAME = {"cn": "A股收盘", "hk": "港股收盘", "us": "美股收盘", "global": "全球"}


def load_markets(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def verdict(a: dict) -> tuple[str, str, str]:
    b, t = a["evidence"]["bottom"], a["evidence"]["top"]
    bn = [i["name"].split("（")[0] for i in b["items"] if i["ok"]]
    tn = [i["name"].split("（")[0] for i in t["items"] if i["ok"]]
    if b["fired"]:
        return "入场", "go", f"抄底四证齐全，止损 {b['stop']:,.2f}" if b["stop"] else "抄底四证齐全"
    if t["fired"]:
        return "离场", "stop", "逃顶四证齐全：" + "、".join(tn)
    if t["score"] >= 3:
        return "减仓", "warn", "逃顶三证：" + "、".join(tn)
    if b["score"] >= 3 and b["wave_ok"]:
        return "关注", "wait", "抄底三证，等第四证：" + "、".join(bn)
    return "观望", "idle", (f"抄底 {b['score']}/4 · 逃顶 {t['score']}/4")


def one(item: dict, get_df, cfg) -> dict:
    out = dict(name=item["name"], symbol=item["symbol"], market=item.get("market", "global"))
    try:
        df = get_df(item["symbol"])
        a = Analyzer(df, cfg).analyze()
        c = df["close"].to_numpy(float)
        v, tone, why = verdict(a)
        out.update(
            date=a["date"], close=_r(c[-1]), chg=_r(c[-1] - c[-2]), chg_pct=_r((c[-1] / c[-2] - 1) * 100, 2),
            spark=[_r(x) for x in c[-60:]],
            bottom=a["evidence"]["bottom"]["score"], top=a["evidence"]["top"]["score"],
            composite=a["scores"]["composite"], bias=a["scores"]["bias"],
            verdict=v, tone=tone, reason=why, no_volume=bool(np.nansum(df["volume"].to_numpy(float)[-60:]) == 0),
        )
    except Exception as ex:  # one bad source must not break the page
        out.update(error=str(getattr(ex, "detail", ex))[:120])
    return out


def build(markets: dict, get_df, cfg, workers: int = 6) -> dict:
    t0 = time.time()
    items = [(g["name"], it) for g in markets["groups"] for it in g["items"]]
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda p: one(p[1], get_df, cfg), items))
    groups, k = [], 0
    for g in markets["groups"]:
        n = len(g["items"])
        groups.append(dict(name=g["name"], items=res[k:k + n]))
        k += n
    ok = [r for r in res if not r.get("error")]
    counts = {v: sum(1 for r in ok if r["verdict"] == v) for v in ("入场", "离场", "减仓", "关注", "观望")}
    asof = {}
    for r in ok:
        asof[r["market"]] = max(asof.get(r["market"], ""), r["date"])
    by_sym = {r["symbol"]: r for r in res}
    ticker = [by_sym[s] for s in markets.get("ticker", []) if s in by_sym and not by_sym[s].get("error")]
    return dict(generated=time.strftime("%Y-%m-%d %H:%M:%S %Z"), groups=groups, counts=counts,
                asof={MARKET_NAME.get(k, k): v for k, v in sorted(asof.items())}, ticker=ticker,
                seconds=round(time.time() - t0, 1), total=len(res), errors=len(res) - len(ok))
