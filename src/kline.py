# -*- coding: utf-8 -*-
"""
江门金量化 · K线数据服务

按品种获取多周期K线，统一列名，带缓存。

周期（按权重从高到低）：
    周线 W → 日线 D → 12小时 12H → 4小时 4H → 1小时 1H → 15分钟 15M → 5分钟 5M

数据源（均为新浪，2026-09-10 验证）：
    国内期货：futures_zh_daily_sina / futures_zh_minute_sina
    国内指数：stock_zh_index_daily / stock_zh_a_minute
    外盘商品：futures_foreign_hist（日线）+ 外盘分时接口（当日分钟）
    美股指数：index_us_stock_sina
    美元指数：新浪外汇日线接口
"""
import json
import re
import threading
import time

import akshare as ak
import pandas as pd
import requests

from .symbols import SYMBOL_MAP

# 缓存有效期（秒）
TTL_DAILY = 1800      # 日线及以上：30 分钟
TTL_INTRADAY = 300    # 分钟线：5 分钟

# 周期定义（顺序 = 权重从高到低）
PERIODS = ["W", "D", "12H", "4H", "1H", "15M", "5M"]
PERIOD_NAME = {
    "W": "周线", "D": "日线", "12H": "12小时", "4H": "4小时",
    "1H": "1小时", "15M": "15分钟", "5M": "5分钟",
}
PERIOD_WEIGHT = {"W": 7, "D": 6, "12H": 5, "4H": 4, "1H": 3, "15M": 2, "5M": 1}

STD_COLS = ["datetime", "open", "high", "low", "close", "volume"]

# 新浪外盘 gb_ 代码 -> 美股指数代码
US_INDEX_CODE = {"gb_ndx": ".NDX", "gb_inx": ".INX"}

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
}

_lock = threading.Lock()
_cache = {}   # (name, period) -> {"t": 时间戳, "df": DataFrame}


def _normalize(df, dt_col, keep_volume=True):
    """把不同来源的K线统一成 [datetime, open, high, low, close, volume]。"""
    if df is None or len(df) == 0:
        return None
    out = pd.DataFrame()
    out["datetime"] = pd.to_datetime(df[dt_col], errors="coerce")
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    if keep_volume and "volume" in df.columns:
        out["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    else:
        out["volume"] = 0
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out.sort_values("datetime").reset_index(drop=True)
    return out if len(out) else None


def _resample(df, rule):
    """按周期重采样（用于合成 4小时 / 12小时 / 周线）。"""
    if df is None or len(df) == 0:
        return None
    d = df.set_index("datetime")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = d.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["close"])
    out = out.reset_index()
    return out if len(out) else None


# ---------------- 日线获取 ----------------

def _fetch_diniw_daily():
    """美元指数日线（新浪外汇接口，1985 年至今）。"""
    url = ("https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
           "var%20_DINIW=/NewForexService.getDayKLine?symbol=DINIW")
    r = requests.get(url, headers=SINA_HEADERS, timeout=15)
    r.encoding = "gbk"
    m = re.search(r'var _DINIW=\("(.*?)"\)', r.text, re.S)
    if not m:
        return None
    rows = []
    for seg in m.group(1).split("|"):
        parts = seg.split(",")
        if len(parts) >= 5:
            # date, open, close, high, low
            rows.append({
                "date": parts[0], "open": parts[1], "close": parts[2],
                "high": parts[3], "low": parts[4],
            })
    return pd.DataFrame(rows) if rows else None


def fetch_daily(name):
    """获取品种日线（统一列名）。"""
    item = SYMBOL_MAP.get(name)
    if not item:
        return None
    src, sym = item["source"], item["symbol"]
    try:
        if src == "sina_futures":
            df = ak.futures_zh_daily_sina(symbol=sym)
            return _normalize(df, "date")
        if src == "sina_index":
            df = ak.stock_zh_index_daily(symbol=sym)
            return _normalize(df, "date")
        if src == "sina_foreign":
            df = ak.futures_foreign_hist(symbol=sym)
            return _normalize(df, "date")
        if src == "sina_global":
            if sym == "DINIW":
                df = _fetch_diniw_daily()
                return _normalize(df, "date")
            code = US_INDEX_CODE.get(sym)
            if code:
                df = ak.index_us_stock_sina(symbol=code)
                return _normalize(df, "date")
    except Exception:
        return None
    return None


