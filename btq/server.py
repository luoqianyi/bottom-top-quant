"""Web terminal: FastAPI backend + static front-end (TradingView Lightweight Charts).

    python -m btq serve            # http://127.0.0.1:8000
"""
from __future__ import annotations
import json, os, time, threading, urllib.request
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import data
from .config import Config
from .analysis import Analyzer, bars_payload, resample, scan_one, _ts, _r
from .backtest import Backtester

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
REPO = ROOT.parent
CONFIGS = REPO / "configs"
WATCHLIST = REPO / "watchlist.txt"

PRESETS = {
    "strict": dict(name="四证抄底 · 严格版", file="default.yaml", desc="完全按视频参数：地量 60 日、放量 2.5 倍、扇形 0.5 线、止损低点下 3%。信号少、质量高。"),
    "relaxed": dict(name="四证抄底 · 宽松版", file="relaxed.yaml", desc="放量 1.8 倍、波段 15%。适合指数、大盘股、黄金。"),
    "crypto": dict(name="四证多空 · 加密/期货", file="crypto_long_short.yaml", desc="4/4 逃顶后反手做空，波段要求更大。"),
}

_cache: dict = {}
_lock = threading.Lock()


def _default(o):
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o.date())
    return str(o)


def J(obj):
    txt = json.dumps(obj, default=_default, ensure_ascii=False, allow_nan=False) if False else json.dumps(obj, default=_default, ensure_ascii=False).replace("NaN", "null").replace("Infinity", "null")
    return JSONResponse(json.loads(txt))


def parse_symbol(sym: str):
    sym = sym.strip()
    for p in ("yahoo", "akshare", "ccxt", "csv", "sina", "csindex", "hksina", "sge", "sinafut"):
        if sym.startswith(p + ":"):
            return sym[len(p) + 1:], p
    return sym, "yahoo"


def get_df(symbol: str, tf: str = "1d", ttl: int = 600) -> pd.DataFrame:
    key = (symbol, tf)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    s, src = parse_symbol(symbol)
    try:
        df = data.load(s, src, None, None)
    except Exception as ex:
        raise HTTPException(400, f"数据获取失败：{ex}")
    if df is None or len(df) < 80:
        raise HTTPException(400, f"{symbol} 没有足够的数据（至少 80 根 K 线）")
    df = resample(df, tf)
    with _lock:
        _cache[key] = (time.time(), df)
    return df


def make_cfg(preset: str = "strict", overrides: dict | None = None) -> Config:
    p = PRESETS.get(preset, PRESETS["strict"])
    path = CONFIGS / p["file"]
    cfg = Config.load(str(path) if path.exists() else None)
    for sec, kv in (overrides or {}).items():
        obj = getattr(cfg, sec, None)
        if obj is None:
            continue
        for k, v in (kv or {}).items():
            if hasattr(obj, k) and v is not None and v != "":
                cur = getattr(obj, k)
                setattr(obj, k, type(cur)(v) if not isinstance(cur, bool) else (v in (True, "true", "1", 1)))
    return cfg


def t_of(df, date):
    if not date:
        return None
    return int(df.index.searchsorted(pd.Timestamp(date), side="right") - 1)


class Req(BaseModel):
    symbol: str = "BTC-USD"
    tf: str = "1d"
    preset: str = "strict"
    overrides: dict | None = None
    date: str | None = None
    direction: str = "long"
    holding: str = "flat"
    period: str = "short"


class ScanReq(BaseModel):
    symbols: list[str] | None = None
    preset: str = "relaxed"
    tf: str = "1d"


class ChatReq(Req):
    question: str = ""
    history: list | None = None


class AlertReq(ScanReq):
    webhook: str = ""
    min_score: int = 3


class WatchReq(BaseModel):
    symbols: list[str]


app = FastAPI(title="btq 四证量化终端")
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "overview.html")


@app.get("/chart")
def chart_page():
    return FileResponse(WEB / "chart.html")


_overview = {}


@app.get("/api/overview")
def overview(preset: str = "relaxed", refresh: bool = False):
    from .overview import load_markets, build
    hit = _overview.get(preset)
    if hit and not refresh and time.time() - hit[0] < 1200:
        return J(hit[1])
    cfg = make_cfg(preset)
    res = build(load_markets(REPO / "markets.yaml"), lambda s: get_df(s), cfg)
    res["model"] = PRESETS.get(preset, PRESETS["relaxed"])["name"]
    res["preset"] = preset
    _overview[preset] = (time.time(), res)
    return J(res)


