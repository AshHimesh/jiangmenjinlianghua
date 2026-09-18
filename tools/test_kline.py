# -*- coding: utf-8 -*-
"""测试 K线服务：各品种 × 各周期。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.kline import PERIODS, PERIOD_NAME, get_kline

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


SAMPLES = ["现货黄金", "WTI原油", "纳斯达克100", "美元指数", "螺纹钢", "上证指数", "科创50", "纯碱"]

for name in SAMPLES:
    log("=== %s ===" % name)
    for p in PERIODS:
        try:
            df = get_kline(name, p)
            if df is None or len(df) == 0:
                log("  %-7s ❌ 无数据" % PERIOD_NAME[p])
                continue
            first = df.iloc[0]["datetime"]
            last = df.iloc[-1]["datetime"]
            lastclose = df.iloc[-1]["close"]
            log("  %-7s ✅ %5d 根  %s → %s  最新收=%s" % (
                PERIOD_NAME[p], len(df), str(first)[:16], str(last)[:16], lastclose))
        except Exception as e:
            log("  %-7s ❌ %s: %s" % (PERIOD_NAME[p], type(e).__name__, str(e)[:60]))
    log("")

with open("tools/_kline_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
