# -*- coding: utf-8 -*-
"""
江门金量化 · 行情数据抓取

数据源（已逐一验证，2026-09-10）：
  1. sina_index   —— 直连 hq.sinajs.cn s_ 接口    上证指数/科创50
  2. sina_futures —— ak.futures_zh_spot()           螺纹钢/焦煤/甲醇/乙二醇/纯碱
  3. sina_global  —— 直连 hq.sinajs.cn              纳斯达克100/标普500/美元指数
  4. sina_foreign —— ak.futures_foreign_commodity_realtime()  伦敦金/银、COMEX铜、NYMEX原油
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import akshare as ak

from .symbols import GROUPS, SYMBOL_MAP

REFRESH_INTERVAL = 2  # 秒（满足 1-3 秒刷新要求）

# 新浪行情接口需要 Referer，否则会被拒
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
}


def _float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _items_of(source):
    return [it for it in SYMBOL_MAP.values() if it["source"] == source]


# ---------------- 各数据源抓取 ----------------

def fetch_sina_index():
    """国内指数：直连新浪，一次请求取 sh000001 / sh000688。

    返回格式：名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额
    """
    out = {}
    try:
        import requests
        url = "https://hq.sinajs.cn/list=s_sh000001,s_sh000688"
        r = requests.get(url, headers=SINA_HEADERS, timeout=10)
        r.encoding = "gbk"
        for line in r.text.strip().split("\n"):
            if '="' not in line:
                continue
            code = line.split("=")[0].replace("var hq_str_", "").strip()
            fields = line.split('"')[1].split(",")
            if not fields or not fields[0]:
                continue
            if "sh000001" in code:
                out["上证指数"] = {"price": _float(fields[1]), "change": _float(fields[3])}
            elif "sh000688" in code:
                out["科创50"] = {"price": _float(fields[1]), "change": _float(fields[3])}
    except Exception:
        pass
    return out


def fetch_sina_futures():
    """国内期货：每个品种一次调用，涨跌幅按昨结算价计算。"""
    out = {}
    for it in _items_of("sina_futures"):
        try:
            df = ak.futures_zh_spot(symbol=it["symbol"], market="CF", adjust="0")
            row = df.iloc[0]
            price = _float(row.get("current_price"))
            settle = _float(row.get("last_settle_price"))
            change = (price - settle) / settle * 100 if settle else 0.0
            out[it["name"]] = {"price": price, "change": round(change, 2)}
        except Exception:
            out[it["name"]] = None
    return out


def fetch_sina_global():
    """国际指数（纳斯达克100/标普500/美元指数）：直连新浪，一次调用。

    gb_ 格式：名称, 最新价, 涨跌幅, 时间, 涨跌额, 今开, 最高, 最低, ...
    DINIW 格式：时间, 最新价, 买价, 卖价, 成交量, 昨收, 最高, 最低, 今开, 名称, 日期
    """
    out = {}
    items = _items_of("sina_global")
    # 新浪返回名称 -> 品种名
    name_map = {"纳斯达克100": "纳斯达克100", "标普500指数": "标普500"}
    try:
        import requests
        codes = [it["symbol"] for it in items]
        url = "https://hq.sinajs.cn/list=" + ",".join(codes)
        r = requests.get(url, headers=SINA_HEADERS, timeout=10)
        r.encoding = "gbk"
        for line in r.text.strip().split("\n"):
            if '="' not in line:
                continue
            code = line.split("=")[0].replace("var hq_str_", "").strip()
            val = line.split('"')[1]
            fields = val.split(",")
            if not fields or not fields[0]:
                continue
            if code.startswith("gb_"):
                raw_name = fields[0]
                if raw_name in name_map:
                    out[name_map[raw_name]] = {
                        "price": _float(fields[1]),
                        "change": _float(fields[2]),
                    }
            elif code == "DINIW":
                price = _float(fields[1])
                prev = _float(fields[3])
                change = (price - prev) / prev * 100 if prev else 0.0
                out["美元指数"] = {"price": price, "change": round(change, 2)}
    except Exception:
        pass
    return out


def fetch_sina_foreign():
    """现货黄金/白银/铜/原油：一次调用（新浪支持 list 批量）。"""
    out = {}
    # akshare 返回的「名称」到品种名的映射
    name_map = {"伦敦金": "现货黄金", "伦敦银": "现货白银", "COMEX铜": "铜", "NYMEX原油": "WTI原油"}
    items = _items_of("sina_foreign")
    try:
        symbols = [it["symbol"] for it in items]
        df = ak.futures_foreign_commodity_realtime(symbol=symbols)
        for _, row in df.iterrows():
            raw_name = str(row.get("名称", ""))
            if raw_name in name_map:
                target = name_map[raw_name]
                it = SYMBOL_MAP[target]
                out[target] = {
                    "price": _float(row.get("最新价")) * it["scale"],
                    "change": _float(row.get("涨跌幅")),
                }
    except Exception:
        pass
    return out


def fetch_all():
    """并行抓取全部来源，合并为 {name: {price, change} 或 None}。"""
    funcs = [fetch_sina_index, fetch_sina_futures, fetch_sina_global, fetch_sina_foreign]
    with ThreadPoolExecutor(max_workers=len(funcs)) as ex:
        results = list(ex.map(lambda f: f(), funcs))
    merged = {}
    for r in results:
        if isinstance(r, dict):
            merged.update(r)
    for name in SYMBOL_MAP:
        merged.setdefault(name, None)
    return merged


# ---------------- 后台刷新服务 ----------------

class QuoteService:
    """后台线程定时刷新行情，缓存最新结果供界面读取。"""

    def __init__(self, interval=REFRESH_INTERVAL):
        self.interval = interval
        self._cache = {}       # name -> {price, change, updated, stale}
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._last_error = None

    def start(self):
        self._thread.start()

    def _loop(self):
        while True:
            self.refresh_once()
            time.sleep(self.interval)

    def refresh_once(self):
        try:
            quotes = fetch_all()
            now = datetime.now().strftime("%H:%M:%S")
            with self._lock:
                for name, q in quotes.items():
                    if q is None:
                        # 抓取失败：保留旧值并标记延迟
                        if name in self._cache:
                            self._cache[name]["stale"] = True
                        continue
                    q["updated"] = now
                    q["stale"] = False
                    self._cache[name] = q
            self._last_error = None
        except Exception as e:
            self._last_error = str(e)

    def get_quotes(self):
        """返回当前缓存快照（供 js_api 调用）。"""
        with self._lock:
            snapshot = {}
            for name, q in self._cache.items():
                snapshot[name] = dict(q)
            return snapshot

    def get_symbols(self):
        """返回品种分组列表（含单位，不含价格）。"""
        result = []
        for g in GROUPS:
            result.append({
                "name": g["name"],
                "items": [{"name": it["name"], "unit": it["unit"]} for it in g["items"]],
            })
        return result
