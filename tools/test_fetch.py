# -*- coding: utf-8 -*-
"""抓取端到端测试：调用 src.fetcher.fetch_all()，打印 14 个品种结果。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher import fetch_all
from src.symbols import GROUPS

OUT = []


def log(*args):
    OUT.append(" ".join(str(a) for a in args))


quotes = fetch_all()

log("品种数:", len(quotes))
log("")
for g in GROUPS:
    log("【%s】" % g["name"])
    for it in g["items"]:
        q = quotes.get(it["name"])
        if q is None:
            log("  %-10s  ❌ 无数据" % it["name"])
        else:
            log("  %-10s  价格=%-12s 涨跌幅=%s%%  单位=%s" %
                (it["name"], q["price"], q["change"], it["unit"]))

with open("tools/_fetch_test.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done lines=", len(OUT))
