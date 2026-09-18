# -*- coding: utf-8 -*-
"""
江门金量化 · 行情数据抓取

数据源（2026-09-18 阶段 8 重新逐一验证）：
  1. sina_index   —— 直连 hq.sinajs.cn s_ 接口     上证/沪深300/创业板指/科创50/黄金ETF
  2. sina_futures —— ak.futures_zh_spot()          螺纹钢/铁矿石/焦煤/玻璃/纯碱/甲醇/乙二醇/沪金/沪银
  3. sina_global  —— 直连 hq.sinajs.cn             纳斯达克100/标普500/美元指数
  4. sina_foreign —— ak.futures_foreign_commodity_realtime()  伦敦金/银、COMEX铜、WTI与布伦特原油
  5. sina_hk      —— 直连 hq.sinajs.cn rt_hk         恒生指数
  6. sina_fx      —— 直连 hq.sinajs.cn fx_           美元兑离岸人民币
  7. sge          —— ak.spot_quotations_sge()        上海金基准价（慢速源，见下）

慢速源（SLOW_SOURCES）
---------------------
上金所接口走 www.sge.com.cn，实测单次 0.4~2 秒，且数据本身是低频的基准价。
把它放进 2 秒循环会拖慢界面、也给对方站点压力，因此单独走 60 秒慢速通道。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import akshare as ak

from .symbols import GROUPS, SYMBOL_MAP

REFRESH_INTERVAL = 2      # 秒（满足 1-3 秒刷新要求）
SLOW_INTERVAL = 60        # 秒：慢速源（上金所）的刷新间隔

# 新浪行情接口需要 Referer，否则会被拒
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
}

# 数据来源中文标签（界面显示）
SOURCE_LABEL = {
    "sge": "上海黄金交易所",
}
DEFAULT_SOURCE_LABEL = "新浪财经 · 免费源"

# 上海金参照收盘价缓存（日线一天只变一次，没必要每轮都拉）
_sge_lock = threading.Lock()
_sge_prev = {}            # symbol -> (参照收盘价, 取数时间戳)
_SGE_PREV_TTL = 1800      # 30 分钟


def _float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _items_of(source):
    return [it for it in SYMBOL_MAP.values() if it["source"] == source]


def _sina_batch(codes):
    """一次请求批量取新浪 hq 数据，返回 {code: [字段...]}。"""
    import requests
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    r = requests.get(url, headers=SINA_HEADERS, timeout=10)
    r.encoding = "gbk"
    out = {}
    for line in r.text.strip().split("\n"):
        if '="' not in line:
            continue
        code = line.split("=")[0].replace("var hq_str_", "").strip()
        out[code] = line.split('"')[1].split(",")
    return out


def _source_of(name):
    item = SYMBOL_MAP.get(name)
    if not item:
        return DEFAULT_SOURCE_LABEL
    return SOURCE_LABEL.get(item["source"], DEFAULT_SOURCE_LABEL)


# ---------------- 各数据源抓取 ----------------

def fetch_sina_index():
    """国内指数与 ETF：直连新浪 s_ 接口，一次请求批量取。

    返回格式：名称, 最新价, 涨跌额, 涨跌幅, 成交量, 成交额
    """
    out = {}
    items = _items_of("sina_index")
    if not items:
        return out
    try:
        by_code = {"s_" + it["symbol"]: it["name"] for it in items}
        data = _sina_batch(list(by_code))
        for code, name in by_code.items():
            fields = data.get(code) or []
            if len(fields) < 4 or not fields[0]:
                continue
            out[name] = {"price": _float(fields[1]), "change": _float(fields[3])}
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
    name_map = {"纳斯达克100": "纳斯达克100", "标普500指数": "标普500"}
    try:
        data = _sina_batch([it["symbol"] for it in items])
        for code, fields in data.items():
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
    """外盘商品（金/银/铜/WTI原油/布伦特原油）：一次调用（新浪支持 list 批量）。"""
    out = {}
    # akshare 返回的「名称」到品种名的映射
    name_map = {"伦敦金": "现货黄金", "伦敦银": "现货白银", "COMEX铜": "铜",
                "NYMEX原油": "WTI原油", "布伦特原油": "布伦特原油"}
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


def fetch_sina_hk():
    """港股指数（恒生指数）：直连新浪 rt_hk 接口。

    字段（2026-09-18 实测，共 25 段）：
      [1]名称 [2]今开 [3]昨收 [4]最高 [5]最低 [6]现价 [7]涨跌额 [8]涨跌幅%
    校验：涨跌额 146.49 = 24750.781 - 24604.289，涨跌幅 0.60 = 146.49/24604.289，自洽。
    """
    out = {}
    items = _items_of("sina_hk")
    if not items:
        return out
    try:
        by_code = {it["symbol"]: it["name"] for it in items}
        data = _sina_batch(list(by_code))
        for code, fields in data.items():
            name = by_code.get(code)
            if not name or len(fields) < 9:
                continue
            price = _float(fields[6])
            if price <= 0:
                continue
            out[name] = {"price": price, "change": round(_float(fields[8]), 2)}
    except Exception:
        pass
    return out


def fetch_sina_fx():
    """外汇（美元兑离岸人民币）：直连新浪 fx_ 接口。

    字段（2026-09-18 实测，共 18 段）：
      [0]时间 [3]昨收 [6]最高 [7]最低 [8]现价 [9]名称 [10]涨跌幅%
    定标方法：取两次快照，用「涨跌额 = 现价 − 昨收」「涨跌幅 = 涨跌额 / 昨收」交叉验证，
    两次都自洽（6.698→-0.09%、6.6996→-0.06%），字段语义不是猜的。
    """
    out = {}
    items = _items_of("sina_fx")
    if not items:
        return out
    try:
        by_code = {it["symbol"]: it["name"] for it in items}
        data = _sina_batch(list(by_code))
        for code, fields in data.items():
            name = by_code.get(code)
            if not name or len(fields) < 11:
                continue
            price = _float(fields[8])
            if price <= 0:
                continue
            out[name] = {"price": price, "change": round(_float(fields[10]), 3)}
    except Exception:
        pass
    return out


def _sge_prev_close(symbol):
    """上海金参照收盘价（缓存 30 分钟）。

    口径说明：上金所只提供日频历史，没有"昨收"字段。这里取 spot_hist_sge
    （列 date, open, close, low, high）**最后一行的收盘价**作为参照：
      - 日盘时段：当日行还没生成，最后一行 = 上一交易日收盘 → 就是标准"昨收"
      - 夜盘时段：最后一行就是当日日盘收盘 → 涨跌幅表示"日盘收盘 → 夜盘现价"
    这个口径已写进 docs/02，不假装它是交易所给的昨收。
    """
    with _sge_lock:
        hit = _sge_prev.get(symbol)
        if hit and (time.time() - hit[1]) < _SGE_PREV_TTL:
            return hit[0]
    try:
        df = ak.spot_hist_sge(symbol=symbol)
        if df is None or len(df) == 0:
            return None
        ref = _float(df.iloc[-1]["close"])
    except Exception:
        return None
    if not ref:
        return None
    with _sge_lock:
        _sge_prev[symbol] = (ref, time.time())
    return ref


def fetch_sge():
    """上海金基准价（上金所，慢速源）。

    ak.spot_quotations_sge 返回 [品种, 时间, 现价, 更新时间]，现价即当前基准价快照。
    """
    out = {}
    for it in _items_of("sge"):
        try:
            sym = it["symbol"]
            df = ak.spot_quotations_sge(symbol=sym)
            if df is None or len(df) == 0:
                continue
            row = df[df["品种"].astype(str).str.strip() == sym]
            row = row.iloc[-1] if len(row) else df.iloc[-1]
            price = _float(row.get("现价"))
            if price <= 0:
                continue
            ref = _sge_prev_close(sym)
            change = round((price - ref) / ref * 100, 2) if ref else 0.0
            out[it["name"]] = {"price": price, "change": change}
        except Exception:
            out[it["name"]] = None
    return out


def fetch_all(slow=True):
    """并行抓取全部来源，合并为 {name: {price, change} 或 None}。

    :param slow: 是否同时抓取慢速源（上金所）。2 秒主循环传 False，
                 由 QuoteService 每 60 秒传一次 True。
    """
    funcs = [fetch_sina_index, fetch_sina_futures, fetch_sina_global,
             fetch_sina_foreign, fetch_sina_hk, fetch_sina_fx]
    if slow:
        funcs.append(fetch_sge)
    with ThreadPoolExecutor(max_workers=len(funcs)) as ex:
        results = list(ex.map(lambda f: f(), funcs))
    merged = {}
    for r in results:
        if isinstance(r, dict):
            merged.update(r)
    if slow:
        for name in SYMBOL_MAP:
            merged.setdefault(name, None)
    return merged


# ---------------- 后台刷新服务 ----------------

class QuoteService:
    """后台线程定时刷新行情，缓存最新结果供界面读取。

    快速源每 2 秒一轮；慢速源（上金所）每 60 秒一轮，不参与快速轮，
    因此不会拖慢界面，也不会把 2 秒节奏压给外部低频接口。
    """

    def __init__(self, interval=REFRESH_INTERVAL, slow_interval=SLOW_INTERVAL):
        self.interval = interval
        self.slow_interval = slow_interval
        self._cache = {}       # name -> {price, change, updated, stale, source}
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._last_error = None

    def start(self):
        self._thread.start()

    def _loop(self):
        last_slow = 0.0
        while True:
            now = time.time()
            due_slow = (now - last_slow) >= self.slow_interval
            self.refresh_once(slow=due_slow)
            if due_slow:
                last_slow = time.time()
            time.sleep(self.interval)

    def refresh_once(self, slow=True):
        try:
            quotes = fetch_all(slow=slow)
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
                    q["source"] = _source_of(name)
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