@app.get("/api/presets")
def presets():
    out = []
    for k, p in PRESETS.items():
        cfg = make_cfg(k)
        out.append(dict(key=k, name=p["name"], desc=p["desc"], params=dict(signal=asdict(cfg.signal), top=asdict(cfg.top), risk=asdict(cfg.risk), cost=asdict(cfg.cost))))
    return out


@app.get("/api/bars")
def bars(symbol: str, tf: str = "1d", date: str | None = None):
    df = get_df(symbol, tf)
    t = t_of(df, date)
    d = df if t is None else df.iloc[: t + 1]
    out = bars_payload(d)
    out.update(symbol=symbol, tf=tf, n=len(df), first=str(df.index[0].date()), last=str(df.index[-1].date()))
    return J(out)


@app.post("/api/analyze")
def analyze(r: Req):
    df = get_df(r.symbol, r.tf)
    cfg = make_cfg(r.preset, r.overrides)
    a = Analyzer(df, cfg).analyze(t_of(df, r.date), r.direction, r.holding, r.period)
    a["symbol"] = r.symbol
    a["model"] = PRESETS.get(r.preset, PRESETS["strict"])["name"]
    if os.environ.get("BTQ_LLM_API_KEY") and r.date is None:
        try:
            a["interpretation_ai"] = llm(_llm_prompt(a, "请用 120 字以内给出这张图的深度解读：结构、四证进度、风险点、下一步该观察什么。"))
        except Exception as ex:
            a["llm_error"] = str(ex)
    return J(a)


@app.post("/api/backtest")
def backtest(r: Req):
    df = get_df(r.symbol, r.tf)
    cfg = make_cfg(r.preset, r.overrides)
    bt = Backtester(df, cfg).run()
    m = bt.metrics()
    eq = bt.equity
    bh = df["close"] / df["close"].iloc[0] * eq.iloc[0]
    ep = bt.episodes()
    fills = bt.trades()
    markers = []

    def short(reason, buy):
        r = str(reason)
        for k, v in (("加仓", "加仓"), ("抄底", "抄底"), ("开空", "开空"), ("止损", "止损"), ("成本线", "破线"), ("目标", "止盈"),
                     ("移动", "移止"), ("逃顶", "逃顶"), ("回补", "回补")):
            if k in r:
                return v
        return "买" if buy else "卖"
    for _, f in fills.iterrows():
        buy = f["shares"] > 0
        markers.append(dict(time=_ts(f["date"]), position="belowBar" if buy else "aboveBar",
                            color="#ef4444" if buy else "#10b981", shape="arrowUp" if buy else "arrowDown",
                            text=short(f["reason"], buy)))
    step = max(1, len(eq) // 1500)
    return J(dict(
        metrics=m, model=PRESETS.get(r.preset, PRESETS["strict"])["name"],
        equity=[dict(time=_ts(i), value=_r(v, 2)) for i, v in list(eq.items())[::step]],
        buyhold=[dict(time=_ts(i), value=_r(v, 2)) for i, v in list(bh.items())[::step]],
        episodes=json.loads(ep.to_json(orient="records", date_format="iso", force_ascii=False)),
        fills=json.loads(fills.to_json(orient="records", date_format="iso", force_ascii=False)) if len(fills) else [],
        markers=markers,
    ))


def _read_watchlist():
    if not WATCHLIST.exists():
        return ["BTC-USD", "NVDA", "AAPL", "600519.SS", "300750.SZ", "0700.HK"]
    out = []
    for line in WATCHLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


@app.get("/api/watchlist")
def watchlist():
    return _read_watchlist()


@app.post("/api/watchlist")
def save_watchlist(w: WatchReq):
    WATCHLIST.write_text("# 自选（一行一个，支持 akshare: / ccxt: / csv: 前缀）\n" + "\n".join(w.symbols) + "\n", encoding="utf-8")
    return dict(ok=True, symbols=w.symbols)


@app.post("/api/scan")
def scan(r: ScanReq):
    cfg = make_cfg(r.preset)
    rows = []
    for s in r.symbols or _read_watchlist():
        try:
            rows.append(json.loads(json.dumps(dict(symbol=s, **scan_one(get_df(s, r.tf), cfg)), default=_default)))
        except HTTPException as ex:
            rows.append(dict(symbol=s, error=ex.detail))
        except Exception as ex:
            rows.append(dict(symbol=s, error=str(ex)))
    return rows


@app.post("/api/alert")
def alert(r: AlertReq):
    rows = scan(r)
    hits = [x for x in rows if not x.get("error") and (x["bottom"] >= r.min_score or x["top"] >= r.min_score)]
    lines = [f"[{'抄底' if x['bottom'] >= x['top'] else '逃顶'}] {x['symbol']} 抄底 {x['bottom']}/4 · 逃顶 {x['top']}/4 · 收盘 {x['price']}" for x in hits]
    sent = False
    if r.webhook and lines:
        text = "四证量化提醒\n" + "\n".join(lines)
        from .notify import post
        post(r.webhook, text)
        sent = True
    return dict(hits=lines, sent=sent)


# ---------------------------------------------------------------- chat
def llm(prompt: str, history: list | None = None) -> str:
    """Any OpenAI-compatible endpoint: BTQ_LLM_BASE_URL (default OpenAI), BTQ_LLM_API_KEY, BTQ_LLM_MODEL."""
    base = os.environ.get("BTQ_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("BTQ_LLM_MODEL", "gpt-4o-mini")
    msgs = [{"role": "system", "content": "你是一个技术分析助手，只基于给定的规则信号和数据回答，简洁、具体，用中文。不给投资建议，必要时提醒风险。"}]
    msgs += (history or [])[-6:]
    msgs.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model, "messages": msgs, "temperature": 0.3}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["BTQ_LLM_API_KEY"]})
    res = json.loads(urllib.request.urlopen(req, timeout=40).read())
    return res["choices"][0]["message"]["content"].strip()


