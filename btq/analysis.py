"""Chart analysis for the web terminal: structure, rule signals, drawings, scores and the trade plan.

Everything is computed from bars 0..t only, so the same function powers the live view and bar replay.
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd

from .config import Config
from .signals import SignalEngine
from .indicators import macd, speed_fan_level, confirmed_pivots

FIB = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
PERIODS = {"short": ("短线", 20), "mid": ("中线", 60), "long": ("长线", 120)}


def _ts(x) -> int:
    return int(pd.Timestamp(x).tz_localize(None).timestamp()) if pd.Timestamp(x).tzinfo else int(pd.Timestamp(x).timestamp())


def _r(x, n=4):
    if x is None:
        return None
    try:
        x = float(x)
    except Exception:
        return None
    return None if not np.isfinite(x) else round(x, n)


def _clip(x, lo=-100, hi=100):
    return int(round(max(lo, min(hi, x))))


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf in ("1d", "d", "day", None):
        return df
    rule = {"1w": "W-FRI", "w": "W-FRI", "1M": "ME", "m": "ME"}[tf]
    o = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return o.dropna(subset=["close"])


def future_times(df: pd.DataFrame, n: int) -> list[int]:
    """Whitespace timestamps to extend lines to the right of the last bar."""
    idx = df.index
    if len(idx) < 3:
        return []
    weekend = any(d.weekday() >= 5 for d in idx[-30:])
    step = pd.Timedelta(idx[-1] - idx[-2]) if len(idx) > 1 else pd.Timedelta(days=1)
    if step >= pd.Timedelta(days=5):
        rng = pd.date_range(idx[-1] + step, periods=n, freq=step)
    else:
        rng = pd.date_range(idx[-1] + pd.Timedelta(days=1), periods=n, freq="D" if weekend else "B")
    return [_ts(d) for d in rng]


class Analyzer:
    def __init__(self, df: pd.DataFrame, cfg: Config):
        self.full = df
        self.cfg = cfg

    # ------------------------------------------------------------------ scores
    def _scores(self, d: pd.DataFrame, win: int, evb, evt):
        c, h, l, v = (d[k].to_numpy(float) for k in ("close", "high", "low", "volume"))
        t = len(d) - 1
        ma20 = pd.Series(c).rolling(20).mean().to_numpy()
        ma60 = pd.Series(c).rolling(60).mean().to_numpy()
        trend = 0
        txt = []
        if np.isfinite(ma20[t]):
            trend += 50 if c[t] > ma20[t] else -50
            txt.append("收盘在 MA20 " + ("上方" if c[t] > ma20[t] else "下方"))
        if np.isfinite(ma60[t]):
            trend += 50 if ma20[t] > ma60[t] else -50
            txt.append("MA20 " + ("高于" if ma20[t] > ma60[t] else "低于") + " MA60")
        w = min(win, t)
        r = c[t] / c[t - w] - 1 if w > 0 else 0
        mom = _clip(r / 0.2 * 100)
        seg = slice(t - w + 1, t + 1)
        chg = np.diff(c[t - w:t + 1]) if w > 0 else np.array([])
        vv = v[seg]
        up = vv[chg > 0].mean() if (chg > 0).any() else 0
        dn = vv[chg <= 0].mean() if (chg <= 0).any() else 0
        ratio = up / dn if dn > 0 else 1.0
        vol_score = _clip((ratio - 1) * 100) if np.nansum(v) > 0 else 0
        tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
        atr = pd.Series(tr).rolling(14).mean().to_numpy()
        atrp = atr[-1] / c[t] * 100 if len(atr) and np.isfinite(atr[-1]) else 0
        volat = _clip(-(atrp - 2) * 20)
        k = self.cfg.signal.wave_pivot_k
        ph = [p for p in confirmed_pivots(h, k, "high") if p[2] <= t]
        pl = [p for p in confirmed_pivots(l, k, "low") if p[2] <= t]
        st = 0
        stxt = "结构不明"
        if len(ph) >= 2 and len(pl) >= 2:
            hh = ph[-1][1] > ph[-2][1]
            hl = pl[-1][1] > pl[-2][1]
            st = (30 if hh else -30) + (30 if hl else -30)
            stxt = {(True, True): "高点抬高、低点抬高", (False, False): "高点降低、低点降低",
                    (True, False): "高点抬高、低点降低（扩散）", (False, True): "高点降低、低点抬高（收敛）"}[(hh, hl)]
        st += 10 * evb.score - 10 * evt.score
        if evb.score >= 3 and evb.e3_speed:
            stxt = "结构转强"
        elif evt.score >= 3 and evt.e3_speed:
            stxt = "结构转弱"
        struct = _clip(st)
        items = [
            dict(key="trend", name="趋势", score=_clip(trend), desc="，".join(txt) or "-"),
            dict(key="momentum", name="动量", score=mom, desc=f"近 {w} 根涨跌 {r * 100:+.1f}%"),
            dict(key="volume", name="量能", score=vol_score, desc=f"近 {w} 根涨日量为跌日的 {ratio:.2f} 倍"),
            dict(key="volatility", name="波动", score=volat, desc=f"ATR {atrp:.2f}%"),
            dict(key="structure", name="结构", score=struct, desc=stxt),
        ]
        wts = dict(trend=0.3, momentum=0.2, volume=0.15, volatility=0.1, structure=0.25)
        comp = _clip(sum(wts[i["key"]] * i["score"] for i in items))
        bias = "偏多" if comp >= 20 else "偏空" if comp <= -20 else "中性"
        return dict(composite=comp, bias=bias, items=items, atr_pct=_r(atrp, 2))

    # ------------------------------------------------------------------ main
    def analyze(self, t: int | None = None, direction: str = "long", holding: str = "flat",
                period: str = "short", ext: int = 20) -> dict:
        timings = {}
        t0 = time.perf_counter()
        full = self.full
        if t is None or t >= len(full):
            t = len(full) - 1
        d = full.iloc[: t + 1]
        eng = SignalEngine(d, self.cfg)
        T = len(d) - 1
        times = [_ts(x) for x in d.index]
        fut = future_times(d, ext)
        all_times = times + fut
        timings["structure"] = time.perf_counter() - t0

        t1 = time.perf_counter()
        evb, evt = eng.bottom(T), eng.top(T)
        ev = evb if direction == "long" else evt
        timings["signals"] = time.perf_counter() - t1

        t2 = time.perf_counter()
        draw = self._drawings(d, eng, ev, evb, evt, direction, times, all_times, T)
        timings["drawings"] = time.perf_counter() - t2

        pname, win = PERIODS.get(period, PERIODS["short"])
        scores = self._scores(d, win, evb, evt)
        plan = self._plan(d, eng, ev, evb, evt, direction, holding, draw)
        text = self._interpret(d, ev, evb, evt, direction, holding, plan, scores)
        timings["ai"] = time.perf_counter() - t0
        last = d.iloc[-1]
        return dict(
            symbol=None, date=str(d.index[-1].date()), t=T, n=len(full),
            price=_r(last["close"]), change_pct=_r((last["close"] / d["close"].iloc[-2] - 1) * 100, 2) if len(d) > 1 else 0,
            period=dict(key=period, name=pname, bars=win), direction=direction, holding=holding,
            evidence=dict(bottom=self._ev_dict(evb, eng), top=self._ev_dict(evt, eng)),
            scores=scores, plan=plan, drawings=draw, interpretation=text,
            steps=[
                dict(key="structure", name="识别图表结构", desc=f"{draw['n_structure']} 条结构线 · 历史数据", sec=_r(timings["structure"], 2)),
                dict(key="signals", name="计算规则信号", desc=plan["verdict"], sec=_r(timings["signals"], 2)),
                dict(key="drawings", name="在图上划线", desc=f"共 {draw['n_total']} 条，逐条画出", sec=_r(timings["drawings"], 2)),
                dict(key="ai", name="AI 深度解读", desc="含在本次分析内", sec=_r(timings["ai"], 2)),
            ],
        )

    def _ev_dict(self, ev, eng):
        names = (["地量", "底背离", "跌速放缓（站上扇形 0.5 线）", "成本线（放量站回锚定 VWAP）"] if ev.side == "bottom"
                 else ["天量 / 量价背离", "顶背离", "涨速衰竭（跌破扇形 0.5 线）", "跌破成本线（锚定 VWAP）"])
        flags = [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]
        detail = [None] * 4
        if ev.anchor_pos is not None:
            detail[0] = f"锚点 {eng.df.iloc[ev.anchor_pos, 0].date()}"
        for n in ev.notes:
            if "pivots" in n:
                a, b = [int(x) for x in n.split()[-1].split("->")]
                detail[1] = f"{eng.df.iloc[a, 0].date()} → {eng.df.iloc[b, 0].date()}"
        if np.isfinite(ev.fan_05):
            detail[2] = f"0.5 线 {ev.fan_05:,.2f}"
        if np.isfinite(ev.avwap):
            detail[3] = f"成本线 {ev.avwap:,.2f}"
        return dict(score=ev.score, fired=ev.fired, wave_ok=ev.wave_ok,
                    items=[dict(name=nm, ok=bool(f), detail=dt) for nm, f, dt in zip(names, flags, detail)],
                    avwap=_r(ev.avwap), fan_05=_r(ev.fan_05), stop=_r(ev.stop), targets=[_r(x) for x in ev.targets],
                    wave=dict(start=_r(ev.extreme_price), end=_r(ev.pivot_price)))

    # ------------------------------------------------------------------ drawings
    def _drawings(self, d, eng, ev, evb, evt, direction, times, all_times, T):
        lines, levels, markers, zones = [], [], [], []
        c = d["close"].to_numpy(float)
        h, l = eng.h, eng.l
        last_ext = len(all_times) - 1
        i0, p0, i1, p1 = ev.extreme_pos, ev.extreme_price, ev.pivot_pos, ev.pivot_price
        if i0 is not None and i1 is not None and i1 > i0:
            for r, col, w in ((0.382, "#22c55e", 1), (0.5, "#eab308", 2), (0.618, "#38bdf8", 1)):
                pts = [dict(time=all_times[i], value=_r(speed_fan_level(p0, i0, p1, i1, r, i)))
                       for i in (i0, i1, last_ext)]
                lines.append(dict(id=f"fan{r}", kind="fan", label=f"速度扇 {r}", color=col, width=w, style=0 if r == 0.5 else 2, points=pts))
            # fibonacci from the wave start to the wave extreme
            hi, lo = (p0, p1) if direction == "long" else (p1, p0)
            for r in FIB:
                price = lo + r * (hi - lo) if direction == "long" else hi - r * (hi - lo)
                levels.append(dict(id=f"fib{r}", kind="fib", label=f"{r:g}", price=_r(price), color="#a78bfa", style=2))
        if ev.anchor_pos is not None:
            aw = eng.avwap(ev.anchor_pos)
            pts = [dict(time=times[i], value=_r(aw[i])) for i in range(ev.anchor_pos, T + 1) if np.isfinite(aw[i])]
            lines.append(dict(id="avwap", kind="avwap", label="成本线 AVWAP", color="#f59e0b", width=2, style=0, points=pts))
            markers.append(dict(time=times[ev.anchor_pos], position="belowBar" if ev.side == "bottom" else "aboveBar",
                                color="#f59e0b", shape="circle", text="地量" if ev.side == "bottom" else "天量"))
        for e in (evb, evt):
            for n in e.notes:
                if "pivots" in n:
                    a, b = [int(x) for x in n.split()[-1].split("->")]
                    key = "low" if e.side == "bottom" else "high"
                    arr = l if key == "low" else h
                    lines.append(dict(id=f"div_{e.side}", kind="divergence", label="底背离" if e.side == "bottom" else "顶背离",
                                      color="#ef4444" if e.side == "bottom" else "#10b981", width=2, style=0,
                                      points=[dict(time=times[a], value=_r(arr[a])), dict(time=times[b], value=_r(arr[b]))],
                                      macd=[dict(time=times[a], value=_r(eng.dif[a])), dict(time=times[b], value=_r(eng.dif[b]))]))
        # zig-zag pivots A..E
        k = self.cfg.signal.wave_pivot_k
        piv = sorted([(p, v, "H") for p, v, cp in eng.wave_hi if cp <= T] + [(p, v, "L") for p, v, cp in eng.wave_lo if cp <= T])
        zz = []
        for p in piv:
            if zz and zz[-1][2] == p[2]:
                if (p[2] == "H" and p[1] >= zz[-1][1]) or (p[2] == "L" and p[1] <= zz[-1][1]):
                    zz[-1] = p
            else:
                zz.append(p)
        zz = zz[-5:]
        letters = "ABCDE"
        for j, (p, v, kind) in enumerate(zz):
            markers.append(dict(time=times[p], position="aboveBar" if kind == "H" else "belowBar", color="#60a5fa",
                                shape="circle", text=letters[j]))
        if len(zz) >= 2:
            lines.append(dict(id="zigzag", kind="zigzag", label="最近波段", color="#60a5fa", width=1, style=0,
                              points=[dict(time=times[p], value=_r(v)) for p, v, _ in zz] + [dict(time=times[T], value=_r(c[T]))]))
        # trendlines: last two lower highs / lower lows
        hs = [(p, v) for p, v, cp in confirmed_pivots(h, k, "high") if cp <= T]
        ls = [(p, v) for p, v, cp in confirmed_pivots(l, k, "low") if cp <= T]

        def tline(pts, label, color, up):
            for a in range(len(pts) - 1, 0, -1):
                (pa, va), (pb, vb) = pts[a - 1], pts[a]
                if (vb < va) != up and pb - pa >= 5:
                    slope = (vb - va) / (pb - pa)
                    lines.append(dict(id=label, kind="trend", label=label, color=color, width=1, style=0,
                                      points=[dict(time=all_times[pa], value=_r(va)),
                                              dict(time=all_times[last_ext], value=_r(va + slope * (last_ext - pa)))]))
                    return
        if len(hs) >= 2:
            down = hs[-1][1] < hs[-2][1]
            tline(hs[-6:], "下降压力线" if down else "上升压力线", "#f87171", not down)
        if len(ls) >= 2:
            down = ls[-1][1] < ls[-2][1]
            tline(ls[-6:], "下降支撑线" if down else "上升支撑线", "#34d399", not down)
        # support / pressure with touch counts
        px = c[T]
        window = max(0, T - 250)
        allp = [v for p, v, cp in confirmed_pivots(h, 3, "high") if cp <= T and p >= window] + \
               [v for p, v, cp in confirmed_pivots(l, 3, "low") if cp <= T and p >= window]

        def touches(level):
            return sum(1 for v in allp if abs(v / level - 1) <= 0.015)
        above = sorted([v for v in allp if v > px * 1.005])
        below = sorted([v for v in allp if v < px * 0.995], reverse=True)
        if above:
            lv = max(above[:3], key=touches)
            levels.append(dict(id="pressure", kind="pressure", label=f"压力·{touches(lv)}次", price=_r(lv), color="#f87171", style=2))
        if below:
            lv = max(below[:3], key=touches)
            levels.append(dict(id="support", kind="support", label=f"支撑·{touches(lv)}次", price=_r(lv), color="#34d399", style=2))
        n_struct = len([x for x in lines if x["kind"] in ("trend", "zigzag", "fan")]) + len([x for x in levels if x["kind"] in ("pressure", "support")])
        return dict(lines=lines, levels=levels, markers=markers, zones=zones, future=all_times[len(times):],
                    n_structure=n_struct, n_total=len(lines) + len(levels))

    # ------------------------------------------------------------------ plan
    def _plan(self, d, eng, ev, evb, evt, direction, holding, draw):
        px = float(d["close"].iloc[-1])
        rk = self.cfg.risk
        long = direction == "long"
        aw = ev.avwap if np.isfinite(ev.avwap) else None
        if aw is None and ev.pivot_price == ev.pivot_price:
            aw = ev.pivot_price * (1.02 if long else 0.98)
        if aw is None:
            aw = px
        zl, zh = aw * (1 - rk.add_tolerance), aw * (1 + rk.add_tolerance)
        mid = (zl + zh) / 2
        stop = ev.stop if np.isfinite(ev.stop) else (mid * 0.95 if long else mid * 1.05)
        tg = [x for x in ev.targets if np.isfinite(x)]
        if long:
            tg = sorted([x for x in tg if x > mid])
        else:
            tg = sorted([x for x in tg if x < mid], reverse=True)
        while len(tg) < 2:
            base = tg[-1] if tg else mid
            tg.append(base + (abs(mid - stop) * 1.5) * (1 if long else -1))
        risk = abs(mid - stop)
        rr = abs(tg[0] - mid) / risk if risk > 0 else None
        s, fired = ev.score, ev.fired
        opp = evt if long else evb
        # verdict
        if holding == "flat":
            if fired:
                verdict, tone = ("可以入场" if long else ("可以做空" if self.cfg.risk.allow_short else "逃顶信号成立，离场")), "go"
            elif s == 3 and ev.wave_ok:
                verdict, tone = "接近条件，等第四证", "wait"
            elif not ev.wave_ok:
                verdict, tone = "未形成有效波段，观望", "idle"
            else:
                verdict, tone = "四证不齐，一手别动", "idle"
        else:
            mine_long = holding == "long"
            danger = evt if mine_long else evb
            if danger.fired:
                verdict, tone = "四证逃顶，清仓离场" if mine_long else "四证见底，空单离场", "stop"
            elif danger.score >= self.cfg.top.reduce_score:
                verdict, tone = "三证已现，先减半仓", "warn"
            elif (px < stop) if mine_long else (px > stop):
                verdict, tone = "跌破止损，离场", "stop"
            else:
                verdict, tone = "继续持有，守住成本线", "hold"
        reasons = []
        side_name = "抄底" if long else "逃顶"
        for it, ok in zip(self._ev_dict(ev, eng)["items"], [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]):
            reasons.append(("√ " if ok else "× ") + it["name"])
        lv = draw["levels"]
        sl = "开空" if self.cfg.risk.allow_short else "离场"
        lv.append(dict(id="zone_hi", kind="zone", label="建仓上沿" if long else sl + "上沿", price=_r(zh), color="#22d3ee", style=1))
        lv.append(dict(id="zone_lo", kind="zone", label="建仓下沿" if long else sl + "下沿", price=_r(zl), color="#22d3ee", style=1))
        lv.append(dict(id="stop", kind="stop", label="止损", price=_r(stop), color="#ef4444", style=0))
        lv.append(dict(id="t1", kind="target", label="第一目标", price=_r(tg[0]), color="#10b981", style=0))
        lv.append(dict(id="t2", kind="target", label="第二目标", price=_r(tg[1]), color="#10b981", style=2))
        draw["zones"].append(dict(id="entry", label="建仓区" if long else sl + "区", lo=_r(zl), hi=_r(zh), color="rgba(34,211,238,0.12)"))
        draw["n_total"] += 5

        def dist(x):
            return _r((x / px - 1) * 100, 2)
        return dict(
            model=f"四证{side_name}", verdict=verdict, tone=tone, score=s, opposite_score=opp.score,
            price=_r(px), entry=[_r(zl), _r(zh)], entry_mid_dist=dist(mid), stop=_r(stop), stop_dist=dist(stop),
            targets=[_r(tg[0]), _r(tg[1])], target_dist=[dist(tg[0]), dist(tg[1])], rr=_r(rr, 2),
            position=("四证齐全先上半仓；回踩成本线不破再加半仓。到第一目标卖一半，止损上移到成本价，剩下的用 15% 移动止盈。"
                      if long else "四证逃顶：3/4 先减半仓，4/4 清仓；开了做空的话 4/4 反手开空，止损放在高点上方 3%。"),
            checklist=reasons,
        )

    # ------------------------------------------------------------------ text
    def _interpret(self, d, ev, evb, evt, direction, holding, plan, scores):
        long = direction == "long"
        parts = []
        if long:
            ok = [n for n, f in zip(["地量", "底背离", "跌速放缓", "放量站回成本线"],
                                    [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]) if f]
            miss = [n for n, f in zip(["地量", "底背离", "跌速放缓", "放量站回成本线"],
                                      [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]) if not f]
        else:
            ok = [n for n, f in zip(["天量/量价背离", "顶背离", "涨速衰竭", "跌破成本线"],
                                    [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]) if f]
            miss = [n for n, f in zip(["天量/量价背离", "顶背离", "涨速衰竭", "跌破成本线"],
                                      [ev.e1_volume, ev.e2_divergence, ev.e3_speed, ev.e4_cost]) if not f]
        if np.isfinite(ev.extreme_price) and np.isfinite(ev.pivot_price):
            mv = (1 - ev.pivot_price / ev.extreme_price) if long else (ev.pivot_price / ev.extreme_price - 1)
            parts.append(f"当前{'下跌' if long else '上涨'}波段从 {ev.extreme_price:,.2f} 到 {ev.pivot_price:,.2f}，幅度 {mv * 100:.1f}%。")
        if ev.fired:
            parts.append(("、".join(ok) + "，四项条件全部满足。") + ("价格进入建仓区，分批参与，跌破止损就离场。" if long else "按规则减仓或清仓，反弹到成本线上方再说。"))
        else:
            parts.append(f"已出现：{'、'.join(ok) if ok else '无'}；还差：{'、'.join(miss)}。四证不齐，一手别{'抄' if long else '动'}。")
        parts.append(f"综合评分 {scores['composite']}（{scores['bias']}），"
                     + "，".join(f"{i['name']} {i['score']:+d}" for i in scores["items"]) + "。")
        if plan.get("rr"):
            parts.append(f"按建仓区中值算，止损距现价 {plan['stop_dist']:+.2f}%，第一目标 {plan['target_dist'][0]:+.2f}%，盈亏比 {plan['rr']:.2f}:1。")
        other = evt if long else evb
        if other.score >= 3:
            parts.append(f"注意：反方向（{'逃顶' if long else '抄底'}）证据已有 {other.score}/4。")
        return "".join(parts)


def scan_one(df: pd.DataFrame, cfg: Config) -> dict:
    a = Analyzer(df, cfg).analyze()
    return dict(date=a["date"], price=a["price"], change_pct=a["change_pct"],
                bottom=a["evidence"]["bottom"]["score"], bottom_fired=a["evidence"]["bottom"]["fired"],
                top=a["evidence"]["top"]["score"], top_fired=a["evidence"]["top"]["fired"],
                composite=a["scores"]["composite"], bias=a["scores"]["bias"])


def bars_payload(df: pd.DataFrame) -> dict:
    m = macd(df["close"])
    times = [_ts(x) for x in df.index]
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ma = {n: df["close"].rolling(n).mean().to_numpy() for n in (5, 10, 20, 60)}
    vma5 = df["volume"].rolling(5).mean().to_numpy()
    vma10 = df["volume"].rolling(10).mean().to_numpy()
    return dict(
        future=future_times(df, 20),
        candles=[dict(time=t, open=_r(a, 6), high=_r(b, 6), low=_r(e, 6), close=_r(f, 6)) for t, a, b, e, f in zip(times, o, h, l, c)],
        volume=[dict(time=t, value=_r(x, 2), color="rgba(239,68,68,0.6)" if f >= a else "rgba(16,185,129,0.6)")
                for t, x, a, f in zip(times, v, o, c)],
        vma5=[dict(time=t, value=_r(x, 2)) for t, x in zip(times, vma5) if np.isfinite(x)],
        vma10=[dict(time=t, value=_r(x, 2)) for t, x in zip(times, vma10) if np.isfinite(x)],
        ma={str(n): [dict(time=t, value=_r(x)) for t, x in zip(times, arr) if np.isfinite(x)] for n, arr in ma.items()},
        dif=[dict(time=t, value=_r(x)) for t, x in zip(times, m["dif"])],
        dea=[dict(time=t, value=_r(x)) for t, x in zip(times, m["dea"])],
        hist=[dict(time=t, value=_r(x), color="#ef4444" if x >= 0 else "#10b981") for t, x in zip(times, m["hist"])],
    )
