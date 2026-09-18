# -*- coding: utf-8 -*-
"""
阶段 8 · 品种候选数据源实测（先验证再接入）

逐候选探测：实时行情 / 日线 / 分钟线，三类分别报告 OK / FAIL。
结果写 tools/_stage8_probe.txt（UTF-8），由人阅读后决定接入哪些、如实标注哪些不可得。

    .venv\\Scripts\\python.exe tools\\verify_stage8_sources.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src  # noqa: F401  —— 安装全局网络超时补丁，避免 akshare 内部请求永久阻塞

import akshare as ak
import pandas as pd
import requests

OUT = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


def brief(obj, n=110):
    if obj is None:
        return "(None)"
    if isinstance(obj, pd.DataFrame):
        if len(obj) == 0:
            return "空表"
        head = " | ".join(str(c) for c in obj.columns[:8])
        tail = obj.tail(1).to_string(index=False).replace("\n", " ")
        return "DataFrame %d 行; 列=[%s]; 末行=%s" % (len(obj), head, tail[:120])
    s = str(obj).replace("\n", " ")
    return s[:n]


def try_call(label, fn):
    try:
        log("  ✅ %-46s %s" % (label, brief(fn())))
        return True
    except Exception as e:
        log("  ❌ %-46s %r" % (label, e))
        return False


SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36",
}


def sina_hq(codes):
    """新浪 hq 接口批量取数，返回原始文本。"""
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(codes),
                     headers=SINA_HEADERS, timeout=10)
    r.encoding = "gbk"
    return r.text.strip()


log("阶段 8 · 品种数据源实测")
log("时间：%s" % pd.Timestamp.now())
log("akshare 版本：%s" % getattr(ak, "__version__", "?"))
log("")

# ==================== 1. 国内期货（新浪）====================
log("=" * 70)
log("1. 国内期货实时 / 日线 / 分钟（候选：沪金 AU0、沪银 AG0、铁矿石 I0、玻璃 FG0）")
log("=" * 70)
for sym in ["AU0", "AG0", "I0", "FG0"]:
    log("[%s]" % sym)
    try_call("实时 futures_zh_spot", lambda s=sym: ak.futures_zh_spot(symbol=s, market="CF", adjust="0"))
    try_call("日线 futures_zh_daily_sina", lambda s=sym: ak.futures_zh_daily_sina(symbol=s))
    try_call("分钟 futures_zh_minute_sina(60)", lambda s=sym: ak.futures_zh_minute_sina(symbol=s, period="60"))

# ==================== 2. 国内指数 / ETF（新浪）====================
log("")
log("=" * 70)
log("2. 指数与 ETF 实时（候选：沪深300 sh000300、创业板指 sz399006、黄金ETF sh518880）")
log("=" * 70)
try_call("hq 批量 s_sh000300,s_sz399006,s_sh518880",
         lambda: sina_hq(["s_sh000300", "s_sz399006", "s_sh518880"]))
try_call("hq 批量 完整行情 sh000300,sz399006,sh518880",
         lambda: sina_hq(["sh000300", "sz399006", "sh518880"]))
try_call("hq 上证指数对照 s_sh000001", lambda: sina_hq(["s_sh000001"]))

log("")
log("=" * 70)
log("3. 指数与 ETF 日线 / 分钟")
log("=" * 70)
try_call("日线 stock_zh_index_daily(sh000300)", lambda: ak.stock_zh_index_daily(symbol="sh000300"))
try_call("日线 stock_zh_index_daily(sz399006)", lambda: ak.stock_zh_index_daily(symbol="sz399006"))
try_call("分钟 stock_zh_a_minute(sh000300,60)",
         lambda: ak.stock_zh_a_minute(symbol="sh000300", period="60", adjust=""))
try_call("分钟 stock_zh_a_minute(sz399006,60)",
         lambda: ak.stock_zh_a_minute(symbol="sz399006", period="60", adjust=""))
log("  -- ETF 518880 --")
for fn_name, call in [
    ("fund_etf_hist_sina(sh518880)", lambda: ak.fund_etf_hist_sina(symbol="sh518880")),
    ("fund_etf_spot_em()", lambda: ak.fund_etf_spot_em()),
]:
    try_call(fn_name, call)

# ==================== 4. 港股指数 ====================
log("")
log("=" * 70)
log("4. 恒生指数（候选多种新浪/东财接口）")
log("=" * 70)
try_call("hq rt_hkHSI", lambda: sina_hq(["rt_hkHSI"]))
try_call("hq hkHSI", lambda: sina_hq(["hkHSI"]))
for fn_name, call in [
    ("stock_hk_index_spot_sina()", lambda: ak.stock_hk_index_spot_sina()),
    ("stock_hk_index_daily_sina(HSI)", lambda: ak.stock_hk_index_daily_sina(symbol="HSI")),
    ("stock_hk_index_daily_em(symbol=HSI)", lambda: ak.stock_hk_index_daily_em(symbol="HSI")),
    ("stock_hk_index_spot_em()", lambda: ak.stock_hk_index_spot_em()),
]:
    try_call(fn_name, call)

# ==================== 5. 外汇（离岸人民币）====================
log("")
log("=" * 70)
log("5. 美元兑离岸人民币 USDCNH")
log("=" * 70)
try_call("hq fx_susdcnh", lambda: sina_hq(["fx_susdcnh"]))
try_call("hq USDCNH", lambda: sina_hq(["USDCNH"]))
try_call("对照 fx_susdcny 在岸", lambda: sina_hq(["fx_susdcny"]))

# ==================== 6. 外盘（布伦特原油）====================
log("")
log("=" * 70)
log("6. 布伦特原油（候选 OIL / UKOIL）")
log("=" * 70)
try_call("futures_foreign_commodity_realtime([OIL])",
         lambda: ak.futures_foreign_commodity_realtime(symbol=["OIL"]))
try_call("futures_foreign_commodity_realtime([UKOIL])",
         lambda: ak.futures_foreign_commodity_realtime(symbol=["UKOIL"]))
try_call("对照 现有 CL(WTI)", lambda: ak.futures_foreign_commodity_realtime(symbol=["CL"]))
try_call("futures_foreign_hist(OIL)", lambda: ak.futures_foreign_hist(symbol="OIL"))
try_call("futures_foreign_hist(UKOIL)", lambda: ak.futures_foreign_hist(symbol="UKOIL"))

# ==================== 7. 上海金基准价（上金所）====================
log("")
log("=" * 70)
log("7. 上海金 Au99.99（上金所，akshare 可用函数清单）")
log("=" * 70)
sge_fns = [n for n in dir(ak) if "sge" in n or "gold" in n.lower() or "spot" in n]
log("  候选函数：%s" % ", ".join(sorted(sge_fns)))
for fn_name, call in [
    ("spot_golden_benchmark_sge()", lambda: ak.spot_golden_benchmark_sge()),
    ("spot_hist_sge(Au99.99)", lambda: ak.spot_hist_sge(symbol="Au99.99")),
    ("spot_quotations_sge(Au99.99)", lambda: ak.spot_quotations_sge(symbol="Au99.99")),
]:
    if hasattr(ak, fn_name.split("(")[0]):
        try_call(fn_name, call)
    else:
        log("  ⏭ %-46s 函数不存在" % fn_name)

# ==================== 8. 金十覆盖复核 ====================
log("")
log("=" * 70)
log("8. 金十可覆盖的候选（阶段 7 已实测，这里只做代码存在性复核）")
log("=" * 70)
try:
    from src.jin10 import JIN10_CODES
    for name, code in [("浙商积存金", "CZBJCJ"), ("布伦特原油", "UKOIL"), ("恒生指数", "HSI"),
                       ("沪深300", "000300"), ("创业板指", "399006"), ("美元/人民币", "USDCNH")]:
        log("  %-14s %-8s %s" % (name, code, "在表内 ✅" if code in JIN10_CODES else "不在表内 ❌"))
    log("  铁矿石/玻璃/沪金/沪银/黄金ETF 在金十表内：%s"
        % [c for c in ["I", "FG", "AU", "AG", "518880"] if c in JIN10_CODES] or "无")
except Exception as e:
    log("  金十表读取失败：%r" % e)
    log(traceback.format_exc())

out = os.path.join(ROOT, "tools", "_stage8_probe.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done -> %s" % out)