def _llm_prompt(a: dict, q: str) -> str:
    slim = {k: a[k] for k in ("symbol", "date", "price", "evidence", "scores", "plan", "interpretation")}
    return "图表分析数据（JSON）：\n" + json.dumps(slim, ensure_ascii=False, default=str) + "\n\n问题：" + q


def rule_answer(a: dict, q: str) -> str:
    p, ev, sc = a["plan"], a["evidence"], a["scores"]
    b, t = ev["bottom"], ev["top"]

    def items(e):
        return "；".join(("√" if i["ok"] else "×") + i["name"] + (f"（{i['detail']}）" if i["detail"] else "") for i in e["items"])
    ql = q.lower()
    if any(k in q for k in ("止损", "风险", "亏")):
        return f"止损 {p['stop']:,}（距现价 {p['stop_dist']:+.2f}%）。规则是波段最低点下方 3%；收盘跌回成本线下方超过 1% 也算判断错了，离场。"
    if any(k in q for k in ("目标", "止盈", "卖")):
        return f"第一目标 {p['targets'][0]:,}（{p['target_dist'][0]:+.2f}%），第二目标 {p['targets'][1]:,}（{p['target_dist'][1]:+.2f}%），盈亏比 {p['rr']}:1。到第一目标先卖一半，止损上移到成本价，剩下用 15% 移动止盈。"
    if any(k in q for k in ("仓", "加", "买多少")):
        return p["position"]
    if any(k in q for k in ("逃顶", "顶")):
        return f"逃顶证据 {t['score']}/4：{items(t)}。3/4 先减半仓，4/4 清仓。"
    if any(k in q for k in ("抄底", "底", "四证", "条件", "为什么", "能不能", "可以")):
        return f"抄底证据 {b['score']}/4：{items(b)}。结论：{p['verdict']}。"
    if any(k in q for k in ("评分", "分数", "趋势", "动量", "量能", "波动", "结构")):
        return f"综合评分 {sc['composite']}（{sc['bias']}）：" + "；".join(f"{i['name']} {i['score']:+d}，{i['desc']}" for i in sc["items"]) + "。"
    if "成本线" in q or "vwap" in ql:
        return f"成本线是从{'地量' if a['direction'] == 'long' else '天量'}第一天开始累计的锚定 VWAP，现在是 {b['avwap'] if a['direction'] == 'long' else t['avwap']}。放量站回才算翻身。"
    return a["interpretation"]


@app.post("/api/chat")
def chat(r: ChatReq):
    df = get_df(r.symbol, r.tf)
    cfg = make_cfg(r.preset, r.overrides)
    a = Analyzer(df, cfg).analyze(t_of(df, r.date), r.direction, r.holding, r.period)
    a["symbol"] = r.symbol
    if os.environ.get("BTQ_LLM_API_KEY"):
        try:
            return dict(answer=llm(_llm_prompt(a, r.question), r.history), engine="llm")
        except Exception as ex:
            return dict(answer=rule_answer(a, r.question) + f"\n（LLM 调用失败，已用规则引擎回答：{ex}）", engine="rules")
    return dict(answer=rule_answer(a, r.question), engine="rules")


def serve(host="127.0.0.1", port=8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
