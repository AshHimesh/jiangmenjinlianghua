# -*- coding: utf-8 -*-
"""
阶段 8 · 新浪 hq 报文定标工具（接入新数据源时先跑这个）

为什么需要它：新浪 hq 各类报文的**段数与顺序都不同**（`s_` 6 段、`rt_hk` 25 段、
`fx_` 18 段），且同类报文里有多个"看起来像价格"的字段。靠猜字段语义接进来的解析，
会静默地把昨收当现价、把最高价当现价 —— 而且界面照样显示数字，没人能一眼看出错。

本工具做两件事：
  1. 打印每个代码的**带下标**原始报文，肉眼确认哪段是什么；
  2. 对价格类字段做**恒等式交叉校验**：用日线序列与实时报文的
     「涨跌额 = 现价 − 昨收」「涨跌幅 = 涨跌额 / 昨收」把字段钉死。

用法：
    .venv\\Scripts\\python.exe tools\\verify_stage8_fields.py
结果写 tools/_stage8_fields.txt（UTF-8）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import src  # noqa: F401  —— 安装全局网络超时补丁

import requests

from src.fetcher import SINA_HEADERS

OUT = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


# 想新增数据源时，把对应的新浪代码加到这里
CODES = ["s_sh000001", "s_sh000300", "s_sz399006", "s_sh000688", "s_sh518880",
         "rt_hkHSI", "fx_susdcnh", "gb_ndx", "gb_inx", "DINIW"]

log("新浪 hq 报文定标（%s）" % __import__("pandas").Timestamp.now())
log("")
log("=" * 74)
log("一、原始报文（带字段下标）")
log("=" * 74)
r = requests.get("https://hq.sinajs.cn/list=" + ",".join(CODES), headers=SINA_HEADERS, timeout=15)
r.encoding = "gbk"
log("HTTP %s" % r.status_code)
log("")
for line in r.text.strip().split("\n"):
    if '="' not in line:
        continue
    code = line.split("=")[0].replace("var hq_str_", "").strip()
    fields = line.split('"')[1].split(",")
    log("=== %s （共 %d 段）===" % (code, len(fields)))
    for i, f in enumerate(fields):
        log("  [%2d] %s" % (i, f))
    log("")

log("")
log("=" * 74)
log("二、外汇报文恒等式校验（把「哪段是现价、哪段是涨跌幅」钉死）")
log("=" * 74)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def check_fx_identity(label, fields, price_idx, pct_idx, prev_idx, delta_idx):
    price, pct = _f(fields[price_idx]), _f(fields[pct_idx])
    prev, delta = _f(fields[prev_idx]), _f(fields[delta_idx])
    if None in (price, pct, prev, delta) or not prev:
        log("  %s：字段不是数字，无法校验" % label)
        return
    calc_delta = price - prev
    calc_pct = calc_delta / prev * 100
    log("  %s" % label)
    log("    假设：现价=[%d]、昨收=[%d]、涨跌额=[%d]、涨跌幅=[%d]" % (
        price_idx, prev_idx, delta_idx, pct_idx))
    log("    报文给的涨跌额 = %s，按假设算 = %.6f  → 差 %.6f" % (delta, calc_delta, abs(delta - calc_delta)))
    log("    报文给的涨跌幅 = %s，按假设算 = %.4f%% → 差 %.4f" % (pct, calc_pct, abs(pct - calc_pct)))
    ok = abs(delta - calc_delta) < 0.001 and abs(pct - calc_pct) < 0.02
    log("    → %s" % ("✅ 自洽，字段语义确认" if ok else "❌ 不自洽，换一组假设再试"))


def fx_report(symbol):
    url = "https://hq.sinajs.cn/list=" + symbol
    rr = requests.get(url, headers=SINA_HEADERS, timeout=15)
    rr.encoding = "gbk"
    fields = rr.text.split('"')[1].split(",")
    if len(fields) < 12:
        log("  %s：报文字段不足（%d），跳过" % (symbol, len(fields)))
        return
    # 依据 2026-09-18 实测：fx_ 报文 [8]现价 [3]昨收 [11]涨跌额 [10]涨跌幅
    check_fx_identity(symbol, fields, price_idx=8, pct_idx=10, prev_idx=3, delta_idx=11)


fx_report("fx_susdcnh")
fx_report("fx_susdcny")

log("")
log("=" * 74)
log("三、港股报文校验（rt_hk：涨跌额 = 现价 − 昨收）")
log("=" * 74)
rr = requests.get("https://hq.sinajs.cn/list=rt_hkHSI", headers=SINA_HEADERS, timeout=15)
rr.encoding = "gbk"
fields = rr.text.split('"')[1].split(",")
if len(fields) >= 9:
    price, prev, delta, pct = _f(fields[6]), _f(fields[3]), _f(fields[7]), _f(fields[8])
    if None not in (price, prev, delta, pct) and prev:
        calc_delta = price - prev
        calc_pct = calc_delta / prev * 100
        log("  rt_hkHSI：现价=[6]=%s 昨收=[3]=%s 涨跌额=[7]=%s 涨跌幅=[8]=%s" % (price, prev, delta, pct))
        log("    算得涨跌额 %.3f（报文 %s）｜算得涨跌幅 %.4f%%（报文 %s）" % (
            calc_delta, delta, calc_pct, pct))
        ok = abs(delta - calc_delta) < 0.01 and abs(pct - calc_pct) < 0.02
        log("    → %s" % ("✅ 自洽" if ok else "❌ 不自洽"))
else:
    log("  rt_hkHSI 报文字段不足（%d）" % len(fields))

out = os.path.join(ROOT, "tools", "_stage8_fields.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done -> %s" % out)
