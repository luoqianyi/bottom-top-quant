"""Market data adapters. Output: DataFrame indexed by date with open/high/low/close/volume.

Sources
  yahoo   (default) : any market Yahoo covers — A股 600519.SS / 000001.SZ, 港股 0700.HK, 美股 AAPL,
                      指数 000001.SS ^GSPC, 加密 BTC-USD, 期货 GC=F, 外汇 USDCNY=X
  akshare (optional): A股日线，代码如 600519 / sh000001  (pip install akshare)
  ccxt    (optional): 交易所加密货币，symbol 如 binance:BTC/USDT  (pip install ccxt)
  csv               : path to a csv with date,open,high,low,close,volume
  sina    (akshare) : A股/北证指数 新浪日线，如 sina:sz399006 sina:sh000300 sina:bj899050（带成交量）
  csindex (akshare) : 中证指数官网，如 csindex:932000（中证2000）csindex:000985（中证全指）
  hksina  (akshare) : 港股指数 新浪，如 hksina:HSI hksina:HSTECH hksina:HSCEI
  sge     (akshare) : 上海金交所现货，如 sge:Au99.99（没有成交量）
  sinafut (akshare) : 新浪外盘期货，如 sinafut:CHA50CFD（富时A50期指）
"""
from __future__ import annotations
import warnings
import pandas as pd
warnings.filterwarnings("ignore")

COLS = ["open", "high", "low", "close", "volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}")
    df = df[COLS].astype(float).dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "date"
    return df


def load_yahoo(symbol: str, start=None, end=None, interval="1d") -> pd.DataFrame:
    import yfinance as yf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start or "2010-01-01", end=end, interval=interval, progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"no data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return _clean(df)


def load_akshare(symbol: str, start=None, end=None) -> pd.DataFrame:
    import akshare as ak
    s = (start or "1990-01-01").replace("-", "")
    e = (end or "2100-01-01").replace("-", "")
    if symbol.startswith(("sh", "sz")):
        df = ak.stock_zh_index_daily(symbol=symbol)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").loc[pd.to_datetime(s):pd.to_datetime(e)]
    else:
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=s, end_date=e, adjust="qfq")
        df = df.rename(columns={"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return _clean(df)


def load_ccxt(symbol: str, start=None, end=None, timeframe="1d") -> pd.DataFrame:
    import ccxt
    ex_name, pair = symbol.split(":", 1)
    ex = getattr(ccxt, ex_name)()
    since = ex.parse8601((start or "2017-01-01") + "T00:00:00Z")
    rows = []
    while True:
        batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("date").drop(columns="ts")
    if end:
        df = df.loc[:pd.to_datetime(end)]
    return _clean(df)


def load_csv(path: str, start=None, end=None) -> pd.DataFrame:
    df = pd.read_csv(path)
    dcol = [c for c in df.columns if str(c).lower() in ("date", "datetime", "time", "日期")][0]
    df[dcol] = pd.to_datetime(df[dcol])
    df = df.set_index(dcol)
    if start:
        df = df.loc[pd.to_datetime(start):]
    if end:
        df = df.loc[:pd.to_datetime(end)]
    return _clean(df)


def _cut(df, start, end):
    df.index = pd.to_datetime(df.index)
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def load_sina(symbol, start=None, end=None):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol).set_index("date")
    return _clean(_cut(df, start, end))


def load_csindex(symbol, start=None, end=None):
    import akshare as ak
    s = (start or "2010-01-01").replace("-", "")
    e = (end or "2100-01-01").replace("-", "")
    df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=s, end_date=e)
    df = df.rename(columns={"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}).set_index("date")
    return _clean(_cut(df, start, end))


def load_hksina(symbol, start=None, end=None):
    import akshare as ak
    df = ak.stock_hk_index_daily_sina(symbol=symbol).set_index("date")
    return _clean(_cut(df, start, end))


def load_sge(symbol, start=None, end=None):
    import akshare as ak
    df = ak.spot_hist_sge(symbol=symbol).set_index("date")
    df["volume"] = 0.0
    return _clean(_cut(df, start, end))


def load_sinafut(symbol, start=None, end=None):
    import akshare as ak
    df = ak.futures_foreign_hist(symbol=symbol).set_index("date")
    return _clean(_cut(df, start, end))


EXTRA = {"sina": load_sina, "csindex": load_csindex, "hksina": load_hksina, "sge": load_sge, "sinafut": load_sinafut}


def load(symbol: str, source: str = "yahoo", start=None, end=None) -> pd.DataFrame:
    if source in EXTRA:
        return EXTRA[source](symbol, start, end)
    if source == "yahoo":
        return load_yahoo(symbol, start, end)
    if source == "akshare":
        return load_akshare(symbol, start, end)
    if source == "ccxt":
        return load_ccxt(symbol, start, end)
    if source == "csv":
        return load_csv(symbol, start, end)
    raise ValueError(f"unknown source {source}")