# ---------------- 分钟线获取 ----------------

def _fetch_foreign_minline(symbol):
    """新浪外盘分时（当日 1 分钟）。返回 DataFrame[datetime, open/high/low/close]。"""
    url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_t=/"
           "GlobalFuturesService.getGlobalFuturesMinLine?symbol=" + symbol)
    r = requests.get(url, headers=SINA_HEADERS, timeout=15)
    r.encoding = "gbk"
    m = re.search(r"var _t=\((.*)\)", r.text, re.S)
    if not m:
        return None
    data = json.loads(m.group(1))
    rows = data.get("minLine_1d") or []
    pts = []
    for row in rows:
        try:
            # 首行 10 字段：[日期, 价, 交易所, '', 时间, 均价, 0, 0, 昨收, '日期 时间']
            # 后续行 6 字段：[时间, 价, 0, 0, 均价, '日期 时间']
            if len(row) >= 10:
                dt, price = row[9], float(row[1])
            elif len(row) >= 6:
                dt, price = row[5], float(row[1])
            else:
                continue
            pts.append({"datetime": dt, "price": price})
        except (ValueError, TypeError, IndexError):
            continue
    if not pts:
        return None
    df = pd.DataFrame(pts)
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime")
    # 由分时价合成 1 分钟K线
    df = df.set_index("datetime")
    bars = df["price"].resample("1min").agg(["first", "max", "min", "last"]).dropna()
    bars.columns = ["open", "high", "low", "close"]
    bars["volume"] = 0
    bars = bars.reset_index()
    return bars if len(bars) else None


def fetch_minute(name, period):
    """获取分钟线。period ∈ {1H, 15M, 5M}（4H/12H 由 1 小时线合成）。"""
    item = SYMBOL_MAP.get(name)
    if not item:
        return None
    src, sym = item["source"], item["symbol"]
    sina_period = {"1H": "60", "15M": "15", "5M": "5"}.get(period)
    if sina_period is None:
        return None
    try:
        if src == "sina_futures":
            df = ak.futures_zh_minute_sina(symbol=sym, period=sina_period)
            return _normalize(df, "datetime")
        if src == "sina_index":
            df = ak.stock_zh_a_minute(symbol=sym, period=sina_period, adjust="")
            return _normalize(df, "day")
        if src in ("sina_foreign", "sina_global"):
            base = _fetch_foreign_minline(sym) if src == "sina_foreign" else None
            if base is None:
                return None
            rule = {"1H": "60min", "15M": "15min", "5M": "5min"}[period]
            return _resample(base, rule)
    except Exception:
        return None
    return None


# ---------------- 对外接口（带缓存） ----------------

def get_kline(name, period, force=False):
    """
    获取指定品种、指定周期的K线。

    :param period: W / D / 12H / 4H / 1H / 15M / 5M
    :return: DataFrame[datetime, open, high, low, close, volume] 或 None
    """
    if period not in PERIODS:
        return None
    key = (name, period)
    ttl = TTL_DAILY if period in ("W", "D") else TTL_INTRADAY

    with _lock:
        hit = _cache.get(key)
        if hit and not force and (time.time() - hit["t"]) < ttl:
            return hit["df"]

    df = None
    try:
        if period == "D":
            df = fetch_daily(name)
        elif period == "W":
            df = _resample(fetch_daily(name), "W")
        elif period in ("1H", "15M", "5M"):
            df = fetch_minute(name, period)
        elif period == "4H":
            df = _resample(fetch_minute(name, "1H"), "4h")
        elif period == "12H":
            df = _resample(fetch_minute(name, "1H"), "12h")
    except Exception:
        df = None

    with _lock:
        if df is not None:
            _cache[key] = {"t": time.time(), "df": df}
        else:
            # 失败时保留旧缓存（若有）
            old = _cache.get(key)
            if old:
                return old["df"]
    return df


def available_periods(name):
    """返回该品种实际可用的周期列表（按权重从高到低）。"""
    out = []
    for p in PERIODS:
        try:
            df = get_kline(name, p)
            if df is not None and len(df) >= 5:
                out.append(p)
        except Exception:
            continue
    return out
